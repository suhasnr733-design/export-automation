import os
import re
from email.mime.application import MIMEApplication
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Set
from config import Config
from app_logging.activity_logger import logger


class AttachmentError(Exception):
    """Custom exception raised when an attachment cannot be located, validated, or loaded."""
    pass


class AttachmentHandler:
    """Handles attachment validation, type verification, and MIME encoding."""

    ALLOWED_EXTENSIONS: Set[str] = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".zip"}

    def __init__(self, file_path: Optional[str] = None):
        self.raw_path = file_path or Config.PRESENTATION_PATH
        self.resolved_path = self.resolve_attachment_path(self.raw_path)

    @classmethod
    def resolve_attachment_path(cls, path_str: Optional[str] = None) -> Path:
        """
        Safely resolve attachment path across different operating systems and deployment environments.

        Handles:
          1. Direct existing absolute or relative paths on the local filesystem.
          2. Historical Windows absolute paths (e.g. 'C:\\Users\\...') deployed onto Linux/POSIX systems.
          3. Stale local paths from other environments that do not exist on the current system,
             normalizing to the deployed Config.PRESENTATION_PATH / Config.ASSETS_DIR when matching
             the presentation asset or assets directory.
          4. Clean preservation of intentional non-existent paths for validation testing.
        """
        if not path_str or str(path_str).strip() == "":
            return Config.get_presentation_file_path()

        raw = str(path_str).strip()

        # 1. Check if the path exists directly as-is on the current filesystem
        try:
            p_direct = Path(raw)
            if p_direct.exists() and p_direct.is_file():
                return p_direct.resolve() if p_direct.is_absolute() else (Config.BASE_DIR / p_direct).resolve()
        except Exception:
            pass

        # 2. Check if relative to Config.BASE_DIR (normalizing backslashes)
        has_win_drive = bool(re.match(r"^[a-zA-Z]:[\\/]", raw))
        if not has_win_drive:
            try:
                norm_rel = raw.replace("\\", "/")
                p_rel = Config.BASE_DIR / norm_rel
                if p_rel.exists() and p_rel.is_file():
                    return p_rel.resolve()
            except Exception:
                pass

        # 3. Handle historical or foreign paths whose filename exists in assets or matches default presentation
        norm_posix = raw.replace("\\", "/")
        filename = Path(norm_posix).name
        default_presentation = Config.get_presentation_file_path()

        if filename:
            # Check if this exact filename exists in the project assets directory
            candidate_in_assets = Config.ASSETS_DIR / filename
            if candidate_in_assets.exists() and candidate_in_assets.is_file():
                return candidate_in_assets.resolve()

            # Check if filename matches configured presentation name
            if default_presentation.exists() and filename == default_presentation.name:
                return default_presentation.resolve()

            # If raw path referenced assets/ or company_presentation in historical absolute path
            if "company_presentation" in filename:
                if default_presentation.exists():
                    return default_presentation.resolve()

        # 4. For foreign Windows drive paths on Linux/POSIX that are completely missing
        if has_win_drive:
            try:
                p_win = Path(raw)
                if p_win.is_absolute():
                    return p_win
            except Exception:
                pass
            return Path(norm_posix)

        # 5. Default preservation for custom paths (allows missing-file tests to fail appropriately)
        p_fallback = Path(raw)
        return p_fallback if p_fallback.is_absolute() else (Config.BASE_DIR / p_fallback)

    @classmethod
    def _resolve_path(cls, path_str: str) -> Path:
        """Backwards-compatible alias for resolve_attachment_path."""
        return cls.resolve_attachment_path(path_str)

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
