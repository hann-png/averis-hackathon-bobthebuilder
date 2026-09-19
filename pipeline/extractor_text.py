"""
extractor_text.py ? Parse plain-text SI/BL attachments into the 7 canonical fields.

Strategy (AI-Primary):
  1. Primary path: Gemini API extracts and normalizes the 7 canonical fields
     from SI/BL document text for every attachment.
  2. Fast cross-check: Synonym dictionary (regex label parsing) cross-checks
     Gemini's answers. Disagreements signal ambiguity and surface in review flags.
  3. Fallback: Synonym dictionary parsing if Gemini is unavailable or rate-limited.

Canonical fields:
  shipper, consignee, notify_party, port_of_loading, port_of_discharge,
  container_count, gross_weight_kg
"""

import os
import re
import json
import logging

logger = logging.getLogger(__name__)

CANONICAL_FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]

BLANK_TOKENS = {"???", "_______", "tba", "tbc", "n/a", "____mt", "", "none", "missing"}


# ?? Synonym Dictionary / Label Matching ?????????????????????????????????????

def match_canonical_field(label: str) -> str | None:
    """
    Map raw label text to a canonical field name.
    Cleans punctuation, language annotations, and handles synonym variations.
    """
    clean = re.sub(r'[一-鿿]', '', label)
    l = clean.lower().strip().rstrip(':').strip()
    l = re.sub(r'[^\w\s]', ' ', l)
    l = ' '.join(l.split())

    if 'net weight' in l or 'net wt' in l:
        return None
    if any(k in l for k in [
        'booking', 'hs code', 'vessel', 'voyage', 'freight',
        'carrier', 'invoice', 'certificate', 'commodity'
    ]):
        return None

    # Check notify first (before consignee because of intermediate consignee phrases)
    if 'notify' in l:
        return 'notify_party'
    if 'consignee' in l or 'to the order of' in l or 'cnee' in l:
        return 'consignee'
    if 'shipper' in l or 'exporter' in l or 'seller' in l or 'principal' in l:
        return 'shipper'

    if 'discharge' in l or 'pod' in l or 'destination' in l:
        return 'port_of_discharge'
    if 'loading' in l or 'load port' in l or 'pol' in l:
        return 'port_of_loading'

    if 'container' in l or 'containers' in l:
        return 'container_count'
    if 'gross' in l or ('weight' in l and 'net' not in l) or ('wt' in l and 'net' not in l):
        return 'gross_weight_kg'

    return None


def detect_document_type(text: str) -> str | None:
    """Detect if the document is an SI, BL, or non-shipping doc type."""
    upper = text[:600].upper()

    if "COMMERCIAL INVOICE" in upper:
        return "COMMERCIAL_INVOICE"
    if "PACKING LIST" in upper:
        return "PACKING_LIST"
    if "CERTIFICATE OF ORIGIN" in upper:
        return "CERTIFICATE_OF_ORIGIN"

    if "SHIPPING INSTRUCTION" in upper:
        return "SI"
    if "BILL OF LADING" in upper:
        return "BL"

    return None


def is_stop_label(line: str) -> bool:
    l = line.lower().strip()
    return any(k in l for k in [
        'vessel', 'voyage', 'carrier', 'container no', 'description',
        'hs code', 'freight', 'booking', 'b/l number', 'b/l no', 'commodity',
        'kinds of packages'
    ])


def parse_lines_to_fields(lines: list[str]) -> dict[str, str]:
    """
    Parse lines containing label-value pairs into canonical fields using synonym dictionary.
    Handles both colon-separated and line-separated labels robustly.
    """
    fields = {}
    i = 0
    current_canonical = None
    current_val = []

    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith('=') or line.startswith('-'):
            continue

        # 1. Check colon-separated label: value
        colon_idx = line.find(':')
        if colon_idx != -1:
            raw_label = line[:colon_idx].strip()
            raw_val = line[colon_idx + 1:].strip()
            canonical = match_canonical_field(raw_label)
            if canonical:
                if current_canonical:
                    fields[current_canonical] = ' '.join(current_val).strip()
                current_canonical = canonical
                current_val = [raw_val] if raw_val else []
                # Ports, container count, weight are single-line values
                if canonical in ('port_of_loading', 'port_of_discharge', 'container_count', 'gross_weight_kg') and raw_val:
                    fields[current_canonical] = raw_val
                    current_canonical = None
                    current_val = []
                continue

        # 2. Check full line as a label
        canonical = match_canonical_field(line)
        if canonical:
            if current_canonical:
                fields[current_canonical] = ' '.join(current_val).strip()
            current_canonical = canonical
            current_val = []
            continue

        # 3. Check stop label
        if is_stop_label(line):
            if current_canonical:
                fields[current_canonical] = ' '.join(current_val).strip()
                current_canonical = None
                current_val = []
            continue

        # 4. Continuation line
        if current_canonical:
            current_val.append(line)
            if current_canonical in ('port_of_loading', 'port_of_discharge'):
                fields[current_canonical] = ' '.join(current_val).strip()
                current_canonical = None
                current_val = []

    if current_canonical and current_val:
        fields[current_canonical] = ' '.join(current_val).strip()

    return fields


