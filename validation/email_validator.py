"""
Email Validation Module for API 3 - EXPORT Automation System.

Provides robust email syntax validation, normalization, and heuristic filtering.
Note: Format and structural checks validate compliance with email addressing standards,
not remote mailbox deliverability.
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional

# Standard RFC-compliant email regex pattern
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)

# Common placeholder and dummy domains/patterns
PLACEHOLDER_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "domain.com",
    "sample.com",
    "placeholder.com",
    "invalid.com",
    "test.org",
    "yourdomain.com",
    "yoursite.com",
    "mailinator.com",
    "tempmail.com",
    "10minutemail.com",
}

PLACEHOLDER_PREFIXES = {
    "test",
    "example",
    "sample",
    "placeholder",
    "user",
    "demo",
    "fake",
    "dummy",
}

DISALLOWED_TLDS = {
    "local",
    "test",
    "example",
    "invalid",
    "localhost",
}


@dataclass
class ValidationResult:
    """Represents the structured outcome of an email validation check."""
    is_valid: bool
    email: str
    normalized_email: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "email": self.email,
            "normalized_email": self.normalized_email,
            "reason": self.reason,
        }


def validate_email_address(raw_email: Optional[str]) -> ValidationResult:
    """
    Validate and normalize an email address.

    Validation steps:
    1. Null / empty check
    2. Lowercase and whitespace stripping
    3. Structural regex compliance
    4. Consecutive dot and symbol sanity
    5. Domain and TLD validation
    6. Placeholder / dummy detection

    Returns a ValidationResult with validation flag, normalized email, and reason.
    """
    if raw_email is None:
        return ValidationResult(
            is_valid=False,
            email="",
            normalized_email="",
            reason="Email is None/empty",
        )

    email_str = str(raw_email).strip()
    if not email_str:
        return ValidationResult(
            is_valid=False,
            email="",
            normalized_email="",
            reason="Email string is blank",
        )

    # Basic normalization
    normalized = email_str.lower().strip()

    # Disallow internal spaces or control characters
    if " " in normalized or "\t" in normalized or "\n" in normalized:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Contains whitespace characters",
        )

    # Must contain exactly one '@'
    if normalized.count("@") != 1:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Must contain exactly one '@' symbol",
        )

    local_part, domain_part = normalized.split("@")

    if not local_part:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Missing local part before '@'",
        )

    if not domain_part:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Missing domain part after '@'",
        )

    # Check for consecutive dots
    if ".." in local_part or ".." in domain_part:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Contains consecutive dots",
        )

    # Check for leading/trailing dots in local part
    if local_part.startswith(".") or local_part.endswith("."):
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Local part starts or ends with a dot",
        )

    # Check regex compliance
    if not EMAIL_REGEX.match(normalized):
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Does not conform to standard email syntax",
        )

    # Domain structure check
    domain_labels = domain_part.split(".")
    if len(domain_labels) < 2:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Domain must contain at least one dot separating domain and TLD",
        )

    tld = domain_labels[-1]
    if len(tld) < 2 or not tld.isalpha():
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason="Invalid top-level domain (TLD)",
        )

    if tld in DISALLOWED_TLDS:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason=f"Disallowed top-level domain '.{tld}'",
        )

    # Check for invalid characters or hyphen at label start/end
    for label in domain_labels:
        if not label or label.startswith("-") or label.endswith("-"):
            return ValidationResult(
                is_valid=False,
                email=email_str,
                normalized_email=normalized,
                reason="Domain labels cannot start or end with a hyphen or be empty",
            )

    # Check placeholder domains
    if domain_part in PLACEHOLDER_DOMAINS:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason=f"Rejected placeholder domain: {domain_part}",
        )

    # Check placeholder local parts on generic domains
    if local_part in PLACEHOLDER_PREFIXES and domain_part in {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com"}:
        return ValidationResult(
            is_valid=False,
            email=email_str,
            normalized_email=normalized,
            reason=f"Rejected generic placeholder account: {normalized}",
        )

    return ValidationResult(
        is_valid=True,
        email=email_str,
        normalized_email=normalized,
        reason="Valid email syntax and structure",
    )


# Backward-compatible alias
validate_single_email = validate_email_address


def validate_buyer_records(
    buyers: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], ValidationResult]]]:
    """
    Validate a list of buyer records.
    Returns:
      - valid_records: List of buyer dicts with normalized email
      - invalid_records: List of tuples (original_buyer_dict, validation_result)
    Never silently discards invalid records.
    """
    valid_records = []
    invalid_records = []

    for record in buyers:
        raw_email = record.get("email", "")
        res = validate_email_address(raw_email)
        if res.is_valid:
            updated_record = dict(record)
            updated_record["email"] = res.normalized_email
            valid_records.append(updated_record)
        else:
            invalid_records.append((record, res))

    return valid_records, invalid_records


def filter_valid_contacts(emails: List[str]) -> Tuple[List[str], List[ValidationResult]]:
    """
    Validate and partition a list of email strings into valid normalized emails and invalid results.
    """
    valid = []
    invalid = []
    for e in emails:
        res = validate_email_address(e)
        if res.is_valid:
            valid.append(res.normalized_email)
        else:
            invalid.append(res)
    return valid, invalid


def normalize_email(raw_email: Optional[str]) -> str:
    """Safely normalize an email address string (lowercase, stripped)."""
    if not raw_email:
        return ""
    return str(raw_email).lower().strip()

