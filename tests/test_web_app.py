"""
Unit and Integration Tests for Phase 5 Professional Web Dashboard (web_app.py).
Validates all routes, upload handling, approval gates, test-mode sending, and credential protection.
"""

import io
import pytest
from pathlib import Path
from flask.testing import FlaskClient

from config import Config
from web_app import app, STAGED_UPLOADS
from outreach.campaign_model import CampaignStatus, CampaignStore, Campaign


@pytest.fixture
def client():
    """Create Flask test client configured with testing flags."""
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-12345"
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


# ==============================================================================
# 1. Navigation & Page Load Tests
# ==============================================================================
def test_dashboard_route_loads(client: FlaskClient):
    """Verify GET / renders 200 OK and contains key dashboard widgets."""
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "Export Sales Pipeline Dashboard" in text
    assert "Total Buyers" in text
    assert "TEST MODE" in text


def test_buyers_route_loads(client: FlaskClient):
    """Verify GET /buyers renders 200 OK and displays buyer table."""
    resp = client.get("/buyers")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "Discovered Buyer Dataset" in text
    assert "Email Address" in text


def test_upload_route_loads(client: FlaskClient):
    """Verify GET /upload renders 200 OK and file upload input."""
    resp = client.get("/upload")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "Ingest Buyer Lead Lists" in text
    assert "Standard Buyer Schema" in text


def test_classify_route_loads(client: FlaskClient):
    """Verify GET /classify renders 200 OK and classification metrics."""
    resp = client.get("/classify")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "AI Lead Classification & Segmentation" in text
    assert "Business (B2B)" in text
    assert "Run AI Classification" in text


def test_campaign_send_route_loads(client: FlaskClient):
    """Verify GET /send renders 200 OK and outreach preparation form."""
    resp = client.get("/send")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "Outreach Campaign Dispatch" in text
    assert "Prepare & Generate Preview" in text


def test_campaigns_list_route_loads(client: FlaskClient):
    """Verify GET /campaigns renders 200 OK and campaigns table."""
    resp = client.get("/campaigns")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "Outreach Campaigns Directory" in text


def test_report_route_loads(client: FlaskClient):
    """Verify GET /report renders 200 OK and analytics metrics."""
    resp = client.get("/report")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "Executive Analytics & Outreach Reports" in text
    assert "Download Full CSV Report" in text


def test_settings_route_loads(client: FlaskClient):
    """Verify GET /settings renders 200 OK and configuration values."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "System Configuration & Safety Parameters" in text
    assert "Daily Send Limit" in text
    assert "TEST_MODE" in text


def test_health_route(client: FlaskClient):
    """Verify GET /health returns 200 OK and valid JSON status object."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.is_json
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["test_mode"] is True
    assert data["service"] == "api3-export-automation"
    assert "version" in data


# ==============================================================================
# 2. Upload & Validation Tests
# ==============================================================================
def test_invalid_csv_upload_rejected(client: FlaskClient):
    """Verify uploading a non-CSV or empty file returns a redirect or rejection."""
    # 1. Non-CSV extension
    data = {
        "csv_file": (io.BytesIO(b"fake data"), "contacts.txt")
    }
    resp = client.post("/upload", data=data, content_type="multipart/form-data", follow_redirects=False)
    assert resp.status_code == 302
    assert "/upload" in resp.headers["Location"]

    # 2. Missing email header
    bad_csv = io.BytesIO(b"name,company,city\nAlice,Acme,Paris\n")
    data2 = {
        "csv_file": (bad_csv, "contacts.csv")
    }
    resp2 = client.post("/upload", data=data2, content_type="multipart/form-data", follow_redirects=False)
    assert resp2.status_code == 302
    assert "/upload" in resp2.headers["Location"]


def test_valid_csv_upload_and_preview(client: FlaskClient):
    """Verify uploading a valid CSV generates an audit preview with token."""
    valid_csv = (
        "buyer_name,company_name,email,country,website\n"
        "Elena Rostova,Nordic Imports,elena.unique_test@nordicimport.se,Sweden,https://nordicimport.se\n"
        "Invalid User,Bad Co,invalid-email-address,UK,https://bad.com\n"
    ).encode("utf-8")

    data = {
        "csv_file": (io.BytesIO(valid_csv), "test_leads.csv")
    }
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "Ingestion Audit & Preview: test_leads.csv" in text
    assert "elena.unique_test@nordicimport.se" in text
    assert "Confirm & Merge" in text


def test_confirm_staged_upload_flow(client: FlaskClient, tmp_path, monkeypatch):
    """Verify confirming staged upload adds records to buyers datastore."""
    test_data_dir = tmp_path / "web_data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Config, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(Config, "BUYERS_CSV", test_data_dir / "buyers.csv")

    from logging.activity_logger import init_data_stores, load_buyers
    init_data_stores(base_dir=tmp_path)

    # Stage an upload token
    token = "test_token_12345"
    STAGED_UPLOADS[token] = {
        "records": [
            {
                "buyer_name": "Web Test Lead",
                "company_name": "Web Co",
                "email": "web.lead@example.com",
                "country": "Germany",
                "website": "https://example.de",
                "source_platform": "CSV Upload",
            }
        ],
        "filename": "web_test.csv",
    }

    resp = client.post("/upload/confirm", data={"upload_token": token}, follow_redirects=True)
    assert resp.status_code == 200
    assert "Discovered Buyer Dataset" in resp.data.decode("utf-8")

    buyers = load_buyers(test_data_dir / "buyers.csv")
    assert any(b["email"] == "web.lead@example.com" for b in buyers)


