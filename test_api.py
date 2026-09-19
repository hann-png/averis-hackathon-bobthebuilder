"""
test_api.py — Integration and endpoint test suite for FastAPI service.

=============================================================================
SAFETY ASSURANCE & HARD CONSTRAINTS:
1. This test suite does NOT call any endpoint with flags that trigger real email sends.
2. It does NOT set BOB_ALLOW_REAL_SEND or any real SMTP credentials anywhere.
3. All outbound transmissions remain structurally disabled by default.
4. Dataset email addresses are never sent real emails under any circumstances.
=============================================================================
"""

import os
from fastapi.testclient import TestClient
from api.main import app

# Ensure safety environment at test run time
os.environ.pop("BOB_ALLOW_REAL_SEND", None)
os.environ.pop("BOB_SMTP_HOST", None)

client = TestClient(app)


def test_health_endpoint():
    """Verify service liveness check."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
    assert data.get("service") == "sdoc-verification-api"


def test_stats_endpoint():
    """Verify aggregated dataset stats."""
    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_emails" in data
    assert data["total_emails"] == 520
    assert "categories" in data
    assert "statuses" in data
    assert "total_defects" in data


def test_submission_endpoint():
    """Verify submission.json is served with strictly conforming schema."""
    response = client.get("/submission")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 520

    allowed_keys = {"category", "status", "review_reason", "has_defect", "defect_fields"}
    for eid, item in list(data.items())[:50]:
        assert set(item.keys()) <= allowed_keys, f"Invalid schema keys in {eid}: {item.keys()}"
        assert "decided_by" not in item, f"Internal decided_by leaked in {eid}"


def test_single_email_endpoint():
    """Verify single email retrieval and verification result."""
    response = client.get("/email/email_004")
    assert response.status_code == 200
    data = response.json()
    assert data.get("email_id") == "email_004"
    assert data.get("category") == "BL_COMPARISON"
    assert data.get("status") == "MISMATCH"
    assert data.get("has_defect") is True
    assert len(data.get("defect_fields", [])) > 0


def test_email_notification_draft_endpoint():
    """Verify auto-generation of mismatch notification draft addressed to sender."""
    response = client.get("/email/email_004/notification")
    assert response.status_code == 200
    data = response.json()
    assert data.get("email_id") == "email_004"
    assert data.get("status") == "MISMATCH"
    assert data.get("notification_eligible") is True
    assert data.get("recipient")
    assert "@" in data.get("recipient")
    assert "Mismatch" in data.get("subject")
    assert "MISMATCH DETECTED" in data.get("body")


def test_email_notification_local_save_action():
    """Verify notification local-save trigger defaults to actually_send=False."""
    response = client.post(
        "/email/email_004/notification/send",
        json={"actually_send": False, "save_locally": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("triggered") is True
    assert data.get("sent") is False
    assert data.get("local_check", {}).get("saved") is True


def test_safety_rail_blocks_unauthorized_send():
    """Verify that even if actually_send=True is passed, structural safety rail blocks sending."""
    response = client.post(
        "/email/email_004/notification/send",
        json={"actually_send": True, "save_locally": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("sent") is False
    assert data.get("reason") == "real_sending_disabled_by_safety_rail"


if __name__ == "__main__":
    print("Running test_api.py directly...")
    test_health_endpoint()
    print("[PASS] test_health_endpoint")
    test_stats_endpoint()
    print("[PASS] test_stats_endpoint")
    test_submission_endpoint()
    print("[PASS] test_submission_endpoint")
    test_single_email_endpoint()
    print("[PASS] test_single_email_endpoint")
    test_email_notification_draft_endpoint()
    print("[PASS] test_email_notification_draft_endpoint")
    test_email_notification_local_save_action()
    print("[PASS] test_email_notification_local_save_action")
    test_safety_rail_blocks_unauthorized_send()
    print("[PASS] test_safety_rail_blocks_unauthorized_send")
    print("\nALL API TESTS PASSED SUCCESSFULLY!")
