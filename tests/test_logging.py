"""
Unit tests for Logging and CSV Data Stores.
"""

import csv
import pytest
from pathlib import Path
from app_logging.activity_logger import (
    init_data_stores,
    save_buyers,
    load_buyers,
    save_classified_emails,
    load_classified_emails,
    log_send_attempt,
    get_sent_emails,
    load_sent_log,
    normalize_buyer_record,
    BUYER_SCHEMA_FIELDS,
)


@pytest.fixture
def temp_data_dir(tmp_path):
    """Provide a clean temporary directory for isolated CSV tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_init_data_stores(temp_data_dir):
    """Verify init_data_stores creates all 4 CSV files with correct headers."""
    init_data_stores(base_dir=temp_data_dir)

    data_dir = temp_data_dir / "data"
    buyers_csv = data_dir / "buyers.csv"
    biz_csv = data_dir / "business_emails.csv"
    ind_csv = data_dir / "individual_emails.csv"
    sent_csv = data_dir / "sent_log.csv"

    assert buyers_csv.exists()
    assert biz_csv.exists()
    assert ind_csv.exists()
    assert sent_csv.exists()

    with open(buyers_csv, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == BUYER_SCHEMA_FIELDS


def test_save_and_load_buyers(temp_data_dir):
    """Verify buyer records are saved, appended, and reloaded accurately."""
    csv_file = temp_data_dir / "data" / "buyers.csv"

    buyers = [
        {
            "buyer_name": "Marcus",
            "company_name": "Zenith",
            "email": "marcus@zenith.com",
            "website": "https://zenith.com",
            "country": "USA",
            "source_platform": "Google",
        },
        {
            "buyer_name": "Elena",
            "company_name": "Aura",
            "email": "elena@aura.de",
            "website": "https://aura.de",
            "country": "Germany",
            "source_platform": "Facebook",
        },
    ]

    saved_count = save_buyers(buyers, csv_path=csv_file)
    assert saved_count == 2

    loaded = load_buyers(csv_file)
    assert len(loaded) == 2
    assert loaded[0]["email"] == "marcus@zenith.com"
    assert loaded[1]["company_name"] == "Aura"


def test_save_and_load_classified_emails(temp_data_dir):
    """Verify business and individual emails are partitioned and saved."""
    biz_file = temp_data_dir / "data" / "business_emails.csv"
    ind_file = temp_data_dir / "data" / "individual_emails.csv"

    biz_emails = ["sales@company.com", "import@distributor.org", "SALES@COMPANY.COM"]
    ind_emails = ["john.practitioner@gmail.com", "yogi.meditation@yahoo.com"]

    save_classified_emails(
        business_emails=biz_emails,
        individual_emails=ind_emails,
        biz_path=biz_file,
        ind_path=ind_file,
    )

    loaded = load_classified_emails(biz_path=biz_file, ind_path=ind_file)
    assert len(loaded["business"]) == 2  # Deduplicated
    assert "sales@company.com" in loaded["business"]
    assert "import@distributor.org" in loaded["business"]
    assert len(loaded["individual"]) == 2


def test_log_send_attempt_and_sent_history(temp_data_dir):
    """Verify sent_log.csv records status correctly and get_sent_emails filters successfully sent emails."""
    sent_file = temp_data_dir / "data" / "sent_log.csv"

    log_send_attempt("success1@test.com", "TEST_MODE_SUCCESS", csv_path=sent_file)
    log_send_attempt("success2@test.com", "SUCCESS", csv_path=sent_file)
    log_send_attempt("failed@test.com", "FAILED: Auth error", csv_path=sent_file)

    sent_set = get_sent_emails(csv_path=sent_file)
    assert "success1@test.com" in sent_set
    assert "success2@test.com" in sent_set
    assert "failed@test.com" not in sent_set  # Failed email should not block retries

    logs = load_sent_log(csv_path=sent_file)
    assert len(logs) == 3


def test_stdlib_logging_not_shadowed():
    """Verify that Python standard-library logging is not shadowed by app_logging."""
    import logging
    import logging.config
    import logging.handlers

    assert hasattr(logging, "getLogger")
    assert hasattr(logging, "basicConfig")
    assert hasattr(logging, "StreamHandler")
    assert hasattr(logging, "FileHandler")

    # Standard library logging file should be part of Python lib, not local workspace
    log_file = getattr(logging, "__file__", "")
    assert "app_logging" not in log_file

