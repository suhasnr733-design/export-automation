"""
Classification Package for Buyer Contacts.
API 3 - EXPORT Automation System (Phase 3: AI Lead Classification).
"""

from .gemini_classifier import (
    ClassificationResult,
    LocalTestClassifier,
    HeuristicClassifier,
    GeminiClassifier,
    classify_contacts,
    classify_contacts_detailed,
    classify_single_contact,
    run_classification_pipeline,
    classify_live_records,
)

__all__ = [
    "ClassificationResult",
    "LocalTestClassifier",
    "HeuristicClassifier",
    "GeminiClassifier",
    "classify_contacts",
    "classify_contacts_detailed",
    "classify_single_contact",
    "run_classification_pipeline",
    "classify_live_records",
]
