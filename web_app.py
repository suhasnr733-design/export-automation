"""
Flask Web Application for API 3 - EXPORT Automation System.
Professional Dashboard for International Buyer Outreach, AI Classification,
and Safe Campaign Management.
"""

import io
import os
import csv
import uuid
import secrets
import logging
from pathlib import Path
from collections import Counter
from typing import Dict, Any, List, Optional

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    Response,
    abort,
    jsonify,
)
from werkzeug.utils import secure_filename

from config import Config
from app_logging.activity_logger import (
    init_data_stores,
    load_buyers,
    save_buyers,
    audit_buyers_csv,
    load_classified_emails,
    save_classified_emails,
    audit_classification_log,
    load_classification_log,
    load_qualification_log,
    save_qualification_log,
    load_discovery_provenance,
    save_lead_review_decision,
    load_lead_review_log,
    get_lead_review_statuses,
    audit_lead_review_log,
    load_sent_log,
    audit_sent_log,
    load_campaign_log,
    audit_campaign_log,
)
from validation.email_validator import (
    validate_single_email,
    validate_buyer_records,
    normalize_email,
)
from classification import run_classification_pipeline
from outreach.campaign_model import CampaignStatus, CampaignStore, Campaign
from outreach.campaign_manager import CampaignManager, CampaignStateError
from outreach.attachment_handler import AttachmentHandler, AttachmentError
from outreach.personalization import PersonalizationEngine
from reports.report_generator import ReportGenerator

# Setup Flask Application
app = Flask(__name__)
app.secret_key = "export-automation-b2b-secret-key-2026"
app.config["SESSION_COOKIE_DOMAIN"] = False

# In-memory staging cache for CSV file uploads before explicit confirmation
STAGED_UPLOADS: Dict[str, Dict[str, Any]] = {}

# Ensure datastores exist on application start
init_data_stores()


def _mask_email(email_str: str) -> str:
    """Mask email address for safe rendering in public UI views."""
    if not email_str or "@" not in email_str:
        return "Not configured"
    parts = email_str.split("@")
    user, domain = parts[0], parts[1]
    if len(user) <= 2:
        masked_user = user[0] + "*"
    else:
        masked_user = user[:2] + "*" * (len(user) - 2)
    return f"{masked_user}@{domain}"


@app.context_processor
def inject_global_data():
    """Inject safe global configuration and system health data into all Jinja2 templates."""
    attachment_handler = AttachmentHandler(Config.PRESENTATION_PATH)
    meta = attachment_handler.get_metadata()

    # Masked config object (never expose passwords or API keys)
    safe_config = {
        "TEST_MODE": Config.TEST_MODE,
        "SEARCH_KEYWORD": Config.SEARCH_KEYWORD,
        "DAILY_SEND_LIMIT": Config.DAILY_SEND_LIMIT,
        "SEND_DELAY": Config.SEND_DELAY,
        "MAX_SEARCH_RESULTS": Config.MAX_SEARCH_RESULTS,
        "MAX_WEBSITES_PER_RESULT": Config.MAX_WEBSITES_PER_RESULT,
        "SEARCH_DELAY": Config.SEARCH_DELAY,
        "CLASSIFICATION_BATCH_SIZE": Config.CLASSIFICATION_BATCH_SIZE,
        "CLASSIFICATION_REVIEW_THRESHOLD": Config.CLASSIFICATION_REVIEW_THRESHOLD,
        "CC_MONITOR_EMAIL": Config.CC_MONITOR_EMAIL,
        "PRESENTATION_PATH": str(Config.PRESENTATION_PATH),
        "EXECUTION_MODE": "TEST MODE (Simulated Outreach)" if Config.TEST_MODE else "LIVE GMAIL SMTP",
    }

    is_gmail_ready = bool(Config.GMAIL_SENDER_EMAIL and Config.GMAIL_APP_PASSWORD)
    is_gemini_ready = bool(Config.GEMINI_API_KEY)

    return {
        "config_data": safe_config,
        "attachment_meta": meta,
        "is_gmail_ready": is_gmail_ready,
        "is_gemini_ready": is_gemini_ready,
        "masked_sender": _mask_email(Config.GMAIL_SENDER_EMAIL),
    }


