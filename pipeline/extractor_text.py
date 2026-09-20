"""
extractor_text.py — Parse plain-text SI/BL attachments into the 7 canonical fields.

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

BLANK_TOKENS = {
    "???",
    "_______",
    "tba",
    "tbc",
    "n/a",
    "____mt",
    "",
    "none",
    "missing",
}


# ── Synonym Dictionary / Label Matching ─────────────────────────────────────

def match_canonical_field(label: str) -> str | None:
    """
    Map raw label text to a canonical field name.
    Cleans punctuation, language annotations, and handles synonym variations.
    """
    clean = re.sub(r'[\u4e00-\u9fff]', '', label)

    l = clean.lower().strip().rstrip(':').strip()
    l = re.sub(r'[^\w\s]', ' ', l)
    l = ' '.join(l.split())

    if 'net weight' in l or 'net wt' in l:
        return None

    if any(k in l for k in [
        'booking',
        'hs code',
        'vessel',
        'voyage',
        'freight',
        'carrier',
        'invoice',
        'certificate',
        'commodity',
    ]):
        return None

    # Check notify first because some labels contain "consignee".
    if 'notify' in l:
        return 'notify_party'

    if (
        'consignee' in l
        or 'to the order of' in l
        or 'cnee' in l
    ):
        return 'consignee'

    if (
        'shipper' in l
        or 'exporter' in l
        or 'seller' in l
        or 'principal' in l
    ):
        return 'shipper'

    if (
        'discharge' in l
        or 'pod' in l
        or 'destination' in l
    ):
        return 'port_of_discharge'

    if (
        'loading' in l
        or 'load port' in l
        or 'pol' in l
    ):
        return 'port_of_loading'

    if 'container' in l or 'containers' in l:
        return 'container_count'

    if (
        'gross' in l
        or ('weight' in l and 'net' not in l)
        or ('wt' in l and 'net' not in l)
    ):
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
        'vessel',
        'voyage',
        'carrier',
        'container no',
        'description',
        'hs code',
        'freight',
        'booking',
        'b/l number',
        'b/l no',
        'commodity',
        'kinds of packages',
    ])


# ── Confidence Helpers ───────────────────────────────────────────────────────

def _label_confidence(raw_label: str, canonical: str) -> float:
    """
    Estimate confidence from the strength of the matched document label.

    Returned internally as 0.0–1.0.
    """
    clean = re.sub(r'[\u4e00-\u9fff]', '', raw_label)

    label = clean.lower().strip().rstrip(':').strip()
    label = re.sub(r'[^\w\s]', ' ', label)
    label = ' '.join(label.split())

    exact_labels = {
        "shipper": {"shipper"},
        "consignee": {"consignee"},
        "notify_party": {"notify party", "notify"},
        "port_of_loading": {"port of loading"},
        "port_of_discharge": {"port of discharge"},
        "container_count": {"container count", "containers"},
        "gross_weight_kg": {"gross weight", "gross weight kg"},
    }

    strong_aliases = {
        "shipper": {"exporter"},
        "consignee": {"cnee", "to the order of"},
        "notify_party": {"notify party intermediate consignee"},
        "port_of_loading": {"load port", "pol"},
        "port_of_discharge": {"pod", "destination"},
        "container_count": {"container"},
        "gross_weight_kg": {"gross wt", "gross"},
    }

    weaker_aliases = {
        "shipper": {"seller", "principal"},
    }

    if label in exact_labels.get(canonical, set()):
        return 0.99

    if label in strong_aliases.get(canonical, set()):
        return 0.93

    if label in weaker_aliases.get(canonical, set()):
        return 0.82

    return 0.78


def parse_lines_to_fields_with_confidence(
    lines: list[str],
) -> tuple[dict[str, str], dict[str, float]]:
    """
    Parse fields with the synonym dictionary and produce confidence metadata.

    This also preserves compatibility with extractor_docs.py.
    """
    fields = {}
    confidence = {}

    current_canonical = None
    current_val = []
    current_confidence = 0.0

    def save_current():
        nonlocal current_canonical
        nonlocal current_val
        nonlocal current_confidence

        if current_canonical and current_val:
            value = ' '.join(current_val).strip()

            if value:
                fields[current_canonical] = value
                confidence[current_canonical] = current_confidence

        current_canonical = None
        current_val = []
        current_confidence = 0.0

    for raw_line in lines:
        line = raw_line.strip()

        if (
            not line
            or line.startswith('=')
            or line.startswith('-')
        ):
            continue

        # 1. Explicit "Label: Value"
        colon_idx = line.find(':')

        if colon_idx != -1:
            raw_label = line[:colon_idx].strip()
            raw_val = line[colon_idx + 1:].strip()

            canonical = match_canonical_field(raw_label)

            if canonical:
                save_current()

                label_conf = _label_confidence(
                    raw_label,
                    canonical,
                )

                if raw_val:
                    fields[canonical] = raw_val
                    confidence[canonical] = label_conf

                else:
                    current_canonical = canonical
                    current_val = []

                    current_confidence = max(
                        0.0,
                        label_conf - 0.04,
                    )

                continue

        # 2. Full line is recognised as a label
        canonical = match_canonical_field(line)

        if canonical:
            save_current()

            current_canonical = canonical
            current_val = []

            current_confidence = max(
                0.0,
                _label_confidence(line, canonical) - 0.06,
            )

            continue

        # 3. Stop label
        if is_stop_label(line):
            save_current()
            continue

        # 4. Continuation/value line
        if current_canonical:
            current_val.append(line)

            if current_canonical in (
                'port_of_loading',
                'port_of_discharge',
            ):
                save_current()

    save_current()

    return fields, confidence


def parse_lines_to_fields(lines: list[str]) -> dict[str, str]:
    """
    Backward-compatible synonym dictionary parser.

    Existing callers continue receiving only the fields dictionary.
    """
    fields, _ = parse_lines_to_fields_with_confidence(lines)

    return fields


# ── Gemini Client for Extraction via Resilient Pool ──────────────────────────

from pipeline.gemini_client import generate_content


def extract_fields_by_gemini(text: str) -> dict[str, str]:
    """
    Primary extraction path.

    Extract the 7 canonical fields from document text using Gemini.
    """
    prompt = f"""
