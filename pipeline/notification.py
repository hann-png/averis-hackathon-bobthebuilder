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
LOCAL_EMAIL_DIR = Path("testing_generated_emails")


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

    CRITICAL SAFETY RAIL:
    Actual transmission requires the environment variable:
        BOB_ALLOW_REAL_SEND=true
    If unset or false, transmission is structurally blocked to prevent accidental
    outbound emails to addresses found in sample datasets.

    SMTP configuration is read from environment variables:

        BOB_SMTP_HOST
        BOB_SMTP_PORT
        BOB_SMTP_USERNAME
        BOB_SMTP_PASSWORD
        BOB_SMTP_FROM
    """

    # Hard Safety Rail: structurally disable outbound emails unless explicitly allowed
    allow_real_send = os.getenv("BOB_ALLOW_REAL_SEND", "").strip().lower() in ("true", "1", "yes")
    if not allow_real_send:
        return {
            "sent": False,
            "reason": "real_sending_disabled_by_safety_rail",
            "message": "Outbound email transmission is structurally blocked by safety rail. Set BOB_ALLOW_REAL_SEND=true to enable.",
        }

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
    draft_overrides: Optional[dict] = None,
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

        draft_overrides:
            Optional operator-edited subject/body. The recipient is intentionally
            never overridable and remains locked to the original sender.

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

    overrides = draft_overrides or {}
    if overrides.get("subject") is not None:
        email["subject"] = str(overrides["subject"])
    if overrides.get("body") is not None:
        email["body"] = str(overrides["body"])

    response = {
        "triggered": True,
        "sent": False,
        "recipient": email["to"],
        "subject": email["subject"],
        "body": email["body"],
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

# Run a local test when this script is executed directly.
def clear_local_test_files():
    """
    Remove previous locally generated test emails.
    """

    if not LOCAL_EMAIL_DIR.exists():
        return

    for file_path in LOCAL_EMAIL_DIR.iterdir():

        if file_path.is_file():
            file_path.unlink()


def run_local_test():
    """
    Run standalone notification tests without:
    - runner.py
    - main application
    - Docker
    - SMTP
    - external services
    """

    print("=" * 70)
    print("BOB NOTIFICATION LOCAL TEST")
    print("=" * 70)

    # Remove files from previous test runs.
    clear_local_test_files()

    test_sender = "test.sender@example.com"

    si_fields = {
        "port_of_discharge": "Port Klang",
        "gross_weight_kg": "12500",
        "container_count": "5",
    }

    bl_fields = {
        "port_of_discharge": "Singapore",
        "gross_weight_kg": "12750",
        "container_count": "5",
    }

    tests = [
        {
            "name": "Mismatch with auto email ENABLED",
            "email_id": "LOCAL_TEST_001",
            "auto_email_enabled": True,
            "email_data": {
                "sender": test_sender,
                "subject": "Shipping Documents",
            },
            "result": {
                "status": "MISMATCH",
                "defect_fields": [
                    "port_of_discharge",
                    "gross_weight_kg",
                ],
            },
            "expected_triggered": True,
            "expected_file": True,
        },
        {
            "name": "Mismatch with auto email DISABLED",
            "email_id": "LOCAL_TEST_002",
            "auto_email_enabled": False,
            "email_data": {
                "sender": test_sender,
                "subject": "Shipping Documents",
            },
            "result": {
                "status": "MISMATCH",
                "defect_fields": [
                    "port_of_discharge",
                ],
            },
            "expected_triggered": False,
            "expected_file": False,
        },
        {
            "name": "No mismatch with auto email ENABLED",
            "email_id": "LOCAL_TEST_003",
            "auto_email_enabled": True,
            "email_data": {
                "sender": test_sender,
                "subject": "Shipping Documents",
            },
            "result": {
                "status": "OK",
                "defect_fields": [],
            },
            "expected_triggered": False,
            "expected_file": False,
        },
        {
            "name": "Needs review with auto email ENABLED",
            "email_id": "LOCAL_TEST_004",
            "auto_email_enabled": True,
            "email_data": {
                "sender": test_sender,
                "subject": "Shipping Documents",
            },
            "result": {
                "status": "NEEDS_REVIEW",
                "defect_fields": [],
            },
            "expected_triggered": False,
            "expected_file": False,
        },
        {
            "name": "Mismatch with missing sender",
            "email_id": "LOCAL_TEST_005",
            "auto_email_enabled": True,
            "email_data": {
                "subject": "Shipping Documents",
            },
            "result": {
                "status": "MISMATCH",
                "defect_fields": [
                    "port_of_discharge",
                ],
            },
            "expected_triggered": True,
            "expected_file": False,
        },
        {
            "name": "Mismatch with multiple fields",
            "email_id": "LOCAL_TEST_006",
            "auto_email_enabled": True,
            "email_data": {
                "sender": test_sender,
                "subject": "SI and BL Verification",
            },
            "result": {
                "status": "MISMATCH",
                "defect_fields": [
                    "port_of_discharge",
                    "gross_weight_kg",
                    "container_count",
                ],
            },
            "expected_triggered": True,
            "expected_file": True,
        },
    ]

    passed = 0
    failed = 0

    for number, test in enumerate(tests, start=1):

        print()
        print(f"[TEST {number}] {test['name']}")
        print("-" * 70)

        response = process_mismatch_notification(
            auto_email_enabled=test["auto_email_enabled"],
            email_id=test["email_id"],
            email_data=test["email_data"],
            result=test["result"],
            si_fields=si_fields,
            bl_fields=bl_fields,
            local_check=True,
            actually_send=False,
        )

        triggered_correct = (
            response["triggered"]
            == test["expected_triggered"]
        )

        file_path = (
            LOCAL_EMAIL_DIR
            / f"{test['email_id']}_mismatch.txt"
        )

        file_exists = file_path.exists()

        file_correct = (
            file_exists
            == test["expected_file"]
        )

        if triggered_correct and file_correct:

            print("PASS")
            passed += 1

        else:

            print("FAIL")
            failed += 1

        print(f"Response: {response}")
        print(f"Expected triggered: {test['expected_triggered']}")
        print(f"Actual triggered: {response['triggered']}")
        print(f"Expected file: {test['expected_file']}")
        print(f"Actual file: {file_exists}")

    print()
    print("=" * 70)
    print("LOCAL TEST SUMMARY")
    print("=" * 70)

    print(f"Tests passed: {passed}")
    print(f"Tests failed: {failed}")
    print(f"Total tests: {len(tests)}")

    print()

    if failed == 0:

        print("ALL TESTS PASSED")

    else:

        print("SOME TESTS FAILED")

    print()
    print(
        f"Test email files are stored in: "
        f"{LOCAL_EMAIL_DIR}"
    )

    print("=" * 70)


if __name__ == "__main__":
    run_local_test()
