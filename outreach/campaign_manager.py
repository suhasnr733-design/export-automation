"""
Campaign Manager and Outreach Pipeline Orchestrator.
API 3 - EXPORT Automation System (Phase 4).
Handles audience selection, personalization, attachment validation, daily limits,
approval gating, TEST_MODE simulation, and campaign logging.
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

from config import Config
from logging.activity_logger import (
    logger,
    init_data_stores,
    load_buyers,
    load_classified_emails,
    load_classification_log,
    load_sent_log,
    get_sent_emails,
    log_send_attempt,
    save_campaign_log,
    get_successful_sends_for_date,
    get_real_sends_for_date,
    get_test_simulations_for_date,
)
from validation.email_validator import validate_single_email
from .attachment_handler import AttachmentHandler, AttachmentError
from .personalization import PersonalizationEngine
from .campaign_model import (
    Campaign,
    CampaignStatus,
    CampaignStateError,
    CampaignStore,
    CampaignRecipientPreview,
)
from .gmail_sender import GmailSender, SendResult


class CampaignManager:
    """Coordinates audience selection, previewing, approval gating, and safe campaign dispatch."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        test_mode: Optional[bool] = None,
        daily_limit: Optional[int] = None,
        test_simulation_limit: Optional[int] = None,
        send_delay: Optional[float] = None,
        attachment_path: Optional[str] = None,
    ):
        self.data_dir = data_dir or Config.DATA_DIR
        self.test_mode = Config.TEST_MODE if test_mode is None else test_mode
        self.daily_limit = Config.DAILY_SEND_LIMIT if daily_limit is None else daily_limit
        self.test_simulation_limit = (
            test_simulation_limit if test_simulation_limit is not None
            else (daily_limit if daily_limit is not None else Config.TEST_SIMULATION_LIMIT)
        )
        self.send_delay = Config.SEND_DELAY if send_delay is None else send_delay
        self.attachment_path = attachment_path or Config.PRESENTATION_PATH

        self.buyers_csv = self.data_dir / "buyers.csv"
        self.biz_csv = self.data_dir / "business_emails.csv"
        self.ind_csv = self.data_dir / "individual_emails.csv"
        self.class_log_csv = self.data_dir / "classification_log.csv"
        self.campaign_log_csv = self.data_dir / "campaign_log.csv"
        self.sent_log_csv = self.data_dir / "sent_log.csv"
        self.campaigns_file = self.data_dir / "campaigns.json"

        init_data_stores(base_dir=self.data_dir.parent if self.data_dir.name == "data" else self.data_dir)

    def select_audience_candidates(
        self,
        audience: str = "business",
    ) -> List[Dict[str, Any]]:
        """
        Resolve candidate contacts for a given audience target ('business', 'individual', or 'all').
        Combines classified lists with metadata from buyers.csv and classification_log.csv.
        """
        aud = audience.lower().strip()
        classified = load_classified_emails(biz_path=self.biz_csv, ind_path=self.ind_csv)
        buyers = load_buyers(self.buyers_csv)
        class_logs = load_classification_log(self.class_log_csv)

        # Build lookup dicts by email
        buyers_by_email: Dict[str, Dict[str, Any]] = {
            b["email"].lower(): b for b in buyers if b.get("email")
        }
        class_logs_by_email: Dict[str, Dict[str, Any]] = {
            c["email"].lower(): c for c in class_logs if c.get("email")
        }

        target_emails: List[str] = []
        if aud == "business":
            target_emails = classified.get("business", [])
        elif aud == "individual":
            target_emails = classified.get("individual", [])
        elif aud == "all":
            target_emails = classified.get("business", []) + classified.get("individual", [])
        elif aud == "single_lead":
            target_emails = list(buyers_by_email.keys())
        else:
            raise ValueError(f"Unknown audience target '{audience}'. Permitted: 'business', 'individual', 'all', 'single_lead'.")

        candidates: List[Dict[str, Any]] = []
        seen = set()

        for raw_email in target_emails:
            em = str(raw_email).strip().lower()
            if not em or em in seen:
                continue
            seen.add(em)

            buyer_info = buyers_by_email.get(em, {
                "buyer_name": "",
                "company_name": "",
                "email": em,
                "website": "",
                "country": "",
                "source_platform": "Classification List",
            })

            log_info = class_logs_by_email.get(em, {})
            category = log_info.get("category", "business" if em in classified.get("business", []) else "individual")
            confidence = float(log_info.get("confidence", 0.90))

            candidates.append({
                "buyer_name": buyer_info.get("buyer_name", ""),
                "company_name": buyer_info.get("company_name", ""),
                "email": em,
                "website": buyer_info.get("website", ""),
                "country": buyer_info.get("country", ""),
                "source_platform": buyer_info.get("source_platform", ""),
                "classification": category,
                "confidence": confidence,
            })

        return candidates

    def evaluate_recipient_eligibility(
        self,
        candidate: Dict[str, Any],
        already_sent_set: Set[str],
        current_daily_sends: int,
        seen_in_batch: Set[str],
        is_test_mode: bool = False,
        test_simulations_today: int = 0,
    ) -> Tuple[bool, str, str, str]:
        """
        Evaluate eligibility for an individual candidate.
        Returns (is_eligible, duplicate_status, daily_limit_status, skip_reason).

        Phase 6H: Quota checks are split by mode:
          - REAL sends: checked against self.daily_limit
          - TEST simulations: checked against self.test_simulation_limit
        """
        em = candidate.get("email", "").strip().lower()

        # 1. Syntax & domain validity
        val_res = validate_single_email(em)
        if not val_res.is_valid:
            return False, "INVALID_SYNTAX", "ELIGIBLE", f"SKIPPED_INVALID ({val_res.reason})"

        # 2. Duplicate checking against historical sent_log and current batch
        if em in already_sent_set:
            return False, "PREVIOUSLY_SENT", "ELIGIBLE", "SKIPPED_DUPLICATE (Already contacted in sent_log.csv)"
        if em in seen_in_batch:
            return False, "BATCH_DUPLICATE", "ELIGIBLE", "SKIPPED_DUPLICATE (Duplicate in same batch)"

        # 3. Quota check — split by mode (Phase 6H)
        if is_test_mode:
            if test_simulations_today >= self.test_simulation_limit:
                return False, "NOT_SENT", "TEST_SIMULATION_LIMIT_REACHED", "SKIPPED_TEST_SIMULATION_LIMIT (Test simulation quota exhausted)"
        else:
            if current_daily_sends >= self.daily_limit:
                return False, "NOT_SENT", "DAILY_LIMIT_REACHED", "SKIPPED_DAILY_LIMIT (Daily send quota exhausted)"

        return True, "NOT_SENT", "ELIGIBLE", ""

    def prepare_campaign(
        self,
        target_audience: str = "business",
        template_text: Optional[str] = None,
        template_path: Optional[Path] = None,
        product_keyword: Optional[str] = None,
    ) -> Tuple[Campaign, List[CampaignRecipientPreview]]:
        """
        Construct a fresh campaign, inspect candidates, validate attachment, and build full preview list.
        Sets status to READY_FOR_REVIEW and persists to campaigns.json.
        """
        # 1. Attachment validation
        handler = AttachmentHandler(self.attachment_path)
        att_meta = handler.get_metadata()
        if not att_meta["is_valid"]:
            logger.warning(f"Attachment pre-flight check warning: {att_meta['message']}")

        # 2. Audience Candidates
        candidates = self.select_audience_candidates(target_audience)
        already_sent = get_sent_emails(self.sent_log_csv)
        # Phase 6H: use mode-specific quota function
        today_sends = get_real_sends_for_date(csv_path=self.sent_log_csv)
        today_test_sims = get_test_simulations_for_date(csv_path=self.sent_log_csv)

        # 3. Load Template
        raw_template = template_text or PersonalizationEngine.load_template_file(template_path)

        # 4. Create Campaign Instance
        campaign = Campaign.create_new(
            target_audience=target_audience,
            body_template=raw_template,
            attachment_path=str(handler.resolved_path),
        )

        previews: List[CampaignRecipientPreview] = []
        eligible_count = 0
        skipped_count = 0
        simulated_daily_sends = today_sends
        simulated_test_sims = today_test_sims
        seen_in_batch: Set[str] = set()

        for c in candidates:
            em = c["email"]
            is_eligible, dup_status, limit_status, skip_reason = self.evaluate_recipient_eligibility(
                candidate=c,
                already_sent_set=already_sent,
                current_daily_sends=simulated_daily_sends,
                seen_in_batch=seen_in_batch,
                is_test_mode=self.test_mode,
                test_simulations_today=simulated_test_sims,
            )

            seen_in_batch.add(em)
            if is_eligible:
                eligible_count += 1
                if self.test_mode:
                    simulated_test_sims += 1
                else:
                    simulated_daily_sends += 1
            else:
                skipped_count += 1

            # Render Personalized Preview
            subject, body = PersonalizationEngine.render_email(
                buyer=c,
                template_text=raw_template,
                product_keyword=product_keyword,
            )

            preview = CampaignRecipientPreview(
                email=em,
                company_name=c.get("company_name", ""),
                country=c.get("country", ""),
                classification=c.get("classification", "business"),
                confidence=c.get("confidence", 0.90),
                subject=subject,
                body_snippet=body[:140].replace("\n", " ") + ("..." if len(body) > 140 else ""),
                attachment_name=handler.resolved_path.name,
                duplicate_status=dup_status,
                daily_limit_status=limit_status,
                is_eligible=is_eligible,
                skip_reason=skip_reason,
            )
            previews.append(preview)

        # Set campaign metadata
        campaign.subject = previews[0].subject if previews else "Export Inquiry"
        campaign.total_recipients = len(candidates)
        campaign.eligible_recipients = eligible_count
        campaign.skipped_recipients = skipped_count
        campaign.recipients_summary = [p.to_dict() for p in previews]
        campaign.mark_ready_for_review()

        # Save to store
        CampaignStore.save_campaign(campaign, file_path=self.campaigns_file)
        return campaign, previews

    def prepare_single_lead_campaign(
        self,
        buyer_record: Dict[str, Any],
        template_text: Optional[str] = None,
        template_path: Optional[Path] = None,
        product_keyword: Optional[str] = None,
    ) -> Tuple[Campaign, List[CampaignRecipientPreview]]:
        """
        Construct a fresh campaign targeted exclusively at a single approved lead.
        Sets status to READY_FOR_REVIEW and persists to campaigns.json.
        Requires explicit campaign approval before simulated execution.
        """
        handler = AttachmentHandler(self.attachment_path)
        raw_template = template_text or PersonalizationEngine.load_template_file(template_path)

        campaign = Campaign.create_new(
            target_audience="single_lead",
            body_template=raw_template,
            attachment_path=str(handler.resolved_path),
        )

        em = buyer_record.get("email", "").strip().lower()
        # 2. Audience Candidates
        already_sent = get_sent_emails(self.sent_log_csv)
        # Phase 6H: use mode-specific quota function
        today_sends = get_real_sends_for_date(csv_path=self.sent_log_csv)
        today_test_sims = get_test_simulations_for_date(csv_path=self.sent_log_csv)

        is_eligible, dup_status, limit_status, skip_reason = self.evaluate_recipient_eligibility(
            candidate=buyer_record,
            already_sent_set=already_sent,
            current_daily_sends=today_sends,
            seen_in_batch=set(),
            is_test_mode=self.test_mode,
            test_simulations_today=today_test_sims,
        )

        subject, body = PersonalizationEngine.render_email(
            buyer=buyer_record,
            template_text=raw_template,
            product_keyword=product_keyword,
        )

        preview = CampaignRecipientPreview(
            email=em,
            company_name=buyer_record.get("company_name", ""),
            country=buyer_record.get("country", ""),
            classification=buyer_record.get("classification", "business"),
            confidence=float(buyer_record.get("confidence", 0.95)),
            subject=subject,
            body_snippet=body[:140].replace("\n", " ") + ("..." if len(body) > 140 else ""),
            attachment_name=handler.resolved_path.name,
            duplicate_status=dup_status,
            daily_limit_status=limit_status,
            is_eligible=is_eligible,
            skip_reason=skip_reason,
        )

        campaign.subject = subject
        campaign.total_recipients = 1
        campaign.eligible_recipients = 1 if is_eligible else 0
        campaign.skipped_recipients = 0 if is_eligible else 1
        campaign.recipients_summary = [preview.to_dict()]
        campaign.mark_ready_for_review()

        CampaignStore.save_campaign(campaign, file_path=self.campaigns_file)
        return campaign, [preview]

    def display_campaign_preview(
        self,
        campaign: Campaign,
        previews: List[CampaignRecipientPreview],
    ) -> None:
        """Render a formatted, reviewable console preview before approval."""
        banner = "=" * 65
        sub = "-" * 65

        print(f"\n{banner}")
        print("            OUTREACH CAMPAIGN PREVIEW & APPROVAL GATE")
        print(f"{banner}")
        print(f"Campaign ID        : {campaign.campaign_id}")
        print(f"Target Audience    : {campaign.target_audience.upper()}")
        print(f"Status             : {campaign.status.value}")
        print(f"Execution Mode     : {'TEST MODE / DRY RUN (Simulated)' if self.test_mode else 'LIVE GMAIL'}")
        print(f"Attachment File    : {campaign.attachment_path}")
        print(f"Daily Send Limit   : {self.daily_limit}")
        print(f"Candidates Loaded  : {campaign.total_recipients}")
        print(f"Eligible to Send   : {campaign.eligible_recipients}")
        print(f"Skipped / Filtered : {campaign.skipped_recipients}")
        print(sub)
        print("RECIPIENT PREVIEW TABLE:")
        print(f"{'#':<3} | {'Recipient':<30} | {'Company':<20} | {'Status':<15}")
        print(sub)

        for idx, p in enumerate(previews, 1):
            status_desc = "ELIGIBLE" if p.is_eligible else p.skip_reason.split()[0]
            print(f"{idx:<3} | {p.email:<30} | {p.company_name[:18]:<20} | {status_desc:<15}")

        print(sub)
        if previews:
            sample = previews[0]
            print("\nSAMPLE PERSONALIZED EMAIL (Recipient #1):")
            print(f"  To         : {sample.email}")
            print(f"  Subject    : {sample.subject}")
            print(f"  Attachment : {sample.attachment_name}")
            print("  Body Snippet:")
            print(f"    {sample.body_snippet}\n")

        print(banner)
        print("APPROVAL INSTRUCTIONS:")
        print(f"  1. Review the recipient list and sample above.")
        print(f"  2. To approve: python main.py --approve-campaign {campaign.campaign_id}")
        print(f"  3. To dispatch in TEST_MODE: python main.py --send --test --campaign-id {campaign.campaign_id}")
        print(f"{banner}\n")

    def approve_campaign(self, campaign_id: str) -> Campaign:
        """
        Execute approval action for a specified campaign ID.
        Transitions campaign from READY_FOR_REVIEW -> APPROVED.
        """
        campaign = CampaignStore.get_campaign(campaign_id, file_path=self.campaigns_file)
        if not campaign:
            raise ValueError(f"Campaign with ID '{campaign_id}' not found in datastore.")

        campaign.approve()
        CampaignStore.save_campaign(campaign, file_path=self.campaigns_file)
        return campaign

    def execute_campaign(
        self,
        campaign_id: Optional[str] = None,
        target_audience: str = "business",
        force_test_mode: Optional[bool] = None,
        product_keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute an approved campaign with strict safety checks:
          - Validates attachment (STOPS if missing)
          - Checks daily send limit
          - Prevents duplicate sends
          - Simulates in TEST_MODE
          - Logs to campaign_log.csv and sent_log.csv
        """
        is_test = self.test_mode if force_test_mode is None else force_test_mode

        # 1. Retrieve or prepare campaign
        campaign: Optional[Campaign] = None
        if campaign_id:
            campaign = CampaignStore.get_campaign(campaign_id, file_path=self.campaigns_file)
            if not campaign:
                raise ValueError(f"Campaign '{campaign_id}' not found.")
        else:
            # Look for most recent APPROVED campaign or create & approve for flow
            campaigns = CampaignStore.load_campaigns(file_path=self.campaigns_file)
            approved = [c for c in campaigns if c.status == CampaignStatus.APPROVED]
            if approved:
                campaign = approved[-1]
            else:
                # If no approved campaign exists, raise error requiring approval
                raise CampaignStateError(
                    "No APPROVED campaign found to execute. "
                    "Run 'python main.py --campaign-preview' and 'python main.py --approve-campaign <id>' first."
                )

        # 2. Strict Approval Verification
        if campaign.status != CampaignStatus.APPROVED:
            raise CampaignStateError(
                f"Campaign '{campaign.campaign_id}' is in status '{campaign.status.value}'. "
                "Only APPROVED campaigns can be executed."
            )

        # 3. Attachment Validation Check (STOP IF MISSING)
        handler = AttachmentHandler(campaign.attachment_path)
        att_valid, att_msg = handler.validate()
        if not att_valid:
            campaign.mark_failed(f"Attachment validation failed: {att_msg}")
            CampaignStore.save_campaign(campaign, file_path=self.campaigns_file)
            raise AttachmentError(f"Campaign execution aborted! {att_msg}")

        # 4. Mark Running
        campaign.mark_running()
        CampaignStore.save_campaign(campaign, file_path=self.campaigns_file)

        # 5. Resolve candidates
        if campaign.target_audience == "single_lead" and campaign.recipients_summary:
            recip_emails = {r["email"].lower() for r in campaign.recipients_summary if r.get("email")}
            all_candidates = self.select_audience_candidates("single_lead")
            candidates = [c for c in all_candidates if c["email"].lower() in recip_emails]
            if not candidates:
                candidates = [
                    {
                        "buyer_name": r.get("buyer_name", ""),
                        "company_name": r.get("company_name", ""),
                        "email": r.get("email", ""),
                        "website": r.get("website", ""),
                        "country": r.get("country", ""),
                        "source_platform": "Lead Review Approval",
                        "classification": r.get("classification", "business"),
                        "confidence": float(r.get("confidence", 0.95)),
                    }
                    for r in campaign.recipients_summary
                ]
        else:
            candidates = self.select_audience_candidates(campaign.target_audience)

        already_sent = get_sent_emails(self.sent_log_csv)
        # Phase 6H: split quota counters by mode
        today_sends = get_real_sends_for_date(csv_path=self.sent_log_csv)
        today_test_sims = get_test_simulations_for_date(csv_path=self.sent_log_csv)

        sender = GmailSender(
            test_mode=is_test,
            daily_limit=self.daily_limit,
            presentation_path=campaign.attachment_path,
            sent_log_path=self.sent_log_csv,
        )

        seen_in_run: Set[str] = set()
        campaign_log_records: List[Dict[str, Any]] = []

        eligible_processed = 0
        duplicates_skipped = 0
        daily_limit_skipped = 0
        invalid_skipped = 0
        successful_sends = 0
        failed_sends = 0

        raw_template = campaign.body_template or PersonalizationEngine.load_template_file()

        for c in candidates:
            em = c["email"]

            # Evaluate eligibility dynamically (Phase 6H: mode-split quotas)
            is_eligible, dup_status, limit_status, skip_reason = self.evaluate_recipient_eligibility(
                candidate=c,
                already_sent_set=already_sent,
                current_daily_sends=today_sends,
                seen_in_batch=seen_in_run,
                is_test_mode=is_test,
                test_simulations_today=today_test_sims,
            )

            # Render Personalized Email
            subject, body = PersonalizationEngine.render_email(
                buyer=c,
                template_text=raw_template,
                product_keyword=product_keyword,
            )

            if not is_eligible:
                if "DUPLICATE" in skip_reason:
                    duplicates_skipped += 1
                    status_log = "SKIPPED_DUPLICATE"
                elif "DAILY_LIMIT" in skip_reason or "SIMULATION_LIMIT" in skip_reason:
                    daily_limit_skipped += 1
                    status_log = "SKIPPED_DAILY_LIMIT"
                else:
                    invalid_skipped += 1
                    status_log = "SKIPPED_INVALID"

                # Record skipped entry in campaign log
                campaign_log_records.append({
                    "campaign_id": campaign.campaign_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "recipient": em,
                    "company_name": c.get("company_name", ""),
                    "audience": campaign.target_audience,
                    "subject": subject,
                    "status": status_log,
                    "mode": "TEST" if is_test else "LIVE",
                    "error": skip_reason,
                })
                continue

            # Record in same-run set
            seen_in_run.add(em)
            eligible_processed += 1

            # Dispatch via GmailSender (Phase 6H: pass campaign_id for traceability)
            res = sender.send_single_email(
                buyer=c,
                personalized_subject=subject,
                personalized_body=body,
                campaign_id=campaign.campaign_id,
            )

            dispatch_status = "TEST_MODE_SUCCESS" if res.is_simulated else res.status

            if res.is_simulated or res.status == "SUCCESS":
                successful_sends += 1
                if is_test:
                    today_test_sims += 1
                else:
                    today_sends += 1
                already_sent.add(em)
            else:
                failed_sends += 1

            # Append to campaign log
            campaign_log_records.append({
                "campaign_id": campaign.campaign_id,
                "timestamp": res.timestamp,
                "recipient": em,
                "company_name": c.get("company_name", ""),
                "audience": campaign.target_audience,
                "subject": subject,
                "status": dispatch_status,
                "mode": "TEST" if is_test else "LIVE",
                "error": res.error_message or "",
            })

            # Send delay if multiple eligible sends in live/test run
            if self.send_delay > 0 and eligible_processed < campaign.eligible_recipients:
                # Apply small delay in test mode or full in live
                delay = min(0.05, self.send_delay) if is_test else self.send_delay
                time.sleep(delay)

        # 6. Save campaign logs
        save_campaign_log(campaign_log_records, csv_path=self.campaign_log_csv, append=True)

        # 7. Complete Campaign
        campaign.mark_completed()
        CampaignStore.save_campaign(campaign, file_path=self.campaigns_file)

        return {
            "campaign_id": campaign.campaign_id,
            "target_audience": campaign.target_audience,
            "mode": "TEST / DRY RUN" if is_test else "LIVE GMAIL",
            "total_candidates": len(candidates),
            "eligible_recipients": eligible_processed,
            "duplicates_skipped": duplicates_skipped,
            "daily_limit_skipped": daily_limit_skipped,
            "invalid_skipped": invalid_skipped,
            "successful_sends": successful_sends,
            "failed_sends": failed_sends,
            "attachment_path": campaign.attachment_path,
            "attachment_status": "VALIDATED (" + handler.resolved_path.name + ")",
            "start_time": campaign.started_at,
            "end_time": campaign.completed_at,
        }