# ==============================================================================
# 0. SYSTEM HEALTH CHECK (Route: /health)
# ==============================================================================
@app.route("/health")
def health():
    """Lightweight health-check endpoint for load balancers, orchestrators, and uptime probes."""
    return jsonify({
        "status": "healthy",
        "test_mode": Config.TEST_MODE,
        "service": "api3-export-automation",
        "version": "3.0",
    }), 200


# ==============================================================================
# 1. DASHBOARD OVERVIEW (Route: /)
# ==============================================================================
@app.route("/")
def dashboard():
    """Main executive dashboard displaying real-time lead KPIs, health, and campaign metrics."""
    buyers_audit = audit_buyers_csv(Config.BUYERS_CSV)
    classified_emails = load_classified_emails(biz_path=Config.BUSINESS_EMAILS_CSV, ind_path=Config.INDIVIDUAL_EMAILS_CSV)
    sent_audit = audit_sent_log(Config.SENT_LOG_CSV)
    campaign_audit = audit_campaign_log(Config.CAMPAIGN_LOG_CSV)
    campaigns = CampaignStore.load_campaigns(Config.CAMPAIGNS_FILE)

    # Country distribution from raw buyers
    buyers = load_buyers(Config.BUYERS_CSV)
    country_counts = Counter(b.get("country", "Unknown") for b in buyers if b.get("country"))
    top_countries = dict(country_counts.most_common(5))

    latest_campaign = campaigns[0] if campaigns else None

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        buyers_audit=buyers_audit,
        classified_emails=classified_emails,
        sent_audit=sent_audit,
        campaign_audit=campaign_audit,
        campaigns=campaigns,
        country_dist=top_countries,
        latest_campaign=latest_campaign,
    )


# ==============================================================================
# 2. BUYERS DATASET (Route: /buyers)
# ==============================================================================
@app.route("/buyers")
def buyers_list():
    """Display discovered buyer contacts table enriched with classification status."""
    buyers = load_buyers(Config.BUYERS_CSV)
    classified_emails = load_classified_emails(biz_path=Config.BUSINESS_EMAILS_CSV, ind_path=Config.INDIVIDUAL_EMAILS_CSV)
    classification_logs = load_classification_log(Config.CLASSIFICATION_LOG_CSV)

    # Map category and confidence to buyer email
    cat_map = {}
    for log in classification_logs:
        em = normalize_email(log.get("email", ""))
        if em:
            cat_map[em] = {
                "category": log.get("category", "unclassified"),
                "confidence": float(log.get("confidence", 0.8)),
            }

    biz_set = set(classified_emails["business"])
    ind_set = set(classified_emails["individual"])

    enriched_buyers = []
    for b in buyers:
        em = normalize_email(b.get("email", ""))
        category = "unclassified"
        confidence = 0.5

        if em in cat_map:
            category = cat_map[em]["category"]
            confidence = cat_map[em]["confidence"]
        elif em in biz_set:
            category = "business"
            confidence = 0.85
        elif em in ind_set:
            category = "individual"
            confidence = 0.85

        enriched_buyers.append({
            **b,
            "category": category,
            "confidence": confidence,
        })

    return render_template(
        "buyers.html",
        active_page="buyers",
        buyers=enriched_buyers,
    )


