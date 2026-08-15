"""
Campaign Data Model and State Machine for API 3 - EXPORT Automation System.
Defines campaign structures, valid statuses, and state transition logic.
"""

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional
from config import Config
from logging.activity_logger import logger


class CampaignStatus(str, Enum):
    """Permitted campaign lifecycle states."""
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CampaignStateError(Exception):
    """Exception raised when an invalid campaign state transition is attempted."""
    pass


@dataclass
class CampaignRecipientPreview:
    """Preview metadata for a single recipient in a campaign."""
    email: str
    company_name: str
    country: str
    classification: str
    confidence: float
    subject: str
    body_snippet: str
    attachment_name: str
    duplicate_status: str
    daily_limit_status: str
    is_eligible: bool
    skip_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Campaign:
    """Outreach campaign entity tracking configuration, lifecycle, and recipient metrics."""
    campaign_id: str
    target_audience: str  # "business", "individual", "all"
    subject: str
    body_template: str
    attachment_path: str
    created_at: str
    total_recipients: int = 0
    eligible_recipients: int = 0
    skipped_recipients: int = 0
    status: CampaignStatus = CampaignStatus.DRAFT
    approved_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    recipients_summary: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create_new(
        cls,
        target_audience: str = "business",
        subject: Optional[str] = None,
        body_template: Optional[str] = None,
        attachment_path: Optional[str] = None,
    ) -> "Campaign":
        """Factory method to construct a fresh campaign in DRAFT status."""
        cid = f"camp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        return cls(
            campaign_id=cid,
            target_audience=target_audience.lower(),
            subject=subject or "",
            body_template=body_template or "",
            attachment_path=attachment_path or Config.PRESENTATION_PATH,
            created_at=datetime.now(timezone.utc).isoformat(),
            status=CampaignStatus.DRAFT,
        )

    def mark_ready_for_review(self) -> None:
        """Transition DRAFT -> READY_FOR_REVIEW."""
        if self.status not in (CampaignStatus.DRAFT, CampaignStatus.READY_FOR_REVIEW):
            raise CampaignStateError(f"Cannot mark {self.status} campaign as READY_FOR_REVIEW.")
        self.status = CampaignStatus.READY_FOR_REVIEW

    def approve(self) -> None:
        """Transition READY_FOR_REVIEW -> APPROVED."""
        if self.status not in (CampaignStatus.READY_FOR_REVIEW, CampaignStatus.DRAFT):
            raise CampaignStateError(
                f"Cannot approve campaign '{self.campaign_id}' in state '{self.status}'. "
                "Campaign must be in DRAFT or READY_FOR_REVIEW status."
            )
        self.status = CampaignStatus.APPROVED
        self.approved_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Campaign '{self.campaign_id}' has been APPROVED for execution.")

    def mark_running(self) -> None:
        """Transition APPROVED -> RUNNING."""
        if self.status != CampaignStatus.APPROVED:
            raise CampaignStateError(
                f"Cannot launch campaign '{self.campaign_id}' because it has not been APPROVED (current: {self.status})."
            )
        self.status = CampaignStatus.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()

    def mark_completed(self) -> None:
        """Transition RUNNING -> COMPLETED."""
        self.status = CampaignStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def mark_failed(self, error_message: str) -> None:
        """Transition to FAILED status with error message."""
        self.status = CampaignStatus.FAILED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.error_message = error_message

    def cancel(self) -> None:
        """Cancel the campaign."""
        if self.status in (CampaignStatus.COMPLETED, CampaignStatus.RUNNING):
            raise CampaignStateError(f"Cannot cancel campaign in '{self.status}' state.")
        self.status = CampaignStatus.CANCELLED

    def to_dict(self) -> Dict[str, Any]:
        """Convert dataclass to dictionary."""
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, CampaignStatus) else str(self.status)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Campaign":
        """Instantiate Campaign from dictionary."""
        status_val = data.get("status", CampaignStatus.DRAFT.value)
        status_enum = CampaignStatus(status_val) if status_val in CampaignStatus._value2member_map_ else CampaignStatus.DRAFT

        return cls(
            campaign_id=data.get("campaign_id", ""),
            target_audience=data.get("target_audience", "business"),
            subject=data.get("subject", ""),
            body_template=data.get("body_template", ""),
            attachment_path=data.get("attachment_path", Config.PRESENTATION_PATH),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            total_recipients=int(data.get("total_recipients", 0)),
            eligible_recipients=int(data.get("eligible_recipients", 0)),
            skipped_recipients=int(data.get("skipped_recipients", 0)),
            status=status_enum,
            approved_at=data.get("approved_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
            recipients_summary=data.get("recipients_summary", []),
        )


class CampaignStore:
    """Manages persistence and retrieval of Campaign records in campaigns.json."""

    @staticmethod
    def load_campaigns(file_path: Optional[Path] = None) -> List[Campaign]:
        """Load all stored campaigns from JSON store."""
        target = file_path or Config.CAMPAIGNS_FILE
        if not target.exists():
            return []
        try:
            with open(target, mode="r", encoding="utf-8") as f:
                data = json.load(f)
                return [Campaign.from_dict(item) for item in data]
        except Exception as e:
            logger.error(f"Failed to read campaigns from '{target}': {e}")
            return []

    @staticmethod
    def save_campaign(campaign: Campaign, file_path: Optional[Path] = None) -> None:
        """Create or update a campaign record in JSON store."""
        target = file_path or Config.CAMPAIGNS_FILE
        target.parent.mkdir(parents=True, exist_ok=True)

        existing = CampaignStore.load_campaigns(target)
        updated = False
        new_list = []
        for c in existing:
            if c.campaign_id == campaign.campaign_id:
                new_list.append(campaign)
                updated = True
            else:
                new_list.append(c)

        if not updated:
            new_list.append(campaign)

        with open(target, mode="w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in new_list], f, indent=2)

    @staticmethod
    def get_campaign(campaign_id: str, file_path: Optional[Path] = None) -> Optional[Campaign]:
        """Fetch campaign by ID."""
        campaigns = CampaignStore.load_campaigns(file_path)
        for c in campaigns:
            if c.campaign_id == campaign_id:
                return c
        return None
