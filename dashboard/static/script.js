const REFRESH_INTERVAL_MS = 5000;
const charts = {};
let searchTimer = null;
let notificationItems = [];
let lastUsbNotification = localStorage.getItem("usbSentinelLastNotification") || "";
let notificationBaselineReady = Boolean(lastUsbNotification);

// The device_code of the currently connected USB, as reported by
// /api/usb_details. All device-specific dashboard data (summary cards,
// tables, activity feed, charts) is scoped to this device. Updated by
// loadUsbDetails(), which must always run before any device-filtered
// request so the rest of the dashboard never queries against a stale
// or empty device.
let activeDeviceCode = "";

// Fixed colors per file-event category so the Event Distribution chart
// always uses the same color for "Created", "Modified", etc. regardless
// of what order the backend's GROUP BY happens to return them in.
const DISTRIBUTION_COLORS = {
  Created: "#2563eb",
  Modified: "#16a34a",
  Deleted: "#f59e0b",
  Renamed: "#e5484d",
};

let refreshCountdown = REFRESH_INTERVAL_MS / 1000;

const elements = {
  usbSearch: document.getElementById("usbSearch"),
  fileSearch: document.getElementById("fileSearch"),
  eventSearch: document.getElementById("eventSearch"),
  dateSearch: document.getElementById("dateSearch"),
  period: document.getElementById("periodSelect"),
  eventFilter: document.getElementById("eventFilter"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function badgeClass(action) {
  const value = String(action || "").toUpperCase();
  if (value === "CONNECTED" || value === "CREATED") return "badge-connected";
  if (value === "REMOVED" || value === "DELETED") return "badge-removed";
  if (value === "MODIFIED") return "badge-modified";
  if (value.startsWith("RENAMED")) return "badge-renamed";
  return "";
}

function formatTime(value, timeOnly = false) {
  if (!value) return "--";
  const [date, time] = String(value).split(" ");
  if (timeOnly) return time || date;
  return `${escapeHtml(date)}<br>${escapeHtml(time || "")}`;
}

function selectedEvent() {
  return elements.eventFilter.value !== "all" ? elements.eventFilter.value : elements.eventSearch.value.trim();
}

function filterParams(extra = {}) {
  const params = {
    usb: elements.usbSearch.value.trim(),
    file: elements.fileSearch.value.trim(),
    event: selectedEvent(),
    date: elements.dateSearch.value,
    period: elements.period.value,
    ...extra,
  };
  // Scope device-specific requests to the currently connected USB. Only
  // attach device_code when we actually have one, so we never send
  // device_code=undefined/null when no USB is connected.
  if (activeDeviceCode) params.device_code = activeDeviceCode;
  return new URLSearchParams(params);
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed (${response.status}): ${url}`);
  return response.json();
}

function updateConnectionStatus(connected, label) {
  const card = document.getElementById("connectionCard");
  const dot = document.getElementById("connectionDot");
  const pill = document.getElementById("connectionStatusPill");
  const statusLabel = document.getElementById("connectionLabel");

  card.classList.toggle("disconnected", !connected);
  dot.classList.toggle("offline", !connected);
  statusLabel.textContent = label;
  pill.className = `connection-pill ${connected ? "online" : "offline"}`;
  pill.innerHTML = `<i></i>${connected ? "USB connected" : "No USB connected"}`;
}

function updateDeviceBadge() {
  const badge = document.getElementById("statsDeviceBadge");
  if (!badge) return;
  badge.textContent = activeDeviceCode || "No device";
  badge.classList.toggle("offline", !activeDeviceCode);
}

async function loadSummary() {
  const query = activeDeviceCode ? `?device_code=${encodeURIComponent(activeDeviceCode)}` : "";
  const data = await getJSON(`/api/summary${query}`);
  document.getElementById("cardUsbEvents").textContent = data.total_usb_events;
  document.getElementById("cardFileEvents").textContent = data.total_file_events;
  document.getElementById("cardConnected").textContent = data.usb_connected ? `${data.usb_connected} active` : "0 active";
  document.getElementById("cardRegistered").textContent = data.registered_usbs;
  updateConnectionStatus(data.usb_connected > 0, data.connection_label);
}

async function loadUsbDetails() {
  const rows = await getJSON("/api/usb_details");
  const body = document.getElementById("usbDetailsBody");
  if (!rows.length) {
    activeDeviceCode = "";
    updateDeviceBadge();
    body.innerHTML = '<div class="no-device details-empty"><span class="material-symbols-outlined">usb_off</span><div><strong>No USB connected</strong><small>Insert a USB device to see its live details here.</small></div></div>';
    return;
  }

  const row = rows[0];
  activeDeviceCode = row.device_code || "";
  updateDeviceBadge();
  const details = [
  ["Device Name", row.usb_name, "memory"],
  ["Drive", row.drive_letter, "hard_drive"],
  ["Filesystem", row.filesystem, "folder_open"],
  ["Device Code", row.device_code, "fingerprint"],

  ["Username", row.username || "--", "person"],
  ["System Name", row.system_name || "--", "computer"],
  ["MAC Address", row.mac_address || "--", "lan"],

  ["Connected Since", formatTime(row.connected_since, true), "schedule"],
];
  body.innerHTML = details.map(([label, value, icon]) => `
    <div class="detail-item"><span class="detail-icon material-symbols-outlined">${icon}</span><div><div class="detail-label">${label}</div><div class="detail-value">${escapeHtml(value)}</div></div></div>
  `).join("");
}

async function loadUsbEvents() {
  const rows = await getJSON(`/api/usb_events?${filterParams({ limit: 5 })}`);
  const body = document.getElementById("usbEventsBody");
  document.getElementById("usbResultCount").textContent = `${rows.length} result${rows.length === 1 ? "" : "s"}`;
  body.innerHTML = rows.length ? rows.map(row => `
    <tr><td>${formatTime(row.event_time)}</td><td><span class="badge ${badgeClass(row.event_type)}">${escapeHtml(row.event_type)}</span></td><td>${escapeHtml(row.usb_name)}</td><td>${escapeHtml(row.drive_letter)}</td></tr>
  `).join("") : '<tr><td colspan="4" class="empty">No USB events match these filters</td></tr>';
}

async function loadFileEvents() {
  const rows = await getJSON(`/api/file_events?${filterParams({ limit: 5 })}`);
  const body = document.getElementById("fileEventsBody");
  document.getElementById("fileResultCount").textContent = `${rows.length} result${rows.length === 1 ? "" : "s"}`;
  body.innerHTML = rows.length ? rows.map(row => `
    <tr data-file="${escapeHtml(row.file_name)}"><td>${formatTime(row.event_time)}</td><td><span class="badge ${badgeClass(row.direction)}">${escapeHtml(row.direction)}</span></td><td>${escapeHtml(row.file_name)}</td><td>${row.file_size_mb != null ? `${escapeHtml(row.file_size_mb)} MB` : "--"}</td></tr>
  `).join("") : '<tr><td colspan="4" class="empty">No file events match these filters</td></tr>';

  body.querySelectorAll("tr[data-file]").forEach(row => row.addEventListener("click", () => openSha256Modal(row.dataset.file)));
}

async function openSha256Modal(fileName) {
  const modal = document.getElementById("sha256Modal");
  document.getElementById("modalFileName").textContent = fileName;
  document.getElementById("modalSha256").textContent = "Loading...";
  modal.classList.remove("hidden");
  try {
    const deviceQuery = activeDeviceCode ? `&device_code=${encodeURIComponent(activeDeviceCode)}` : "";
    const data = await getJSON(`/api/sha256?file_name=${encodeURIComponent(fileName)}${deviceQuery}`);
    document.getElementById("modalSha256").textContent = data.sha256 || "Not available";
  } catch {
    document.getElementById("modalSha256").textContent = "Error loading hash";
  }
}

function activityIcon(event) {
  const value = String(event).toUpperCase();
  if (value === "CONNECTED") return "usb";
  if (value === "REMOVED") return "usb_off";
  if (value === "CREATED") return "note_add";
  if (value === "DELETED") return "delete";
  if (value.startsWith("RENAMED")) return "drive_file_rename_outline";
  return "edit_document";
}

function notificationKey(item) {
  return `${item.event_time}|${item.event}|${item.detail}`;
}

function showToast(item) {
  const stack = document.getElementById("toastStack");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `<span class="toast-icon material-symbols-outlined">usb</span><div><strong>USB Connected</strong><span>${escapeHtml(item.detail)}</span><small>${escapeHtml(item.event_time)}</small></div><button type="button" aria-label="Dismiss">&times;</button>`;
  toast.querySelector("button").addEventListener("click", () => toast.remove());
  stack.prepend(toast);
  setTimeout(() => toast.remove(), 7000);
}

function renderNotifications() {
  const list = document.getElementById("notificationList");
  const badge = document.getElementById("notificationBadge");
  badge.textContent = notificationItems.length;
  badge.classList.toggle("hidden", !notificationItems.length);
  list.innerHTML = notificationItems.length ? notificationItems.map(item => `
    <div class="notification-item"><span class="material-symbols-outlined">usb</span><div><strong>USB Connected</strong><span>${escapeHtml(item.detail)}</span><small>${escapeHtml(item.event_time)}</small></div></div>
  `).join("") : '<div class="empty">No new notifications</div>';
}

function pushNotification(item) {
  notificationItems.unshift(item);
  notificationItems = notificationItems.slice(0, 8);
  renderNotifications();
  showToast(item);
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification("USB Connected", { body: item.detail, icon: "/favicon.ico" });
  }
}

async function loadActivity() {
  const rows = await getJSON(`/api/activity?${filterParams({ limit: 12 })}`);
  const feed = document.getElementById("activityFeed");
  feed.innerHTML = rows.length ? rows.map(item => `
    <div class="activity-item"><span class="activity-time">${escapeHtml(String(item.event_time).split(" ")[1] || item.event_time)}</span><span class="activity-marker ${badgeClass(item.event)}"><span class="material-symbols-outlined">${activityIcon(item.event)}</span></span><div class="activity-copy"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.detail)}${item.drive ? ` · ${escapeHtml(item.drive)}` : ""}</span></div><span class="badge ${badgeClass(item.event)}">${escapeHtml(item.event)}</span></div>
  `).join("") : '<div class="empty">No recent activity matches these filters</div>';

  const newestConnection = rows.find(item => String(item.event).toUpperCase() === "CONNECTED");
  if (!newestConnection) return;
  const key = notificationKey(newestConnection);
  if (!notificationBaselineReady) {
    lastUsbNotification = key;
    localStorage.setItem("usbSentinelLastNotification", key);
    notificationBaselineReady = true;
  } else if (key !== lastUsbNotification) {
    lastUsbNotification = key;
    localStorage.setItem("usbSentinelLastNotification", key);
    pushNotification(newestConnection);
  }
}

function themeColors() {
  const dark = document.documentElement.dataset.theme === "dark";
  return { text: dark ? "#adb6c8" : "#596174", grid: dark ? "#30394c" : "#e6e9f0" };
}

function baseChartOptions(showLegend = false) {
  const colors = themeColors();
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: "index" },
    plugins: { legend: { display: showLegend, labels: { color: colors.text, usePointStyle: true, boxWidth: 8 } } },
    scales: {
      x: { ticks: { color: colors.text, maxTicksLimit: 7 }, grid: { display: false } },
      y: { beginAtZero: true, ticks: { color: colors.text, precision: 0 }, grid: { color: colors.grid } },
    },
  };
}

function upsertChart(id, config) {
  if (typeof Chart === "undefined") {
    console.error("Chart.js is not loaded");
    return null;
  }

  const canvas = document.getElementById(id);

  if (!canvas) {
    console.error(`Canvas not found: ${id}`);
    return null;
  }

  // Destroy old chart instance before creating a fresh chart
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }

  // Also destroy any Chart.js instance attached to this canvas
  const existingChart = Chart.getChart(canvas);

  if (existingChart) {
    existingChart.destroy();
  }

  charts[id] = new Chart(canvas.getContext("2d"), config);

  requestAnimationFrame(() => {
    charts[id].resize();
    charts[id].update();
  });

  return charts[id];
}

async function loadStatistics() {
  const data = await getJSON(`/api/stats/overview?${filterParams()}`);
  document.getElementById("todayUsbCount").textContent = data.today.usb;
  document.getElementById("todayFileCount").textContent = data.today.file;
  const rangeText = elements.dateSearch.value || elements.period.options[elements.period.selectedIndex].text;
  document.getElementById("chartRangeLabel").textContent = rangeText;

  upsertChart("usbTodayChart", {
    type: "bar",
    data: { labels: data.labels, datasets: [{ data: data.usb_series, backgroundColor: "rgba(37, 99, 235, .72)", borderRadius: 4 }] },
    options: { ...baseChartOptions(false), plugins: { legend: { display: false } } },
  });
  upsertChart("fileTodayChart", {
    type: "line",
    data: { labels: data.labels, datasets: [{ data: data.file_series, borderColor: "#7c3aed", backgroundColor: "rgba(124, 58, 237, .12)", fill: true, tension: .35, pointRadius: 2 }] },
    options: { ...baseChartOptions(false), plugins: { legend: { display: false } } },
  });

  const distributionLabels = data.distribution.map(item => item.action);
  const distributionValues = data.distribution.map(item => item.total);
  const distributionColors = distributionLabels.map(label => DISTRIBUTION_COLORS[label] || "#94a3b8");
  const distributionTotal = distributionValues.reduce((sum, value) => sum + value, 0);

  document.getElementById("donutTotal").textContent = distributionTotal;

  const legend = document.getElementById("distributionLegend");
  legend.innerHTML = distributionTotal ? data.distribution.map(item => {
    const percent = ((item.total / distributionTotal) * 100).toFixed(1);
    const color = DISTRIBUTION_COLORS[item.action] || "#94a3b8";
    return `<li><span class="legend-dot" style="background:${color}"></span><span class="legend-label">${escapeHtml(item.action)}</span><span class="legend-value">${item.total} (${percent}%)</span></li>`;
  }).join("") : '<li class="empty">No file events in this period</li>';

  upsertChart("distributionChart", {
    type: "doughnut",
    data: { labels: distributionLabels, datasets: [{ data: distributionValues, backgroundColor: distributionColors, borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: "68%", plugins: { legend: { display: false } } },
  });
  upsertChart("timelineChart", {
    type: "line",
    data: { labels: data.labels, datasets: [
      { label: "USB Events", data: data.usb_series, borderColor: "#2563eb", backgroundColor: "rgba(37, 99, 235, .08)", tension: .35, pointRadius: 2, fill: true },
      { label: "File Events", data: data.file_series, borderColor: "#7c3aed", backgroundColor: "rgba(124, 58, 237, .06)", tension: .35, pointRadius: 2, fill: true },
    ] },
    options: { ...baseChartOptions(false), plugins: { legend: { display: false } } },
  });
}

// ==========================================================
// USB Access Control
// ==========================================================

async function postJSON(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Request failed (${response.status}): ${url}`);
  return response.json();
}

