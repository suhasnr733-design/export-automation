# API 3 – EXPORT Automation System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Test Suite](https://img.shields.io/badge/pytest-144%20passed-brightgreen.svg)]()
[![Safety Mode](https://img.shields.io/badge/TEST__MODE-ACTIVE-orange.svg)]()
[![License](https://img.shields.io/badge/license-Proprietary%20%2F%20B2B-blue.svg)]()

A modular, enterprise-grade Python application designed for international B2B export buyer discovery, contact data extraction, RFC email validation, data provenance tracking, AI-assisted classification and qualification, human approval gates, safe simulated/live campaign outreach, and analytics.

---

## Table of Contents

- [Project Purpose & Business Workflow](#project-purpose--business-workflow)
- [Complete Architecture](#complete-architecture)
- [Project Directory Structure](#project-directory-structure)
- [Key Features & Capabilities](#key-features--capabilities)
  - [1. Buyer Discovery Pipeline](#1-buyer-discovery-pipeline)
  - [2. Contact Extraction & Validation](#2-contact-extraction--validation)
  - [3. Provenance & Data Isolation](#3-provenance--data-isolation)
  - [4. AI Classification & Qualification](#4-ai-classification--qualification)
  - [5. Human Review Desk & Safe Preview](#5-human-review-desk--safe-preview)
  - [6. Campaign Lifecycle & Dual-Gate Approval](#6-campaign-lifecycle--dual-gate-approval)
  - [7. Safety Controls & Dual Quota Architecture](#7-safety-controls--dual-quota-architecture)
  - [8. Duplicate Prevention & Idempotency](#8-duplicate-prevention--idempotency)
  - [9. Analytical Reporting](#9-analytical-reporting)
- [Web Dashboard Routes](#web-dashboard-routes)
- [CLI Commands](#cli-commands)
- [Installation & Setup](#installation--setup)
- [Configuration Reference (`.env`)](#configuration-reference-env)
- [Running Automated Tests](#running-automated-tests)
- [Security & Compliance Notes](#security--compliance-notes)
- [Known Limitations](#known-limitations)

---

## Project Purpose & Business Workflow

Export manufacturers and B2B trading houses often struggle with manual lead discovery, invalid contact details, unqualified inquiries, and compliance risks when conducting cold outreach to international distributors.

The **API 3 Export Automation System** solves these challenges through an 8-stage automated pipeline:

```
[1] Discovery      → Discover candidate buyers across search engines, website crawls & directories
[2] Extraction     → Extract email addresses, names, company names, and domains via regex & HTML parsers
[3] Validation     → Filter out disposable domains, invalid RFC syntax, and test placeholders
[4] Provenance     → Tag data origins (LIVE_DISCOVERY vs HISTORICAL_TEST) & deduplicate vs sent log
[5] Intelligence   → Classify contacts (B2B vs Consumer) & score qualification (0-100 score)
[6] Human Review   → Review live leads on dashboard (/review), verify country, approve candidates
[7] Staging & Gate → Preview personalized emails (/review/preview), approve campaign, verify PDF attachment
[8] Dispatch       → Safe simulation in TEST_MODE or rate-limited Gmail SMTP delivery
```

---

## Complete Architecture

```
                                  +---------------------------------------+
                                  |         Multi-Channel Discovery       |
                                  |  (Google Live, Web Deep Crawl, Stubs) |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |         Extraction & Sanitation       |
                                  |     (Regex, Mailto, 6-col Schema)     |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |         Validation & Filtering        |
                                  |   (RFC 5322, Disposable Blocklist)    |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |      Provenance & Deduplication       |
                                  |  (LIVE vs HISTORICAL, sent_log.csv)   |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |      AI Classification & Scoring      |
                                  |  (Gemini / Heuristic, 6-Pillar Qual)  |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |   Human Lead Review Gate (/review)    |
                                  |    (Approve / Reject / Manual Review) |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |   Personalization & Campaign Preview  |
                                  |     (Side-by-side token rendering)    |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |      Campaign Approval Gate 2         |
                                  |  (DRAFT -> READY_FOR_REVIEW -> APPVD) |
                                  +-------------------+-------------------+
                                                      |
                                      +---------------+---------------+
                                      |                               |
                           [TEST_MODE = true]                [TEST_MODE = false]
                                      |                               |
                                      v                               v
                          +-----------------------+       +-----------------------+
                          | Safe Simulated Engine |       |    Gmail SMTP Auth    |
                          | (TEST_MODE_SUCCESS)   |       |  (Rate-limited sends) |
                          +-----------+-----------+       +-----------+-----------+
                                      |                               |
                                      +---------------+---------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |    Persistence, Audit & Analytics     |
                                  |  (sent_log, campaign_log, CSV export) |
                                  +---------------------------------------+
```

---

## Project Directory Structure

```
export-automation/
├── main.py                     # Central CLI orchestration & pipeline entry point
├── web_app.py                  # Professional Flask web dashboard
├── config.py                   # Central configuration & environment loader
├── requirements.txt            # Project dependencies
├── .env.example                # Safe environment variable template
├── .gitignore                  # Git ignore rules for secrets and caches
├── README.md                   # Complete system documentation
│
├── docs/                       # Detailed documentation
│   ├── architecture.md         # System architecture & Mermaid flowcharts
│   └── demo-workflow.md        # Step-by-step TEST_MODE demonstration guide
│
├── search/                     # Discovery adapters & query engines
│   ├── __init__.py
│   ├── query_builder.py        # Commercial query generator
│   ├── google_search.py        # Live Google search adapter with diagnostics
│   ├── website_search.py       # Deep website crawl & contact scraper
│   ├── facebook_search.py      # Facebook discovery stub
│   ├── linkedin_search.py      # LinkedIn discovery stub
│   ├── directory_search.py     # B2B Trade directory stub
│   ├── relevance_filter.py     # Domain scoring & keyword audit
│   └── search_cache.py         # Response caching mechanism
│
├── extraction/                 # Contact extraction and text processing
│   ├── __init__.py
│   └── data_extractor.py       # Regex email extraction & schema mapping
│
├── validation/                 # Email validation and hygiene
│   ├── __init__.py
│   └── email_validator.py      # RFC syntax checking & disposable filtering
│
├── classification/             # Contact audience classification
│   ├── __init__.py
│   └── gemini_classifier.py    # Gemini 2.5 Flash & heuristic engine
│
├── qualification/              # AI buyer qualification & lead scoring
│   ├── __init__.py
│   └── buyer_qualifier.py      # 6-pillar 0-100 qualification scoring
│
├── outreach/                   # Campaign management & email dispatch
│   ├── __init__.py
│   ├── campaign_model.py       # Campaign dataclass & state machine
│   ├── campaign_manager.py     # Staging, approval & batch dispatcher
│   ├── gmail_auth.py           # Authenticated Gmail SMTP manager
│   ├── gmail_sender.py         # Rate-limited sender & test simulator
│   ├── personalization.py      # Template variable interpolation
│   └── attachment_handler.py   # PDF presentation validation & MIME attachment
│
├── logging/                    # Logging, CSV data persistence & provenance
│   ├── __init__.py
│   └── activity_logger.py      # Thread-safe CSV datastore manager
│
├── reports/                    # Run summary analytics and export
│   ├── __init__.py
│   └── report_generator.py     # Conversion funnel & CSV export
│
├── data/                       # CSV & JSON Data Stores
│   ├── buyers.csv              # Master buyer dataset
│   ├── business_emails.csv     # Qualified B2B / wholesale emails
│   ├── individual_emails.csv   # Personal / retail inboxes
│   ├── sent_log.csv            # Historical outreach log for idempotency
│   ├── campaign_log.csv        # Campaign execution history
│   ├── campaigns.json          # Staged and active campaign definitions
│   ├── classification_log.csv  # AI classification audit trail
│   ├── qualification_log.csv   # Lead qualification score cards
│   ├── lead_review_log.csv     # Human review decision audit log
│   └── discovery_provenance.json # Source provenance metadata
│
├── assets/                     # Attachment assets (PDF presentations)
│   ├── .gitkeep
│   └── company_presentation.pdf
│
├── templates/                  # Jinja2 HTML templates for Web Dashboard
│   ├── base.html               # Global layout with safety banner
│   ├── dashboard.html          # Main overview & KPI cards
│   ├── buyers.html             # Discovered buyer directory
│   ├── upload.html             # CSV ingestion & staging audit
│   ├── classify.html           # AI classification trigger & stats
│   ├── review.html             # Human lead review desk
│   ├── review_preview.html     # Live personalization preview
│   ├── send.html               # Campaign dispatch setup
│   ├── campaigns.html          # Campaign directory
│   ├── campaign_detail.html    # Granular campaign view & execution
│   ├── report.html             # Analytics & conversion funnel
│   ├── settings.html           # System configuration viewer
│   ├── error.html              # User-friendly error page
│   └── outreach_template.txt   # Default outreach email template
│
├── static/                     # Static web assets
│   ├── css/style.css           # Modern dark-slate dashboard stylesheet
│   └── js/app.js               # Client-side UI interactions
│
└── tests/                      # Automated test suite (144 tests)
    ├── test_extraction.py
    ├── test_validation.py
    ├── test_logging.py
    ├── test_duplicate_prevention.py
    ├── test_discovery.py
    ├── test_discovery_isolation.py
    ├── test_duplicate_isolation.py
    ├── test_search_diagnostics.py
    ├── test_quota_hardening.py
    ├── test_classification.py
    ├── test_live_gemini_classification.py
    ├── test_data_integrity_provenance.py
    ├── test_outreach_campaign.py
    ├── test_buyer_qualification.py
    ├── test_lead_review_and_preview.py
    └── test_web_app.py
```

---

## Key Features & Capabilities

### 1. Buyer Discovery Pipeline
- **Search Query Builder**: Combines target export keywords with intent modifiers (`"wholesale"`, `"importer"`, `"distributor"`, `"procurement"`).
- **Google Search Adapter**: Live HTTP discovery with rate-limiting, user-agent rotation, domain caching, and query diagnostics.
- **Deep Website Search**: Crawls company websites to extract emails from `/contact`, `/about`, `/inquiry`, and `/wholesale` pages.

### 2. Contact Extraction & Validation
- **Regex & HTML Mailto Extraction**: Discovers email addresses embedded in unstructured text and hyperlinks.
- **Canonical 6-Column Schema**: Normalizes records into: `buyer_name`, `company_name`, `email`, `website`, `country`, `source_platform`.
- **RFC 5322 & Disposable Filtering**: Rejects malformed addresses, disposable domains (`mailinator.com`, `tempmail.com`), and test placeholders (`example.com`).

### 3. Provenance & Data Isolation
- **`discovery_provenance.json`**: Immutably records origin metadata (`LIVE_DISCOVERY` vs `HISTORICAL_TEST`).
- **Country Integrity**: Maintains `"Unknown — Verification Required"` when country data cannot be verified from domain or page content, avoiding hallucinated data.

### 4. AI Classification & Qualification
- **Gemini 2.5 Flash**: Evaluates organizational structures to classify contacts into B2B business vs individual consumers (with local heuristic fallback).
- **6-Pillar Lead Qualification (0–100 Score)**:
  - *Business Legitimacy* (20 pts)
  - *Product Relevance* (20 pts)
  - *Commercial Intent* (25 pts)
  - *Contact Quality* (15 pts)
  - *Website Evidence* (10 pts)
  - *Country Completeness* (10 pts)
  - Recommendations: `REVIEW_FOR_OUTREACH` ($\ge 75$), `MANUAL_REVIEW` (50–74), `DO_NOT_CONTACT` ($< 50$).

### 5. Human Review Desk & Safe Preview
- **Review Desk (`/review`)**: Dedicated web interface for reviewing `LIVE_DISCOVERY` leads before staging.
- **Personalization Preview (`/review/preview`)**: Side-by-side template preview rendering personalized tokens (`{{buyer_name}}`, `{{company_name}}`, `{{product}}`, `{{country}}`) without dispatching emails.

### 6. Campaign Lifecycle & Dual-Gate Approval
- **State Machine**: `DRAFT` $\rightarrow$ `READY_FOR_REVIEW` $\rightarrow$ `APPROVED` $\rightarrow$ `COMPLETED` / `FAILED`.
- **Two-Step Approval Gate**:
  1. *Gate 1*: Explicit lead approval on the review desk.
  2. *Gate 2*: Explicit campaign approval on the campaign page before execution.

### 7. Safety Controls & Dual Quota Architecture
- **`TEST_MODE` Safety Switch**: When `TEST_MODE=true` (the default), real SMTP sending is strictly disabled. Dispatches are simulated and recorded with `TEST_MODE_SUCCESS`.
- **Dual Quota System**:
  - `DAILY_SEND_LIMIT`: Enforces a hard daily ceiling on real SMTP sends (default: 10).
  - `TEST_SIMULATION_LIMIT`: Independent limit for test simulations (default: 50).
- **Credential Protection**: Secrets (`GMAIL_APP_PASSWORD`, `GEMINI_API_KEY`) are never rendered in HTML templates or logs.

### 8. Duplicate Prevention & Idempotency
- **Historical Cross-Run Deduplication**: Queries `data/sent_log.csv` before staging or sending; prevents any recipient from receiving duplicate outreach across multiple campaigns.

### 9. Analytical Reporting
- **Console Analytics**: Formatted ASCII run metrics and conversion funnels.
- **Web Analytics (`/report`)**: Interactive charts and qualification distributions.
- **CSV Export (`/download-report`)**: Direct export of all outreach metrics.

---

## Web Dashboard Routes

| Route | Method | Description |
| :--- | :--- | :--- |
| **`/`** | `GET` | Executive Dashboard: KPIs, recent activity, system health, and safety status banner. |
| **`/buyers`** | `GET` | Buyer Dataset: Searchable, filterable table of all discovered and ingested contacts. |
| **`/upload`** | `GET`, `POST` | Lead Ingestion: Upload CSV lead lists with automatic schema auditing and staging cache. |
| **`/upload/confirm`** | `POST` | Ingestion Merge: Explicitly merges staged CSV contacts into master datastore. |
| **`/classify`** | `GET` | AI Classification: Overview of B2B vs individual contact segmentation. |
| **`/classify/run`** | `POST` | AI Trigger: Executes batch classification on unclassified contacts. |
| **`/review`** | `GET` | Lead Review Desk: Human review center for `LIVE_DISCOVERY` leads with score cards. |
| **`/review/decision`** | `POST` | Review Action: Submits human approval, rejection, or manual review decisions. |
| **`/review/preview`** | `GET` | Personalization Preview: Renders live email previews for approved leads. |
| **`/review/create-campaign`** | `POST` | Campaign Staging: Stages approved leads into a new campaign in `READY_FOR_REVIEW`. |
| **`/send`** | `GET` | Outreach Dispatch: Prepares manual campaign dispatch with audience selector. |
| **`/campaign/create`** | `POST` | Campaign Creation: Creates a new campaign batch. |
| **`/campaigns`** | `GET` | Campaigns Directory: Lists all campaigns with approval and execution statuses. |
| **`/campaigns/<id>`** | `GET` | Campaign Detail: Granular view of campaign recipients, dispatch tokens, and logs. |
| **`/campaign/approve/<id>`** | `POST` | Campaign Approval Gate: Approves a staged campaign for execution. |
| **`/campaign/execute/<id>`** | `POST` | Campaign Execution: Triggers simulated or live campaign dispatch. |
| **`/report`** | `GET` | Analytics & Reports: Conversion funnel, country breakdown, and execution logs. |
| **`/download-report`** | `GET` | CSV Export: Streams consolidated outreach report CSV. |
| **`/settings`** | `GET` | Settings: Read-only viewer of active configuration parameters and safety locks. |

---

## CLI Commands

The system provides a rich set of command-line tools via [`main.py`](file:///c:/Users/LENOVO/Desktop/export-automation/main.py):

### Run Full Pipeline (Default Safe Test Mode)
```bash
python main.py
```

### Standalone Real Buyer Discovery
```bash
python main.py --discover --keyword "Handmade Pashmina" --limit 5
```

### Dataset Validation & Email Hygiene Audit
```bash
python main.py --validate
```

### Run AI Lead Classification
```bash
python main.py --classify
```

### Preview Outreach Campaign (Dry Run)
```bash
python main.py --campaign-preview
```

### Safe Campaign Execution (Test Mode)
```bash
python main.py --send --test
```

### System Configuration & Quota Status Audit
```bash
python main.py --status
```

### Campaign History & Directory Status
```bash
python main.py --campaign-status
```

### Display Web Route Specification
```bash
python main.py --routes-info
```

---

## Installation & Setup

### 1. Prerequisites
- Python 3.10+ (Python 3.12.10 recommended)
- `pip`

### 2. Setup Virtual Environment (Optional / Recommended)
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 5. Launch the Web Application
```bash
python web_app.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

## Configuration Reference (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `TEST_MODE` | `true` | **Master Safety Switch**. When `true`, real email dispatch is strictly prevented. |
| `SEARCH_KEYWORD` | `Singing Bowls` | Target export product/industry niche keyword. |
| `SEARCH_DELAY` | `1.0` | Delay in seconds between search requests. |
| `MAX_SEARCH_RESULTS` | `15` | Maximum search result items inspected per discovery run. |
| `MAX_WEBSITES_PER_RESULT` | `5` | Maximum websites crawled for contact details. |
| `TEST_DISCOVERY` | `false` | When `true`, uses offline discovery fixtures for testing. |
| `CLASSIFICATION_LIVE` | `false` | When `true`, routes AI classification to live Gemini API. |
| `GEMINI_API_KEY` | *(empty)* | Google Gemini API key for live AI classification. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Target Gemini model name. |
| `CLASSIFICATION_BATCH_SIZE` | `20` | Maximum contacts evaluated per classification batch. |
| `CLASSIFICATION_REVIEW_THRESHOLD`| `0.70` | Confidence threshold below which manual review is flagged. |
| `DAILY_SEND_LIMIT` | `10` | Daily sending ceiling for real SMTP dispatches. |
| `TEST_SIMULATION_LIMIT` | `50` | Maximum simulation dispatches allowed in a single test batch. |
| `SEND_DELAY` | `5.0` | Delay in seconds between consecutive email dispatches. |
| `PRESENTATION_PATH` | `assets/company_presentation.pdf` | Path to PDF catalog attachment. |
| `GMAIL_EMAIL` | *(empty)* | Gmail sender address (required only when `TEST_MODE=false`). |
| `GMAIL_APP_PASSWORD` | *(empty)* | 16-character Google App Password (never committed). |

---

## Running Automated Tests

Run the complete 144-test suite using `pytest`:

```bash
pytest tests/ -v
```

### Test Suite Coverage:
1. `tests/test_extraction.py`: Regex extraction, HTML mailto parsing, trailing character cleanup, schema normalization.
2. `tests/test_validation.py`: RFC syntax validation, disposable domain rejection, whitespace handling.
3. `tests/test_logging.py`: CSV read/write, schema initialization, atomic writes, backup creation.
4. `tests/test_duplicate_prevention.py`: Sent log deduplication, missing attachment validation, simulation idempotency.
5. `tests/test_discovery.py`: Query builder generation, search adapter contract validation.
6. `tests/test_discovery_isolation.py`: Discovery isolation, live vs synthetic isolation.
7. `tests/test_duplicate_isolation.py`: Cross-run duplicate isolation.
8. `tests/test_search_diagnostics.py`: Query diagnostics, relevance filtering.
9. `tests/test_quota_hardening.py`: Quota handling, dual quota limits, rate-limiting resilience.
10. `tests/test_classification.py`: Audience classification logic, business vs individual partitioning.
11. `tests/test_live_gemini_classification.py`: Gemini API connector, prompt structures, heuristic fallbacks.
12. `tests/test_data_integrity_provenance.py`: Provenance metadata tracking, country integrity.
13. `tests/test_outreach_campaign.py`: Campaign state machine, staging, dual approval gates, test execution.
14. `tests/test_buyer_qualification.py`: 6-pillar scoring engine, keyword expansion, recommendations.
15. `tests/test_lead_review_and_preview.py`: Human lead review desk, country preservation, personalization preview.
16. `tests/test_web_app.py`: Flask web dashboard routes, upload staging, credential masking, report download.

---

## Security & Compliance Notes

1. **Safety First**: `TEST_MODE` defaults to `true` to guarantee no accidental emails are dispatched during development or evaluation.
2. **Credential Protection**: Secrets (`GMAIL_APP_PASSWORD`, `GEMINI_API_KEY`) are loaded strictly from `.env` and are never hard-coded or rendered in HTML responses.
3. **Attachment Safety**: `AttachmentHandler` enforces strict PDF MIME validation and a 10 MB size limit before staging.
4. **Dual Approval Gates**: Campaign dispatches require explicit approval at both the lead level and the campaign level.
5. **Data Provenance**: All records maintain auditable origin tags in `data/discovery_provenance.json`.

---

## Known Limitations

- **Search Adaptor Stubs**: Facebook, LinkedIn, and B2B Trade Directory adapters currently operate as structured stub interfaces for custom API connectors.
- **Single-User Desk**: The web dashboard is currently architected for single-operator local use and does not incorporate multi-tenant user authentication.
- **Gmail SMTP Provider**: Outreach is currently configured for standard Gmail SMTP with Google App Passwords rather than OAuth2 Enterprise Gmail APIs.
