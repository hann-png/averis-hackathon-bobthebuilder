"""
extractor_text.py — Parse plain-text SI/BL attachments into the 7 canonical fields.

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


def _label_confidence(raw_label: str, canonical: str) -> float:
    """
    Estimate confidence based on how strongly a raw label identifies
    a canonical field.
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

    # The label still matched match_canonical_field(), but wasn't an
    # exact known label.
    return 0.78

def parse_lines_to_fields_with_confidence(
    lines: list[str],
) -> tuple[dict[str, str], dict[str, float]]:
    """
    Parse fields while also recording confidence for each extracted value.
    """
    fields = {}
    confidence = {}

    current_canonical = None
    current_val = []
    current_confidence = 0.0

    def save_current():
        nonlocal current_canonical, current_val, current_confidence

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

        if not line or line.startswith('=') or line.startswith('-'):
            continue

        # 1. Explicit "Label: Value"
        colon_idx = line.find(':')

        if colon_idx != -1:
            raw_label = line[:colon_idx].strip()
            raw_val = line[colon_idx + 1:].strip()

            canonical = match_canonical_field(raw_label)

            if canonical:
                save_current()

                label_conf = _label_confidence(raw_label, canonical)

                if raw_val:
                    fields[canonical] = raw_val

                    # Explicit label:value is strongest extraction pattern.
                    confidence[canonical] = min(1.0, label_conf)
                else:
                    current_canonical = canonical
                    current_val = []

                    # Slightly lower because the value must be collected
                    # from following lines.
                    current_confidence = max(0.0, label_conf - 0.04)

                continue

        # 2. Whole line is a recognised label
        canonical = match_canonical_field(line)

        if canonical:
            save_current()

            current_canonical = canonical
            current_val = []

            # Separate label/value layout is slightly less certain.
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

            # Ports should only consume one following line.
            if current_canonical in (
                'port_of_loading',
                'port_of_discharge',
            ):
                save_current()

    save_current()

    return fields, confidence

def parse_lines_to_fields(lines: list[str]) -> dict[str, str]:
    """
    Backward-compatible field parser.

    Existing callers still receive only the fields dictionary.
    """
    fields, _ = parse_lines_to_fields_with_confidence(lines)
    return fields


class ExtractionResult:
    """Structured extraction result."""

    def __init__(
        self,
        fields: dict,
        doc_type: str | None,
        is_readable: bool,
        has_wrong_type: bool = False,
        wrong_type_desc: str | None = None,
        confidence: dict[str, float] | None = None,
    ):
        self.fields = fields
        self.doc_type = doc_type
        self.is_readable = is_readable
        self.has_wrong_type = has_wrong_type
        self.wrong_type_desc = wrong_type_desc

        # Confidence is stored separately so existing code can still use:
        # result.fields["shipper"]
        self.confidence = confidence or {}

    def missing_fields(self) -> list[str]:
        """Return canonical fields that are missing or contain placeholder tokens."""
        missing = []

        for field in CANONICAL_FIELDS:
            val = self.fields.get(field, "").strip().lower()

            if (
                not val
                or val in BLANK_TOKENS
                or any(
                    tok in val
                    for tok in ["???", "____", "n/a", "tba", "tbc"]
                )
            ):
                missing.append(field)

        return missing

    def confidence_for(self, field: str) -> float:
        """
        Return confidence score for one canonical field.

        Missing confidence defaults to 0.0.
        """
        return float(self.confidence.get(field, 0.0))

    def low_confidence_fields(self, threshold: float = 0.75) -> list[str]:
        """
        Return extracted fields whose confidence is below the threshold.

        Missing fields are handled separately by missing_fields().
        """
        low = []

        for field in CANONICAL_FIELDS:
            if field not in self.fields:
                continue

            if self.confidence_for(field) < threshold:
                low.append(field)

        return low
def extract_text(text: str, expected_type: str = None) -> ExtractionResult:
    """
    Extract canonical fields from plain text document content.
    """
    if not text or len(text.strip()) < 10:
        return ExtractionResult(
            fields={},
            doc_type=None,
            is_readable=False
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
        )

    lines = text.splitlines()

    fields, confidence = parse_lines_to_fields_with_confidence(lines)

    return ExtractionResult(
        fields=fields,
        doc_type=doc_type,
        is_readable=True,
        confidence=confidence,
    )