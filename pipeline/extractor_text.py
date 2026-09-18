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


def parse_lines_to_fields(lines: list[str]) -> dict[str, str]:
    """
    Parse lines containing label-value pairs into canonical fields.
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
            # Ports only take 1 line
            if current_canonical in ('port_of_loading', 'port_of_discharge'):
                fields[current_canonical] = ' '.join(current_val).strip()
                current_canonical = None
                current_val = []

    if current_canonical and current_val:
        fields[current_canonical] = ' '.join(current_val).strip()

    return fields


class ExtractionResult:
    """Structured extraction result."""

    def __init__(self, fields: dict, doc_type: str | None, is_readable: bool,
                 has_wrong_type: bool = False, wrong_type_desc: str | None = None):
        self.fields = fields
        self.doc_type = doc_type
        self.is_readable = is_readable
        self.has_wrong_type = has_wrong_type
        self.wrong_type_desc = wrong_type_desc

    def missing_fields(self) -> list[str]:
        """Return canonical fields that are missing or contain placeholder tokens."""
        missing = []
        for field in CANONICAL_FIELDS:
            val = self.fields.get(field, "").strip().lower()
            if not val or val in BLANK_TOKENS or any(tok in val for tok in ['???', '____', 'n/a', 'tba', 'tbc']):
                missing.append(field)
        return missing


def extract_text(text: str, expected_type: str = None) -> ExtractionResult:
    """
    Extract canonical fields from plain text document content.
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

    lines = text.splitlines()
    fields = parse_lines_to_fields(lines)

    return ExtractionResult(
        fields=fields, doc_type=doc_type, is_readable=True
    )
