(() => {
  "use strict";

  const CONFIG = window.SDOC_CONFIG || {};
  const FIELDS = [
    ["shipper", "Shipper"],
    ["consignee", "Consignee"],
    ["notify_party", "Notify party"],
    ["port_of_loading", "Port of loading"],
    ["port_of_discharge", "Port of discharge"],
    ["container_count", "Container count"],
    ["gross_weight_kg", "Gross weight (kg)"]
  ];

  const FALLBACK_EMAIL = {
    email_id: "email_004",
    from: "docs@vitalsolutions.sg",
    subject: "REQUEST BL DRAFT _ PO 26067_ COATED IVORY BOARD__138MT",
    body: "Hi Mitchelle,\n\nAttached are the SI and draft BL for OC 5ALT-01226 (COATED IVORY BOARD). Please check the details and confirm.\n\nBest Regards,\nDeswita Elvyani\nShipping Documentation\nDID : +971 04 4938298\nAPRIL Fine Paper Trading (Middle East) Fze\n#813, 4 EA, Dubai Airport Free Zone\nP.O. Box : 293775, Dubai, United Arab Emirates\nWebsite : www.aprilasia.com | www.paperone.com",
    attachments: ["attachments/email_004_SI.txt", "attachments/email_004_BL.txt"]
  };

  function buildFallbackSubmission() {
    const categories = index => index <= 220 ? "BL_COMPARISON" : index <= 345 ? "SI_REQUEST" : index <= 420 ? "INVOICE_QUERY" : index <= 480 ? "GENERAL" : "SPAM";
    const reviewReasons = ["wrong_doc_type", "missing_attachment", "unreadable", "missing_value"];
    const defectSets = [["container_count"], ["gross_weight_kg"], ["port_of_discharge"], ["shipper"], ["consignee", "notify_party"]];
    const result = {};
    for (let index = 1; index <= 520; index += 1) {
      const id = `email_${String(index).padStart(3, "0")}`;
      const review = index >= 201 && index <= 220;
      const mismatch = index <= 46;
      result[id] = {
        category: categories(index),
        status: review ? "NEEDS_REVIEW" : mismatch ? "MISMATCH" : "OK",
        review_reason: review ? reviewReasons[(index - 201) % reviewReasons.length] : null,
        has_defect: mismatch,
        defect_fields: mismatch ? defectSets[(index - 1) % defectSets.length] : []
      };
    }
    result.email_004.defect_fields = ["consignee", "notify_party"];
    return result;
  }

  const FALLBACK_SUBMISSION = buildFallbackSubmission();

  const FALLBACK_FIELDS = {
    si: {
      shipper: "APRIL FAR EAST (M) SDN BHD",
      consignee: "EAST BRIGHT FZ-LLC",
      notify_party: "EAST BRIGHT FZ-LLC",
      port_of_loading: "NANTONG, CHINA (CNNTG)",
      port_of_discharge: "KARACHI, PAKISTAN (PKKHI)",
      container_count: "6 x 40'HC",
      gross_weight_kg: "131,058 KG"
    },
    bl: {
      shipper: "APRIL FAR EAST (M) SDN BHD",
      consignee: "UAB NOVAKOPA",
      notify_party: "UAB NOVAKOPA",
      port_of_loading: "NANTONG, CHINA (CNNTG)",
      port_of_discharge: "KARACHI, PAKISTAN (PKKHI)",
      container_count: "6 x 40'HC",
      gross_weight_kg: "131,058 KG"
    }
  };

  const state = {
    submission: {},
    stats: null,
    emails: new Map([[FALLBACK_EMAIL.email_id, FALLBACK_EMAIL]]),
    fields: new Map([[FALLBACK_EMAIL.email_id, FALLBACK_FIELDS]]),
    reviewed: new Set(JSON.parse(localStorage.getItem("sdoc-reviewed") || "[]")),
    drafts: new Map(),
    selectedId: "email_004",
    statusFilter: "FLAGGED",
    categoryFilter: "ALL",
    search: "",
    visibleCount: 20,
    source: "Demo data"
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
  const titleCase = (value = "") => value.toLowerCase().replace(/_/g, " ").replace(/\b\w/g, char => char.toUpperCase());
  const displaySubject = (value = "") => String(value).replace(/_+/g, " ").replace(/\s+/g, " ").trim();
  const formatId = (id = "") => id.toUpperCase();
  const percent = (value, total) => total ? `${(value / total * 100).toFixed(1)}%` : "0.0%";
  const statusClass = status => status === "MISMATCH" ? "mismatch" : status === "NEEDS_REVIEW" ? "review" : "ok";
  const statusLabel = status => status === "NEEDS_REVIEW" ? "Review" : status === "MISMATCH" ? "Mismatch" : "Clean";

  function showToast(message, tone = "success") {
    const toast = $("#toast");
    $("#toastText").textContent = message;
    $(".toast-icon", toast).style.background = tone === "warning" ? "var(--amber)" : tone === "error" ? "var(--red)" : "var(--green)";
    toast.classList.add("visible");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove("visible"), 2600);
  }

  async function fetchJson(url, timeout = 2200, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        cache: "no-store",
        headers: { Accept: "application/json", ...(options.headers || {}) }
      });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadSubmission() {
    const apiBase = (CONFIG.apiBase || "").replace(/\/$/, "");
    const attempts = [
      apiBase && `${apiBase}/submission`,
      CONFIG.submissionPath || "../submission.json"
    ].filter(Boolean);

    for (const url of attempts) {
      try {
        const submission = await fetchJson(url);
        if (submission && Object.keys(submission).length) {
          state.source = url.includes("/submission") ? "Live API" : "Local dataset";
          return submission;
        }
      } catch (_) { /* try next source */ }
    }
    state.source = "Preview data";
    return FALLBACK_SUBMISSION;
  }

  function computeStats(submission) {
    const all = Object.values(submission);
    const categories = {};
    const statuses = {};
    const review_reasons = {};
    const defect_fields_breakdown = {};
    all.forEach(item => {
      categories[item.category] = (categories[item.category] || 0) + 1;
      statuses[item.status] = (statuses[item.status] || 0) + 1;
      if (item.review_reason) review_reasons[item.review_reason] = (review_reasons[item.review_reason] || 0) + 1;
      (item.defect_fields || []).forEach(field => defect_fields_breakdown[field] = (defect_fields_breakdown[field] || 0) + 1);
    });
    return { total_emails: all.length, categories, statuses, review_reasons, total_defects: statuses.MISMATCH || 0, defect_fields_breakdown };
  }

  async function loadEmail(emailId) {
    if (state.emails.has(emailId)) return state.emails.get(emailId);
    const url = `${String(CONFIG.dataBase || "../data").replace(/\/$/, "")}/inbox/${emailId}.json`;
    try {
      const email = await fetchJson(url, 3000);
      state.emails.set(emailId, email);
      return email;
    } catch (_) {
      const generic = {
        email_id: emailId,
        from: "Source email unavailable in API response",
        subject: `${titleCase(state.submission[emailId]?.category || "Email")} — ${formatId(emailId)}`,
        body: "Serve this frontend from the repository root to load the source email body and attachments.",
        attachments: []
      };
      state.emails.set(emailId, generic);
      return generic;
    }
  }

  async function loadText(path) {
    const base = String(CONFIG.dataBase || "../data").replace(/\/$/, "");
    const response = await fetch(`${base}/${path}`, { cache: "no-store" });
    if (!response.ok) throw new Error("Attachment unavailable");
    return response.text();
  }

  function parseFields(text) {
    const patterns = {
      shipper: /^(?:shipper)\s*:\s*(.+)$/im,
      consignee: /^(?:consignee(?:\s*\([^)]*\))?|to\s+the\s+order\s+of|cnee)\s*:\s*(.+)$/im,
      notify_party: /^(?:notify(?:\s+party)?|intermediate\s+consignee)\s*:\s*(.+)$/im,
      port_of_loading: /^(?:port\s+of\s+loading(?:\s*\([^)]*\))?|load\s+port|pol)\s*:\s*(.+)$/im,
      port_of_discharge: /^(?:port\s+of\s+discharge(?:\s*\([^)]*\))?|discharge\s+port|pod)\s*:\s*(.+)$/im,
      container_count: /^(?:total\s+containers?|container\s+count|no\.?\s+of\s+containers?)\s*:\s*(.+)$/im,
      gross_weight_kg: /^(?:gross\s+(?:wt|weight)(?:\s*\([^)]*\))?|gross\s+weight\s+kg)\s*:\s*(.+)$/im
    };
    return Object.fromEntries(Object.entries(patterns).map(([field, regex]) => [field, (text.match(regex)?.[1] || "Not extracted").trim()]));
  }

  async function loadComparison(emailId, email) {
    if (state.fields.has(emailId)) return state.fields.get(emailId);
    const attachments = email.attachments || [];
    const textAttachments = attachments.filter(path => /\.txt$/i.test(path));
    if (textAttachments.length < 2) return { si: {}, bl: {} };

    let siPath = textAttachments.find(path => /_SI(?:[._])/i.test(path)) || textAttachments[0];
    let blPath = textAttachments.find(path => /_BL(?:[._])/i.test(path)) || textAttachments[1];
    try {
      const [siText, blText] = await Promise.all([loadText(siPath), loadText(blPath)]);
      const result = { si: parseFields(siText), bl: parseFields(blText) };
      state.fields.set(emailId, result);
      return result;
    } catch (_) {
      return { si: {}, bl: {} };
    }
  }

  function renderStats() {
    const stats = state.stats;
    const total = stats.total_emails || 0;
    const mismatch = stats.statuses.MISMATCH || 0;
    const review = stats.statuses.NEEDS_REVIEW || 0;
    const clean = stats.statuses.OK || 0;
    $("#totalStat").textContent = total.toLocaleString();
    $("#mismatchStat").textContent = mismatch.toLocaleString();
    $("#reviewStat").textContent = review.toLocaleString();
    $("#cleanStat").textContent = clean.toLocaleString();
    $("#mismatchRate").textContent = percent(mismatch, total);
    $("#reviewRate").textContent = percent(review, total);
    $("#cleanRate").textContent = percent(clean, total);
    $("#navMismatchCount").textContent = mismatch;
    $("#navReviewCount").textContent = review;
    $("#dataSourceLabel").textContent = state.source;
    $("#connectionDot").classList.toggle("offline", state.source === "Preview data");
  }

  function filteredIds() {
    const query = state.search.toLowerCase();
    return Object.entries(state.submission).filter(([id, item]) => {
      const statusMatch = state.statusFilter === "ALL" ||
        (state.statusFilter === "FLAGGED" && ["MISMATCH", "NEEDS_REVIEW"].includes(item.status)) ||
        item.status === state.statusFilter;
      const categoryMatch = state.categoryFilter === "ALL" || item.category === state.categoryFilter;
      const email = state.emails.get(id);
      const queryMatch = !query || id.toLowerCase().includes(query) ||
        (email?.subject || "").toLowerCase().includes(query) ||
        (email?.from || "").toLowerCase().includes(query);
      return statusMatch && categoryMatch && queryMatch;
    }).map(([id]) => id).sort((a, b) => {
      if (a === state.selectedId) return -1;
      if (b === state.selectedId) return 1;
      const priority = { NEEDS_REVIEW: 0, MISMATCH: 1, OK: 2 };
      return priority[state.submission[a].status] - priority[state.submission[b].status] || a.localeCompare(b, undefined, { numeric: true });
    });
  }

  function renderQueue() {
    const ids = filteredIds();
    const shown = ids.slice(0, state.visibleCount);
    const queue = $("#queueList");
    $("#resultCount").textContent = `${ids.length} ${ids.length === 1 ? "case" : "cases"}`;
    $("#queueRange").textContent = ids.length ? `Showing 1–${Math.min(shown.length, ids.length)} of ${ids.length}` : "No results";
    $("#loadMoreButton").hidden = shown.length >= ids.length;

    if (!ids.length) {
      queue.innerHTML = `<div class="empty-state"><div><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg><strong>No matching emails</strong><p>Try a different search or filter.</p></div></div>`;
      return;
    }

    queue.innerHTML = shown.map((id, index) => {
      const item = state.submission[id];
      const email = state.emails.get(id);
      const cls = statusClass(item.status);
      const secondary = item.status === "NEEDS_REVIEW" ? titleCase(item.review_reason) : titleCase(item.category);
      return `<button class="queue-item ${cls} ${id === state.selectedId ? "active" : ""}" style="--item-index:${index}" type="button" data-email-id="${escapeHtml(id)}">
        <div class="queue-item-top"><strong>${escapeHtml(formatId(id))}</strong><span class="status-chip ${cls}">${statusLabel(item.status)}</span></div>
        <p class="queue-subject" title="${escapeHtml(email?.subject || "")}">${escapeHtml(displaySubject(email?.subject) || titleCase(item.category))}</p>
        <div class="queue-item-bottom"><span>${escapeHtml(email?.from || secondary)}</span><span>${item.defect_fields?.length ? `${item.defect_fields.length} issue${item.defect_fields.length > 1 ? "s" : ""}` : secondary}</span></div>
      </button>`;
    }).join("");

    $$(".queue-item", queue).forEach(button => button.addEventListener("click", () => selectEmail(button.dataset.emailId)));
  }

  function resultCopy(item) {
    const count = item.defect_fields?.length || 0;
    if (item.status === "MISMATCH") return {
      title: `${count} ${count === 1 ? "discrepancy" : "discrepancies"} detected`,
      text: `${(item.defect_fields || []).map(titleCase).join(" and ")} ${count === 1 ? "requires" : "require"} attention before this draft is finalized.`
    };
    if (item.status === "NEEDS_REVIEW") return {
      title: "Human review required",
      text: `The workflow stopped safely because of: ${titleCase(item.review_reason || "uncertain result")}.`
    };
    return { title: "No mismatch detected", text: "All available comparison fields match the shipping instruction." };
  }

  function apiUrl(path) {
    return `${String(CONFIG.apiBase || window.location.origin).replace(/\/$/, "")}${path}`;
  }

  function renderDraftLoading() {
    $("#draftComposer").innerHTML = `<div class="draft-loading" aria-label="Loading response draft">
      <div class="draft-loading-head"><span class="skeleton"></span><span class="skeleton"></span></div>
      <span class="skeleton draft-loading-line"></span><span class="skeleton draft-loading-line short"></span>
      <div class="skeleton draft-loading-body"></div>
    </div>`;
  }

  function renderDraftError(message) {
    $("#draftComposer").innerHTML = `<div class="draft-empty">
      <span class="draft-empty-icon"><svg viewBox="0 0 24 24"><path d="M12 9v4m0 4h.01"/><circle cx="12" cy="12" r="9"/></svg></span>
      <div><strong>Draft unavailable</strong><p>${escapeHtml(message || "The notification service could not be reached.")}</p></div>
      <button class="secondary-button" type="button" data-draft-action="retry">Try again</button>
    </div>`;
  }

  function renderDraft(draft) {
    const fields = (draft.defect_fields || []).map(field => `<span>${escapeHtml(titleCase(field))}</span>`).join("");
    const generatedDate = draft.generated_at ? new Date(draft.generated_at) : null;
    const generatedAt = generatedDate && !Number.isNaN(generatedDate.getTime())
      ? generatedDate.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
      : "Generated now";
    $("#draftComposer").innerHTML = `<article class="draft-composer">
      <header class="draft-composer-head">
        <div class="draft-heading">
          <span class="draft-mark"><svg viewBox="0 0 24 24"><path d="M4 19.5V5a2 2 0 0 1 2-2h8l6 6v10.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19.5Z"/><path d="M14 3v6h6M8 14h8M8 17h5"/></svg></span>
          <div><p class="eyebrow">Clarification email</p><h3>Response draft</h3></div>
        </div>
        <div class="draft-state"><span></span>Draft only · Not sent</div>
      </header>

      <div class="draft-evidence">
        <div><strong>${(draft.defect_fields || []).length} ${(draft.defect_fields || []).length === 1 ? "field" : "fields"} included</strong><p>The detected differences are locked to the verification result.</p></div>
        <div class="draft-field-chips">${fields}</div>
      </div>

      <div class="draft-address-row"><span>To</span><strong>${escapeHtml(draft.recipient || "Recipient unavailable")}</strong><i>Original sender</i></div>
      <div class="draft-address-row"><span>Subject</span><strong>${escapeHtml(draft.subject || "Shipping document clarification")}</strong></div>
      <div class="draft-body-wrap">
        <div class="draft-body-toolbar"><span>Message</span><small>${escapeHtml(generatedAt)}</small></div>
        <textarea id="draftBody" readonly spellcheck="false" aria-label="Generated response draft">${escapeHtml(draft.body || "")}</textarea>
      </div>

      <footer class="draft-actions">
        <p><svg viewBox="0 0 24 24"><path d="M12 3 4 6v6c0 5 3.4 8 8 9 4.6-1 8-4 8-9V6l-8-3Z"/><path d="m9 12 2 2 4-4"/></svg>Saving creates a local draft only. No email will be sent.</p>
        <div>
          <button class="secondary-button" type="button" data-draft-action="regenerate"><svg viewBox="0 0 24 24"><path d="M20 6v5h-5M4 18v-5h5"/><path d="M18.5 9A7 7 0 0 0 6 6.5L4 9m2 6a7 7 0 0 0 12 2.5l2-2.5"/></svg>Regenerate</button>
          <button class="secondary-button" type="button" data-draft-action="copy"><svg viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>Copy</button>
          <button class="primary-button" type="button" data-draft-action="save"><svg viewBox="0 0 24 24"><path d="M5 3h12l2 2v16H5Z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/></svg><span>Save draft</span></button>
        </div>
      </footer>
    </article>`;
  }

  async function loadDraft(emailId, options = {}) {
    const item = state.submission[emailId];
    if (!item || item.status !== "MISMATCH") return;
    if (!options.force && state.drafts.has(emailId)) {
      renderDraft(state.drafts.get(emailId));
      return;
    }
    renderDraftLoading();
    try {
      const draft = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/notification`), 8000);
      if (state.selectedId !== emailId) return;
      if (!draft.notification_eligible) throw new Error("This email is not eligible for a clarification draft.");
      state.drafts.set(emailId, draft);
      renderDraft(draft);
    } catch (error) {
      if (state.selectedId === emailId) renderDraftError(error.name === "AbortError" ? "The draft service took too long to respond." : error.message);
    }
  }

  async function copyDraft() {
    const draft = state.drafts.get(state.selectedId);
    if (!draft) return;
    const content = `To: ${draft.recipient || ""}\nSubject: ${draft.subject || ""}\n\n${draft.body || ""}`;
    await navigator.clipboard?.writeText(content);
    showToast("Response draft copied");
  }

  async function saveDraft(button) {
    const emailId = state.selectedId;
    const original = button.innerHTML;
    button.disabled = true;
    button.classList.add("is-loading");
    $("span", button).textContent = "Saving…";
    try {
      const result = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/notification/send`), 10000, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actually_send: false, save_locally: true })
      });
      showToast(result.local_check?.saved ? "Draft saved locally" : "Draft prepared");
    } catch (error) {
      showToast(error.name === "AbortError" ? "Save request timed out" : "Could not save the draft", "error");
    } finally {
      button.disabled = false;
      button.classList.remove("is-loading");
      button.innerHTML = original;
    }
  }

  function renderComparison(item, fields) {
    const defects = new Set(item.defect_fields || []);
    const hasValues = Object.keys(fields.si || {}).length || Object.keys(fields.bl || {}).length;
    const rows = FIELDS.map(([key, label]) => {
      const different = defects.has(key);
      const siValue = fields.si?.[key] || (item.category === "BL_COMPARISON" ? "Source value unavailable" : "Not applicable");
      const blValue = fields.bl?.[key] || (item.category === "BL_COMPARISON" ? "Source value unavailable" : "Not applicable");
      return `<div class="comparison-row ${different ? "is-different" : ""}">
        <div class="comparison-cell field-name">${label}</div>
        <div class="comparison-cell"><span class="cell-value">${escapeHtml(siValue)}</span></div>
        <div class="comparison-cell"><span class="cell-value">${escapeHtml(blValue)}</span></div>
        <div class="comparison-cell"><span class="row-result ${different ? "mismatch" : "match"}">
          <svg viewBox="0 0 24 24">${different ? '<path d="m7 7 10 10M17 7 7 17"/>' : '<path d="M20 6 9 17l-5-5"/>'}</svg>${different ? "Mismatch" : "Match"}
        </span></div>
      </div>`;
    }).join("");

    $("#comparisonTable").innerHTML = `<div class="comparison-row table-head"><div class="comparison-cell">Field</div><div class="comparison-cell">Shipping instruction</div><div class="comparison-cell">Bill of Lading</div><div class="comparison-cell">Result</div></div>${rows}`;
    if (!hasValues && item.category !== "BL_COMPARISON") {
      $("#comparisonTable").innerHTML = `<div class="empty-state"><div><svg viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h5"/></svg><strong>No document comparison</strong><p>${titleCase(item.category)} emails are classified only, as required by the workflow.</p></div></div>`;
    }
  }

  function renderAttachments(email) {
    const attachments = email.attachments || [];
    $("#attachmentTabCount").textContent = attachments.length;
    $("#attachmentGrid").innerHTML = attachments.length ? attachments.map(path => {
      const name = path.split("/").pop();
      const ext = name.split(".").pop();
      return `<article class="attachment-card">
        <div class="file-icon"><svg viewBox="0 0 24 24"><path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7Z"/><path d="M14 2v5h5M9 13h6M9 17h4"/></svg></div>
        <div><strong>${escapeHtml(name)}</strong><small>Source document</small></div><span class="attachment-badge">${escapeHtml(ext)}</span>
      </article>`;
    }).join("") : `<div class="empty-state"><div><svg viewBox="0 0 24 24"><path d="m21 12.5-8.3 8.3a6 6 0 0 1-8.5-8.5l9-9a4 4 0 0 1 5.7 5.7l-9 9a2 2 0 0 1-2.8-2.8l8.3-8.3"/></svg><strong>No attachments</strong><p>This email does not include source documents.</p></div></div>`;
  }

  function renderAudit(item) {
    const events = [
      ["Email classified", `Assigned to ${titleCase(item.category)}.`, "Stage 1"],
      ...(item.category === "BL_COMPARISON" ? [["Documents extracted", "Seven canonical shipping fields evaluated.", "Stage 2"]] : []),
      [item.status === "NEEDS_REVIEW" ? "Case escalated" : "Verification completed", item.status === "MISMATCH" ? `${item.defect_fields.length} mismatched field(s) surfaced.` : item.status === "NEEDS_REVIEW" ? titleCase(item.review_reason) : "No mismatch detected.", "Stage 3"],
      ...(state.reviewed.has(state.selectedId) ? [["Operator reviewed", "Case marked as reviewed in this browser.", "Human review"]] : [])
    ];
    $("#auditTimeline").innerHTML = events.map(([title, description, time]) => `<div class="timeline-item"><span class="timeline-dot"></span><strong>${escapeHtml(title)}</strong><p>${escapeHtml(description)}</p><time>${escapeHtml(time)}</time></div>`).join("");
  }

  async function selectEmail(emailId, options = {}) {
    if (!state.submission[emailId]) return;
    state.selectedId = emailId;
    renderQueue();
    const item = state.submission[emailId];
    const [email, fields] = await Promise.all([loadEmail(emailId), loadEmail(emailId).then(value => loadComparison(emailId, value))]);
    const cls = statusClass(item.status);
    const copy = resultCopy(item);
    const orb = $("#statusOrb");
    orb.className = `status-orb ${cls}`;
    orb.innerHTML = item.status === "OK" ? '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>' : item.status === "NEEDS_REVIEW" ? '<svg viewBox="0 0 24 24"><path d="M12 8v4m0 4h.01"/><circle cx="12" cy="12" r="9"/></svg>' : '<svg viewBox="0 0 24 24"><path d="M12 8v5m0 4h.01"/><circle cx="12" cy="12" r="9"/></svg>';
    $("#selectedId").textContent = formatId(emailId);
    $("#selectedCategory").textContent = titleCase(item.category);
    $("#selectedSubject").textContent = displaySubject(email.subject) || formatId(emailId);
    $("#selectedSubject").title = email.subject || formatId(emailId);
    $("#summaryBanner").className = `summary-banner ${cls}`;
    $("#summaryTitle").textContent = copy.title;
    $("#summaryText").textContent = copy.text;
    $("#comparisonTabCount").textContent = item.defect_fields?.length || 0;
    $("#emailFrom").textContent = email.from || "Not available";
    $("#emailSubject").textContent = email.subject || "Not available";
    $("#emailBody").textContent = email.body || "No email body available.";
    $("#retryButton").style.display = item.status === "NEEDS_REVIEW" ? "flex" : "none";
    updateReviewedButton();
    renderComparison(item, fields);
    renderAttachments(email);
    renderAudit(item);
    const draftTabButton = $(".draft-tab-button");
    draftTabButton.hidden = item.status !== "MISMATCH";
    if (item.status !== "MISMATCH" && draftTabButton.classList.contains("active")) setTab("comparison");
    if (item.status === "MISMATCH") loadDraft(emailId);
    if (!options.silent) $(".detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function updateReviewedButton() {
    const button = $("#reviewedButton");
    const reviewed = state.reviewed.has(state.selectedId);
    button.classList.toggle("reviewed", reviewed);
    $("span", button).textContent = reviewed ? "Reviewed" : "Mark reviewed";
  }

  function toggleReviewed() {
    if (state.reviewed.has(state.selectedId)) state.reviewed.delete(state.selectedId);
    else state.reviewed.add(state.selectedId);
    localStorage.setItem("sdoc-reviewed", JSON.stringify([...state.reviewed]));
    updateReviewedButton();
    renderAudit(state.submission[state.selectedId]);
    showToast(state.reviewed.has(state.selectedId) ? "Case marked as reviewed" : "Review mark removed");
  }

  function setTab(tabName) {
    $$(".tab-bar button").forEach(button => button.classList.toggle("active", button.dataset.tab === tabName));
    $$(".tab-content").forEach(panel => panel.classList.toggle("active", panel.dataset.panel === tabName));
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("sdoc-theme", theme);
  }

  function moveNavSelection(button = $(".nav-item.active")) {
    const nav = $(".primary-nav");
    const selection = $("#navSelection");
    if (!nav || !selection || !button) return;
    const navRect = nav.getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    selection.style.height = `${buttonRect.height}px`;
    selection.style.transform = `translate3d(0, ${buttonRect.top - navRect.top}px, 0)`;
  }

  function setActiveNav(button) {
    if (!button) return;
    $$(".nav-item[data-nav]").forEach(item => item.classList.toggle("active", item === button));
    requestAnimationFrame(() => moveNavSelection(button));
  }

  function syncSidebarButton() {
    const collapsed = $(".app-shell").classList.contains("sidebar-collapsed");
    const trigger = $("#openSidebar");
    trigger.setAttribute("aria-expanded", String(!collapsed));
    trigger.setAttribute("aria-label", collapsed ? "Show navigation" : "Hide navigation");
  }

  function toggleSidebar() {
    if (window.matchMedia("(max-width: 960px)").matches) {
      openSidebar();
      return;
    }
    const shell = $(".app-shell");
    shell.classList.toggle("sidebar-collapsed");
    localStorage.setItem("sdoc-sidebar-collapsed", String(shell.classList.contains("sidebar-collapsed")));
    syncSidebarButton();
    setTimeout(() => moveNavSelection(), 760);
  }

  function bindEvents() {
    $("#themeToggle").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
    $("#refreshButton").addEventListener("click", refreshData);
    $("#reviewedButton").addEventListener("click", toggleReviewed);
    $("#retryButton").addEventListener("click", () => {
      showToast("Retry requested — connect this action to POST /process", "warning");
      $("#retryButton svg").style.animation = "spin .7s var(--ease)";
      setTimeout(() => $("#retryButton svg").style.animation = "", 800);
    });
    $("#loadMoreButton").addEventListener("click", () => { state.visibleCount += 20; renderQueue(); });
    $("#searchInput").addEventListener("input", event => { state.search = event.target.value.trim(); state.visibleCount = 20; renderQueue(); });
    $("#categoryFilter").addEventListener("change", event => { state.categoryFilter = event.target.value; state.visibleCount = 20; renderQueue(); });
    $$("#statusFilters button").forEach(button => button.addEventListener("click", () => {
      $$("#statusFilters button").forEach(item => item.classList.toggle("active", item === button));
      state.statusFilter = button.dataset.status;
      state.visibleCount = 20;
      const navName = button.dataset.status === "OK" ? "verified" : "overview";
      setActiveNav($(`.nav-item[data-nav="${navName}"]`));
      renderQueue();
    }));
    $$(".tab-bar button").forEach(button => button.addEventListener("click", () => setTab(button.dataset.tab)));
    $("#draftComposer").addEventListener("click", event => {
      const button = event.target.closest("[data-draft-action]");
      if (!button) return;
      const action = button.dataset.draftAction;
      if (action === "copy") copyDraft();
      if (action === "save") saveDraft(button);
      if (["retry", "regenerate"].includes(action)) loadDraft(state.selectedId, { force: true });
    });
    $$(".nav-item[data-nav]").forEach(button => button.addEventListener("click", () => {
      const status = button.dataset.focusStatus || "FLAGGED";
      setActiveNav(button);
      state.statusFilter = status;
      state.visibleCount = 20;
      $$("#statusFilters button").forEach(item => item.classList.toggle("active", item.dataset.status === (["MISMATCH", "NEEDS_REVIEW"].includes(status) ? "FLAGGED" : status)));
      renderQueue();
      const first = filteredIds().find(id => status === "FLAGGED" || state.submission[id].status === status);
      if (first) selectEmail(first);
      if (window.matchMedia("(max-width: 960px)").matches) closeSidebar();
    }));

    document.addEventListener("keydown", event => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        $("#searchInput").focus();
      }
      if (event.key === "Escape") {
        $("#morePopover").hidden = true;
        closeSidebar();
      }
    });

    $("#moreButton").addEventListener("click", event => {
      const popover = $("#morePopover");
      const rect = event.currentTarget.getBoundingClientRect();
      popover.style.top = `${rect.bottom + 7}px`;
      popover.style.left = `${Math.min(window.innerWidth - 182, rect.right - 170)}px`;
      popover.hidden = !popover.hidden;
    });
    $("#copyIdButton").addEventListener("click", async () => {
      await navigator.clipboard?.writeText(state.selectedId);
      $("#morePopover").hidden = true;
      showToast("Email ID copied");
    });
    $("#exportButton").addEventListener("click", exportSelected);
    document.addEventListener("click", event => {
      if (!event.target.closest("#morePopover") && !event.target.closest("#moreButton")) $("#morePopover").hidden = true;
    });

    $("#openSidebar").addEventListener("click", toggleSidebar);
    $("#closeSidebar").addEventListener("click", closeSidebar);
    $("#mobileScrim").addEventListener("click", closeSidebar);
    window.addEventListener("resize", () => requestAnimationFrame(() => moveNavSelection()));
  }

  function openSidebar() { $("#sidebar").classList.add("open"); $("#mobileScrim").classList.add("visible"); }
  function closeSidebar() { $("#sidebar").classList.remove("open"); $("#mobileScrim").classList.remove("visible"); }

  function exportSelected() {
    const id = state.selectedId;
    const payload = { email_id: id, ...state.submission[id], operator_reviewed: state.reviewed.has(id) };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${id}-verification.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    $("#morePopover").hidden = true;
    showToast("Verification result exported");
  }

  async function hydrateVisibleEmails() {
    const ids = filteredIds().slice(0, 30);
    const workers = Array.from({ length: 6 }, async () => {
      while (ids.length) {
        const id = ids.shift();
        if (id) await loadEmail(id);
      }
    });
    await Promise.all(workers);
    renderQueue();
  }

  async function refreshData() {
    const button = $("#refreshButton");
    button.classList.add("spinning");
    state.submission = await loadSubmission();
    state.stats = computeStats(state.submission);
    if (!state.submission[state.selectedId]) state.selectedId = Object.keys(state.submission)[0];
    renderStats();
    renderQueue();
    await selectEmail(state.selectedId, { silent: true });
    $("#lastSync").textContent = "Just now";
    button.classList.remove("spinning");
    showToast("Dashboard data refreshed");
  }

  async function init() {
    const savedTheme = localStorage.getItem("sdoc-theme");
    const preferred = window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
    setTheme(savedTheme || preferred);
    if (localStorage.getItem("sdoc-sidebar-collapsed") === "true" && !window.matchMedia("(max-width: 960px)").matches) {
      $(".app-shell").classList.add("sidebar-collapsed");
    }
    bindEvents();
    syncSidebarButton();
    requestAnimationFrame(() => moveNavSelection());
    state.submission = await loadSubmission();
    state.stats = computeStats(state.submission);
    if (!state.submission[state.selectedId]) state.selectedId = Object.keys(state.submission)[0];
    renderStats();
    renderQueue();
    await selectEmail(state.selectedId, { silent: true });
    hydrateVisibleEmails();
  }

  init().catch(error => {
    console.error(error);
    showToast("Could not initialize the dashboard", "error");
  });
})();
