# 🏆 Averis x Monash Hackathon 2026 — Team Submission & Action Checklist

This document is your step-by-step action checklist for everything our team needs to prepare, record, and submit before the preliminary round deadline.

---

## ⏰ Crucial Deadlines & Milestones

| Event / Milestone | Date & Time | Action Required |
|---|---|---|
| **Preliminary Round Submission Deadline** | **22nd September 2026 (12:00 p.m. noon)** | Submit the Google Form with all deliverables |
| **Finalist Shortlisting Announcement** | **24th September 2026** | Check Discord and email for top 10 announcement |
| **Final Pitch Day (Physical @ Monash)** | **26th September 2026** | 10-minute live pitch + 5-minute Q&A (All team members must attend in person) |

---

## 📝 1. Google Forms Submission Deliverables

Submission Google Form: **[https://forms.gle/nnam5eXrf5cjXdf3](https://forms.gle/nnam5eXrf5cjXdf3)**

### Deliverable 1: Team Details
- [ ] Team Name: *(e.g., Bob the Builder)*
- [ ] Team Representative Details (Name, personal email address, WhatsApp contact number).
- [ ] Resumes of all team members compiled into a single folder or PDF link (shared with "Anyone with the link can view").

### Deliverable 2: Project Name & Description
- [ ] **Project Name**: `BOB — Intelligent Shipping Document Verification & Discrepancy Management`
- [ ] **Project Summary / Description** *(Pre-drafted copy-paste summary)*:
  > *BOB is an end-to-end intelligent automation system designed to eliminate maritime inbox overload and prevent costly document errors. It automatically classifies incoming logistics emails, parses multi-format attachments (.txt, .pdf, .docx, .xlsx), extracts the 7 canonical shipping fields, performs deterministic zero-false-alarm comparison between Shipping Instructions (SI) and draft Bills of Lading (BL), generates plain-English AI discrepancy explanations using Gemini 2.0 Flash, composes automated clarification email drafts with dual-lock safety rails, and escalates ambiguous edge-cases for human review.*

### Deliverable 3: GitHub Repository Link
- [ ] **Public GitHub Link**: `https://github.com/hann-png/averis-hackathon-bobthebuilder`
- [ ] Verify repository visibility is set to **Public**.
- [ ] Verify that `README.md` is clean, readable, and contains setup instructions.

### Deliverable 4: Live Prototype / Cloud Demo Link
- [ ] **Live Prototype URL**: `https://averis-hackathon-bobthebuilder-production.up.railway.app`
- [ ] **Action on Railway**: Log in to Railway, navigate to the project settings, and add the environment variable:
  - Key: `GEMINI_API_KEY`
  - Value: `your-gemini-api-key`
  *(Note: Do NOT set `BOB_ALLOW_REAL_SEND` on Railway; outbound emails remain safely blocked).*

### Deliverable 5: 5-Minute Pitch Video Link
- [ ] Record a video demonstration (Strict maximum: **5 minutes 00 seconds**).
  > ⚠️ **Warning**: For every 30 seconds exceeding 5:00, 1 mark is deducted!
- [ ] Upload to YouTube as **Unlisted** or **Public** (Do NOT make it Private).
- [ ] **Required Video Structure**:
  1. **Quick Intro (0:00 - 0:30)**: Team name, project name ("BOB"), and member intros.
  2. **The Problem (0:30 - 1:15)**: Mixed inboxes, repetitive manual comparison of 7 fields, naming variances, consequences of missed discrepancies (fines, delays).
  3. **Architecture & Tech Stack (1:15 - 2:00)**: Python, FastAPI, Gemini 2.0 Flash, multi-format doc extractors, deterministic comparator, Railway cloud deployment.
  4. **Live Walkthrough Demo (2:00 - 4:00)**:
     - Open the live web app (`https://averis-hackathon-bobthebuilder-production.up.railway.app`).
     - Show email classification across 5 categories.
     - Show a `MISMATCH` shipment: highlight the 7-field table, the AI discrepancy explanation, and the auto-drafted clarification email.
     - Show an escalation case (`NEEDS_REVIEW`: missing attachment or unreadable PDF).
  5. **Impact & Future Roadmap (4:00 - 4:50)**: Time saved, zero false alarms, human-in-the-loop review safety, and future extensions (OCR for mobile scans, carrier EDI integration).

### Deliverable 6: Slide Deck / Documentation Link
- [ ] Create a slide deck on Google Slides (set permission: *"Anyone with the link → Viewer"*).
- [ ] **Required Slide Sections (per Hackathon Rubric)**:
  - Slide 1: Title & Team members.
  - Slide 2: Problem Statement & Stakeholder Impact.
  - Slide 3: Solution Overview & Value Proposition.
  - Slide 4: System Architecture & Data Flow (use the Mermaid diagram from README).
  - Slide 5: Technical Craftsmanship (AI Extraction + Deterministic Comparator + Dual-Lock Safety).
  - Slide 6: Key Features & Demo Screenshots.
  - Slide 7: Challenges Faced & How We Solved Them (e.g., handling messy formatting without false positives).
  - Slide 8: Future Roadmap & Commercial Viability.

---

## ✍️ 2. Written Question Responses (For the Google Form)

The submission form asks for written responses to several criteria. Here are talking points you can adapt:

### Q1: Problem-Solution Alignment & Stakeholder Value
- **Who it affects**: Shipping operators, freight forwarders, documentation clerks.
- **The pain**: Operations staff manually cross-checking hundreds of emails and documents daily. A single mismatch between SI and draft BL causes port hold-ups, customs penalties, and cargo re-routing.
- **The BOB solution**: Automates 90%+ of routine checks deterministically, freeing staff to focus solely on high-risk escalated exceptions.

### Q2: AI & Cloud Infrastructure Integration
- **AI Integration**: We leverage **Google Gemini 2.0 Flash** for fuzzy classification of complex incoming logistics correspondence, unstructured text extraction, and generating plain-English discrepancy explanations.
- **Cloud Infrastructure**: The system is containerized via Docker and deployed live on **Railway**, offering auto-scaling, high availability, and instant public accessibility for operators and judges.

### Q3: Technical Challenges Faced & How We Overcame Them
- **Challenge**: Relying purely on LLMs for field comparison leads to hallucinations and subtle numeric rounding errors (false alarms).
- **Our Solution**: A **hybrid AI-deterministic architecture**. AI handles unstructured extraction, while a pure Python comparator performs normalized alphanumeric and numeric matching (`≤ 1.0 KG` threshold), guaranteeing 100% precision with zero false alarms.

---

## 🏛️ 3. Physical Final Pitch Day Prep (26th September 2026)

If selected as a **Top 10 Finalist** (announced 24th September):
- [ ] **Mandatory Attendance**: All registered team members must be physically present at the Monash University Malaysia campus.
- [ ] **Pitch Timing**: 10 minutes live presentation & live demo + 5 minutes Q&A with judges.
- [ ] **Preparation**:
  - Test laptop display with HDMI projectors.
  - Keep a local backup of the app running (`uvicorn api.main:app` and `streamlit run dashboard/app.py`) in case venue Wi-Fi is slow.
  - Rehearse pitch transitions between team members to stay strictly under 10 minutes.
