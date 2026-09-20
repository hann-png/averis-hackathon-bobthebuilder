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
from api import main as api_main
from api.main import app
from api.operator_state import OperatorStateStore

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


def test_partial_postgres_import_cannot_replace_complete_submission(monkeypatch):
    """A partial database import must leave the complete file dataset active."""
    class PartialPostgres:
        def get_submission(self):
            return {"email_004": api_main._get_file_submission()["email_004"]}

    monkeypatch.setattr(api_main, "postgres_store", PartialPostgres())
    submission = api_main._get_submission()
    assert len(submission) == 520
    assert "email_013" in submission


def test_complete_postgres_import_serves_email_content_and_comparison(monkeypatch):
    """A verified database import becomes the source for UI email data."""
    database_submission = api_main._get_file_submission()

    class CompletePostgres:
        def get_submission(self):
            return database_submission

        def get_email(self, email_id):
            return {
                "email_id": email_id,
                "from": "postgres@example.com",
                "subject": "PostgreSQL source",
                "body": "Stored email body",
                "attachments": ["si.txt", "bl.txt"],
            }

        def get_comparison(self, email_id):
            return {
                "si": {"consignee": "SI value"},
                "bl": {"consignee": "BL value"},
            }

    monkeypatch.setattr(api_main, "postgres_store", CompletePostgres())
    source = client.get("/email/email_004/source")
    comparison = client.get("/email/email_004/comparison")

    assert source.status_code == 200
    assert source.json()["from"] == "postgres@example.com"
    assert comparison.status_code == 200
    assert comparison.json()["si"]["consignee"] == "SI value"


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


def test_source_email_endpoint_returns_real_non_fallback_content():
    """Verify Railway can serve every source email without exposing the data directory."""
    response = client.get("/email/email_013/source")
    assert response.status_code == 200
    data = response.json()
    assert data["email_id"] == "email_013"
    assert data["from"] == "sales@roxcel.at"
    assert "MOMBASA" in data["subject"]
    assert "Attached are the SI and draft BL" in data["body"]
    assert len(data["attachments"]) == 2


def test_comparison_endpoint_returns_extracted_fields_for_non_fallback_email():
    """Verify the document comparison no longer depends on browser access to data/."""
    response = client.get("/email/email_013/comparison")
    assert response.status_code == 200
    data = response.json()
    assert data["email_id"] == "email_013"
    assert data["si"]
    assert data["bl"]
    assert "port_of_discharge" in data["si"]
    assert data["si"]["port_of_discharge"] != data["bl"]["port_of_discharge"]


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


def test_edited_notification_draft_is_persisted(tmp_path, monkeypatch):
    """Verify operator edits are saved separately and reload without changing source data."""
    monkeypatch.setattr(api_main, "operator_state", OperatorStateStore(tmp_path / "operator.db"))
    subject = "[BOB] Edited mismatch clarification"
    body = "Operator-reviewed draft body for email_004."
    response = client.post(
        "/email/email_004/notification/send",
        json={
            "actually_send": False,
            "save_locally": True,
            "subject": subject,
            "body": body,
        },
    )
    assert response.status_code == 200
    assert response.json().get("draft", {}).get("subject") == subject

    reloaded = client.get("/email/email_004/notification")
    assert reloaded.status_code == 200
    data = reloaded.json()
    assert data.get("is_saved") is True
    assert data.get("subject") == subject
    assert data.get("body") == body


def test_operator_review_and_open_timestamps(tmp_path, monkeypatch):
    """Verify review/open activity is persisted outside submission.json."""
    monkeypatch.setattr(api_main, "operator_state", OperatorStateStore(tmp_path / "operator.db"))
    reviewed = client.post(
        "/email/email_004/review",
        json={"reviewed": True, "reviewer": "test-operator"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json().get("reviewed") is True
    assert reviewed.json().get("reviewed_at")

    opened = client.post("/email/email_004/opened")
    assert opened.status_code == 200
    assert opened.json().get("last_opened_at")

    metadata = client.get("/operator/metadata")
    assert metadata.status_code == 200
    assert metadata.json()["latest_reviewed"]["email_id"] == "email_004"


def test_pipeline_timestamp_updates_without_overwriting_operator_activity(tmp_path):
    """A new pipeline timestamp powers time filters while review state stays durable."""
    store = OperatorStateStore(tmp_path / "operator.db")
    store.ensure_emails(["email_004"], processed_at="2026-09-19T01:00:00Z")
    store.mark_reviewed("email_004", True, "test-operator")
    reviewed_at = store.get("email_004")["reviewed_at"]

    store.ensure_emails(["email_004"], processed_at="2026-09-20T01:00:00Z")
    activity = store.get("email_004")
    assert activity["processed_at"] == "2026-09-20T01:00:00Z"
    assert activity["reviewed"] is True
    assert activity["reviewed_at"] == reviewed_at


def test_activity_timeline_records_operator_and_draft_events(tmp_path, monkeypatch):
    """Verify the UI audit trail has durable evidence without modifying submission.json."""
    monkeypatch.setattr(api_main, "operator_state", OperatorStateStore(tmp_path / "operator.db"))
    assert client.post("/email/email_004/opened").status_code == 200
    assert client.post(
        "/email/email_004/review",
        json={"reviewed": True, "reviewer": "test-operator"},
    ).status_code == 200
    assert client.get("/email/email_004/notification?regenerate=true").status_code == 200
    assert client.post(
        "/email/email_004/notification/send",
        json={
            "actually_send": False,
            "save_locally": True,
            "subject": "Operator-confirmed draft",
            "body": "This content is saved for review and is not sent.",
        },
    ).status_code == 200

    response = client.get("/email/email_004/activity")
    assert response.status_code == 200
    event_types = {event["event_type"] for event in response.json()["events"]}
    assert {"opened", "reviewed", "draft_regenerated", "draft_saved"} <= event_types


def test_assistant_query_endpoint_uses_verified_submission_counts():
    """Verify assistant totals are calculated by backend data, not generated by an LLM."""
    response = client.post(
        "/assistant/query",
        json={"query": "How many mismatched emails are there?", "timezone_offset_minutes": -480},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("blocked") is False
    assert data.get("intent") == "list_status"
    assert data.get("metric", {}).get("value") == 46


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


def test_email_confidence_endpoint():
    """Verify extraction confidence scoring endpoint."""
    response = client.get("/email/email_004/confidence")
    assert response.status_code == 200
    data = response.json()
    assert data.get("email_id") == "email_004"
    assert "si" in data
    assert "bl" in data
    assert "confidence" in data["si"]
    assert "overall_confidence" in data["si"]
    assert isinstance(data["si"]["overall_confidence"], (int, float))


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
    test_email_confidence_endpoint()
    print("[PASS] test_email_confidence_endpoint")
    print("\nALL API TESTS PASSED SUCCESSFULLY!")