function showAccessToast(message, icon = "verified_user") {
  const stack = document.getElementById("toastStack");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `<span class="toast-icon material-symbols-outlined">${icon}</span><div><strong>Access Control</strong><span>${escapeHtml(message)}</span></div><button type="button" aria-label="Dismiss">&times;</button>`;
  toast.querySelector("button").addEventListener("click", () => toast.remove());
  stack.prepend(toast);
  setTimeout(() => toast.remove(), 5000);
}

async function loadAccessSummary() {
  const data = await getJSON("/api/access/summary");
  const badge = document.getElementById("accessPendingBadge");
  badge.textContent = data.pending;
  badge.classList.toggle("hidden", !data.pending);
  document.getElementById("accessPendingCount").textContent = `${data.pending} pending`;
}

async function loadAccessPending() {
  const rows = await getJSON("/api/access/pending");
  const body = document.getElementById("accessPendingBody");
  body.innerHTML = rows.length ? rows.map(row => `
    <tr>
      <td>${escapeHtml(row.device_name)}</td>
      <td>${escapeHtml(row.device_code)}</td>
      <td>${escapeHtml(row.serial_number)}</td>
      <td>${formatTime(row.request_time)}</td>
      <td><span class="badge badge-modified">PENDING</span></td>
      <td class="access-actions">
        <select class="duration-select" data-id="${row.id}">
          <option value="">Always Trust</option>
          <option value="10">10 min</option>
          <option value="30">30 min</option>
          <option value="60">1 hour</option>
        </select>
        <button class="button button-primary" data-action="approve" data-id="${row.id}">Approve</button>
        <button class="button button-danger" data-action="block" data-id="${row.id}">Block</button>
      </td>
    </tr>
  `).join("") : '<tr><td colspan="6" class="empty">No pending USB requests</td></tr>';
}

