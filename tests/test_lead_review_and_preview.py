"""
Unit and Integration Tests for Phase 6F: Human Lead Review & Safe Campaign Preview.
Validates:
- Review page (/review) filters strictly for LIVE_DISCOVERY leads
- Default review status is PENDING_REVIEW
- Human approval, rejection, and manual review decision recording
- Unknown country preservation ("Unknown — Verification Required") without guessing
- Only approved leads can enter campaign preview
- Unapproved leads cannot preview or stage campaigns
- Campaign preview renders personalization without sending emails
- Second approval gate is strictly enforced
- TEST_MODE remains active and zero real SMTP calls occur
- Lead review audit log creation and persistence
"""

import json
import csv
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import Config
from web_app import app
from app_logging.activity_logger import (
    init_data_stores,
    save_buyers,
    save_discovery_provenance,
    save_qualification_log,
    save_lead_review_decision,
    load_lead_review_log,
    get_lead_review_statuses,
    audit_lead_review_log,
    load_sent_log,
)
from outreach.campaign_model import CampaignStore, CampaignStatus
from outreach.campaign_manager import CampaignManager


@pytest.fixture
def mock_review_env(tmp_path):
    """Set up isolated data environment with LIVE_DISCOVERY and HISTORICAL leads."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    init_data_stores(base_dir=tmp_path)

    # 1. Create buyers (2 LIVE_DISCOVERY, 2 HISTORICAL_TEST)
    buyers = [
        {
            "buyer_name": "",
            "company_name": "Pashmina Vogue™",
            "email": "support@pashminavogue.com",
            "website": "https://pashminavogue.com",
            "country": "UNKNOWN",
            "source_platform": "Website Search",
        },
        {
            "buyer_name": "Artisan Desk",
            "company_name": "Pashmina Artisan",
            "email": "support@pashminaartisan.in",
            "website": "https://pashminaartisan.in",
            "country": "India",
            "source_platform": "Website Search",
        },
        {
            "buyer_name": "Historical Buyer 1",
            "company_name": "Zenith Healing",
            "email": "contact@zenithhealing.com",
            "website": "https://zenithhealing.com",
            "country": "United States",
            "source_platform": "Google Search",
        },
        {
            "buyer_name": "Historical Buyer 2",
            "company_name": "Aura Wellness",
            "email": "info@aurawellness.de",
            "website": "https://aurawellness.de",
            "country": "Germany",
            "source_platform": "Google Search",
        },
    ]
    save_buyers(buyers, csv_path=data_dir / "buyers.csv")

    # 2. Discovery Provenance
    prov_data = {
        "metadata": {"last_updated": "2026-08-14T21:00:00Z"},
        "records": {
            "support@pashminavogue.com": {"data_source": "LIVE_DISCOVERY", "product_keyword": "Handmade Pashmina"},
            "support@pashminaartisan.in": {"data_source": "LIVE_DISCOVERY", "product_keyword": "Handmade Pashmina"},
            "contact@zenithhealing.com": {"data_source": "HISTORICAL_TEST", "product_keyword": "Singing Bowls"},
            "info@aurawellness.de": {"data_source": "HISTORICAL_TEST", "product_keyword": "Singing Bowls"},
        },
    }
    with open(data_dir / "discovery_provenance.json", "w", encoding="utf-8") as f:
        json.dump(prov_data, f)

    # 3. Qualification log
    qual_records = [
        {
            "email": "support@pashminavogue.com",
            "company_name": "Pashmina Vogue™",
            "product": "Handmade Pashmina",
            "business_status": "business",
            "product_relevance": "1.0",
            "buyer_intent": "0.85",
            "commercial_signals": "retailer; distributor; importer",
            "evidence": "Trademarked brand name; Professional .com domain; International retail presence",
            "qualification_score": "91",
            "qualification_level": "HIGH",
            "recommendation": "REVIEW_FOR_OUTREACH",
            "classification_source": "GEMINI",
            "qualification_source": "GEMINI",
            "timestamp": "2026-08-14T21:00:00Z",
        },
        {
            "email": "support@pashminaartisan.in",
            "company_name": "Pashmina Artisan",
            "product": "Handmade Pashmina",
            "business_status": "business",
            "product_relevance": "1.0",
            "buyer_intent": "0.10",
            "commercial_signals": "manufacturer; artisan; exporter",
            "evidence": "Entity based in India; Producer rather than importer; Acts as competitor",
            "qualification_score": "77",
            "qualification_level": "HIGH",
            "recommendation": "MANUAL_REVIEW",
            "classification_source": "GEMINI",
            "qualification_source": "GEMINI",
            "timestamp": "2026-08-14T21:00:00Z",
        },
    ]
    save_qualification_log(qual_records, csv_path=data_dir / "qualification_log.csv")

    # 4. Classification log
    with open(data_dir / "classification_log.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["support@pashminavogue.com", "business", "0.95", "Corporate domain", "GEMINI", "False", "2026-08-14T21:00:00Z"])
        writer.writerow(["support@pashminaartisan.in", "business", "0.95", "Corporate domain", "GEMINI", "False", "2026-08-14T21:00:00Z"])

    # 5. Point Config to isolated directory
    orig_data_dir = Config.DATA_DIR
    orig_buyers_csv = Config.BUYERS_CSV
    orig_qual_csv = Config.QUALIFICATION_LOG_CSV
    orig_review_csv = Config.LEAD_REVIEW_LOG_CSV
    orig_prov_file = Config.DISCOVERY_PROVENANCE_FILE
    orig_campaigns_file = Config.CAMPAIGNS_FILE
    orig_class_log = Config.CLASSIFICATION_LOG_CSV
    orig_sent_log = Config.SENT_LOG_CSV

    Config.DATA_DIR = data_dir
    Config.BUYERS_CSV = data_dir / "buyers.csv"
    Config.QUALIFICATION_LOG_CSV = data_dir / "qualification_log.csv"
    Config.LEAD_REVIEW_LOG_CSV = data_dir / "lead_review_log.csv"
    Config.DISCOVERY_PROVENANCE_FILE = data_dir / "discovery_provenance.json"
    Config.CAMPAIGNS_FILE = data_dir / "campaigns.json"
    Config.CLASSIFICATION_LOG_CSV = data_dir / "classification_log.csv"
    Config.SENT_LOG_CSV = data_dir / "sent_log.csv"

    yield data_dir

    Config.DATA_DIR = orig_data_dir
    Config.BUYERS_CSV = orig_buyers_csv
    Config.QUALIFICATION_LOG_CSV = orig_qual_csv
    Config.LEAD_REVIEW_LOG_CSV = orig_review_csv
    Config.DISCOVERY_PROVENANCE_FILE = orig_prov_file
    Config.CAMPAIGNS_FILE = orig_campaigns_file
    Config.CLASSIFICATION_LOG_CSV = orig_class_log
    Config.SENT_LOG_CSV = orig_sent_log


@pytest.fixture
def client(mock_review_env):
    """Create Flask test client configured for isolated review environment."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_review_page_loads_and_displays_only_live_discovery(client):
    """Verify /review route loads, displays LIVE_DISCOVERY leads, and excludes historical leads."""
    response = client.get("/review")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Assert LIVE_DISCOVERY leads are visible
    assert "Pashmina Vogue" in html
    assert "support@pashminavogue.com" in html
    assert "Pashmina Artisan" in html
    assert "support@pashminaartisan.in" in html

    # Assert HISTORICAL_TEST leads are excluded
    assert "Zenith Healing" not in html
    assert "contact@zenithhealing.com" not in html
    assert "Aura Wellness" not in html
    assert "info@aurawellness.de" not in html

    # Assert Safety Banners and Badges
    assert "GEMINI GENERATED" in html
    assert "HUMAN REVIEW REQUIRED" in html
    assert "TEST MODE" in html


