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
    try { detail = (await res.json()).detail || detail; } catch {}
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
    `Nächste automatische Prüfung: ${fmtTime(s.next_run)} (${s.schedule} Uhr)`;
  document.getElementById("demo-hint").textContent = s.demo
    ? "Demo-Modus: Ohne API-Keys werden simulierte Preise erzeugt. Firecrawl- und/oder Tavily-Key in /opt/firecrawlapp/.env eintragen und Dienst neu starten."
    : "";
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

function renderProducts(products) {
  const tbody = document.getElementById("products-body");
  if (!products.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">Noch keine Produkte. Oben eine URL hinzufügen.</td></tr>';
    return;
  }
  tbody.innerHTML = products
    .map((p) => {
      const name = p.name || p.url;
      return `<tr data-id="${p.id}">
        <td class="pname" title="${p.url}"><a href="${p.url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${name}</a><span class="src-tag">${p.last_source || "?"}</span></td>
        <td class="muted">${p.retailer || "–"}</td>
        <td class="num"><span class="price">${p.last_price != null ? fmtEUR.format(p.last_price) : "–"}</span>${availHtml(p.last_availability) !== "<span class=\"muted\">–</span>" ? "<br>" + availHtml(p.last_availability) : ""}</td>
        <td class="num">${changeHtml(p.change_abs, p.change_pct)}</td>
        <td>${sparkline(p.sparkline)}</td>
        <td class="muted">${fmtTime(p.last_checked)}</td>
        <td class="row-actions">
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
  const cls = { price_drop: "ev-drop", price_rise: "ev-rise", error: "ev-error", info: "ev-info" };
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
  try {
    await api("/api/products", {
      method: "POST",
      body: JSON.stringify({ url: urlEl.value.trim(), name: nameEl.value.trim() }),
    });
    toast("Produkt hinzugefügt – erste Prüfung läuft …", "success");
    urlEl.value = "";
    nameEl.value = "";
    refreshAll();
    setTimeout(refreshAll, 4000);
    setTimeout(refreshAll, 15000);
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
  ];
  document.getElementById("detail-stats").innerHTML = stats
    .map(([l, v]) => `<div><span>${l}</span><b>${v}</b></div>`)
    .join("");

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
