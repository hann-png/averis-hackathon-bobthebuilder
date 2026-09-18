"""
extractor_docs.py — Extract fields from PDF, DOCX, and XLSX attachments.

Works with both local file paths and in-memory bytes (for HTTP server support):
- PDF: Extracted directly via pypdf; detects unreadable / corrupted PDFs.
- DOCX: Extracted from tables and paragraphs via python-docx.
- XLSX: Extracted from rows via openpyxl.
"""

import io
import os
import re
import json
import logging
from pathlib import Path

import pypdf
import docx
import openpyxl

from pipeline.extractor_text import (
    CANONICAL_FIELDS,
    ExtractionResult,
    match_canonical_field,
    parse_lines_to_fields,
    detect_document_type,
)

logger = logging.getLogger(__name__)


def extract_from_docx(file_source) -> ExtractionResult:
    """Extract fields from a docx file path or bytes IO."""
    try:
        source = io.BytesIO(file_source) if isinstance(file_source, bytes) else file_source
        doc = docx.Document(source)
        fields = {}
        for t in doc.tables:
            for r in t.rows:
                if len(r.cells) >= 2:
                    raw_label = r.cells[0].text.strip()
                    raw_val = r.cells[1].text.strip().replace('\n', ' ')
                    canonical = match_canonical_field(raw_label)
                    if canonical:
                        fields[canonical] = raw_val

        # Also check paragraphs if any fields are missing
        if len(fields) < len(CANONICAL_FIELDS):
            lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            extra = parse_lines_to_fields(lines)
            for k, v in extra.items():
                if k not in fields:
                    fields[k] = v

        full_text = "\n".join(p.text for p in doc.paragraphs)
        doc_type = detect_document_type(full_text)
        return ExtractionResult(fields=fields, doc_type=doc_type, is_readable=True)
    except Exception as e:
        logger.error(f"Failed to extract docx: {e}")
        return ExtractionResult(fields={}, doc_type=None, is_readable=False)


def extract_from_xlsx(file_source) -> ExtractionResult:
    """Extract fields from an xlsx file path or bytes IO."""
    try:
        source = io.BytesIO(file_source) if isinstance(file_source, bytes) else file_source
        wb = openpyxl.load_workbook(source, data_only=True)
        fields = {}
        text_lines = []
        for row in wb.active.iter_rows(values_only=True):
            if row and row[0]:
                raw_label = str(row[0]).strip()
                canonical = match_canonical_field(raw_label)
                if canonical:
                    vals = [str(c).strip() for c in row[1:] if c is not None and str(c).strip()]
                    fields[canonical] = ' '.join(vals)
                text_lines.append(" | ".join(str(c) for c in row if c is not None))

        doc_type = detect_document_type("\n".join(text_lines))
        return ExtractionResult(fields=fields, doc_type=doc_type, is_readable=True)
    except Exception as e:
        logger.error(f"Failed to extract xlsx: {e}")
        return ExtractionResult(fields={}, doc_type=None, is_readable=False)


def extract_from_pdf(file_source) -> ExtractionResult:
    """
    Extract fields from a pdf file path or bytes IO.
    Detects corrupt stream errors or blank/image-only PDFs as unreadable.
    """
    try:
        source = io.BytesIO(file_source) if isinstance(file_source, bytes) else file_source
        reader = pypdf.PdfReader(source)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip() or len(text.strip()) < 15:
            return ExtractionResult(fields={}, doc_type=None, is_readable=False)

        doc_type = detect_document_type(text)
        wrong_types = {"COMMERCIAL_INVOICE", "PACKING_LIST", "CERTIFICATE_OF_ORIGIN"}
        if doc_type in wrong_types:
            return ExtractionResult(
                fields={}, doc_type=doc_type, is_readable=True,
                has_wrong_type=True, wrong_type_desc=doc_type
            )

        fields = parse_lines_to_fields(text.splitlines())
        return ExtractionResult(fields=fields, doc_type=doc_type, is_readable=True)
    except Exception as e:
        logger.info(f"PDF unreadable or corrupted: {e}")
        return ExtractionResult(fields={}, doc_type=None, is_readable=False)


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
                text = file_source.decode("utf-8", errors="replace")
            else:
                with open(file_source, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            from pipeline.extractor_text import extract_text
            return extract_text(text)
        except Exception as e:
            return ExtractionResult(fields={}, doc_type=None, is_readable=False)
    elif ext == ".docx":
        return extract_from_docx(file_source)
    elif ext == ".xlsx":
        return extract_from_xlsx(file_source)
    elif ext == ".pdf":
        return extract_from_pdf(file_source)
    else:
        return ExtractionResult(fields={}, doc_type=None, is_readable=False)
