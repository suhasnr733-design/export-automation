"""
Phase 6H Regression Test Suite: Quota Hardening & Sent Log Schema

Verifies:
1. TEST_MODE does not consume real-send quota
2. Real SEND consumes real-send quota
3. TEST_MODE has its own quota (TEST_SIMULATION_LIMIT)
4. Real-send daily limit blocks correctly
5. Test-simulation limit blocks correctly
6. campaign_id is stored in new sent log entries
7. Old 3-column sent-log records remain readable and migrate safely
8. Campaign report retrieves its own send records by campaign_id
9. Duplicate prevention still works for both modes
10. TEST_MODE_SUCCESS is not counted as real SENT
11. audit_sent_log returns separated counters
12. Migration preserves all records without loss
"""

import csv
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import Config
from app_logging.activity_logger import (
    init_data_stores,
    log_send_attempt,
    load_sent_log,
    audit_sent_log,
    get_sent_emails,
    get_real_sends_for_date,
    get_test_simulations_for_date,
    get_successful_sends_for_date,
    migrate_sent_log_schema,
    SENT_LOG_FIELDS,
    SEND_TYPE_REAL,
    SEND_TYPE_TEST,
    SEND_TYPE_LEGACY,
)
from outreach.campaign_manager import CampaignManager
from outreach.campaign_model import Campaign, CampaignStatus, CampaignStore
from outreach.gmail_sender import GmailSender