# ==============================================================================
# 3. CSV LEAD UPLOAD (Route: /upload & /upload/confirm)
# ==============================================================================
@app.route("/upload", methods=["GET", "POST"])
def upload_buyers():
    """Handle CSV spreadsheet upload, schema validation, and duplicate checking."""
    preview_data = None

    if request.method == "POST":
        if "csv_file" not in request.files:
            flash("No file was uploaded.", "error")
            return redirect(url_for("upload_buyers"))

        file = request.files["csv_file"]
        if not file or file.filename == "":
            flash("Please select a valid CSV file.", "error")
            return redirect(url_for("upload_buyers"))

        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".csv"):
            flash("Invalid file format. Please upload a standard .csv file.", "error")
            return redirect(url_for("upload_buyers"))

        try:
            content_str = file.read().decode("utf-8-sig", errors="replace")
            csv_reader = csv.DictReader(io.StringIO(content_str))

            if not csv_reader.fieldnames or "email" not in [f.strip().lower() for f in csv_reader.fieldnames]:
                flash("CSV must contain at least an 'email' column header.", "error")
                return redirect(url_for("upload_buyers"))

            # Normalize column headers
            raw_rows = []
            for row in csv_reader:
                cleaned_row = {}
                for k, v in row.items():
                    if k:
                        cleaned_row[k.strip().lower()] = (v or "").strip()
                raw_rows.append({
                    "buyer_name": cleaned_row.get("buyer_name", cleaned_row.get("name", "")),
                    "company_name": cleaned_row.get("company_name", cleaned_row.get("company", "")),
                    "email": cleaned_row.get("email", ""),
                    "website": cleaned_row.get("website", cleaned_row.get("url", "")),
                    "country": cleaned_row.get("country", ""),
                    "source_platform": cleaned_row.get("source_platform", "CSV Upload"),
                })

            # Check existing buyers to calculate duplicates
            existing_buyers = load_buyers(Config.BUYERS_CSV)
            existing_emails = {normalize_email(b["email"]) for b in existing_buyers if b.get("email")}

            valid_records, invalid_count = validate_buyer_records(raw_rows)

            new_valid_records = []
            duplicate_count = 0
            seen_in_upload = set()

            for rec in valid_records:
                norm_em = normalize_email(rec["email"])
                if norm_em in existing_emails or norm_em in seen_in_upload:
                    duplicate_count += 1
                else:
                    seen_in_upload.add(norm_em)
                    new_valid_records.append(rec)

            # Store in staging cache with unique token
            token = str(uuid.uuid4())
            STAGED_UPLOADS[token] = {
                "records": new_valid_records,
                "filename": filename,
            }

            preview_data = {
                "token": token,
                "filename": filename,
                "total_rows": len(raw_rows),
                "new_valid_records": new_valid_records,
                "duplicate_count": duplicate_count,
                "invalid_count": invalid_count,
            }

        except Exception as e:
            flash(f"Error parsing CSV file: {str(e)}", "error")
            return redirect(url_for("upload_buyers"))

    return render_template(
        "upload.html",
        active_page="upload",
        preview_data=preview_data,
    )


@app.route("/upload/confirm", methods=["POST"])
def confirm_upload():
    """Persist staged CSV upload records to data/buyers.csv after user confirmation."""
    token = request.form.get("upload_token")
    if not token or token not in STAGED_UPLOADS:
        flash("Staged upload expired or invalid. Please re-upload.", "error")
        return redirect(url_for("upload_buyers"))

    staged = STAGED_UPLOADS.pop(token)
    records_to_add = staged.get("records", [])

    if records_to_add:
        save_buyers(records_to_add, csv_path=Config.BUYERS_CSV, append=True)
        flash(f"Successfully merged {len(records_to_add)} new buyer leads into buyers.csv.", "success")
    else:
        flash("No new valid records to merge.", "warning")

    return redirect(url_for("buyers_list"))


# ==============================================================================
# 4. AI CLASSIFICATION (Route: /classify & /classify/run)
# ==============================================================================
@app.route("/classify")
def classify_view():
    """Display lead classification metrics, configuration status, and audit log."""
    buyers = load_buyers(Config.BUYERS_CSV)
    classified_emails = load_classified_emails(biz_path=Config.BUSINESS_EMAILS_CSV, ind_path=Config.INDIVIDUAL_EMAILS_CSV)
    logs = load_classification_log(Config.CLASSIFICATION_LOG_CSV)

    biz_count = len(classified_emails["business"])
    ind_count = len(classified_emails["individual"])
    review_count = sum(1 for l in logs if str(l.get("review_required", "")).lower() in ("true", "1", "yes"))

    return render_template(
        "classify.html",
        active_page="classify",
        total_buyers=len(buyers),
        biz_count=biz_count,
        ind_count=ind_count,
        review_count=review_count,
        classification_logs=logs,
    )