async function loadAccessTrusted() {
  const rows = await getJSON("/api/access/trusted");
  const body = document.getElementById("accessTrustedBody");
  body.innerHTML = rows.length ? rows.map(row => `
    <tr>
      <td>${escapeHtml(row.device_name)}</td>
      <td>${escapeHtml(row.device_code)}</td>
      <td>${escapeHtml(row.approved_by)}</td>
      <td>${formatTime(row.approved_at)}</td>
      <td class="access-actions"><button class="button button-danger" data-action="remove-trust" data-code="${escapeHtml(row.device_code)}">Remove Trust</button></td>
    </tr>
  `).join("") : '<tr><td colspan="5" class="empty">No trusted devices yet</td></tr>';
}

async function loadAccessBlocked() {
  const rows = await getJSON("/api/access/blocked");
  const body = document.getElementById("accessBlockedBody");
  body.innerHTML = rows.length ? rows.map(row => `
    <tr>
      <td>${escapeHtml(row.device_code)}</td>
      <td>${escapeHtml(row.blocked_by)}</td>
      <td>${escapeHtml(row.reason)}</td>
      <td>${formatTime(row.blocked_at)}</td>
      <td class="access-actions"><button class="button button-primary" data-action="unblock" data-code="${escapeHtml(row.device_code)}">Unblock</button></td>
    </tr>
  `).join("") : '<tr><td colspan="5" class="empty">No blocked devices</td></tr>';
}

