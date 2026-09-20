"""
comparator.py — Pure deterministic field comparison between SI and BL documents.

NO AI calls. Pure Python string/number comparison with normalization.

Compares these 7 fields:
  shipper, consignee, notify_party, port_of_loading, port_of_discharge,
  container_count, gross_weight_kg
"""

import re
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


def _is_blank_or_placeholder(val: str) -> bool:
    if not val:
        return True
    v = val.strip().lower()
    return v in BLANK_TOKENS or any(p in v for p in ['???', '____', 'n/a', 'tba'])


def _normalize_text(value: str) -> str:
    """Normalize text: uppercase, alphanumeric + space only, collapsed whitespace."""
    if not value:
        return ""
    v = value.strip().upper()
    v = re.sub(r'^(TO\s+THE\s+ORDER\s+OF|TO\s+ORDER\s+OF|TO\s+ORDER)\s*[:\-]?\s*', '', v)
    v = re.sub(r'[^\w\s]', ' ', v)
    return ' '.join(v.split())


def _normalize_port(value: str) -> str:
    """Normalize port name, removing port codes like (MYPKG) or (SGSIN)."""
    if not value:
        return ""
    v = re.sub(r'\([A-Z0-9]+\)', '', value)
    return _normalize_text(v)


def _extract_container_count(value: str) -> int | None:
    """Extract numeric container count from strings like: 4 x 20'FCL, 1 x 40'HC."""
    if not value:
        return None
    m = re.search(r'(\d+)\s*[xX×]\s*\d+', value)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)', value)
    if m:
        return int(m.group(1))
    return None


def _extract_weight_kg(value: str) -> float | None:
    """Extract numeric weight in KG from strings like: 82,932 KG, 21,577 KG."""
    if not value:
        return None
    cleaned = value.replace(",", "").replace(" ", "")
    m = re.search(r'([\d.]+)', cleaned)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def compare(si_fields: dict[str, str], bl_fields: dict[str, str]) -> list[str]:
    """
    Compare SI and BL extracted fields.
    Returns a sorted list of mismatched canonical field names.
    """
    defect_fields = []

    for field in CANONICAL_FIELDS:
        si_val = si_fields.get(field, "").strip()
        bl_val = bl_fields.get(field, "").strip()

        # Skip if either is blank or placeholder
        if _is_blank_or_placeholder(si_val) or _is_blank_or_placeholder(bl_val):
            continue

        if field == "container_count":
            c_si = _extract_container_count(si_val)
            c_bl = _extract_container_count(bl_val)
            if c_si is not None and c_bl is not None and c_si != c_bl:
                defect_fields.append(field)

        elif field == "gross_weight_kg":
            w_si = _extract_weight_kg(si_val)
            w_bl = _extract_weight_kg(bl_val)
            if w_si is not None and w_bl is not None and abs(w_si - w_bl) > 1.0:
                defect_fields.append(field)

        elif field in ("port_of_loading", "port_of_discharge"):
            if _normalize_port(si_val) != _normalize_port(bl_val):
                defect_fields.append(field)

        else:  # shipper, consignee, notify_party
            if _normalize_text(si_val) != _normalize_text(bl_val):
                defect_fields.append(field)

    return sorted(defect_fields)
