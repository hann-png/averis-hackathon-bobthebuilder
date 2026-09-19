# ?? Shipping Document Verification Pipeline

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg?logo=python)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.40+-FF4B4B.svg?logo=streamlit)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An end-to-end intelligent automation system built for the **Shipping Document Verification** hackathon. It classifies logistics emails, extracts canonical fields from multi-format Shipping Instructions (SI) and Bills of Lading (BL) (`.txt`, `.pdf`, `.docx`, `.xlsx`), identifies field discrepancies with zero false alarms, generates human-readable AI discrepancy explanations, and reliably escalates edge-case exceptions for human review.

---

## ?? Live Prototype & Service Links

> ?? **Live Prototype URL**: `https://sdoc-verification-service-placeholder.run.app` *(Replace with deployed URL)*
>
> - **Interactive API Documentation Portal**: `/docs`
> - **Operator Web Interface**: `/app`
> - **Swagger UI**: `/swagger`

---

## ? Quick Start

### 1. Prerequisites
- Python 3.10+ (Python 3.11 or 3.12 recommended)
- Git

### 2. Installation
```bash
# 1. Clone the repository
git clone -b wei-hann https://github.com/hann-png/averis-hackathon-bobthebuilder.git
cd averis-hackathon-bobthebuilder

# 2. Create and activate virtual environment
python -m venv venv

# On Windows (PowerShell):
.env\Scripts\Activate.ps1
# On macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env and configure your GEMINI_API_KEY
```

### 3. Run Pipeline CLI
Process the entire inbox and generate a schema-compliant `submission.json`:

```bash
python run_pipeline.py --data data --output submission.json
```

Output:
```text
Loaded 520 emails from data
Pipeline complete: 520 emails processed
? Submission validated successfully
Submission saved to submission.json
```

---

## ? Key Features

