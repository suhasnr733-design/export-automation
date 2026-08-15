"""
Unit tests for Phase 4: Outreach Campaign Preparation and Safe Gmail Integration.
Covers all 20 required test scenarios:
  1. Audience selection
  2. Business audience
  3. Individual audience
  4. All audience
  5. Email personalization
  6. Missing buyer name fallback
  7. Missing company fallback
  8. Attachment validation
  9. Missing attachment blocks campaign
  10. Duplicate recipient blocking
  11. Same-campaign duplicate blocking
  12. Daily send limit
  13. Send delay configuration
  14. TEST_MODE never connects to SMTP
  15. TEST_MODE logging
  16. Campaign creation
  17. Campaign approval
  18. Campaign report
  19. Invalid recipients
  20. Failed send handling
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import Config
from logging.activity_logger import (
    init_data_stores,
    save_buyers,
    save_classified_emails,
    log_send_attempt,
    load_sent_log,
    load_campaign_log,
)
from outreach.attachment_handler import AttachmentHandler, AttachmentError
from outreach.personalization import PersonalizationEngine
from outreach.campaign_model import (
    Campaign,
    CampaignStatus,
    CampaignStateError,
    CampaignStore,
)
from outreach.campaign_manager import CampaignManager
from outreach.gmail_sender import GmailSender, SendResult
from reports.report_generator import ReportGenerator


@pytest.fixture
def test_env(tmp_path):
    """Setup an isolated test environment with sample buyers, classified files, and dummy presentation PDF."""
    data_dir = tmp_path / "data"
    assets_dir = tmp_path / "assets"
    data_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    init_data_stores(base_dir=tmp_path)

    # Create dummy presentation PDF
    presentation_file = assets_dir / "company_presentation.pdf"
    with open(presentation_file, "wb") as f:
        f.write(b"%PDF-1.4 Mock Presentation Content for Unit Testing")

    # Sample buyers
    buyers = [
        {"buyer_name": "Marcus Vance", "company_name": "Zenith Sound Imports Ltd", "email": "import@zenithhealing.com", "website": "https://zenithhealing.com", "country": "USA", "source_platform": "Google Search"},
        {"buyer_name": "Elena Rostova", "company_name": "Aura Wellness Wholesale", "email": "contact@aurawellness.de", "website": "https://aurawellness.de", "country": "Germany", "source_platform": "Google Search"},
        {"buyer_name": "John Doe", "company_name": "", "email": "john.soundlover@gmail.com", "website": "", "country": "USA", "source_platform": "Google Search"},
    ]
    save_buyers(buyers, csv_path=data_dir / "buyers.csv")

    # Classified emails
    biz_emails = ["import@zenithhealing.com", "contact@aurawellness.de"]
    ind_emails = ["john.soundlover@gmail.com"]
    save_classified_emails(biz_emails, ind_emails, biz_path=data_dir / "business_emails.csv", ind_path=data_dir / "individual_emails.csv")

    return {
        "tmp_path": tmp_path,
        "data_dir": data_dir,
        "assets_dir": assets_dir,
        "presentation_file": presentation_file,
    }


# 1. Audience selection
def test_audience_selection(test_env):
    """Verify audience selection loads candidates with correct metadata."""
    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    candidates = mgr.select_audience_candidates(audience="business")
    assert len(candidates) == 2
    assert any(c["email"] == "import@zenithhealing.com" for c in candidates)
    assert any(c["company_name"] == "Zenith Sound Imports Ltd" for c in candidates)


# 2. Business audience
def test_business_audience(test_env):
    """Verify selecting business audience only includes records from business_emails.csv."""
    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    candidates = mgr.select_audience_candidates(audience="business")
    assert len(candidates) == 2
    emails = {c["email"] for c in candidates}
    assert emails == {"import@zenithhealing.com", "contact@aurawellness.de"}


# 3. Individual audience
def test_individual_audience(test_env):
    """Verify selecting individual audience only includes records from individual_emails.csv."""
    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    candidates = mgr.select_audience_candidates(audience="individual")
    assert len(candidates) == 1
    assert candidates[0]["email"] == "john.soundlover@gmail.com"


# 4. All audience
def test_all_audience(test_env):
    """Verify selecting 'all' audience combines business and individual contacts."""
    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    candidates = mgr.select_audience_candidates(audience="all")
    assert len(candidates) == 3


# 5. Email personalization
def test_email_personalization():
    """Verify template placeholders are replaced with buyer metadata."""
    buyer = {
        "buyer_name": "Marcus Vance",
        "company_name": "Zenith Sound Imports Ltd",
        "country": "USA",
        "website": "https://zenithhealing.com",
        "email": "import@zenithhealing.com",
    }
    tpl = "Subject: Catalog for {{company_name}}\n\nDear {{buyer_name}},\nWe supply {{product}} in {{country}}."
    subject, body = PersonalizationEngine.render_email(buyer, template_text=tpl, product_keyword="Singing Bowls")

    assert "Zenith Sound Imports Ltd" in subject
    assert "Dear Marcus Vance" in body
    assert "Singing Bowls" in body
    assert "USA" in body
    assert "{{" not in subject and "{{" not in body


# 6. Missing buyer name fallback
def test_missing_buyer_name_fallback():
    """Verify missing or None buyer_name renders professional fallback."""
    buyer = {
        "buyer_name": None,
        "company_name": "Zenith Ltd",
        "country": "USA",
        "email": "import@zenithhealing.com",
    }
    tpl = "Dear {{buyer_name}},\nGreetings to {{company_name}}."
    _, body = PersonalizationEngine.render_email(buyer, template_text=tpl)

    assert "None" not in body
    assert "Dear Procurement Team" in body or "Dear Valued Partner" in body or "Dear Purchasing Team" in body


# 7. Missing company fallback
def test_missing_company_fallback():
    """Verify missing or None company_name renders professional fallback."""
    buyer = {
        "buyer_name": "John Doe",
        "company_name": "",
        "country": "USA",
        "email": "john@example.com",
    }
    tpl = "Dear {{buyer_name}},\nWe are eager to partner with {{company_name}}."
    _, body = PersonalizationEngine.render_email(buyer, template_text=tpl)

    assert "None" not in body
    assert "your organization" in body


# 8. Attachment validation
def test_attachment_validation(test_env):
    """Verify AttachmentHandler correctly validates an existing PDF file."""
    handler = AttachmentHandler(str(test_env["presentation_file"]))
    is_valid, msg = handler.validate()
    assert is_valid is True
    meta = handler.get_metadata()
    assert meta["exists"] is True
    assert meta["size_bytes"] > 0
    assert meta["extension"] == ".pdf"


# 9. Missing attachment blocks campaign
def test_missing_attachment_blocks_campaign(test_env):
    """Verify campaign execution raises AttachmentError if attachment file is missing."""
    mgr = CampaignManager(
        data_dir=test_env["data_dir"],
        attachment_path=str(test_env["assets_dir"] / "non_existent_file.pdf"),
    )
    campaign, _ = mgr.prepare_campaign(target_audience="business")
    mgr.approve_campaign(campaign.campaign_id)

    with pytest.raises(AttachmentError):
        mgr.execute_campaign(campaign_id=campaign.campaign_id, force_test_mode=True)


# 10. Duplicate recipient blocking
def test_duplicate_recipient_blocking(test_env):
    """Verify recipients already in sent_log.csv are skipped."""
    sent_log = test_env["data_dir"] / "sent_log.csv"
    log_send_attempt(email="import@zenithhealing.com", status="TEST_MODE_SUCCESS", csv_path=sent_log)

    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    campaign, previews = mgr.prepare_campaign(target_audience="business")

    # One should be eligible, one should be skipped as duplicate
    assert campaign.eligible_recipients == 1
    assert campaign.skipped_recipients == 1

    mgr.approve_campaign(campaign.campaign_id)
    summary = mgr.execute_campaign(campaign_id=campaign.campaign_id, force_test_mode=True)
    assert summary["successful_sends"] == 1
    assert summary["duplicates_skipped"] == 1


# 11. Same-campaign duplicate blocking
def test_same_campaign_duplicate_blocking(test_env):
    """Verify duplicate occurrences of an email within the same campaign are skipped."""
    # Add duplicate to business list
    biz_csv = test_env["data_dir"] / "business_emails.csv"
    with open(biz_csv, "a", encoding="utf-8") as f:
        f.write("import@zenithhealing.com\n")

    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    campaign, previews = mgr.prepare_campaign(target_audience="business")

    assert campaign.total_recipients == 2  # candidate resolution deduplicates by email


# 12. Daily send limit
def test_daily_send_limit(test_env):
    """Verify campaign honors daily send limit and flags excess recipients as SKIPPED_DAILY_LIMIT."""
    mgr = CampaignManager(
        data_dir=test_env["data_dir"],
        daily_limit=1,
        attachment_path=str(test_env["presentation_file"]),
    )
    campaign, previews = mgr.prepare_campaign(target_audience="business")

    assert campaign.eligible_recipients == 1
    assert campaign.skipped_recipients == 1

    mgr.approve_campaign(campaign.campaign_id)
    summary = mgr.execute_campaign(campaign_id=campaign.campaign_id, force_test_mode=True)
    assert summary["successful_sends"] == 1
    assert summary["daily_limit_skipped"] == 1


# 13. Send delay configuration
def test_send_delay_configuration(test_env):
    """Verify send delay parameter is stored and accessible."""
    mgr = CampaignManager(
        data_dir=test_env["data_dir"],
        send_delay=2.5,
        attachment_path=str(test_env["presentation_file"]),
    )
    assert mgr.send_delay == 2.5


# 14. TEST_MODE never connects to SMTP
def test_test_mode_never_connects_to_smtp(test_env):
    """Verify GmailSender with test_mode=True simulates dispatch and never calls SMTP connect."""
    sender = GmailSender(
        test_mode=True,
        presentation_path=str(test_env["presentation_file"]),
        sent_log_path=test_env["data_dir"] / "sent_log.csv",
    )

    with patch("smtplib.SMTP_SSL") as mock_smtp:
        res = sender.send_single_email({"email": "import@zenithhealing.com", "company_name": "Zenith Ltd"})
        assert res.is_simulated is True
        assert res.status == "TEST_MODE_SUCCESS"
        mock_smtp.assert_not_called()


# 15. TEST_MODE logging
def test_test_mode_logging(test_env):
    """Verify TEST_MODE dispatch logs to sent_log.csv and campaign_log.csv with TEST mode."""
    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    campaign, _ = mgr.prepare_campaign(target_audience="business")
    mgr.approve_campaign(campaign.campaign_id)
    mgr.execute_campaign(campaign_id=campaign.campaign_id, force_test_mode=True)

    sent_logs = load_sent_log(test_env["data_dir"] / "sent_log.csv")
    camp_logs = load_campaign_log(test_env["data_dir"] / "campaign_log.csv")

    assert len(sent_logs) == 2
    assert all(l["status"] == "TEST_MODE_SUCCESS" for l in sent_logs)
    assert len(camp_logs) == 2
    assert all(c["mode"] == "TEST" for c in camp_logs)


# 16. Campaign creation
def test_campaign_creation():
    """Verify factory creation of Campaign in DRAFT status."""
    camp = Campaign.create_new(target_audience="business", subject="Test Subject")
    assert camp.status == CampaignStatus.DRAFT
    assert camp.campaign_id.startswith("camp_")
    assert camp.target_audience == "business"


# 17. Campaign approval
def test_campaign_approval(test_env):
    """Verify campaign approval gate transitions and blocks unapproved dispatch."""
    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    campaign, _ = mgr.prepare_campaign(target_audience="business")

    assert campaign.status == CampaignStatus.READY_FOR_REVIEW

    # Unapproved execution must fail
    with pytest.raises(CampaignStateError):
        mgr.execute_campaign(campaign_id=campaign.campaign_id, force_test_mode=True)

    # Approve
    approved_camp = mgr.approve_campaign(campaign.campaign_id)
    assert approved_camp.status == CampaignStatus.APPROVED
    assert approved_camp.approved_at is not None


# 18. Campaign report
def test_campaign_report(capsys):
    """Verify ReportGenerator.print_campaign_report renders all required metrics."""
    data = {
        "campaign_id": "camp_20260814_test",
        "target_audience": "business",
        "mode": "TEST / DRY RUN",
        "total_candidates": 10,
        "eligible_recipients": 8,
        "duplicates_skipped": 1,
        "invalid_skipped": 1,
        "daily_limit_skipped": 0,
        "successful_sends": 8,
        "failed_sends": 0,
        "attachment_status": "VALIDATED (company_presentation.pdf)",
        "status": "COMPLETED",
        "start_time": "2026-08-14T11:00:00Z",
        "end_time": "2026-08-14T11:01:00Z",
    }
    ReportGenerator.print_campaign_report(data)
    captured = capsys.readouterr().out

    assert "CAMPAIGN REPORT" in captured
    assert "camp_20260814_test" in captured
    assert "TEST / DRY RUN" in captured
    assert "Eligible Recipients : 8" in captured


# 19. Invalid recipients
def test_invalid_recipients_handling(test_env):
    """Verify invalid syntax email addresses are flagged as SKIPPED_INVALID."""
    biz_csv = test_env["data_dir"] / "business_emails.csv"
    with open(biz_csv, "w", encoding="utf-8") as f:
        f.write("email\n")
        f.write("valid@zenithhealing.com\n")
        f.write("malformed@@domain..com\n")
        f.write("placeholder@example.com\n")

    mgr = CampaignManager(data_dir=test_env["data_dir"], attachment_path=str(test_env["presentation_file"]))
    campaign, previews = mgr.prepare_campaign(target_audience="business")

    assert campaign.eligible_recipients == 1
    assert campaign.skipped_recipients == 2

    invalid_previews = [p for p in previews if not p.is_eligible]
    assert len(invalid_previews) == 2
    assert all("INVALID" in p.skip_reason for p in invalid_previews)


# 20. Failed send handling
def test_failed_send_handling(test_env):
    """Verify GmailSender handles live SMTP errors gracefully without crashing."""
    sender = GmailSender(
        test_mode=False,
        presentation_path=str(test_env["presentation_file"]),
        sent_log_path=test_env["data_dir"] / "sent_log.csv",
    )

    with patch("outreach.gmail_auth.GmailAuth.connect", side_effect=ConnectionError("SMTP Auth Refused")):
        with patch("outreach.gmail_auth.GmailAuth.validate_credentials", return_value=(True, "OK")):
            res = sender.send_single_email({"email": "import@zenithhealing.com", "company_name": "Zenith Ltd"})
            assert res.is_simulated is False
            assert "FAILED" in res.status
            assert "SMTP Auth Refused" in str(res.error_message)