# ?? Gemini Client for Extraction ???????????????????????????????????????????

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def extract_fields_by_gemini(text: str) -> dict[str, str]:
    """
    Primary extraction path: Extract the 7 canonical fields from document text using Gemini.
    """
    client = _get_gemini_client()

    prompt = f"""You are an expert logistics parser. Extract the 7 canonical shipping fields from this Shipping Instruction (SI) or Bill of Lading (BL):

Fields:
1. shipper: Shipper or exporter company name and address
2. consignee: Consignee company name and address
3. notify_party: Notify party company name and address
4. port_of_loading: Port of loading (POL)
5. port_of_discharge: Port of discharge (POD)
6. container_count: Total number of containers (e.g. "4 x 40'HC", "1", "4")
7. gross_weight_kg: Total gross weight with unit (e.g. "82,932 KG", "21577 KG")

If a field is missing, placeholder (e.g. N/A, TBA, TBC, ???, _______), or unstated in the text, return "" (empty string) for that field.

Document Text:
{text[:4000]}
"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "object",
                "properties": {
                    "shipper": {"type": "string"},
                    "consignee": {"type": "string"},
                    "notify_party": {"type": "string"},
                    "port_of_loading": {"type": "string"},
                    "port_of_discharge": {"type": "string"},
                    "container_count": {"type": "string"},
                    "gross_weight_kg": {"type": "string"},
                },
                "required": [
                    "shipper", "consignee", "notify_party",
                    "port_of_loading", "port_of_discharge",
                    "container_count", "gross_weight_kg",
                ],
            },
            "temperature": 0.0,
        },
    )

    result = json.loads(response.text)
    return {k: str(result.get(k, "")).strip() for k in CANONICAL_FIELDS}


def cross_check_disagreements(gemini_fields: dict[str, str], rule_fields: dict[str, str]) -> list[str]:
    """
    Cross-check Gemini extraction against synonym dictionary extraction.
    Returns a list of fields where the two methods disagree significantly,
    signaling genuine ambiguity worth surfacing for human review.
    """
    disagreements = []

    for field in CANONICAL_FIELDS:
        g_val = gemini_fields.get(field, "").strip()
        r_val = rule_fields.get(field, "").strip()

        # Check for blanks/placeholders
        g_blank = not g_val or g_val.lower() in BLANK_TOKENS or any(t in g_val.lower() for t in ['???', '____', 'n/a', 'tba'])
        r_blank = not r_val or r_val.lower() in BLANK_TOKENS or any(t in r_val.lower() for t in ['???', '____', 'n/a', 'tba'])

        if g_blank and r_blank:
            continue

        # If one found a value and the other is blank/placeholder, that is a potential conflict
        if g_blank != r_blank:
            disagreements.append(field)
            continue

        # Both have values: compare normalized values
        if field == "container_count":
            g_nums = re.findall(r'\d+', g_val)
            r_nums = re.findall(r'\d+', r_val)
            g_cnt = int(g_nums[0]) if g_nums else None
            r_cnt = int(r_nums[0]) if r_nums else None
            if g_cnt is not None and r_cnt is not None and g_cnt != r_cnt:
                disagreements.append(field)

        elif field == "gross_weight_kg":
            g_clean = g_val.replace(',', '').replace(' ', '')
            r_clean = r_val.replace(',', '').replace(' ', '')
            g_m = re.search(r'([\d.]+)', g_clean)
            r_m = re.search(r'([\d.]+)', r_clean)
            if g_m and r_m:
                try:
                    if abs(float(g_m.group(1)) - float(r_m.group(1))) > 1.0:
                        disagreements.append(field)
                except ValueError:
                    if g_clean != r_clean:
                        disagreements.append(field)
            elif g_clean != r_clean:
                disagreements.append(field)

        elif field in ("port_of_loading", "port_of_discharge"):
            def norm_port(p):
                p = re.sub(r'\([A-Z0-9]+\)', '', p).upper()
                p = re.sub(r'[^\w\s]', ' ', p)
                return ' '.join(p.split())

            if norm_port(g_val) != norm_port(r_val):
                disagreements.append(field)

        else:  # shipper, consignee, notify_party
            def norm_text(t):
                t = t.upper()
                t = re.sub(r'[^\w\s]', ' ', t)
                return ' '.join(t.split())

            g_norm = norm_text(g_val)
            r_norm = norm_text(r_val)
            # Check if neither is a substring of the other and they differ
            if g_norm != r_norm and not (g_norm in r_norm or r_norm in g_norm):
                disagreements.append(field)

    return sorted(disagreements)


# ?? Extraction Result & Public API ??????????????????????????????????????????

class ExtractionResult:
    """Structured extraction result."""

    def __init__(
        self,
        fields: dict,
        doc_type: str | None,
        is_readable: bool,
        has_wrong_type: bool = False,
        wrong_type_desc: str | None = None,
        has_disagreement: bool = False,
        disagreement_fields: list[str] | None = None,
        extracted_by: str = "gemini",
        rule_fields: dict | None = None,
        gemini_fields: dict | None = None,
    ):
        self.fields = fields
        self.doc_type = doc_type
        self.is_readable = is_readable
        self.has_wrong_type = has_wrong_type
        self.wrong_type_desc = wrong_type_desc
        self.has_disagreement = has_disagreement
        self.disagreement_fields = disagreement_fields or []
        self.extracted_by = extracted_by
        self.rule_fields = rule_fields or {}
        self.gemini_fields = gemini_fields or {}

    def missing_fields(self) -> list[str]:
        """Return canonical fields that are missing, placeholder, or have unresolved extraction disagreement."""
        missing = []
        for field in CANONICAL_FIELDS:
            val = self.fields.get(field, "").strip().lower()
            if not val or val in BLANK_TOKENS or any(tok in val for tok in ['???', '____', 'n/a', 'tba', 'tbc']):
                missing.append(field)
        # Ambiguous disagreement fields also contribute to review flag
        for field in self.disagreement_fields:
            if field not in missing:
                missing.append(field)
        return missing


def extract_text(text: str, expected_type: str = None) -> ExtractionResult:
    """
    Extract canonical fields from plain text document content.
    Primary: Gemini API.
    Cross-check: Synonym dictionary to detect ambiguity/disagreements.
    Fallback: Synonym dictionary parsing if Gemini is unavailable.
    """
    if not text or len(text.strip()) < 10:
        return ExtractionResult(fields={}, doc_type=None, is_readable=False)

    doc_type = detect_document_type(text)
    wrong_types = {"COMMERCIAL_INVOICE", "PACKING_LIST", "CERTIFICATE_OF_ORIGIN"}
    if doc_type in wrong_types:
        return ExtractionResult(
            fields={}, doc_type=doc_type, is_readable=True,
            has_wrong_type=True, wrong_type_desc=doc_type
        )

    # Fast synonym dictionary / regex parsing (for cross-check and fallback)
    lines = text.splitlines()
    rule_fields = parse_lines_to_fields(lines)

    # Primary path: Gemini API
    try:
        gemini_fields = extract_fields_by_gemini(text)
        disagreements = cross_check_disagreements(gemini_fields, rule_fields)
        return ExtractionResult(
            fields=dict(gemini_fields),
            doc_type=doc_type,
            is_readable=True,
            has_disagreement=len(disagreements) > 0,
            disagreement_fields=disagreements,
            extracted_by="gemini",
            rule_fields=rule_fields,
            gemini_fields=gemini_fields,
        )
    except Exception as e:
        logger.warning(f"Gemini text extraction unavailable ({e}); using synonym dictionary")
        return ExtractionResult(
            fields=rule_fields,
            doc_type=doc_type,
            is_readable=True,
            has_disagreement=False,
            disagreement_fields=[],
            extracted_by="rule",
            rule_fields=rule_fields,
            gemini_fields={},
        )