def test_default_pending_review_status(client, mock_review_env):
    """Verify candidate leads default to PENDING_REVIEW before explicit human review."""
    response = client.get("/review")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "PENDING HUMAN REVIEW" in html

    statuses = get_lead_review_statuses(Config.LEAD_REVIEW_LOG_CSV)
    assert len(statuses) == 0  # No explicit decisions logged yet


def test_approve_lead_updates_log_and_unlocks_preview(client, mock_review_env):
    """Verify approving a lead records decision in lead_review_log.csv and displays approved badge."""
    post_data = {
        "email": "support@pashminavogue.com",
        "company_name": "Pashmina Vogue™",
        "decision": "approve",
        "notes": "Verified high-end retail boutique model with active .com domain.",
        "qualification_score": "91",
        "recommendation": "REVIEW_FOR_OUTREACH",
    }
    res = client.post("/review/decision", data=post_data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "APPROVED FOR OUTREACH" in html
    assert "Preview Campaign" in html

    # Verify audit log on disk
    statuses = get_lead_review_statuses(Config.LEAD_REVIEW_LOG_CSV)
    assert "support@pashminavogue.com" in statuses
    assert statuses["support@pashminavogue.com"]["review_status"] == "APPROVED"
    assert statuses["support@pashminavogue.com"]["reviewer_decision"] == "Approve for Campaign"


def test_reject_lead_updates_log_and_blocks_preview(client, mock_review_env):
    """Verify rejecting a lead records REJECTED status and prevents preview."""
    post_data = {
        "email": "support@pashminaartisan.in",
        "company_name": "Pashmina Artisan",
        "decision": "reject",
        "notes": "Direct artisan producer in India - competitor rather than buyer.",
        "qualification_score": "77",
        "recommendation": "MANUAL_REVIEW",
    }
    res = client.post("/review/decision", data=post_data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "REJECTED" in html

    # Verify audit log
    statuses = get_lead_review_statuses(Config.LEAD_REVIEW_LOG_CSV)
    assert statuses["support@pashminaartisan.in"]["review_status"] == "REJECTED"

    # Attempting to access preview for rejected lead must redirect with warning
    prev_res = client.get("/review/preview?email=support@pashminaartisan.in", follow_redirects=True)
    assert "Campaign preview is only available for leads with APPROVED" in prev_res.get_data(as_text=True)


def test_request_manual_review_updates_log(client, mock_review_env):
    """Verify requesting manual review records MANUAL_REVIEW_REQUESTED status."""
    post_data = {
        "email": "support@pashminaartisan.in",
        "company_name": "Pashmina Artisan",
        "decision": "manual_review",
        "notes": "Need to check if they have wholesale procurement division.",
        "qualification_score": "77",
        "recommendation": "MANUAL_REVIEW",
    }
    res = client.post("/review/decision", data=post_data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "MANUAL REVIEW REQUESTED" in html

    statuses = get_lead_review_statuses(Config.LEAD_REVIEW_LOG_CSV)
    assert statuses["support@pashminaartisan.in"]["review_status"] == "MANUAL_REVIEW_REQUESTED"


def test_unknown_country_preserved_without_guessing(client, mock_review_env):
    """Verify leads with unknown country explicitly display 'Unknown — Verification Required'."""
    # 1. Review page display
    res = client.get("/review")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "Unknown — Verification Required" in html
    assert "Pashmina Vogue" in html

    # 2. Approve lead and check Preview page display
    client.post("/review/decision", data={
        "email": "support@pashminavogue.com",
        "company_name": "Pashmina Vogue™",
        "decision": "approve",
    })

    prev_res = client.get("/review/preview?email=support@pashminavogue.com")
    assert prev_res.status_code == 200
    prev_html = prev_res.get_data(as_text=True)

    assert "Unknown — Verification Required" in prev_html
    # Check safe fallback token used in email body (not a fabricated country)
    assert "international markets" in prev_html


def test_unapproved_lead_cannot_access_campaign_preview(client, mock_review_env):
    """Verify attempting to preview an unapproved lead is blocked and redirected."""
    # Lead is currently PENDING_REVIEW
    res = client.get("/review/preview?email=support@pashminavogue.com", follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "Campaign preview is only available for leads with APPROVED" in html


def test_campaign_preview_renders_personalization_without_sending(client, mock_review_env):
    """Verify preview generates To, Subject, Body, and PDF Attachment info without dispatching any emails."""
    # 1. Approve lead
    client.post("/review/decision", data={
        "email": "support@pashminavogue.com",
        "company_name": "Pashmina Vogue™",
        "decision": "approve",
    })

    # 2. Get preview
    res = client.get("/review/preview?email=support@pashminavogue.com")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "support@pashminavogue.com" in html
    assert "Pashmina Vogue™" in html
    assert "company_presentation.pdf" in html
    assert "Personalized Message Preview" in html

    # 3. Assert zero emails sent
    sent_logs = load_sent_log(Config.SENT_LOG_CSV)
    assert len(sent_logs) == 0


def test_unapproved_lead_cannot_create_campaign(client, mock_review_env):
    """Verify unapproved leads cannot create campaigns."""
    res = client.post("/review/create-campaign", data={"email": "support@pashminavogue.com"}, follow_redirects=True)
    assert "Campaign creation is only permitted for APPROVED leads" in res.get_data(as_text=True)


def test_second_approval_gate_and_test_mode_execution(client, mock_review_env):
    """
    Verify complete Phase 6F flow:
    Lead Review -> APPROVED -> Campaign Preview -> READY_FOR_REVIEW -> Campaign Approval -> TEST_MODE Execution.
    """
    # 1. Approve Lead
    client.post("/review/decision", data={
        "email": "support@pashminavogue.com",
        "company_name": "Pashmina Vogue™",
        "decision": "approve",
        "notes": "Verified export boutique",
    })

    # 2. Stage Campaign from Preview
    stage_res = client.post("/review/create-campaign", data={"email": "support@pashminavogue.com"}, follow_redirects=True)
    assert stage_res.status_code == 200
    stage_html = stage_res.get_data(as_text=True)

    # 3. Verify Campaign created in READY_FOR_REVIEW status
    campaigns = CampaignStore.load_campaigns(Config.CAMPAIGNS_FILE)
    assert len(campaigns) == 1
    campaign = campaigns[0]
    assert campaign.status == CampaignStatus.READY_FOR_REVIEW

    # 4. Approve Campaign at second approval gate
    appr_res = client.post(f"/campaign/approve/{campaign.campaign_id}", follow_redirects=True)
    assert appr_res.status_code == 200

    updated_campaign = CampaignStore.get_campaign(campaign.campaign_id, file_path=Config.CAMPAIGNS_FILE)
    assert updated_campaign.status == CampaignStatus.APPROVED

    # 5. Execute Campaign in TEST_MODE
    exec_res = client.post(f"/campaign/execute/{campaign.campaign_id}", follow_redirects=True)
    assert exec_res.status_code == 200

    completed_campaign = CampaignStore.get_campaign(campaign.campaign_id, file_path=Config.CAMPAIGNS_FILE)
    assert completed_campaign.status == CampaignStatus.COMPLETED

    # 6. Verify sent log contains TEST_MODE simulation entry and zero live sends
    sent_logs = load_sent_log(Config.SENT_LOG_CSV)
    assert len(sent_logs) == 1
    assert "TEST_MODE" in sent_logs[0]["status"]
    assert sent_logs[0]["email"] == "support@pashminavogue.com"
