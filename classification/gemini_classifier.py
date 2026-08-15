"""
Gemini and Local Deterministic Contact Classification Module.
API 3 - EXPORT Automation System (Phase 3: AI Lead Classification).

Classifies discovered buyer email contacts into:
  - 'business' (corporate procurement, distributors, wholesalers, retail chains)
  - 'individual' (freelance practitioners, consumers, single personal inboxes)

Supports:
  - Structured JSON classification via Gemini API (gemini-2.5-flash)
  - Deterministic LOCAL_TEST_CLASSIFICATION for TEST_MODE and offline execution
  - Configurable batch processing (CLASSIFICATION_BATCH_SIZE)
  - Configurable confidence threshold & review flagging (CLASSIFICATION_REVIEW_THRESHOLD)
  - Complete audit logging to data/classification_log.csv
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set

from config import Config
from app_logging.activity_logger import (
    logger,
    load_buyers,
    save_classified_emails,
    save_classification_log,
    DEFAULT_BUYERS_CSV,
    DEFAULT_BIZ_CSV,
    DEFAULT_IND_CSV,
    DEFAULT_CLASSIFICATION_LOG_CSV,
)
from validation.email_validator import validate_buyer_records, validate_email_address

# Free/personal email provider domains
FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "ymail.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "protonmail.com",
    "proton.me",
    "zoho.com",
    "mail.com",
    "gmx.com",
    "yandex.com",
}

# Role / Corporate email prefixes
BUSINESS_PREFIXES = {
    "info",
    "contact",
    "sales",
    "import",
    "imports",
    "procurement",
    "buyer",
    "buying",
    "wholesale",
    "purchasing",
    "order",
    "orders",
    "trade",
    "export",
    "admin",
    "corporate",
    "office",
    "inquiries",
    "enquiry",
    "support",
    "team",
    "hello",
    "compras",
    "vertrieb",
}

# Corporate legal and organizational indicators in company names
CORPORATE_SUFFIX_TERMS = [
    "ltd", "limited", "inc", "incorporated", "llc", "corp", "corporation",
    "gmbh", "pty", "pty ltd", "sa", "s.a.", "sl", "s.l.", "srl", "bv",
    "co", "company", "group", "holdings", "enterprises", "trading",
    "imports", "distribuciones", "distribution", "wholesale", "supplies",
]


@dataclass
class ClassificationResult:
    """Represents the structured outcome of a contact lead classification."""
    email: str
    category: str  # "business" or "individual"
    confidence: float  # 0.0 to 1.0
    reason: str
    classification_source: str  # "GEMINI", "LOCAL_TEST_CLASSIFICATION", or "ERROR"
    review_required: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "classification_source": self.classification_source,
            "review_required": self.review_required,
            "timestamp": self.timestamp,
        }


class LocalTestClassifier:
    """
    Deterministic local classifier for TEST_MODE and offline development.
    Uses multi-signal heuristics (domain structure, role prefixes, company legal structure)
    to classify contacts cleanly without external network calls.
    """

    SOURCE_NAME = "LOCAL_TEST_CLASSIFICATION"

    @classmethod
    def classify(
        cls,
        buyer: Dict[str, Any],
        review_threshold: Optional[float] = None,
    ) -> ClassificationResult:
        threshold = Config.CLASSIFICATION_REVIEW_THRESHOLD if review_threshold is None else review_threshold
        email = str(buyer.get("email", "")).strip().lower()
        company = str(buyer.get("company_name", "")).strip()
        website = str(buyer.get("website", "")).strip()

        if not email or "@" not in email:
            return ClassificationResult(
                email=email,
                category="individual",
                confidence=0.0,
                reason="Invalid or missing email address",
                classification_source=cls.SOURCE_NAME,
                review_required=True,
            )

        local_part, domain_part = email.split("@", 1)
        company_lower = company.lower()

        # Check for corporate suffix in company name
        has_corp_suffix = any(
            re.search(r"\b" + re.escape(term) + r"\b", company_lower)
            for term in CORPORATE_SUFFIX_TERMS
        )

        is_corporate_domain = domain_part not in FREE_EMAIL_DOMAINS and "." in domain_part
        has_biz_prefix = local_part in BUSINESS_PREFIXES or any(
            p in local_part for p in ["procure", "buyer", "import", "whole", "purchas"]
        )

        # 1. Strong Business Indicators:
        if is_corporate_domain:
            reason = f"Corporate domain '@{domain_part}'"
            if has_biz_prefix:
                reason += f" with commercial prefix '{local_part}'"
            if company:
                reason += f" ({company})"
            confidence = 0.95 if (has_corp_suffix or has_biz_prefix) else 0.88
            return ClassificationResult(
                email=email,
                category="business",
                confidence=confidence,
                reason=reason,
                classification_source=cls.SOURCE_NAME,
                review_required=confidence < threshold,
            )

        # Freemail domain but established enterprise entity
        if domain_part in FREE_EMAIL_DOMAINS and has_corp_suffix:
            confidence = 0.82
            reason = f"Enterprise entity '{company}' utilizing commercial freemail '@{domain_part}'"
            return ClassificationResult(
                email=email,
                category="business",
                confidence=confidence,
                reason=reason,
                classification_source=cls.SOURCE_NAME,
                review_required=confidence < threshold,
            )

        # Freemail domain with informal or ambiguous business name
        if domain_part in FREE_EMAIL_DOMAINS and company and not has_corp_suffix:
            confidence = 0.65  # Below default 0.70 threshold -> triggers REVIEW_REQUIRED
            reason = f"Public freemail '@{domain_part}' with unverified business name '{company}'; review suggested"
            return ClassificationResult(
                email=email,
                category="business",
                confidence=confidence,
                reason=reason,
                classification_source=cls.SOURCE_NAME,
                review_required=True,
            )

        # 2. Strong Individual Indicators:
        if domain_part in FREE_EMAIL_DOMAINS and not company:
            confidence = 0.85
            reason = f"Personal freemail address on '@{domain_part}' with no associated corporate entity"
            return ClassificationResult(
                email=email,
                category="individual",
                confidence=confidence,
                reason=reason,
                classification_source=cls.SOURCE_NAME,
                review_required=confidence < threshold,
            )

        # Fallback for ambiguous cases
        confidence = 0.50
        reason = "Indeterminate commercial context; classified as individual pending review"
        return ClassificationResult(
            email=email,
            category="individual",
            confidence=confidence,
            reason=reason,
            classification_source=cls.SOURCE_NAME,
            review_required=True,
        )


class HeuristicClassifier:
    """Backwards-compatible alias for local heuristic classification."""

    @staticmethod
    def classify(buyer: Dict[str, Any]) -> str:
        res = LocalTestClassifier.classify(buyer)
        return res.category


class GeminiClassifier:
    """Handles LLM-powered contact classification via Google Gemini API."""

    SOURCE_NAME = "GEMINI"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else Config.GEMINI_API_KEY

    def classify_batch(
        self,
        buyers: List[Dict[str, Any]],
        review_threshold: Optional[float] = None,
    ) -> List[ClassificationResult]:
        """
        Send a batch of buyers to Gemini for structured JSON classification.
        Falls back safely to LocalTestClassifier if API call fails or key is missing.
        """
        threshold = Config.CLASSIFICATION_REVIEW_THRESHOLD if review_threshold is None else review_threshold

        if not self.api_key:
            logger.warning("Gemini API key is not configured. Falling back to local test classifier.")
            return [
                LocalTestClassifier.classify(b, review_threshold=threshold)
                for b in buyers if b.get("email")
            ]

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            contacts_payload = [
                {
                    "email": b.get("email", "").strip().lower(),
                    "company_name": b.get("company_name", "").strip(),
                    "buyer_name": b.get("buyer_name", "").strip(),
                    "website": b.get("website", "").strip(),
                    "country": b.get("country", "").strip(),
                    "source_platform": b.get("source_platform", "").strip(),
                }
                for b in buyers
            ]

            prompt = (
                "You are an expert international trade analyst. Classify each of the following export buyer contact records "
                "into either 'business' (commercial importer, wholesale distributor, retail buyer, corporate procurement) "
                "or 'individual' (retail consumer, freelance practitioner, personal address).\n\n"
                "Instructions:\n"
                "1. Return strictly a JSON object with a single top-level key 'classifications' containing a list of objects.\n"
                "2. Each object must have keys: 'email', 'category', 'confidence', and 'reason'.\n"
                "3. 'category' must be either 'business' or 'individual'.\n"
                "4. 'confidence' must be a float between 0.0 and 1.0.\n"
                "5. 'reason' must be a concise, factual explanation based ONLY on the provided data.\n"
                "6. Do not invent missing details.\n\n"
                f"Contact Records to Classify:\n{json.dumps(contacts_payload, indent=2)}"
            )

            model_name = getattr(Config, "GEMINI_MODEL", "gemini-3.5-flash")
            response = None
            for cand in [model_name, "gemini-3.5-flash", "gemini-3-flash-preview"]:
                try:
                    response = client.models.generate_content(
                        model=cand,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.0,
                        ),
                    )
                    if response and response.text:
                        break
                except Exception as me:
                    if "404" in str(me) or "NOT_FOUND" in str(me):
                        continue
                    raise me

            raw_text = response.text.strip() if (response and response.text) else ""
            return self._parse_gemini_json(raw_text, buyers, threshold)

        except Exception as e:
            logger.error(f"Gemini API batch classification failed: {e}. Falling back to local test classification.")
            return [
                LocalTestClassifier.classify(b, review_threshold=threshold)
                for b in buyers if b.get("email")
            ]

    def _parse_gemini_json(
        self,
        raw_text: str,
        buyers: List[Dict[str, Any]],
        review_threshold: float,
    ) -> List[ClassificationResult]:
        """Parse Gemini JSON response and validate structure."""
        buyer_map = {b["email"].strip().lower(): b for b in buyers if b.get("email")}
        results: Dict[str, ClassificationResult] = {}

        try:
            # Clean markdown codeblocks if present
            cleaned_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
            cleaned_text = re.sub(r"\s*```$", "", cleaned_text, flags=re.MULTILINE).strip()
            data = json.loads(cleaned_text)

            items = []
            if isinstance(data, dict):
                items = data.get("classifications", [])
            elif isinstance(data, list):
                items = data

            for item in items:
                if not isinstance(item, dict):
                    continue
                email = str(item.get("email", "")).strip().lower()
                if not email or email not in buyer_map:
                    continue

                raw_cat = str(item.get("category", item.get("classification", ""))).strip().lower()
                category = "business" if raw_cat == "business" else ("individual" if raw_cat == "individual" else "business")

                try:
                    confidence = float(item.get("confidence", 0.85))
                    confidence = max(0.0, min(1.0, confidence))
                except (ValueError, TypeError):
                    confidence = 0.75

                reason = str(item.get("reason", "Classified via Gemini AI model")).strip()
                review_req = confidence < review_threshold

                results[email] = ClassificationResult(
                    email=email,
                    category=category,
                    confidence=confidence,
                    reason=reason,
                    classification_source=self.SOURCE_NAME,
                    review_required=review_req,
                )

        except Exception as parse_err:
            logger.warning(f"Failed to parse Gemini JSON response: {parse_err}. Recovering with local fallback.")

        # Ensure all input buyers have a result
        final_list = []
        for b in buyers:
            em = b.get("email", "").strip().lower()
            if em:
                if em in results:
                    final_list.append(results[em])
                else:
                    fallback_res = LocalTestClassifier.classify(b, review_threshold=review_threshold)
                    final_list.append(fallback_res)

        return final_list


def classify_contacts(
    buyers: List[Dict[str, Any]],
    force_heuristic: Optional[bool] = None,
    batch_size: Optional[int] = None,
    review_threshold: Optional[float] = None,
) -> Tuple[List[str], List[str]]:
    """
    Classify buyer contacts into business and individual email lists.
    Backwards-compatible interface returning: (business_emails, individual_emails).
    """
    results = classify_contacts_detailed(
        buyers=buyers,
        force_heuristic=force_heuristic,
        batch_size=batch_size,
        review_threshold=review_threshold,
    )

    biz_emails = [r.email for r in results if r.category == "business"]
    ind_emails = [r.email for r in results if r.category == "individual"]
    return biz_emails, ind_emails


def classify_contacts_detailed(
    buyers: List[Dict[str, Any]],
    force_heuristic: Optional[bool] = None,
    batch_size: Optional[int] = None,
    review_threshold: Optional[float] = None,
) -> List[ClassificationResult]:
    """
    Execute batch classification on buyer records, returning structured ClassificationResult list.
    Deduplicates unique contacts by normalized email before classification.
    """
    use_heuristic = Config.TEST_MODE or not Config.GEMINI_API_KEY if force_heuristic is None else force_heuristic
    bsize = Config.CLASSIFICATION_BATCH_SIZE if batch_size is None else batch_size
    threshold = Config.CLASSIFICATION_REVIEW_THRESHOLD if review_threshold is None else review_threshold

    # Filter and deduplicate unique valid email records
    seen_emails: Set[str] = set()
    unique_valid_buyers: List[Dict[str, Any]] = []

    for b in buyers:
        em = str(b.get("email", "")).strip().lower()
        if em and em not in seen_emails:
            seen_emails.add(em)
            unique_valid_buyers.append(b)

    if not unique_valid_buyers:
        return []

    results: List[ClassificationResult] = []

    if use_heuristic:
        logger.info(f"Classifying {len(unique_valid_buyers)} contacts using LocalTestClassifier (TEST_MODE={Config.TEST_MODE}).")
        for b in unique_valid_buyers:
            results.append(LocalTestClassifier.classify(b, review_threshold=threshold))
    else:
        logger.info(f"Classifying {len(unique_valid_buyers)} contacts via Gemini AI (batch size: {bsize}).")
        classifier = GeminiClassifier()
        # Process in batches
        for i in range(0, len(unique_valid_buyers), bsize):
            batch = unique_valid_buyers[i : i + bsize]
            try:
                batch_results = classifier.classify_batch(batch, review_threshold=threshold)
                results.extend(batch_results)
            except Exception as batch_err:
                logger.error(f"Error in classification batch {i // bsize + 1}: {batch_err}. Applying local fallback.")
                for b in batch:
                    results.append(LocalTestClassifier.classify(b, review_threshold=threshold))

    return results


def classify_single_contact(buyer: Dict[str, Any]) -> str:
    """Convenience helper to classify a single buyer."""
    res = LocalTestClassifier.classify(buyer)
    return res.category


def run_classification_pipeline(
    buyers_csv_path: Optional[Path] = None,
    biz_csv_path: Optional[Path] = None,
    ind_csv_path: Optional[Path] = None,
    log_csv_path: Optional[Path] = None,
    batch_size: Optional[int] = None,
    review_threshold: Optional[float] = None,
    force_test_mode: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Execute standalone Phase 3 AI Lead Classification pipeline.
    Loads buyers.csv, validates syntax, deduplicates contacts, classifies via Gemini/Local,
    persists business_emails.csv, individual_emails.csv, classification_log.csv,
    and displays structured audit summary.
    """
    b_path = buyers_csv_path or Config.BUYERS_CSV
    biz_path = biz_csv_path or Config.BUSINESS_EMAILS_CSV
    ind_path = ind_csv_path or Config.INDIVIDUAL_EMAILS_CSV
    log_path = log_csv_path or Config.CLASSIFICATION_LOG_CSV

    bsize = Config.CLASSIFICATION_BATCH_SIZE if batch_size is None else batch_size
    threshold = Config.CLASSIFICATION_REVIEW_THRESHOLD if review_threshold is None else review_threshold
    is_test_mode = Config.TEST_MODE if force_test_mode is None else force_test_mode

    # 1. Load buyers
    all_buyers = load_buyers(b_path)
    total_buyer_records = len(all_buyers)

    # 2. Extract and count unique emails
    all_emails = [b["email"].lower() for b in all_buyers if b.get("email")]
    unique_emails_count = len(set(all_emails))

    # 3. Validate email syntax and exclude invalid emails
    valid_buyers, invalid_records = validate_buyer_records(all_buyers)
    valid_emails_count = len(valid_buyers)
    invalid_emails_count = len(invalid_records)

    # 4. Deduplicate valid buyers by normalized email
    seen_emails: Set[str] = set()
    deduped_valid_buyers: List[Dict[str, Any]] = []
    for b in valid_buyers:
        em = b["email"].lower()
        if em not in seen_emails:
            seen_emails.add(em)
            deduped_valid_buyers.append(b)

    # 5. Classify unique contacts
    classification_source = "LOCAL_TEST_CLASSIFICATION" if (is_test_mode or not Config.GEMINI_API_KEY) else "GEMINI"
    results = classify_contacts_detailed(
        buyers=deduped_valid_buyers,
        force_heuristic=is_test_mode or not Config.GEMINI_API_KEY,
        batch_size=bsize,
        review_threshold=threshold,
    )

    business_emails = [r.email for r in results if r.category == "business"]
    individual_emails = [r.email for r in results if r.category == "individual"]
    review_required_count = len([r for r in results if r.review_required])
    classification_failures = len([r for r in results if r.classification_source == "ERROR"])

    total_batches = (len(deduped_valid_buyers) + bsize - 1) // bsize if deduped_valid_buyers else 0

    # 6. Output persistence
    save_classified_emails(
        business_emails=business_emails,
        individual_emails=individual_emails,
        biz_path=biz_path,
        ind_path=ind_path,
    )

    # Save detailed classification log
    log_records = [r.to_dict() for r in results]
    save_classification_log(
        records=log_records,
        csv_path=log_path,
        append=False,  # Rewrite clean classification snapshot
    )

    # 7. Format summary banner
    banner = "=" * 60
    print(f"\n{banner}")
    print("                 AI CLASSIFICATION SUMMARY")
    print(f"{banner}")
    print(f"Total buyer records    : {total_buyer_records}")
    print(f"Unique emails          : {unique_emails_count}")
    print(f"Valid emails           : {valid_emails_count}")
    print(f"Invalid emails         : {invalid_emails_count}")
    print(f"Business contacts      : {len(business_emails)}")
    print(f"Individual contacts    : {len(individual_emails)}")
    print(f"Review required        : {review_required_count}")
    print(f"Classification failures: {classification_failures}")
    print(f"Classification source  : {classification_source}")
    print(f"Batches processed      : {total_batches}")
    print(f"{banner}\n")

    return {
        "total_buyer_records": total_buyer_records,
        "unique_emails": unique_emails_count,
        "valid_emails": valid_emails_count,
        "invalid_emails": invalid_emails_count,
        "business_contacts": len(business_emails),
        "individual_contacts": len(individual_emails),
        "review_required": review_required_count,
        "classification_failures": classification_failures,
        "classification_source": classification_source,
        "batches_processed": total_batches,
        "results": results,
    }


