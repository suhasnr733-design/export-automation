"""
Activity Logger and Centralized CSV Data Store Manager.
Handles structured logging and CSV read/write operations for buyers, classifications, and send history.
"""

import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Set, Optional, Any

# Project base and data paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_BUYERS_CSV = DATA_DIR / "buyers.csv"
DEFAULT_BIZ_CSV = DATA_DIR / "business_emails.csv"
DEFAULT_IND_CSV = DATA_DIR / "individual_emails.csv"
DEFAULT_CLASSIFICATION_LOG_CSV = DATA_DIR / "classification_log.csv"
DEFAULT_QUALIFICATION_LOG_CSV = DATA_DIR / "qualification_log.csv"
DEFAULT_LEAD_REVIEW_LOG_CSV = DATA_DIR / "lead_review_log.csv"
DEFAULT_CAMPAIGN_LOG_CSV = DATA_DIR / "campaign_log.csv"
DEFAULT_SENT_LOG_CSV = DATA_DIR / "sent_log.csv"
DEFAULT_PROVENANCE_FILE = DATA_DIR / "discovery_provenance.json"

# Standard Buyer Schema
BUYER_SCHEMA_FIELDS = [
    "buyer_name",
    "company_name",
    "email",
    "website",
    "country",
    "source_platform",
]

# Classification Log Schema
CLASSIFICATION_LOG_FIELDS = [
    "email",
    "category",
    "confidence",
    "reason",
    "classification_source",
    "review_required",
    "timestamp",
]

# Qualification Log Schema (Phase 6E)
QUALIFICATION_LOG_FIELDS = [
    "email",
    "company_name",
    "product",
    "business_status",
    "product_relevance",
    "buyer_intent",
    "commercial_signals",
    "evidence",
    "qualification_score",
    "qualification_level",
    "recommendation",
    "classification_source",
    "qualification_source",
    "timestamp",
]

# Human Lead Review Log Schema (Phase 6F)
LEAD_REVIEW_LOG_FIELDS = [
    "email",
    "company_name",
    "qualification_score",
    "recommendation",
    "review_status",
    "reviewer_decision",
    "review_timestamp",
    "notes",
]

# Campaign Log Schema
CAMPAIGN_LOG_FIELDS = [
    "campaign_id",
    "timestamp",
    "recipient",
    "company_name",
    "audience",
    "subject",
    "status",
    "mode",
    "error",
]

# Set up standard logger
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("ExportAutomation")


