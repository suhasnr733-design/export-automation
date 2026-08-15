"""
Unit tests for Email Validation Module.
"""

import pytest
from validation.email_validator import (
    validate_email_address,
    validate_buyer_records,
    filter_valid_contacts,
)


def test_valid_standard_emails():
    """Verify standard legitimate business and personal emails pass validation."""
    valid_examples = [
        "procurement@zenithhealing.com",
        "import.manager@aura-wellness.de",
        "buyer_sophie@lotusliving.co.uk",
        "john.doe@company.org",
        "sales@trade-supply.io",
        "contact@business.travel",
    ]
    for email in valid_examples:
        res = validate_email_address(email)
        assert res.is_valid is True, f"Expected '{email}' to be valid. Reason: {res.reason}"
        assert res.normalized_email == email.lower()


def test_email_normalization():
    """Verify emails with uppercase or surrounding whitespace are cleaned and normalized."""
    res = validate_email_address("  Buyer.Desk@ZenithHealing.COM  ")
    assert res.is_valid is True
    assert res.normalized_email == "buyer.desk@zenithhealing.com"


def test_reject_malformed_emails():
    """Verify malformed email formats are cleanly rejected."""
    malformed_examples = [
        "",
        None,
        "plainaddress",
        "@missinglocal.com",
        "missingdomain@",
        "missing.dot@domain",
        "two@@ats.com",
        "spaces in@domain.com",
        "consecutive..dots@domain.com",
        "local@domain..com",
        ".leadingdot@domain.com",
        "trailingdot.@domain.com",
        "bad-tld@domain.c",
    ]
    for email in malformed_examples:
        res = validate_email_address(email)
        assert res.is_valid is False, f"Expected '{email}' to be invalid"
        assert res.reason != ""


def test_reject_placeholder_domains():
    """Verify placeholder and dummy domains are rejected."""
    placeholders = [
        "john@example.com",
        "test@test.com",
        "user@domain.com",
        "admin@sample.com",
        "temp@mailinator.com",
        "buyer@invalid.com",
    ]
    for email in placeholders:
        res = validate_email_address(email)
        assert res.is_valid is False, f"Expected placeholder '{email}' to be rejected"
        assert "placeholder" in res.reason.lower() or "rejected" in res.reason.lower()


def test_reject_generic_placeholder_accounts():
    """Verify obvious generic placeholder accounts on free email providers are rejected."""
    fake_accounts = [
        "test@gmail.com",
        "example@yahoo.com",
        "demo@outlook.com",
        "fake@hotmail.com",
    ]
    for email in fake_accounts:
        res = validate_email_address(email)
        assert res.is_valid is False
        assert "placeholder" in res.reason.lower()


def test_validate_buyer_records_preserves_records():
    """Verify validate_buyer_records partitions valid and invalid records without data loss."""
    raw_records = [
        {"buyer_name": "Alice", "company_name": "Zenith", "email": "ALICE@ZENITH.COM"},
        {"buyer_name": "Bob", "company_name": "Fake Co", "email": "bob@example.com"},
        {"buyer_name": "Charlie", "company_name": "Broken", "email": "bad_email_format"},
    ]

    valid_list, invalid_list = validate_buyer_records(raw_records)

    assert len(valid_list) == 1
    assert valid_list[0]["email"] == "alice@zenith.com"

    assert len(invalid_list) == 2
    invalid_emails = [r[0]["email"] for r in invalid_list]
    assert "bob@example.com" in invalid_emails
    assert "bad_email_format" in invalid_emails


def test_filter_valid_contacts():
    """Verify filter_valid_contacts returns clean list of valid strings and invalid objects."""
    contacts = [
        "valid1@company.com",
        "invalid@",
        "VALID2@COMPANY.CO.UK",
        "test@test.com",
    ]
    valid, invalid = filter_valid_contacts(contacts)
    assert valid == ["valid1@company.com", "valid2@company.co.uk"]
    assert len(invalid) == 2
