# BOB — Intelligent Shipping Document Verification & Discrepancy Management

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.40+-FF4B4B.svg?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Gemini AI](https://img.shields.io/badge/AI-Gemini_3.5_Flash_Lite-8E75B2.svg?logo=google&logoColor=white)](https://ai.google.dev/)
[![Railway Live Demo](https://img.shields.io/badge/Live_Demo-Railway-0B0D0E.svg?logo=railway&logoColor=white)](https://averis-hackathon-bobthebuilder-production.up.railway.app)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Built by Team **Bob the Builder** for the **Averis x Monash Hackathon 2026**, **BOB** (*Bill of Lading Verification System*) is an intelligent end-to-end automation platform that transforms messy maritime operations inboxes into a zero-defect document verification workflow: classifying incoming emails, extracting canonical shipping fields from multi-format attachments (`.txt`, `.pdf`, `.docx`, `.xlsx`), detecting discrepancies between Shipping Instructions (SI) and draft Bills of Lading (BL), generating natural-language AI discrepancy summaries, auto-drafting sender clarification emails with dual-lock safety rails, and routing ambiguous cases to human operators.

---

## 🌐 Live Prototype & Deployed Services

The application is deployed and publicly accessible on cloud infrastructure:

| Service Surface | Direct Access Link | Description |
|---|---|---|
| **Operator Web Interface** | [Live Web App (`/app`)](https://averis-hackathon-bobthebuilder-production.up.railway.app/app) | Modern visual portal for shipment triage and inspection |
| **Interactive API Documentation** | [API Portal (`/docs`)](https://averis-hackathon-bobthebuilder-production.up.railway.app/docs) | Interactive testing console for all pipeline endpoints |
| **Swagger UI Specification** | [OpenAPI Console (`/swagger`)](https://averis-hackathon-bobthebuilder-production.up.railway.app/swagger) | Complete OpenAPI 3.0 schema and request models |
| **Service Health Check** | [Health Endpoint (`/health`)](https://averis-hackathon-bobthebuilder-production.up.railway.app/health) | Real-time container liveness and heartbeat check |

---

## ⚡ Quick Start (Run Locally in 3 Steps)

### 1. Installation & Environment Setup
```bash
# Clone repository
git clone https://github.com/hann-png/averis-hackathon-bobthebuilder.git
cd averis-hackathon-bobthebuilder

# Create and activate virtual environment
python -m venv venv

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables (optional for local rules-fallback, required for Gemini AI)
cp .env.example .env
```

### 2. Verify Everything with Automated Tests
Automated endpoint tests covering health checks, submission validation, and per-email routes (`test_api.py`), plus security and assistant test suites:
```bash
# Run API endpoint, schema validation, and safety rails test suite
python test_api.py

# Run workspace assistant safety and natural-language query tests
python test_assistant.py

# Test standalone auto-reply notification scenarios (all 6 cases)
python -m pipeline.notification
```

### 3. Run the End-to-End Pipeline
Process the dataset and generate the validated `submission.json`:
```bash
python run_pipeline.py --data data --output submission.json
```

---

## ✨ Features

- **5-Category Email Classification**: Accurately routes incoming emails into `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, and `SPAM`. Combines fast regex pre-filters for spam and recurring operational digests with a primary Gemini 3.5 Flash Lite classifier and deterministic fallback rules.
- **Multi-Format Document Extraction**: Ingests `.txt`, `.pdf`, `.docx`, and `.xlsx` attachments to extract the 7 canonical shipping fields, cross-checking model extractions against synonym dictionaries to generate field-level confidence ratings.
- **Deterministic 7-Field Comparison**: Implements zero-false-alarm matching logic that normalizes entity punctuation, legal corporate suffixes, `"TO ORDER OF..."` consignee clauses, container notations (e.g. `4 x 40'HC` → `4`), port name variations, and metric weight tolerances (`≤ 1.0 KG`).
- **Reliability & Human Review Escalation**: Identifies ambiguous shipments and unresolvable edge cases, routing them to human review with standardized diagnostic reason codes (`wrong_doc_type`, `missing_attachment`, `unreadable`, `missing_value`).
- **Automated Clarification Notifications**: Prepares structured, sender-addressed clarification drafts when discrepancies occur, detailing the exact fields in dispute with actionable resolution requests.
- **Dual-Lock Safety Rails**: Outbound email sending is strictly locked by default (`actually_send=False`), requiring explicit configuration of `BOB_ALLOW_REAL_SEND=true` before any SMTP transmission can occur, with all drafts mirrored to local audit files.
- **Natural-Language Workspace Assistant**: Supports read-only operational inquiries (e.g., querying mismatches, port anomalies, or escalation queues) through conversational prompts powered by allowlisted query execution.
- **Zero-Trust Security & PII Protection**: Includes attachment magic-byte validation, zip-bomb protection, adversarial prompt injection defenses, SHA-256 cryptographic provenance, and automated PII redaction.

---

## 🖥️ Interactive User Interfaces

### 1. FastAPI Microservice & Web Interface *(Live on Railway & Local)*
The core production service runs on FastAPI, powering the REST API and the live Operator Web Portal:
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```
*API Docs: `http://localhost:8080/docs` | Web App: `http://localhost:8080/app`*

**Core Endpoints:**
- `GET /health` — Service liveness check and database connection status.
- `GET /stats` — Aggregated metrics across all emails, categories, and defect fields.
- `GET /submission` — Returns validated `submission.json` adhering to competition requirements.
- `GET /email/{email_id}` — On-demand result and classification for a specific email.
- `GET /email/{email_id}/notification` — Generates a draft email notification addressed to the original sender.
- `POST /email/{email_id}/notification/send` — Saves notification draft locally (safely defaults to `actually_send=False`).
- `POST /assistant/query` — Natural-language operational query endpoint.

### 2. Streamlit Operator Review Dashboard *(Local-Only)*
> **Note**: The Streamlit dashboard is designed for local development and offline operator triage (`streamlit run dashboard/app.py` on `localhost:8501`). It is **not** part of the live Railway cloud deployment, which runs the FastAPI microservice and web interface.

Launch locally via:
```bash
streamlit run dashboard/app.py
```
*Access at: `http://localhost:8501`*

**Key Features:**
- **Real-Time KPI Cards**: Total emails processed, mismatch rate, escalation queue size, and clean shipment counts.
- **Side-by-Side Field Diffing**: Highlights discrepancies across all 7 canonical fields in clear color-coded tables.
- **AI Discrepancy Explanations**: Plain-English root cause explanations generated by Gemini 3.5 Flash Lite.
- **📧 Mismatch Notification Draft Tab**: Inspects sender-addressed clarification drafts with a one-click local save button.
- **Operator Review Checkbox**: Tracks human-in-the-loop review status per shipment.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    A[Incoming Email Inbox] --> B0[Spam & Digest Pre-Filter<br/>Fast Regex & Domain Check]
    B0 -->|Obvious Spam| C1[SPAM - OK]
    B0 -->|Operational Digest / Holiday| C2[GENERAL - OK]
    B0 -->|Standard Email| B[AI Email Classifier<br/>Gemini 3.5 Flash Lite Primary<br/>Domain Rules Fallback]
    
    B -->|SPAM| C1
    B -->|GENERAL| C2
    B -->|INVOICE_QUERY| C3[INVOICE_QUERY - OK]
    B -->|SI_REQUEST| C4[SI_REQUEST - OK]
    B -->|BL_COMPARISON| D[Escalation Gate 1<br/>Deterministic Attachment Check]
    
    D -->|< 2 atts & compare requested| E1[NEEDS_REVIEW<br/>missing_attachment]
    D -->|0 atts draft request| E2[Status OK]
    D -->|SI + BL Attached| F[Multi-Format Extractor<br/>.txt, .pdf, .docx, .xlsx<br/>Gemini AI + Synonym Cross-Check]
    
    F -->|Non-BL Document Detected| G1[NEEDS_REVIEW<br/>wrong_doc_type]
    F -->|Corrupt or Blank Scan| G2[NEEDS_REVIEW<br/>unreadable]
    F -->|Extract 7 Canonical Fields| H[Escalation Gate 2<br/>Missing Placeholders Check]
    
    H -->|Missing Required Field / TBA| G3[NEEDS_REVIEW<br/>missing_value]
    H -->|All 7 Fields Clean| I[Deterministic Comparator<br/>Pure Python Alphanumeric & Numeric Normalization]
    
    I -->|Field Discrepancy Found| J1[MISMATCH<br/>has_defect: true]
    I -->|All 7 Fields Match| J2[OK<br/>has_defect: false]
    
    J1 --> J3[AI Discrepancy Explainer<br/>Gemini 3.5 Flash Lite Summary]
    J1 --> J4[Notification Engine<br/>Drafts Sender Clarification Email]
    
    J1 --> K[submission.json]
    J2 --> K
    C1 --> K
    C2 --> K
    C3 --> K
    C4 --> K
    E1 --> K
    E2 --> K
    G1 --> K
    G2 --> K
    G3 --> K
```

---

## ⚙️ Implementation Details

### 1. Resilient Multi-Key Gemini Pool & Concurrency Design (`gemini_client.py`)
To process enterprise document batches without stalls or quota exhaustion, BOB implements a custom thread-safe client pool:
- **Token Bucket Rate Limiting**: A `TokenBucketRateLimiter` dynamically throttles request throughput, calibrating the refill rate to `pool_size * RPM_PER_KEY` tokens/minute.
- **Lock Contention Elimination**: Concurrency is optimized by holding the `threading.Lock` **only** during client index lookup and compare-and-swap rotation (<1ms). The lock is released *before* initiating the I/O-bound `generate_content` network call, allowing multiple worker threads to execute requests concurrently without blocking each other.
- **Thread-Safe Key Rotation on 429**: When a key encounters a quota limit (`RESOURCE_EXHAUSTED` / HTTP 429), the client pool triggers a compare-and-swap rotation to the next active key. Only the worker that observed the failure advances the pointer, preventing race conditions from skipping multiple keys at once.
- **Strictly Bounded Cooldown Cycles**: If all configured keys in the pool encounter rate limits within a single cycle, the pool enters a bounded sleep (`DEFAULT_COOLDOWN_SECONDS = 20.0s`). Cooldown is capped at `MAX_COOLDOWN_CYCLES = 2` (~40 seconds total). If quota remains unavailable, it raises a `RuntimeError`, allowing the caller to switch cleanly to local fallback rules rather than hanging indefinitely.
- **Per-Email Disk Caching**: Raw AI responses and extraction payloads are cached on disk (`data/cache/`), enabling interrupted runs to resume immediately without re-burning API quota.

### 2. The AI-vs-Deterministic Architectural Split
A core architectural principle in BOB is strict separation between **probabilistic perception** and **deterministic verification**:
- **AI Where Judgment Matters (Perception & Natural Language)**: LLMs (Gemini 3.5 Flash Lite) handle tasks requiring linguistic adaptability and context:
  - **Email Intent Classification** (`classifier.py`): Discriminating nuanced logistics correspondence (e.g. routine operational digests mentioning an SI versus genuine comparison requests).
  - **Multi-Format Extraction** (`extractor_text.py`, `extractor_docs.py`): Parsing variable visual and spatial layouts across PDFs, Word documents, Excel spreadsheets, and plain text.
  - **Discrepancy Summaries** (`explainer.py`): Translating raw field deltas into concise, human-friendly root-cause explanations for operators.
- **Pure Deterministic Code Where Correctness Must Be Guaranteed (Comparison & Escalation)**: To eliminate hallucinations and guarantee zero-defect compliance, no AI model is permitted to decide whether documents match or escalate:
  - **Field Comparison** (`comparator.py`): Executes pure Python normalization—stripping legal corporate suffixes, collapsing whitespace, handling negotiable `"TO ORDER OF..."` consignee clauses, mapping UN/LOCODE port aliases, extracting numeric container counts (`4 x 40'HC` → `4`), and enforcing weight delta thresholds (`≤ 1.0 KG`).
  - **Reliability Escalation** (`escalation.py`): Enforces deterministic business rules for missing attachments, unreadable scans, wrong document types (e.g. commercial invoices), and placeholder tokens (`???`, `TBA`, `______`) with 100% auditable reason codes.

### 3. Confidence Scoring & Synonym-Dictionary Cross-Check (`extractor_text.py`)
To prevent silent extraction errors, BOB pairs generative AI extraction with an independent domain rule engine:
- **Dual-Engine Extraction**: For every document attachment, Gemini extracts the 7 canonical fields while an independent regex-based synonym dictionary parses the text against domain label variations (`"consignee"` / `"cnee"`, `"port of loading"` / `"load port"`, `"port of discharge"` / `"pod"`, `"gross weight"` / `"total weight"`).
- **Cross-Engine Reconciliation**: `reconcile_extractions()` normalizes both outputs and checks for semantic divergence across entity text, container numbers, ports, and numeric weights.
- **Stratified Confidence Scoring**: The `build_cross_check_confidence()` algorithm assigns calibrated confidence ratings per field:
  - **`0.99` (High Confidence)**: Gemini and the synonym dictionary rule parser extract identical normalized values.
  - **`0.85` (AI-Derived)**: Gemini successfully extracted a field from complex unstructured layout where keyword label patterns were absent.
  - **`0.55` (Disagreement / Ambiguity Signal)**: Gemini and the rule parser extracted conflicting values. This serves as an explicit uncertainty signal to flag potential ambiguity for human operators.
  - **`0.00` (Unresolved)**: The field is empty or contains placeholder tokens (`???`, `TBA`, `N/A`).

---

## 🧩 Challenges Faced

**Silent AI fallback under missing credentials.** Our classifier and extractor are designed to gracefully fall back to rules/dictionary logic if Gemini is unavailable — but this meant a misconfigured environment variable could let the entire pipeline run silently on rules-only logic with no visible error. We fixed this by adding explicit startup logging that reports whether AI classification is genuinely active, plus a `decided_by` field tracked per-email so we can always verify how many decisions were actually made by AI versus fallback rules.

**Rate limits at real dataset scale.** Processing the full 520-email dataset quickly hit free-tier Gemini rate limits. We built a resilient multi-key client pool with automatic key rotation and bounded cooldown cycles, plus per-email disk caching so an interrupted run resumes instead of re-processing everything from scratch.

**Over-eager document extraction on unreadable files.** Our vision-based fallback for scanned/image-only documents initially tried to extract *some* answer even from genuinely corrupted or illegible files, rather than admitting it couldn't read them — causing missed escalations. We refined the extraction prompt and validation logic so the system correctly flags truly unreadable documents instead of guessing.

**Inconsistent field labeling across documents.** Shipping Instructions and Bills of Lading frequently label the same field differently (e.g. "Port of Loading" vs. "Load Port"). We combined a synonym dictionary with AI-based extraction, using disagreement between the two as a signal for uncertainty rather than picking one silently.

**Classification edge cases.** Some routine operational emails mention shipping terminology without being genuine document-comparison requests. Identifying and correcting this required analyzing real misclassifications and refining the classifier's decision boundary accordingly.

---

## 🗺️ Future Roadmap

- Deploy the Streamlit operator dashboard as a standalone live service, rather than local-only, for real-time human review access
- Expand OCR/vision handling to cover a wider range of scanned and degraded document conditions
- Grow the field-synonym dictionary as more real-world label variants are encountered in production use
- Add multi-language support for non-English shipping documents
- Extend observability with dashboards tracking AI-vs-rule decision ratios and per-provider latency/error rates over time
- Support additional document types beyond SI/BL — packing lists, commercial invoices, certificates of origin — as outlined in the hackathon's advanced-stage challenges

---

## 📋 The 7 Canonical Comparison Fields

The system extracts and verifies the 7 canonical shipment fields between the Shipping Instruction (SI) and draft Bill of Lading (BL):

| Canonical Field | Data Type | Normalization & Verification Logic |
|---|---|---|
| `shipper` | Entity / Text | Uppercase alphanumeric comparison; strips legal suffixes and corporate punctuation variations. |
| `consignee` | Entity / Text | Normalizes buyer names; handles `"TO ORDER OF..."` negotiable BL variants. |
| `notify_party` | Entity / Text | Verified independently from consignee to prevent false cross-binding. |
| `port_of_loading` | Port / Location | Resolves UN/LOCODE codes (e.g., `(MYPKG)` vs `PORT KELANG`) and aliases to canonical names. |
| `port_of_discharge` | Port / Location | Normalizes destination aliases, strips country prefixes, collapses punctuation. |
| `container_count` | Numeric / Text | Regex extracts container totals (e.g., `4 x 40'HC` → `4`). |
| `gross_weight_kg` | Numeric (KG) | Strips units (LBS, MT, KG) & thousands separators; verifies delta `≤ 1.0 KG`. |

---

## 🔒 Auto-Reply Notifications & Safety Rails

When discrepancies are detected, BOB automatically creates a structured, sender-addressed clarification draft detailing the exact fields in dispute and requesting corrections.

### Dual-Lock Safety Architecture
To ensure test and benchmark addresses from sample datasets are **never** accidentally contacted:
1. **Structural Default (`actually_send=False`)**: All code paths, UI triggers, and API endpoints default to draft-mode only.
2. **Environment Variable Guard (`BOB_ALLOW_REAL_SEND`)**: Real SMTP transmission via `send_mismatch_email()` is structurally blocked at the code level unless `BOB_ALLOW_REAL_SEND=true` is explicitly set in `.env`.
3. **Local Audit Trail**: Generated emails are saved as readable `.txt` files inside `testing_generated_emails/` for inspection and demonstration.

---

## 📁 Project Structure

```text
averis-hackathon-bobthebuilder/
├── api/
│   ├── main.py                     # Production FastAPI REST microservice
│   ├── assistant.py                # Natural-language workspace query engine
│   ├── operator_state.py           # Human review audit trails & state store
│   ├── postgres_store.py           # Production PostgreSQL persistence
│   └── docs.html                   # Interactive visual API portal served at /docs
├── dashboard/
│   └── app.py                      # Local Streamlit visual review & inspection dashboard
├── frontend/                       # Web application served at /app
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── pipeline/
│   ├── classifier.py               # 5-class email classifier (Gemini 3.5 Flash Lite + regex pre-filter)
│   ├── gemini_client.py            # Resilient multi-key Gemini client pool with rate limiting
│   ├── extractor_text.py           # Canonical text extraction with synonym cross-check
│   ├── extractor_docs.py           # Multi-format doc parser (.pdf, .docx, .xlsx)
│   ├── explainer.py                # Gemini AI discrepancy explanation generator
│   ├── comparator.py               # Deterministic 7-field matching logic
│   ├── escalation.py               # Reliability escalation rules (wrong doc, unreadable, etc.)
│   ├── notification.py             # Auto-reply draft generator & dual-lock safety rails
│   ├── security.py                 # Anti-injection, PII redaction & attachment sanitization
│   └── runner.py                   # Complete pipeline orchestrator
├── data/                           # Hackathon inbox records and SI/BL attachments
├── testing_generated_emails/       # Local audit files of auto-generated mismatch drafts
├── test_api.py                     # Automated integration and endpoint test suite
├── test_assistant.py               # Workspace assistant test suite
├── run_pipeline.py                 # CLI entry point to process data & output submission.json
├── submission.json                 # Strictly validated competition submission file
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Production container image
└── README.md                       # Project documentation
```

---

## ☁️ Cloud & Container Deployment

### Running with Docker Locally:
```bash
docker build -t bob-sdoc .
docker run -p 8080:8080 -e GEMINI_API_KEY="your-gemini-key" bob-sdoc
```

### Production Railway Deployment:
The project is containerized and auto-deployed to Railway. The live deployment is available at:
👉 **[https://averis-hackathon-bobthebuilder-production.up.railway.app](https://averis-hackathon-bobthebuilder-production.up.railway.app)**

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. The competition dataset under `data/` was provided by the hackathon organizers and is not covered by this license (see [LICENSE](LICENSE) for the full attribution note).
