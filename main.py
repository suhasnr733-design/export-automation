"""
API 3 - EXPORT AUTOMATION SYSTEM
Main Pipeline, Discovery, Classification & Safe Outreach CLI Entry Point.

Supports:
  - Full 7-stage automated outreach pipeline (TEST_MODE by default)
  - Standalone Buyer Discovery (--discover)
  - Dataset Validation (--validate)
  - AI Classification Pipeline (--classify)
  - Campaign Preview & Approval Gate (--campaign-preview, --approve-campaign)
  - Safe Campaign Execution (--send --test)
  - Dataset and Configuration Status (--status, --campaign-status)
  - Web Interface Routing Specification (--routes-info)
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import Config
from logging.activity_logger import (
    logger,
    init_data_stores,
    save_buyers,
    load_buyers,
    save_classified_emails,
    load_classified_emails,
    save_classification_log,
    load_classification_log,
    audit_classification_log,
    save_campaign_log,
    load_campaign_log,
    audit_campaign_log,
    get_sent_emails,
    load_sent_log,
    audit_buyers_csv,
    audit_sent_log,
    save_discovery_provenance,
    load_discovery_provenance,
    save_qualification_log,
    load_qualification_log,
    audit_qualification_log,
    audit_lead_review_log,
)
from search import (
    SearchQueryBuilder,
    GoogleSearchAdapter,
    FacebookSearchAdapter,
    LinkedInSearchAdapter,
    DirectorySearchAdapter,
    WebsiteSearchAdapter,
    evaluate_result_relevance,
    RelevanceAudit,
)
from extraction import (
    extract_buyers_from_search_results,
    extract_buyers_from_website,
)
from validation import validate_buyer_records
from classification import (
    classify_contacts,
    classify_contacts_detailed,
    run_classification_pipeline,
    classify_live_records,
    ClassificationResult,
)
from qualification import (
    QualificationResult,
    LocalTestQualifier,
    qualify_live_buyers,
    expand_product_keywords,
)
from outreach import (
    GmailSender,
    AttachmentHandler,
    AttachmentError,
    PersonalizationEngine,
    Campaign,
    CampaignStatus,
    CampaignStateError,
    CampaignStore,
    CampaignManager,
)
from reports import ReportGenerator, RunMetrics


def run_discovery_only(
    keyword: Optional[str] = None,
    max_results: Optional[int] = None,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Execute standalone Phase 2 Real Buyer Discovery workflow.
    Discovers potential export buyers, extracts details, validates emails,
    deduplicates against existing data, and persists to data/buyers.csv.
    """
    search_keyword = keyword or Config.SEARCH_KEYWORD
    limit = max_results or Config.MAX_SEARCH_RESULTS
    target_data_dir = data_dir or Config.DATA_DIR
    buyers_csv_path = target_data_dir / "buyers.csv"

    init_data_stores(base_dir=target_data_dir.parent if target_data_dir.name == "data" else target_data_dir)

    # 1. Inspect existing datastore state
    existing_buyers = load_buyers(buyers_csv_path)
    existing_emails = {b["email"].lower() for b in existing_buyers if b.get("email")}

    print("\n" + "=" * 60)
    print("             REAL BUYER DISCOVERY PIPELINE")
    print("=" * 60)
    print(f"Keyword         : {search_keyword}")
    print(f"Max Results     : {limit}")
    print(f"Discovery Mode  : {'TEST DISCOVERY' if Config.TEST_DISCOVERY else 'LIVE WEB DISCOVERY'}")
    print(f"Target Store    : {buyers_csv_path.name}")
    print(f"Existing Buyers : {len(existing_buyers)}")
    print("-" * 60)

    # 2. Build Multi-source Queries
    queries = SearchQueryBuilder.build_discovery_queries(search_keyword)
    logger.info(f"Generated {len(queries)} specialized search queries for '{search_keyword}'.")

    # 3. Multi-channel Search Execution
    raw_search_results = []
    source_statuses = {}

    # Google Search Adapter (LIVE)
    google_adapter = GoogleSearchAdapter(max_results=limit, test_discovery=Config.TEST_DISCOVERY)
    google_results = google_adapter.search(search_keyword)
    raw_search_results.extend(google_results)
    source_statuses["Google Search"] = "LIVE" if not Config.TEST_DISCOVERY else "TEST_DISCOVERY"

    # Display Query Diagnostics
    if google_adapter.last_diagnostics:
        print("\n--- Search Query Diagnostics ---")
        for diag in google_adapter.last_diagnostics:
            print(diag.format_report())
            print()

    # Social & Directory Adapters (STUB)
    fb_adapter = FacebookSearchAdapter()
    fb_results = fb_adapter.search(search_keyword)
    raw_search_results.extend(fb_results)
    source_statuses["Facebook"] = "STUB"

    li_adapter = LinkedInSearchAdapter()
    li_results = li_adapter.search(search_keyword)
    raw_search_results.extend(li_results)
    source_statuses["LinkedIn"] = "STUB"

    dir_adapter = DirectorySearchAdapter()
    dir_results = dir_adapter.search(search_keyword)
    raw_search_results.extend(dir_results)
    source_statuses["Trade Directory"] = "STUB"

    # Deep Website Crawl Adapter (LIVE)
    web_adapter = WebsiteSearchAdapter(
        max_websites=Config.MAX_WEBSITES_PER_RESULT,
        test_discovery=Config.TEST_DISCOVERY,
    )
    external_urls = [r["url"] for r in google_results if r.get("url") and r["url"].startswith("http")]
    if external_urls:
        web_results = web_adapter.crawl_and_extract(external_urls[:Config.MAX_WEBSITES_PER_RESULT], keyword=search_keyword)
        raw_search_results.extend(web_results)
        source_statuses["Website Deep Crawl"] = "LIVE" if not Config.TEST_DISCOVERY else "TEST_DISCOVERY"
    else:
        source_statuses["Website Deep Crawl"] = "IDLE (No URLs)"

    # 4. Result Relevance Filter & Discovery Audit
    print("\n" + "-" * 60)
    print("           DISCOVERY RELEVANCE AUDIT")
    print("-" * 60)

    accepted_raw_results = []
    rejected_count = 0

    for idx, item in enumerate(raw_search_results, 1):
        audit = evaluate_result_relevance(item, keyword=search_keyword, query=item.get("query", ""))
        print(f"\n[{idx}/{len(raw_search_results)}]")
        print(audit.format_log_entry())

        if audit.decision == "ACCEPT":
            accepted_raw_results.append(item)
        else:
            rejected_count += 1

    print("-" * 60 + "\n")

    # 5. Information Extraction from Accepted Results
    discovered_buyers = extract_buyers_from_search_results(accepted_raw_results, product_keyword=search_keyword)
    total_emails_discovered = len(discovered_buyers)

    # 6. Email Validation & Syntax Verification
    valid_buyers, invalid_buyers = validate_buyer_records(discovered_buyers)

    # 7. Deduplication against data/buyers.csv (DISCOVERY DEDUPLICATION)
    unique_new_buyers = []
    duplicate_count = 0
    seen_in_batch = set()

    for buyer in valid_buyers:
        norm_email = buyer["email"].lower()
        if norm_email in seen_in_batch or norm_email in existing_emails:
            duplicate_count += 1
        else:
            seen_in_batch.add(norm_email)
            unique_new_buyers.append(buyer)

    # 8. Persistence to data/buyers.csv and discovery provenance
    records_written = 0
    if unique_new_buyers:
        records_written = save_buyers(unique_new_buyers, csv_path=buyers_csv_path, append=True)
        prov_path = buyers_csv_path.parent / "discovery_provenance.json"
        save_discovery_provenance(unique_new_buyers, keyword=search_keyword, json_path=prov_path)

    # 9. Summary Display
    print("\n" + "=" * 60)
    print("                 DISCOVERY SUMMARY")
    print("=" * 60)
    print(f"Existing buyers in datastore : {len(existing_buyers)}")
    print(f"Search results collected     : {len(raw_search_results)}")
    print(f"Relevant items accepted      : {len(accepted_raw_results)}")
    print(f"Unrelated items rejected     : {rejected_count}")
    print(f"Potential buyer records      : {len(discovered_buyers)}")
    print(f"Emails discovered            : {total_emails_discovered}")
    print(f"Valid emails                 : {len(valid_buyers)}")
    print(f"Invalid emails filtered      : {len(invalid_buyers)}")
    print(f"Duplicates against existing  : {duplicate_count}")
    print(f"New records written to CSV   : {records_written}")
    print("-" * 60)
    print("Source Adapter Statuses      :")
    for src, st in source_statuses.items():
        print(f"  * {src:<24}: {st}")
    print("=" * 60 + "\n")

    return {
        "existing_buyers": len(existing_buyers),
        "search_results": len(raw_search_results),
        "accepted_items": len(accepted_raw_results),
        "rejected_items": rejected_count,
        "potential_buyers": len(discovered_buyers),
        "emails_discovered": total_emails_discovered,
        "valid_emails": len(valid_buyers),
        "duplicates_removed": duplicate_count,
        "records_written": records_written,
        "source_statuses": source_statuses,
    }


