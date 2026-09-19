# 🚢 BOB Document Verification — Team Architecture & Codebase Guide

Welcome to the internal technical architecture guide for **BOB (Bill of Lading Verification System)**! This document explains how the entire project works, what every file and folder does, key design choices, critical rules to observe, and how everything connects together.

---

## 🎯 1. The Core Problem We Are Solving

In global shipping operations, shipping coordinators face two huge operational bottlenecks:
1. **Inbox Overload**: The same inbox receives thousands of mixed emails — document-checking requests, new shipping instruction (SI) requests, invoice queries, operational updates, and spam.
2. **Manual Discrepancy Checking**: For document verification requests, staff manually read two documents:
   - **Shipping Instruction (SI)**: The source of truth containing intended shipment details.
   - **Draft Bill of Lading (BL)**: The carrier's draft document that must match the SI before issuance.
   Staff must compare **7 canonical fields** (Shipper, Consignee, Notify Party, Port of Loading, Port of Discharge, Container Count, Gross Weight). Human comparison is slow, repetitive, and error-prone.
3. **Ambiguity & Discrepancies**: Different documents use different names (e.g., `"Port of Loading"` vs `"Load Port"`, `"MYPKG"` vs `"PORT KELANG"`).
4. **Actioning Mismatches**: When discrepancies exist, operations staff must draft clarification emails to senders asking for corrections.

**BOB automates this entire pipeline end-to-end with zero false alarms, AI-powered natural-language explanations, automated draft notifications, and deterministic human-in-the-loop escalation.**

---

## 🧱 2. End-to-End System Data Flow

```
[Incoming Email Inbox (520 Emails)]
          │
          ▼
1. Spam Pre-Filter (Regex & Blacklist) ──(Spam)──► Status: OK, Category: SPAM
          │ (Legitimate Email)
          ▼
2. AI Classifier (Gemini 2.0 Flash) ──► Category: SI_REQUEST, INVOICE_QUERY, GENERAL
          │ (BL_COMPARISON)
          ▼
3. Escalation Gate 1 (Attachment Count Check)
   ├── 0 attachments (Draft request) ──► Status: OK
   └── < 2 attachments (Comparison requested) ──► Status: NEEDS_REVIEW [missing_attachment]
          │ (SI + BL attachments present)
          ▼
4. Multi-Format Extractor (.txt, .pdf, .docx, .xlsx)
   ├── Non-BL document detected ──► Status: NEEDS_REVIEW [wrong_doc_type]
   ├── Corrupted / unreadable file ──► Status: NEEDS_REVIEW [unreadable]
   └── Extract 7 Canonical Fields (AI + Synonym Dictionary)
          │
          ▼
5. Escalation Gate 2 (Missing Value Check)
   └── Missing required value / "TBA" / "N/A" ──► Status: NEEDS_REVIEW [missing_value]
          │ (All 7 fields extracted cleanly)
          ▼
6. Deterministic Comparator (Pure Python)
   ├── Discrepancy Found ──► Status: MISMATCH, has_defect: true, defect_fields: [...]
   │        │
   │        ├──► 7. Gemini AI Discrepancy Explainer (1-2 sentence plain-English summary)
   │        └──► 8. Notification Engine (Drafts sender-addressed clarification email)
   │
   └── All 7 Fields Match ──► Status: OK, has_defect: false
          │
          ▼
[submission.json & Live Web UIs]
```

---

## 📂 3. Folder & File Directory Map

Here is the exact breakdown of every file in our repository and what it does:

### 🌐 `api/` — Production REST Backend
- **[`api/main.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/api/main.py)**: The FastAPI service entrypoint.
  - Mounts the Verity Web App at `/app` (and redirects `/` to `/app`).
  - Serves interactive visual API documentation at `/docs`.
  - Exposes REST endpoints: `/health`, `/stats`, `/submission`, `/email/{email_id}`, `/email/{email_id}/notification`, and `/email/{email_id}/notification/send`.
- **[`api/docs.html`](file:///c:/Users/WeiHann/Documents/hackathon/averis/api/docs.html)**: Interactive visual API documentation portal.

### 📊 `dashboard/` — Internal Operator Review Dashboard
- **[`dashboard/app.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/dashboard/app.py)**: A Streamlit visual inspection app.
  - Allows operators to filter shipments by category and status.
  - Renders side-by-side color-coded SI vs BL comparison tables.
  - Displays Gemini-generated discrepancy explanation callouts.
  - Contains the **"📧 Mismatch Notification Draft"** tab to view drafted emails and save them locally with a single click.

### 🖥️ `frontend/` — Verity Web Application
- **`frontend/index.html`**, **`styles.css`**, **`app.js`**:
  - The primary web portal deployed on Railway.
  - Communicates directly with the FastAPI endpoints.
  - Renders shipment KPI cards, filterable tables, search bars, and detailed inspection drawers.

