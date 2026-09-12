/* ── DOM refs ──────────────────────────────────────────── */
const $ = (s) => document.querySelector(s);
const textEl = $("#text");
const extractBtn = $("#extractBtn");
const clearBtn = $("#clearBtn");
const statsEl = $("#stats");
const resultsEl = $("#results");
const copyBar = $("#copyBar");
const copyFilter = $("#copyFilter");
const copyBtn = $("#copyBtn");
const csvBtn = $("#csvBtn");
const copyMsg = $("#copyMsg");
const fileInput = $("#fileInput");
const themeToggle = $("#themeToggle");
const historySection = $("#historySection");
const historyList = $("#historyList");
const genDemoBtn = $("#genDemoBtn");
const genEstimateBtn = $("#genEstimateBtn");
const estimatePanel = $("#estimatePanel");
const estDomain = $("#estDomain");
const estFirst = $("#estFirst");
const estLast = $("#estLast");
const estRunBtn = $("#estRunBtn");
const jsonBtn = $("#jsonBtn");
const insights = $("#insights");
const insightBars = $("#insightBars");
const pitchModal = $("#pitchModal");
const pitchSubject = $("#pitchSubject");
const pitchBody = $("#pitchBody");
const pitchCopy = $("#pitchCopy");
const pitchClose = $("#pitchClose");
const importLeadsBtn = $("#importLeadsBtn");
const leadsSection = $("#leadsSection");
const leadsStatus = $("#leadsStatus");
const leadsRefreshBtn = $("#leadsRefreshBtn");
const leadsExportBtn = $("#leadsExportBtn");
const leadsList = $("#leadsList");
const leadsStats = $("#leadsStats");
const dashToggleBtn = $("#dashToggleBtn");
const dashboardPanel = $("#dashboardPanel");
const dashTotal = $("#dashTotal");
const dashNew = $("#dashNew");
const dashNoStatus = $("#dashNoStatus");
const dashDomains = $("#dashDomains");
const dashScans = $("#dashScans");
const dashStatut = $("#dashStatut");
const dashHeat = $("#dashHeat");
const dashDomType = $("#dashDomType");
const dashDomainsBox = $("#dashDomainsBox");
const dashSources = $("#dashSources");
const dashTimeline = $("#dashTimeline");
let dashboardLoaded = false;

const STATUS_LABELS = { recente: "Récente", active: "Active", ancienne: "Ancienne" };
const TAGS = ["", "Lead", "Client", "Prospect", "Fournisseur", "Partenaire", "Spam"];
const STORAGE_KEY = "maillens_history";
const THEME_KEY = "maillens_theme";
const TAGS_KEY = "maillens_tags";
const PAGE_SIZE = 50;

let lastData = null;
let pageRendered = 0;

/* ── Theme ────────────────────────────────────────────── */
function applyTheme(theme) {
    document.body.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
}
(function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved) {
        applyTheme(saved);
    } else {
        const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        applyTheme(prefersDark ? "dark" : "light");
    }
})();
themeToggle.addEventListener("click", () => {
    const current = document.body.getAttribute("data-theme");
    applyTheme(current === "dark" ? "light" : "dark");
});

/* ── File import ─────────────────────────────────────── */
fileInput.addEventListener("change", async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    const parts = [];
    for (const file of files) {
        try {
            parts.push(await file.text());
        } catch { /* fichier illisible, ignoré */ }
    }
    textEl.value = parts.join("\n\n");
    textEl.focus();
    fileInput.value = "";
});

/* ── Tags (persistés) ──────────────────────────────────── */
function getTags() {
    try { return JSON.parse(localStorage.getItem(TAGS_KEY)) || {}; }
    catch { return {}; }
}

function setTag(email, tag) {
    const t = getTags();
    if (tag) t[email] = tag; else delete t[email];
    localStorage.setItem(TAGS_KEY, JSON.stringify(t));
}