function loadAccessControl() {
  return Promise.all([loadAccessSummary(), loadAccessPending(), loadAccessTrusted(), loadAccessBlocked()]);
}

document.getElementById("accessControlPanel").addEventListener("click", async event => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  button.disabled = true;

  try {
    const { action, id, code } = button.dataset;
    if (action === "approve") {
      const select = document.querySelector(`.duration-select[data-id="${id}"]`);
      const duration = select && select.value ? Number(select.value) : null;
      await postJSON(`/api/access/approve/${id}`, { duration_minutes: duration });
      showAccessToast(duration ? `Device approved for ${duration} minutes.` : "Device approved and marked trusted.");
    } else if (action === "block") {
      await postJSON(`/api/access/block/${id}`);
      showAccessToast("Device blocked.", "block");
    } else if (action === "remove-trust") {
      await postJSON("/api/access/trust/remove", { device_code: code });
      showAccessToast(`Trust removed for ${code}.`, "gpp_bad");
    } else if (action === "unblock") {
      await postJSON("/api/access/unblock", { device_code: code });
      showAccessToast(`${code} unblocked.`, "gpp_good");
    }
    // Refresh the access tables immediately, then the live USB status again
    // after the monitor's two-second approval poll has had time to react.
    await refreshAll();
    if (action === "approve") setTimeout(refreshAll, 2500);
  } catch (error) {
    console.error("Access control action failed:", error);
    showAccessToast("Action failed. Please try again.", "error");
  } finally {
    button.disabled = false;
  }
});