### ⚙️ `pipeline/` — The Core Automation Engine
This is the heart of the project. Every file has a single, well-defined responsibility:
- **[`pipeline/classifier.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/pipeline/classifier.py)**:
  - Classifies incoming emails into 5 categories: `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, `SPAM`.
  - Architecture: Fast regex pre-filter for obvious spam ➔ Gemini 2.0 Flash primary classification ➔ domain rules fallback.
- **[`pipeline/extractor_text.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/pipeline/extractor_text.py)**:
  - Extracts the 7 canonical fields from plain-text attachments (`.txt`).
  - Employs a comprehensive logistics synonym dictionary (resolving `"Port of Loading"`, `"POL"`, `"Load Port"`, etc.).
- **[`pipeline/extractor_docs.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/pipeline/extractor_docs.py)**:
  - Specialized parser for binary and multi-format attachments:
    - `.pdf`: Parsed via `pypdf` with corruption/blank scan detection.
    - `.docx`: Parsed via `python-docx` traversing paragraphs and tables.
    - `.xlsx`: Parsed via `openpyxl` extracting structured cell grids.
- **[`pipeline/comparator.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/pipeline/comparator.py)**:
  - **100% Deterministic Python Comparison** between SI and BL fields.
  - Normalizes corporate punctuation, resolves UN/LOCODE port codes, normalizes units (KG vs MT vs LBS), and extracts package numbers.
  - Guarantees zero hallucinated defects or false alarms.
- **[`pipeline/escalation.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/pipeline/escalation.py)**:
  - Implements the 4 official competition escalation reasons for human review:
    1. `missing_attachment`: Comparison requested but fewer than 2 attachments provided.
    2. `wrong_doc_type`: Attachment is a Commercial Invoice, Packing List, Certificate of Origin, etc.
    3. `unreadable`: Corrupt PDF stream or empty/blank scan.
    4. `missing_value`: Critical field contains placeholders like `"TBA"`, `"N/A"`, `"_______"`, or is empty.
- **[`pipeline/explainer.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/pipeline/explainer.py)**:
  - Uses Gemini 2.0 Flash to generate concise 1-2 sentence human-readable explanations of detected discrepancies.
- **[`pipeline/notification.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/pipeline/notification.py)**:
  - Generates structured, professional mismatch clarification emails addressed to the original sender.
  - Includes **Dual-Lock Safety Rails** (defaults to `actually_send=False` and blocks SMTP unless `BOB_ALLOW_REAL_SEND=true`).
  - Stores local audit records in `testing_generated_emails/`.
  - Includes standalone local test runner (`run_local_test()`).
- **[`pipeline/runner.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/pipeline/runner.py)**:
  - The orchestrator connecting: Classifier ➔ Attachment Identification ➔ Extractor ➔ Escalation ➔ Comparator ➔ Notification.
  - Runs across all 520 inbox emails.

### 🧪 Root Files & Configurations
- **[`test_api.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/test_api.py)**: Automated test suite verifying health, stats, schema, single email inspection, notification drafts, and safety rails.
- **[`run_pipeline.py`](file:///c:/Users/WeiHann/Documents/hackathon/averis/run_pipeline.py)**: CLI command to process `data/` and output `submission.json`.
- **[`submission.json`](file:///c:/Users/WeiHann/Documents/hackathon/averis/submission.json)**: The final generated output adhering strictly to the competition JSON schema.
- **[`Dockerfile`](file:///c:/Users/WeiHann/Documents/hackathon/averis/Dockerfile)**: Multi-stage production container image for cloud deployment.
- **[`.env.example`](file:///c:/Users/WeiHann/Documents/hackathon/averis/.env.example)**: Template for environment keys (`GEMINI_API_KEY`, optional settings).
- **[`README.md`](file:///c:/Users/WeiHann/Documents/hackathon/averis/README.md)**: The public project documentation.

---

## 🔒 4. Critical Technical Rules & Things to Note

1. **Strict `submission.json` Schema**:
   The evaluation server expects every email entry to contain **only** these exact keys:
   ```json
   {
     "category": "BL_COMPARISON",
     "status": "MISMATCH",
     "review_reason": null,
     "has_defect": true,
     "defect_fields": ["container_count", "gross_weight_kg"]
   }
   ```
   **Never** add internal debugging fields (like `decided_by` or `raw_text`) into `submission.json`.

2. **Ground-Truth Secrecy**:
   The repository must **never** contain private answer keys, `scoring.py`, or claims of benchmark scores (`"1.0000"`). We removed those to ensure academic integrity and avoid disqualification.

3. **Dual-Lock Email Safety Rail**:
   The sample dataset contains real company domains and email addresses. **Never send real emails to addresses from this dataset**.
   - `actually_send` defaults to `False` everywhere.
   - `BOB_ALLOW_REAL_SEND` must remain unset/false in `.env`, `.env.example`, and on Railway.

4. **Hybrid AI Architecture**:
   - We use AI where it excels: Fuzzy classification, unstructured document extraction, and plain-English discrepancy summaries.
   - We use Deterministic Python where accuracy is non-negotiable: Checking attachment count, identifying placeholders, and comparing field values.

---

## 🛠️ 5. Team Quick Reference Commands

```bash
# 1. Run all API & safety tests:
python test_api.py

# 2. Run standalone notification test cases:
python -m pipeline.notification

# 3. Run the full pipeline on dataset:
python run_pipeline.py --data data --output submission.json

# 4. Start local FastAPI web service:
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
# (Visit: http://localhost:8080)

# 5. Start local Streamlit dashboard:
streamlit run dashboard/app.py
# (Visit: http://localhost:8501)
```
