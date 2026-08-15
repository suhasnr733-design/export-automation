"""
Data Extraction Module for API 3 - EXPORT Automation System.

Extracts contact emails, company names, country locations, and buyer names
from raw text, HTML documents, and search results, mapping them to the normalized buyer schema.
"""

import re
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup

# Regex to find candidate email addresses in free text / HTML
EMAIL_SEARCH_REGEX = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    re.IGNORECASE
)

# Common Country Code Top-Level Domains (ccTLDs)
CCTLD_COUNTRY_MAP = {
    ".de": "Germany",
    ".uk": "United Kingdom",
    ".co.uk": "United Kingdom",
    ".org.uk": "United Kingdom",
    ".au": "Australia",
    ".com.au": "Australia",
    ".net.au": "Australia",
    ".ca": "Canada",
    ".es": "Spain",
    ".fr": "France",
    ".it": "Italy",
    ".nl": "Netherlands",
    ".jp": "Japan",
    ".co.jp": "Japan",
    ".ie": "Ireland",
    ".at": "Austria",
    ".ch": "Switzerland",
    ".se": "Sweden",
    ".no": "Norway",
    ".dk": "Denmark",
    ".nz": "New Zealand",
    ".co.nz": "New Zealand",
    ".in": "India",
    ".co.in": "India",
    ".be": "Belgium",
    ".sg": "Singapore",
    ".us": "United States",
}

# Major country name search patterns in textual address blocks
KNOWN_COUNTRIES = [
    "United States",
    "USA",
    "United Kingdom",
    "UK",
    "Germany",
    "Deutschland",
    "Australia",
    "Canada",
    "Spain",
    "España",
    "France",
    "Italy",
    "Italia",
    "Netherlands",
    "Japan",
    "Ireland",
    "Austria",
    "Österreich",
    "Switzerland",
    "Sweden",
    "Norway",
    "Denmark",
    "New Zealand",
    "India",
    "Belgium",
    "Singapore",
]

# Relevance keyword dictionary
RELEVANCE_KEYWORDS = [
    "importer",
    "distributor",
    "wholesaler",
    "wholesale",
    "retailer",
    "supplier",
    "buyer",
    "meditation",
    "wellness",
    "yoga",
    "spiritual products",
    "sound healing",
    "singing bowls",
    "tibetan singing bowls",
    "crystal singing bowls",
    "gongs",
    "brass bowls",
    "sound therapy",
]


def clean_extracted_email(raw: str) -> str:
    """
    Clean extraneous trailing punctuation (e.g. '.', ',', ';', ')', ']', '>') from regex matches.
    """
    if not raw:
        return ""
    cleaned = raw.strip().rstrip(".,;:)>]'\"").lstrip("<([\"'")
    return cleaned.lower()


def extract_emails_from_text(text: Optional[str]) -> List[str]:
    """
    Extract unique, normalized email addresses from raw text while preserving discovery order.
    """
    if not text or not isinstance(text, str):
        return []

    matches = EMAIL_SEARCH_REGEX.findall(text)
    seen = set()
    results = []

    for match in matches:
        cleaned = clean_extracted_email(match)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            results.append(cleaned)

    return results


def extract_emails_from_html(html_content: Optional[str]) -> List[str]:
    """
    Parse HTML content, check 'mailto:' links, and extract emails from text nodes.
    """
    if not html_content or not isinstance(html_content, str):
        return []

    emails = []
    seen = set()

    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Extract from mailto: links
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if href.lower().startswith("mailto:"):
                # Handle possible query params like mailto:info@example.com?subject=...
                mailto_target = href[7:].split("?")[0]
                cleaned = clean_extracted_email(mailto_target)
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    emails.append(cleaned)

        # 2. Extract from visible text
        text_content = soup.get_text(separator=" ")
        text_emails = extract_emails_from_text(text_content)
        for e in text_emails:
            if e not in seen:
                seen.add(e)
                emails.append(e)

    except Exception:
        # Fallback to pure regex if HTML parsing fails
        return extract_emails_from_text(html_content)

    return emails


