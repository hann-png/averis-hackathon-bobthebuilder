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
    emailLoads: new Map(),
    fields: new Map([[FALLBACK_EMAIL.email_id, FALLBACK_FIELDS]]),
    reviewed: new Set(JSON.parse(localStorage.getItem("sdoc-reviewed") || "[]")),
    reviewHistory: JSON.parse(localStorage.getItem("sdoc-review-history") || "[]"),
    drafts: new Map(),
    metadata: new Map(),
    metadataOnline: false,
    assistantMessages: JSON.parse(sessionStorage.getItem("sdoc-assistant-messages") || "null") || [
      { role: "assistant", text: "Hi, I’m BOB. I can find verification cases, count mismatches, inspect the review queue, and take you directly to an email." }
    ],
    assistantTyping: false,
    assistantBusy: false,
    lastDashboardNav: "overview",
    selectedId: "email_004",
    statusFilter: "FLAGGED",
    categoryFilter: "ALL",
    timeFilter: "ALL",
    search: "",
    savedViews: JSON.parse(localStorage.getItem("sdoc-saved-views") || "[]"),
    activeSavedView: "",
    viewPredicate: "",
    pendingDraftSave: null,
    assistantDock: "left",
    assistantDragMoved: false,
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

  async function loadOperatorMetadata() {
    try {
      const payload = await fetchJson(apiUrl("/operator/metadata"), 6000);
      const records = payload.emails || {};
      state.metadata = new Map(Object.entries(records));
      state.reviewed = new Set(Object.entries(records).filter(([, value]) => value.reviewed).map(([id]) => id));
      state.reviewHistory = Object.values(records)
        .filter(value => value.reviewed && value.reviewed_at)
        .sort((a, b) => String(b.reviewed_at).localeCompare(String(a.reviewed_at)))
        .map(value => ({ id: value.email_id, reviewedAt: value.reviewed_at }));
      state.metadataOnline = true;
      localStorage.setItem("sdoc-reviewed", JSON.stringify([...state.reviewed]));
      localStorage.setItem("sdoc-review-history", JSON.stringify(state.reviewHistory));
      return true;
    } catch (_) {
      state.metadataOnline = false;
      return false;
    }
  }

  async function recordOpened(emailId) {
    if (!state.metadataOnline) return;
    try {
      const metadata = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/opened`), 5000, { method: "POST" });
      state.metadata.set(emailId, metadata);
      if (state.selectedId === emailId) renderAudit(state.submission[emailId]);
    } catch (_) { /* opening an email must never be blocked by activity logging */ }
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
    if (state.emailLoads.has(emailId)) return state.emailLoads.get(emailId);
    const request = (async () => {
      try {
        const email = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/source`), 6000);
        state.emails.set(emailId, email);
        return email;
      } catch (_) { /* local static fallback below */ }
      const url = `${String(CONFIG.dataBase || "../data").replace(/\/$/, "")}/inbox/${emailId}.json`;
      try {
        const email = await fetchJson(url, 3000);
        state.emails.set(emailId, email);
        return email;
      } catch (_) {
        const generic = {
          email_id: emailId,
          from: "Source email unavailable",
          subject: `${titleCase(state.submission[emailId]?.category || "Email")} — ${formatId(emailId)}`,
          body: "The source email could not be loaded from the API or local dataset.",
          attachments: []
        };
        state.emails.set(emailId, generic);
        return generic;
      }
    })().finally(() => state.emailLoads.delete(emailId));
    state.emailLoads.set(emailId, request);
    return request;
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
    try {
      const payload = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/comparison`), 10000);
      const result = { si: payload.si || {}, bl: payload.bl || {} };
      state.fields.set(emailId, result);
      return result;
    } catch (_) { /* retain direct-file support for local static previews */ }
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

  function matchesTimeFilter(emailId) {
    if (state.timeFilter === "ALL") return true;
    const metadata = state.metadata.get(emailId) || {};
    const field = state.timeFilter === "REVIEWED" ? "reviewed_at" : state.timeFilter === "OPENED" ? "last_opened_at" : "processed_at";
    const value = metadata[field];
    const timestamp = value ? new Date(value) : null;
    if (!timestamp || Number.isNaN(timestamp.getTime())) return false;
    const age = Date.now() - timestamp.getTime();
    if (state.timeFilter === "TODAY") return happenedToday(value);
    if (state.timeFilter === "24H") return age >= 0 && age <= 24 * 60 * 60 * 1000;
    return age >= 0 && age <= 7 * 24 * 60 * 60 * 1000;
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
      const viewMatch = state.viewPredicate === "wrong_doc_type"
        ? item.review_reason === "wrong_doc_type"
        : state.viewPredicate === "unreviewed_bl"
          ? item.category === "BL_COMPARISON" && !state.reviewed.has(id)
          : true;
      return statusMatch && categoryMatch && queryMatch && matchesTimeFilter(id) && viewMatch;
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

  function renderSavedViews() {
    const select = $("#savedViewSelect");
    if (!select) return;
    const customOptions = state.savedViews.map(view => `<option value="${escapeHtml(view.id)}">${escapeHtml(view.name)}</option>`).join("");
    select.innerHTML = `<option value="">Saved views</option>
      <optgroup label="Suggested">
        <option value="builtin:today-mismatch">Today’s mismatches</option>
        <option value="builtin:wrong-doc">Wrong document type</option>
        <option value="builtin:unreviewed-bl">Unreviewed BL comparisons</option>
      </optgroup>
      ${customOptions ? `<optgroup label="My views">${customOptions}</optgroup>` : ""}`;
    select.value = state.activeSavedView;
    $("#deleteViewButton").hidden = !state.activeSavedView || state.activeSavedView.startsWith("builtin:");
  }

  function clearSavedViewSelection() {
    if (!state.activeSavedView && !state.viewPredicate) return;
    state.activeSavedView = "";
    state.viewPredicate = "";
    renderSavedViews();
  }

  function syncFilterControls() {
    $("#categoryFilter").value = state.categoryFilter;
    $("#timeFilter").value = state.timeFilter;
    $("#searchInput").value = state.search;
    $$("#statusFilters button").forEach(button => button.classList.toggle("active", button.dataset.status === (["MISMATCH", "NEEDS_REVIEW"].includes(state.statusFilter) ? "FLAGGED" : state.statusFilter)));
  }

  function applySavedView(viewId) {
    state.activeSavedView = viewId;
    state.viewPredicate = "";
    if (viewId === "builtin:today-mismatch") {
      Object.assign(state, { statusFilter: "MISMATCH", categoryFilter: "ALL", timeFilter: "TODAY", search: "" });
    } else if (viewId === "builtin:wrong-doc") {
      Object.assign(state, { statusFilter: "NEEDS_REVIEW", categoryFilter: "ALL", timeFilter: "ALL", search: "", viewPredicate: "wrong_doc_type" });
    } else if (viewId === "builtin:unreviewed-bl") {
      Object.assign(state, { statusFilter: "ALL", categoryFilter: "BL_COMPARISON", timeFilter: "ALL", search: "", viewPredicate: "unreviewed_bl" });
    } else {
      const view = state.savedViews.find(candidate => candidate.id === viewId);
      if (view) Object.assign(state, view.filters);
      else state.activeSavedView = "";
    }
    state.visibleCount = 20;
    syncFilterControls();
    renderSavedViews();
    renderQueue();
    const first = filteredIds()[0];
    if (first) selectEmail(first, { silent: true });
  }

  function openSaveViewModal() {
    const modal = $("#saveViewModal");
    $("#savedViewName").value = "";
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => modal.classList.add("visible"));
    setTimeout(() => $("#savedViewName").focus(), 220);
  }

  function closeModal(modalId) {
    const modal = $(`#${modalId}`);
    if (!modal) return;
    modal.classList.remove("visible");
    modal.setAttribute("aria-hidden", "true");
    setTimeout(() => { if (!modal.classList.contains("visible")) modal.hidden = true; }, 260);
  }

  function saveCurrentView() {
    const name = $("#savedViewName").value.trim();
    if (!name) {
      showToast("Give this view a name", "warning");
      return;
    }
    const view = {
      id: `view-${Date.now()}`,
      name: name.slice(0, 48),
      filters: {
        statusFilter: state.statusFilter,
        categoryFilter: state.categoryFilter,
        timeFilter: state.timeFilter,
        search: state.search,
        viewPredicate: state.viewPredicate
      }
    };
    state.savedViews.push(view);
    state.activeSavedView = view.id;
    localStorage.setItem("sdoc-saved-views", JSON.stringify(state.savedViews));
    closeModal("saveViewModal");
    renderSavedViews();
    showToast("Workspace view saved");
  }

  function deleteCurrentView() {
    if (!state.activeSavedView || state.activeSavedView.startsWith("builtin:")) return;
    state.savedViews = state.savedViews.filter(view => view.id !== state.activeSavedView);
    localStorage.setItem("sdoc-saved-views", JSON.stringify(state.savedViews));
    state.activeSavedView = "";
    state.viewPredicate = "";
    renderSavedViews();
    showToast("Saved view removed");
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
    const displayedTimestamp = draft.saved_at || draft.generated_at;
    const generatedDate = displayedTimestamp ? new Date(displayedTimestamp) : null;
    const generatedAt = generatedDate && !Number.isNaN(generatedDate.getTime())
      ? generatedDate.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
      : "Generated now";
    $("#draftComposer").innerHTML = `<article class="draft-composer ${draft.is_saved ? "is-saved" : ""}">
      <header class="draft-composer-head">
        <div class="draft-heading">
          <span class="draft-mark"><svg viewBox="0 0 24 24"><path d="M4 19.5V5a2 2 0 0 1 2-2h8l6 6v10.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19.5Z"/><path d="M14 3v6h6M8 14h8M8 17h5"/></svg></span>
          <div><p class="eyebrow">Clarification email</p><h3>Response draft</h3></div>
        </div>
        <div class="draft-state"><span></span><b>${draft.is_saved ? "Saved" : "Draft only"}</b> · Not sent</div>
      </header>

      <div class="draft-evidence">
        <div><strong>${(draft.defect_fields || []).length} ${(draft.defect_fields || []).length === 1 ? "field" : "fields"} included</strong><p>The detected differences are locked to the verification result.</p></div>
        <div class="draft-field-chips">${fields}</div>
      </div>

      <div class="draft-address-row"><span>To</span><strong>${escapeHtml(draft.recipient || "Recipient unavailable")}</strong><i>Original sender</i></div>
      <label class="draft-address-row draft-subject-row"><span>Subject</span><input id="draftSubject" type="text" maxlength="300" value="${escapeHtml(draft.subject || "Shipping document clarification")}" aria-label="Draft subject"></label>
      <div class="draft-body-wrap">
        <div class="draft-body-toolbar"><span>Message</span><small>${draft.is_saved ? "Saved" : "Generated"} ${escapeHtml(generatedAt)}</small></div>
        <textarea id="draftBody" maxlength="20000" spellcheck="true" aria-label="Generated response draft">${escapeHtml(draft.body || "")}</textarea>
      </div>

      <footer class="draft-actions">
        <p><svg viewBox="0 0 24 24"><path d="M12 3 4 6v6c0 5 3.4 8 8 9 4.6-1 8-4 8-9V6l-8-3Z"/><path d="m9 12 2 2 4-4"/></svg>You can edit this draft. The recipient stays locked and saving never sends it.</p>
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
      const regenerate = options.force ? "?regenerate=true" : "";
      const draft = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/notification${regenerate}`), 8000);
      if (state.selectedId !== emailId) return;
      if (!draft.notification_eligible) throw new Error("This email is not eligible for a clarification draft.");
      state.drafts.set(emailId, draft);
      renderDraft(draft);
      if (state.metadataOnline) {
        try {
          const metadata = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/metadata`), 5000);
          state.metadata.set(emailId, metadata);
          if (state.selectedId === emailId) renderAudit(state.submission[emailId]);
        } catch (_) { /* the draft remains usable if the audit refresh fails */ }
      }
    } catch (error) {
      if (state.selectedId === emailId) renderDraftError(error.name === "AbortError" ? "The draft service took too long to respond." : error.message);
    }
  }

  async function copyDraft() {
    const draft = state.drafts.get(state.selectedId);
    if (!draft) return;
    const subject = $("#draftSubject")?.value || draft.subject || "";
    const body = $("#draftBody")?.value || draft.body || "";
    const content = `To: ${draft.recipient || ""}\nSubject: ${subject}\n\n${body}`;
    await navigator.clipboard?.writeText(content);
    showToast("Response draft copied");
  }

  function openDraftPreview(button) {
    const emailId = state.selectedId;
    const draft = state.drafts.get(emailId);
    const subject = $("#draftSubject")?.value.trim() || "";
    const body = $("#draftBody")?.value.trim() || "";
    if (!draft || !subject || !body) {
      showToast("Subject and message cannot be empty", "warning");
      return;
    }
    state.pendingDraftSave = { button, emailId, subject, body };
    $("#draftPreviewRecipient").textContent = draft.recipient || "Recipient unavailable";
    $("#draftPreviewSubject").textContent = subject;
    $("#draftPreviewBody").textContent = body;
    const flags = [];
    flags.push(subject !== (draft.subject || "").trim() ? "Subject edited" : "Subject unchanged");
    flags.push(body !== (draft.body || "").trim() ? "Message edited" : "Message unchanged");
    $("#draftPreviewFlags").innerHTML = flags.map(flag => `<span class="${flag.endsWith("unchanged") ? "unchanged" : ""}">${escapeHtml(flag)}</span>`).join("");
    $("#draftConfirmCheck").checked = false;
    $("#confirmDraftSave").disabled = true;
    const modal = $("#draftPreviewModal");
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => modal.classList.add("visible"));
  }

  async function saveDraft(button, pending = null) {
    const emailId = pending?.emailId || state.selectedId;
    const subject = pending?.subject || $("#draftSubject")?.value.trim() || "";
    const body = pending?.body || $("#draftBody")?.value.trim() || "";
    if (!subject || !body) {
      showToast("Subject and message cannot be empty", "warning");
      return;
    }
    const original = button.innerHTML;
    button.disabled = true;
    button.classList.add("is-loading");
    $("span", button).textContent = "Saving…";
    try {
      const result = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/notification/send`), 10000, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actually_send: false, save_locally: true, subject, body })
      });
      const current = state.drafts.get(emailId) || {};
      const saved = { ...current, ...(result.draft || {}), subject, body, is_saved: Boolean(result.local_check?.saved), saved_at: result.draft?.saved_at };
      state.drafts.set(emailId, saved);
      if (result.activity) state.metadata.set(emailId, result.activity);
      if (state.selectedId === emailId) {
        renderDraft(saved);
        renderAudit(state.submission[emailId]);
      }
      closeModal("draftPreviewModal");
      state.pendingDraftSave = null;
      showToast(result.local_check?.saved ? "Draft saved safely" : "Draft prepared");
    } catch (error) {
      showToast(error.name === "AbortError" ? "Save request timed out" : "Could not save the draft", "error");
    } finally {
      button.disabled = false;
      button.classList.remove("is-loading");
      button.innerHTML = original;
    }
  }

  const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  const idNumber = id => Number(String(id).match(/\d+/)?.[0] || 0);
  const newestFirst = ids => [...ids].sort((a, b) => {
    const aTime = Date.parse(state.metadata.get(a)?.processed_at || "") || 0;
    const bTime = Date.parse(state.metadata.get(b)?.processed_at || "") || 0;
    return bTime - aTime || idNumber(b) - idNumber(a);
  });
  const happenedToday = value => {
    const date = value ? new Date(value) : null;
    const today = new Date();
    return date && !Number.isNaN(date.getTime()) && date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth() && date.getDate() === today.getDate();
  };

  function assistantCardHtml(id, requestedTab = "comparison") {
    const item = state.submission[id];
    if (!item) return "";
    const email = state.emails.get(id);
    const cls = statusClass(item.status);
    const issueCopy = item.status === "MISMATCH"
      ? `${item.defect_fields?.length || 0} ${(item.defect_fields?.length || 0) === 1 ? "discrepancy" : "discrepancies"}`
      : item.status === "NEEDS_REVIEW" ? titleCase(item.review_reason || "Review required") : "Verified clean";
    const fieldActions = item.status === "MISMATCH" && item.defect_fields?.length
      ? `<span class="assistant-field-actions">${item.defect_fields.slice(0, 3).map(field => `<span data-focus-field="${escapeHtml(field)}">${escapeHtml(titleCase(field))}</span>`).join("")}</span>`
      : "";
    return `<button class="assistant-result-card ${cls}" type="button" data-open-email="${escapeHtml(id)}" data-open-tab="${escapeHtml(requestedTab)}">
      <span class="assistant-result-accent"></span>
      <span class="assistant-result-content">
        <span class="assistant-result-top"><strong>${escapeHtml(formatId(id))}</strong><i class="status-chip ${cls}">${statusLabel(item.status)}</i></span>
        <span class="assistant-result-subject">${escapeHtml(displaySubject(email?.subject) || titleCase(item.category))}</span>
        <span class="assistant-result-meta">${escapeHtml(issueCopy)}<i></i>${escapeHtml(titleCase(item.category))}</span>
        ${fieldActions}
      </span>
      <span class="assistant-result-open"><svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg></span>
    </button>`;
  }

  function updateAssistantContext() {
    const item = state.submission[state.selectedId];
    const email = state.emails.get(state.selectedId);
    if (!item) return;
    const subject = displaySubject(email?.subject) || titleCase(item.category);
    $("#assistantContextId").textContent = formatId(state.selectedId);
    $("#assistantContextSubject").textContent = subject;
    $("#assistantDraftAction").hidden = item.status !== "MISMATCH";
    $("#compactContextId").textContent = formatId(state.selectedId);
    $("#compactContextSubject").textContent = subject;
    $("#compactContextSubject").title = subject;
    $("#compactDraftAction").hidden = item.status !== "MISMATCH";
    const compactCard = $("#compactContextCard");
    compactCard.classList.remove("mismatch", "review", "ok");
    compactCard.classList.add(statusClass(item.status));
  }

  function runContextAction(action) {
    const id = formatId(state.selectedId);
    const prompts = {
      explain: `Explain the discrepancies for ${id}`,
      summarize: `Summarize ${id}`,
      related: `Find emails related to ${id}`,
      draft: `Open the response draft for ${id}`
    };
    if (action === "draft" && state.submission[state.selectedId]?.status !== "MISMATCH") {
      showToast("Drafts are available for mismatched emails", "warning");
      return;
    }
    $("#compactContextCard").classList.remove("is-expanded");
    $("#compactContextToggle").setAttribute("aria-expanded", "false");
    submitAssistantPrompt(prompts[action]);
  }

  function assistantMessageHtml(message) {
    const cards = (message.cards || []).map(card => assistantCardHtml(card.id || card, card.tab || "comparison")).join("");
    const metric = message.metric ? `<div class="assistant-metric"><strong>${escapeHtml(message.metric.value)}</strong><span>${escapeHtml(message.metric.label)}</span></div>` : "";
    const source = message.source ? `<span class="assistant-response-source">${escapeHtml(message.source)}</span>` : "";
    return `<div class="assistant-message ${message.role}">
      ${message.role === "assistant" ? '<span class="assistant-message-avatar"><svg viewBox="0 0 24 24"><path d="M8 18.5 4 21v-5.2A8 8 0 0 1 3 12C3 7 7 3 12 3s9 4 9 9-4 9-9 9a9.8 9.8 0 0 1-4-.9"/><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01"/></svg></span>' : ""}
      <div class="assistant-message-stack"><div class="assistant-bubble">${escapeHtml(message.text).replace(/\n/g, "<br>")}</div>${source}${metric}${cards ? `<div class="assistant-result-stack">${cards}</div>` : ""}</div>
    </div>`;
  }

  function renderAssistantMessages() {
    const full = $("#assistantFullMessages");
    const compact = $("#assistantCompactMessages");
    if (!full || !compact) return;
    const typing = state.assistantTyping ? `<div class="assistant-message assistant"><span class="assistant-message-avatar"><svg viewBox="0 0 24 24"><path d="M8 18.5 4 21v-5.2A8 8 0 0 1 3 12C3 7 7 3 12 3s9 4 9 9-4 9-9 9a9.8 9.8 0 0 1-4-.9"/></svg></span><div class="assistant-bubble assistant-typing"><i></i><i></i><i></i></div></div>` : "";
    full.innerHTML = state.assistantMessages.map(assistantMessageHtml).join("") + typing;
    compact.innerHTML = state.assistantMessages.slice(-6).map(assistantMessageHtml).join("") + typing;
    $("#assistantFull").classList.toggle("has-conversation", state.assistantMessages.length > 1);
    sessionStorage.setItem("sdoc-assistant-messages", JSON.stringify(state.assistantMessages.slice(-30)));
    requestAnimationFrame(() => {
      full.scrollTop = full.scrollHeight;
      compact.scrollTop = compact.scrollHeight;
    });
  }

  async function prepareAssistantCards(ids, limit = 4) {
    const selected = ids.slice(0, limit);
    await Promise.all(selected.map(id => loadEmail(id)));
    return selected.map(id => ({ id }));
  }

  async function buildLocalAssistantReply(prompt) {
    const query = prompt.toLowerCase().trim();
    const entries = Object.entries(state.submission);
    const matchingStatus = status => entries.filter(([, item]) => item.status === status).map(([id]) => id);
    const explicitId = query.match(/email[\s_-]?(\d{1,4})/i);

    if (explicitId) {
      const id = `email_${String(explicitId[1]).padStart(3, "0")}`;
      if (!state.submission[id]) return { role: "assistant", text: `I couldn’t find ${formatId(id)} in the current dataset.` };
      const email = await loadEmail(id);
      const item = state.submission[id];
      const wantsDraft = /draft|reply|response/.test(query) && state.submission[id].status === "MISMATCH";
      if (/summar/.test(query)) {
        return { role: "assistant", text: `${formatId(id)} is “${displaySubject(email.subject)}” from ${email.from || "an unavailable sender"}. It is classified as ${titleCase(item.category)}, has status ${titleCase(item.status)}, and includes ${(email.attachments || []).length} attachment${(email.attachments || []).length === 1 ? "" : "s"}.`, cards: [{ id }] };
      }
      if (/explain|why|discrepanc|difference/.test(query)) {
        const fields = item.defect_fields || [];
        const text = item.status === "MISMATCH"
          ? `${formatId(id)} is mismatched because ${fields.map(titleCase).join(" and ") || "the compared values"} differ between the shipping instruction and Bill of Lading. Select a field below to inspect it.`
          : item.status === "NEEDS_REVIEW" ? `${formatId(id)} requires human review because of ${titleCase(item.review_reason)}.` : `${formatId(id)} has no recorded discrepancies.`;
        return { role: "assistant", text, cards: [{ id }] };
      }
      if (/related|similar/.test(query)) {
        const sender = String(email.from || "").toLowerCase();
        const scored = Object.keys(state.submission).filter(candidate => candidate !== id).map(candidate => {
          const candidateEmail = state.emails.get(candidate) || {};
          const score = Number(state.submission[candidate].category === item.category) + 2 * Number(Boolean(sender) && String(candidateEmail.from || "").toLowerCase() === sender);
          return { candidate, score };
        }).filter(result => result.score).sort((a, b) => b.score - a.score || idNumber(b.candidate) - idNumber(a.candidate)).map(result => result.candidate);
        return { role: "assistant", text: `I found ${scored.length} emails related by sender or category to ${formatId(id)}.`, metric: { value: scored.length, label: "Related emails" }, cards: await prepareAssistantCards(scored, 4) };
      }
      return { role: "assistant", text: `${formatId(id)} is ready. Open it to inspect the ${wantsDraft ? "response draft" : "verification result"}.`, cards: [{ id, tab: wantsDraft ? "draft" : "comparison" }] };
    }

    if (/draft|reply|response/.test(query)) {
      const id = state.selectedId;
      const item = state.submission[id];
      if (!item || item.status !== "MISMATCH") return { role: "assistant", text: "Response drafts are available only for confirmed mismatches. Open a mismatched email first, or ask me to show mismatched emails." };
      await loadEmail(id);
      return { role: "assistant", text: `The clarification draft for ${formatId(id)} is ready to inspect.`, cards: [{ id, tab: "draft" }] };
    }

    if (/what can you do|help|commands|examples/.test(query)) {
      return { role: "assistant", text: "I can count mismatches, show the review queue, find wrong document types, open a specific email, locate your latest reviewed case, filter by category, and take you directly to a response draft." };
    }

    if (/wrong\s+(document|doc)|document\s+type/.test(query)) {
      const ids = newestFirst(entries.filter(([, item]) => item.review_reason === "wrong_doc_type").map(([id]) => id));
      return { role: "assistant", text: ids.length ? `I found ${ids.length} emails escalated because the document type is wrong.` : "No wrong-document-type cases are currently recorded.", metric: { value: ids.length, label: "Wrong document type" }, cards: await prepareAssistantCards(ids) };
    }

    if (/latest\s+reviewed|last\s+reviewed|recently\s+reviewed/.test(query)) {
      const id = state.reviewHistory[0]?.id || [...state.reviewed].at(-1);
      if (!id || !state.submission[id]) return { role: "assistant", text: "No reviewed email has been recorded in this browser yet." };
      await loadEmail(id);
      return { role: "assistant", text: `${formatId(id)} is the most recently reviewed email recorded in this browser.`, cards: [{ id }] };
    }

    if (/review/.test(query)) {
      const ids = newestFirst(matchingStatus("NEEDS_REVIEW"));
      const latestOnly = /newest|latest|most recent/.test(query);
      const cards = await prepareAssistantCards(latestOnly ? ids.slice(0, 1) : ids);
      return { role: "assistant", text: latestOnly ? (ids.length ? "This is the newest case in the review queue, based on dataset order." : "The review queue is empty.") : `${ids.length} emails currently need an operator review.`, metric: latestOnly ? null : { value: ids.length, label: "Need review" }, cards };
    }

    if (/mismatch|discrepanc|flagged/.test(query)) {
      const onlyMismatch = /mismatch|discrepanc/.test(query);
      let ids = newestFirst(entries.filter(([, item]) => onlyMismatch ? item.status === "MISMATCH" : ["MISMATCH", "NEEDS_REVIEW"].includes(item.status)).map(([id]) => id));
      let todayNote = "";
      if (/today/.test(query)) {
        const timestamped = ids.filter(id => state.metadata.get(id)?.processed_at);
        ids = timestamped.filter(id => happenedToday(state.metadata.get(id).processed_at));
        todayNote = timestamped.length ? " These results use the backend processing timestamp." : " Processing timestamps are unavailable for this dataset.";
      }
      return { role: "assistant", text: `I found ${ids.length} ${onlyMismatch ? "mismatched" : "flagged"} emails${/today/.test(query) ? " for today" : ""}.${todayNote}`, metric: { value: ids.length, label: onlyMismatch ? "Mismatches" : "Flagged cases" }, cards: await prepareAssistantCards(ids) };
    }

    if (/clean|verified|passed/.test(query)) {
      const ids = newestFirst(matchingStatus("OK"));
      return { role: "assistant", text: `${ids.length} emails were verified clean by the current pipeline.`, metric: { value: ids.length, label: "Verified clean" }, cards: await prepareAssistantCards(ids, 3) };
    }

    const categoryMap = [
      [/bill of lading|bl comparison|\bbl\b/, "BL_COMPARISON"],
      [/shipping instruction|si request|\bsi\b/, "SI_REQUEST"],
      [/invoice/, "INVOICE_QUERY"], [/spam/, "SPAM"], [/general/, "GENERAL"]
    ];
    const category = categoryMap.find(([pattern]) => pattern.test(query))?.[1];
    if (category) {
      const ids = newestFirst(entries.filter(([, item]) => item.category === category).map(([id]) => id));
      return { role: "assistant", text: `I found ${ids.length} emails classified as ${titleCase(category)}.`, metric: { value: ids.length, label: titleCase(category) }, cards: await prepareAssistantCards(ids) };
    }

    const stopWords = new Set(["find", "show", "open", "mail", "email", "the", "that", "with", "about", "please", "can", "you", "me", "a", "an", "my", "for"]);
    const terms = query.replace(/[^a-z0-9@.]+/g, " ").split(/\s+/).filter(term => term.length > 2 && !stopWords.has(term));
    const searchable = [...state.emails.entries()].filter(([id]) => state.submission[id]);
    const scored = searchable.map(([id, email]) => {
      const haystack = `${id} ${email.subject || ""} ${email.from || ""}`.toLowerCase();
      return { id, score: terms.reduce((total, term) => total + (haystack.includes(term) ? 1 : 0), 0) };
    }).filter(result => result.score > 0).sort((a, b) => b.score - a.score).map(result => result.id);
    if (scored.length) return { role: "assistant", text: `I found ${scored.length} matching emails among the messages currently loaded in the workspace.`, cards: await prepareAssistantCards(scored) };

    return { role: "assistant", text: "Try asking for mismatched emails, the newest review case, wrong document types, a category, or a specific ID such as EMAIL_004." };
  }

  async function buildAssistantReply(prompt) {
    try {
      const payload = await fetchJson(apiUrl("/assistant/query"), 12000, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: prompt,
          selected_email_id: state.selectedId,
          timezone_offset_minutes: new Date().getTimezoneOffset()
        })
      });

      (payload.results || []).forEach(result => {
        const emailId = result.email_id;
        if (!emailId || !state.submission[emailId]) return;
        const currentEmail = state.emails.get(emailId) || { email_id: emailId, attachments: [] };
        state.emails.set(emailId, {
          ...currentEmail,
          email_id: emailId,
          from: result.sender || currentEmail.from,
          subject: result.subject || currentEmail.subject
        });
        const currentMetadata = state.metadata.get(emailId) || {};
        state.metadata.set(emailId, {
          ...currentMetadata,
          processed_at: result.processed_at ?? currentMetadata.processed_at,
          reviewed_at: result.reviewed_at ?? currentMetadata.reviewed_at,
          last_opened_at: result.last_opened_at ?? currentMetadata.last_opened_at
        });
      });

      return {
        role: "assistant",
        text: payload.message,
        metric: payload.metric || null,
        cards: (payload.results || []).map(result => ({ id: result.email_id, tab: result.tab || "comparison", fields: result.defect_fields || [] })),
        source: payload.blocked
          ? "Security policy"
          : payload.interpreted_by === "gemini"
            ? "AI interpreted · verified workspace data"
            : "Verified workspace data"
      };
    } catch (_) {
      const fallback = await buildLocalAssistantReply(prompt);
      return { ...fallback, source: "Offline workspace fallback" };
    }
  }

  async function submitAssistantPrompt(prompt) {
    const value = String(prompt || "").trim();
    if (!value || state.assistantBusy) return;
    state.assistantBusy = true;
    state.assistantMessages.push({ role: "user", text: value });
    state.assistantTyping = true;
    renderAssistantMessages();
    $$('[data-assistant-input]').forEach(input => { input.value = ""; input.disabled = true; });
    await wait(420);
    try {
      state.assistantMessages.push(await buildAssistantReply(value));
    } catch (_) {
      state.assistantMessages.push({ role: "assistant", text: "I couldn’t complete that search. Please try again." });
    } finally {
      state.assistantTyping = false;
      state.assistantBusy = false;
      $$('[data-assistant-input]').forEach(input => { input.disabled = false; });
      renderAssistantMessages();
      const visibleInput = $("#assistantFull").classList.contains("visible") ? $("#assistantFull [data-assistant-input]") : $("#assistantCompact [data-assistant-input]");
      visibleInput?.focus();
    }
  }

  function openAssistant(mode = "compact") {
    updateAssistantContext();
    if (mode === "full") {
      closeAssistantCompact();
      const panel = $("#assistantFull");
      panel.hidden = false;
      panel.setAttribute("aria-hidden", "false");
      $(".main-content").classList.add("assistant-view-open");
      $("#assistantOrb").classList.add("full-open");
      $(".main-content").scrollTo({ top: 0, behavior: "auto" });
      setActiveNav($("#askBobNav"));
      requestAnimationFrame(() => panel.classList.add("visible"));
      setTimeout(() => $("#assistantFull [data-assistant-input]")?.focus(), 360);
    } else {
      const panel = $("#assistantCompact");
      if (!panel.style.top) {
        panel.style.right = "auto";
        panel.style.left = state.assistantDock === "left" ? "23px" : `${Math.max(14, window.innerWidth - panel.offsetWidth - 23)}px`;
      }
      panel.classList.add("visible");
      panel.setAttribute("aria-hidden", "false");
      $("#assistantOrb").classList.add("compact-open");
      $("#assistantOrb").setAttribute("aria-expanded", "true");
      setTimeout(() => $("#assistantCompact [data-assistant-input]")?.focus(), 260);
    }
    renderAssistantMessages();
  }

  function closeAssistantCompact() {
    $("#assistantCompact").classList.remove("visible");
    $("#assistantCompact").setAttribute("aria-hidden", "true");
    $("#assistantOrb").classList.remove("compact-open");
    $("#assistantOrb").setAttribute("aria-expanded", "false");
  }

  function closeAssistantFull(restoreNavigation = true) {
    const panel = $("#assistantFull");
    panel.classList.remove("visible", "is-navigating");
    panel.setAttribute("aria-hidden", "true");
    $(".main-content").classList.remove("assistant-view-open");
    $("#assistantOrb").classList.remove("full-open");
    setTimeout(() => { if (!panel.classList.contains("visible")) panel.hidden = true; }, 420);
    if (restoreNavigation) setActiveNav($(`.nav-item[data-nav="${state.lastDashboardNav}"]`) || $('.nav-item[data-nav="overview"]'));
  }

  async function navigateFromAssistant(emailId, tabName = "comparison", fieldName = "") {
    const item = state.submission[emailId];
    if (!item) return;
    const fullWasOpen = $("#assistantFull").classList.contains("visible");
    if (fullWasOpen) {
      $("#assistantFull").classList.add("is-navigating");
      await wait(280);
      closeAssistantFull(false);
      openAssistant("compact");
    }
    const navName = item.status === "MISMATCH" ? "mismatch" : item.status === "NEEDS_REVIEW" ? "review" : "verified";
    state.lastDashboardNav = navName;
    state.statusFilter = item.status;
    state.categoryFilter = "ALL";
    state.timeFilter = "ALL";
    state.activeSavedView = "";
    state.viewPredicate = "";
    state.search = "";
    state.visibleCount = 20;
    syncFilterControls();
    renderSavedViews();
    setActiveNav($(`.nav-item[data-nav="${navName}"]`));
    $$("#statusFilters button").forEach(button => button.classList.toggle("active", button.dataset.status === (item.status === "OK" ? "OK" : "FLAGGED")));
    renderQueue();
    await selectEmail(emailId, { silent: true });
    setTab(tabName === "draft" && item.status === "MISMATCH" ? "draft" : "comparison");
    $(".detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    if (fieldName) {
      setTab("comparison");
      setTimeout(() => {
        const row = $(`.comparison-row[data-field="${CSS.escape(fieldName)}"]`);
        if (!row) return;
        row.classList.remove("focus-highlight");
        requestAnimationFrame(() => row.classList.add("focus-highlight"));
        row.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 460);
    }
    state.assistantMessages.push({ role: "assistant", text: `${formatId(emailId)} is open in the verification workspace.` });
    renderAssistantMessages();
  }

  function renderComparison(item, fields) {
    const defects = new Set(item.defect_fields || []);
    const hasValues = Object.keys(fields.si || {}).length || Object.keys(fields.bl || {}).length;
    const rows = FIELDS.map(([key, label]) => {
      const different = defects.has(key);
      const siValue = fields.si?.[key] || (item.category === "BL_COMPARISON" ? "Source value unavailable" : "Not applicable");
      const blValue = fields.bl?.[key] || (item.category === "BL_COMPARISON" ? "Source value unavailable" : "Not applicable");
      return `<div class="comparison-row ${different ? "is-different" : ""}" data-field="${escapeHtml(key)}">
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
    const metadata = state.metadata.get(state.selectedId);
    const formatTime = value => {
      const parsed = value ? new Date(value) : null;
      return parsed && !Number.isNaN(parsed.getTime())
        ? parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
        : "Pipeline stage";
    };
    const processedAt = formatTime(metadata?.processed_at);
    const pipelineEvents = [
      { title: "Email classified", detail: `Assigned to ${titleCase(item.category)}.`, occurred_at: processedAt },
      ...(item.category === "BL_COMPARISON" ? [{ title: "Documents extracted", detail: "Seven canonical shipping fields evaluated.", occurred_at: processedAt }] : []),
      {
        title: item.status === "NEEDS_REVIEW" ? "Case escalated" : "Verification completed",
        detail: item.status === "MISMATCH" ? `${item.defect_fields.length} mismatched field(s) surfaced.` : item.status === "NEEDS_REVIEW" ? titleCase(item.review_reason) : "No mismatch detected.",
        occurred_at: processedAt
      }
    ];
    const activityEvents = Array.isArray(metadata?.events) ? [...metadata.events].reverse() : [];
    if (!activityEvents.length && state.reviewed.has(state.selectedId)) {
      activityEvents.push({ title: "Operator reviewed", detail: "Case marked as reviewed in this browser.", occurred_at: metadata?.reviewed_at || state.reviewHistory.find(entry => entry.id === state.selectedId)?.reviewedAt });
    }
    const events = [...pipelineEvents, ...activityEvents];
    $("#auditTimeline").innerHTML = events.map(event => `<div class="timeline-item"><span class="timeline-dot"></span><strong>${escapeHtml(event.title)}</strong><p>${escapeHtml(event.detail || "Activity recorded.")}</p><time>${escapeHtml(event.occurred_at?.includes?.("T") ? formatTime(event.occurred_at) : event.occurred_at || "Activity")}${event.actor ? ` · ${escapeHtml(titleCase(event.actor))}` : ""}</time></div>`).join("");
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
    updateAssistantContext();
    const draftTabButton = $(".draft-tab-button");
    draftTabButton.hidden = item.status !== "MISMATCH";
    if (item.status !== "MISMATCH" && draftTabButton.classList.contains("active")) setTab("comparison");
    if (item.status === "MISMATCH") loadDraft(emailId);
    if (options.trackOpen !== false) recordOpened(emailId);
    if (!options.silent) $(".detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function updateReviewedButton() {
    const button = $("#reviewedButton");
    const reviewed = state.reviewed.has(state.selectedId);
    button.classList.toggle("reviewed", reviewed);
    $("span", button).textContent = reviewed ? "Reviewed" : "Mark reviewed";
  }

  async function toggleReviewed() {
    const emailId = state.selectedId;
    const reviewed = !state.reviewed.has(emailId);
    const button = $("#reviewedButton");
    button.disabled = true;
    try {
      if (state.metadataOnline) {
        const metadata = await fetchJson(apiUrl(`/email/${encodeURIComponent(emailId)}/review`), 7000, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reviewed, reviewer: "operator" })
        });
        state.metadata.set(emailId, metadata);
        if (metadata.reviewed) state.reviewed.add(emailId);
        else state.reviewed.delete(emailId);
        state.reviewHistory = metadata.reviewed
          ? [{ id: emailId, reviewedAt: metadata.reviewed_at }, ...state.reviewHistory.filter(entry => entry.id !== emailId)].slice(0, 100)
          : state.reviewHistory.filter(entry => entry.id !== emailId);
        showToast(metadata.reviewed ? "Review saved to workspace" : "Review mark removed");
      } else {
        if (reviewed) {
          state.reviewed.add(emailId);
          state.reviewHistory = [{ id: emailId, reviewedAt: new Date().toISOString() }, ...state.reviewHistory.filter(entry => entry.id !== emailId)].slice(0, 100);
        } else {
          state.reviewed.delete(emailId);
          state.reviewHistory = state.reviewHistory.filter(entry => entry.id !== emailId);
        }
        showToast("API unavailable — review saved in this browser", "warning");
      }
      localStorage.setItem("sdoc-reviewed", JSON.stringify([...state.reviewed]));
      localStorage.setItem("sdoc-review-history", JSON.stringify(state.reviewHistory));
      if (state.selectedId === emailId) {
        updateReviewedButton();
        renderAudit(state.submission[emailId]);
      }
    } catch (_) {
      showToast("Could not update the review status", "error");
    } finally {
      button.disabled = false;
    }
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
    [$("#openSidebar"), $("#assistantSidebarToggle")].filter(Boolean).forEach(trigger => {
      trigger.setAttribute("aria-expanded", String(!collapsed));
      trigger.setAttribute("aria-label", collapsed ? "Show navigation" : "Hide navigation");
    });
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

  const commandIcon = '<svg viewBox="0 0 24 24"><path d="M5 7h14M5 12h14M5 17h9"/></svg>';
  const commandActions = [
    { id: "assistant", label: "Open Ask BOB", detail: "Search and navigate the verification workspace", hint: "AI" },
    { id: "mismatch", label: "Show mismatches", detail: "Open every confirmed document discrepancy", hint: "46" },
    { id: "review", label: "Open review queue", detail: "Cases waiting for an operator decision", hint: "20" },
    { id: "today", label: "Today’s mismatches", detail: "Apply the timestamped saved view", hint: "View" },
    { id: "verified", label: "Show verified email", detail: "Browse clean pipeline results", hint: "OK" },
    { id: "theme", label: "Switch appearance", detail: "Toggle light and dark mode", hint: "Theme" }
  ];

  function renderCommandResults(query = "") {
    const normalized = query.trim().toLowerCase();
    const actions = commandActions.filter(action => !normalized || `${action.label} ${action.detail}`.toLowerCase().includes(normalized));
    const emails = normalized ? Object.keys(state.submission).filter(id => {
      const email = state.emails.get(id) || {};
      return `${id} ${email.subject || ""} ${email.from || ""}`.toLowerCase().includes(normalized);
    }).slice(0, 8) : [];
    const actionHtml = actions.map(action => `<button class="command-result" type="button" data-command="${action.id}"><span class="command-result-icon">${commandIcon}</span><span><strong>${escapeHtml(action.label)}</strong><small>${escapeHtml(action.detail)}</small></span><kbd>${escapeHtml(action.hint)}</kbd></button>`).join("");
    const emailHtml = emails.map(id => {
      const email = state.emails.get(id) || {};
      return `<button class="command-result" type="button" data-command-email="${escapeHtml(id)}"><span class="command-result-icon">${commandIcon}</span><span><strong>${escapeHtml(formatId(id))}</strong><small>${escapeHtml(displaySubject(email.subject) || titleCase(state.submission[id].category))}</small></span><kbd>Open</kbd></button>`;
    }).join("");
    $("#commandPaletteTitle").textContent = emails.length ? "Emails and actions" : "Quick actions";
    $("#commandResults").innerHTML = actionHtml + emailHtml || `<div class="empty-state"><div><strong>No matching command</strong><p>Try an email ID, sender, subject, or workspace action.</p></div></div>`;
    $(".command-result")?.classList.add("active");
  }

  function openCommandPalette() {
    const palette = $("#commandPalette");
    palette.hidden = false;
    palette.setAttribute("aria-hidden", "false");
    $("#commandInput").value = "";
    renderCommandResults();
    requestAnimationFrame(() => palette.classList.add("visible"));
    setTimeout(() => $("#commandInput").focus(), 160);
  }

  function closeCommandPalette() {
    const palette = $("#commandPalette");
    palette.classList.remove("visible");
    palette.setAttribute("aria-hidden", "true");
    setTimeout(() => { if (!palette.classList.contains("visible")) palette.hidden = true; }, 260);
  }

  function runCommand(command) {
    closeCommandPalette();
    if (command === "assistant") return openAssistant("full");
    if (command === "today") return applySavedView("builtin:today-mismatch");
    if (command === "theme") return setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    const nav = $(`.nav-item[data-nav="${command}"]`);
    if (nav) nav.click();
  }

  function clampFloatingElement(element) {
    if (!element?.style.top || window.matchMedia("(max-width: 640px)").matches) return;
    const rect = element.getBoundingClientRect();
    const x = Math.max(12, Math.min(parseFloat(element.style.left) || rect.left, window.innerWidth - rect.width - 12));
    const y = Math.max(12, Math.min(parseFloat(element.style.top) || rect.top, window.innerHeight - rect.height - 12));
    element.style.left = `${x}px`;
    element.style.top = `${y}px`;
  }

  function makeDraggable(handle, element, options = {}) {
    let drag = null;
    handle.addEventListener("pointerdown", event => {
      const interactive = event.target.closest("button, input, textarea, a");
      if (window.matchMedia("(max-width: 640px)").matches || event.button !== 0 || (interactive && interactive !== handle)) return;
      const rect = element.getBoundingClientRect();
      drag = { id: event.pointerId, startX: event.clientX, startY: event.clientY, x: rect.left, y: rect.top, moved: false };
      element.style.right = "auto";
      element.style.bottom = "auto";
      element.style.left = `${rect.left}px`;
      element.style.top = `${rect.top}px`;
      element.classList.add("is-dragging");
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener("pointermove", event => {
      if (!drag || event.pointerId !== drag.id) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if (Math.hypot(dx, dy) > 5) drag.moved = true;
      if (!drag.moved) return;
      const x = Math.max(12, Math.min(drag.x + dx, window.innerWidth - element.offsetWidth - 12));
      const y = Math.max(12, Math.min(drag.y + dy, window.innerHeight - element.offsetHeight - 12));
      element.style.left = `${x}px`;
      element.style.top = `${y}px`;
    });
    const finish = event => {
      if (!drag || event.pointerId !== drag.id) return;
      const moved = drag.moved;
      drag = null;
      element.classList.remove("is-dragging");
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      if (!moved) return;
      const rect = element.getBoundingClientRect();
      const dockLeft = rect.left + rect.width / 2 < window.innerWidth / 2;
      element.style.left = `${dockLeft ? 14 : window.innerWidth - rect.width - 14}px`;
      state.assistantDock = dockLeft ? "left" : "right";
      if (options.orb) {
        state.assistantDragMoved = true;
        setTimeout(() => { state.assistantDragMoved = false; }, 80);
      }
    };
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
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
    $("#searchInput").addEventListener("input", event => { clearSavedViewSelection(); state.search = event.target.value.trim(); state.visibleCount = 20; renderQueue(); });
    $("#categoryFilter").addEventListener("change", event => { clearSavedViewSelection(); state.categoryFilter = event.target.value; state.visibleCount = 20; renderQueue(); });
    $("#timeFilter").addEventListener("change", event => { clearSavedViewSelection(); state.timeFilter = event.target.value; state.visibleCount = 20; renderQueue(); });
    $("#savedViewSelect").addEventListener("change", event => applySavedView(event.target.value));
    $("#saveViewButton").addEventListener("click", openSaveViewModal);
    $("#deleteViewButton").addEventListener("click", deleteCurrentView);
    $("#confirmSaveView").addEventListener("click", saveCurrentView);
    $("#savedViewName").addEventListener("keydown", event => { if (event.key === "Enter") saveCurrentView(); });
    $$("#statusFilters button").forEach(button => button.addEventListener("click", () => {
      clearSavedViewSelection();
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
      if (action === "save") openDraftPreview(button);
      if (["retry", "regenerate"].includes(action)) loadDraft(state.selectedId, { force: true });
    });
    $("#draftComposer").addEventListener("input", event => {
      if (!event.target.matches("#draftSubject, #draftBody")) return;
      const composer = event.target.closest(".draft-composer");
      composer?.classList.add("has-edits");
      const label = $(".draft-state b", composer);
      if (label) label.textContent = "Edited";
    });
    $$(".nav-item[data-nav]").forEach(button => button.addEventListener("click", () => {
      if (button.dataset.nav === "assistant") {
        openAssistant("full");
        if (window.matchMedia("(max-width: 960px)").matches) closeSidebar();
        return;
      }
      closeAssistantFull(false);
      closeAssistantCompact();
      clearSavedViewSelection();
      state.lastDashboardNav = button.dataset.nav;
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
        openCommandPalette();
      }
      if (event.key === "Escape") {
        if ($("#commandPalette").classList.contains("visible")) return closeCommandPalette();
        const openModal = $(".modal-backdrop.visible");
        if (openModal) return closeModal(openModal.id);
        $("#morePopover").hidden = true;
        if ($("#assistantFull").classList.contains("visible")) closeAssistantFull();
        else closeAssistantCompact();
        closeSidebar();
      }
    });

    $("#commandInput").addEventListener("input", event => renderCommandResults(event.target.value));
    $("#commandInput").addEventListener("keydown", event => {
      const results = $$(".command-result");
      if (!results.length) return;
      const current = Math.max(0, results.findIndex(result => result.classList.contains("active")));
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        results[current].classList.remove("active");
        const next = event.key === "ArrowDown" ? (current + 1) % results.length : (current - 1 + results.length) % results.length;
        results[next].classList.add("active");
        results[next].scrollIntoView({ block: "nearest" });
      }
      if (event.key === "Enter") {
        event.preventDefault();
        results[current].click();
      }
    });
    $("#commandResults").addEventListener("click", event => {
      const target = event.target.closest("[data-command], [data-command-email]");
      if (!target) return;
      if (target.dataset.commandEmail) {
        closeCommandPalette();
        navigateFromAssistant(target.dataset.commandEmail);
      } else runCommand(target.dataset.command);
    });
    $("#commandPalette").addEventListener("click", event => { if (event.target === event.currentTarget) closeCommandPalette(); });

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
    $("#assistantSidebarToggle").addEventListener("click", toggleSidebar);
    $("#closeSidebar").addEventListener("click", closeSidebar);
    $("#mobileScrim").addEventListener("click", closeSidebar);
    $("#assistantOrb").addEventListener("click", () => {
      if (state.assistantDragMoved) return;
      $("#assistantCompact").classList.contains("visible") ? closeAssistantCompact() : openAssistant("compact");
    });
    $("#compactContextToggle").addEventListener("click", () => {
      const card = $("#compactContextCard");
      const expanded = card.classList.toggle("is-expanded");
      $("#compactContextToggle").setAttribute("aria-expanded", String(expanded));
    });
    $("#closeAssistantCompact").addEventListener("click", closeAssistantCompact);
    $("#expandAssistant").addEventListener("click", () => openAssistant("full"));
    $("#closeAssistantFull").addEventListener("click", () => closeAssistantFull());
    $("#minimizeAssistant").addEventListener("click", () => { closeAssistantFull(false); openAssistant("compact"); });
    $("#clearAssistant").addEventListener("click", () => {
      state.assistantMessages = [{ role: "assistant", text: "Conversation cleared. What would you like to find in the verification workspace?" }];
      renderAssistantMessages();
    });
    $$("[data-assistant-form]").forEach(form => form.addEventListener("submit", event => {
      event.preventDefault();
      submitAssistantPrompt($("[data-assistant-input]", form).value);
    }));
    document.addEventListener("click", event => {
      if (!event.target.closest("#compactContextCard")) {
        $("#compactContextCard").classList.remove("is-expanded");
        $("#compactContextToggle").setAttribute("aria-expanded", "false");
      }
      const contextAction = event.target.closest("[data-context-action]");
      if (contextAction) runContextAction(contextAction.dataset.contextAction);
      const prompt = event.target.closest("[data-assistant-prompt]");
      if (prompt) submitAssistantPrompt(prompt.dataset.assistantPrompt);
      const result = event.target.closest("[data-open-email]");
      if (result) navigateFromAssistant(result.dataset.openEmail, result.dataset.openTab, event.target.closest("[data-focus-field]")?.dataset.focusField || "");
    });
    $$('[data-close-modal]').forEach(button => button.addEventListener("click", () => closeModal(button.dataset.closeModal)));
    $$(".modal-backdrop").forEach(modal => modal.addEventListener("click", event => { if (event.target === modal) closeModal(modal.id); }));
    $("#draftConfirmCheck").addEventListener("change", event => { $("#confirmDraftSave").disabled = !event.target.checked; });
    $("#confirmDraftSave").addEventListener("click", () => {
      const pending = state.pendingDraftSave;
      if (pending && $("#draftConfirmCheck").checked) saveDraft(pending.button, pending);
    });
    $$(".assistant-add-button").forEach(button => button.addEventListener("click", () => showToast("Try: Open EMAIL_004 or show mismatched emails")));
    makeDraggable($("#assistantOrb"), $("#assistantOrb"), { orb: true });
    makeDraggable($("#assistantCompactDragHandle"), $("#assistantCompact"));
    window.addEventListener("resize", () => requestAnimationFrame(() => {
      moveNavSelection();
      clampFloatingElement($("#assistantOrb"));
      clampFloatingElement($("#assistantCompact"));
    }));
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
    await loadOperatorMetadata();
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
    renderAssistantMessages();
    renderSavedViews();
    syncSidebarButton();
    requestAnimationFrame(() => moveNavSelection());
    state.submission = await loadSubmission();
    await loadOperatorMetadata();
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
