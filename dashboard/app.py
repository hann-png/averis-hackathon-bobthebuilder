"""
app.py — Streamlit Verification & Review Dashboard

Interactive web interface for logistics operators to:
- Monitor pipeline statistics (Stage 1, Stage 3, and Reliability metrics)
- Inspect flagged emails (MISMATCH and NEEDS_REVIEW)
- Compare SI vs BL documents side-by-side with highlighted defects
- Review unreadable, missing value, and wrong document escalations
- Approve or reject edge cases with human-in-the-loop review state
"""

import json
import os
import sys
from pathlib import Path

import streamlit as st

# Setup paths
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from pipeline.extractor_docs import extract_document
from pipeline.comparator import CANONICAL_FIELDS, _normalize_text, _normalize_port
from pipeline.notification import generate_mismatch_email, save_email_locally
from pipeline.security import scan_email_security
from data.loader import Inbox

st.set_page_config(
    page_title="Shipping Document Verification Dashboard",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1e293b, #0f172a);
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
    }
    .badge-mismatch {
        background-color: #ef4444;
        color: white;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 12px;
    }
    .badge-review {
        background-color: #f59e0b;
        color: black;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 12px;
    }
    .badge-ok {
        background-color: #10b981;
        color: white;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 12px;
    }
    .diff-cell-bad {
        background-color: rgba(239, 68, 68, 0.2);
        border-left: 4px solid #ef4444;
        padding: 8px;
    }
    .diff-cell-good {
        background-color: rgba(16, 185, 129, 0.1);
        border-left: 4px solid #10b981;
        padding: 8px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_data():
    sub_path = ROOT_DIR / "submission.json"
    inbox_dir = ROOT_DIR / "data" / "inbox"
    if not sub_path.exists():
        return {}, {}
    with open(sub_path, encoding="utf-8") as f:
        sub = json.load(f)

    emails = {}
    if inbox_dir.exists():
        for p in inbox_dir.glob("email_*.json"):
            eid = p.stem
            with open(p, encoding="utf-8") as fp:
                emails[eid] = json.load(fp)

    return sub, emails



@st.cache_data
def get_mismatch_explanation(si_fields: dict, bl_fields: dict, defect_fields: tuple) -> str:
    from pipeline.explainer import explain_mismatch
    return explain_mismatch(si_fields, bl_fields, list(defect_fields))

submission, emails = load_data()

if not submission:
    st.error("No `submission.json` found. Please run `python run_pipeline.py` first.")
    st.stop()

# Initialize session state for operator reviews
if "reviewed_items" not in st.session_state:
    st.session_state.reviewed_items = {}

# Sidebar filters
st.sidebar.title("🚢 SDOC Verification")
st.sidebar.markdown("Automated SI / BL comparison and routing")

category_filter = st.sidebar.multiselect(
    "Filter by Category",
    options=["ALL", "BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"],
    default=["ALL"],
)

status_filter = st.sidebar.multiselect(
    "Filter by Status",
    options=["ALL", "MISMATCH", "NEEDS_REVIEW", "OK"],
    default=["MISMATCH", "NEEDS_REVIEW"],
)

search_query = st.sidebar.text_input("Search Email ID or Subject", "")

# Metrics row
total = len(submission)
mismatch_count = sum(1 for v in submission.values() if v.get("status") == "MISMATCH")
review_count = sum(1 for v in submission.values() if v.get("status") == "NEEDS_REVIEW")
ok_count = sum(1 for v in submission.values() if v.get("status") == "OK")
reviewed_count = len(st.session_state.reviewed_items)

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Total Emails", total)
col2.metric("Mismatches Flagged", mismatch_count, delta=f"{mismatch_count/total*100:.1f}%")
col3.metric("Escalations (Review)", review_count, delta=f"{review_count/total*100:.1f}%")
col4.metric("Clean (OK)", ok_count)
col5.metric("Human Reviewed", f"{reviewed_count}/{mismatch_count + review_count}")
col6.metric("🛡️ Security Shield", "Active", delta="Zero-Trust", delta_color="normal")

st.markdown("---")

# Filter logic
filtered_eids = []
for eid, v in submission.items():
    cat = v.get("category", "")
    st_val = v.get("status", "")

    if "ALL" not in category_filter and cat not in category_filter:
        continue
    if "ALL" not in status_filter and st_val not in status_filter:
        continue

    em = emails.get(eid, {})
    subj = em.get("subject", "")
    if search_query:
        q = search_query.lower()
        if q not in eid.lower() and q not in subj.lower():
            continue

    filtered_eids.append(eid)

st.subheader(f"Showing {len(filtered_eids)} emails matching filter")

# Two-column layout: list on the left, details on the right
left_col, right_col = st.columns([1, 2])

with left_col:
    selected_eid = st.selectbox(
        "Select an email to inspect:",
        options=filtered_eids,
        format_func=lambda x: f"{x} - {submission[x].get('status')} [{submission[x].get('category')}]"
    )

    if selected_eid:
        item = submission[selected_eid]
        email_data = emails.get(selected_eid, {})
        st.markdown(f"**From:** `{email_data.get('from', 'N/A')}`")
        st.markdown(f"**Subject:** {email_data.get('subject', 'N/A')}")
        st.markdown(f"**Category:** `{item.get('category')}`")

        status = item.get("status")
        if status == "MISMATCH":
            st.markdown(f"<span class='badge-mismatch'>MISMATCH ({len(item.get('defect_fields', []))} defects)</span>", unsafe_allow_html=True)
            st.markdown(f"**Defect Fields:** {', '.join(item.get('defect_fields', []))}")
        elif status == "NEEDS_REVIEW":
            st.markdown(f"<span class='badge-review'>NEEDS_REVIEW: {item.get('review_reason')}</span>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='badge-ok'>OK</span>", unsafe_allow_html=True)

        is_reviewed = st.session_state.reviewed_items.get(selected_eid, False)
        new_reviewed = st.checkbox("Mark as Reviewed by Operator", value=is_reviewed, key=f"rev_{selected_eid}")
        st.session_state.reviewed_items[selected_eid] = new_reviewed

with right_col:
    if selected_eid:
        item = submission[selected_eid]
        email_data = emails.get(selected_eid, {})
        atts = email_data.get("attachments", [])

        st.markdown("### Document Inspection & Comparison")

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "Field Comparison",
            "Email Content",
            "Raw Attachments",
            "📧 Mismatch Notification Draft",
            "🛡️ Security Shield"
        ])

        with tab1:
            if item.get("category") != "BL_COMPARISON":
                st.info(f"This email was classified as `{item.get('category')}`. Document comparison is only performed on `BL_COMPARISON`.")
            elif len(atts) < 2:
                if item.get("status") == "NEEDS_REVIEW":
                    st.warning(f"Escalated with reason: `{item.get('review_reason')}`. Fewer than 2 attachments provided.")
                else:
                    st.info("Draft BL request email (0 attachments). No comparison required.")
            else:
                # Extract attachments for side-by-side view
                si_path = ROOT_DIR / "data" / atts[0]
                bl_path = ROOT_DIR / "data" / atts[1]
                if "_BL." in str(si_path) and "_SI." in str(bl_path):
                    si_path, bl_path = bl_path, si_path

                si_res = extract_document(str(si_path))
                bl_res = extract_document(str(bl_path))

                defects = set(item.get("defect_fields", []))

                # Display Gemini-generated Mismatch Explanation next to comparison
                if defects:
                    explanation = get_mismatch_explanation(si_res.fields, bl_res.fields, tuple(sorted(list(defects))))
                    st.markdown(
                        f'''<div style="background-color: rgba(239, 68, 68, 0.15); border-left: 5px solid #ef4444; border-radius: 8px; padding: 14px 16px; margin-bottom: 18px;">
                            <h4 style="margin: 0 0 6px 0; color: #ef4444;">?? AI Discrepancy Explanation</h4>
                            <p style="margin: 0; font-size: 15px; color: #f8fafc;">{explanation}</p>
                        </div>''',
                        unsafe_allow_html=True
                    )

                # Show extraction disagreement alert if present
                if getattr(si_res, "has_disagreement", False) or getattr(bl_res, "has_disagreement", False):
                    conflict_fields = list(set(getattr(si_res, "disagreement_fields", []) + getattr(bl_res, "disagreement_fields", [])))
                    if conflict_fields:
                        st.warning(f"?? **Extraction Discrepancy Detected:** AI and rules extractors differed on: {', '.join(conflict_fields)}")


                # Display table
                rows = []
                for f in CANONICAL_FIELDS:
                    si_v = si_res.fields.get(f, "—")
                    bl_v = bl_res.fields.get(f, "—")
                    has_diff = f in defects
                    diff_icon = "❌ MISMATCH" if has_diff else "✅ MATCH"
                    rows.append({
                        "Field": f.replace("_", " ").title(),
                        "Shipping Instruction (SI)": si_v,
                        "Bill of Lading (BL)": bl_v,
                        "Status": diff_icon,
                    })

                st.table(rows)

        with tab2:
            st.markdown(f"**From:** {email_data.get('from')}")
            st.markdown(f"**Subject:** {email_data.get('subject')}")
            st.text_area("Body", email_data.get("body", ""), height=300)

        with tab3:
            if not atts:
                st.write("No attachments.")
            else:
                for a in atts:
                    att_file = ROOT_DIR / "data" / a
                    st.markdown(f"#### `{a}` ({att_file.stat().st_size if att_file.exists() else 0} bytes)")
                    if str(att_file).endswith(".txt") and att_file.exists():
                        with open(att_file, encoding="utf-8", errors="replace") as fp:
                            st.code(fp.read(), language="text")
                    else:
                        st.info(f"Binary attachment ({att_file.suffix}). Extracted via specialized parser.")

        with tab4:
            if item.get("status") != "MISMATCH":
                st.info(f"Auto mismatch draft notifications are only generated for confirmed mismatches. This email status is `{item.get('status')}`.")
            elif len(atts) < 2:
                st.info("Insufficient attachments available to generate discrepancy details.")
            else:
                si_path = ROOT_DIR / "data" / atts[0]
                bl_path = ROOT_DIR / "data" / atts[1]
                if "_BL." in str(si_path) and "_SI." in str(bl_path):
                    si_path, bl_path = bl_path, si_path

                si_res = extract_document(str(si_path))
                bl_res = extract_document(str(bl_path))

                draft = generate_mismatch_email(
                    email_id=selected_eid,
                    email_data=email_data,
                    result=item,
                    si_fields=si_res.fields,
                    bl_fields=bl_res.fields,
                )

                if not draft:
                    st.warning("Could not identify original sender address from email metadata.")
                else:
                    st.markdown(f"**To (Original Sender):** `{draft['to']}`")
                    st.markdown(f"**Subject:** `{draft['subject']}`")
                    st.markdown(f"**Generated:** `{draft['generated_at']}`")
                    st.text_area("Notification Draft Body", draft["body"], height=320)

                    # Only local save button — structural safety rail prevents accidental real sending
                    if st.button("💾 Generate / Save Draft Locally", key=f"save_draft_{selected_eid}"):
                        saved_info = save_email_locally(draft, selected_eid)
                        st.success(f"Draft notification saved locally to: `{saved_info.get('path')}`")

        with tab5:
            st.markdown("#### 🛡️ Enterprise Zero-Trust Security & Compliance Audit")
            try:
                inbox_instance = Inbox(str(ROOT_DIR / "data"))
                sec_report = scan_email_security(inbox_instance, selected_eid)

                is_passed = sec_report.get("security_verdict") == "PASSED"
                badge_bg = "rgba(16, 185, 129, 0.15)" if is_passed else "rgba(239, 68, 68, 0.15)"
                badge_border = "#10b981" if is_passed else "#ef4444"
                verdict_text = sec_report.get("security_verdict", "PASSED")
                score = sec_report.get("posture_score", 100)

                st.markdown(
                    f'''<div style="background-color: {badge_bg}; border-left: 5px solid {badge_border}; border-radius: 8px; padding: 14px 18px; margin-bottom: 18px;">
                        <h4 style="margin: 0 0 4px 0; color: {badge_border};">🛡️ Posture: {verdict_text} (Score: {score}/100)</h4>
                        <p style="margin: 0; color: #cbd5e1; font-size: 13px;">SHA-256 Provenance Fingerprint: <code>{sec_report.get("email_sha256")}</code></p>
                    </div>''',
                    unsafe_allow_html=True
                )

                sec_col1, sec_col2 = st.columns(2)

                with sec_col1:
                    st.markdown("##### 🔍 Zero-Trust Attachment Sandbox")
                    att_reports = sec_report.get("attachment_reports", [])
                    if not att_reports:
                        st.info("No attachments found on this email record.")
                    else:
                        for ar in att_reports:
                            is_safe = ar.get("is_safe", True)
                            status_badge = "✅ CLEAN" if is_safe else "🚨 BLOCKED"
                            with st.expander(f"{status_badge} — {Path(ar.get('attachment', '')).name}"):
                                st.write(f"**MIME Detected:** `{ar.get('mime_detected')}`")
                                st.write(f"**SHA-256 Digest:** `{ar.get('sha256')}`")
                                if ar.get("threats"):
                                    for t in ar["threats"]:
                                        st.error(f"Threat: {t}")
                                else:
                                    st.success("Magic bytes verified. No malicious executables, macros, or zip bombs.")

                with sec_col2:
                    st.markdown("##### 🤖 Prompt Injection & PII Sanitization")
                    inj = sec_report.get("prompt_injection_check", {})
                    if inj.get("is_safe"):
                        st.success("✅ **Prompt Injection Guard:** Clean (No adversarial instructions detected)")
                    else:
                        st.error(f"🚨 **Adversarial Instruction Flagged:** Threat Level `{inj.get('threat_level')}`")
                        st.write(f"Patterns: `{inj.get('matched_patterns')}`")

                    pii = sec_report.get("pii_compliance", {})
                    pii_count = pii.get("pii_detected_count", 0)
                    if pii_count > 0:
                        st.warning(f"🔒 **PII Redaction Engine:** Masked {pii_count} sensitive entities for GDPR/SOC2 compliance.")
                        st.json(pii.get("breakdown", {}))
                    else:
                        st.info("🔒 **PII Redaction Engine:** Zero high-risk personal IDs or credit cards detected.")

                    with st.expander("👁️ View Redacted LLM-Safe Context"):
                        st.code(pii.get("redacted_preview", ""), language="text")

            except Exception as exc:
                st.error(f"Security audit scanner error: {exc}")