def extract_company_name(
    html_content: Optional[str] = None,
    title: Optional[str] = None,
    url: Optional[str] = None,
) -> str:
    """
    Attempt to extract a clean company name from HTML metadata, page title, or domain structure.
    Never invents names; leaves blank if unconfident.
    """
    # 1. Try OpenGraph og:site_name from HTML
    if html_content and isinstance(html_content, str):
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            og_site = soup.find("meta", property="og:site_name")
            if og_site and og_site.get("content"):
                candidate = og_site["content"].strip()
                if 2 <= len(candidate) <= 60:
                    return candidate

            # Schema.org Organization name
            schema_org = soup.find(attrs={"itemtype": re.compile(r"Organization", re.I)})
            if schema_org:
                name_elem = schema_org.find(attrs={"itemprop": "name"})
                if name_elem and name_elem.get_text():
                    candidate = name_elem.get_text().strip()
                    if 2 <= len(candidate) <= 60:
                        return candidate
        except Exception:
            pass

    # 2. Clean page title
    raw_title = title or ""
    if not raw_title and html_content and isinstance(html_content, str):
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            if soup.title and soup.title.string:
                raw_title = soup.title.string.strip()
        except Exception:
            pass

    if raw_title:
        # Split on standard title delimiters: |, -, –, —, :, •
        parts = re.split(r"\s+[\|\-–—:•]\s+", raw_title)
        for part in parts:
            p = part.strip()
            # Ignore generic navigation names
            if p.lower() in {"home", "contact", "contact us", "about", "about us", "welcome", "wholesale", "index", "official site"}:
                continue
            if 2 <= len(p) <= 60:
                return p

    # 3. Fallback: derive from domain name if URL provided
    if url:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            domain = re.sub(r"^www\.", "", domain)
            domain_name = domain.split(".")[0]
            if len(domain_name) >= 3 and domain_name.lower() not in {"google", "bing", "yahoo", "facebook", "linkedin"}:
                # Format "zenithhealing" -> "Zenithhealing" or "zenith-healing" -> "Zenith Healing"
                clean_name = domain_name.replace("-", " ").replace("_", " ").title()
                return clean_name
        except Exception:
            pass

    return ""


def extract_country(text: Optional[str] = None, url: Optional[str] = None) -> str:
    """
    Determine the country from domain ccTLD or explicit address occurrences in text.
    Leaves blank if uncertain.
    """
    # 1. Check domain ccTLD
    if url:
        try:
            parsed = urlparse(url)
            netloc = (parsed.netloc or parsed.path).lower()
            for tld, country in CCTLD_COUNTRY_MAP.items():
                if netloc.endswith(tld):
                    return country
        except Exception:
            pass

    # 2. Check textual content for known countries
    if text and isinstance(text, str):
        text_lower = text.lower()
        for c in KNOWN_COUNTRIES:
            pattern = r"\b" + re.escape(c.lower()) + r"\b"
            if re.search(pattern, text_lower):
                return "United States" if c.upper() == "USA" else ("United Kingdom" if c.upper() == "UK" else c)

    return ""


def extract_buyer_name(text: Optional[str]) -> str:
    """
    Look for explicit contact person names in public contact or about text.
    Leaves blank if not confidently found.
    """
    if not text or not isinstance(text, str):
        return ""

    patterns = [
        r"(?:Contact Person|Contact|Attn|Buyer|Procurement Officer|Manager)\s*[:\-]\s*([A-Z][a-z]+ [A-Z][a-z]+)",
        r"(?:Head of Procurement|Procurement Manager)\s*[:\-]?\s*([A-Z][a-z]+ [A-Z][a-z]+)",
    ]

    for pat in patterns:
        match = re.search(pat, text)
        if match:
            candidate = match.group(1).strip()
            # Ensure candidate is not a generic header
            if candidate.lower() not in {"contact us", "send message", "about us", "customer service"}:
                return candidate

    return ""


