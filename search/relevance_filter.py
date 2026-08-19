"""
Relevance Filter and Audit Engine for Export Discovery.

Evaluates discovered search results and websites against:
1. Product Category Relevance (e.g. Pashmina, Cashmere, Shawls vs unrelated products like Singing Bowls)
2. Commercial Buyer / Importer Intent (e.g. Importer, Wholesale, Distributor, Procurement)

Outputs structured audit records with explicit ACCEPT / REJECT decisions and justifications.
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from app_logging.activity_logger import logger

# Product category keyword expansion dictionaries
PRODUCT_SYNONYMS: Dict[str, List[str]] = {
    "pashmina": [
        "pashmina",
        "cashmere",
        "shawl",
        "shawls",
        "scarf",
        "scarves",
        "stole",
        "stoles",
        "wrap",
        "wraps",
        "textile",
        "textiles",
        "wool",
        "woolen",
        "silk",
        "apparel",
        "fashion",
        "garment",
        "garments",
        "handicraft",
        "handicrafts",
        "handmade",
        "handloom",
        "artisan",
        "fabric",
    ],
    "singing bowl": [
        "singing bowl",
        "singing bowls",
        "tibetan singing bowl",
        "tibetan singing bowls",
        "handcrafted singing bowl",
        "handcrafted singing bowls",
        "sound bowl",
        "sound bowls",
        "meditation bowl",
        "meditation bowls",
        "brass bowl",
        "bronze bowl",
        "crystal bowl",
        "chakra bowl",
        "healing bowl",
        "healing bowls",
        "bowl",
        "bowls",
        "tibetan",
        "handcrafted",
        "instrument",
        "sound",
        "meditation",
        "chakra",
        "healing",
        "wellness",
        "yoga",
        "spiritual",
        "sound bath",
        "sound healing",
        "percussion",
        "artisan bowl",
        "handmade bowl",
        "gong",
        "bells",
        "mindfulness",
    ],
    "yoga": [
        "yoga",
        "mat",
        "mats",
        "strap",
        "straps",
        "block",
        "blocks",
        "bolster",
        "bolsters",
        "meditation",
        "cushion",
        "cushions",
        "wellness",
        "fitness",
        "accessories",
        "pilates",
        "activewear",
        "props",
        "equipment",
    ],
}

# Commercial buyer and wholesale intent terms
BUYER_INTENT_TERMS = [
    "importer",
    "imports",
    "importing",
    "import",
    "distributor",
    "distribution",
    "wholesaler",
    "wholesale",
    "retailer",
    "retail",
    "procurement",
    "purchasing",
    "buyer",
    "buying",
    "supplier",
    "store",
    "shop",
    "b2b",
    "catalog",
    "inquiry",
    "trade",
    "commercial",
    # Additional retail and business intent terms
    "seller",
    "vendor",
    "business",
    "company",
    "boutique",
    "marketplace",
    "ecommerce",
    "e-commerce",
    "online shop",
    "contact",
    "email",
    "phone",
    "website",
    "order",
    "purchase",
    "buy",
    "price",
    "shipping",
    "delivery",
    "payment",
    "inventory",
]

UNRELATED_NEGATIVE_TERMS: Dict[str, List[str]] = {
    "pashmina": [
        "singing bowl",
        "singing bowls",
        "sound healing",
        "sound therapy",
        "gong meditation",
        "tingsha bells",
    ],
    "singing bowl": [
        # Singing bowls rarely conflict with other products
        # Removed overly strict filtering to improve discovery
    ],
}

# Domains that are always irrelevant for B2B export discovery
BLOCKED_DOMAINS = [
    "whatsapp.com",
    "web.whatsapp.com",
    "zhihu.com",
    "baidu.com",
    "zhidao.baidu.com",
    "jingyan.baidu.com",
    "mail.qq.com",
    "service.mail.qq.com",
    "qq.com",
    "sciencedirect.com",
    "researchgate.net",
    "semanticscholar.org",
    "structurae.net",
    "scispace.com",
    "scite.ai",
    "upcommons.upc.edu",
    "jglobal.jst.go.jp",
    "doc88.com",
    "jobsnet.in",
    "sfit.ac.in",
    "juit.ac.in",
    "offcampusjobs4u.com",
    "freshershunt.in",
    "scribd.com",
    "uptti.ac.in",
    "tsec.edu",
    "care.ac.in",
    "punchng.com",
    "berliner-zeitung.de",
    "facebook.com",
    "linkedin.com",
    "twitter.com",
    "youtube.com",
    "instagram.com",
    "reddit.com",
    "wikipedia.org",
    "stackoverflow.com",
    "github.com",
    # Grammar / Dictionary / Unrelated domains
    "merriam-webster.com",
    "grammarly.com",
    "dictionary.com",
    "cambridge.org",
    "collinsdictionary.com",
    "grammarwaves.com",
    "amerilingua.com",
    "ingles.com",
    "englishcurrent.com",
    "vocaberry.com",
    "speedtest.net",
    "ookla.com",
    "commercialguru.com.sg",
]


class RelevanceAudit:
    """Structure storing evaluation decision and diagnostic metadata."""
    def __init__(
        self,
        query: str,
        title: str,
        url: str,
        product_relevance: str,
        buyer_relevance: str,
        decision: str,
        reason: str,
        company: str = "",
        country: str = "",
        extracted_email: str = "",
    ):
        self.query = query
        self.title = title
        self.url = url
        self.product_relevance = product_relevance
        self.buyer_relevance = buyer_relevance
        self.decision = decision
        self.reason = reason
        self.company = company
        self.country = country
        self.extracted_email = extracted_email

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "title": self.title,
            "url": self.url,
            "product_relevance": self.product_relevance,
            "buyer_relevance": self.buyer_relevance,
            "decision": self.decision,
            "reason": self.reason,
            "company": self.company,
            "country": self.country,
            "extracted_email": self.extracted_email,
        }

    def format_log_entry(self) -> str:
        lines = [
            f"Query: {self.query or 'N/A'}",
            f"Title: {self.title or 'N/A'}",
            f"URL: {self.url or 'N/A'}",
            f"Product relevance: {self.product_relevance}",
            f"Buyer relevance: {self.buyer_relevance}",
        ]
        if self.extracted_email:
            lines.append(f"Extracted email: {self.extracted_email}")
        if self.company:
            lines.append(f"Company: {self.company}")
        if self.country:
            lines.append(f"Country: {self.country}")
        lines.append(f"Decision: {self.decision}")
        lines.append(f"Reason: {self.reason}")
        return "\n".join(lines)


def get_product_terms_for_keyword(keyword: str) -> List[str]:
    """Retrieve product terms for relevance matching.
    
    IMPORTANT: For multi-word keywords like 'Singing Bowls', we do NOT add individual
    word tokens (e.g. 'singing', 'bowls') to avoid false-positive matches on completely
    unrelated pages that happen to contain common words like 'bowl' or 'singing'.
    Only multi-word phrases and product-specific synonyms are used.
    """
    kw_clean = keyword.lower().strip()
    terms = set()

    # Always include exact full phrase
    terms.add(kw_clean)

    # For exact Singing Bowls searches, use ONLY multi-word phrases — never single words
    if "singing bowls" in kw_clean or "singing bowl" in kw_clean:
        exact_terms = [
            "singing bowl",
            "singing bowls",
            "tibetan singing bowl",
            "tibetan singing bowls",
            "handcrafted singing bowl",
            "handcrafted singing bowls",
            "sound bowl",
            "sound bowls",
            "meditation bowl",
            "meditation bowls",
            "brass bowl",
            "bronze bowl",
            "crystal bowl",
            "healing bowl",
            "healing bowls",
            "tibetan bowl",
            "sound healing",
            "sound bath",
        ]
        terms.update(exact_terms)
        return sorted(terms)

    # For single-word keywords, add individual tokens
    words = re.findall(r"[a-z0-9]+", kw_clean)
    terms.update(words)

    # Normal synonym expansion for other categories
    for cat_key, synonym_list in PRODUCT_SYNONYMS.items():
        if cat_key in kw_clean or any(w in cat_key for w in words):
            terms.update(synonym_list)

    return sorted(terms)


def evaluate_result_relevance(
    item: Dict[str, Any],
    keyword: str,
    query: str = "",
) -> RelevanceAudit:
    """
    Evaluate search result or extracted buyer for product relevance and commercial buyer intent.
    Returns a RelevanceAudit object with ACCEPT or REJECT decision.
    """
    title = str(item.get("title", "")).strip()
    url = str(item.get("url", item.get("website", ""))).strip()
    snippet = str(item.get("snippet", "")).strip()
    content = str(item.get("content", item.get("raw_text", ""))).strip()
    company = str(item.get("company_name", "")).strip()
    country = str(item.get("country", "")).strip()
    email = str(item.get("email", "")).strip()
    item_kw = str(item.get("keyword", "")).strip()

    # NOTE: Do NOT include {query} in text_corpus — it causes false positives
    # where every result matches product terms because the query itself contains the keyword.
    text_corpus = f"{title} {url} {snippet} {content} {company} {item_kw}".lower()

    # Check if the URL belongs to a known irrelevant domain and reject immediately
    url_lower = url.lower()
    for blocked in BLOCKED_DOMAINS:
        if blocked in url_lower:
            return RelevanceAudit(
                query=query,
                title=title,
                url=url,
                product_relevance="NONE",
                buyer_relevance="LOW",
                decision="REJECT",
                reason=f"blocked domain: {blocked} (irrelevant for B2B export discovery)",
                company=company,
                country=country,
                extracted_email=email,
            )

    # 1. Product Relevance Analysis
    target_terms = get_product_terms_for_keyword(keyword)
    matched_product_terms = [t for t in target_terms if t in text_corpus]

    # For Singing Bowls specifically, require exact product phrase match rather than generic singing/wellness words
    kw_lower = keyword.lower().strip()
    exact_phrase_present = "singing bowls" in text_corpus or "singing bowl" in text_corpus
    generic_singing_overlap = any(term in text_corpus for term in ["singing", "karaoke", "song", "vocal", "sing lesson", "learn to sing"])

    negative_hits = []
    for cat_key, neg_list in UNRELATED_NEGATIVE_TERMS.items():
        if cat_key in kw_lower:
            for neg in neg_list:
                if neg in text_corpus:
                    negative_hits.append(neg)

    if "singing bowl" in kw_lower or "singing bowls" in kw_lower:
        # For singing bowls, allow results with related wellness terms alongside exact phrase
        # or results with high relevance even if generic overlap exists
        wellness_terms = ["meditation", "yoga", "healing", "wellness", "spiritual", "chakra", "sound bath", "mindfulness"]
        has_wellness_context = any(term in text_corpus for term in wellness_terms)
        
        if exact_phrase_present:
            # Exact phrase present - ACCEPT even with generic singing terms if wellness context exists
            if has_wellness_context or len(matched_product_terms) >= 2:
                product_rel = "HIGH"
            elif not generic_singing_overlap:
                product_rel = "MEDIUM"
            else:
                product_rel = "MEDIUM" if has_wellness_context else "LOW"
        elif has_wellness_context and len(matched_product_terms) >= 1:
            # Wellness context + product terms (even without exact phrase)
            product_rel = "MEDIUM"
        else:
            product_rel = "NONE"
    else:
        if any(keyword.lower() in text_corpus for _ in [1]) or len(matched_product_terms) >= 2:
            product_rel = "HIGH"
        elif len(matched_product_terms) >= 1:
            product_rel = "MEDIUM"
        else:
            product_rel = "NONE"

    # If domain contains negative terms and 0 strong product matches, downgrade to NONE
    if negative_hits and len(matched_product_terms) == 0:
        product_rel = "NONE"

    # 2. Buyer Intent Analysis
    matched_buyer_terms = [b for b in BUYER_INTENT_TERMS if b in text_corpus]
    if len(matched_buyer_terms) >= 2:
        buyer_rel = "HIGH"
    elif len(matched_buyer_terms) >= 1:
        buyer_rel = "MEDIUM"
    else:
        buyer_rel = "LOW"

    # 3. Decision Formulation
    if product_rel == "NONE":
        decision = "REJECT"
        if negative_hits:
            reason = f"unrelated legacy domain / category ({', '.join(negative_hits[:2])})"
        else:
            reason = f"no product keywords matching '{keyword}'"
    elif buyer_rel == "LOW" and not email:
        decision = "REJECT"
        reason = "insufficient commercial wholesale / importer intent"
    else:
        decision = "ACCEPT"
        reason = f"relevant product ({', '.join(matched_product_terms[:2])}) and commercial buyer criteria"

    audit = RelevanceAudit(
        query=query,
        title=title,
        url=url,
        product_relevance=product_rel,
        buyer_relevance=buyer_rel,
        decision=decision,
        reason=reason,
        company=company,
        country=country,
        extracted_email=email,
    )
    return audit
