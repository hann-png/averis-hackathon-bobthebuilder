"""
extractor_docs.py — Extract fields from PDF, DOCX, and XLSX attachments.

Works with both local file paths and in-memory bytes (for HTTP server support):
- PDF: Extracted directly via pypdf; detects unreadable / corrupted PDFs.
- DOCX: Extracted from tables and paragraphs via python-docx.
- XLSX: Extracted from rows via openpyxl.
"""

import io
import json
import logging
import os
from pathlib import Path

import pypdf
import docx
import openpyxl

from pipeline.extractor_text import (
    CANONICAL_FIELDS,
    ExtractionResult,
    match_canonical_field,
    parse_lines_to_fields_with_confidence,
    _label_confidence,
    detect_document_type,
)

logger = logging.getLogger(__name__)


def extract_from_docx(file_source) -> ExtractionResult:
    """Extract fields from a docx file path or bytes IO."""
    try:
        source = (
            io.BytesIO(file_source)
            if isinstance(file_source, bytes)
            else file_source
        )

        doc = docx.Document(source)

        fields = {}
        confidence = {}

        for table in doc.tables:
            for row in table.rows:
                if len(row.cells) >= 2:
                    raw_label = row.cells[0].text.strip()
                    raw_val = row.cells[1].text.strip().replace("\n", " ")

                    canonical = match_canonical_field(raw_label)

                    if canonical:
                        fields[canonical] = raw_val
                        confidence[canonical] = _label_confidence(
                            raw_label,
                            canonical,
                        )

        # Also check paragraphs if any fields are missing
        if len(fields) < len(CANONICAL_FIELDS):
            lines = [
                p.text.strip()
                for p in doc.paragraphs
                if p.text.strip()
            ]

            extra_fields, extra_confidence = (
                parse_lines_to_fields_with_confidence(lines)
            )

            for key, value in extra_fields.items():
                if key not in fields:
                    fields[key] = value
                    confidence[key] = extra_confidence.get(key, 0.0)

        full_text = "\n".join(p.text for p in doc.paragraphs)
        doc_type = detect_document_type(full_text)

        return ExtractionResult(
            fields=fields,
            doc_type=doc_type,
            is_readable=True,
            confidence=confidence,
        )

    except Exception as e:
        logger.error(f"Failed to extract docx: {e}")

        return ExtractionResult(
            fields={},
            doc_type=None,
            is_readable=False,
        )


def extract_from_xlsx(file_source) -> ExtractionResult:
    """Extract fields from an xlsx file path or bytes IO."""
    try:
        source = (
            io.BytesIO(file_source)
            if isinstance(file_source, bytes)
            else file_source
        )

        wb = openpyxl.load_workbook(source, data_only=True)

        fields = {}
        confidence = {}
        text_lines = []

        for row in wb.active.iter_rows(values_only=True):
            if row and row[0]:
                raw_label = str(row[0]).strip()
                canonical = match_canonical_field(raw_label)

                if canonical:
                    vals = [
                        str(cell).strip()
                        for cell in row[1:]
                        if cell is not None and str(cell).strip()
                    ]

                    fields[canonical] = " ".join(vals)

                    confidence[canonical] = _label_confidence(
                        raw_label,
                        canonical,
                    )

                text_lines.append(
                    " | ".join(
                        str(cell)
                        for cell in row
                        if cell is not None
                    )
                )

        doc_type = detect_document_type("\n".join(text_lines))

        return ExtractionResult(
            fields=fields,
            doc_type=doc_type,
            is_readable=True,
            confidence=confidence,
        )

    except Exception as e:
        logger.error(f"Failed to extract xlsx: {e}")

        return ExtractionResult(
            fields={},
            doc_type=None,
            is_readable=False,
        )