def classify_live_records(
    buyers: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    review_threshold: Optional[float] = None,
) -> Tuple[List[ClassificationResult], Optional[str]]:
    """
    Classify contacts strictly using the live Gemini API (gemini-2.5-flash).
    Does NOT fall back to local test heuristics if the API call or key is invalid.

    Returns:
      (results, error_code_or_message)
      If failed: ([], "GEMINI_API_KEY_NOT_CONFIGURED" or "GEMINI_API_ERROR: ...")
    """
    key = api_key if api_key is not None else Config.GEMINI_API_KEY
    if not key:
        return [], "GEMINI_API_KEY_NOT_CONFIGURED"

    threshold = Config.CLASSIFICATION_REVIEW_THRESHOLD if review_threshold is None else review_threshold

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)

        contacts_payload = [
            {
                "email": b.get("email", "").strip().lower(),
                "company_name": b.get("company_name", "").strip(),
                "buyer_name": b.get("buyer_name", "").strip(),
                "website": b.get("website", "").strip(),
                "country": b.get("country", "").strip(),
                "source_platform": b.get("source_platform", "").strip(),
            }
            for b in buyers
        ]

        prompt = (
            "You are an expert international trade analyst. Classify each of the following export buyer contact records "
            "into either 'business' (commercial importer, wholesale distributor, retail buyer, corporate procurement) "
            "or 'individual' (retail consumer, freelance practitioner, personal address).\n\n"
            "Instructions:\n"
            "1. Return strictly a JSON object with a single top-level key 'classifications' containing a list of objects.\n"
            "2. Each object must have keys: 'email', 'category', 'confidence', and 'reason'.\n"
            "3. 'category' must be either 'business' or 'individual'.\n"
            "4. 'confidence' must be a float between 0.0 and 1.0.\n"
            "5. 'reason' must be a concise, factual explanation based ONLY on the provided data.\n"
            "6. Do not invent missing details. If country or other information is unknown, do not guess.\n\n"
            f"Contact Records to Classify:\n{json.dumps(contacts_payload, indent=2)}"
        )

        model_name = getattr(Config, "GEMINI_MODEL", "gemini-3.5-flash")
        response = None
        for cand in [model_name, "gemini-3.5-flash", "gemini-3-flash-preview"]:
            try:
                response = client.models.generate_content(
                    model=cand,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                )
                if response and response.text:
                    break
            except Exception as me:
                if "404" in str(me) or "NOT_FOUND" in str(me):
                    continue
                raise me

        raw_text = response.text.strip() if (response and response.text) else ""
        if not raw_text:
            return [], "GEMINI_API_ERROR: Empty response returned by Gemini model"

        # Parse JSON
        cleaned_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
        cleaned_text = re.sub(r"\s*```$", "", cleaned_text, flags=re.MULTILINE).strip()
        data = json.loads(cleaned_text)

        items = data.get("classifications", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        buyer_map = {b["email"].strip().lower(): b for b in buyers if b.get("email")}

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email", "")).strip().lower()
            if not email or email not in buyer_map:
                continue

            raw_cat = str(item.get("category", item.get("classification", ""))).strip().lower()
            category = "business" if raw_cat == "business" else ("individual" if raw_cat == "individual" else "business")

            try:
                confidence = float(item.get("confidence", 0.85))
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.75

            reason = str(item.get("reason", "Classified via Gemini AI model")).strip()
            review_req = confidence < threshold

            results.append(
                ClassificationResult(
                    email=email,
                    category=category,
                    confidence=confidence,
                    reason=reason,
                    classification_source="GEMINI",
                    review_required=review_req,
                )
            )

        if not results:
            return [], "GEMINI_API_ERROR: No valid classifications could be extracted from model JSON"

        return results, None

    except Exception as e:
        return [], f"GEMINI_API_ERROR: {e}"