@pytest.fixture
def temp_env(tmp_path):
    """Create an isolated test environment with fresh CSV files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    init_data_stores(base_dir=tmp_path)
    
    # Create sample dummy PDF presentation
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = assets_dir / "company_presentation.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy pdf content for testing")

    return {
        "base_dir": tmp_path,
        "data_dir": data_dir,
        "sent_log": data_dir / "sent_log.csv",
        "buyers_csv": data_dir / "buyers.csv",
        "biz_csv": data_dir / "business_emails.csv",
        "ind_csv": data_dir / "individual_emails.csv",
        "campaign_log": data_dir / "campaign_log.csv",
        "campaigns_file": data_dir / "campaigns.json",
        "presentation_path": str(pdf_path),
    }


def test_test_mode_does_not_consume_real_quota(temp_env):
    """Verify that logging TEST_MODE simulations leaves real send count at 0."""
    sent_log = temp_env["sent_log"]

    # Log several TEST_MODE simulations
    log_send_attempt("lead1@example.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, csv_path=sent_log)
    log_send_attempt("lead2@example.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, csv_path=sent_log)
    log_send_attempt("lead3@example.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, csv_path=sent_log)

    real_count = get_real_sends_for_date(csv_path=sent_log)
    compat_count = get_successful_sends_for_date(csv_path=sent_log)
    test_sim_count = get_test_simulations_for_date(csv_path=sent_log)

    assert real_count == 0, "TEST_MODE entries must not count towards real sends"
    assert compat_count == 0, "get_successful_sends_for_date must delegate to real sends"
    assert test_sim_count == 3, "TEST_MODE entries must increment test simulations count"


def test_real_send_consumes_real_quota(temp_env):
    """Verify that logging a REAL_SEND increments the real send count."""
    sent_log = temp_env["sent_log"]

    log_send_attempt("real1@buyer.com", "SENT", send_type=SEND_TYPE_REAL, campaign_id="camp_001", csv_path=sent_log)
    log_send_attempt("real2@buyer.com", "SUCCESS", send_type=SEND_TYPE_REAL, campaign_id="camp_001", csv_path=sent_log)

    real_count = get_real_sends_for_date(csv_path=sent_log)
    test_sim_count = get_test_simulations_for_date(csv_path=sent_log)

    assert real_count == 2
    assert test_sim_count == 0


def test_test_mode_has_its_own_quota(temp_env):
    """Verify that TEST_MODE quota increments independently of REAL_SEND quota."""
    sent_log = temp_env["sent_log"]

    log_send_attempt("test@test.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, csv_path=sent_log)
    log_send_attempt("real@buyer.com", "SENT", send_type=SEND_TYPE_REAL, csv_path=sent_log)

    assert get_test_simulations_for_date(csv_path=sent_log) == 1
    assert get_real_sends_for_date(csv_path=sent_log) == 1


def test_real_send_daily_limit_blocks_correctly(temp_env):
    """Verify campaign manager blocks real sends when daily_limit is reached."""
    manager = CampaignManager(
        data_dir=temp_env["data_dir"],
        test_mode=False,
        daily_limit=2,
        attachment_path=temp_env["presentation_path"],
    )

    already_sent = set()
    current_daily_sends = 2  # Already at daily limit of 2

    candidate = {"email": "buyer@validpartner.com", "company_name": "Valid Partner"}
    is_eligible, _, limit_status, skip_reason = manager.evaluate_recipient_eligibility(
        candidate=candidate,
        already_sent_set=already_sent,
        current_daily_sends=current_daily_sends,
        seen_in_batch=set(),
        is_test_mode=False,
        test_simulations_today=0,
    )

    assert not is_eligible
    assert limit_status == "DAILY_LIMIT_REACHED"
    assert "SKIPPED_DAILY_LIMIT" in skip_reason


def test_test_simulation_limit_blocks_correctly(temp_env):
    """Verify campaign manager blocks test simulations when test_simulation_limit is reached."""
    manager = CampaignManager(
        data_dir=temp_env["data_dir"],
        test_mode=True,
        daily_limit=10,
        test_simulation_limit=5,
        attachment_path=temp_env["presentation_path"],
    )

    candidate = {"email": "partner@validboutique.com", "company_name": "Valid Boutique"}
    is_eligible, _, limit_status, skip_reason = manager.evaluate_recipient_eligibility(
        candidate=candidate,
        already_sent_set=set(),
        current_daily_sends=0,
        seen_in_batch=set(),
        is_test_mode=True,
        test_simulations_today=5,  # Reached test limit
    )

    assert not is_eligible
    assert limit_status == "TEST_SIMULATION_LIMIT_REACHED"
    assert "SKIPPED_TEST_SIMULATION_LIMIT" in skip_reason


def test_campaign_id_stored_in_new_sent_log_entries(temp_env):
    """Verify campaign_id is accurately persisted in sent_log.csv."""
    sent_log = temp_env["sent_log"]
    target_campaign_id = "camp_20260814_alpha"

    log_send_attempt(
        email="partner@brand.com",
        status="TEST_MODE_SUCCESS",
        send_type=SEND_TYPE_TEST,
        campaign_id=target_campaign_id,
        csv_path=sent_log,
    )

    records = load_sent_log(sent_log)
    matching = [r for r in records if r.get("email") == "partner@brand.com"]
    assert len(matching) == 1
    assert matching[0]["campaign_id"] == target_campaign_id
    assert matching[0]["send_type"] == SEND_TYPE_TEST


def test_legacy_3_column_records_migrate_cleanly(tmp_path):
    """Verify migration of legacy 3-column CSV to 5-column CSV with all records intact."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    sent_log = data_dir / "sent_log.csv"

    # Write legacy 3-column CSV
    with open(sent_log, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "status", "timestamp"])
        writer.writerow(["legacy_test@test.com", "TEST_MODE_SUCCESS", "2026-08-14T10:00:00Z"])
        writer.writerow(["legacy_real@buyer.com", "SENT", "2026-08-14T10:05:00Z"])
        writer.writerow(["legacy_failed@buyer.com", "FAILED: Auth error", "2026-08-14T10:10:00Z"])

    count = migrate_sent_log_schema(sent_log)
    assert count == 3

    # Verify new schema and contents
    with open(sent_log, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == SENT_LOG_FIELDS
        rows = list(reader)
        assert len(rows) == 3

        assert rows[0]["email"] == "legacy_test@test.com"
        assert rows[0]["send_type"] == SEND_TYPE_TEST
        assert rows[0]["campaign_id"] == "LEGACY"

        assert rows[1]["email"] == "legacy_real@buyer.com"
        assert rows[1]["send_type"] == SEND_TYPE_REAL
        assert rows[1]["campaign_id"] == "LEGACY"

        assert rows[2]["email"] == "legacy_failed@buyer.com"
        assert rows[2]["send_type"] == SEND_TYPE_LEGACY
        assert rows[2]["campaign_id"] == "LEGACY"


def test_campaign_report_retrieves_own_send_records(temp_env):
    """Verify that multiple campaigns can isolate their own sent log entries."""
    sent_log = temp_env["sent_log"]

    log_send_attempt("a@brand.com", "TEST_MODE_SUCCESS", campaign_id="camp_A", csv_path=sent_log)
    log_send_attempt("b@brand.com", "TEST_MODE_SUCCESS", campaign_id="camp_B", csv_path=sent_log)
    log_send_attempt("c@brand.com", "TEST_MODE_SUCCESS", campaign_id="camp_A", csv_path=sent_log)

    records = load_sent_log(sent_log)
    camp_a_sends = [r for r in records if r.get("campaign_id") == "camp_A"]
    camp_b_sends = [r for r in records if r.get("campaign_id") == "camp_B"]

    assert len(camp_a_sends) == 2
    assert len(camp_b_sends) == 1
    assert {r["email"] for r in camp_a_sends} == {"a@brand.com", "c@brand.com"}
    assert {r["email"] for r in camp_b_sends} == {"b@brand.com"}


def test_duplicate_prevention_still_works_globally(temp_env):
    """Verify that previously sent addresses are captured by get_sent_emails for duplicate avoidance."""
    sent_log = temp_env["sent_log"]

    log_send_attempt("duplicate@target.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, csv_path=sent_log)
    log_send_attempt("live_dup@target.com", "SENT", send_type=SEND_TYPE_REAL, csv_path=sent_log)

    sent_set = get_sent_emails(sent_log)
    assert "duplicate@target.com" in sent_set
    assert "live_dup@target.com" in sent_set

    # Test eligibility check flags duplicates
    manager = CampaignManager(
        data_dir=temp_env["data_dir"],
        test_mode=True,
        attachment_path=temp_env["presentation_path"],
    )

    is_eligible, dup_status, _, skip_reason = manager.evaluate_recipient_eligibility(
        candidate={"email": "duplicate@target.com"},
        already_sent_set=sent_set,
        current_daily_sends=0,
        seen_in_batch=set(),
        is_test_mode=True,
    )
    assert not is_eligible
    assert dup_status == "PREVIOUSLY_SENT"
    assert "SKIPPED_DUPLICATE" in skip_reason


def test_test_mode_success_not_counted_as_sent(temp_env):
    """Verify audit_sent_log strictly separates test_mode_records and successful_sends (live)."""
    sent_log = temp_env["sent_log"]

    log_send_attempt("sim1@test.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, csv_path=sent_log)
    log_send_attempt("sim2@test.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, csv_path=sent_log)

    audit = audit_sent_log(sent_log)
    assert audit["successful_sends"] == 0, "Live successful_sends must be 0"
    assert audit["total_real_sends"] == 0
    assert audit["test_mode_records"] == 2
    assert audit["total_test_simulations"] == 2


def test_audit_sent_log_returns_separate_counters(temp_env):
    """Verify audit_sent_log structure includes separated real and test quota counters."""
    sent_log = temp_env["sent_log"]

    log_send_attempt("live@domain.com", "SENT", send_type=SEND_TYPE_REAL, csv_path=sent_log)
    log_send_attempt("test@domain.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, csv_path=sent_log)

    audit = audit_sent_log(sent_log)

    assert "real_sends_today" in audit
    assert "test_simulations_today" in audit
    assert "total_real_sends" in audit
    assert "total_test_simulations" in audit
    assert audit["real_sends_today"] == 1
    assert audit["test_simulations_today"] == 1


def test_migration_idempotent_and_safe(temp_env):
    """Verify that migrate_sent_log_schema on an already-migrated file returns 0 and does not alter data."""
    sent_log = temp_env["sent_log"]

    log_send_attempt("lead@test.com", "TEST_MODE_SUCCESS", send_type=SEND_TYPE_TEST, campaign_id="camp_x", csv_path=sent_log)
    rows_before = load_sent_log(sent_log)

    # Re-running migration on already 5-field schema should be no-op
    res = migrate_sent_log_schema(sent_log)
    assert res == 0

    rows_after = load_sent_log(sent_log)
    assert rows_before == rows_after
