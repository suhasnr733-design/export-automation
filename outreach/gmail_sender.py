"""
Gmail Sender and Campaign Outreach Engine.
API 3 - EXPORT Automation System (Phase 4).

Orchestrates personalized email dispatch, presentation attachment, duplicate prevention,
send delays, daily limits, and mock-safe simulation in TEST_MODE.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import Config
from logging.activity_logger import (
    logger,
    log_send_attempt,
    get_sent_emails,
    SEND_TYPE_REAL,
    SEND_TYPE_TEST,
)
from .attachment_handler import AttachmentHandler, AttachmentError
from .gmail_auth import GmailAuth


@dataclass
class SendResult:
    """Represents the outcome of an individual email outreach dispatch."""
    email: str
    status: str
    is_simulated: bool
    error_message: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class GmailSender:
    """Outreach engine with duplicate prevention and safe TEST_MODE simulation."""

    def __init__(
        self,
        test_mode: Optional[bool] = None,
        daily_limit: Optional[int] = None,
        send_delay: Optional[float] = None,
        presentation_path: Optional[str] = None,
        sent_log_path: Optional[Path] = None,
    ):
        self.test_mode = Config.TEST_MODE if test_mode is None else test_mode
        self.daily_limit = Config.DAILY_SEND_LIMIT if daily_limit is None else daily_limit
        self.send_delay = Config.SEND_DELAY if send_delay is None else send_delay
        self.attachment_handler = AttachmentHandler(presentation_path)
        self.auth = GmailAuth()
        self.sent_log_path = sent_log_path

    def build_email_message(
        self,
        recipient: Dict[str, Any],
        subject: Optional[str] = None,
        body: Optional[str] = None,
    ) -> MIMEMultipart:
        """
        Construct a personalized MIME email with HTML/text body and presentation attachment.
        Supports CC monitoring address if configured.
        """
        buyer_name = recipient.get("buyer_name", "").strip() or "Valued Partner"
        company_name = recipient.get("company_name", "").strip() or "Your Esteemed Company"
        to_email = recipient["email"].strip().lower()
        keyword = Config.SEARCH_KEYWORD

        final_subject = subject or f"Export Inquiry & Catalog: Authentic {keyword} for {company_name}"
        final_body = body or (
            f"Dear {buyer_name},\n\n"
            f"We are leading direct artisanal manufacturers and exporters of authentic {keyword}.\n"
            f"Given {company_name}'s stellar reputation in international trade, we would love to present our export catalog.\n\n"
            "Please find our company presentation attached for your review.\n\n"
            "Warm regards,\nExport Sales Department"
        )

        msg = MIMEMultipart()
        msg["From"] = Config.GMAIL_EMAIL or "export-desk@exportautomation.com"
        msg["To"] = to_email
        msg["Subject"] = final_subject

        if Config.CC_MONITOR_EMAIL:
            msg["Cc"] = Config.CC_MONITOR_EMAIL

        # Attach text body
        msg.attach(MIMEText(final_body, "plain", "utf-8"))

        # Attach presentation PDF if available
        try:
            attachment_part = self.attachment_handler.create_mime_attachment()
            msg.attach(attachment_part)
        except AttachmentError as e:
            logger.warning(f"Attachment omitted for {to_email}: {e}")

        return msg

    def send_single_email(
        self,
        buyer: Dict[str, Any],
        personalized_subject: Optional[str] = None,
        personalized_body: Optional[str] = None,
        campaign_id: str = "",
    ) -> "SendResult":
        """
        Dispatch a single email to a recipient.
        In TEST_MODE (test_mode=True):
          - Constructs MIME message
          - Simulates dispatch
          - Logs TEST_MODE_SUCCESS with send_type=TEST_MODE_SIMULATION to sent_log.csv
          - Never connects to Gmail SMTP
        In LIVE Mode (test_mode=False):
          - Connects to Gmail SMTP
          - Transmits message
          - Logs SENT with send_type=REAL_SEND
        """
        email = buyer["email"].strip().lower()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Build MIME to validate structure and attachment
        mime_msg = self.build_email_message(
            recipient=buyer,
            subject=personalized_subject,
            body=personalized_body,
        )

        if self.test_mode:
            status = "TEST_MODE_SUCCESS"
            logger.info(f"[TEST_MODE] Simulated send to: {email} ({buyer.get('company_name', 'N/A')})")
            log_send_attempt(
                email=email,
                status=status,
                send_type=SEND_TYPE_TEST,
                campaign_id=campaign_id,
                timestamp=timestamp,
                csv_path=self.sent_log_path,
            )
            return SendResult(
                email=email,
                status=status,
                is_simulated=True,
                timestamp=timestamp,
            )

        # Live Outreach Mode
        is_ready, msg = self.auth.validate_credentials()
        if not is_ready:
            status = "FAILED: Missing Gmail credentials"
            log_send_attempt(
                email=email,
                status=status,
                send_type=SEND_TYPE_REAL,
                campaign_id=campaign_id,
                timestamp=timestamp,
                csv_path=self.sent_log_path,
            )
            return SendResult(
                email=email,
                status=status,
                is_simulated=False,
                error_message=msg,
                timestamp=timestamp,
            )

        try:
            smtp_server = self.auth.connect()
            recipients_list = [email]
            if Config.CC_MONITOR_EMAIL:
                recipients_list.append(Config.CC_MONITOR_EMAIL)

            smtp_server.sendmail(Config.GMAIL_EMAIL, recipients_list, mime_msg.as_string())
            smtp_server.quit()

            status = "SENT"
            logger.info(f"Live send SUCCESS to: {email}")
            log_send_attempt(
                email=email,
                status=status,
                send_type=SEND_TYPE_REAL,
                campaign_id=campaign_id,
                timestamp=timestamp,
                csv_path=self.sent_log_path,
            )
            return SendResult(
                email=email,
                status=status,
                is_simulated=False,
                timestamp=timestamp,
            )
        except Exception as e:
            status = f"FAILED: {e}"
            logger.error(f"Failed live send to {email}: {e}")
            log_send_attempt(
                email=email,
                status=status,
                send_type=SEND_TYPE_REAL,
                campaign_id=campaign_id,
                timestamp=timestamp,
                csv_path=self.sent_log_path,
            )
            return SendResult(
                email=email,
                status=status,
                is_simulated=False,
                error_message=str(e),
                timestamp=timestamp,
            )

    def send_campaign(
        self,
        buyers: List[Dict[str, Any]],
        skip_duplicates: bool = True,
        override_sent_set: Optional[set] = None,
    ) -> List[SendResult]:
        """
        Execute outreach campaign for a list of buyers.
        Applies duplicate checks, daily limits, and send delays.
        """
        sent_history = get_sent_emails(csv_path=self.sent_log_path) if override_sent_set is None else override_sent_set
        results: List[SendResult] = []

        eligible_buyers = []
        for b in buyers:
            email = b.get("email", "").strip().lower()
            if not email:
                continue
            if skip_duplicates and email in sent_history:
                logger.info(f"Duplicate prevention: Skipping already-sent recipient '{email}'")
                continue
            eligible_buyers.append(b)

        total_queued = len(eligible_buyers)
        logger.info(f"Outreach queue prepared: {total_queued} recipients ready (Daily Limit: {self.daily_limit}).")

        send_batch = eligible_buyers[:self.daily_limit]
        if len(eligible_buyers) > self.daily_limit:
            logger.info(f"Capping batch at daily limit: {len(send_batch)} of {total_queued} queued.")

        for idx, buyer in enumerate(send_batch, 1):
            res = self.send_single_email(buyer)
            results.append(res)
            if res.is_simulated or res.status in ("SENT", "SUCCESS"):
                sent_history.add(buyer["email"].strip().lower())

            if idx < len(send_batch) and self.send_delay > 0:
                delay = min(0.05, self.send_delay) if self.test_mode else self.send_delay
                time.sleep(delay)

        return results