function refreshFilteredData() {
  return Promise.all([loadUsbEvents(), loadFileEvents(), loadActivity(), loadStatistics()]);
}

function scheduleFilterRefresh() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => refreshFilteredData().catch(console.error), 300);
}

[elements.usbSearch, elements.fileSearch, elements.eventSearch, elements.dateSearch].forEach(input => input.addEventListener("input", scheduleFilterRefresh));
[elements.period, elements.eventFilter].forEach(select => select.addEventListener("change", () => refreshFilteredData().catch(console.error)));

document.getElementById("resetFilters").addEventListener("click", () => {
  elements.usbSearch.value = "";
  elements.fileSearch.value = "";
  elements.eventSearch.value = "";
  elements.dateSearch.value = "";
  elements.period.value = "7d";
  elements.eventFilter.value = "all";
  refreshFilteredData().catch(console.error);
});

function exportReport(format) {
  window.location.href = `/api/export/${format}?${filterParams()}`;
}

document.querySelectorAll(".report-button").forEach(button => button.addEventListener("click", () => exportReport(button.dataset.format)));
document.getElementById("exportAllBtn").addEventListener("click", () => exportReport("csv"));

document.getElementById("modalClose").addEventListener("click", () => document.getElementById("sha256Modal").classList.add("hidden"));
document.getElementById("sha256Modal").addEventListener("click", event => { if (event.target.id === "sha256Modal") event.target.classList.add("hidden"); });