# ==============================================================================
# 3. AI Classification Web Action Test
# ==============================================================================
def test_classification_action_post(client: FlaskClient):
    """Verify POST /classify/run executes classification pipeline and redirects."""
    resp = client.post("/classify/run", follow_redirects=False)
    assert resp.status_code == 302
    assert "/classify" in resp.headers["Location"]


# ==============================================================================
# 4. Campaign Lifecycle & Approval Gate Tests
# ==============================================================================
def test_campaign_creation_approval_and_execution_flow(client: FlaskClient, tmp_path, monkeypatch):
    """Test full web workflow: Create Campaign -> Approve Gate -> Test Mode Send -> View Detail."""
    test_data_dir = tmp_path / "camp_data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Config, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(Config, "BUYERS_CSV", test_data_dir / "buyers.csv")
    monkeypatch.setattr(Config, "BUSINESS_EMAILS_CSV", test_data_dir / "business_emails.csv")
    monkeypatch.setattr(Config, "CAMPAIGNS_FILE", test_data_dir / "campaigns.json")
    monkeypatch.setattr(Config, "SENT_LOG_CSV", test_data_dir / "sent_log.csv")
    monkeypatch.setattr(Config, "CAMPAIGN_LOG_CSV", test_data_dir / "campaign_log.csv")

    from logging.activity_logger import init_data_stores, save_buyers, save_classified_emails
    init_data_stores(base_dir=tmp_path)

    # Seed buyer
    save_buyers([
        {
            "buyer_name": "Web Importer",
            "company_name": "Web Wholesale Ltd",
            "email": "web.importer@webglobal.co.uk",
            "country": "United Kingdom",
            "website": "https://webglobal.co.uk",
            "source_platform": "Web",
        }
    ], csv_path=test_data_dir / "buyers.csv")

    save_classified_emails(
        ["web.importer@webglobal.co.uk"],
        [],
        biz_path=test_data_dir / "business_emails.csv",
        ind_path=test_data_dir / "individual_emails.csv",
    )

    # 1. Create Campaign
    resp = client.post("/campaign/create", data={
        "audience": "business",
        "product_keyword": "Singing Bowls",
        "template_text": "Subject: Catalog for {{company_name}}\n\nHello {{buyer_name}}, attached is our catalog.",
    }, follow_redirects=False)

    assert resp.status_code == 302
    redirect_url = resp.headers["Location"]
    assert "campaign_id=" in redirect_url
    camp_id = redirect_url.split("campaign_id=")[1]

    # Verify Campaign is in READY_FOR_REVIEW
    camp = CampaignStore.get_campaign(camp_id, file_path=test_data_dir / "campaigns.json")
    assert camp is not None
    assert camp.status == CampaignStatus.READY_FOR_REVIEW

    # 2. Approve Campaign Gate
    resp_approve = client.post(f"/campaign/approve/{camp_id}", follow_redirects=True)
    assert resp_approve.status_code == 200
    assert "has been APPROVED for execution" in resp_approve.data.decode("utf-8")

    camp_approved = CampaignStore.get_campaign(camp_id, file_path=test_data_dir / "campaigns.json")
    assert camp_approved.status == CampaignStatus.APPROVED

    # 3. Execute Campaign in TEST_MODE
    resp_exec = client.post(f"/campaign/execute/{camp_id}", follow_redirects=True)
    assert resp_exec.status_code == 200
    text_exec = resp_exec.data.decode("utf-8")
    assert "Campaign Detail:" in text_exec
    assert "TEST_MODE_SUCCESS" in text_exec or "COMPLETED" in text_exec

    # 4. View Detail
    resp_detail = client.get(f"/campaigns/{camp_id}")
    assert resp_detail.status_code == 200
    assert camp_id in resp_detail.data.decode("utf-8")


# ==============================================================================
# 5. Report Download Test
# ==============================================================================
def test_report_download_route(client: FlaskClient):
    """Verify GET /download-report returns valid CSV attachment with headers."""
    resp = client.get("/download-report")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment;" in resp.headers.get("Content-Disposition", "")
    content = resp.data.decode("utf-8")
    assert "email" in content or "status" in content


# ==============================================================================
# 6. Security & Credential Protection Tests
# ==============================================================================
def test_credentials_never_exposed_in_responses(client: FlaskClient, monkeypatch):
    """Ensure sensitive API keys and SMTP app passwords are NEVER rendered in HTML."""
    fake_secret_key = "AIzaSySecretGeminiKey123456789"
    fake_app_password = "supersecretapppasswordxyz"

    monkeypatch.setattr(Config, "GEMINI_API_KEY", fake_secret_key)
    monkeypatch.setattr(Config, "GMAIL_APP_PASSWORD", fake_app_password)
    monkeypatch.setattr(Config, "GMAIL_SENDER_EMAIL", "confidential.export@gmail.com")

    for route in ["/", "/buyers", "/upload", "/classify", "/send", "/campaigns", "/report", "/settings"]:
        resp = client.get(route)
        body = resp.data.decode("utf-8")
        assert fake_secret_key not in body, f"Gemini API key leaked in route: {route}"
        assert fake_app_password not in body, f"Gmail app password leaked in route: {route}"
