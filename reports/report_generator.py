"""
Reporting Module for API 3 - EXPORT Automation System.
Generates comprehensive run metrics, console summaries, campaign reports, and exports.
"""

import csv
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from config import Config
from app_logging.activity_logger import logger


@dataclass
class RunMetrics:
    """Stores execution metrics across all pipeline stages."""
    total_buyers_discovered: int = 0
    valid_emails: int = 0
    invalid_emails: int = 0
    duplicate_contacts: int = 0
    business_contacts: int = 0
    individual_contacts: int = 0
    total_queued: int = 0
    successful_sends: int = 0
    failed_sends: int = 0
    test_mode_sends: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReportGenerator:
    """Renders formatted execution reports and exports metrics."""

    def __init__(self, metrics: Optional[RunMetrics] = None):
        self.metrics = metrics or RunMetrics()

    def print_console_summary(self) -> None:
        """Render a clean, formatted ASCII run summary in the console."""
        m = self.metrics
        banner = "=" * 60
        sub_banner = "-" * 60

        print(f"\n{banner}")
        print("                 PIPELINE RUN SUMMARY")
        print(f"{banner}")
        print(f"Keyword Tested           : {Config.SEARCH_KEYWORD}")
        print(f"Execution Mode           : {'TEST MODE (SIMULATED)' if Config.TEST_MODE else 'LIVE MODE'}")
        print(f"Timestamp                : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(sub_banner)
        print(f"Total Buyers Discovered  : {m.total_buyers_discovered}")
        print(f"Valid Emails             : {m.valid_emails}")
        print(f"Invalid Emails Filtered  : {m.invalid_emails}")
        print(f"Duplicate Emails Removed : {m.duplicate_contacts}")
        print(sub_banner)
        print(f"Business Contacts (B2B)  : {m.business_contacts}")
        print(f"Individual Contacts      : {m.individual_contacts}")
        print(sub_banner)
        print(f"Total Contacts Queued    : {m.total_queued}")
        if Config.TEST_MODE:
            print(f"Test-Mode Simulated Sends: {m.test_mode_sends}")
        else:
            print(f"Live Successful Sends    : {m.successful_sends}")
            print(f"Live Failed Sends        : {m.failed_sends}")
        print(f"{banner}\n")

    @staticmethod
    def print_campaign_report(report_data: Dict[str, Any]) -> None:
        """
        Render a formatted Campaign Report conforming to Phase 4 specifications.
        """
        banner = "=" * 60
        sub_banner = "-" * 60

        cid = report_data.get("campaign_id", "N/A")
        aud = str(report_data.get("target_audience", "business")).upper()
        mode = report_data.get("mode", "TEST / DRY RUN")

        total_candidates = report_data.get("total_candidates", 0)
        eligible = report_data.get("eligible_recipients", 0)
        dup_skipped = report_data.get("duplicates_skipped", 0)
        inv_skipped = report_data.get("invalid_skipped", 0)
        limit_skipped = report_data.get("daily_limit_skipped", 0)

        success = report_data.get("successful_sends", 0)
        failed = report_data.get("failed_sends", 0)
        att_status = report_data.get("attachment_status", "VALIDATED")
        status = report_data.get("status", "COMPLETED")
        start_t = report_data.get("start_time", "N/A")
        end_t = report_data.get("end_time", "N/A")

        print(f"\n{banner}")
        print("                      CAMPAIGN REPORT")
        print(f"{banner}")
        print(f"Campaign            : {cid}")
        print(f"Audience            : {aud}")
        print(f"Mode                : {mode}")
        print(sub_banner)
        print(f"Candidates Loaded   : {total_candidates}")
        print(f"Eligible Recipients : {eligible}")
        print(f"Duplicates Skipped  : {dup_skipped}")
        print(f"Invalid Skipped     : {inv_skipped}")
        print(f"Daily Limit Skipped : {limit_skipped}")
        print(sub_banner)
        print(f"Successful Sends    : {success}")
        print(f"Failed Sends        : {failed}")
        print(sub_banner)
        print(f"Attachment          : {att_status}")
        print(f"Execution Status    : {status}")
        print(f"Start Time          : {start_t}")
        print(f"End Time            : {end_t}")
        print(f"{banner}\n")

    def export_summary_csv(self, file_path: Optional[Path] = None) -> Path:
        """
        Export summary metrics to a CSV file.
        Useful for future web dashboard downloads or automated archiving.
        """
        target = file_path or (Config.DATA_DIR / f"run_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        target.parent.mkdir(parents=True, exist_ok=True)

        data = self.metrics.to_dict()
        with open(target, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            for k, v in data.items():
                writer.writerow([k, v])

        logger.info(f"Summary report exported to: {target}")
        return target
