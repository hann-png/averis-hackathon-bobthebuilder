"""
notification.py — Automatic mismatch email notification.

When a confirmed mismatch is detected, this module can generate
an email addressed to the original sender.

Features:
- Automatic email ON/OFF toggle
- Local email file generation for testing
- Email preview
- Optional SMTP sending
- Original sender detection
- Mismatch details from SI and BL
"""

from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
import os
import smtplib
from typing import Optional


FIELD_DISPLAY_NAMES = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify Party",
    "port_of_loading": "Port of Loading",
    "port_of_discharge": "Port of Discharge",
    "container_count": "Container Count",
    "gross_weight_kg": "Gross Weight (kg)",
}


# Local folder where generated emails are stored during testing.
LOCAL_EMAIL_DIR = Path("generated_emails")


def should_send_auto_email(
    auto_email_enabled: bool,
    result: dict,
) -> bool:
    """
    Return True only when:
    - automatic email is enabled
    - the comparison result is a confirmed mismatch
    """

    return (
        auto_email_enabled
        and result.get("status") == "MISMATCH"
    )


def get_original_sender(
    email_data: dict,
) -> Optional[str]:
    """
    Get the original sender from the incoming email record.

    Supports several common field names.
    """

    sender = (
        email_data.get("from")
        or email_data.get("sender")
        or email_data.get("from_email")
        or email_data.get("email")
    )

    if not sender:
        return None

    return str(sender).strip()


def _display_field_name(field: str) -> str:
    """
    Convert a canonical field name into a readable name.
    """

    return FIELD_DISPLAY_NAMES.get(
        field,
        field.replace("_", " ").title(),
    )


def _get_field_value(
    fields: Optional[dict],
    field: str,
) -> str:
    """
    Safely retrieve an extracted field value.
    """

    if not fields:
        return "Not available"

    value = fields.get(field)

    if value is None:
        return "Not available"

    value = str(value).strip()

    if not value:
        return "Not available"

    return value


def generate_mismatch_email(
    email_id: str,
    email_data: dict,
    result: dict,
    si_fields: Optional[dict] = None,
    bl_fields: Optional[dict] = None,
) -> Optional[dict]:
    """
    Generate a mismatch email addressed to the original sender.

    This function does not send the email.
    """

    recipient = get_original_sender(email_data)

    if not recipient:
        return None

    defect_fields = result.get(
        "defect_fields",
        [],
    )

    original_subject = email_data.get(
        "subject",
        "No subject",
    )

    subject = (
        f"[BOB] Shipping Document Mismatch - {email_id}"
    )

    body_lines = [
        "Dear Sender,",
        "",
        "BOB has detected a mismatch between the",
        "Shipping Instruction (SI) and Bill of Lading (BL)",
        "associated with your shipping request.",
        "",
        "SHIPMENT INFORMATION",
        "---------------------",
        f"Email ID: {email_id}",
        f"Original Subject: {original_subject}",
        "",
        "MISMATCH DETECTED",
        "-----------------",
    ]

    if defect_fields:

        for field in defect_fields:

            field_name = _display_field_name(field)

            si_value = _get_field_value(
                si_fields,
                field,
            )

            bl_value = _get_field_value(
                bl_fields,
                field,
            )

            body_lines.extend([
                "",
                field_name,
                f"SI: {si_value}",
                f"BL: {bl_value}",
            ])

    else:

        body_lines.extend([
            "",
            "No specific defect field was provided.",
        ])

    body_lines.extend([
        "",
        "ACTION REQUIRED",
        "---------------",
        "Please review the above discrepancy and provide",
        "the necessary correction or clarification.",
        "",
        "This email was generated automatically by BOB",
        "(Bill of Lading Verification).",
        "",
        "Regards,",
        "BOB Document Verification System",
    ])

    return {
        "to": recipient,
        "subject": subject,
        "body": "\n".join(body_lines),
        "generated_at": datetime.now().isoformat(
            timespec="seconds"
        ),
    }


def preview_mismatch_email(
    email_id: str,
    email_data: dict,
    result: dict,
    si_fields: Optional[dict] = None,
    bl_fields: Optional[dict] = None,
) -> Optional[str]:
    """
    Generate a readable local preview of the email.
    """

    email = generate_mismatch_email(
        email_id=email_id,
        email_data=email_data,
        result=result,
        si_fields=si_fields,
        bl_fields=bl_fields,
    )

    if email is None:
        return None

    return (
        f"TO: {email['to']}\n"
        f"SUBJECT: {email['subject']}\n"
        f"GENERATED: {email['generated_at']}\n"
        f"\n"
        f"{email['body']}"
    )


