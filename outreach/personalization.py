"""
Personalization Engine Module for API 3 - EXPORT Automation System.
Renders customized, professional export business outreach emails with robust fallbacks.
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from config import Config
from app_logging.activity_logger import logger


class PersonalizationEngine:
    """Renders personalized outreach subjects and body templates with safe fallbacks."""

    FALLBACK_BUYER_NAME = "Procurement Team"
    FALLBACK_COMPANY_NAME = "your organization"
    FALLBACK_COUNTRY = "international markets"
    FALLBACK_WEBSITE = "your website"
    FALLBACK_PRODUCT = "Handcrafted Export Products"

    # Default Subject if none is defined in the template
    DEFAULT_SUBJECT_TEMPLATE = "Wholesale Export Catalog: Handcrafted {{product}} for {{company_name}}"

    @classmethod
    def clean_field_value(cls, val: Any, fallback: str) -> str:
        """
        Ensure field value is non-empty and does not contain string artifacts like 'None', 'null', 'n/a'.
        Returns cleaned string or the provided fallback.
        """
        if val is None:
            return fallback
        s = str(val).strip()
        if not s or s.lower() in ("none", "null", "n/a", "undefined", "unknown", "nan"):
            return fallback
        return s

    @classmethod
    def get_personalization_context(
        cls,
        buyer: Dict[str, Any],
        product_keyword: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Build safe personalization dictionary from a buyer record with professional fallbacks.
        """
        product = product_keyword or Config.SEARCH_KEYWORD or cls.FALLBACK_PRODUCT
        cleaned_product = cls.clean_field_value(product, cls.FALLBACK_PRODUCT)

        buyer_name = cls.clean_field_value(buyer.get("buyer_name"), cls.FALLBACK_BUYER_NAME)
        company_name = cls.clean_field_value(buyer.get("company_name"), cls.FALLBACK_COMPANY_NAME)
        country = cls.clean_field_value(buyer.get("country"), cls.FALLBACK_COUNTRY)
        website = cls.clean_field_value(buyer.get("website"), cls.FALLBACK_WEBSITE)
        email = cls.clean_field_value(buyer.get("email"), "")

        return {
            "buyer_name": buyer_name,
            "company_name": company_name,
            "country": country,
            "website": website,
            "email": email,
            "product": cleaned_product,
        }

    @classmethod
    def render_template(
        cls,
        template_text: str,
        buyer: Dict[str, Any],
        product_keyword: Optional[str] = None,
    ) -> str:
        """
        Replace all {{placeholder}} tags with contextual values.
        Ensures no 'None', 'null', or raw placeholders remain.
        """
        ctx = cls.get_personalization_context(buyer, product_keyword)

        rendered = template_text
        for key, val in ctx.items():
            pattern = re.compile(rf"\{{\{{\s*{key}\s*\}}\}}", re.IGNORECASE)
            rendered = pattern.sub(val, rendered)

        # Catch-all: remove any remaining unresolved {{...}} tags with safe fallback
        rendered = re.sub(r"\{\{\s*\w+\s*\}\}", "", rendered)

        # Final safety check against accidental "None" / "null" insertions
        rendered = re.sub(r"\bNone\b", cls.FALLBACK_COMPANY_NAME, rendered)
        rendered = re.sub(r"\bnull\b", cls.FALLBACK_COMPANY_NAME, rendered)

        return rendered

    @classmethod
    def load_template_file(cls, template_path: Optional[Path] = None) -> str:
        """
        Load outreach template text from disk, or fallback to default template.
        """
        target = template_path or Config.DEFAULT_TEMPLATE_PATH
        if target.exists():
            try:
                with open(target, mode="r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Could not read template file '{target}': {e}. Using built-in fallback.")

        # Built-in fallback template if file missing
        return (
            "Subject: Wholesale Export Catalog: Premium {{product}} for {{company_name}}\n\n"
            "Dear {{buyer_name}},\n\n"
            "We are a direct manufacturer and artisan exporter of authentic {{product}}.\n"
            "Please find attached our latest wholesale presentation and catalog for {{company_name}}.\n\n"
            "Best regards,\nExport Operations Team"
        )

    @classmethod
    def render_email(
        cls,
        buyer: Dict[str, Any],
        template_text: Optional[str] = None,
        template_path: Optional[Path] = None,
        product_keyword: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Render subject and body for a buyer contact.
        If template starts with 'Subject: ...', parses subject line automatically.
        Returns (subject, body).
        """
        raw_text = template_text or cls.load_template_file(template_path)
        rendered = cls.render_template(raw_text, buyer, product_keyword)

        lines = rendered.strip().splitlines()
        subject = ""
        body_lines = []

        if lines and lines[0].lower().startswith("subject:"):
            subject = lines[0][len("subject:"):].strip()
            body_lines = lines[1:]
        else:
            # Render default subject template
            subject = cls.render_template(cls.DEFAULT_SUBJECT_TEMPLATE, buyer, product_keyword)
            body_lines = lines

        body = "\n".join(body_lines).strip()
        return subject, body