@app.route("/classify/run", methods=["POST"])
def run_classification_action():
    """Execute AI classification pipeline on buyer dataset."""
    try:
        summary = run_classification_pipeline(
            buyers_path=Config.BUYERS_CSV,
            biz_path=Config.BUSINESS_EMAILS_CSV,
            ind_path=Config.INDIVIDUAL_EMAILS_CSV,
            log_path=Config.CLASSIFICATION_LOG_CSV,
            force_test_mode=Config.TEST_MODE,
        )
        flash(
            f"AI Classification Complete! Processed {summary['total_records']} contacts: "
            f"{summary['business_count']} Business (B2B), {summary['individual_count']} Individual.",
            "success"
        )
    except Exception as e:
        flash(f"Classification failed: {str(e)}", "error")

    return redirect(url_for("classify_view"))


# ==============================================================================
# 5. HUMAN LEAD REVIEW & CAMPAIGN PREVIEW (Route: /review, /review/decision, /review/preview)
# ==============================================================================
@app.route("/review")
def review_view():
    """Display qualified leads for explicit human review before outreach approval."""
    buyers = load_buyers(Config.BUYERS_CSV)
    prov_data = load_discovery_provenance(Config.DISCOVERY_PROVENANCE_FILE)
    prov_records = prov_data.get("records", {})

    # Filter strictly for LIVE_DISCOVERY leads
    live_buyers = []
    for b in buyers:
        em = b.get("email", "").strip().lower()
        if em and prov_records.get(em, {}).get("data_source") == "LIVE_DISCOVERY":
            live_buyers.append(b)

    # Load qualification log
    qual_logs = load_qualification_log(Config.QUALIFICATION_LOG_CSV)
    qual_by_email = {q["email"].strip().lower(): q for q in qual_logs if q.get("email")}

    # Load classification log
    class_logs = load_classification_log(Config.CLASSIFICATION_LOG_CSV)
    class_by_email = {c["email"].strip().lower(): c for c in class_logs if c.get("email")}

    # Load human review decisions
    review_statuses = get_lead_review_statuses(Config.LEAD_REVIEW_LOG_CSV)

    candidates = []
    for b in live_buyers:
        em = b["email"].strip().lower()
        qual = qual_by_email.get(em, {})
        class_rec = class_by_email.get(em, {})
        rev = review_statuses.get(em, {})

        # Handle Country Safely: Never guess missing country
        country_raw = b.get("country", "").strip()
        if not country_raw or country_raw.upper() in ("UNKNOWN", "NONE", "N/A", ""):
            country_display = "Unknown — Verification Required"
            is_country_unknown = True
        else:
            country_display = country_raw
            is_country_unknown = False

        # Parse commercial signals & evidence
        raw_signals = qual.get("commercial_signals", "")
        signals = [s.strip() for s in (raw_signals.split(";") if ";" in raw_signals else raw_signals.split(",")) if s.strip()]
        if not signals:
            signals = ["UNKNOWN"]

        raw_evidence = qual.get("evidence", "")
        evidence_list = [e.strip() for e in (raw_evidence.split(";") if ";" in raw_evidence else raw_evidence.split("\n")) if e.strip()]
        if not evidence_list:
            evidence_list = ["No automated evidence logged. Manual inspection recommended."]

        try:
            score = int(qual.get("qualification_score", 50))
        except (ValueError, TypeError):
            score = 50

        try:
            prod_rel = float(qual.get("product_relevance", 0.5))
        except (ValueError, TypeError):
            prod_rel = 0.5

        try:
            b_intent = float(qual.get("buyer_intent", 0.5))
        except (ValueError, TypeError):
            b_intent = 0.5

        # Review status defaults to PENDING_REVIEW
        status = rev.get("review_status", "PENDING_REVIEW").strip().upper()
        if status not in ("APPROVED", "REJECTED", "MANUAL_REVIEW_REQUESTED"):
            status = "PENDING_REVIEW"

        candidates.append({
            "buyer": b,
            "email": b["email"],
            "company_name": b.get("company_name", "Unknown Company"),
            "website": b.get("website", ""),
            "country_display": country_display,
            "is_country_unknown": is_country_unknown,
            "product": qual.get("product", Config.SEARCH_KEYWORD or "Export Products"),
            "business_status": qual.get("business_status", class_rec.get("category", "business")),
            "confidence": class_rec.get("confidence", "0.95"),
            "buyer_intent": b_intent,
            "commercial_signals": signals,
            "product_relevance": prod_rel,
            "qualification_score": score,
            "qualification_level": qual.get("qualification_level", "HIGH" if score >= 75 else ("MEDIUM" if score >= 50 else "LOW")),
            "recommendation": qual.get("recommendation", "REVIEW_FOR_OUTREACH" if score >= 75 else "MANUAL_REVIEW"),
            "evidence": evidence_list,
            "qualification_source": qual.get("qualification_source", "GEMINI"),
            "classification_source": qual.get("classification_source", "GEMINI"),
            "review_status": status,
            "reviewer_decision": rev.get("reviewer_decision", "Pending Decision"),
            "review_timestamp": rev.get("review_timestamp", ""),
            "review_notes": rev.get("notes", ""),
        })

    # Sort candidates prioritizing qualification_level=HIGH and recommendation=REVIEW_FOR_OUTREACH
    def sort_key(c):
        is_high_outreach = (c["qualification_level"] == "HIGH" and c["recommendation"] == "REVIEW_FOR_OUTREACH")
        return (not is_high_outreach, -c["qualification_score"])

    candidates.sort(key=sort_key)

    review_audit = audit_lead_review_log(Config.LEAD_REVIEW_LOG_CSV)

    return render_template(
        "review.html",
        active_page="review",
        candidates=candidates,
        total_candidates=len(candidates),
        review_audit=review_audit,
    )


