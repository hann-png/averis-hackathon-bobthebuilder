"""
security.py — Enterprise Zero-Trust Security & Compliance Layer.

Designed for logistics document automation pipelines ingesting arbitrary
files and communications from external freight forwarders and carriers.

Core Security Pillars:
1. Zero-Trust Attachment Sanitizer (Magic bytes, extension spoofing, zip-bomb, path traversal)
2. Adversarial Prompt Injection Guard (Prevents AI poisoning / instruction hijacking)
3. PII & Financial Data Redactor (Masks sensitive data for GDPR / SOC2 compliance)
4. Cryptographic Document Provenance (SHA-256 tamper-evident integrity fingerprinting)
"""

import hashlib
import io
import logging
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

# ── 1. MAGIC BYTES & FILE SIGNATURES ─────────────────────────────────────────

MAGIC_SIGNATURES = {
    ".pdf": [b"%PDF-"],
    ".docx": [b"PK\x03\x04"],
    ".xlsx": [b"PK\x03\x04"],
}

# Known dangerous executable and script signatures
MALICIOUS_SIGNATURES = {
    "WINDOWS_EXECUTABLE_PE": b"MZ",
    "LINUX_ELF_EXECUTABLE": b"\x7fELF",
    "SHELL_SCRIPT": b"#!/",
    "JAVA_CLASS": b"\xca\xfe\xba\xbe",
}

MAX_ALLOWED_DECOMPRESSED_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_DECOMPRESSION_RATIO = 100.0  # Suspected zip bomb if uncompressed is > 100x compressed


@dataclass
class FileSecurityReport:
    filename: str
    is_safe: bool
    mime_detected: str
    sha256: str
    threats: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


