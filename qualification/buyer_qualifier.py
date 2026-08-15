"""
Buyer Qualification and Lead Scoring Module.
API 3 - EXPORT Automation System (Phase 6E: AI Buyer Qualification).

Evaluates discovered business contacts to determine whether they are genuine
export buyers, importers, wholesalers, or retailers (as opposed to competitors,
direct manufacturers, or unrelated retail stores).

Scoring Framework (0-100):
- Business Legitimacy: 20 pts max
- Product Relevance: 20 pts max
- Buyer / Commercial Intent: 25 pts max
- Contact Quality: 15 pts max
- Website Evidence: 10 pts max
- Country / Evidence Completeness: 10 pts max

Qualification Levels:
- HIGH (>= 75)
- MEDIUM (50 - 74)
- LOW (< 50)
- REVIEW_REQUIRED

Recommendations:
- REVIEW_FOR_OUTREACH
- MANUAL_REVIEW
- DO_NOT_CONTACT
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
    save_qualification_log,
    DEFAULT_QUALIFICATION_LOG_CSV,
)
from classification.gemini_classifier import FREE_EMAIL_DOMAINS, BUSINESS_PREFIXES, CORPORATE_SUFFIX_TERMS


# Commercial intent signal definitions
BUYER_INTENT_SIGNALS = {
    "importer": ("importer", "importing", "imports", "import", "importation"),
    "distributor": ("distributor", "distribution", "distribute", "distributes", "distribuciones"),
    "wholesaler": ("wholesaler", "wholesale", "wholesalers", "b2b", "bulk order", "bulk orders", "grossiste", "vertrieb"),
    "retailer": ("retailer", "retail", "retailers", "boutique", "stockists", "stockist"),
    "procurement": ("procurement", "purchasing", "sourcing", "buyer", "buying", "acquisition", "compras"),
    "reseller": ("reseller", "resellers", "trade", "commercial trade", "merchant", "trading"),
    "international_sourcing": ("international sourcing", "global trade", "import partner", "overseas sourcing"),
}

SUPPLIER_SIGNALS = {
    "manufacturer": ("manufacturer", "factory", "producer", "production", "crafting", "maker", "artisan"),
    "exporter": ("exporter", "exports", "exporting", "export"),
}

# Domain keyword expansion dictionaries for generalized relevance evaluation
PRODUCT_SYNONYMS = {
    "pashmina": ["pashmina", "cashmere", "shawl", "shawls", "scarf", "scarves", "textile", "textiles", "wool", "wrap", "stole", "handmade", "fashion", "accessories", "apparel"],
    "cashmere": ["cashmere", "pashmina", "wool", "shawls", "scarves", "knitwear", "apparel", "accessories"],
    "singing bowl": ["singing bowl", "singing bowls", "sound healing", "tibetan bowl", "tibetan bowls", "meditation", "wellness", "holistic", "bell", "gong"],
    "tea": ["tea", "organic tea", "herbal tea", "loose leaf", "tea importer", "beverages"],
    "coffee": ["coffee", "arabica", "specialty coffee", "coffee beans", "roastery", "importer"],
    "spices": ["spices", "organic spices", "culinary herbs", "seasonings", "bulk spices"],
    "handicrafts": ["handicrafts", "artisan crafts", "handmade", "decor", "home goods", "fair trade"],
}


def expand_product_keywords(keyword: Optional[str]) -> List[str]:
    """
    Expand a search keyword into a generalized list of relevant domain tokens and synonyms.
    Ensures qualification logic is dynamic and configurable rather than hardcoded to a single niche.
    """
    if not keyword:
        return ["export", "wholesale", "trade", "products"]

    raw = keyword.lower().strip()
    tokens = set(re.findall(r"\b[a-z]{3,}\b", raw))

    # Match predefined synonym clusters if applicable
    for syn_key, syn_list in PRODUCT_SYNONYMS.items():
        if syn_key in raw or any(t in syn_key for t in tokens):
            tokens.update(syn_list)

    return sorted(list(tokens))


@dataclass
class QualificationResult:
    """Represents the structured evaluation of a buyer's commercial qualification."""
    email: str
    company_name: str
    product: str
    business_status: str  # "business", "individual", "unknown"
    product_relevance: float  # 0.0 to 1.0
    buyer_intent: float  # 0.0 to 1.0
    commercial_signals: List[str]
    evidence: List[str]
    qualification_score: int  # 0 to 100
    qualification_level: str  # "HIGH", "MEDIUM", "LOW", "REVIEW_REQUIRED"
    recommendation: str  # "REVIEW_FOR_OUTREACH", "MANUAL_REVIEW", "DO_NOT_CONTACT"
    classification_source: str  # "GEMINI", "LOCAL_TEST_CLASSIFICATION", etc.
    qualification_source: str  # "GEMINI", "LOCAL_TEST_QUALIFIER", "ERROR"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "company_name": self.company_name,
            "product": self.product,
            "business_status": self.business_status,
            "product_relevance": round(self.product_relevance, 2),
            "buyer_intent": round(self.buyer_intent, 2),
            "commercial_signals": self.commercial_signals,
            "evidence": self.evidence,
            "qualification_score": self.qualification_score,
            "qualification_level": self.qualification_level,
            "recommendation": self.recommendation,
            "classification_source": self.classification_source,
            "qualification_source": self.qualification_source,
            "timestamp": self.timestamp,
        }