/* ── Extract ─────────────────────────────────────────── */
async function extract() {
    const value = textEl.value.trim();
    if (!value) return;

    resultsEl.innerHTML = "";
    statsEl.innerHTML = "";
    copyBar.hidden = true;
    copyMsg.textContent = "";
    insights.hidden = true;

    extractBtn.classList.add("loading");
    extractBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Analyse...';

    try {
        const res = await fetch("/extract", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: value }),
        });
        const data = await res.json();

        if (!res.ok) {
            resultsEl.innerHTML = `<div class="error-msg">${data.error || "Erreur"}</div>`;
            return;
        }

        if (data.total === 0) {
            resultsEl.innerHTML = `<div class="empty-hint">Aucun email trouvé dans le texte.</div>`;
            return;
        }

        lastData = data;

        statsEl.innerHTML = `
            <div class="stat total">${data.total}<small>Total</small></div>
            <div class="stat active">${data.actives}<small>Actives</small></div>
            <div class="stat recente">${data.recentes}<small>Récentes</small></div>
            <div class="stat chaud">${data.chauds}<small>Chauds</small></div>
            <div class="stat pro">${data.pros}<small>Pro</small></div>
            ${data.jetables > 0 ? `<div class="stat invalid">${data.jetables}<small>Jetables</small></div>` : ""}
            ${data.typos_corriges > 0 ? `<div class="stat typo">${data.typos_corriges}<small>Typos</small></div>` : ""}
            ${data.invalides > 0 ? `<div class="stat invalid">${data.invalides}<small>Invalides</small></div>` : ""}
        `;

        renderInsights(data);

        pageRendered = 0;
        appendResults();

        copyBar.hidden = false;
        saveToHistory(value, data);
        renderHistory();
    } catch (err) {
        resultsEl.innerHTML = `<div class="error-msg">Erreur réseau : ${err.message}</div>`;
    } finally {
        extractBtn.classList.remove("loading");
        extractBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Analyser';
    }
}

function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

function renderEmailCard(e, i) {
    const emailDisplay = e.original
        ? `<span class="typo-badge">corrigé</span> <del style="color:var(--text-muted);font-weight:400;font-size:13px">${e.original}</del> → ${e.email}`
        : e.email;
    const sources = (e.sources || []).map(s => `<span class="source-badge">${s}</span>`).join(" ");
    const contextHtml = e.context ? `<div class="email-context">« ${escapeHtml(e.context)} »</div>` : "";
    const savedTag = getTags()[e.email] || "";
    const tagOptions = TAGS.map(t => `<option value="${t}" ${t === savedTag ? "selected" : ""}>${t || "— Tag —"}</option>`).join("");
    const scoreColor = e.score >= 75 ? "var(--green)" : e.score >= 50 ? "var(--amber)" : "var(--red)";
    const audienceBadge = e.audience === "jetable"
        ? `<span class="aud-badge jetable" title="Adresse jetable">Jetable</span>`
        : e.audience === "generique"
            ? `<span class="aud-badge generique" title="Adresse générique (info@, contact@...)">Générique</span>`
            : "";
    const lastSeen = e.last_seen ? `<span class="last-seen" title="Dernière activité détectée">vu ${e.last_seen}</span>` : "";
    return `
        <div class="email-card" style="animation-delay:${i * 0.04}s" data-email="${escapeHtml(e.email)}">
            <div class="email-left">
                <div class="email-addr">${emailDisplay}</div>
                <div class="email-meta">
                    <span class="provider-badge">${e.provider}</span>
                    <span class="type-badge ${e.domain_type}">${e.domain_type === "pro" ? "Pro" : "Perso"}</span>
                    ${audienceBadge}
                    ${sources}
                    ${lastSeen}
                </div>
                ${contextHtml}
            </div>
            <div class="email-right">
                <div class="score-wrap" title="Score de qualité ${e.score}/100">
                    <div class="score-ring" style="background:conic-gradient(${scoreColor} ${e.score * 3.6}deg, var(--border) 0deg)">
                        <div class="score-core">${e.score}</div>
                    </div>
                </div>
                <span class="badge ${e.status}">${STATUS_LABELS[e.status]}</span>
                <button class="btn-relance" data-email="${escapeHtml(e.email)}" title="Générer un email de relance pour ce contact">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 2 11 13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                    Relance
                </button>
                <select class="tag-select" data-email="${escapeHtml(e.email)}">${tagOptions}</select>
            </div>
        </div>
    `;
}