def _extract_pdf_via_vision(raw_bytes: bytes) -> ExtractionResult:
    """Fall back to sending raw PDF bytes to Gemini vision model for scanned/image-only documents."""
    try:
        from google.genai import types
        from pipeline.gemini_client import generate_content

        pdf_part = types.Part.from_bytes(data=raw_bytes, mime_type="application/pdf")
        prompt = """You are an expert shipping document specialist.
Analyze this scanned/image document (Shipping Instruction or Bill of Lading).
Determine the document type and extract the 7 canonical shipping fields:
- shipper
- consignee
- notify_party
- port_of_loading
- port_of_discharge
- container_count
- gross_weight_kg

If a field is missing, placeholder, or unstated, return an empty string for that field."""

        response = generate_content(
            contents=[prompt, pdf_part],
            config={
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "doc_type": {
                            "type": "string",
                            "enum": [
                                "SI",
                                "BL",
                                "COMMERCIAL_INVOICE",
                                "PACKING_LIST",
                                "CERTIFICATE_OF_ORIGIN",
                                "OTHER",
                            ],
                        },
                        "shipper": {"type": "string"},
                        "consignee": {"type": "string"},
                        "notify_party": {"type": "string"},
                        "port_of_loading": {"type": "string"},
                        "port_of_discharge": {"type": "string"},
                        "container_count": {"type": "string"},
                        "gross_weight_kg": {"type": "string"},
                    },
                    "required": [
                        "doc_type",
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

        parsed = json.loads(response.text)
        doc_type = parsed.get("doc_type", "BL")
        fields = {k: parsed.get(k, "") for k in CANONICAL_FIELDS}
        confidence = {k: 0.9 if fields[k] else 0.0 for k in CANONICAL_FIELDS}

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

        return ExtractionResult(
            fields=fields,
            doc_type=doc_type,
            is_readable=True,
            confidence=confidence,
        )

    except Exception as e:
        logger.warning(f"PDF vision fallback unavailable ({e}); marking as unreadable")
        return ExtractionResult(
            fields={},
            doc_type=None,
            is_readable=False,
        )


def extract_from_pdf(file_source) -> ExtractionResult:
    """
    Extract fields from a pdf file path or bytes IO.
    Detects corrupt stream errors or blank/image-only PDFs as unreadable.
    Falls back to Gemini vision model before declaring unreadable.
    """
    try:
        raw_bytes = None
        if isinstance(file_source, bytes):
            raw_bytes = file_source
            source = io.BytesIO(file_source)
        elif isinstance(file_source, (str, Path)) and os.path.exists(file_source):
            with open(file_source, "rb") as f:
                raw_bytes = f.read()
            source = io.BytesIO(raw_bytes)
        else:
            source = file_source

        reader = pypdf.PdfReader(source)

        text = "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )

        if not text.strip() or len(text.strip()) < 15:
            return ExtractionResult(
                fields={},
                doc_type=None,
                is_readable=False,
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

        fields, confidence = parse_lines_to_fields_with_confidence(
            text.splitlines()
        )

        return ExtractionResult(
            fields=fields,
            doc_type=doc_type,
            is_readable=True,
            confidence=confidence,
        )

    except Exception as e:
        logger.info(f"PDF unreadable or corrupted: {e}")

        return ExtractionResult(
            fields={},
            doc_type=None,
            is_readable=False,
        )


def extract_document(file_source, filename: str = "") -> ExtractionResult:
    """
    Unified extraction entry point for any attachment path or raw bytes.
    Dispatches based on extension (.txt, .docx, .xlsx, .pdf).
    """
    if isinstance(file_source, str) and not filename:
        filename = file_source

    ext = Path(filename).suffix.lower()

    if ext == ".txt":
        try:
            if isinstance(file_source, bytes):
                text = file_source.decode(
                    "utf-8",
                    errors="replace",
                )
            else:
                with open(
                    file_source,
                    encoding="utf-8",
                    errors="replace",
                ) as f:
                    text = f.read()

            from pipeline.extractor_text import extract_text

            return extract_text(text)

        except Exception:
            return ExtractionResult(
                fields={},
                doc_type=None,
                is_readable=False,
            )

    elif ext == ".docx":
        return extract_from_docx(file_source)

    elif ext == ".xlsx":
        return extract_from_xlsx(file_source)

    elif ext == ".pdf":
        return extract_from_pdf(file_source)

    else:
        return ExtractionResult(
            fields={},
            doc_type=None,
            is_readable=False,
        )