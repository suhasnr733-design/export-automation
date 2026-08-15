"""
Attachment Handler Module for API 3 - EXPORT Automation System.
Validates the presence, file type, non-emptiness, and readability of sales presentations,
and constructs MIME attachments.
"""

from email.mime.application import MIMEApplication
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Set
from config import Config
from logging.activity_logger import logger


class AttachmentError(Exception):
    """Custom exception raised when an attachment cannot be located, validated, or loaded."""
    pass


class AttachmentHandler:
    """Handles attachment validation, type verification, and MIME encoding."""

    ALLOWED_EXTENSIONS: Set[str] = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".zip"}

    def __init__(self, file_path: Optional[str] = None):
        self.raw_path = file_path or Config.PRESENTATION_PATH
        self.resolved_path = self._resolve_path(self.raw_path)

    @staticmethod
    def _resolve_path(path_str: str) -> Path:
        """Resolve path against project BASE_DIR if relative."""
        p = Path(path_str)
        if p.is_absolute():
            return p
        return Config.BASE_DIR / p

    def get_metadata(self) -> Dict[str, Any]:
        """
        Return structured metadata about the attachment file including existence, size, and validity.
        """
        exists = self.resolved_path.exists()
        is_file = self.resolved_path.is_file() if exists else False
        size_bytes = self.resolved_path.stat().st_size if is_file else 0
        ext = self.resolved_path.suffix.lower()

        is_valid, reason = self.validate()

        return {
            "path": str(self.resolved_path),
            "filename": self.resolved_path.name,
            "exists": exists,
            "is_file": is_file,
            "size_bytes": size_bytes,
            "size_kb": round(size_bytes / 1024, 2),
            "extension": ext,
            "is_valid": is_valid,
            "message": reason,
        }

    def validate(self) -> Tuple[bool, str]:
        """
        Comprehensive pre-flight validation:
          1. Path exists
          2. Path is a regular file
          3. Allowed file extension (.pdf, .pptx, etc.)
          4. File is not empty (size > 0 bytes)
          5. File is readable
        Returns (is_valid, message).
        """
        if not self.resolved_path.exists():
            msg = (
                f"Presentation file not found at: '{self.resolved_path}'. "
                "Please place your company presentation PDF at this location or update PRESENTATION_PATH in .env."
            )
            logger.error(msg)
            return False, msg

        if not self.resolved_path.is_file():
            msg = f"Configured presentation path is not a regular file: '{self.resolved_path}'"
            logger.error(msg)
            return False, msg

        # Check allowed extension
        ext = self.resolved_path.suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            msg = f"Unsupported attachment file extension '{ext}'. Allowed: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            logger.error(msg)
            return False, msg

        # Check file is not empty
        try:
            size = self.resolved_path.stat().st_size
            if size == 0:
                msg = f"Presentation file '{self.resolved_path.name}' is empty (0 bytes)."
                logger.error(msg)
                return False, msg
        except Exception as e:
            msg = f"Cannot inspect file stats for '{self.resolved_path}': {e}"
            logger.error(msg)
            return False, msg

        # Check read permission
        try:
            with open(self.resolved_path, "rb") as f:
                f.read(min(1024, size))
        except Exception as e:
            msg = f"Cannot read presentation file '{self.resolved_path}': {e}"
            logger.error(msg)
            return False, msg

        return True, f"Presentation file validated successfully ({self.resolved_path.name}, {round(size/1024, 1)} KB)."

    def create_mime_attachment(self) -> MIMEApplication:
        """
        Read the presentation file and construct a MIMEApplication attachment.
        Raises AttachmentError if validation fails.
        """
        is_valid, error_msg = self.validate()
        if not is_valid:
            raise AttachmentError(error_msg)

        try:
            with open(self.resolved_path, "rb") as f:
                content = f.read()

            part = MIMEApplication(content, Name=self.resolved_path.name)
            part["Content-Disposition"] = f'attachment; filename="{self.resolved_path.name}"'
            logger.debug(f"Created MIME attachment: {self.resolved_path.name} ({len(content)} bytes)")
            return part
        except Exception as e:
            raise AttachmentError(f"Failed to create MIME attachment from '{self.resolved_path}': {e}")
