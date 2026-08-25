const fmtEUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

let detailChart = null;
let currentDetailId = null;

function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* ignore */ }
    if (typeof detail === "object" && detail !== null) {
      const e = new Error(detail.message || JSON.stringify(detail));
      e.payload = detail;
      throw e;
    }
    throw new Error(detail);
  }
  return res.json();
}

function fmtTime(iso) {
  if (!iso) return "–";
  const d = new Date(iso.replace(" ", "T") + (iso.includes("Z") ? "" : "Z"));
  if (isNaN(d)) return iso;
  return d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function changeHtml(abs, pct) {
  if (abs === null || abs === undefined) return '<span class="muted">–</span>';
  const cls = abs < 0 ? "change-down" : abs > 0 ? "change-up" : "muted";
  const arrow = abs < 0 ? "▼" : abs > 0 ? "▲" : "•";
  return `<span class="${cls}">${arrow} ${abs > 0 ? "+" : ""}${abs.toFixed(2)} (${pct > 0 ? "+" : ""}${pct}%)</span>`;
}

function availHtml(avail) {
  if (!avail) return '<span class="muted">–</span>';
  const cls = avail.includes("out") || avail.includes("nicht") ? "avail-out" : avail.includes("low") ? "avail-low" : "avail-in";
  return `<span class="avail-dot ${cls}"></span>${avail}`;
}

function sparkline(points) {
  if (!points || points.length < 2) return '<span class="muted">keine Daten</span>';
  const w = 130, h = 34, pad = 2;
  const prices = points.map((p) => p.p);
  const min = Math.min(...prices), max = Math.max(...prices);
  const range = max - min || 1;
  const stepX = (w - pad * 2) / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = pad + i * stepX;
    const y = h - pad - ((p.p - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const trend = prices[prices.length - 1] < prices[0];
  const color = trend ? "var(--green)" : prices[prices.length - 1] > prices[0] ? "var(--red)" : "var(--muted)";
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline fill="none" stroke="${color}" stroke-width="1.6" points="${coords.join(" ")}"/></svg>`;
}

async function loadStatus() {
  const s = await api("/api/status");
  const badges = [];
  badges.push(`<span class="badge ${s.firecrawl ? "on" : "off"}">Firecrawl ${s.firecrawl ? "✓" : "✗"}</span>`);
  badges.push(`<span class="badge ${s.tavily ? "on" : "off"}">Tavily ${s.tavily ? "✓" : "✗"}</span>`);
  if (s.demo) badges.push('<span class="badge demo">Demo-Modus</span>');
  document.getElementById("provider-badges").innerHTML = badges.join("");
  document.getElementById("next-run").textContent =
    `Auto-Prüfung: alle ${s.check_interval_minutes} Min · nächster Lauf: ${fmtTime(s.next_run)}`;
  document.getElementById("demo-banner").style.display = s.demo ? "flex" : "none";
  renderStats(s.stats);
}

function renderStats(stats) {
  const cards = [
    { label: "Produkte", value: stats.products, cls: "" },
    { label: "Checks heute", value: stats.checks_today, cls: "" },
    { label: "🟢 Drops (7T)", value: stats.drops_7d, cls: "green" },
    { label: "🔴 Anstiege (7T)", value: stats.rises_7d, cls: "red" },
  ];
  document.getElementById("stats-row").innerHTML = cards
    .map((c) => `<div class="stat-card ${c.cls}"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`)
    .join("");
}

function fmtInterval(h) {
  if (h % 24 === 0) return `${h / 24} Tag${h / 24 > 1 ? "e" : ""}`;
  return `${h} Std`;
}

const INTERVAL_CHOICES = [1, 3, 6, 12, 24, 48, 168];

function intervalSelectHtml(current) {
  const choices = INTERVAL_CHOICES.includes(current)
    ? INTERVAL_CHOICES
    : [...INTERVAL_CHOICES, current].sort((a, b) => a - b);
  return choices
    .map((h) => `<option value="${h}" ${h === current ? "selected" : ""}>${fmtInterval(h)}</option>`)
    .join("");
}

async function setIntervalHours(ev, id, sel) {
  if (ev) ev.stopPropagation();
  try {
    await api(`/api/products/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ interval_hours: Number(sel.value) }),
    });
    toast(`Prüfintervall gesetzt auf ${fmtInterval(Number(sel.value))}.`, "success");
    refreshAll();
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
}