class AttachmentSanitizer:
    """Validates files against malicious payload signatures, zip-bombs, and path injection."""

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filenames to prevent path traversal and null byte injection."""
        if not filename:
            return "unnamed_document"
        clean = filename.replace("\x00", "").replace("..", "")
        clean = re.sub(r'[\/\\:*?"<>|]', "_", clean)
        return clean.strip(" .")

    @staticmethod
    def validate_file(filename: str, data: Union[bytes, str]) -> FileSecurityReport:
        """
        Comprehensive zero-trust validation for an attachment.
        Verifies magic bytes, checks for extension spoofing, and scans zip archives.
        """
        threats = []
        details = {}
        raw_bytes = data.encode("utf-8") if isinstance(data, str) else data
        ext = Path(filename).suffix.lower()

        # 1. SHA-256 Provenance Hash
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        details["file_size_bytes"] = len(raw_bytes)
        details["sha256"] = sha256

        # 2. Path Traversal Check in Filename
        if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
            threats.append("PATH_TRAVERSAL_ATTEMPT")

        if "\x00" in filename:
            threats.append("NULL_BYTE_INJECTION")

        # 3. Malicious Executable Magic Byte Detection
        for threat_type, sig in MALICIOUS_SIGNATURES.items():
            if raw_bytes.startswith(sig):
                threats.append(f"MALICIOUS_PAYLOAD_DETECTED:{threat_type}")

        # 4. Extension vs Magic Bytes Verification
        mime_detected = "application/octet-stream"
        if ext in MAGIC_SIGNATURES:
            expected_sigs = MAGIC_SIGNATURES[ext]
            matched = any(raw_bytes.startswith(sig) for sig in expected_sigs)
            if not matched:
                threats.append(f"EXTENSION_SPOOFING: File claims {ext} but lacks expected magic signature")
            else:
                mime_detected = "application/pdf" if ext == ".pdf" else "application/vnd.openxmlformats"

        elif ext == ".txt":
            mime_detected = "text/plain"
            # Check for non-text binary blobs
            if b"\x00" in raw_bytes[:1024]:
                threats.append("BINARY_CONTENT_IN_TEXT_FILE")

        # 5. Zip-Bomb & Embedded Macro Scan for DOCX / XLSX
        if ext in (".docx", ".xlsx") and raw_bytes.startswith(b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    total_uncompressed = 0
                    has_macros = False
                    for member in zf.infolist():
                        total_uncompressed += member.file_size
                        # Check for VBA macros or embedded executables
                        name_lower = member.filename.lower()
                        if "vbaproject.bin" in name_lower or name_lower.endswith((".exe", ".bat", ".vbs", ".ps1")):
                            has_macros = True
                            threats.append(f"EMBEDDED_EXECUTABLE_OR_MACRO:{member.filename}")

                    compressed_size = max(len(raw_bytes), 1)
                    ratio = total_uncompressed / compressed_size
                    details["uncompressed_size_bytes"] = total_uncompressed
                    details["compression_ratio"] = round(ratio, 2)

                    if total_uncompressed > MAX_ALLOWED_DECOMPRESSED_SIZE:
                        threats.append(f"ZIP_BOMB_EXCESSIVE_SIZE:{total_uncompressed}_bytes")
                    if ratio > MAX_DECOMPRESSION_RATIO:
                        threats.append(f"ZIP_BOMB_SUSPICIOUS_RATIO:{ratio:.1f}x")

            except zipfile.BadZipFile:
                threats.append("CORRUPT_ZIP_STRUCTURE")
            except Exception as e:
                threats.append(f"ARCHIVE_INSPECTION_ERROR:{str(e)}")

        is_safe = len(threats) == 0
        return FileSecurityReport(
            filename=filename,
            is_safe=is_safe,
            mime_detected=mime_detected,
            sha256=sha256,
            threats=threats,
            details=details,
        )


# ── 2. ADVERSARIAL PROMPT INJECTION GUARD ───────────────────────────────────

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|prompts)",
    r"disregard\s+(all\s+)?(previous|prior)\s+(instructions|prompts)",
    r"system\s*override",
    r"you\s+are\s+now\s+(in\s+)?developer\s+mode",
    r"jailbreak",
    r"do\s+not\s+(report|flag)\s+any\s+(defects|mismatches)",
    r"always\s+(output|classify|mark)\s+(as\s+)?(ok|clean|matched)",
    r"output\s+status\s*[:=]\s*ok",
    r"has_defect\s*[:=]\s*false",
    r"forget\s+all\s+rules",
    r"pretend\s+you\s+are\s+an\s+unrestricted",
    r"<\|system\|>",
    r"<\|im_start\|>",
]


class PromptInjectionGuard:
    """Scans emails and document texts for prompt injection attacks designed to trick LLMs."""

    @staticmethod
    def scan_text(text: str) -> dict:
        if not text:
            return {"is_safe": True, "threat_level": "CLEAN", "matched_patterns": []}

        matched = []
        lower = text.lower()
        for pat in PROMPT_INJECTION_PATTERNS:
            if re.search(pat, lower):
                matched.append(pat)

        if len(matched) >= 2:
            threat_level = "HIGH"
        elif len(matched) == 1:
            threat_level = "MEDIUM"
        else:
            threat_level = "CLEAN"

        return {
            "is_safe": len(matched) == 0,
            "threat_level": threat_level,
            "matched_patterns": matched,
        }


# ── 3. PII & SENSITIVE DATA REDACTOR ────────────────────────────────────────

PII_PATTERNS = {
    "PAYMENT_CARD": r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b",
    "TAX_OR_SSN_ID": r"\b\d{3}-\d{2}-\d{4}\b",
    "IBAN_ACCOUNT": r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
    "PHONE_NUMBER": r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
}


class PIIRedactor:
    """Redacts personally identifiable information and financial accounts for GDPR / SOC2 compliance."""

    @staticmethod
    def redact(text: str) -> tuple[str, dict]:
        if not text:
            return "", {"total_redactions": 0, "by_type": {}}

        redacted = text
        stats = {}
        total = 0

        for pii_type, pattern in PII_PATTERNS.items():
            matches = re.findall(pattern, redacted)
            count = len(matches)
            if count > 0:
                stats[pii_type] = count
                total += count
                redacted = re.sub(pattern, f"[REDACTED_{pii_type}]", redacted)

        return redacted, {"total_redactions": total, "by_type": stats}


# ── 4. CRYPTOGRAPHIC PROVENANCE & EMAIL SECURITY AUDIT ──────────────────────

def compute_sha256(data: Union[bytes, str]) -> str:
    """Compute SHA-256 fingerprint."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def scan_email_security(inbox, email_id: str) -> dict:
    """
    Executes a complete multi-vector security scan on an email and its attachments.
    Returns an enterprise compliance audit report.
    """
    try:
        email = inbox.get(email_id)
    except Exception as e:
        return {"email_id": email_id, "error": f"Failed to load email: {e}"}

    subject = email.get("subject", "")
    body = email.get("body", "")
    sender = email.get("from", "")
    attachments = email.get("attachments", [])

    # 1. Attachment Zero-Trust Checks
    attachment_reports = []
    all_attachments_safe = True
    total_threats = 0

    for att in attachments:
        try:
            file_bytes = inbox.read_bytes(att)
            report = AttachmentSanitizer.validate_file(att, file_bytes)
            attachment_reports.append({
                "attachment": att,
                "is_safe": report.is_safe,
                "mime_detected": report.mime_detected,
                "sha256": report.sha256,
                "threats": report.threats,
                "details": report.details,
            })
            if not report.is_safe:
                all_attachments_safe = False
                total_threats += len(report.threats)
        except Exception as e:
            attachment_reports.append({
                "attachment": att,
                "is_safe": False,
                "threats": [f"READ_ERROR: {str(e)}"],
            })
            all_attachments_safe = False
            total_threats += 1

    # 2. Prompt Injection Guardrail on Email Subject & Body
    combined_text = f"{subject}\n{body}"
    injection_report = PromptInjectionGuard.scan_text(combined_text)
    if not injection_report["is_safe"]:
        total_threats += len(injection_report["matched_patterns"])

    # 3. PII & Privacy Redaction Audit
    redacted_body, pii_stats = PIIRedactor.redact(body)

    # 4. Overall Posture Score (0-100)
    score = 100
    if total_threats > 0:
        score = max(0, 100 - (total_threats * 30))

    security_verdict = "PASSED" if score >= 80 and all_attachments_safe else "QUARANTINE_REQUIRED"

    return {
        "email_id": email_id,
        "security_verdict": security_verdict,
        "posture_score": score,
        "sender": sender,
        "attachments_scanned": len(attachments),
        "attachments_safe": all_attachments_safe,
        "attachment_reports": attachment_reports,
        "prompt_injection_check": injection_report,
        "pii_compliance": {
            "pii_detected_count": pii_stats["total_redactions"],
            "breakdown": pii_stats["by_type"],
            "redacted_preview": redacted_body[:300] + ("..." if len(redacted_body) > 300 else ""),
        },
        "email_sha256": compute_sha256(combined_text),
    }