@app.route("/review/decision", methods=["POST"])
def submit_lead_review_decision():
    """Record human review decision for a candidate lead."""
    email = request.form.get("email", "").strip().lower()
    company_name = request.form.get("company_name", "").strip()
    decision = request.form.get("decision", "").strip().lower()
    notes = request.form.get("notes", "").strip()
    score = request.form.get("qualification_score", "0")
    recommendation = request.form.get("recommendation", "")

    if not email:
        flash("Email address is required for lead review.", "error")
        return redirect(url_for("review_view"))

    if decision == "approve":
        status = "APPROVED"
        decision_label = "Approve for Campaign"
        flash_msg = f"Lead '{email}' ({company_name}) has been APPROVED for outreach."
        flash_type = "success"
    elif decision == "reject":
        status = "REJECTED"
        decision_label = "Reject"
        flash_msg = f"Lead '{email}' ({company_name}) has been REJECTED."
        flash_type = "warning"
    elif decision in ("manual_review", "request_review"):
        status = "MANUAL_REVIEW_REQUESTED"
        decision_label = "Request Manual Review"
        flash_msg = f"Lead '{email}' ({company_name}) marked for MANUAL REVIEW."
        flash_type = "info"
    else:
        flash(f"Invalid review decision '{decision}'.", "error")
        return redirect(url_for("review_view"))

    record = {
        "email": email,
        "company_name": company_name,
        "qualification_score": score,
        "recommendation": recommendation,
        "review_status": status,
        "reviewer_decision": decision_label,
        "notes": notes,
    }
    save_lead_review_decision(record, csv_path=Config.LEAD_REVIEW_LOG_CSV)
    flash(flash_msg, flash_type)
    return redirect(url_for("review_view"))