async function saveDetailInterval(val) {
  if (!currentDetailId) return;
  try {
    await api(`/api/products/${currentDetailId}`, {
      method: "PATCH",
      body: JSON.stringify({ interval_hours: Number(val) }),
    });
    toast(`Prüfintervall gesetzt auf ${fmtInterval(Number(val))}.`, "success");
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
}

function renderProducts(products) {
  const tbody = document.getElementById("products-body");
  if (!products.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">Noch keine Produkte. Oben eine URL hinzufügen.</td></tr>';
    return;
  }
  tbody.innerHTML = products
    .map((p) => {
      const name = p.name || p.url;
      const ih = p.interval_hours || 24;
      return `<tr data-id="${p.id}">
        <td class="pname no-label" title="${p.url}${p.note ? "\n\n📝 " + p.note.replace(/"/g, "&quot;") : ""}"><a href="${p.url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${name}</a><span class="src-tag">${p.last_source || "?"}</span>${p.note ? `<div class="pnote">📝 ${p.note}</div>` : ""}</td>
        <td data-label="Shop" class="muted">${p.retailer || "–"}</td>
        <td data-label="Preis" class="num"><span class="price">${p.last_price != null ? fmtEUR.format(p.last_price) : "–"}</span>${availHtml(p.last_availability) !== "<span class=\"muted\">–</span>" ? "<br>" + availHtml(p.last_availability) : ""}</td>
        <td data-label="Änderung" class="num">${changeHtml(p.change_abs, p.change_pct)}</td>
        <td data-label="Verlauf">${sparkline(p.sparkline)}</td>
        <td data-label="Intervall" onclick="event.stopPropagation()"><select class="interval-select" onchange="setIntervalHours(event, ${p.id}, this)" title="Nächste geplante Prüfung: ${fmtTime(p.next_check_at)}">${intervalSelectHtml(ih)}</select></td>
        <td data-label="Geprüft" class="muted">${fmtTime(p.last_checked)}</td>
        <td data-label="Aktionen" class="row-actions">
          <button class="btn" onclick="checkProduct(event, ${p.id})" title="Jetzt prüfen">⟳</button>
          <button class="btn danger" onclick="deleteProduct(event, ${p.id}, '${name.replace(/'/g, "\\'")}')" title="Löschen">🗑</button>
        </td>
      </tr>`;
    })
    .join("");
}

async function loadProducts() {
  const products = await api("/api/products");
  renderProducts(products);
}

function renderEvents(events) {
  const ul = document.getElementById("events-list");
  if (!events.length) {
    ul.innerHTML = '<li class="empty">Keine Ereignisse.</li>';
    return;
  }
  const cls = { price_drop: "ev-drop", price_rise: "ev-rise", error: "ev-error", info: "ev-info", success: "ev-success" };
  ul.innerHTML = events
    .map((e) => `<li class="${cls[e.type] || ""}">${e.message}<span class="when">${fmtTime(e.created_at)}</span></li>`)
    .join("");
}

async function loadEvents() {
  const events = await api("/api/events?limit=40");
  renderEvents(events);
}

async function refreshAll() {
  try {
    await Promise.all([loadStatus(), loadProducts(), loadEvents()]);
  } catch (err) {
    console.error(err);
  }
}

async function checkProduct(ev, id) {
  if (ev) ev.stopPropagation();
  try {
    await api(`/api/products/${id}/check`, { method: "POST" });
    toast("Prüfung gestartet …");
    setTimeout(refreshAll, 2500);
    setTimeout(refreshAll, 8000);
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
}

async function deleteProduct(ev, id, name) {
  if (ev) ev.stopPropagation();
  if (!confirm(`„${name}" wirklich löschen (inkl. Historie)?`)) return;
  try {
    await api(`/api/products/${id}`, { method: "DELETE" });
    toast("Produkt gelöscht", "success");
    refreshAll();
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
}

document.getElementById("check-all-btn").addEventListener("click", async () => {
  const btn = document.getElementById("check-all-btn");
  btn.disabled = true;
  try {
    await api("/api/check-all", { method: "POST" });
    toast("Alle Produkte werden geprüft …");
    setTimeout(refreshAll, 3000);
    setTimeout(refreshAll, 12000);
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  } finally {
    setTimeout(() => (btn.disabled = false), 2000);
  }
});

document.getElementById("add-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const urlEl = document.getElementById("add-url");
  const nameEl = document.getElementById("add-name");
  let url = urlEl.value.trim();
  if (url && !/^https?:\/\//i.test(url)) url = "https://" + url;
  try {
    const res = await api("/api/products", {
      method: "POST",
      body: JSON.stringify({ url, name: nameEl.value.trim() }),
    });
    toast(
      res.replaced_existing
        ? "Bestehenden Eintrag zurückgesetzt – neue Prüfung läuft …"
        : "Produkt hinzugefügt – erste Prüfung läuft …",
      "success"
    );
    urlEl.value = "";
    nameEl.value = "";
    refreshAll();
    setTimeout(refreshAll, 4000);
    setTimeout(refreshAll, 15000);
  } catch (err) {
    if (err.payload && err.payload.product_id && confirm("URL wird bereits getrackt. Historie zurücksetzen und neu prüfen?")) {
      try {
        await api(`/api/products/${err.payload.product_id}/reset`, { method: "POST" });
        toast("Produkt zurückgesetzt – Prüfung läuft …", "success");
        urlEl.value = "";
        nameEl.value = "";
        refreshAll();
        setTimeout(refreshAll, 6000);
        return;
      } catch (err2) {
        toast(`Fehler: ${err2.message}`, "error");
        return;
      }
    }
    toast(`Fehler: ${err.message}`, "error");
  }
});

async function openSettings() {
  try {
    const s = await api("/api/settings");
    document.getElementById("set-firecrawl").value = "";
    document.getElementById("set-tavily").value = "";
    document.getElementById("set-firecrawl-state").textContent = s.firecrawl.configured
      ? `(gesetzt: ${s.firecrawl.masked}${s.firecrawl.from_env ? ", aus .env" : ""})`
      : "(nicht gesetzt)";
    document.getElementById("set-tavily-state").textContent = s.tavily.configured
      ? `(gesetzt: ${s.tavily.masked}${s.tavily.from_env ? ", aus .env" : ""})`
      : "(nicht gesetzt)";
    document.getElementById("set-demo-mode").value = s.demo_mode;
    document.getElementById("settings-modal").showModal();
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
}

document.getElementById("settings-btn").addEventListener("click", openSettings);
document.getElementById("banner-settings-btn").addEventListener("click", openSettings);
document.getElementById("settings-close").addEventListener("click", () => {
  document.getElementById("settings-modal").close();
});

document.getElementById("settings-save").addEventListener("click", async () => {
  const body = {
    demo_mode: document.getElementById("set-demo-mode").value,
  };
  const fc = document.getElementById("set-firecrawl").value.trim();
  const tv = document.getElementById("set-tavily").value.trim();
  if (fc) body.firecrawl_api_key = fc;
  if (tv) body.tavily_api_key = tv;
  try {
    const s = await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
    document.getElementById("settings-modal").close();
    toast("Einstellungen gespeichert", "success");
    refreshAll();
    if (!s.demo_active) {
      toast("Demo-Modus inaktiv – prüfe alle Produkte mit den echten APIs …");
      await api("/api/check-all", { method: "POST" });
      setTimeout(refreshAll, 5000);
      setTimeout(refreshAll, 20000);
    }
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
});

document.getElementById("demo-exit-btn").addEventListener("click", async () => {
  try {
    const s = await api("/api/demo/exit", { method: "POST" });
    toast("Demo-Modus beendet.", "success");
    refreshAll();
    if (!s.firecrawl.configured && !s.tavily.configured) {
      toast("Achtung: Ohne API-Keys schlagen echte Prüfungen fehl.", "error");
      openSettings();
    } else {
      await api("/api/check-all", { method: "POST" });
      setTimeout(refreshAll, 5000);
    }
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
});

document.getElementById("demo-clear-btn").addEventListener("click", async () => {
  if (!confirm("Alle Demo-Produkte (simulierte Preise) löschen?")) return;
  try {
    const r = await api("/api/demo/clear-products", { method: "POST" });
    toast(`${r.removed} Demo-Produkte entfernt.`, "success");
    refreshAll();
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
});

async function openDetail(id) {
  const products = await api("/api/products");
  const p = products.find((x) => x.id === id);
  if (!p) return;
  currentDetailId = id;
  document.getElementById("detail-title").textContent = p.name || p.url;
  const link = document.getElementById("detail-url");
  link.href = p.url;
  link.textContent = p.url;

  const prices = p.sparkline.map((s) => s.p);
  const avg = prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : null;
  const stats = [
    ["Aktueller Preis", p.last_price != null ? fmtEUR.format(p.last_price) : "–"],
    ["Ø 30 Tage", avg != null ? fmtEUR.format(avg) : "–"],
    ["Min 30 Tage", p.min_30d != null ? fmtEUR.format(p.min_30d) : "–"],
    ["Max 30 Tage", p.max_30d != null ? fmtEUR.format(p.max_30d) : "–"],
    ["Änderung", p.change_abs != null ? `${p.change_abs > 0 ? "+" : ""}${p.change_abs.toFixed(2)} (${p.change_pct}%)` : "–"],
    ["Nächste Prüfung", p.next_check_at ? fmtTime(p.next_check_at) : "bei nächstem Lauf"],
  ];
  document.getElementById("detail-stats").innerHTML = stats
    .map(([l, v]) => `<div><span>${l}</span><b>${v}</b></div>`)
    .join("");
  document.getElementById("detail-interval").innerHTML = intervalSelectHtml(p.interval_hours || 24);
  document.getElementById("detail-note").value = p.note || "";

  const ctx = document.getElementById("detail-chart");
  if (detailChart) detailChart.destroy();
  detailChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: p.sparkline.map((s) => fmtTime(s.t)),
      datasets: [
        {
          label: "Preis",
          data: p.sparkline.map((s) => s.p),
          borderColor: "#4493f8",
          backgroundColor: "rgba(68,147,248,.12)",
          fill: true,
          tension: 0.25,
          pointRadius: 2,
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#8b949e", maxTicksLimit: 8, font: { size: 10 } }, grid: { color: "rgba(45,51,59,.4)" } },
        y: { ticks: { color: "#8b949e", callback: (v) => v + " €" }, grid: { color: "rgba(45,51,59,.4)" } },
      },
    },
  });
  document.getElementById("detail-modal").showModal();
}

document.getElementById("note-save").addEventListener("click", async () => {
  if (!currentDetailId) return;
  try {
    await api(`/api/products/${currentDetailId}`, {
      method: "PATCH",
      body: JSON.stringify({ note: document.getElementById("detail-note").value }),
    });
    toast("Notiz gespeichert.", "success");
    refreshAll();
  } catch (err) {
    toast(`Fehler: ${err.message}`, "error");
  }
});

document.getElementById("products-body").addEventListener("click", (ev) => {
  const row = ev.target.closest("tr[data-id]");
  if (row) openDetail(Number(row.dataset.id));
});

document.getElementById("detail-close").addEventListener("click", () => {
  document.getElementById("detail-modal").close();
});

document.getElementById("detail-check").addEventListener("click", async () => {
  if (!currentDetailId) return;
  await api(`/api/products/${currentDetailId}/check`, { method: "POST" });
  toast("Prüfung gestartet …");
  setTimeout(async () => {
    await refreshAll();
    openDetail(currentDetailId);
  }, 4000);
});

refreshAll();
setInterval(refreshAll, 30000);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get("action") === "check-all") {
  document.getElementById("check-all-btn").click();
}
