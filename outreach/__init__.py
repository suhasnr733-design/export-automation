"""
Outreach and Gmail Dispatch Package.
API 3 - EXPORT Automation System (Phase 4).
"""

from .attachment_handler import AttachmentHandler, AttachmentError
from .gmail_auth import GmailAuth
from .gmail_sender import GmailSender, SendResult
from .personalization import PersonalizationEngine
from .campaign_model import (
    Campaign,
    CampaignStatus,
    CampaignStateError,
    CampaignStore,
    CampaignRecipientPreview,
)
from .campaign_manager import CampaignManager

__all__ = [
    "AttachmentHandler",
    "AttachmentError",
    "GmailAuth",
    "GmailSender",
    "SendResult",
    "PersonalizationEngine",
    "Campaign",
    "CampaignStatus",
    "CampaignStateError",
    "CampaignStore",
    "CampaignRecipientPreview",
    "CampaignManager",
]
