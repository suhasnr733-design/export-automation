"""
Unit tests for Duplicate Prevention, TEST_MODE Simulation, and Attachment Handling.
"""

import pytest
from pathlib import Path
from outreach.gmail_sender import GmailSender
from outreach.attachment_handler import AttachmentHandler, AttachmentError
from app_logging.activity_logger import log_send_attempt, get_sent_emails


def test_gmail_sender_test_mode_simulation(tmp_path):
    """Verify GmailSender in TEST_MODE simulates delivery and does not touch SMTP."""
    sent_file = tmp_path / "sent_log.csv"

    sender = GmailSender(
        test_mode=True,
        daily_limit=5,
        presentation_path="assets/company_presentation.pdf",
        sent_log_path=sent_file,
    )

    test_buyers = [
        {"buyer_name": "Marcus", "company_name": "Zenith", "email": "marcus@zenithhealing.com"},
        {"buyer_name": "Elena", "company_name": "Aura", "email": "elena@aurawellness.de"},
    ]

    sent_set = set()
    results = sender.send_campaign(test_buyers, override_sent_set=sent_set)

    assert len(results) == 2
    assert all(r.is_simulated is True for r in results)
    assert all(r.status == "TEST_MODE_SUCCESS" for r in results)
    assert "marcus@zenithhealing.com" in sent_set
    assert "elena@aurawellness.de" in sent_set


def test_duplicate_prevention_idempotency(tmp_path):
    """Verify sender skips already-sent recipients and only processes new contacts."""
    sent_file = tmp_path / "sent_log.csv"
    sent_set = {"marcus@zenithhealing.com"}

    sender = GmailSender(
        test_mode=True,
        daily_limit=10,
        sent_log_path=sent_file,
    )

    candidates = [
        {"buyer_name": "Marcus", "company_name": "Zenith", "email": "marcus@zenithhealing.com"},
        {"buyer_name": "Elena", "company_name": "Aura", "email": "elena@aurawellness.de"},
    ]

    # First pass: only Elena should be queued
    results = sender.send_campaign(candidates, override_sent_set=sent_set)
    assert len(results) == 1
    assert results[0].email == "elena@aurawellness.de"

    # Second pass: both are in sent_set, 0 should be sent
    results_pass2 = sender.send_campaign(candidates, override_sent_set=sent_set)
    assert len(results_pass2) == 0


def test_missing_presentation_file_error(tmp_path):
    """Verify AttachmentHandler returns clear error and raises AttachmentError on missing files."""
    missing_path = tmp_path / "non_existent_file.pdf"
    handler = AttachmentHandler(str(missing_path))

    is_valid, msg = handler.validate()
    assert is_valid is False
    assert "not found" in msg.lower()

    with pytest.raises(AttachmentError) as exc_info:
        handler.create_mime_attachment()
    assert "not found" in str(exc_info.value).lower()


def test_valid_presentation_attachment():
    """Verify AttachmentHandler successfully loads and encodes an existing presentation file."""
    handler = AttachmentHandler("assets/company_presentation.pdf")
    is_valid, msg = handler.validate()
    assert is_valid is True

    mime_part = handler.create_mime_attachment()
    assert mime_part is not None
    assert mime_part.get_content_type() == "application/octet-stream"


def test_historical_windows_attachment_path_resolution():
    """Regression test: historical Windows absolute paths resolve to current deployed asset file."""
    windows_path = r"C:\Users\LENOVO\Desktop\export-automation\assets\company_presentation.pdf"
    handler = AttachmentHandler(windows_path)
    is_valid, msg = handler.validate()

    assert is_valid is True
    assert handler.resolved_path.exists()
    assert handler.resolved_path.name == "company_presentation.pdf"

    # Stale paths from other historical machines/directories
    other_machine_path = r"C:\Users\OtherDeveloper\Workspace\assets\company_presentation.pdf"
    other_handler = AttachmentHandler(other_machine_path)
    assert other_handler.validate()[0] is True
    assert other_handler.resolved_path.exists()


def test_cross_platform_nonexistent_drive_path_resolution():
    """Regression test: unknown or non-existent Windows drive paths resolve cleanly to deployed presentation."""
    stale_drive_path = r"Z:\invalid_render_volume\assets\company_presentation.pdf"
    resolved = AttachmentHandler.resolve_attachment_path(stale_drive_path)

    assert resolved.exists()
    assert resolved.name == "company_presentation.pdf"
    assert "Z:" not in resolved.name


def test_campaign_from_dict_normalizes_historical_attachment_path():
    """Regression test: Campaign deserialization normalizes stale Windows attachment paths."""
    from outreach.campaign_model import Campaign

    data = {
        "campaign_id": "camp_test_regression_123",
        "target_audience": "business",
        "subject": "Test Inquiry",
        "body_template": "Hello {{company_name}}",
        "attachment_path": r"C:\Users\LENOVO\Desktop\export-automation\assets\company_presentation.pdf",
        "status": "APPROVED",
    }

    camp = Campaign.from_dict(data)
    handler = AttachmentHandler(camp.attachment_path)
    is_valid, msg = handler.validate()

    assert is_valid is True
    assert Path(camp.attachment_path).exists()
    assert Path(camp.attachment_path).name == "company_presentation.pdf"
