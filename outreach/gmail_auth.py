"""
Gmail Authentication and SMTP Client Manager.
Provides authenticated SMTP sessions for Gmail outreach while securing credentials.
"""

import smtplib
import ssl
from typing import Optional, Tuple, Union
from config import Config
from app_logging.activity_logger import logger


class GmailAuth:
    """Manages Gmail SMTP authentication and session initialization."""

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT_SSL = 465
    SMTP_PORT_TLS = 587

    def __init__(self, email: Optional[str] = None, app_password: Optional[str] = None):
        self.email = email or Config.GMAIL_EMAIL
        self.app_password = app_password or Config.GMAIL_APP_PASSWORD

    def validate_credentials(self) -> Tuple[bool, str]:
        """
        Check if Gmail credentials are provided without exposing the password in logs.
        """
        if not self.email:
            return False, "GMAIL_EMAIL is not set in configuration or .env."
        if not self.app_password:
            return False, "GMAIL_APP_PASSWORD is not set in configuration or .env."
        return True, "Credentials format verified."

    def connect(self) -> Union[smtplib.SMTP_SSL, smtplib.SMTP]:
        """
        Establish an authenticated SSL connection with Gmail SMTP.
        Never logs or outputs the app password.
        """
        is_valid, msg = self.validate_credentials()
        if not is_valid:
            raise ValueError(f"Gmail Authentication Failed: {msg}")

        # Attempt 1: Connect via SMTP_SSL on port 465 (preferred)
        context = ssl.create_default_context()
        try:
            logger.info(f"Connecting to Gmail SMTP ({self.SMTP_HOST}:{self.SMTP_PORT_SSL}) for {self.email[:3]}***")
            server = smtplib.SMTP_SSL(self.SMTP_HOST, self.SMTP_PORT_SSL, context=context, timeout=15)
            server.login(self.email, self.app_password)
            logger.info("Successfully authenticated with Gmail SMTP.")
            return server
        except smtplib.SMTPAuthenticationError as e:
            logger.error("Gmail SMTP authentication failed. Check your App Password in Google Account settings.")
            raise ConnectionError("Invalid Gmail App Password or Account credentials.") from e
        except (OSError, smtplib.SMTPException) as e:
            logger.warning(f"SMTP_SSL connection on port {self.SMTP_PORT_SSL} failed: {e}. Trying fallback...")

        # Attempt 2: Fallback to STARTTLS on port 587
        try:
            logger.info(f"Fallback: Connecting to Gmail SMTP ({self.SMTP_HOST}:{self.SMTP_PORT_TLS}) with STARTTLS...")
            server = smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT_TLS, timeout=15)
            server.starttls(context=context)
            server.login(self.email, self.app_password)
            logger.info("Successfully authenticated with Gmail SMTP via STARTTLS fallback.")
            return server
        except smtplib.SMTPAuthenticationError as e:
            logger.error("Gmail SMTP authentication failed. Check your App Password in Google Account settings.")
            raise ConnectionError("Invalid Gmail App Password or Account credentials.") from e
        except Exception as e:
            error_message = (
                f"SMTP Connection Error: All connection attempts failed. Last error: {e}. "
                "Please check your internet connection, firewall settings, and ensure "
                f"outbound access to {self.SMTP_HOST} on ports {self.SMTP_PORT_SSL} or {self.SMTP_PORT_TLS} is allowed."
            )
            logger.error(error_message)
            raise ConnectionError(error_message) from e

    def test_connection(self) -> Tuple[bool, str]:  # type: ignore
        """
        Test SMTP connectivity and credentials without sending an email.
        """
        try:
            server = self.connect()
            server.quit()
            return True, "Gmail SMTP credentials verified successfully."
        except Exception as e:
            return False, str(e)