function appendResults() {
    if (!lastData || !lastData.emails) return;
    const remaining = lastData.emails.length - pageRendered;
    if (remaining <= 0) return;
    const slice = lastData.emails.slice(pageRendered, pageRendered + PAGE_SIZE);
    resultsEl.insertAdjacentHTML("beforeend", slice.map((e, i) => renderEmailCard(e, pageRendered + i)).join(""));
    pageRendered += slice.length;
    updateLoadMore();
}

function updateLoadMore() {
    const remaining = lastData && lastData.emails ? lastData.emails.length - pageRendered : 0;
    let btn = document.getElementById("loadMoreBtn");
    if (remaining > 0) {
        if (!btn) {
            btn = document.createElement("button");
            btn.id = "loadMoreBtn";
            btn.className = "btn-ghost load-more";
            btn.addEventListener("click", appendResults);
            resultsEl.appendChild(btn);
        }
        btn.textContent = `Voir plus d'emails (${remaining})`;
    } else if (btn) {
        btn.remove();
    }
}

/* ── Copy ────────────────────────────────────────────── */
function selectedEmails() {
    if (!lastData) return [];
    const filter = copyFilter.value;
    if (filter === "all") return lastData.emails.map(e => e.email);
    return lastData.emails.filter(e => {
        if (filter === "chaud") return e.heat === "chaud";
        if (filter === "tiede") return e.heat === "tiede";
        if (filter === "froid") return e.heat === "froid";
        if (filter === "pro") return e.domain_type === "pro";
        if (filter === "perso") return e.domain_type === "perso";
        if (filter === "nominal") return e.audience !== "jetable";
        if (filter === "jetable") return e.audience === "jetable";
        return e.status === filter;
    }).map(e => e.email);
}

function showCopyFeedback(msg) {
    copyMsg.textContent = msg;
    copyMsg.style.opacity = "1";
    setTimeout(() => { copyMsg.style.opacity = "0"; copyMsg.textContent = ""; }, 2200);
}

async function copyEmails() {
    const emails = selectedEmails();
    if (!emails.length) return showCopyFeedback("Aucun email");
    try {
        await navigator.clipboard.writeText(emails.join("\n"));
    } catch {
        const ta = document.createElement("textarea");
        ta.value = emails.join("\n");
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
    }
    showCopyFeedback(`Copié (${emails.length})`);
}

