"""
Configuration Module for API 3 - EXPORT Automation System.
Loads environment variables and provides structured access to settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory Resolution
BASE_DIR = Path(__file__).resolve().parent

# Load .env if present
load_dotenv(dotenv_path=BASE_DIR / ".env")


def _str_to_bool(val: str, default: bool = True) -> bool:
    """Convert string environment variable to boolean safely."""
    if val is None:
        return default
    val = str(val).strip().lower()
    if val in ("true", "1", "t", "yes", "y"):
        return True
    if val in ("false", "0", "f", "no", "n"):
        return False
    return default


class Config:
    """Application configuration container."""

    # Project Paths
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    ASSETS_DIR: Path = BASE_DIR / "assets"
    TEMPLATES_DIR: Path = BASE_DIR / "templates"

    # CSV & JSON Data File Paths
    BUYERS_CSV: Path = DATA_DIR / "buyers.csv"
    BUSINESS_EMAILS_CSV: Path = DATA_DIR / "business_emails.csv"
    INDIVIDUAL_EMAILS_CSV: Path = DATA_DIR / "individual_emails.csv"
    CLASSIFICATION_LOG_CSV: Path = DATA_DIR / "classification_log.csv"
    QUALIFICATION_LOG_CSV: Path = DATA_DIR / "qualification_log.csv"
    LEAD_REVIEW_LOG_CSV: Path = DATA_DIR / "lead_review_log.csv"
    CAMPAIGN_LOG_CSV: Path = DATA_DIR / "campaign_log.csv"
    CAMPAIGNS_FILE: Path = DATA_DIR / "campaigns.json"
    SENT_LOG_CSV: Path = DATA_DIR / "sent_log.csv"
    DISCOVERY_PROVENANCE_FILE: Path = DATA_DIR / "discovery_provenance.json"
    DEFAULT_TEMPLATE_PATH: Path = TEMPLATES_DIR / "outreach_template.txt"

    # Search & Discovery Settings
    SEARCH_KEYWORD: str = os.getenv("SEARCH_KEYWORD", "Singing Bowls").strip()
    SEARCH_DELAY: float = float(os.getenv("SEARCH_DELAY", "1.0"))
    MAX_SEARCH_RESULTS: int = int(os.getenv("MAX_SEARCH_RESULTS", "50"))
    MAX_WEBSITES_PER_RESULT: int = int(os.getenv("MAX_WEBSITES_PER_RESULT", "5"))
    TEST_DISCOVERY: bool = _str_to_bool(os.getenv("TEST_DISCOVERY", "false"), default=False)
    DEFAULT_USER_AGENT: str = os.getenv(
        "DEFAULT_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "").strip()
    GOOGLE_CSE_ID: str = os.getenv("GOOGLE_CSE_ID", "").strip()

    # Classification Settings
    CLASSIFICATION_BATCH_SIZE: int = int(os.getenv("CLASSIFICATION_BATCH_SIZE", "20"))
    CLASSIFICATION_REVIEW_THRESHOLD: float = float(os.getenv("CLASSIFICATION_REVIEW_THRESHOLD", "0.70"))

    # Outreach Limits & Timing
    DAILY_SEND_LIMIT: int = int(os.getenv("DAILY_SEND_LIMIT", "10"))
    TEST_SIMULATION_LIMIT: int = int(os.getenv("TEST_SIMULATION_LIMIT", "50"))
    SEND_DELAY: float = float(os.getenv("SEND_DELAY", "5.0"))
    CC_MONITOR_EMAIL: str = os.getenv("CC_MONITOR_EMAIL", "").strip()

    # Attachments
    PRESENTATION_PATH: str = os.getenv("PRESENTATION_PATH", "assets/company_presentation.pdf").strip()

    # Gmail SMTP Credentials
    GMAIL_EMAIL: str = os.getenv("GMAIL_EMAIL", os.getenv("GMAIL_SENDER_EMAIL", "")).strip()
    GMAIL_SENDER_EMAIL: str = GMAIL_EMAIL
    GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "").strip()

    # Gemini AI Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
    CLASSIFICATION_LIVE: bool = _str_to_bool(os.getenv("CLASSIFICATION_LIVE", "false"), default=False)

    # Safety Mode: TEST_MODE=true strictly disables real email sending
    TEST_MODE: bool = _str_to_bool(os.getenv("TEST_MODE", "true"), default=True)
    RESET_ON_STARTUP: bool = _str_to_bool(os.getenv("RESET_ON_STARTUP", "false"), default=False)

    @classmethod
    def get_presentation_file_path(cls) -> Path:
        """Resolve presentation path relative to BASE_DIR if not absolute."""
        p = Path(cls.PRESENTATION_PATH)
        if p.is_absolute():
            return p
        return cls.BASE_DIR / p

    @classmethod
    def is_gemini_available(cls) -> bool:
        """Check if Gemini API is configured and live classification is enabled."""
        return bool(cls.GEMINI_API_KEY) and cls.CLASSIFICATION_LIVE

    @classmethod
    def is_live_gmail_ready(cls) -> bool:
        """Check if live Gmail sending has prerequisites configured."""
        return bool(cls.GMAIL_EMAIL and cls.GMAIL_APP_PASSWORD and not cls.TEST_MODE)

    @classmethod
    def to_dict(cls, mask_secrets: bool = True) -> dict:
        """Return configuration summary dictionary with masked secrets."""
        return {
            "SEARCH_KEYWORD": cls.SEARCH_KEYWORD,
            "SEARCH_DELAY": cls.SEARCH_DELAY,
            "MAX_SEARCH_RESULTS": cls.MAX_SEARCH_RESULTS,
            "MAX_WEBSITES_PER_RESULT": cls.MAX_WEBSITES_PER_RESULT,
            "TEST_DISCOVERY": cls.TEST_DISCOVERY,
            "CLASSIFICATION_BATCH_SIZE": cls.CLASSIFICATION_BATCH_SIZE,
            "CLASSIFICATION_REVIEW_THRESHOLD": cls.CLASSIFICATION_REVIEW_THRESHOLD,
            "CLASSIFICATION_LIVE": cls.CLASSIFICATION_LIVE,
            "DAILY_SEND_LIMIT": cls.DAILY_SEND_LIMIT,
            "TEST_SIMULATION_LIMIT": cls.TEST_SIMULATION_LIMIT,
            "SEND_DELAY": cls.SEND_DELAY,
            "PRESENTATION_PATH": cls.PRESENTATION_PATH,
            "GMAIL_EMAIL": cls.GMAIL_EMAIL if not mask_secrets else (
                f"{cls.GMAIL_EMAIL[:3]}***@{cls.GMAIL_EMAIL.split('@')[-1]}" if "@" in cls.GMAIL_EMAIL else "***"
            ),
            "GMAIL_APP_PASSWORD": "***" if mask_secrets and cls.GMAIL_APP_PASSWORD else (cls.GMAIL_APP_PASSWORD if not mask_secrets else ""),
            "GEMINI_API_KEY": "***" if mask_secrets and cls.GEMINI_API_KEY else (cls.GEMINI_API_KEY if not mask_secrets else ""),
            "TEST_MODE": cls.TEST_MODE,
        }

    @classmethod
    def __repr__(cls) -> str:
        return f"<Config TEST_MODE={cls.TEST_MODE} KEYWORD='{cls.SEARCH_KEYWORD}' LIMIT={cls.DAILY_SEND_LIMIT}>"