const darkModeToggle = document.getElementById("darkModeToggle");
const themeLabel = document.getElementById("themeLabel");

function applyTheme(isDark) {
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
  themeLabel.textContent = isDark ? "Dark Mode" : "Light Mode";
  localStorage.setItem("usbDashboardTheme", isDark ? "dark" : "light");
  if (Object.keys(charts).length) loadStatistics().catch(console.error);
}

darkModeToggle.addEventListener("change", event => applyTheme(event.target.checked));
const savedDarkMode = localStorage.getItem("usbDashboardTheme") === "dark";
darkModeToggle.checked = savedDarkMode;
applyTheme(savedDarkMode);

const notificationButton = document.getElementById("notificationButton");
const notificationPanel = document.getElementById("notificationPanel");
notificationButton.addEventListener("click", async () => {
  notificationPanel.classList.toggle("hidden");
  if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission();
});
document.getElementById("clearNotifications").addEventListener("click", () => { notificationItems = []; renderNotifications(); });
document.addEventListener("click", event => {
  if (!event.target.closest(".notification-wrap")) notificationPanel.classList.add("hidden");
});

const menuButton = document.getElementById("menuButton");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const closeSidebar = () => document.body.classList.remove("sidebar-open");
menuButton.addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
sidebarBackdrop.addEventListener("click", closeSidebar);
document.querySelectorAll(".sidebar .nav-item").forEach(link => link.addEventListener("click", closeSidebar));

async function refreshAll() {
  try {
    // Active device detection must complete first so activeDeviceCode is
    // current before any device-filtered request goes out. Running this
    // concurrently with loadSummary()/refreshFilteredData() (as before)
    // caused a race condition where those requests could fire with a
    // stale activeDeviceCode from the previous refresh cycle.
    await loadUsbDetails();
    await Promise.all([loadSummary(), refreshFilteredData(), loadAccessControl()]);
    document.querySelector(".topbar .live-refresh")?.classList.remove("refresh-error");
  } catch (error) {
    console.error("Dashboard refresh failed:", error);
    document.querySelector(".topbar .live-refresh")?.classList.add("refresh-error");
  } finally {
    refreshCountdown = REFRESH_INTERVAL_MS / 1000;
    updateRefreshCountdown();
  }
}

function updateRefreshCountdown() {
  const el = document.getElementById("autoRefreshCountdown");
  if (el) el.textContent = refreshCountdown;
}

renderNotifications();
refreshAll();
setInterval(refreshAll, REFRESH_INTERVAL_MS);
setInterval(() => {
  refreshCountdown = refreshCountdown > 0 ? refreshCountdown - 1 : REFRESH_INTERVAL_MS / 1000;
  updateRefreshCountdown();
}, 1000);