def calculate_relevance_score(text: Optional[str], keyword: str = "") -> float:
    """
    Calculate a basic relevance score for discovered public content.
    Returns a score indicating alignment with export buyer criteria.
    """
    if not text or not isinstance(text, str):
        return 0.0

    text_lower = text.lower()
    score = 0.0

    # Match target keyword phrase
    if keyword and keyword.lower() in text_lower:
        score += 5.0

    # Match export/trade commercial intent indicators
    for kw in RELEVANCE_KEYWORDS:
        if kw in text_lower:
            score += 1.5

    return round(score, 2)


def create_buyer_record(
    buyer_name: str = "",
    company_name: str = "",
    email: str = "",
    website: str = "",
    country: str = "",
    source_platform: str = "",
) -> Dict[str, str]:
    """
    Construct a normalized buyer schema dictionary matching the project requirements.
    """
    return {
        "buyer_name": str(buyer_name).strip(),
        "company_name": str(company_name).strip(),
        "email": clean_extracted_email(email),
        "website": str(website).strip(),
        "country": str(country).strip(),
        "source_platform": str(source_platform).strip(),
    }


def extract_buyers_from_search_results(
    raw_results: List[Dict[str, Any]],
    source_platform: str = "Unknown",
    product_keyword: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Process raw search adapter results (snippets, titles, metadata) into structured buyer records.
    """
    buyers = []
    seen_emails = set()

    for item in raw_results:
        direct_email = clean_extracted_email(item.get("email", ""))
        extracted_emails = []

        if direct_email:
            extracted_emails.append(direct_email)

        text_corpus = " ".join([
            str(item.get("title", "")),
            str(item.get("snippet", "")),
            str(item.get("content", "")),
            str(item.get("raw_text", "")),
        ])

        for found_email in extract_emails_from_text(text_corpus):
            if found_email not in extracted_emails:
                extracted_emails.append(found_email)

        platform = item.get("source_platform", source_platform)
        url = item.get("website", item.get("link", item.get("url", "")))
        title = item.get("title", "")

        company = item.get("company_name") or extract_company_name(title=title, url=url)
        buyer_name = item.get("buyer_name") or extract_buyer_name(text_corpus)
        country = item.get("country") or extract_country(text=text_corpus, url=url)

        if extracted_emails:
            for em in extracted_emails:
                if em and em not in seen_emails:
                    seen_emails.add(em)
                    buyers.append(create_buyer_record(
                        buyer_name=buyer_name,
                        company_name=company,
                        email=em,
                        website=url,
                        country=country,
                        source_platform=platform,
                    ))
        else:
            if company or url:
                buyers.append(create_buyer_record(
                    buyer_name=buyer_name,
                    company_name=company,
                    email="",
                    website=url,
                    country=country,
                    source_platform=platform,
                ))

    return buyers


def extract_buyers_from_website(
    html_content: str,
    url: str,
    title: Optional[str] = None,
    source_platform: str = "Website Search"
) -> List[Dict[str, str]]:
    """
    Extract structured buyer records from a fetched website page.
    """
    if not html_content:
        return []

    soup = None
    text_content = ""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        text_content = soup.get_text(separator=" ")
    except Exception:
        text_content = html_content

    emails = extract_emails_from_html(html_content)
    company = extract_company_name(html_content=html_content, title=title, url=url)
    country = extract_country(text=text_content, url=url)
    buyer_name = extract_buyer_name(text_content)

    buyers = []
    if emails:
        for em in emails:
            buyers.append(create_buyer_record(
                buyer_name=buyer_name,
                company_name=company,
                email=em,
                website=url,
                country=country,
                source_platform=source_platform,
            ))
    elif company or url:
        buyers.append(create_buyer_record(
            buyer_name=buyer_name,
            company_name=company,
            email="",
            website=url,
            country=country,
            source_platform=source_platform,
        ))

    return buyers