@app.route("/review/preview")
def review_campaign_preview():
    """Preview personalized outreach email for an APPROVED lead only (strictly no sending)."""
    email = request.args.get("email", "").strip().lower()
    if not email:
        flash("Target email required for preview.", "error")
        return redirect(url_for("review_view"))

    # Verify review status is APPROVED
    review_statuses = get_lead_review_statuses(Config.LEAD_REVIEW_LOG_CSV)
    lead_status = review_statuses.get(email, {}).get("review_status", "PENDING_REVIEW")

    if lead_status != "APPROVED":
        flash(
            f"Campaign preview is only available for leads with APPROVED human review status (Current: {lead_status}).",
            "warning",
        )
        return redirect(url_for("review_view"))

    # Load buyer record
    buyers = load_buyers(Config.BUYERS_CSV)
    target_buyer = next((b for b in buyers if b.get("email", "").strip().lower() == email), None)
    if not target_buyer:
        flash(f"Buyer record for '{email}' not found.", "error")
        return redirect(url_for("review_view"))

    # Load template and render preview
    raw_template = PersonalizationEngine.load_template_file(Config.DEFAULT_TEMPLATE_PATH)
    subject, body = PersonalizationEngine.render_email(
        buyer=target_buyer,
        template_text=raw_template,
        product_keyword=Config.SEARCH_KEYWORD,
    )

    # Attachment validation
    handler = AttachmentHandler(Config.PRESENTATION_PATH)
    att_meta = handler.get_metadata()

    # Country check
    country_raw = target_buyer.get("country", "").strip()
    is_country_unknown = not country_raw or country_raw.upper() in ("UNKNOWN", "NONE", "N/A", "")
    country_display = "Unknown — Verification Required" if is_country_unknown else country_raw

    return render_template(
        "review_preview.html",
        active_page="review",
        buyer=target_buyer,
        email=email,
        company_name=target_buyer.get("company_name", "Unknown Company"),
        country_display=country_display,
        is_country_unknown=is_country_unknown,
        subject=subject,
        body=body,
        attachment_meta=att_meta,
        review_record=review_statuses.get(email, {}),
    )


@app.route("/review/create-campaign", methods=["POST"])
def create_campaign_for_approved_lead():
    """Create a staged campaign in READY_FOR_REVIEW status for an approved lead."""
    email = request.form.get("email", "").strip().lower()
    if not email:
        flash("Email address required.", "error")
        return redirect(url_for("review_view"))

    # Verify review status is APPROVED
    review_statuses = get_lead_review_statuses(Config.LEAD_REVIEW_LOG_CSV)
    lead_status = review_statuses.get(email, {}).get("review_status", "PENDING_REVIEW")

    if lead_status != "APPROVED":
        flash(
            f"Campaign creation is only permitted for APPROVED leads (Current: {lead_status}).",
            "error",
        )
        return redirect(url_for("review_view"))

    buyers = load_buyers(Config.BUYERS_CSV)
    target_buyer = next((b for b in buyers if b.get("email", "").strip().lower() == email), None)
    if not target_buyer:
        flash(f"Buyer record for '{email}' not found.", "error")
        return redirect(url_for("review_view"))

    manager = CampaignManager(
        data_dir=Config.DATA_DIR,
        daily_limit=Config.DAILY_SEND_LIMIT,
        attachment_path=str(Config.PRESENTATION_PATH),
    )

    campaign, previews = manager.prepare_single_lead_campaign(
        buyer_record=target_buyer,
        product_keyword=Config.SEARCH_KEYWORD,
    )

    flash(
        f"Campaign '{campaign.campaign_id}' created in READY_FOR_REVIEW status! "
        f"Please complete the campaign approval gate before test execution.",
        "success",
    )
    return redirect(url_for("campaign_detail", campaign_id=campaign.campaign_id))



# ==============================================================================
# 5. CAMPAIGN DISPATCH & APPROVAL GATE (Route: /send)
# ==============================================================================
@app.route("/send")
def campaign_send_view():
    """Display campaign preparation interface, template editor, preview, and approval gate."""
    buyers = load_buyers(Config.BUYERS_CSV)
    classified_emails = load_classified_emails(biz_path=Config.BUSINESS_EMAILS_CSV, ind_path=Config.INDIVIDUAL_EMAILS_CSV)
    campaigns = CampaignStore.load_campaigns(Config.CAMPAIGNS_FILE)

    # Load default template text if available
    template_content = ""
    if Config.DEFAULT_TEMPLATE_PATH.exists():
        template_content = Config.DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")

    campaign_id = request.args.get("campaign_id")
    active_campaign = None
    active_previews = []

    manager = CampaignManager(
        data_dir=Config.DATA_DIR,
        daily_limit=Config.DAILY_SEND_LIMIT,
        attachment_path=str(Config.PRESENTATION_PATH),
    )

    if campaign_id:
        active_campaign = CampaignStore.get_campaign(campaign_id, file_path=Config.CAMPAIGNS_FILE)
        if active_campaign:
            # Re-generate preview details for active campaign
            _, active_previews = manager.prepare_campaign(
                target_audience=active_campaign.target_audience,
                product_keyword=Config.SEARCH_KEYWORD,
            )
    elif campaigns:
        # Show latest campaign if available
        active_campaign = campaigns[0]
        _, active_previews = manager.prepare_campaign(
            target_audience=active_campaign.target_audience,
            product_keyword=Config.SEARCH_KEYWORD,
        )

    return render_template(
        "send.html",
        active_page="send",
        total_buyers=len(buyers),
        biz_count=len(classified_emails["business"]),
        ind_count=len(classified_emails["individual"]),
        template_content=template_content,
        active_campaign=active_campaign,
        active_previews=active_previews,
        selected_audience=active_campaign.target_audience if active_campaign else "business",
    )