/* ── Export CSV ──────────────────────────────────────── */
function exportCSV() {
    if (!lastData) return;
    const tagsStore = getTags();
    const rows = [["email", "provider", "domain", "type", "status", "score", "heat", "sources", "context", "original", "tag", "last_seen"]];
    lastData.emails.forEach(e => {
        rows.push([
            e.email, e.provider, e.domain, e.domain_type, e.status, e.score, e.heat,
            (e.sources || []).join("; "),
            (e.context || "").replace(/"/g, '""'),
            e.original || "", tagsStore[e.email] || "", e.last_seen || ""
        ]);
    });
    const csv = rows.map(r => r.map(c => `"${c}"`).join(",")).join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `maillens_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showCopyFeedback("CSV téléchargé");
}

/* ── Export JSON ──────────────────────────────────────── */
function exportJSON() {
    if (!lastData) return;
    const blob = new Blob([JSON.stringify(lastData, null, 2)], { type: "application/json;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `maillens_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showCopyFeedback("JSON téléchargé");
}

/* ── Insights (barres CSS) ────────────────────────────── */
function countTop(emails, keySelector, nb) {
    const counts = {};
    emails.forEach(e => {
        const keys = keySelector(e);
        (Array.isArray(keys) ? keys : [keys]).forEach(k => {
            if (k == null || k === "") return;
            counts[k] = (counts[k] || 0) + 1;
        });
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, nb);
}

function barBlock(title, entries, total, colors) {
    if (!entries.length) return "";
    const rows = entries.map(([label, n]) => {
        const pct = total ? Math.round((n / total) * 100) : 0;
        const fillCss = colors && colors[label] ? `;background:${colors[label]}` : "";
        return `
            <div class="bar-row">
                <span class="bar-label">${escapeHtml(label)}</span>
                <div class="bar-track">
                    <div class="bar-fill" style="width:${pct}%${fillCss}"></div>
                </div>
                <span class="bar-val">${n}</span>
            </div>`;
    }).join("");
    return `<div class="bar-group"><div class="bar-title">${escapeHtml(title)}</div>${rows}</div>`;
}

const HEAT_LABELS = { chaud: "Chaud", tiede: "Tiède", froid: "Froid" };
const STATUS_COLORS = {
    "À traiter": "var(--amber)",
    Prospect: "var(--accent)",
    "Contacté": "#7c5cff",
    Client: "var(--green)",
    Perdu: "var(--red)",
    Spam: "var(--text-muted)",
};
const HEAT_COLORS = { Chaud: "var(--green)", "Tiède": "var(--amber)", Froid: "var(--red)" };

function renderTimeline(points) {
    if (!points.length) return '<div class="empty-hint">Aucune analyse sur la période.</div>';
    const max = Math.max(...points.map(p => p.count), 1);
    const bars = points.map(p => {
        const h = p.count ? Math.max(8, Math.round((p.count / max) * 110)) : 3;
        return `
            <div class="tl-col" title="${p.label} : ${p.count}">
                <div class="tl-bar" style="height:${h}px"></div>
                <span class="tl-val">${p.count || ""}</span>
                <span class="tl-label">${p.label.slice(5)}</span>
            </div>`;
    }).join("");
    return `<div class="timeline">${bars}</div>`;
}

async function loadDashboard() {
    dashboardLoaded = true;
    try {
        const res = await fetch("/leads/dashboard");
        const b = await res.json();
        dashTotal.textContent = b.total;
        dashNew.textContent = b.nouveaux_30j;
        dashNoStatus.textContent = b.sans_statut;
        dashDomains.textContent = b.domaines_total;
        dashScans.textContent = b.scans_total;

        const toEntries = (obj) => Object.entries(obj).sort((a, b2) => b2[1] - a[1]);

        dashStatut.innerHTML = barBlock("", toEntries(b.par_statut), b.total, STATUS_COLORS);
        dashHeat.innerHTML = barBlock(
            "",
            toEntries(b.par_heat).map(([k, n]) => [HEAT_LABELS[k] || k, n]),
            b.total,
            HEAT_COLORS
        );
        dashDomType.innerHTML = barBlock(
            "",
            toEntries(b.par_type_domaine).map(([k, n]) => [k === "pro" ? "Pro (entreprise)" : "Perso", n]),
            b.total
        );
        dashDomainsBox.innerHTML = barBlock("", b.top_domaines.map(d => [d.domain, d.count]), b.total);
        dashSources.innerHTML = barBlock("", b.top_sources.map(s => [s.source, s.count]), null) || '<div class="empty-hint">Aucune source détectée.</div>';
        dashTimeline.innerHTML = renderTimeline(b.timeline);
    } catch { /* serveur indisponible */ }
}

function renderInsights(data) {
    const total = data.emails.length;
    const sources = countTop(data.emails, e => e.sources || [], 4);
    const providers = countTop(data.emails, e => e.provider, 4);
    const audiences = countTop(data.emails, e => e.audience, 3);
    const domTypes = [
        ["Pro", data.emails.filter(e => e.domain_type === "pro").length],
        ["Perso", data.emails.filter(e => e.domain_type === "perso").length],
    ].filter(([, n]) => n > 0);

    const html = [
        barBlock("Sources", sources, total),
        barBlock("Fournisseurs", providers, total),
        barBlock("Type de domaine", domTypes, total),
        barBlock("Fiabilité", audiences.map(([a, n]) => [labelAudience(a), n]), total),
    ].join("");
    if (!html) { insights.hidden = true; return; }
    insightBars.innerHTML = html;
    insights.hidden = false;
}

function labelAudience(a) {
    return { nominal: "Nominaux", generique: "Génériques", jetable: "Jetables" }[a] || a;
}

/* ── Base de leads ───────────────────────────────────── */
const LEAD_STATUS_OPTIONS = ["À traiter", "Prospect", "Contacté", "Client", "Perdu", "Spam"];

function attrEsc(s) {
    return escapeHtml(s).replace(/"/g, "&quot;");
}

function leadRow(l) {
    const name = [l.first_name, l.last_name].filter(Boolean).join(" ");
    const chips = (l.emails || []).map(e => `<code class="lead-chip">${escapeHtml(e)}</code>`).join("");
    const scoreColor = l.score >= 75 ? "var(--green)" : l.score >= 50 ? "var(--amber)" : "var(--red)";
    const heatLabels = { chaud: "Chaud", tiede: "Tiède", froid: "Froid" };
    const statusOptions = ["", ...LEAD_STATUS_OPTIONS]
        .map(s => `<option value="${s}" ${s === l.status ? "selected" : ""}>${s || "— Statut —"}</option>`)
        .join("");
    return `
        <div class="lead-row" data-id="${l.id}">
            <div class="lead-main">
                <div class="lead-email">
                    ${escapeHtml(l.canonical_email)}
                    <span class="lead-count">${(l.emails || []).length} adr.</span>
                </div>
                <div class="lead-meta">
                    ${name ? `<span class="lead-name">${escapeHtml(name)}</span>` : ""}
                    <span class="type-badge ${l.domain_type}">${l.domain_type === "pro" ? "Pro" : "Perso"}</span>
                    <span class="score-mini" style="color:${scoreColor}">${l.score}</span>
                    <span class="lead-heat">${heatLabels[l.heat] || l.heat}</span>
                    ${l.last_seen ? `<span class="last-seen">vu ${l.last_seen}</span>` : ""}
                    <span class="lead-scan">${l.scans}x</span>
                </div>
                <div class="lead-emails" hidden>${chips}</div>
            </div>
            <div class="lead-controls">
                <button class="lead-expand" data-id="${l.id}" title="Voir les adresses liées">▾</button>
                <select class="lead-status" data-id="${l.id}">${statusOptions}</select>
                <input class="lead-note" data-id="${l.id}" placeholder="Note…" value="${attrEsc(l.notes || "")}">
                <button class="lead-del" data-id="${l.id}" title="Supprimer ce lead">&times;</button>
            </div>
        </div>
    `;
}

async function loadLeads() {
    try {
        const qs = new URLSearchParams();
        if (leadsStatus.value) qs.set("status", leadsStatus.value);
        const res = await fetch(`/leads?${qs}`);
        const body = await res.json();
        leadsList.innerHTML = body.leads.length
            ? body.leads.map(leadRow).join("")
            : `<div class="empty-hint">Aucun lead. Analysez un texte puis cliquez sur « Importer les leads ».</div>`;
        const by = body.stats.by_status || {};
        const parts = [`${body.stats.total} total`];
        LEAD_STATUS_OPTIONS.forEach(s => { if (by[s]) parts.push(`${s}: ${by[s]}`); });
        leadsStats.textContent = parts.join(" · ");
        leadsSection.hidden = false;
    } catch { /* serveur indisponible */ }
}

async function importLeads() {
    if (!lastData || !lastData.emails || !lastData.emails.length) {
        return showCopyFeedback("Analysez d'abord un texte");
    }
    const label = importLeadsBtn.textContent;
    importLeadsBtn.classList.add("loading");
    importLeadsBtn.textContent = "Import…";
    try {
        const res = await fetch("/leads/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ emails: lastData.emails }),
        });
        const body = await res.json();
        if (!res.ok) return showCopyFeedback(body.error || "Erreur import");
        showCopyFeedback(`Import : ${body.created} créé(s), ${body.updated} mis à jour`);
        await loadLeads();
    } catch (err) {
        showCopyFeedback(`Erreur : ${err.message}`);
    } finally {
        importLeadsBtn.classList.remove("loading");
        importLeadsBtn.textContent = label;
    }
}

async function exportLeadsCSV() {
    try {
        const res = await fetch("/leads");
        const body = await res.json();
        const headers = ["email", "nom", "domaine", "type", "statut", "score", "heat", "notes", "adresses_liees", "scans"];
        const rows = body.leads.map(l => [
            l.canonical_email,
            [l.first_name, l.last_name].filter(Boolean).join(" "),
            l.domain, l.domain_type, l.status || "", l.score, l.heat,
            (l.notes || "").replace(/"/g, '""'),
            (l.emails || []).join("; "), l.scans
        ]);
        const csv = [headers, ...rows].map(r => r.map(c => `"${c}"`).join(",")).join("\n");
        const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `leads_${new Date().toISOString().slice(0, 10)}.csv`;
        a.click();
        URL.revokeObjectURL(url);
        showCopyFeedback("CSV des leads téléchargé");
    } catch (err) {
        showCopyFeedback(`Erreur : ${err.message}`);
    }
}

importLeadsBtn.addEventListener("click", importLeads);
leadsRefreshBtn.addEventListener("click", () => { loadLeads(); loadDashboard(); });
leadsExportBtn.addEventListener("click", exportLeadsCSV);
leadsStatus.addEventListener("change", loadLeads);

dashToggleBtn.addEventListener("click", () => {
    dashboardPanel.hidden = !dashboardPanel.hidden;
    if (!dashboardPanel.hidden) loadDashboard();
});

leadsList.addEventListener("click", async (e) => {
    const del = e.target.closest(".lead-del");
    if (del) {
        await fetch(`/leads/${del.dataset.id}`, { method: "DELETE" });
        await loadLeads();
        return;
    }
    const exp = e.target.closest(".lead-expand");
    if (exp) {
        const row = exp.closest(".lead-row");
        const chips = row.querySelector(".lead-emails");
        chips.hidden = !chips.hidden;
        exp.textContent = chips.hidden ? "▾" : "▴";
        return;
    }
});

leadsList.addEventListener("change", async (e) => {
    const statusSel = e.target.closest(".lead-status");
    const note = e.target.closest(".lead-note");
    const payload = {};
    if (statusSel) payload.status = statusSel.value;
    if (note) payload.notes = note.value.trim();
    if (!Object.keys(payload).length) return;
    const id = (statusSel || note).dataset.id;
    try {
        const res = await fetch(`/leads/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const body = await res.json();
        if (!res.ok) {
            showCopyFeedback(body.error || "Erreur");
        } else {
            showCopyFeedback("Lead mis à jour");
            await loadLeads();
        }
    } catch (err) {
        showCopyFeedback(`Erreur : ${err.message}`);
    }
});

/* ── Cold email (relance) ─────────────────────────────── */
async function openPitch(email, evt) {
    const btn = evt.currentTarget;
    const data = lastData?.emails.find(x => x.email === email);
    if (!lastData || !data) return;
    btn.classList.add("loading");
    pitchSubject.textContent = "Génération...";
    pitchBody.textContent = "";
    pitchModal.hidden = false;
    try {
        const res = await fetch("/generate/pitch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, context: data.context || "", sources: data.sources || [], score: data.score }),
        });
        const pitch = await res.json();
        if (!res.ok) {
            pitchSubject.textContent = "Erreur";
            pitchBody.textContent = pitch.error || "Erreur";
            return;
        }
        pitchSubject.textContent = `« ${pitch.subject} »`;
        pitchBody.textContent = pitch.text;
    } catch (err) {
        pitchSubject.textContent = "Erreur";
        pitchBody.textContent = `Erreur : ${err.message}`;
    } finally {
        btn.classList.remove("loading");
    }
}

resultsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-relance");
    if (btn) {
        openPitch(btn.dataset.email, { currentTarget: btn });
    }
});

resultsEl.addEventListener("change", (e) => {
    const sel = e.target.closest(".tag-select");
    if (sel) setTag(sel.dataset.email, sel.value);
});

pitchClose.addEventListener("click", () => { pitchModal.hidden = true; });
pitchModal.addEventListener("click", (e) => { if (e.target === pitchModal) pitchModal.hidden = true; });
pitchCopy.addEventListener("click", async () => {
    const orig = pitchCopy.innerHTML;
    const text = `${pitchSubject.textContent}\n\n${pitchBody.textContent}`;
    try {
        await navigator.clipboard.writeText(text);
        pitchCopy.textContent = "Copié";
        setTimeout(() => { pitchCopy.innerHTML = orig; }, 1400);
    } catch { /* presse-papier indisponible */ }
});

/* ── History (localStorage) ──────────────────────────── */
function getHistory() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || []; }
    catch { return []; }
}

function saveToHistory(text, data) {
    const hist = getHistory();
    hist.unshift({
        id: Date.now(),
        date: new Date().toLocaleString("fr-FR"),
        total: data.total,
        actives: data.actives,
        preview: text.slice(0, 120) + (text.length > 120 ? "..." : ""),
        text: text,
    });
    if (hist.length > 20) hist.length = 20;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(hist));
}

function renderHistory() {
    const hist = getHistory();
    if (!hist.length) { historySection.hidden = true; return; }
    historySection.hidden = false;
    historyList.innerHTML = hist.map(h => `
        <div class="history-item" data-id="${h.id}">
            <div style="flex:1;min-width:0">
                <div class="hist-info">${escapeHtml(h.preview)}</div>
                <div class="hist-date">${h.date}</div>
            </div>
            <div class="hist-count">${h.total} emails</div>
            <button class="hist-del" data-id="${h.id}" title="Supprimer">&times;</button>
        </div>
    `).join("");
}

historyList.addEventListener("click", (e) => {
    const del = e.target.closest(".hist-del");
    if (del) {
        e.stopPropagation();
        const id = Number(del.dataset.id);
        const hist = getHistory().filter(h => h.id !== id);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(hist));
        renderHistory();
        return;
    }
    const item = e.target.closest(".history-item");
    if (item) {
        const id = Number(item.dataset.id);
        const entry = getHistory().find(h => h.id === id);
        if (entry) {
            textEl.value = entry.text;
            extract();
            window.scrollTo({ top: 0, behavior: "smooth" });
        }
    }
});

/* ── Email generator ──────────────────────────────────── */
async function generateDemo() {
    genDemoBtn.classList.add("loading");
    try {
        const res = await fetch("/generate/demo", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ count: 12 }),
        });
        const data = await res.json();
        if (!res.ok) {
            resultsEl.innerHTML = `<div class="error-msg">${data.error || "Erreur"}</div>`;
            return;
        }
        textEl.value = data.text;
        estimatePanel.hidden = true;
        await extract();
    } catch (err) {
        resultsEl.innerHTML = `<div class="error-msg">Erreur : ${err.message}</div>`;
    } finally {
        genDemoBtn.classList.remove("loading");
    }
}

async function runEstimate() {
    const domain = estDomain.value.trim().toLowerCase();
    const first = estFirst.value.trim();
    const last = estLast.value.trim();
    if (!domain || !(first || last)) {
        resultsEl.innerHTML = `<div class="error-msg">Renseignez au moins un domaine et un prénom ou nom.</div>`;
        return;
    }
    estRunBtn.classList.add("loading");
    try {
        const res = await fetch("/generate/estimate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ domain, first_name: first, last_name: last }),
        });
        const data = await res.json();
        if (!res.ok) {
            resultsEl.innerHTML = `<div class="error-msg">${data.error || "Erreur"}</div>`;
            return;
        }
        copyBar.hidden = true;
        statsEl.innerHTML = "";
        lastData = null;
        insights.hidden = true;
        renderEstimate(data);
    } catch (err) {
        resultsEl.innerHTML = `<div class="error-msg">Erreur : ${err.message}</div>`;
    } finally {
        estRunBtn.classList.remove("loading");
    }
}

function copyText(btn, text) {
    const old = btn.textContent;
    btn.textContent = "Copié";
    setTimeout(() => { btn.textContent = old; }, 1400);
    navigator.clipboard?.writeText(text).catch(() => {});
}

function estRows(list) {
    return list.map(c => `
        <div class="email-card est-card">
            <div class="email-left">
                <div class="email-addr">${escapeHtml(c.email)}</div>
                <div class="email-meta"><span class="est-pattern">${escapeHtml(c.pattern)}</span></div>
            </div>
            <div class="email-right">
                <button class="btn-copy" onclick="copyText(this, '${escapeHtml(c.email)}')">Copier</button>
            </div>
        </div>
    `).join("");
}

function renderEstimate(data) {
    const candidates = data.candidates || [];
    const generic = data.generic || [];
    resultsEl.innerHTML = `
        <div class="gen-head glass">
            <div class="gen-head-title">
                <strong>${data.total}</strong> adresses pour
                <code>${escapeHtml(data.domain)}</code>
            </div>
            <button id="copyAllEst" class="btn-copy">Copier tout</button>
        </div>
        ${estRows(candidates).replace(/\n/g, "")}
        ${generic.length ? `
            <div class="gen-divider">Adresses génériques</div>
            ${estRows(generic).replace(/\n/g, "")}
        ` : ""}
    `;
    document.getElementById("copyAllEst")?.addEventListener("click", () => {
        const all = [...candidates, ...generic].map(c => c.email);
        const btn = document.getElementById("copyAllEst");
        copyText(btn, all.join("\n"));
    });
}

/* ── Events ──────────────────────────────────────────── */
extractBtn.addEventListener("click", extract);
genDemoBtn.addEventListener("click", generateDemo);
genEstimateBtn.addEventListener("click", () => {
    estimatePanel.hidden = !estimatePanel.hidden;
    if (!estimatePanel.hidden) estDomain.focus();
});
estRunBtn.addEventListener("click", runEstimate);
estDomain.addEventListener("keydown", (e) => { if (e.key === "Enter") runEstimate(); });
estFirst.addEventListener("keydown", (e) => { if (e.key === "Enter") runEstimate(); });
estLast.addEventListener("keydown", (e) => { if (e.key === "Enter") runEstimate(); });
copyBtn.addEventListener("click", copyEmails);
csvBtn.addEventListener("click", exportCSV);
jsonBtn.addEventListener("click", exportJSON);
clearBtn.addEventListener("click", () => {
    textEl.value = "";
    resultsEl.innerHTML = "";
    statsEl.innerHTML = "";
    copyBar.hidden = true;
    copyMsg.textContent = "";
    insights.hidden = true;
    lastData = null;
});

textEl.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") extract();
});

/* ── Init ────────────────────────────────────────────── */
renderHistory();
loadLeads();