def normalize_buyer_record(record: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize raw buyer data into the standard schema.
    Ensures all expected keys are present, stripped, and email is lowercased.
    """
    email_raw = str(record.get("email", "")).strip().lower()
    return {
        "buyer_name": str(record.get("buyer_name", "")).strip(),
        "company_name": str(record.get("company_name", "")).strip(),
        "email": email_raw,
        "website": str(record.get("website", "")).strip(),
        "country": str(record.get("country", "")).strip(),
        "source_platform": str(record.get("source_platform", "")).strip(),
    }


def init_data_stores(base_dir: Optional[Path] = None) -> None:
    """
    Ensure all required CSV data files and their parent directories exist with proper headers.
    """
    data_dir = (base_dir / "data") if base_dir else DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)

    files_and_headers = [
        (data_dir / "buyers.csv", BUYER_SCHEMA_FIELDS),
        (data_dir / "business_emails.csv", ["email"]),
        (data_dir / "individual_emails.csv", ["email"]),
        (data_dir / "classification_log.csv", CLASSIFICATION_LOG_FIELDS),
        (data_dir / "qualification_log.csv", QUALIFICATION_LOG_FIELDS),
        (data_dir / "lead_review_log.csv", LEAD_REVIEW_LOG_FIELDS),
        (data_dir / "campaign_log.csv", CAMPAIGN_LOG_FIELDS),
        (data_dir / "sent_log.csv", SENT_LOG_FIELDS),
    ]

    for file_path, headers in files_and_headers:
        if not file_path.exists() or file_path.stat().st_size == 0:
            with open(file_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            logger.debug(f"Initialized CSV data file: {file_path.name}")

    # Phase 6H: Migrate sent_log.csv to 5-field schema if on old 3-field schema
    sent_log_path = data_dir / "sent_log.csv"
    if sent_log_path.exists() and sent_log_path.stat().st_size > 0:
        migrated = migrate_sent_log_schema(sent_log_path)
        if migrated > 0:
            logger.info(f"init_data_stores: Migrated {migrated} sent_log records to Phase 6H schema.")


def load_buyers(csv_path: Optional[Path] = None) -> List[Dict[str, str]]:
    """
    Load buyer records from buyers.csv.
    """
    target = csv_path or DEFAULT_BUYERS_CSV
    if not target.exists():
        return []

    buyers = []
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("email"):
                buyers.append(normalize_buyer_record(row))
    return buyers


def save_buyers(buyers: List[Dict[str, Any]], csv_path: Optional[Path] = None, append: bool = False) -> int:
    """
    Save normalized buyer records to buyers.csv.
    Deduplicates against existing records by normalized lowercase email.
    Returns count of new records saved.
    """
    target = csv_path or DEFAULT_BUYERS_CSV
    target.parent.mkdir(parents=True, exist_ok=True)

    existing_buyers = load_buyers(target) if append and target.exists() else []
    existing_emails = {b["email"].lower() for b in existing_buyers if b.get("email")}

    new_count = 0
    records_to_write = list(existing_buyers) if append else []

    for b in buyers:
        norm = normalize_buyer_record(b)
        email = norm["email"]
        if email and (not append or email not in existing_emails):
            records_to_write.append(norm)
            existing_emails.add(email)
            new_count += 1
        elif not email:
            # Keep records without email if provided
            records_to_write.append(norm)
            new_count += 1

    with open(target, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BUYER_SCHEMA_FIELDS)
        writer.writeheader()
        for r in records_to_write:
            writer.writerow(r)

    logger.info(f"Saved {len(records_to_write)} total buyer records ({new_count} new) to {target.name}")
    return new_count


def save_classified_emails(
    business_emails: List[str],
    individual_emails: List[str],
    biz_path: Optional[Path] = None,
    ind_path: Optional[Path] = None,
) -> None:
    """
    Persist classified email lists into business_emails.csv and individual_emails.csv.
    """
    b_path = biz_path or DEFAULT_BIZ_CSV
    i_path = ind_path or DEFAULT_IND_CSV

    b_path.parent.mkdir(parents=True, exist_ok=True)
    i_path.parent.mkdir(parents=True, exist_ok=True)

    # Save business emails (deduplicated & normalized)
    unique_biz = sorted(list({e.strip().lower() for e in business_emails if e.strip()}))
    with open(b_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["email"])
        for email in unique_biz:
            writer.writerow([email])

    # Save individual emails (deduplicated & normalized)
    unique_ind = sorted(list({e.strip().lower() for e in individual_emails if e.strip()}))
    with open(i_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["email"])
        for email in unique_ind:
            writer.writerow([email])

    logger.info(f"Saved {len(unique_biz)} business emails and {len(unique_ind)} individual emails to CSV.")


def load_classified_emails(
    biz_path: Optional[Path] = None,
    ind_path: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """
    Load business and individual emails from CSV.
    """
    b_path = biz_path or DEFAULT_BIZ_CSV
    i_path = ind_path or DEFAULT_IND_CSV

    biz = []
    ind = []

    if b_path.exists():
        with open(b_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("email"):
                    biz.append(row["email"].strip().lower())

    if i_path.exists():
        with open(i_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("email"):
                    ind.append(row["email"].strip().lower())

    return {"business": biz, "individual": ind}


def save_classification_log(
    records: List[Dict[str, Any]],
    csv_path: Optional[Path] = None,
    append: bool = True,
) -> int:
    """
    Persist structured classification entries to classification_log.csv.
    """
    target = csv_path or DEFAULT_CLASSIFICATION_LOG_CSV
    target.parent.mkdir(parents=True, exist_ok=True)
    file_exists = target.exists() and target.stat().st_size > 0

    mode = "a" if append else "w"
    with open(target, mode=mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CLASSIFICATION_LOG_FIELDS)
        if not append or not file_exists:
            writer.writeheader()
        for r in records:
            writer.writerow({
                "email": str(r.get("email", "")).strip().lower(),
                "category": str(r.get("category", "")).strip().lower(),
                "confidence": str(r.get("confidence", 0.0)),
                "reason": str(r.get("reason", "")).strip(),
                "classification_source": str(r.get("classification_source", "")).strip(),
                "review_required": "True" if r.get("review_required") else "False",
                "timestamp": str(r.get("timestamp", "")) or datetime.now(timezone.utc).isoformat(),
            })

    logger.debug(f"Saved {len(records)} classification audit entries to {target.name}")
    return len(records)


def load_classification_log(csv_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Load all records from classification_log.csv.
    """
    target = csv_path or DEFAULT_CLASSIFICATION_LOG_CSV
    if not target.exists():
        return []

    logs = []
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            logs.append(dict(row))
    return logs


def audit_classification_log(csv_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Audit classification_log.csv and return metric breakdown.
    """
    target = csv_path or DEFAULT_CLASSIFICATION_LOG_CSV
    if not target.exists():
        return {
            "total_records": 0,
            "unique_emails": 0,
            "business_count": 0,
            "individual_count": 0,
            "review_required_count": 0,
            "error_count": 0,
            "source_distribution": {},
        }

    logs = load_classification_log(target)
    total_records = len(logs)
    emails = [r.get("email", "").lower() for r in logs if r.get("email")]
    unique_emails = len(set(emails))

    biz = 0
    ind = 0
    review = 0
    errors = 0
    source_dist: Dict[str, int] = {}

    for r in logs:
        cat = r.get("category", "").lower()
        if cat == "business":
            biz += 1
        elif cat == "individual":
            ind += 1
        else:
            errors += 1

        if str(r.get("review_required", "")).lower() in ("true", "1", "yes", "review_required"):
            review += 1

        src = r.get("classification_source", "UNKNOWN")
        source_dist[src] = source_dist.get(src, 0) + 1

    return {
        "total_records": total_records,
        "unique_emails": unique_emails,
        "business_count": biz,
        "individual_count": ind,
        "review_required_count": review,
        "error_count": errors,
        "source_distribution": source_dist,
    }


def save_qualification_log(
    records: List[Dict[str, Any]],
    csv_path: Optional[Path] = None,
    append: bool = True,
) -> int:
    """
    Save structured buyer qualification records to qualification_log.csv.
    """
    if not records:
        return 0

    target = csv_path or DEFAULT_QUALIFICATION_LOG_CSV
    target.parent.mkdir(parents=True, exist_ok=True)
    file_exists = target.exists() and target.stat().st_size > 0

    mode = "a" if append else "w"
    with open(target, mode=mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=QUALIFICATION_LOG_FIELDS)
        if not append or not file_exists:
            writer.writeheader()
        for r in records:
            comm_signals = r.get("commercial_signals", [])
            if isinstance(comm_signals, list):
                comm_signals_str = "; ".join(comm_signals)
            else:
                comm_signals_str = str(comm_signals)

            evidence = r.get("evidence", [])
            if isinstance(evidence, list):
                evidence_str = "; ".join(evidence)
            else:
                evidence_str = str(evidence)

            writer.writerow({
                "email": str(r.get("email", "")).strip().lower(),
                "company_name": str(r.get("company_name", "")).strip(),
                "product": str(r.get("product", "")).strip(),
                "business_status": str(r.get("business_status", "")).strip(),
                "product_relevance": str(r.get("product_relevance", 0.0)),
                "buyer_intent": str(r.get("buyer_intent", 0.0)),
                "commercial_signals": comm_signals_str,
                "evidence": evidence_str,
                "qualification_score": str(r.get("qualification_score", 0)),
                "qualification_level": str(r.get("qualification_level", "LOW")).strip(),
                "recommendation": str(r.get("recommendation", "MANUAL_REVIEW")).strip(),
                "classification_source": str(r.get("classification_source", "")).strip(),
                "qualification_source": str(r.get("qualification_source", "")).strip(),
                "timestamp": str(r.get("timestamp", "")) or datetime.now(timezone.utc).isoformat(),
            })

    logger.debug(f"Saved {len(records)} qualification audit entries to {target.name}")
    return len(records)


def load_qualification_log(csv_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Load all records from qualification_log.csv.
    """
    target = csv_path or DEFAULT_QUALIFICATION_LOG_CSV
    if not target.exists():
        return []

    logs = []
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            logs.append(dict(row))
    return logs


def audit_qualification_log(csv_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Audit qualification_log.csv and return metric breakdown.
    """
    target = csv_path or DEFAULT_QUALIFICATION_LOG_CSV
    if not target.exists():
        return {
            "total_records": 0,
            "unique_emails": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "review_required_count": 0,
            "recommendations": {},
            "source_distribution": {},
        }

    logs = load_qualification_log(target)
    total_records = len(logs)
    emails = [r.get("email", "").lower() for r in logs if r.get("email")]
    unique_emails = len(set(emails))

    high = 0
    med = 0
    low = 0
    rev = 0
    recs: Dict[str, int] = {}
    sources: Dict[str, int] = {}

    for r in logs:
        level = str(r.get("qualification_level", "")).upper()
        if level == "HIGH":
            high += 1
        elif level == "MEDIUM":
            med += 1
        elif level == "LOW":
            low += 1
        elif level == "REVIEW_REQUIRED":
            rev += 1

        rec = str(r.get("recommendation", "UNKNOWN")).upper()
        recs[rec] = recs.get(rec, 0) + 1

        src = str(r.get("qualification_source", "UNKNOWN"))
        sources[src] = sources.get(src, 0) + 1

    return {
        "total_records": total_records,
        "unique_emails": unique_emails,
        "high_count": high,
        "medium_count": med,
        "low_count": low,
        "review_required_count": rev,
        "recommendations": recs,
        "source_distribution": sources,
    }


def save_campaign_log(
    records: List[Dict[str, Any]],
    csv_path: Optional[Path] = None,
    append: bool = True,
) -> int:
    """
    Persist campaign dispatch entries to campaign_log.csv.
    """
    target = csv_path or DEFAULT_CAMPAIGN_LOG_CSV
    target.parent.mkdir(parents=True, exist_ok=True)
    file_exists = target.exists() and target.stat().st_size > 0

    mode = "a" if append else "w"
    with open(target, mode=mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPAIGN_LOG_FIELDS)
        if not append or not file_exists:
            writer.writeheader()
        for r in records:
            writer.writerow({
                "campaign_id": str(r.get("campaign_id", "")).strip(),
                "timestamp": str(r.get("timestamp", "")) or datetime.now(timezone.utc).isoformat(),
                "recipient": str(r.get("recipient", "")).strip().lower(),
                "company_name": str(r.get("company_name", "")).strip(),
                "audience": str(r.get("audience", "")).strip(),
                "subject": str(r.get("subject", "")).strip(),
                "status": str(r.get("status", "")).strip(),
                "mode": str(r.get("mode", "TEST")).strip().upper(),
                "error": str(r.get("error", "")).strip(),
            })

    logger.debug(f"Saved {len(records)} campaign log entries to {target.name}")
    return len(records)


def load_campaign_log(csv_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Load all records from campaign_log.csv.
    """
    target = csv_path or DEFAULT_CAMPAIGN_LOG_CSV
    if not target.exists():
        return []

    logs = []
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            logs.append(dict(row))
    return logs


def audit_campaign_log(csv_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Audit campaign_log.csv and return breakdown metrics.
    """
    target = csv_path or DEFAULT_CAMPAIGN_LOG_CSV
    if not target.exists():
        return {
            "total_records": 0,
            "campaign_ids": [],
            "successful_sends": 0,
            "failed_sends": 0,
            "test_mode_sends": 0,
            "live_sends": 0,
        }

    logs = load_campaign_log(target)
    total_records = len(logs)
    campaign_ids = list({r.get("campaign_id") for r in logs if r.get("campaign_id")})

    success = 0
    failed = 0
    test_mode = 0
    live = 0

    for r in logs:
        status = r.get("status", "").upper()
        mode = r.get("mode", "").upper()

        if mode == "TEST":
            test_mode += 1
        elif mode == "LIVE":
            live += 1

        if "SUCCESS" in status or status == "SENT":
            success += 1
        elif "FAIL" in status or "ERR" in status:
            failed += 1

    return {
        "total_records": total_records,
        "campaign_ids": campaign_ids,
        "successful_sends": success,
        "failed_sends": failed,
        "test_mode_sends": test_mode,
        "live_sends": live,
    }


# =========================================================================
# Sent Log Schema Constants (Phase 6H)
# =========================================================================

SENT_LOG_FIELDS = ["email", "status", "send_type", "campaign_id", "timestamp"]
SEND_TYPE_REAL = "REAL_SEND"
SEND_TYPE_TEST = "TEST_MODE_SIMULATION"
SEND_TYPE_LEGACY = "LEGACY"


def migrate_sent_log_schema(csv_path: Optional[Path] = None) -> int:
    """
    Migrate sent_log.csv from 3-column schema (email, status, timestamp)
    to 5-column schema (email, status, send_type, campaign_id, timestamp).

    - Creates a .bak backup before writing.
    - Infers send_type from status: TEST_MODE_* -> TEST_MODE_SIMULATION, SENT/SUCCESS -> REAL_SEND, else LEGACY.
    - Sets campaign_id = 'LEGACY' for all existing records.
    - Returns number of records migrated (0 if already on new schema or file missing).
    - Safe to call multiple times (idempotent when already on new schema).
    """
    target = csv_path or DEFAULT_SENT_LOG_CSV
    if not target.exists() or target.stat().st_size == 0:
        return 0

    # Detect schema version from header
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        if "send_type" in fieldnames and "campaign_id" in fieldnames:
            return 0  # Already migrated
        existing_rows = list(reader)

    # Build migrated rows
    migrated: List[Dict[str, str]] = []
    for row in existing_rows:
        status = row.get("status", "").upper()
        if "TEST_MODE" in status:
            send_type = SEND_TYPE_TEST
        elif status in ("SENT", "SUCCESS"):
            send_type = SEND_TYPE_REAL
        else:
            send_type = SEND_TYPE_LEGACY
        migrated.append({
            "email": row.get("email", ""),
            "status": row.get("status", ""),
            "send_type": send_type,
            "campaign_id": "LEGACY",
            "timestamp": row.get("timestamp", ""),
        })

    # Atomic write: write to temp, rename
    bak_path = target.with_suffix(".csv.bak")
    tmp_path = target.with_suffix(".csv.tmp")
    import shutil
    shutil.copy2(target, bak_path)

    try:
        with open(tmp_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SENT_LOG_FIELDS)
            writer.writeheader()
            writer.writerows(migrated)
        tmp_path.replace(target)
        logger.info(f"Migrated sent_log.csv schema: {len(migrated)} records -> 5-field schema.")
    except Exception as e:
        logger.error(f"Migration failed, backup retained at {bak_path}: {e}")
        raise

    return len(migrated)


def get_real_sends_for_date(
    target_date: Optional[str] = None,
    csv_path: Optional[Path] = None,
) -> int:
    """
    Count REAL_SEND entries recorded for a specific date.
    Used for production daily quota enforcement.
    TEST_MODE_SIMULATION entries are NOT counted here.
    """
    target = csv_path or DEFAULT_SENT_LOG_CSV
    if not target.exists():
        return 0

    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    count = 0
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row.get("timestamp", "")
            send_type = row.get("send_type", "").upper()
            status = row.get("status", "").upper()
            # On old (LEGACY) schema without send_type: fall back to status-based detection
            if not send_type or send_type == SEND_TYPE_LEGACY:
                is_real = status in ("SENT", "SUCCESS")
            else:
                is_real = send_type == SEND_TYPE_REAL
            if ts.startswith(target_date) and is_real and ("SUCCESS" in status or status in ("SENT",)):
                count += 1
    return count


def get_test_simulations_for_date(
    target_date: Optional[str] = None,
    csv_path: Optional[Path] = None,
) -> int:
    """
    Count TEST_MODE_SIMULATION entries recorded for a specific date.
    Used for test-simulation quota enforcement.
    REAL_SEND entries are NOT counted here.
    """
    target = csv_path or DEFAULT_SENT_LOG_CSV
    if not target.exists():
        return 0

    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    count = 0
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row.get("timestamp", "")
            send_type = row.get("send_type", "").upper()
            status = row.get("status", "").upper()
            # On old (LEGACY) schema without send_type: fall back to status-based detection
            if not send_type or send_type == SEND_TYPE_LEGACY:
                is_test = "TEST_MODE" in status
            else:
                is_test = send_type == SEND_TYPE_TEST
            if ts.startswith(target_date) and is_test:
                count += 1
    return count


def get_successful_sends_for_date(
    target_date: Optional[str] = None,
    csv_path: Optional[Path] = None,
) -> int:
    """
    [BACKWARD COMPAT] Count real (non-test) successful send events for a date.
    Now delegates to get_real_sends_for_date() — TEST_MODE_SIMULATION entries
    are NO LONGER counted here.
    """
    return get_real_sends_for_date(target_date=target_date, csv_path=csv_path)


def get_sent_emails(csv_path: Optional[Path] = None) -> Set[str]:
    """
    Read historical sent records from sent_log.csv and return set of normalized emails
    that were successfully sent (or test-mode sent).
    """
    target = csv_path or DEFAULT_SENT_LOG_CSV
    if not target.exists():
        return set()

    sent_set = set()
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = row.get("status", "").upper()
            email = row.get("email", "").strip().lower()
            # Mark as sent if SUCCESS or TEST_MODE_SUCCESS
            if email and ("SUCCESS" in status or status == "TEST_MODE_SUCCESS" or status == "SENT"):
                sent_set.add(email)

    return sent_set


def log_send_attempt(
    email: str,
    status: str,
    send_type: Optional[str] = None,
    campaign_id: str = "",
    timestamp: Optional[str] = None,
    csv_path: Optional[Path] = None,
) -> None:
    """
    Append an attempted email send record to sent_log.csv.

    Args:
        email: Recipient email address.
        status: Outcome status (TEST_MODE_SUCCESS, SENT, FAILED, etc.).
        send_type: REAL_SEND or TEST_MODE_SIMULATION. Inferred from status if None.
        campaign_id: Campaign identifier for traceability. Defaults to empty string.
        timestamp: ISO timestamp. Defaults to current UTC time.
        csv_path: Override path for sent_log.csv.
    """
    target = csv_path or DEFAULT_SENT_LOG_CSV
    target.parent.mkdir(parents=True, exist_ok=True)

    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    # Infer send_type from status if not provided
    if send_type is None:
        send_type = SEND_TYPE_TEST if "TEST_MODE" in status.upper() else SEND_TYPE_REAL

    # Detect schema version of existing file
    file_exists = target.exists() and target.stat().st_size > 0
    needs_new_header = False
    if file_exists:
        with open(target, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing_fields = reader.fieldnames or []
        needs_new_header = "send_type" not in existing_fields
        if needs_new_header:
            # Migrate before appending
            migrate_sent_log_schema(target)
    else:
        needs_new_header = False  # Will write header below

    with open(target, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SENT_LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "email": email.strip().lower(),
            "status": status.strip(),
            "send_type": send_type,
            "campaign_id": campaign_id or "",
            "timestamp": timestamp,
        })

    logger.debug(f"Logged send attempt: {email} -> {status} [{send_type}] campaign={campaign_id or 'N/A'}")


def load_sent_log(csv_path: Optional[Path] = None) -> List[Dict[str, str]]:
    """
    Load all records from sent_log.csv.
    """
    target = csv_path or DEFAULT_SENT_LOG_CSV
    if not target.exists():
        return []

    logs = []
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            logs.append(dict(row))
    return logs


def load_discovery_provenance(json_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load discovery provenance metadata mapping email -> source metadata.
    """
    target = json_path or DEFAULT_PROVENANCE_FILE
    if not target.exists():
        return {"metadata": {}, "records": {}}

    try:
        with open(target, mode="r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"metadata": {}, "records": {}}
            if "records" not in data:
                data = {"metadata": {}, "records": data}
            return data
    except Exception as e:
        logger.warning(f"Failed to load discovery provenance: {e}")
        return {"metadata": {}, "records": {}}


def save_discovery_provenance(
    records: List[Dict[str, Any]],
    keyword: str,
    json_path: Optional[Path] = None,
) -> None:
    """
    Persist or update provenance records for newly discovered or inspected leads.
    Preserves keyword, timestamp, URL, relevance decision, and data_source.
    """
    target = json_path or DEFAULT_PROVENANCE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    current_data = load_discovery_provenance(target)
    now_iso = datetime.now(timezone.utc).isoformat()

    current_data["metadata"]["last_discovery_keyword"] = keyword
    current_data["metadata"]["last_discovery_timestamp"] = now_iso

    prov_records = current_data.get("records", {})

    for r in records:
        email = r.get("email", "").strip().lower()
        if not email:
            continue
        prov_records[email] = {
            "data_source": r.get("data_source", "LIVE_DISCOVERY"),
            "keyword": r.get("keyword", keyword),
            "discovery_timestamp": r.get("discovery_timestamp", now_iso),
            "source_platform": r.get("source_platform", "Website Search"),
            "url": r.get("url") or r.get("website", ""),
            "company_name": r.get("company_name", ""),
            "country": r.get("country", ""),
            "relevance_decision": r.get("relevance_decision", "ACCEPT"),
            "relevance_reason": r.get("relevance_reason", "Discovered via keyword-aware web search"),
        }

    current_data["records"] = prov_records
    current_data["metadata"]["total_provenance_records"] = len(prov_records)

    with open(target, mode="w", encoding="utf-8") as f:
        json.dump(current_data, f, indent=2, ensure_ascii=False)


def get_provenance_audit(
    records: Optional[List[Dict[str, Any]]] = None,
    json_path: Optional[Path] = None,
    csv_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Audit buyer records against discovery provenance to categorize into:
    - Historical / Test buyers
    - Live Discovery buyers
    - User Uploaded buyers
    """
    if records is None:
        target_csv = csv_path or DEFAULT_BUYERS_CSV
        records = load_buyers(target_csv) if target_csv.exists() else []

    prov_data = load_discovery_provenance(json_path)
    prov_records = prov_data.get("records", {})
    metadata = prov_data.get("metadata", {})

    historical_test_count = 0
    live_discovery_count = 0
    user_upload_count = 0

    for r in records:
        em = r.get("email", "").strip().lower()
        p_entry = prov_records.get(em, {})
        source_type = p_entry.get("data_source", "").upper()

        if source_type == "LIVE_DISCOVERY":
            live_discovery_count += 1
        elif source_type == "USER_UPLOAD":
            user_upload_count += 1
        else:
            # Default to HISTORICAL_TEST for records prior to or without explicit live discovery provenance
            historical_test_count += 1

    return {
        "historical_test_count": historical_test_count,
        "live_discovery_count": live_discovery_count,
        "user_upload_count": user_upload_count,
        "last_discovery_keyword": metadata.get("last_discovery_keyword", "Handmade Pashmina"),
        "last_discovery_timestamp": metadata.get("last_discovery_timestamp", ""),
        "total_records": len(records),
    }


def audit_buyers_csv(csv_path: Optional[Path] = None, provenance_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Audit buyers.csv and return breakdown metrics:
    total records, unique emails, duplicate emails, source_platform distribution,
    records with missing company/country/website/buyer_name, and provenance breakdown.
    """
    target = csv_path or DEFAULT_BUYERS_CSV
    if not target.exists():
        return {
            "total_records": 0,
            "unique_emails": 0,
            "duplicate_emails": 0,
            "platform_distribution": {},
            "missing_company": 0,
            "missing_country": 0,
            "missing_website": 0,
            "missing_buyer_name": 0,
            "historical_test_count": 0,
            "live_discovery_count": 0,
            "user_upload_count": 0,
            "last_discovery_keyword": "Handmade Pashmina",
        }

    records = load_buyers(target)
    total_records = len(records)
    emails = [r["email"].lower() for r in records if r.get("email")]
    unique_emails = len(set(emails))
    duplicate_emails = total_records - unique_emails

    platform_dist: Dict[str, int] = {}
    missing_company = 0
    missing_country = 0
    missing_website = 0
    missing_buyer_name = 0

    for r in records:
        src = r.get("source_platform", "Unknown") or "Unknown"
        platform_dist[src] = platform_dist.get(src, 0) + 1

        if not r.get("company_name"):
            missing_company += 1
        if not r.get("country"):
            missing_country += 1
        if not r.get("website"):
            missing_website += 1
        if not r.get("buyer_name"):
            missing_buyer_name += 1

    prov_audit = get_provenance_audit(records, json_path=provenance_path, csv_path=target)

    return {
        "total_records": total_records,
        "unique_emails": unique_emails,
        "duplicate_emails": duplicate_emails,
        "platform_distribution": platform_dist,
        "missing_company": missing_company,
        "missing_country": missing_country,
        "missing_website": missing_website,
        "missing_buyer_name": missing_buyer_name,
        "historical_test_count": prov_audit["historical_test_count"],
        "live_discovery_count": prov_audit["live_discovery_count"],
        "user_upload_count": prov_audit["user_upload_count"],
        "last_discovery_keyword": prov_audit["last_discovery_keyword"],
        "last_discovery_timestamp": prov_audit.get("last_discovery_timestamp", ""),
    }


def audit_sent_log(csv_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Audit sent_log.csv and return breakdown metrics with separated
    REAL_SEND and TEST_MODE_SIMULATION counters (Phase 6H).
    """
    target = csv_path or DEFAULT_SENT_LOG_CSV
    empty = {
        "total_records": 0,
        "unique_emails": 0,
        "successful_sends": 0,
        "failed_sends": 0,
        "test_mode_records": 0,
        "unique_simulated_recipients": 0,
        "unique_live_contacted": 0,
        "skipped_duplicates": 0,
        "skipped_daily_limit": 0,
        "skipped_invalid": 0,
        # Phase 6H additions
        "total_real_sends": 0,
        "total_test_simulations": 0,
        "real_sends_today": 0,
        "test_simulations_today": 0,
    }
    if not target.exists():
        return empty

    logs = load_sent_log(target)
    total_records = len(logs)

    successful_sends = 0
    failed_sends = 0
    test_mode_records = 0
    total_real_sends = 0
    total_test_simulations = 0
    skipped_duplicates = 0
    skipped_daily_limit = 0
    skipped_invalid = 0

    simulated_emails: Set[str] = set()
    live_contacted_emails: Set[str] = set()
    all_emails: Set[str] = set()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    real_sends_today = 0
    test_simulations_today = 0

    for r in logs:
        status = r.get("status", "").upper()
        send_type = r.get("send_type", "").upper()
        ts = r.get("timestamp", "")
        em = r.get("email", "").strip().lower()
        if em:
            all_emails.add(em)

        # Determine category by send_type first, fall back to status heuristic
        if send_type == SEND_TYPE_TEST or (not send_type and "TEST_MODE" in status):
            test_mode_records += 1
            total_test_simulations += 1
            if em:
                simulated_emails.add(em)
            if ts.startswith(today):
                test_simulations_today += 1
        elif send_type == SEND_TYPE_REAL or (not send_type and status in ("SENT", "SUCCESS")):
            if status in ("SENT", "SUCCESS"):
                successful_sends += 1
                total_real_sends += 1
                if em:
                    live_contacted_emails.add(em)
                if ts.startswith(today):
                    real_sends_today += 1
            elif "FAIL" in status or "ERR" in status:
                failed_sends += 1
        elif "FAIL" in status or "ERR" in status:
            failed_sends += 1
        elif "DUPLICATE" in status:
            skipped_duplicates += 1
        elif "DAILY_LIMIT" in status:
            skipped_daily_limit += 1
        elif "INVALID" in status:
            skipped_invalid += 1

    return {
        "total_records": total_records,
        "unique_emails": len(all_emails),
        "successful_sends": successful_sends,
        "failed_sends": failed_sends,
        "test_mode_records": test_mode_records,
        "unique_simulated_recipients": len(simulated_emails),
        "unique_live_contacted": len(live_contacted_emails),
        "skipped_duplicates": skipped_duplicates,
        "skipped_daily_limit": skipped_daily_limit,
        "skipped_invalid": skipped_invalid,
        # Phase 6H additions
        "total_real_sends": total_real_sends,
        "total_test_simulations": total_test_simulations,
        "real_sends_today": real_sends_today,
        "test_simulations_today": test_simulations_today,
    }


# =========================================================================
# Human Lead Review Store Operations (Phase 6F)
# =========================================================================

def save_lead_review_decision(
    record: Dict[str, Any],
    csv_path: Optional[Path] = None,
) -> None:
    """
    Save or append a human lead review decision to lead_review_log.csv.
    Fields: email, company_name, qualification_score, recommendation, review_status, reviewer_decision, review_timestamp, notes.
    """
    target = csv_path or DEFAULT_LEAD_REVIEW_LOG_CSV
    target.parent.mkdir(parents=True, exist_ok=True)

    file_exists = target.exists() and target.stat().st_size > 0

    norm_email = str(record.get("email", "")).strip().lower()
    ts = record.get("review_timestamp") or datetime.now(timezone.utc).isoformat()

    row = {
        "email": norm_email,
        "company_name": str(record.get("company_name", "")).strip(),
        "qualification_score": str(record.get("qualification_score", 0)),
        "recommendation": str(record.get("recommendation", "")).strip(),
        "review_status": str(record.get("review_status", "PENDING_REVIEW")).strip().upper(),
        "reviewer_decision": str(record.get("reviewer_decision", "")).strip(),
        "review_timestamp": str(ts),
        "notes": str(record.get("notes", "")).strip(),
    }

    with open(target, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEAD_REVIEW_LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    logger.info(f"Recorded lead review decision for {norm_email}: status={row['review_status']}")


def load_lead_review_log(csv_path: Optional[Path] = None) -> List[Dict[str, str]]:
    """
    Load all human lead review records from lead_review_log.csv.
    """
    target = csv_path or DEFAULT_LEAD_REVIEW_LOG_CSV
    if not target.exists():
        return []

    records = []
    with open(target, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("email"):
                records.append({k: str(v).strip() for k, v in row.items()})
    return records


def get_lead_review_statuses(csv_path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """
    Get the most recent review decision mapped by email.
    Returns: Dict[email_lower, review_record_dict]
    """
    logs = load_lead_review_log(csv_path)
    latest_by_email: Dict[str, Dict[str, str]] = {}
    for r in logs:
        em = r.get("email", "").strip().lower()
        if em:
            latest_by_email[em] = r
    return latest_by_email


def audit_lead_review_log(csv_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Produce summary metrics on human lead reviews from lead_review_log.csv.
    """
    target = csv_path or DEFAULT_LEAD_REVIEW_LOG_CSV
    statuses = get_lead_review_statuses(target)

    approved = sum(1 for s in statuses.values() if s.get("review_status") == "APPROVED")
    rejected = sum(1 for s in statuses.values() if s.get("review_status") == "REJECTED")
    manual_review = sum(1 for s in statuses.values() if s.get("review_status") == "MANUAL_REVIEW_REQUESTED")
    pending = sum(1 for s in statuses.values() if s.get("review_status") == "PENDING_REVIEW")

    return {
        "total_reviews": len(statuses),
        "approved": approved,
        "rejected": rejected,
        "manual_review_requested": manual_review,
        "pending": pending,
        "latest_statuses": statuses,
    }