You are an expert logistics parser.

Extract the 7 canonical shipping fields from this Shipping Instruction (SI)
or Bill of Lading (BL):

Fields:

1. shipper:
   Shipper or exporter company name and address

2. consignee:
   Consignee company name and address

3. notify_party:
   Notify party company name and address

4. port_of_loading:
   Port of loading (POL)

5. port_of_discharge:
   Port of discharge (POD)

6. container_count:
   Total number of containers
   Examples: "4 x 40'HC", "1", "4"

7. gross_weight_kg:
   Total gross weight with unit
   Examples: "82,932 KG", "21577 KG"

If a field is missing, placeholder
(e.g. N/A, TBA, TBC, ???, _______),
or unstated in the text,
return an empty string for that field.

Document Text:

{text[:4000]}
"""

    response = generate_content(
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "object",
                "properties": {
                    "shipper": {
                        "type": "string",
                    },
                    "consignee": {
                        "type": "string",
                    },
                    "notify_party": {
                        "type": "string",
                    },
                    "port_of_loading": {
                        "type": "string",
                    },
                    "port_of_discharge": {
                        "type": "string",
                    },
                    "container_count": {
                        "type": "string",
                    },
                    "gross_weight_kg": {
                        "type": "string",
                    },
                },
                "required": [
                    "shipper",
                    "consignee",
                    "notify_party",
                    "port_of_loading",
                    "port_of_discharge",
                    "container_count",
                    "gross_weight_kg",
                ],
            },
            "temperature": 0.0,
        },
    )

    result = json.loads(response.text)

    return {
        key: str(result.get(key, "")).strip()
        for key in CANONICAL_FIELDS
    }


# ── Gemini / Rule Cross-check ────────────────────────────────────────────────

def cross_check_disagreements(
    gemini_fields: dict[str, str],
    rule_fields: dict[str, str],
) -> list[str]:
    """
    Cross-check Gemini extraction against synonym dictionary extraction.

    Returns fields where the methods disagree significantly.
    """
    disagreements = []

    for field in CANONICAL_FIELDS:
        g_val = gemini_fields.get(
            field,
            "",
        ).strip()

        r_val = rule_fields.get(
            field,
            "",
        ).strip()

        g_blank = (
            not g_val
            or g_val.lower() in BLANK_TOKENS
            or any(
                token in g_val.lower()
                for token in [
                    '???',
                    '____',
                    'n/a',
                    'tba',
                ]
            )
        )

        r_blank = (
            not r_val
            or r_val.lower() in BLANK_TOKENS
            or any(
                token in r_val.lower()
                for token in [
                    '???',
                    '____',
                    'n/a',
                    'tba',
                ]
            )
        )

        if g_blank and r_blank:
            continue

        # One parser found a value and the other did not.
        if g_blank != r_blank:
            disagreements.append(field)
            continue

        if field == "container_count":
            g_nums = re.findall(
                r'\d+',
                g_val,
            )

            r_nums = re.findall(
                r'\d+',
                r_val,
            )

            g_cnt = (
                int(g_nums[0])
                if g_nums
                else None
            )

            r_cnt = (
                int(r_nums[0])
                if r_nums
                else None
            )

            if (
                g_cnt is not None
                and r_cnt is not None
                and g_cnt != r_cnt
            ):
                disagreements.append(field)

        elif field == "gross_weight_kg":
            g_clean = (
                g_val
                .replace(',', '')
                .replace(' ', '')
            )

            r_clean = (
                r_val
                .replace(',', '')
                .replace(' ', '')
            )

            g_match = re.search(
                r'([\d.]+)',
                g_clean,
            )

            r_match = re.search(
                r'([\d.]+)',
                r_clean,
            )

            if g_match and r_match:
                try:
                    difference = abs(
                        float(g_match.group(1))
                        - float(r_match.group(1))
                    )

                    if difference > 1.0:
                        disagreements.append(field)

                except ValueError:
                    if g_clean != r_clean:
                        disagreements.append(field)

            elif g_clean != r_clean:
                disagreements.append(field)

        elif field in (
            "port_of_loading",
            "port_of_discharge",
        ):

            def norm_port(port):
                port = re.sub(
                    r'\([A-Z0-9]+\)',
                    '',
                    port,
                ).upper()

                port = re.sub(
                    r'[^\w\s]',
                    ' ',
                    port,
                )

                return ' '.join(
                    port.split()
                )

            if norm_port(g_val) != norm_port(r_val):
                disagreements.append(field)

        else:
            # shipper / consignee / notify party
            def norm_text(value):
                value = value.upper()

                value = re.sub(
                    r'[^\w\s]',
                    ' ',
                    value,
                )

                return ' '.join(
                    value.split()
                )

            g_norm = norm_text(g_val)
            r_norm = norm_text(r_val)

            if (
                g_norm != r_norm
                and not (
                    g_norm in r_norm
                    or r_norm in g_norm
                )
            ):
                disagreements.append(field)

    return sorted(disagreements)


# ── Confidence Calculation ──────────────────────────────────────────────────

def build_cross_check_confidence(
    gemini_fields: dict[str, str],
    rule_fields: dict[str, str],
    disagreements: list[str],
) -> dict[str, float]:
    """
    Build confidence scores for Gemini-primary extraction.

    Confidence stays internally between 0.0 and 1.0.

    General interpretation:
      0.99 = Gemini and rule parser agree
      0.85 = Gemini found a value that rules did not confidently extract
      0.55 = Gemini/rule disagreement
      0.00 = no usable value
    """
    confidence = {}

    for field in CANONICAL_FIELDS:
        gemini_value = gemini_fields.get(
            field,
            "",
        ).strip()

        rule_value = rule_fields.get(
            field,
            "",
        ).strip()

        if not gemini_value:
            confidence[field] = 0.0
            continue

        if field in disagreements:
            confidence[field] = 0.55
            continue

        if rule_value:
            confidence[field] = 0.99
        else:
            confidence[field] = 0.85

    return confidence


# ── Extraction Result ────────────────────────────────────────────────────────

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
        confidence: dict[str, float] | None = None,
    ):
        self.fields = fields
        self.doc_type = doc_type
        self.is_readable = is_readable

        self.has_wrong_type = has_wrong_type
        self.wrong_type_desc = wrong_type_desc

        self.has_disagreement = has_disagreement
        self.disagreement_fields = (
            disagreement_fields or []
        )

        self.extracted_by = extracted_by

        self.rule_fields = (
            rule_fields or {}
        )

        self.gemini_fields = (
            gemini_fields or {}
        )

        # Stored internally as values between 0.0 and 1.0.
        self.confidence = (
            confidence or {}
        )

    def missing_fields(self) -> list[str]:
        """
        Return canonical fields that are missing, placeholders,
        or have unresolved extraction disagreements.
        """
        missing = []

        for field in CANONICAL_FIELDS:
            val = (
                self.fields
                .get(field, "")
                .strip()
                .lower()
            )

            if (
                not val
                or val in BLANK_TOKENS
                or any(
                    token in val
                    for token in [
                        '???',
                        '____',
                        'n/a',
                        'tba',
                        'tbc',
                    ]
                )
            ):
                missing.append(field)

        # Preserve team's disagreement review behaviour.
        for field in self.disagreement_fields:
            if field not in missing:
                missing.append(field)

        return missing

    def confidence_for(
        self,
        field: str,
    ) -> float:
        """
        Return normalized confidence between 0.0 and 1.0.
        """
        return float(
            self.confidence.get(
                field,
                0.0,
            )
        )

    def confidence_percent_for(
        self,
        field: str,
    ) -> float:
        """
        Return confidence as a percentage.

        Example:
            0.99 -> 99.0
        """
        return round(
            self.confidence_for(field) * 100,
            1,
        )

    def confidence_percentages(
        self,
    ) -> dict[str, float]:
        """
        Return all confidence scores as percentages.

        Example:
            {
                "shipper": 99.0,
                "consignee": 85.0
            }
        """
        return {
            field: self.confidence_percent_for(field)
            for field in CANONICAL_FIELDS
            if field in self.fields
        }

    def low_confidence_fields(
        self,
        threshold: float = 0.75,
    ) -> list[str]:
        """
        Return extracted fields whose confidence is below threshold.

        Threshold remains normalized internally.

        Example:
            0.75 = 75%
        """
        return [
            field
            for field in CANONICAL_FIELDS
            if field in self.fields
            and self.confidence_for(field) < threshold
        ]


# ── Public Extraction API ────────────────────────────────────────────────────

def extract_text(
    text: str,
    expected_type: str = None,
) -> ExtractionResult:
    """
    Extract canonical fields from plain text.

    Primary:
        Gemini API

    Cross-check:
        Synonym dictionary

    Fallback:
        Synonym dictionary if Gemini is unavailable
    """
    if not text or len(text.strip()) < 10:
        return ExtractionResult(
            fields={},
            doc_type=None,
            is_readable=False,
            confidence={},
        )

    doc_type = detect_document_type(text)

    wrong_types = {
        "COMMERCIAL_INVOICE",
        "PACKING_LIST",
        "CERTIFICATE_OF_ORIGIN",
    }

    if doc_type in wrong_types:
        return ExtractionResult(
            fields={},
            doc_type=doc_type,
            is_readable=True,
            has_wrong_type=True,
            wrong_type_desc=doc_type,
            confidence={},
        )

    # Rule parser is retained as Gemini cross-check and fallback.
    lines = text.splitlines()

    rule_fields, rule_confidence = (
        parse_lines_to_fields_with_confidence(lines)
    )

    # Primary extraction path: Gemini
    try:
        gemini_fields = extract_fields_by_gemini(
            text
        )

        disagreements = cross_check_disagreements(
            gemini_fields,
            rule_fields,
        )

        confidence = build_cross_check_confidence(
            gemini_fields,
            rule_fields,
            disagreements,
        )

        return ExtractionResult(
            fields=dict(gemini_fields),
            doc_type=doc_type,
            is_readable=True,
            has_disagreement=(
                len(disagreements) > 0
            ),
            disagreement_fields=disagreements,
            extracted_by="gemini",
            rule_fields=rule_fields,
            gemini_fields=gemini_fields,
            confidence=confidence,
        )

    except Exception as e:
        logger.warning(
            f"Gemini text extraction unavailable ({e}); "
            "using synonym dictionary"
        )

        return ExtractionResult(
            fields=rule_fields,
            doc_type=doc_type,
            is_readable=True,
            has_disagreement=False,
            disagreement_fields=[],
            extracted_by="rule",
            rule_fields=rule_fields,
            gemini_fields={},
            confidence=rule_confidence,
        )