class LocalTestQualifier:
    """
    Deterministic rule-based qualification engine for TEST_MODE and offline validation.
    Calculates multi-dimensional scoring strictly without external network calls.
    """

    SOURCE_NAME = "LOCAL_TEST_QUALIFIER"

    @classmethod
    def qualify(
        cls,
        buyer: Dict[str, Any],
        product_keyword: Optional[str] = None,
        classification_source: str = "LOCAL_TEST_CLASSIFICATION",
    ) -> QualificationResult:
        email = str(buyer.get("email", "")).strip().lower()
        company = str(buyer.get("company_name", "")).strip()
        website = str(buyer.get("website", "")).strip()
        country = str(buyer.get("country", "")).strip()
        platform = str(buyer.get("source_platform", "")).strip()
        product = product_keyword or Config.SEARCH_KEYWORD or "Export Goods"

        evidence: List[str] = []
        commercial_signals: List[str] = []

        domain_part = email.split("@")[-1] if "@" in email else ""
        user_part = email.split("@")[0] if "@" in email else ""

        # 1. Business Legitimacy (Max 20 pts)
        is_freemail = domain_part in FREE_EMAIL_DOMAINS
        has_corp_suffix = any(term in company.lower() for term in CORPORATE_SUFFIX_TERMS)
        has_business_prefix = any(pref in user_part for pref in BUSINESS_PREFIXES)

        business_status = "business" if (not is_freemail or has_corp_suffix or has_business_prefix) else ("individual" if not company else "unknown")

        biz_score = 0
        if not is_freemail and domain_part:
            biz_score += 15
            evidence.append(f"Dedicated domain '{domain_part}'")
        if has_corp_suffix:
            biz_score += 5
            evidence.append(f"Corporate entity indicator in company name '{company}'")
        elif not is_freemail and company:
            biz_score += 5
        biz_score = min(20, biz_score)

        # 2. Product Relevance (Max 20 pts)
        relevant_tokens = expand_product_keywords(product)
        search_blob = f"{company} {website} {domain_part} {platform}".lower()

        matched_tokens = [t for t in relevant_tokens if t in search_blob]
        if matched_tokens:
            product_relevance = min(1.0, 0.4 + (len(matched_tokens) * 0.2))
            product_score = int(product_relevance * 20)
            evidence.append(f"Product relevance matches: {', '.join(matched_tokens[:4])}")
        else:
            product_relevance = 0.2
            product_score = 4
            evidence.append("Limited explicit product tokens in domain/metadata")

        # 3. Buyer Intent & Commercial Signals (Max 25 pts)
        intent_score = 0
        # Check buyer intent signals
        for sig_name, sig_words in BUYER_INTENT_SIGNALS.items():
            if any(w in search_blob or w in user_part for w in sig_words):
                commercial_signals.append(sig_name)

        # Check supplier signals (distinguish buyer vs pure manufacturer)
        is_pure_supplier = False
        supplier_matches = [s_name for s_name, s_words in SUPPLIER_SIGNALS.items() if any(w in search_blob for w in s_words)]
        if supplier_matches and not commercial_signals:
            commercial_signals.extend(supplier_matches)
            is_pure_supplier = True

        if "importer" in commercial_signals or "procurement" in commercial_signals:
            intent_score = 25
            evidence.append("Direct import/procurement commercial intent detected")
        elif "wholesaler" in commercial_signals or "distributor" in commercial_signals:
            intent_score = 20
            evidence.append("Wholesale/distribution commercial channel detected")
        elif "retailer" in commercial_signals or "reseller" in commercial_signals:
            intent_score = 15
            evidence.append("Commercial retail/stockist entity detected")
        elif is_pure_supplier:
            intent_score = 8
            evidence.append("Supplier/artisan entity; evaluated as potential trade partner or manufacturer")
        elif business_status == "business":
            intent_score = 12
            evidence.append("Commercial entity with standard B2B inquiry channel")
        else:
            intent_score = 0
            evidence.append("No explicit buyer/commercial intent detected")

        buyer_intent = round(min(1.0, intent_score / 25.0), 2)

        # 4. Contact Quality (Max 15 pts)
        contact_score = 0
        if has_business_prefix and not is_freemail:
            contact_score = 15
            evidence.append(f"High-quality corporate mailbox prefix '{user_part}'")
        elif not is_freemail:
            contact_score = 12
            evidence.append("Direct corporate domain mailbox")
        elif has_business_prefix:
            contact_score = 8
            evidence.append("Commercial mailbox on public email service")
        else:
            contact_score = 3
            evidence.append("Personal or freemail contact address")

        # 5. Website Evidence (Max 10 pts)
        web_score = 0
        if website and website.startswith("http") and not any(host in website for host in ["facebook.com", "linkedin.com", "instagram.com"]):
            web_score = 10
            evidence.append("Active custom commercial website")
        elif website:
            web_score = 4
            evidence.append("Social platform or third-party presence")
        else:
            web_score = 0
            evidence.append("No website URL provided")

        # 6. Country & Evidence Completeness (Max 10 pts)
        completeness_score = 0
        if country and country.upper() not in ("UNKNOWN", ""):
            completeness_score += 5
            evidence.append(f"Verified country location: {country}")
        else:
            evidence.append("Country origin: UNKNOWN")

        if company and email and website:
            completeness_score += 5

        # Compute Total Score (0-100)
        total_score = biz_score + product_score + intent_score + contact_score + web_score + completeness_score
        total_score = max(0, min(100, total_score))

        # Qualification Level & Recommendation
        if total_score >= 75:
            qual_level = "HIGH"
            recommendation = "REVIEW_FOR_OUTREACH"
        elif total_score >= 50:
            qual_level = "MEDIUM"
            recommendation = "MANUAL_REVIEW"
        else:
            qual_level = "LOW"
            recommendation = "DO_NOT_CONTACT"

        # Refine recommendation if product relevance or buyer intent is too low
        if product_relevance < 0.3:
            recommendation = "DO_NOT_CONTACT"
        elif qual_level == "HIGH" and buyer_intent < 0.4:
            recommendation = "MANUAL_REVIEW"
            qual_level = "REVIEW_REQUIRED"

        return QualificationResult(
            email=email,
            company_name=company,
            product=product,
            business_status=business_status,
            product_relevance=product_relevance,
            buyer_intent=buyer_intent,
            commercial_signals=commercial_signals if commercial_signals else ["UNKNOWN"],
            evidence=evidence,
            qualification_score=total_score,
            qualification_level=qual_level,
            recommendation=recommendation,
            classification_source=classification_source,
            qualification_source=cls.SOURCE_NAME,
        )