def save_email_locally(
    email: dict,
    email_id: str,
) -> dict:
    """
    Save the generated email to a local .txt file.

    This is useful for:
    - local testing
    - hackathon demonstrations
    - checking email content before SMTP is enabled
    """

    LOCAL_EMAIL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_path = (
        LOCAL_EMAIL_DIR
        / f"{email_id}_mismatch.txt"
    )

    content = (
        f"TO: {email['to']}\n"
        f"SUBJECT: {email['subject']}\n"
        f"GENERATED: {email['generated_at']}\n"
        f"\n"
        f"{email['body']}\n"
    )

    file_path.write_text(
        content,
        encoding="utf-8",
    )

    return {
        "saved": True,
        "path": str(file_path),
        "recipient": email["to"],
    }


def send_mismatch_email(
    email: dict,
) -> dict:
    """
    Send an already-generated email using SMTP.

    SMTP configuration is read from environment variables:

        BOB_SMTP_HOST
        BOB_SMTP_PORT
        BOB_SMTP_USERNAME
        BOB_SMTP_PASSWORD
        BOB_SMTP_FROM
    """

    smtp_host = os.getenv(
        "BOB_SMTP_HOST"
    )

    smtp_port = os.getenv(
        "BOB_SMTP_PORT",
        "587",
    )

    smtp_username = os.getenv(
        "BOB_SMTP_USERNAME"
    )

    smtp_password = os.getenv(
        "BOB_SMTP_PASSWORD"
    )

    smtp_from = os.getenv(
        "BOB_SMTP_FROM",
        smtp_username,
    )

    if not smtp_host:

        return {
            "sent": False,
            "reason": "smtp_not_configured",
        }

    try:

        message = EmailMessage()

        message["From"] = smtp_from
        message["To"] = email["to"]
        message["Subject"] = email["subject"]

        message.set_content(
            email["body"]
        )

        with smtplib.SMTP(
            smtp_host,
            int(smtp_port),
            timeout=20,
        ) as server:

            server.starttls()

            if smtp_username and smtp_password:

                server.login(
                    smtp_username,
                    smtp_password,
                )

            server.send_message(
                message
            )

        return {
            "sent": True,
            "recipient": email["to"],
            "subject": email["subject"],
            "generated_at": email["generated_at"],
        }

    except Exception as exc:

        return {
            "sent": False,
            "reason": "send_failed",
            "error": str(exc),
        }


def process_mismatch_notification(
    auto_email_enabled: bool,
    email_id: str,
    email_data: dict,
    result: dict,
    si_fields: Optional[dict] = None,
    bl_fields: Optional[dict] = None,
    local_check: bool = True,
    actually_send: bool = False,
) -> dict:
    """
    Main notification function.

    Flow:

        Mismatch?
            ↓
        Auto email ON?
            ↓
        Generate email
            ↓
        Local check/save
            ↓
        Optionally send through SMTP

    Parameters:

        auto_email_enabled:
            Dashboard ON/OFF toggle.

        local_check:
            Save the generated email locally as a .txt file.

        actually_send:
            Send the email through SMTP.

    By default, actually_send=False so testing cannot accidentally
    send emails.
    """

    # Do nothing if automatic email is disabled
    # or if there is no confirmed mismatch.
    if not should_send_auto_email(
        auto_email_enabled,
        result,
    ):

        return {
            "triggered": False,
            "sent": False,
            "reason": "disabled_or_no_mismatch",
        }

    # Generate email addressed to original sender.
    email = generate_mismatch_email(
        email_id=email_id,
        email_data=email_data,
        result=result,
        si_fields=si_fields,
        bl_fields=bl_fields,
    )

    if email is None:

        return {
            "triggered": True,
            "sent": False,
            "reason": "missing_original_sender",
        }

    response = {
        "triggered": True,
        "sent": False,
        "recipient": email["to"],
        "subject": email["subject"],
    }

    # Save locally for checking/testing.
    if local_check:

        local_result = save_email_locally(
            email,
            email_id,
        )

        response["local_check"] = local_result

    # Only send if explicitly enabled.
    if actually_send:

        send_result = send_mismatch_email(
            email
        )

        response.update(
            send_result
        )

    return response