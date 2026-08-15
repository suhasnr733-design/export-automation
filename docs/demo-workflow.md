# Internship Demonstration Workflow (TEST_MODE)
## API 3 — EXPORT Automation System

This document outlines a complete, step-by-step walkthrough demonstrating the full Export Automation System in **`TEST_MODE`**. This guide is designed for internship evaluations, technical presentations, and end-to-end system validation with zero risk of sending real emails.

---

## 1. Prerequisites & Environment Check

Before beginning the demonstration, verify that the application is operating in safe test mode:

1. **Verify Python Version**:
   - Python 3.10+ (Recommended: Python 3.12.10)
2. **Verify Configuration**:
   - Ensure `.env` has `TEST_MODE=true`
3. **Launch the Web Application**:
   ```bash
   python web_app.py
   ```
   Access the dashboard at [http://127.0.0.1:5000](http://127.0.0.1:5000).
   The yellow **TEST MODE ACTIVE** safety banner will be visible across the top of all pages.

---

## 2. End-to-End Walkthrough Scenario: "Handmade Pashmina"

### Step 1: Real Buyer Discovery (CLI or Web Upload)
Run the buyer discovery engine targeting international buyers of handcrafted pashmina shawls:

```bash
python main.py --discover --keyword "Handmade Pashmina" --limit 5
```

**What happens:**
- `SearchQueryBuilder` generates high-intent commercial B2B queries (`"Handmade Pashmina wholesale importer"`, `"Handmade Pashmina distributor Europe"`).
- `GoogleSearchAdapter` and `WebsiteSearchAdapter` discover live domains, parse `/contact` and `/about` pages, and extract contact records.
- Discovered records are tagged with `data_source: LIVE_DISCOVERY` in `data/discovery_provenance.json`.
- Validated records are saved to `data/buyers.csv`.

---

### Step 2: Email Validation & Hygiene
Verify that extracted email addresses pass strict syntax and anti-disposable checks:

```bash
python main.py --validate
```

**What happens:**
- `EmailValidator` parses every record against RFC 5322 rules.
- Disposable domains (`mailinator.com`, `tempmail.com`) and generic placeholders (`test@example.com`) are automatically rejected.
- Sanitized emails are normalized to lowercase without trailing punctuation.

---

### Step 3: AI Lead Classification
Segment contacts into commercial business entities versus individual consumer inboxes:

```bash
python main.py --classify
```

**What happens:**
- Contacts are evaluated by the AI classification engine (Gemini 2.5 Flash with deterministic fallback).
- Corporate domain structures, organizational prefixes, and corporate keywords are analyzed.
- Verified business entities are routed to `data/business_emails.csv`; consumer accounts are routed to `data/individual_emails.csv`.
- An audit entry with confidence scores and reasoning is recorded in `data/classification_log.csv`.

---

### Step 4: AI Buyer Qualification & Lead Scoring
Evaluate commercial intent and fit using the 6-pillar qualification framework:

**Web Dashboard Step:**
1. Navigate to **Lead Review** (`/review`) on the web dashboard.
2. The desk filters exclusively for leads tagged as `LIVE_DISCOVERY`.
3. Each lead displays a score card (0–100) across 6 dimensions:
   - Business Legitimacy (Domain authority, registration markers)
   - Product Relevance (Alignment with "Handmade Pashmina")
   - Buyer Intent (Importer, wholesaler, boutique retailer signals)
   - Contact Quality (Named contact vs generic inbox)
   - Website Evidence (Catalog, SSL, business footprint)
   - Data Completeness (Country verification)
4. Notice that leads without explicit country data maintain **"Unknown — Verification Required"** rather than guessing.

---

### Step 5: Human Review Decision Gate
1. On the **Lead Review Desk** (`/review`), inspect the discovered lead:
   - **Company**: *Pashmina Vogue™*
   - **Email**: `support@pashminavogue.com`
   - **Score**: `75 / 100` (High Qualification)
2. Click **Approve Lead** (or select multiple and submit bulk approval).
3. The system records the approval in `data/lead_review_log.csv`.

---

### Step 6: Safe Personalization & Campaign Preview
1. Click **Preview Outreach Campaign** (`/review/preview`).
2. The personalization engine generates dynamic email previews for each approved recipient:
   - Subject: `Direct Export Catalog: Premium Handcrafted Handmade Pashmina for Pashmina Vogue™`
   - Recipient tokens: `{{company_name}}`, `{{product}}`, `{{country}}`.
   - Attachment verification: Confirms `assets/company_presentation.pdf` is valid and ready.
3. Review the rendered email side-by-side to verify formatting.
4. Click **Stage Outreach Campaign**.

---

### Step 7: Campaign Staging & Second Approval Gate
1. Navigate to **Campaigns** (`/campaigns`) and click on the newly staged campaign.
2. Campaign status is **`READY_FOR_REVIEW`**.
3. Inspect campaign details, target recipient count, and template.
4. Click **Approve Campaign for Execution**. Status updates to **`APPROVED`**.

---

### Step 8: Safe TEST_MODE Execution
1. On the approved campaign page, click **Execute Campaign (Simulated)**.
2. The engine executes the dispatch simulation:
   - Applies the simulated send delay (`5s` default).
   - Enforces the `TEST_SIMULATION_LIMIT` quota.
   - Logs simulated delivery tokens (`TEST_MODE_SUCCESS`) in `data/sent_log.csv` and `data/campaign_log.csv`.
   - **Zero real SMTP calls occur and no real emails leave the machine.**
3. Status transitions to **`COMPLETED`**.

---

### Step 9: Analytics & Reporting
1. Navigate to **Reports** (`/report`) on the web dashboard.
2. Review the updated metrics:
   - Total Buyers Processed
   - AI Classification Distribution
   - Qualification Score Breakdown
   - Conversion Funnel (Discovered $\rightarrow$ Validated $\rightarrow$ Qualified $\rightarrow$ Approved $\rightarrow$ Contacted)
3. Click **Download Full CSV Report** (`/download-report`) to download the consolidated audit export.

---

## 3. Post-Demo Audit Checklist

Run the CLI status audit to verify data integrity and safety:

```bash
python main.py --status
```

Expected output confirms:
- `TEST_MODE: True`
- `Real Emails Sent Today: 0`
- `Simulated Dispatches Logged: Verified`
- `Historical and Live Datastores: Fully Intact`