def run_validation_check(csv_path: Optional[Path] = None) -> None:
    """
    Validate existing records in data/buyers.csv and display status report.
    """
    target_csv = csv_path or Config.BUYERS_CSV
    init_data_stores()
    buyers = load_buyers(target_csv)

    print("\n" + "=" * 60)
    print("              DATASTORE VALIDATION AUDIT")
    print("=" * 60)
    print(f"Inspecting File: {target_csv.name}")
    print(f"Total Records  : {len(buyers)}")
    print("-" * 60)

    if not buyers:
        print("No buyer records currently stored in data/buyers.csv.")
        print("=" * 60 + "\n")
        return

    valid_records, invalid_records = validate_buyer_records(buyers)

    print(f"Valid Email Records   : {len(valid_records)}")
    print(f"Invalid / Flagged     : {len(invalid_records)}")

    if invalid_records:
        print("\nFlagged Records:")
        for idx, (rec, res) in enumerate(invalid_records, 1):
            print(f"  [{idx}] Email: '{rec.get('email')}' | Company: '{rec.get('company_name')}' | Reason: {res.reason}")

    print("=" * 60 + "\n")


def run_classification_only(
    data_dir: Optional[Path] = None,
    batch_size: Optional[int] = None,
    review_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Execute standalone Phase 3 AI Lead Classification workflow.
    Loads buyers.csv, validates syntax, deduplicates, classifies contacts,
    persists business_emails.csv, individual_emails.csv, classification_log.csv,
    and displays structured audit summary.
    """
    target_dir = data_dir or Config.DATA_DIR
    init_data_stores(base_dir=target_dir.parent if target_dir.name == "data" else target_dir)

    return run_classification_pipeline(
        buyers_csv_path=target_dir / "buyers.csv",
        biz_csv_path=target_dir / "business_emails.csv",
        ind_csv_path=target_dir / "individual_emails.csv",
        log_csv_path=target_dir / "classification_log.csv",
        batch_size=batch_size,
        review_threshold=review_threshold,
    )


def run_classify_live_action(data_dir: Optional[Path] = None) -> None:
    """
    Execute SAFE LIVE GEMINI CLASSIFICATION exclusively for LIVE_DISCOVERY leads.
    Safety invariants:
    - Gmail is strictly DISABLED / TEST MODE
    - Refuses to run if CLASSIFICATION_LIVE is False
    - Refuses to run if GEMINI_API_KEY is missing
    - Strictly filters out HISTORICAL_TEST leads
    - Does NOT fallback to LOCAL_TEST_CLASSIFICATION on API failure
    """
    target_dir = data_dir or Config.DATA_DIR
    init_data_stores(base_dir=target_dir.parent if target_dir.name == "data" else target_dir)

    print("\n" + "=" * 60)
    print("         SAFE LIVE GEMINI CLASSIFICATION")
    print("=" * 60)
    print("GEMINI CLASSIFICATION: LIVE")
    print("GMAIL OUTREACH: DISABLED / TEST MODE")
    print("=" * 60 + "\n")

    if not Config.CLASSIFICATION_LIVE:
        print("ERROR: CLASSIFICATION_LIVE is set to false.")
        print("Enable with CLASSIFICATION_LIVE=true in .env to perform live Gemini classification.")
        print("\n" + "=" * 60)
        print("GEMINI CLASSIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    if not Config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY_NOT_CONFIGURED.")
        print("Please configure GEMINI_API_KEY in .env before running live classification.")
        print("\n" + "=" * 60)
        print("GEMINI CLASSIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    # Load buyers and provenance
    buyers = load_buyers(target_dir / "buyers.csv")
    prov_data = load_discovery_provenance(target_dir / "discovery_provenance.json")
    prov_records = prov_data.get("records", {})

    # Select ONLY LIVE_DISCOVERY records
    live_buyers = []
    for b in buyers:
        em = b.get("email", "").strip().lower()
        if em and prov_records.get(em, {}).get("data_source") == "LIVE_DISCOVERY":
            live_buyers.append(b)

    if not live_buyers:
        print("No LIVE_DISCOVERY buyer records found in discovery provenance.")
        print("\n" + "=" * 60)
        print("GEMINI CLASSIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    print(f"Targeting {len(live_buyers)} LIVE_DISCOVERY records for Gemini classification (excluding {len(buyers) - len(live_buyers)} historical/other records).")

    # Validate emails
    valid_live, invalid_live = validate_buyer_records(live_buyers)
    if not valid_live:
        print("All candidate live records failed email validation.")
        print("\n" + "=" * 60)
        print("GEMINI CLASSIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    # Call Gemini classifier
    results, err = classify_live_records(valid_live, api_key=Config.GEMINI_API_KEY)
    if err:
        print(f"ERROR: {err}")
        print("\n" + "=" * 60)
        print("GEMINI CLASSIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    # Append results to classification_log.csv
    log_records = [r.to_dict() for r in results]
    save_classification_log(log_records, csv_path=target_dir / "classification_log.csv", append=True)

    # Update business / individual email lists
    classified_current = load_classified_emails(
        biz_path=target_dir / "business_emails.csv",
        ind_path=target_dir / "individual_emails.csv",
    )
    biz_set = set(classified_current.get("business", []))
    ind_set = set(classified_current.get("individual", []))

    for r in results:
        if r.category == "business":
            biz_set.add(r.email)
        elif r.category == "individual":
            ind_set.add(r.email)

    save_classified_emails(
        business_emails=sorted(list(biz_set)),
        individual_emails=sorted(list(ind_set)),
        biz_path=target_dir / "business_emails.csv",
        ind_path=target_dir / "individual_emails.csv",
    )

    print("\n--- Live Gemini Classification Results ---")
    for idx, r in enumerate(results, 1):
        print(f"\n[{idx}/{len(results)}]")
        print(f"Email                 : {r.email}")
        print(f"Category              : {r.category}")
        print(f"Confidence            : {r.confidence}")
        print(f"Reason                : {r.reason}")
        print(f"Classification Source : {r.classification_source}")
        print(f"Review Required       : {r.review_required}")

    print("\n" + "=" * 60)
    print("GEMINI CLASSIFICATION: LIVE")
    print("GMAIL OUTREACH: DISABLED / TEST MODE")
    print("=" * 60 + "\n")


def run_qualify_live_action(data_dir: Optional[Path] = None, keyword: Optional[str] = None) -> None:
    """
    Execute SAFE AI BUYER QUALIFICATION exclusively for LIVE_DISCOVERY leads.
    Safety invariants:
    - Gmail outreach is strictly DISABLED / TEST MODE
    - Refuses to run if CLASSIFICATION_LIVE is False
    - Refuses to run if GEMINI_API_KEY is missing
    - Strictly filters out HISTORICAL_TEST leads
    - Does NOT fallback to heuristic qualifier on API failure
    """
    target_dir = data_dir or Config.DATA_DIR
    init_data_stores(base_dir=target_dir.parent if target_dir.name == "data" else target_dir)

    print("\n" + "=" * 60)
    print("           SAFE LIVE GEMINI QUALIFICATION")
    print("=" * 60)
    print("GEMINI QUALIFICATION: LIVE")
    print("GMAIL OUTREACH: DISABLED / TEST MODE")
    print("=" * 60 + "\n")

    if not Config.CLASSIFICATION_LIVE:
        print("ERROR: CLASSIFICATION_LIVE is set to false.")
        print("Enable with CLASSIFICATION_LIVE=true in .env to perform live Gemini qualification.")
        print("\n" + "=" * 60)
        print("GEMINI QUALIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    if not Config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY_NOT_CONFIGURED.")
        print("Please configure GEMINI_API_KEY in .env before running live qualification.")
        print("\n" + "=" * 60)
        print("GEMINI QUALIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    # Load buyers and provenance
    buyers = load_buyers(target_dir / "buyers.csv")
    prov_data = load_discovery_provenance(target_dir / "discovery_provenance.json")
    prov_records = prov_data.get("records", {})

    # Select ONLY LIVE_DISCOVERY records
    live_buyers = []
    for b in buyers:
        em = b.get("email", "").strip().lower()
        if em and prov_records.get(em, {}).get("data_source") == "LIVE_DISCOVERY":
            live_buyers.append(b)

    if not live_buyers:
        print("No LIVE_DISCOVERY buyer records found in discovery provenance.")
        print("\n" + "=" * 60)
        print("GEMINI QUALIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    product_target = keyword or Config.SEARCH_KEYWORD or "Export Products"
    print(f"Targeting {len(live_buyers)} LIVE_DISCOVERY records for AI Qualification in product niche: '{product_target}' (excluding {len(buyers) - len(live_buyers)} historical/other records).")

    # Validate emails
    valid_live, invalid_live = validate_buyer_records(live_buyers)
    if not valid_live:
        print("All candidate live records failed email validation.")
        print("\n" + "=" * 60)
        print("GEMINI QUALIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    # Call Gemini qualification
    results, err = qualify_live_buyers(valid_live, product_keyword=product_target, api_key=Config.GEMINI_API_KEY)
    if err:
        print(f"ERROR: {err}")
        print("\n" + "=" * 60)
        print("GEMINI QUALIFICATION: LIVE")
        print("GMAIL OUTREACH: DISABLED / TEST MODE")
        print("=" * 60 + "\n")
        return

    # Save to data/qualification_log.csv
    log_records = [r.to_dict() for r in results]
    save_qualification_log(log_records, csv_path=target_dir / "qualification_log.csv", append=True)

    # Print results in required format
    print("\n" + "=" * 60)
    print("             BUYER QUALIFICATION RESULTS")
    print("=" * 60)

    for r in results:
        comm_signals_str = ", ".join(r.commercial_signals) if isinstance(r.commercial_signals, list) else str(r.commercial_signals)
        evidence_str = "\n  - " + "\n  - ".join(r.evidence) if isinstance(r.evidence, list) else str(r.evidence)

        print(f"\nCompany: {r.company_name or 'UNKNOWN'}")
        print(f"Email: {r.email}")
        print(f"Product: {r.product}")
        print()
        print(f"Business: {r.business_status}")
        print(f"Product relevance: {r.product_relevance:.2f}")
        print(f"Buyer intent: {r.buyer_intent:.2f}")
        print()
        print(f"Commercial signals: {comm_signals_str}")
        print(f"Evidence:{evidence_str}")
        print()
        print(f"Qualification score: {r.qualification_score}")
        print(f"Qualification level: {r.qualification_level}")
        print(f"Recommendation: {r.recommendation}")
        print()
        print(f"Qualification source: {r.qualification_source}")
        print("-" * 60)

    print("=" * 60)
    print("GEMINI QUALIFICATION: LIVE")
    print("GMAIL OUTREACH: DISABLED / TEST MODE")
    print("=" * 60 + "\n")


def run_campaign_preview_action(
    audience: str = "business",
    data_dir: Optional[Path] = None,
    keyword: Optional[str] = None,
) -> Campaign:
    """
    Prepare draft campaign, validate attachment, build recipient previews, and display preview table.
    """
    target_dir = data_dir or Config.DATA_DIR
    mgr = CampaignManager(data_dir=target_dir)
    campaign, previews = mgr.prepare_campaign(target_audience=audience, product_keyword=keyword)
    mgr.display_campaign_preview(campaign, previews)
    return campaign


def run_campaign_approval_action(
    campaign_id: str,
    data_dir: Optional[Path] = None,
) -> None:
    """
    Approve an existing campaign for execution.
    """
    target_dir = data_dir or Config.DATA_DIR
    mgr = CampaignManager(data_dir=target_dir)
    try:
        campaign = mgr.approve_campaign(campaign_id)
        print("\n" + "=" * 60)
        print("             CAMPAIGN APPROVAL CONFIRMATION")
        print("=" * 60)
        print(f"Campaign ID : {campaign.campaign_id}")
        print(f"Audience    : {campaign.target_audience.upper()}")
        print(f"Status      : {campaign.status.value}")
        print(f"Approved At : {campaign.approved_at}")
        print("-" * 60)
        print("Campaign is now APPROVED for execution.")
        print(f"To execute in TEST MODE: python main.py --send --test --campaign-id {campaign.campaign_id}")
        print("=" * 60 + "\n")
    except Exception as e:
        print(f"\n[ERROR] Could not approve campaign '{campaign_id}': {e}\n")


def run_campaign_send_action(
    campaign_id: Optional[str] = None,
    is_test: bool = True,
    audience: str = "business",
    data_dir: Optional[Path] = None,
    keyword: Optional[str] = None,
) -> None:
    """
    Execute an approved campaign. In TEST_MODE (default), simulates email sending safely.
    """
    target_dir = data_dir or Config.DATA_DIR
    mgr = CampaignManager(data_dir=target_dir, test_mode=is_test)
    try:
        result = mgr.execute_campaign(
            campaign_id=campaign_id,
            target_audience=audience,
            force_test_mode=is_test,
            product_keyword=keyword,
        )
        ReportGenerator.print_campaign_report(result)
    except CampaignStateError as cse:
        print(f"\n[APPROVAL GATE BLOCKED]: {cse}\n")
    except AttachmentError as ae:
        print(f"\n[ATTACHMENT SAFETY ABORT]: {ae}\n")
    except Exception as e:
        print(f"\n[CAMPAIGN ERROR]: {e}\n")


def run_campaign_status_action(data_dir: Optional[Path] = None) -> None:
    """
    Display overview of all stored campaigns and recent campaign log metrics.
    """
    target_dir = data_dir or Config.DATA_DIR
    campaigns_file = target_dir / "campaigns.json"
    campaigns = CampaignStore.load_campaigns(campaigns_file)
    camp_audit = audit_campaign_log(target_dir / "campaign_log.csv")

    print("\n" + "=" * 70)
    print("             EXPORT OUTREACH CAMPAIGNS STATUS & AUDIT")
    print("=" * 70)
    print(f"Total Stored Campaigns : {len(campaigns)}")
    print(f"Total Campaign Logs    : {camp_audit['total_records']}")
    print(f"Test-Mode Sends Logged : {camp_audit['test_mode_sends']}")
    print(f"Live Sends Logged      : {camp_audit['live_sends']}")
    print("-" * 70)
    if not campaigns:
        print("No campaigns found in datastore. Run 'python main.py --campaign-preview' to create one.")
    else:
        print(f"{'Campaign ID':<36} | {'Audience':<10} | {'Status':<15} | {'Eligible/Total':<14}")
        print("-" * 70)
        for c in campaigns:
            print(f"{c.campaign_id:<36} | {c.target_audience:<10} | {c.status.value:<15} | {c.eligible_recipients}/{c.total_recipients:<14}")
    print("=" * 70 + "\n")


def run_status_check(data_dir: Optional[Path] = None) -> None:
    """
    Display comprehensive dataset metrics, configuration, and outreach log summary.
    """
    target_dir = data_dir or Config.DATA_DIR
    init_data_stores(base_dir=target_dir.parent if target_dir.name == "data" else target_dir)

    prov_path = target_dir / "discovery_provenance.json"
    buyers_audit = audit_buyers_csv(target_dir / "buyers.csv", provenance_path=prov_path)
    sent_audit = audit_sent_log(target_dir / "sent_log.csv")
    classification_audit = audit_classification_log(target_dir / "classification_log.csv")
    qualification_audit = audit_qualification_log(target_dir / "qualification_log.csv")
    review_audit = audit_lead_review_log(target_dir / "lead_review_log.csv")
    campaign_audit = audit_campaign_log(target_dir / "campaign_log.csv")
    classified = load_classified_emails(
        biz_path=target_dir / "business_emails.csv",
        ind_path=target_dir / "individual_emails.csv",
    )

    print("\n" + "=" * 60)
    print("          EXPORT AUTOMATION SYSTEM STATUS & AUDIT")
    print("=" * 60)
    print(f"Configured Keyword   : {Config.SEARCH_KEYWORD}")
    print(f"Last Discovery Run   : {buyers_audit['last_discovery_keyword']}")
    print(f"Execution Mode       : {'TEST MODE (Simulated Outreach)' if Config.TEST_MODE else 'LIVE OUTREACH'}")
    print(f"Discovery Mode       : {'TEST DISCOVERY' if Config.TEST_DISCOVERY else 'LIVE WEB DISCOVERY'}")
    print(f"Daily Send Limit     : {Config.DAILY_SEND_LIMIT}")
    print(f"Test Simulation Limit: {Config.TEST_SIMULATION_LIMIT}")
    print(f"Classification Batch : {Config.CLASSIFICATION_BATCH_SIZE}")
    print(f"Review Threshold     : {Config.CLASSIFICATION_REVIEW_THRESHOLD}")
    print("-" * 60)
    print("Buyers Store (data/buyers.csv):")
    print(f"  - Total Buyers          : {buyers_audit['total_records']}")
    print(f"  - Historical/Test Buyers: {buyers_audit['historical_test_count']}")
    print(f"  - Live Discovery Buyers : {buyers_audit['live_discovery_count']}")
    print(f"  - User Uploaded Buyers  : {buyers_audit['user_upload_count']}")
    print(f"  - Unique Emails         : {buyers_audit['unique_emails']}")
    print(f"  - Duplicate Emails      : {buyers_audit['duplicate_emails']}")
    print("  - Platform Distribution :")
    for plat, count in buyers_audit["platform_distribution"].items():
        print(f"      * {plat:<20}: {count}")
    print("  - Field Completeness    :")
    print(f"      * Missing Company   : {buyers_audit['missing_company']}")
    print(f"      * Missing Country   : {buyers_audit['missing_country']}")
    print(f"      * Missing Website   : {buyers_audit['missing_website']}")
    print(f"      * Missing Buyer Name: {buyers_audit['missing_buyer_name']}")
    print("-" * 60)
    print("Classified Audience Lists & Audit:")
    print(f"  - Business Emails (B2B) : {len(classified['business'])}")
    print(f"  - Individual Emails     : {len(classified['individual'])}")
    print(f"  - Classification Logs   : {classification_audit['total_records']}")
    print(f"  - Classification Engine : {'LOCAL TEST CLASSIFIER (Rule-based Heuristic)' if not Config.is_gemini_available() else 'LIVE GEMINI ACTIVE'}")
    print(f"  - Review Required (Flag): {classification_audit['review_required_count']}")
    print("-" * 60)
    print("Buyer Qualification Audit (data/qualification_log.csv):")
    print(f"  - Total Qualified Logs  : {qualification_audit['total_records']}")
    print(f"  - HIGH Qualified Leads  : {qualification_audit['high_count']}")
    print(f"  - MEDIUM Qualified Leads: {qualification_audit['medium_count']}")
    print(f"  - LOW Qualified Leads   : {qualification_audit['low_count']}")
    print(f"  - Review Required Flags : {qualification_audit['review_required_count']}")
    print(f"  - Recommendations Break : {qualification_audit['recommendations']}")
    print("-" * 60)
    print("Human Lead Review Audit (data/lead_review_log.csv):")
    print(f"  - Total Human Decisions : {review_audit['total_reviews']}")
    print(f"  - Approved for Campaign : {review_audit['approved']}")
    print(f"  - Rejected Leads        : {review_audit['rejected']}")
    print(f"  - Manual Review Reqs    : {review_audit['manual_review_requested']}")
    print(f"  - Pending Decisions     : {review_audit['pending']}")
    print("-" * 60)
    print("Campaign & Outreach Logs (data/campaign_log.csv & sent_log.csv):")
    print(f"  - Real Sends Today          : {sent_audit.get('real_sends_today', 0)} / {Config.DAILY_SEND_LIMIT}")
    print(f"  - TEST_MODE Sims Today      : {sent_audit.get('test_simulations_today', 0)} / {Config.TEST_SIMULATION_LIMIT}")
    print(f"  - Total Historical Test Sims: {sent_audit.get('total_test_simulations', sent_audit['test_mode_records'])}")
    print(f"  - Total Real Sends          : {sent_audit.get('total_real_sends', sent_audit['successful_sends'])}")
    print(f"  - Total Campaign Attempts   : {campaign_audit['total_records']}")
    print(f"  - Live Failed Sends         : {sent_audit['failed_sends']}")
    print(f"  - Unique Simulated Targets  : {sent_audit['unique_simulated_recipients']}")
    print(f"  - Unique Live Contacted     : {sent_audit['unique_live_contacted']}")
    print("-" * 60)
    print("Infrastructure & Readiness:")
    print(f"  - Presentation File     : {Config.PRESENTATION_PATH} ({'Found' if Config.get_presentation_file_path().exists() else 'MISSING'})")
    print(f"  - Gemini API            : {'LIVE GEMINI 2.5 ACTIVE' if Config.is_gemini_available() else 'LOCAL TEST CLASSIFIER'}")
    print(f"  - SMTP Status           : {'LIVE SMTP READY' if Config.is_live_gmail_ready() else 'DISABLED / TEST MODE (Protected)'}")
    print("=" * 60 + "\n")


def run_pipeline(
    keyword: Optional[str] = None,
    test_mode: Optional[bool] = None,
    daily_limit: Optional[int] = None,
) -> RunMetrics:
    """
    Execute complete 7-stage automated export discovery and outreach pipeline.
    """
    search_keyword = keyword or Config.SEARCH_KEYWORD
    is_test_mode = Config.TEST_MODE if test_mode is None else test_mode
    send_limit = Config.DAILY_SEND_LIMIT if daily_limit is None else daily_limit

    metrics = RunMetrics(start_time=datetime.now(timezone.utc).isoformat())

    print("\n" + "=" * 50)
    print("      API 3 - EXPORT AUTOMATION SYSTEM")
    print("=" * 50)
    print(f"Target Keyword : {search_keyword}")
    print(f"Mode           : {'TEST MODE (SIMULATED OUTREACH)' if is_test_mode else 'LIVE OUTREACH'}")
    print(f"Daily Limit    : {send_limit}")
    print("=" * 50 + "\n")

    # -------------------------------------------------------------
    # [1/7] Database Initialization
    # -------------------------------------------------------------
    print("[1/7] Initializing data stores...")
    init_data_stores()

    # -------------------------------------------------------------
    # [2/7] Buyer Discovery
    # -------------------------------------------------------------
    print(f"[2/7] Running buyer discovery for '{search_keyword}'...")
    raw_results = []

    # Google Search Adapter
    google_adapter = GoogleSearchAdapter(max_results=Config.MAX_SEARCH_RESULTS, test_discovery=Config.TEST_DISCOVERY)
    google_results = google_adapter.search(search_keyword)
    raw_results.extend(google_results)

    # Social & Directory Stubs
    raw_results.extend(FacebookSearchAdapter().search(search_keyword))
    raw_results.extend(LinkedInSearchAdapter().search(search_keyword))
    raw_results.extend(DirectorySearchAdapter().search(search_keyword))

    # Website Deep Crawl
    web_adapter = WebsiteSearchAdapter(max_websites=Config.MAX_WEBSITES_PER_RESULT, test_discovery=Config.TEST_DISCOVERY)
    external_urls = [r["url"] for r in google_results if r.get("url") and r["url"].startswith("http")]
    if external_urls:
        web_results = web_adapter.crawl_and_extract(external_urls[:Config.MAX_WEBSITES_PER_RESULT], keyword=search_keyword)
        raw_results.extend(web_results)

    # Filter by product and buyer relevance
    accepted_results = []
    for item in raw_results:
        audit = evaluate_result_relevance(item, keyword=search_keyword, query=item.get("query", ""))
        if audit.decision == "ACCEPT":
            accepted_results.append(item)

    discovered_buyers = extract_buyers_from_search_results(accepted_results, product_keyword=search_keyword)
    metrics.total_buyers_discovered = len(discovered_buyers)

    # -------------------------------------------------------------
    # [3/7] Email Validation
    # -------------------------------------------------------------
    print("[3/7] Validating emails...")
    valid_buyers, invalid_buyers = validate_buyer_records(discovered_buyers)
    metrics.valid_emails = len(valid_buyers)
    metrics.invalid_emails = len(invalid_buyers)

    # -------------------------------------------------------------
    # [4/7] Deduplication & Persistence
    # -------------------------------------------------------------
    print("[4/7] Deduplicating & saving buyer records...")
    existing_buyers = load_buyers()
    existing_emails = {b["email"].lower() for b in existing_buyers if b.get("email")}

    unique_new_buyers = []
    duplicate_count = 0

    seen_in_batch = set()
    for b in valid_buyers:
        em = b["email"].lower()
        if em in seen_in_batch or em in existing_emails:
            duplicate_count += 1
        else:
            seen_in_batch.add(em)
            unique_new_buyers.append(b)

    metrics.duplicate_contacts = duplicate_count
    save_buyers(unique_new_buyers, append=True)
    logger.info(f"Duplicate filtering complete: {len(unique_new_buyers)} unique new contacts ({duplicate_count} duplicates avoided).")

    # -------------------------------------------------------------
    # [5/7] AI Classification
    # -------------------------------------------------------------
    print("[5/7] AI classification...")
    buyers_to_classify = unique_new_buyers if unique_new_buyers else valid_buyers
    classification_results = classify_contacts_detailed(
        buyers_to_classify,
        force_heuristic=is_test_mode or not Config.GEMINI_API_KEY,
    )

    biz_emails = [r.email for r in classification_results if r.category == "business"]
    ind_emails = [r.email for r in classification_results if r.category == "individual"]

    metrics.business_contacts = len(biz_emails)
    metrics.individual_contacts = len(ind_emails)

    save_classified_emails(biz_emails, ind_emails)
    save_classification_log([r.to_dict() for r in classification_results], append=True)

    # -------------------------------------------------------------
    # [6/7] Outreach
    # -------------------------------------------------------------
    print("[6/7] Outreach...")
    sender = GmailSender(
        test_mode=is_test_mode,
        daily_limit=send_limit,
    )

    target_buyers = [b for b in buyers_to_classify if b.get("email", "").lower() in biz_emails]
    if not target_buyers:
        target_buyers = buyers_to_classify

    metrics.total_queued = len(target_buyers)
    send_results = sender.send_campaign(target_buyers)

    for r in send_results:
        if r.is_simulated:
            metrics.test_mode_sends += 1
        elif r.status == "SUCCESS":
            metrics.successful_sends += 1
        else:
            metrics.failed_sends += 1

    # -------------------------------------------------------------
    # [7/7] Report
    # -------------------------------------------------------------
    print("[7/7] Report...")
    metrics.end_time = datetime.now(timezone.utc).isoformat()
    report_gen = ReportGenerator(metrics)
    report_gen.print_console_summary()

    return metrics


# -----------------------------------------------------------------
# Planned Web Interface Routes Architecture Specification
# -----------------------------------------------------------------
WEB_ROUTES_SPECIFICATION = {
    "/": "Dashboard overview of discovery stats, historical sends, and campaign status.",
    "/upload": "Upload CSV/Excel contact lists for validation and pipeline ingestion.",
    "/classify": "Run on-demand AI classification on loaded contacts.",
    "/send": "Trigger batch outreach campaign with safety confirmations.",
    "/report": "View analytical reports, delivery statistics, and engagement logs.",
    "/settings": "Configure search keywords, daily limits, and API keys securely.",
    "/download-report": "Export run summaries and sent logs as downloadable CSV files.",
}


def main():
    parser = argparse.ArgumentParser(
        description="API 3 - EXPORT Automation System: Discovery, Classification & Outreach Pipeline"
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Execute only the Phase 2 Buyer Discovery pipeline"
    )
    parser.add_argument(
        "--classify",
        action="store_true",
        help="Execute standalone Phase 3 AI Lead Classification"
    )
    parser.add_argument(
        "--classify-live",
        action="store_true",
        help="Execute SAFE live Gemini classification strictly for LIVE_DISCOVERY leads"
    )
    parser.add_argument(
        "--qualify-live",
        action="store_true",
        help="Execute SAFE AI Buyer Qualification strictly for LIVE_DISCOVERY leads"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Audit and validate email records in data/buyers.csv"
    )
    parser.add_argument(
        "--campaign-preview",
        action="store_true",
        help="Prepare a draft outreach campaign and view personalized recipient preview"
    )
    parser.add_argument(
        "--approve-campaign",
        type=str,
        default=None,
        metavar="CAMPAIGN_ID",
        help="Approve a prepared campaign for execution by ID"
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Execute outreach campaign for approved campaign"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Enforce TEST_MODE dry-run simulation when sending (safe mock send)"
    )
    parser.add_argument(
        "--campaign-status",
        action="store_true",
        help="Display status summary of all stored campaigns"
    )
    parser.add_argument(
        "--audience",
        type=str,
        default="business",
        choices=["business", "individual", "all"],
        help="Target audience for campaign (default: business)"
    )
    parser.add_argument(
        "--campaign-id",
        type=str,
        default=None,
        help="Specific campaign ID to execute"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display dataset statistics and environment status"
    )
    parser.add_argument(
        "--keyword",
        type=str,
        default=None,
        help="Export product keyword to search for (e.g. 'Singing Bowls', 'Handmade Pashmina')"
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        default=None,
        help="Enforce TEST_MODE simulation (no real emails sent)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of items to process or send"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Custom datastore directory path for isolated test execution"
    )
    parser.add_argument(
        "--routes-info",
        action="store_true",
        help="Display planned web interface routing architecture"
    )

    args = parser.parse_args()

    custom_data_dir = Path(args.data_dir).resolve() if args.data_dir else None

    if args.routes_info:
        print("\nPlanned Web Interface Routes Architecture:")
        print("-" * 50)
        for route, desc in WEB_ROUTES_SPECIFICATION.items():
            print(f"  {route:<18} : {desc}")
        print("-" * 50 + "\n")
        return

    if args.status:
        run_status_check(data_dir=custom_data_dir)
        return

    if args.campaign_status:
        run_campaign_status_action(data_dir=custom_data_dir)
        return

    if args.validate:
        run_validation_check(csv_path=custom_data_dir / "buyers.csv" if custom_data_dir else None)
        return

    if args.discover:
        run_discovery_only(
            keyword=args.keyword,
            max_results=args.limit,
            data_dir=custom_data_dir,
        )
        return

    if args.classify:
        run_classification_only(
            data_dir=custom_data_dir,
            batch_size=args.limit,
        )
        return

    if args.classify_live:
        run_classify_live_action(data_dir=custom_data_dir)
        return

    if args.qualify_live:
        run_qualify_live_action(data_dir=custom_data_dir, keyword=args.keyword)
        return

    if args.campaign_preview:
        run_campaign_preview_action(
            audience=args.audience,
            data_dir=custom_data_dir,
            keyword=args.keyword,
        )
        return

    if args.approve_campaign:
        run_campaign_approval_action(
            campaign_id=args.approve_campaign,
            data_dir=custom_data_dir,
        )
        return

    if args.send:
        # Enforce TEST_MODE unless explicitly configured otherwise
        is_test = True if args.test or Config.TEST_MODE else False
        run_campaign_send_action(
            campaign_id=args.campaign_id,
            is_test=is_test,
            audience=args.audience,
            data_dir=custom_data_dir,
            keyword=args.keyword,
        )
        return

    run_pipeline(
        keyword=args.keyword,
        test_mode=args.test_mode,
        daily_limit=args.limit,
    )


if __name__ == "__main__":
    main()