@app.route("/campaign/create", methods=["POST"])
def create_campaign_action():
    """Create a new campaign batch and generate candidate preview in READY_FOR_REVIEW state."""
    audience = request.form.get("audience", "business").lower()
    product_keyword = request.form.get("product_keyword", Config.SEARCH_KEYWORD).strip()
    template_text = request.form.get("template_text", "").strip()

    try:
        manager = CampaignManager(
            data_dir=Config.DATA_DIR,
            daily_limit=Config.DAILY_SEND_LIMIT,
            attachment_path=str(Config.PRESENTATION_PATH),
        )
        campaign, previews = manager.prepare_campaign(
            target_audience=audience,
            product_keyword=product_keyword,
            template_text=template_text or None,
        )
        flash(
            f"Campaign '{campaign.campaign_id}' generated with {campaign.eligible_recipients} eligible candidates. "
            "Please review the preview table and approve before dispatching.",
            "info"
        )
        return redirect(url_for("campaign_send_view", campaign_id=campaign.campaign_id))
    except Exception as e:
        flash(f"Error preparing campaign: {str(e)}", "error")
        return redirect(url_for("campaign_send_view"))


@app.route("/campaign/approve/<campaign_id>", methods=["POST"])
def approve_campaign_action(campaign_id: str):
    """Execute approval gate action for a campaign with backend attachment validation."""
    try:
        manager = CampaignManager(
            data_dir=Config.DATA_DIR,
            daily_limit=Config.DAILY_SEND_LIMIT,
            attachment_path=str(Config.PRESENTATION_PATH),
        )
        campaign = manager.approve_campaign(campaign_id)
        flash(f"Campaign '{campaign.campaign_id}' has been APPROVED for execution.", "success")
        return redirect(url_for("campaign_send_view", campaign_id=campaign.campaign_id))
    except (AttachmentError, CampaignStateError, ValueError) as e:
        flash(str(e), "error")
        return redirect(url_for("campaign_send_view", campaign_id=campaign_id))
    except Exception as e:
        flash(f"Approval failed: {str(e)}", "error")
        return redirect(url_for("campaign_send_view", campaign_id=campaign_id))


@app.route("/campaign/execute/<campaign_id>", methods=["POST"])
def execute_campaign_action(campaign_id: str):
    """Execute an approved campaign in TEST_MODE (or Live with confirmation) with backend attachment validation."""
    try:
        manager = CampaignManager(
            data_dir=Config.DATA_DIR,
            daily_limit=Config.DAILY_SEND_LIMIT,
            attachment_path=str(Config.PRESENTATION_PATH),
        )
        report_data = manager.execute_campaign(
            campaign_id=campaign_id,
            force_test_mode=Config.TEST_MODE,
        )
        flash(
            f"Campaign '{campaign_id}' executed successfully! "
            f"Dispatched: {report_data['successful_sends']}, Skipped: {report_data['duplicates_skipped'] + report_data['daily_limit_skipped']}.",
            "success"
        )
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))
    except (AttachmentError, CampaignStateError, ValueError) as e:
        flash(str(e), "error")
        return redirect(url_for("campaign_send_view", campaign_id=campaign_id))
    except Exception as e:
        flash(f"Execution failed: {str(e)}", "error")
        return redirect(url_for("campaign_send_view", campaign_id=campaign_id))


