"""Email Validation Package."""

from .email_validator import (
    ValidationResult,
    validate_email_address,
    validate_single_email,
    validate_buyer_records,
    filter_valid_contacts,
    normalize_email,
)

__all__ = [
    "ValidationResult",
    "validate_email_address",
    "validate_single_email",
    "validate_buyer_records",
    "filter_valid_contacts",
    "normalize_email",
]