- **AI-Primary Email Classification**: Uses Gemini 2.0 Flash as the primary classifier across 5 logistics categories (`BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, `SPAM`), with a cheap regex/domain pre-filter for obvious spam.
- **Multi-Format Document Extraction**: Extracts the 7 canonical shipping fields from `.txt`, `.pdf` (`pypdf`), `.docx` (`python-docx`), and `.xlsx` (`openpyxl`) attachments.
- **Synonym Dictionary Cross-Check**: Every text extraction is cross-checked against a domain-specific synonym dictionary. Conflicting extractions are treated as ambiguous signals and escalated for human review.
- **Pure Deterministic Comparison**: Document comparison is 100% deterministic Python string and numeric matching with unit normalization, guaranteeing zero false alarms.
- **AI Mismatch Explanations**: When a discrepancy is detected, Gemini 2.0 Flash generates a concise 1-2 sentence factual explanation (e.g., *"BL lists 4 containers but SI specifies 3"*), displayed in the operator review dashboard.
- **Deterministic Edge-Case Escalation**: Accurately flags and categorizes human-review cases into official competition reasons: `missing_attachment`, `wrong_doc_type`, `unreadable`, and `missing_value`.

---

## ?? Application & Dashboard Usage

### 1. Streamlit Operator Review Dashboard
Launch the visual human-in-the-loop inspection dashboard:

```bash
streamlit run dashboard/app.py
```
Open **`http://localhost:8501`** in your browser.

**Dashboard Features:**
- **Metrics Overview**: Real-time KPI cards for Total Emails, Flagged Mismatches, Review Queue, and Clean shipments.
- **Filter & Search**: Drill down by category (`BL_COMPARISON`, `SI_REQUEST`, etc.) and status (`MISMATCH`, `NEEDS_REVIEW`, `OK`).
- **Side-by-Side Field Diffing**: Canonical 7-field table highlighting SI vs. BL discrepancies in red.
- **AI Discrepancy Explanations**: Gemini callout cards explaining exact root-cause differences.
- **Raw Attachment Inspection**: Native preview of original `.txt`, `.pdf`, `.docx`, and `.xlsx` files.
- **Operator Review State**: Persistent checkbox tracking human reviews during verification sessions.

### 2. FastAPI Microservice
Start the production REST API server:

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```
Interactive API documentation is available at **`http://localhost:8080/docs`** and the Web UI at **`http://localhost:8080/app`**.

**Key Endpoints:**
- `GET /health`: Liveness and service heartbeat check
- `POST /process`: Triggers full pipeline execution on the dataset
- `GET /submission`: Retrieves cached `submission.json`
- `GET /email/{email_id}`: On-demand classification & verification for a single email
- `GET /stats`: Aggregated summary statistics across all processed shipments

---

## ?? System Architecture

```mermaid
flowchart TD
    A[Incoming Email Inbox] --> B0[Spam Pre-Filter<br/>Keyword & Domain Fast Filter]
    B0 -->|Obvious Spam| C1[SPAM - OK]
    B0 -->|Candidate Email| B[AI Email Classifier<br/>Gemini 2.0 Flash Primary<br/>Rule Fallback]
    
    B -->|SPAM| C1
    B -->|GENERAL| C2[GENERAL - OK]
    B -->|INVOICE_QUERY| C3[INVOICE_QUERY - OK]
    B -->|SI_REQUEST| C4[SI_REQUEST - OK]
    B -->|BL_COMPARISON| D[Escalation Gate 1<br/>Deterministic Attachment Check]
    
    D -->|< 2 atts & compare req| E1[NEEDS_REVIEW<br/>missing_attachment]
    D -->|0 atts draft request| E2[Status OK]
    D -->|SI + BL Available| F[Multi-Format Extractor<br/>Gemini AI Primary Extraction<br/>Synonym Dict Cross-Check]
    
    F -->|Detect Non-BL Doc| G1[NEEDS_REVIEW<br/>wrong_doc_type]
    F -->|Corrupt / Empty Scan| G2[NEEDS_REVIEW<br/>unreadable]
    F -->|Extract 7 Canonical Fields| H[Escalation Gate 2<br/>Deterministic Missing / Disagreement Check]
    
    H -->|Blank / TBA / Conflict| G3[NEEDS_REVIEW<br/>missing_value]
    H -->|All Fields Clean| I[Deterministic Comparator<br/>Pure Python String & Numeric Matching<br/>(Pure Deterministic Python)]
    
    I -->|Field Discrepancy Found| J1[MISMATCH<br/>has_defect: true]
    I -->|All 7 Fields Match| J2[OK<br/>has_defect: false]
    
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

## ?? The 7 Canonical Comparison Fields

The pipeline extracts and verifies the following 7 core fields between the Shipping Instruction (SI) and Bill of Lading (BL):

| Canonical Field | Type | Normalization & Matching Logic |
|---|---|---|
| `shipper` | Entity / Text | Uppercase alphanumeric comparison, ignores corporate punctuation & whitespace variations. |
| `consignee` | Entity / Text | Normalizes buyer details, resolves `"TO ORDER OF..."` variants. |
| `notify_party` | Entity / Text | Checked independently from consignee to avoid false binding. |
| `port_of_loading` | Port / Location | Strips UN/LOCODE port codes (e.g. `(MYPKG)` vs `PORT KELANG`) and matches primary name. |
| `port_of_discharge` | Port / Location | Resolves destination aliases and collapses punctuation differences. |
| `container_count` | Numeric / Text | Regex extracts package counts (e.g., `4 x 40'HC` ? `4`). |
| `gross_weight_kg` | Numeric (KG) | Strips units & thousands separators, verifies numeric delta `<= 1.0 KG`. |

---

## ?? Validation & Self-Evaluation

To evaluate your generated `submission.json` against the competition criteria without requiring private ground-truth files, validate results using the official hackathon evaluation server.

### 1. Using the Python Loader API (`loader.py`)
The `Inbox` helper connects directly to the local evaluation server over HTTP:

```python
from data.loader import Inbox

# Connect to the local evaluation server
inbox = Inbox("http://localhost:8080")

# Submit your generated submission dict and retrieve the live scoreboard
scoreboard = inbox.submit(submission)
print("Evaluation scoreboard:", scoreboard)
```

### 2. Using the CLI Entry Point
You can also generate and submit in a single command using the `--submit` flag:

```bash
python run_pipeline.py --data data --output submission.json --submit http://localhost:8080
```
This automatically posts your results to `/submit`, validates schema compliance, and saves the evaluation breakdown to `submission_scores.json`.

---

## ?? Project Structure

```text
sdoc/
??? api/
?   ??? main.py                     # FastAPI REST API service
?   ??? docs.html                   # Interactive API documentation portal
??? dashboard/
?   ??? app.py                      # Streamlit visual review & inspection dashboard
??? frontend/                       # Verity HTML/CSS/JS web application (served at /app)
?   ??? index.html
?   ??? styles.css
?   ??? app.js
??? pipeline/
?   ??? __init__.py
?   ??? classifier.py               # AI-primary email classifier (Gemini 2.0 + spam filter)
?   ??? extractor_text.py           # Gemini 2.0 canonical extractor + synonym cross-check
?   ??? extractor_docs.py           # Multi-format parser (.pdf, .docx, .xlsx)
?   ??? explainer.py                # Gemini AI discrepancy explanation generator
?   ??? comparator.py               # Pure deterministic Python field matcher
?   ??? escalation.py               # Edge-case detector (missing docs, unreadable, etc.)
?   ??? runner.py                   # End-to-end pipeline orchestrator
??? data/                           # Hackathon inbox records and document attachments
??? run_pipeline.py                 # CLI entry point to run pipeline & generate submission.json
??? submission.json                 # Output submission adhering to the required schema
??? requirements.txt                # Python package dependencies
??? Dockerfile                      # Production container image
??? README.md                       # Comprehensive documentation
```

---

## ?? Docker & Cloud Deployment

### Build and Run Docker Container Locally:
```bash
docker build -t sdoc-verification .
docker run -p 8080:8080 -e GEMINI_API_KEY="your-key" sdoc-verification
```

### Deploy to Google Cloud Run:
The production service is packaged via `Dockerfile` and can be deployed directly to Cloud Run or any container host:

```bash
# Direct deployment to Cloud Run
gcloud run deploy sdoc-verification-service   --source .   --region us-central1   --platform managed   --allow-unauthenticated   --set-env-vars GEMINI_API_KEY="your-gemini-api-key"
```
*(Note: Requires a linked GCP billing account and Cloud Run/Build APIs enabled).*

---

## ?? License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