def qualify_live_buyers(
    buyers: List[Dict[str, Any]],
    product_keyword: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Tuple[List[QualificationResult], Optional[str]]:
    """
    Qualify discovered buyer contacts strictly using Google Gemini API (gemini-3.5-flash).
    Does NOT fall back to local test heuristics if the API call fails or key is missing.

    Returns:
      (results, error_message_or_none)
    """
    key = api_key if api_key is not None else Config.GEMINI_API_KEY
    if not key:
        return [], "GEMINI_API_KEY_NOT_CONFIGURED"

    product = product_keyword or Config.SEARCH_KEYWORD or "Export Products"

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)

        contacts_payload = [
            {
                "email": b.get("email", "").strip().lower(),
                "company_name": b.get("company_name", "").strip(),
                "website": b.get("website", "").strip(),
                "country": b.get("country", "").strip() or "UNKNOWN",
                "source_platform": b.get("source_platform", "").strip(),
                "target_product": product,
            }
            for b in buyers if b.get("email")
        ]

        prompt = (
            "You are an expert international trade qualification analyst. Qualify each of the following candidate "
            "buyer records to evaluate if they represent viable commercial export buyers, wholesale importers, "
            "or retail stockists for the specified target product category.\n\n"
            "Evaluation Rules:\n"
            "1. 'business_status': 'business', 'individual', or 'unknown'.\n"
            "2. 'product_relevance': float between 0.0 and 1.0 evaluating relevance to the target product.\n"
            "3. 'buyer_intent': float between 0.0 and 1.0 evaluating whether the entity acts as a buyer/importer/distributor/retailer vs competitor/supplier.\n"
            "4. 'commercial_signals': list of detected commercial roles (e.g., ['importer', 'wholesaler', 'retailer', 'distributor', 'manufacturer', 'artisan']).\n"
            "5. 'evidence': list of factual, concise observations based strictly on the provided data. Do NOT use unescaped double quotes inside strings; use single quotes.\n"
            "6. 'qualification_score': integer from 0 to 100 calculated from: Business Legitimacy (20), Product Relevance (20), Buyer Intent (25), Contact Quality (15), Website (10), Completeness (10).\n"
            "7. 'qualification_level': 'HIGH' (>= 75), 'MEDIUM' (50-74), 'LOW' (< 50), or 'REVIEW_REQUIRED'.\n"
            "8. 'recommendation': 'REVIEW_FOR_OUTREACH', 'MANUAL_REVIEW', or 'DO_NOT_CONTACT'.\n"
            "9. DO NOT invent missing details. If evidence or country is missing, return 'UNKNOWN'.\n"
            "10. Each item in 'qualifications' MUST include the 'email' and 'company_name' matching the input record.\n\n"
            "Return STRICTLY a JSON object with top-level key 'qualifications' containing a list of objects matching the above schema.\n\n"
            f"Contacts to Qualify:\n{json.dumps(contacts_payload, indent=2)}"
        )

        model_name = getattr(Config, "GEMINI_MODEL", "gemini-3-flash-preview")
        response = None
        for cand in [model_name, "gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview"]:
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
                if "404" in str(me) or "NOT_FOUND" in str(me) or "503" in str(me) or "UNAVAILABLE" in str(me):
                    continue
                raise me

        raw_text = response.text.strip() if (response and response.text) else ""
        if not raw_text:
            return [], "GEMINI_API_ERROR: Empty response returned by Gemini model"

        # Parse JSON response with robust cleanup
        cleaned_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
        cleaned_text = re.sub(r"\s*```$", "", cleaned_text, flags=re.MULTILINE).strip()
        cleaned_text = re.sub(r",\s*([\]}])", r"\1", cleaned_text)
        data = json.loads(cleaned_text)

        items = data.get("qualifications", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        buyer_map = {b["email"].strip().lower(): b for b in buyers if b.get("email")}
        valid_buyers = [b for b in buyers if b.get("email")]

        results: List[QualificationResult] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            email = str(item.get("email", "")).strip().lower()
            if not email or email not in buyer_map:
                if idx < len(valid_buyers):
                    email = valid_buyers[idx]["email"].strip().lower()
                else:
                    continue

            orig_b = buyer_map.get(email, {})
            comp = orig_b.get("company_name") or item.get("company_name", "")
            b_status = str(item.get("business_status", "business")).strip().lower()

            try:
                prod_rel = max(0.0, min(1.0, float(item.get("product_relevance", 0.8))))
            except (ValueError, TypeError):
                prod_rel = 0.5

            try:
                b_intent = max(0.0, min(1.0, float(item.get("buyer_intent", 0.7))))
            except (ValueError, TypeError):
                b_intent = 0.5

            signals = item.get("commercial_signals", [])
            if not isinstance(signals, list):
                signals = [str(signals)]

            evidence_items = item.get("evidence", [])
            if not isinstance(evidence_items, list):
                evidence_items = [str(evidence_items)]

            try:
                score = int(item.get("qualification_score", 75))
                score = max(0, min(100, score))
            except (ValueError, TypeError):
                score = 70

            q_level = str(item.get("qualification_level", "MEDIUM")).upper()
            if q_level not in ("HIGH", "MEDIUM", "LOW", "REVIEW_REQUIRED"):
                q_level = "HIGH" if score >= 75 else ("MEDIUM" if score >= 50 else "LOW")

            rec = str(item.get("recommendation", "MANUAL_REVIEW")).upper()
            if rec not in ("REVIEW_FOR_OUTREACH", "MANUAL_REVIEW", "DO_NOT_CONTACT"):
                rec = "REVIEW_FOR_OUTREACH" if q_level == "HIGH" else ("MANUAL_REVIEW" if q_level == "MEDIUM" else "DO_NOT_CONTACT")

            results.append(
                QualificationResult(
                    email=email,
                    company_name=comp,
                    product=product,
                    business_status=b_status,
                    product_relevance=prod_rel,
                    buyer_intent=b_intent,
                    commercial_signals=signals,
                    evidence=evidence_items,
                    qualification_score=score,
                    qualification_level=q_level,
                    recommendation=rec,
                    classification_source="GEMINI",
                    qualification_source="GEMINI",
                )
            )

        if not results:
            return [], "GEMINI_API_ERROR: No valid qualification records extracted from Gemini response"

        return results, None

    except Exception as e:
        return [], f"GEMINI_API_ERROR: {e}"