# ==============================================================================
# 6. CAMPAIGN DIRECTORY & DETAILS (Route: /campaigns & /campaigns/<id>)
# ==============================================================================
@app.route("/campaigns")
def campaigns_list():
    """List all stored outreach campaigns and their lifecycle statuses."""
    campaigns = CampaignStore.load_campaigns(Config.CAMPAIGNS_FILE)
    return render_template(
        "campaigns.html",
        active_page="campaigns",
        campaigns=campaigns,
    )


@app.route("/campaigns/<campaign_id>")
def campaign_detail(campaign_id: str):
    """View detailed execution logs and recipient outcomes for a specific campaign."""
    campaign = CampaignStore.get_campaign(campaign_id, file_path=Config.CAMPAIGNS_FILE)
    if not campaign:
        flash(f"Campaign '{campaign_id}' not found.", "error")
        return redirect(url_for("campaigns_list"))

    all_logs = load_campaign_log(Config.CAMPAIGN_LOG_CSV)
    campaign_logs = [log for log in all_logs if log.get("campaign_id") == campaign_id]

    return render_template(
        "campaign_detail.html",
        active_page="campaigns",
        campaign=campaign,
        log_records=campaign_logs,
    )


# ==============================================================================
# 7. REPORTS & ANALYTICS (Route: /report & /download-report)
# ==============================================================================
@app.route("/report")
def reports_view():
    """Consolidated executive reports, success metrics, and distribution charts."""
    buyers_audit = audit_buyers_csv(Config.BUYERS_CSV)
    classified_emails = load_classified_emails(biz_path=Config.BUSINESS_EMAILS_CSV, ind_path=Config.INDIVIDUAL_EMAILS_CSV)
    sent_audit = audit_sent_log(Config.SENT_LOG_CSV)
    sent_logs = load_sent_log(Config.SENT_LOG_CSV)

    buyers = load_buyers(Config.BUYERS_CSV)
    country_counts = Counter(b.get("country", "Unknown") for b in buyers if b.get("country"))
    top_countries = dict(country_counts.most_common(10))

    return render_template(
        "report.html",
        active_page="report",
        buyers_audit=buyers_audit,
        classified_emails=classified_emails,
        sent_audit=sent_audit,
        sent_logs=sent_logs,
        country_dist=top_countries,
    )


@app.route("/download-report")
def download_report():
    """Download the sent_log.csv or campaign log as a CSV attachment."""
    sent_log_path = Config.SENT_LOG_CSV
    if not sent_log_path.exists():
        flash("No sent log data available for export.", "warning")
        return redirect(url_for("reports_view"))

    return send_file(
        sent_log_path,
        mimetype="text/csv",
        as_attachment=True,
        download_name="export_outreach_report.csv",
    )


# ==============================================================================
# 8. SYSTEM SETTINGS & CREDENTIAL STATUS (Route: /settings)
# ==============================================================================
@app.route("/settings")
def settings_view():
    """Display system parameters, discovery configurations, and masked security statuses."""
    return render_template(
        "settings.html",
        active_page="settings",
    )


# ==============================================================================
# 9. ERROR HANDLING
# ==============================================================================
@app.errorhandler(404)
def page_not_found(e):
    """Friendly 404 error handler."""
    return render_template(
        "error.html",
        error_title="Page Not Found (404)",
        error_message="The requested page or route does not exist in the Export Automation Dashboard.",
    ), 404


@app.errorhandler(500)
def internal_server_error(e):
    """Friendly 500 error handler (masks stack trace)."""
    return render_template(
        "error.html",
        error_title="Internal System Notice (500)",
        error_message="An unexpected server error occurred. Please verify data integrity and try again.",
    ), 500


def run_web_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
    """Entrypoint to run the Flask web application."""
    print("\n" + "=" * 65)
    print("      API 3 - EXPORT AUTOMATION SYSTEM WEB DASHBOARD")
    print("=" * 65)
    print(f"Server URL         : http://{host}:{port}/")
    print(f"Execution Mode     : {'TEST MODE (Safe Simulation)' if Config.TEST_MODE else 'LIVE OUTREACH'}")
    print(f"Search Keyword     : {Config.SEARCH_KEYWORD}")
    print(f"Daily Send Limit   : {Config.DAILY_SEND_LIMIT} emails/day")
    print("=" * 65 + "\n")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_web_server(host="127.0.0.1", port=5000, debug=True)
