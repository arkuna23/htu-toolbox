"use strict";

import { destroyIcons, iconMarkup, mountIcons, setButtonLoading, setIcon, syncIconMotion } from "./icons.js";

/* ------------------------------------------------------------------ util -- */
const $ = (id) => document.getElementById(id);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const token = document.querySelector('meta[name="htu-token"]').content;
const root = document.documentElement;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const systemTheme = window.matchMedia("(prefers-color-scheme: light)");

/* --------------------------------------------------------------- settings -- */
/* Workspace preferences are purely presentational and never leave the browser. */
const SETTINGS_KEY = "htu-toolbox.settings.v1";
const SETTINGS_DEFAULTS = {
  themeMode: "dark",
  paletteId: "iris",
  customSeed: "#6750a4",
  density: "standard",
  motion: "system",
  compactNav: false,
};
let settings = { ...SETTINGS_DEFAULTS };

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...SETTINGS_DEFAULTS };
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return { ...SETTINGS_DEFAULTS };
    const merged = { ...SETTINGS_DEFAULTS };
    for (const key of Object.keys(SETTINGS_DEFAULTS)) {
      if (key === "compactNav") {
        if (typeof parsed[key] === "boolean") merged[key] = parsed[key];
      } else if (typeof parsed[key] === "string" && parsed[key]) {
        merged[key] = parsed[key];
      }
    }
    return merged;
  } catch (error) {
    return { ...SETTINGS_DEFAULTS };
  }
}

function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (error) {
    /* Storage can be unavailable in private mode; preferences stay in memory. */
  }
}

function hexToRgb(hex) {
  const value = String(hex || "").trim().replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}$/.test(value)) return null;
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ];
}

/* Applies the resolved workspace preferences to the root element. Every value
   lands as a data-* attribute or a custom property, never an inline rule the
   strict style-src 'self' CSP would reject. */
function applySettings() {
  const prefersLight = systemTheme.matches;
  const dark =
    settings.themeMode === "dark" ||
    (settings.themeMode === "system" && !prefersLight);
  root.classList.toggle("dark", dark);
  root.classList.toggle("light", !dark);
  root.dataset.theme = dark ? "dark" : "light";
  root.dataset.palette = settings.paletteId;
  root.dataset.density = settings.density;
  root.dataset.motion =
    settings.motion === "system"
      ? reduceMotion.matches
        ? "reduced"
        : "full"
      : settings.motion;
  root.dataset.compactNav = String(settings.compactNav);
  root.style.colorScheme = dark ? "dark" : "light";
  syncIconMotion();

  if (settings.paletteId === "custom") {
    const rgb = hexToRgb(settings.customSeed);
    if (rgb) {
      root.style.setProperty("--seed-r", String(rgb[0]));
      root.style.setProperty("--seed-g", String(rgb[1]));
      root.style.setProperty("--seed-b", String(rgb[2]));
    }
  }

  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.setAttribute("content", dark ? "#141218" : "#fdfbff");

  syncSettingsControls();
}

function syncSettingsControls() {
  $$("[data-setting]").forEach((group) => {
    const key = group.dataset.setting;
    if (group.classList.contains("segmented") || group.classList.contains("swatches")) {
      $$("[role=radio]", group).forEach((option) => {
        const active =
          key === "compactNav"
            ? settings[key] === (option.dataset.value === "true")
            : settings[key] === option.dataset.value;
        option.setAttribute("aria-checked", String(active));
      });
    } else if (group.getAttribute("role") === "switch") {
      group.setAttribute("aria-checked", String(Boolean(settings[key])));
    }
  });
  const customDot = $("customSwatchDot");
  if (customDot) customDot.style.background = settings.customSeed;
  const preview = $("seedPreview");
  if (preview) preview.style.background = settings.customSeed;
  const input = $("seedInput");
  if (input && document.activeElement !== input) {
    input.value = settings.customSeed.toUpperCase();
  }
  const themeButton = $("themeButton");
  if (themeButton) {
    const dark = root.classList.contains("dark");
    setIcon(themeButton, dark ? "sun" : "moon");
    themeButton.setAttribute("aria-label", dark ? "切换到浅色主题" : "切换到深色主题");
  }
}

function updateSetting(key, value) {
  settings[key] = value;
  saveSettings();
  applySettings();
}

/* ------------------------------------------------------------------- api -- */
async function api(path, { timeout = 20000, ...options } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const headers = new Headers(options.headers || {});
  headers.set("X-HTU-Token", token);
  if (options.body) headers.set("Content-Type", "application/json");
  try {
    const response = await fetch(path, {
      ...options,
      headers,
      signal: controller.signal,
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `请求失败 (${response.status})`);
    }
    return payload;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("请求超时，请稍后刷新状态确认结果。");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function date(value) {
  if (!value) return "—";
  return new Date(Number(value) * 1000).toLocaleTimeString("zh-CN", { hour12: false });
}

/* ----------------------------------------------------------------- toast -- */
function toast(message, tone = "info") {
  const host = $("toastHost");
  const node = document.createElement("div");
  const tones = { error: "err", ok: "ok", warning: "warning", info: "info" };
  node.className = `toast animate-pop toast-${tones[tone] || "info"}`;
  const icon = tone === "error" ? "close" : tone === "ok" ? "check" : "help";
  const safe = document.createElement("span");
  safe.className = "toast-text";
  safe.textContent = message;
  node.innerHTML = iconMarkup(icon);
  node.appendChild(safe);
  host.appendChild(node);
  mountIcons(node);
  setTimeout(() => {
    destroyIcons(node);
    node.remove();
  }, 5200);
}

/* --------------------------------------------------------------- routing -- */
const PAGES = {
  overview: { title: "总览", view: "overviewView" },
  network: { title: "校园网", view: "networkView" },
  logs: { title: "运行日志", view: "logsView" },
  account: { title: "账号设置", view: "accountView" },
  guide: { title: "使用指南", view: "guideView" },
};
/* Sidebar highlights the section a sub-page belongs to. */
const NAV_FOR_PAGE = { overview: "overview", network: "network", account: "account", logs: "logs", guide: "guide" };

function currentPage() {
  const hash = location.hash.slice(1);
  const page = hash.split("/")[0];
  return PAGES[page] ? page : "overview";
}

function showPage(focus = false) {
  const page = currentPage();
  for (const [name, meta] of Object.entries(PAGES)) {
    $(meta.view).hidden = name !== page;
  }
  const active = NAV_FOR_PAGE[page];
  $$("[data-nav]").forEach((link) => {
    const on = link.dataset.nav === active;
    link.classList.toggle("active", on);
    if (on) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("breadcrumbPage").textContent = PAGES[page].title;
  document.title = `HTU Toolbox · ${PAGES[page].title}`;
  closeDrawer(false);
  if (focus) {
    $("mainContent").scrollTop = 0;
    $("mainContent").focus({ preventScroll: true });
  }
}

/* ---------------------------------------------------------------- drawer -- */
const wideLayout = window.matchMedia("(min-width: 1024px)");

function buildDrawer() {
  const drawer = $("sidebarDrawer");
  if (drawer.dataset.built === "true") return drawer;
  const clone = $("sidebar").cloneNode(true);
  clone.removeAttribute("id");
  clone.removeAttribute("aria-label");
  clone.setAttribute("role", "presentation");
  clone.querySelectorAll("[id]").forEach((node) => {
    node.dataset.sidebarSource = node.id;
    node.removeAttribute("id");
  });
  drawer.appendChild(clone);
  mountIcons(drawer);
  drawer.dataset.built = "true";
  bindNavClicks(drawer);
  return drawer;
}

function syncDrawerState() {
  $$("#sidebarDrawer [data-sidebar-source]").forEach((node) => {
    const source = $(node.dataset.sidebarSource);
    node.textContent = source.textContent;
    node.className = source.className;
  });
  $$("#sidebarDrawer [data-nav]").forEach((link) => {
    const active = link.dataset.nav === currentPage();
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function openDrawer() {
  buildDrawer();
  syncDrawerState();
  $("sidebarDrawer").hidden = false;
  $("sidebarScrim").hidden = false;
  document.querySelector(".content").inert = true;
  $("menuButton").setAttribute("aria-expanded", "true");
  setIcon($("menuButton"), "close");
  const first = $("sidebarDrawer").querySelector("[data-nav]");
  if (first) first.focus();
}

function closeDrawer(restoreFocus = true) {
  if ($("sidebarDrawer").hidden) return;
  $("sidebarDrawer").hidden = true;
  $("sidebarScrim").hidden = true;
  document.querySelector(".content").inert = false;
  $("menuButton").setAttribute("aria-expanded", "false");
  setIcon($("menuButton"), "menu");
  if (restoreFocus && !wideLayout.matches) $("menuButton").focus();
}

function bindNavClicks(scope = document) {
  $$("a[href^='#']", scope).forEach((link) => {
    link.addEventListener("click", () => closeDrawer(false));
  });
  $$("[data-open-settings]", scope).forEach((button) => {
    button.addEventListener("click", () => {
      closeDrawer(false);
      openSettings();
    });
  });
}

/* --------------------------------------------------------------- dialogs -- */
function openSettings() {
  if ($("helpDialog").open) $("helpDialog").close();
  if ($("searchDialog").open) $("searchDialog").close();
  if (!$("settingsDialog").open) $("settingsDialog").showModal();
  syncSettingsControls();
}

function wireDialogs() {
  $$("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => $(button.dataset.closeDialog).close());
  });
  /* Clicking the backdrop (outside the panel) dismisses, as the reference does. */
  $$("dialog.overlay").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });
  $$("[data-open-settings]").forEach((button) =>
    button.addEventListener("click", openSettings),
  );
  $("settingsButton").addEventListener("click", openSettings);
}

function wireSettingsDialog() {
  $$("[data-setting]").forEach((group) => {
    const key = group.dataset.setting;
    if (group.getAttribute("role") === "switch") {
      group.addEventListener("click", () =>
        updateSetting(key, group.getAttribute("aria-checked") !== "true"),
      );
      return;
    }
    $$("[role=radio]", group).forEach((option) => {
      option.addEventListener("click", () => {
        if (key === "paletteId") updateSetting("paletteId", option.dataset.value);
        else updateSetting(key, option.dataset.value);
      });
    });
  });

  $$("[data-settings-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$("[data-settings-tab]").forEach((other) => {
        const on = other === tab;
        other.setAttribute("aria-selected", String(on));
        $(other.getAttribute("aria-controls")).hidden = !on;
      });
    });
  });

  const seedInput = $("seedInput");
  seedInput.addEventListener("input", () => {
    const rgb = hexToRgb(seedInput.value);
    const dot = $("customSwatchDot");
    const preview = $("seedPreview");
    if (!rgb) {
      seedInput.classList.add("input-error");
      return;
    }
    seedInput.classList.remove("input-error");
    if (dot) dot.style.background = seedInput.value;
    if (preview) preview.style.background = seedInput.value;
  });
  seedInput.addEventListener("change", () => {
    const rgb = hexToRgb(seedInput.value);
    if (!rgb) {
      toast("请输入有效颜色，例如 #6750a4。", "error");
      seedInput.value = settings.customSeed.toUpperCase();
      syncSettingsControls();
      return;
    }
    settings.customSeed = `#${rgb.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
    updateSetting("paletteId", "custom");
  });

  $("settingsReset").addEventListener("click", () => {
    settings = { ...SETTINGS_DEFAULTS };
    saveSettings();
    applySettings();
    toast("已恢复默认工作区设置。", "ok");
  });

  $("themeButton").addEventListener("click", () => {
    updateSetting("themeMode", root.classList.contains("dark") ? "light" : "dark");
    toast(root.classList.contains("dark") ? "已切换到深色主题。" : "已切换到浅色主题。", "ok");
  });

  $("motionPreviewButton").addEventListener("click", () => {
    $$(".motion-chip", $("motionPreviewStage")).forEach((chip, index) => {
      chip.style.animation = "none";
      void chip.offsetWidth;
      chip.style.animation = `fade-up .38s cubic-bezier(.2,.8,.2,1) ${index * 60}ms both`;
    });
  });
  reduceMotion.addEventListener("change", () => {
    if (settings.motion === "system") applySettings();
  });
  systemTheme.addEventListener("change", () => {
    if (settings.themeMode === "system") applySettings();
  });
}

/* ---------------------------------------------------------------- search -- */
function filterSearch() {
  const query = $("searchInput").value.trim().toLocaleLowerCase();
  let matches = 0;
  $$("[data-search]").forEach((item) => {
    const on = !query || item.dataset.search.toLocaleLowerCase().includes(query);
    item.hidden = !on;
    if (on) matches++;
  });
  $$(".search-group-label").forEach((label) => (label.hidden = matches === 0));
  $("searchEmpty").hidden = matches > 0;
}

function openSearch() {
  if ($("helpDialog").open) $("helpDialog").close();
  if ($("settingsDialog").open) $("settingsDialog").close();
  $("searchInput").value = "";
  filterSearch();
  if (!$("searchDialog").open) $("searchDialog").showModal();
  $("searchInput").focus();
}

function wireSearch() {
  $("searchButton").addEventListener("click", openSearch);
  $("mobileSearchButton").addEventListener("click", openSearch);
  $("searchInput").addEventListener("input", filterSearch);
  $("searchDialog").addEventListener("keydown", (event) => {
    const visible = $$("#searchResults [data-search]").filter((item) => !item.hidden);
    const fromInput = event.target === $("searchInput");
    const result = event.target.closest("[data-search]");
    if (!fromInput && !result) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!visible.length) return;
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const index = visible.indexOf(result);
      const next = index === -1
        ? direction === 1 ? 0 : visible.length - 1
        : (index + direction + visible.length) % visible.length;
      visible[next].focus();
      visible[next].scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter" && fromInput) {
      event.preventDefault();
      visible[0]?.click();
    }
  });
}

/* ------------------------------------------------------------------ state -- */
let configured = false;
let busy = false;
let dirty = false;
const dirtyFields = new Set();
const defaults = {
  account: "",
  operator: "lt",
  portalUrl: "",
  intervalSeconds: 10,
  autoStart: false,
};
/* The same field appears on the network and account pages; keep them paired. */
const FIELD_PAIRS = [
  ["account", ["accountInput", "accountInput2"]],
  ["password", ["passwordInput", "passwordInput2"]],
  ["portalUrl", ["portalInput", "portalInput2"]],
  ["intervalSeconds", ["intervalInput", "intervalInput2"]],
];
const OPERATOR_LABELS = { yd: "中国移动", lt: "中国联通", dx: "中国电信", hsd: "校园本地" };
let logLines = [];

function setSwitch(button, value) {
  if (button) button.setAttribute("aria-checked", String(Boolean(value)));
}

function setOperator(value) {
  $$("[data-operator-group]").forEach((group) => {
    $$("[role=radio]", group).forEach((option) =>
      option.setAttribute("aria-checked", String(option.dataset.value === value)),
    );
  });
  const hiddenA = $("operatorSelect");
  const hiddenB = $("operatorSelect2");
  if (hiddenA) hiddenA.value = value;
  if (hiddenB) hiddenB.value = value;
}

function currentOperator(scope = document) {
  const checked = scope.querySelector("[data-operator-group] [aria-checked='true']");
  return checked ? checked.dataset.value : "lt";
}

function setBusy(value) {
  busy = value;
  $$("form").forEach((form) => {
    form.setAttribute("aria-busy", String(value));
    $$("input,textarea,button", form).forEach((el) => {
      if (el.type === "hidden") return;
      el.disabled = value;
    });
  });
  $$("[data-action]").forEach((button) => {
    button.disabled = value || (!configured && !["check", "logout"].includes(button.dataset.action));
  });
  const save = $("saveButton");
  if (save) save.textContent = value ? "正在处理…" : "保存并连接";
  const save2 = $("saveButton2");
  if (save2) save2.textContent = value ? "正在处理…" : "保存配置";
}

function setServiceState(state, label) {
  $("serviceState").textContent = label;
  $("topServiceText").textContent = label;
  $("topService").className = `chip chip-${state}${state === "warning" ? " chip-pulse" : ""}`;
  const dot = $("serviceDot");
  dot.className = `chip-dot chip-${state}`;
  syncDrawerState();
}

function setNetworkMeter(network) {
  const meter = $("overviewMeter");
  const level = network.online ? 5 : network.state === "captive" ? 3 : network.state === "error" ? 1 : 0;
  meter.dataset.level = String(level);
  meter.dataset.tone = network.online ? "success" : network.state === "error" ? "danger" : "warning";
}

function render(data) {
  const { task, network, config, platform } = data;
  configured = config.passwordConfigured;
  const running = task.state === "Running";
  const labels = { Running: "运行中", Ready: "已暂停", NotInstalled: "未配置" };
  const taskLabel = task.stopping ? "正在停止" : labels[task.state] || task.state;

  const networkLabel = network.online
    ? "在线"
    : network.state === "captive"
      ? "待认证"
      : network.state === "error"
        ? "检测失败"
        : "尚未检测";
  const networkHint = network.online
    ? "已确认互联网连接"
    : network.message || "点击立即检测查看网络状态";
  const networkTone = network.online
    ? "success"
    : network.state === "error"
      ? "danger"
      : network.state === "captive"
        ? "warning"
        : "";

  $("sidebarNetwork").textContent = networkLabel;
  $("sidebarTask").textContent = taskLabel;
  $("sidebarInterval").textContent = `${config.intervalSeconds}s`;
  $("sidebarUpdate").textContent = date(Date.now() / 1000);

  $("overviewNetwork").textContent = networkLabel;
  $("overviewTask").textContent = taskLabel;
  $("overviewNextRun").textContent = date(task.nextRunTime);
  $("overviewNetworkHint").textContent = networkHint;
  $("overviewLastRun").textContent = network.checkedAt ? `上次检测 ${date(network.checkedAt)}` : "暂无检测记录";
  const badge = $("overviewNetworkBadge");
  badge.textContent = networkLabel;
  badge.className = `chip chip-${networkTone}${networkTone ? " chip-pulse" : ""}`;
  setNetworkMeter(network);

  const connectionLabel = running
    ? "自动登录已开启"
    : configured
      ? "自动登录已暂停"
      : "等待账号配置";
  $("connectionText").textContent = connectionLabel;
  $("connectionPill").className = `chip chip-${running ? "success" : ""}${running ? " chip-pulse" : ""}`;
  $("lastUpdate").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
  $("overviewUpdated").textContent = $("lastUpdate").textContent;
  if (network.message) $("lastResult").textContent = network.message;

  $("navNetworkBadge").textContent = running ? "运行中" : configured ? "已配置" : "未配置";
  $("navNetworkBadge").className = `chip chip-accent nav-badge${running ? " chip-pulse" : ""}`;

  $("platformBadge").textContent = platform.name;
  $("infoPlatform").textContent = platform.name;
  $("infoStorage").textContent = platform.passwordStorage || "—";
  $("infoAccount").textContent = config.account || "未配置";
  $("infoPortal").textContent = config.portalUrl ? "已配置" : "—";
  $("platformHint").textContent = platform.autostartHint;

  const configuredNote = config.passwordConfigured ? "已保存 · 留空保留" : "首次配置必填";
  $("passwordConfigured").textContent = configuredNote;
  $("passwordConfigured2").textContent = configuredNote;
  $("passwordInput").required = !config.passwordConfigured;
  $("passwordInput2").required = !config.passwordConfigured;
  for (const id of ["passwordInput", "passwordInput2"]) {
    $(id).placeholder = config.passwordConfigured ? "留空保留已存密码" : "输入上网密码";
  }
  $("credChip").className = `chip chip-${config.passwordConfigured ? "success" : "warning"}`;
  $("credChip").innerHTML = `<span class="chip-dot"></span>${config.passwordConfigured ? "已加密保存" : "尚未保存密码"}`;
  $("infoAccount2").textContent = config.account || "未配置";
  $("infoOperator2").textContent = OPERATOR_LABELS[config.operator] || "—";
  $("infoPortal2").textContent = config.portalUrl ? "已配置" : "—";

  if (!dirty && !busy) {
    $("accountInput").value = config.account ?? defaults.account;
    $("accountInput2").value = config.account ?? defaults.account;
    $("portalInput").value = config.portalUrl ?? defaults.portalUrl;
    $("portalInput2").value = config.portalUrl ?? defaults.portalUrl;
    $("intervalInput").value = config.intervalSeconds ?? defaults.intervalSeconds;
    $("intervalInput2").value = config.intervalSeconds ?? defaults.intervalSeconds;
    setSwitch($("autoStartSwitch"), config.autoStart);
    setSwitch($("autoStartSwitch2"), config.autoStart);
    setOperator(config.operator || "lt");
    dirtyFields.clear();
  }
  setBusy(busy);
  syncDrawerState();
}

async function loadStatus() {
  try {
    const { data } = await api("/api/status", { timeout: 30000 });
    render(data);
    setServiceState("success", "服务已连接");
  } catch (error) {
    setServiceState("danger", "服务未连接");
    $("connectionText").textContent = "服务连接失败";
    $("connectionPill").className = "chip chip-danger";
    $("lastUpdate").textContent = "服务未连接 · 显示最后记录";
    $("overviewUpdated").textContent = "服务未连接 · 显示最后记录";
  }
}

/* ------------------------------------------------------------------ logs -- */
function currentTail() {
  return $("logTail").value;
}

async function loadLogs() {
  try {
    const { data } = await api(`/api/logs?tail=${currentTail()}`, { timeout: 12000 });
    logLines = data.lines;
    const text = data.lines.length ? data.lines.join("\n") : "暂无记录";
    for (const id of ["logOutput", "logOutput2"]) {
      const node = $(id);
      const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 40;
      node.textContent = text;
      if (atBottom) node.scrollTop = node.scrollHeight;
    }
    const meta = `${data.lines.length} 行${data.lastWriteTime ? ` · ${date(data.lastWriteTime)}` : ""}`;
    $("logMeta").textContent = meta;
    $("logMeta2").textContent = meta;
  } catch (error) {
    $("logMeta").textContent = error.message;
    $("logMeta2").textContent = error.message;
  }
}

function downloadLog() {
  if (!logLines.length) {
    toast("暂无可导出的日志内容。", "error");
    return;
  }
  const url = URL.createObjectURL(
    new Blob([logLines.join("\n")], { type: "text/plain;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "htu-connect.log";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* -------------------------------------------------------------- controls -- */
function collectConfig(form) {
  const suffix = form.id === "configForm2" ? "2" : "";
  return {
    account: $(`accountInput${suffix}`).value.trim(),
    operator: currentOperator(form),
    password: $(`passwordInput${suffix}`).value,
    portalUrl: $(`portalInput${suffix}`).value.trim(),
    intervalSeconds: Number($(`intervalInput${suffix}`).value),
    autoStart: $(`autoStartSwitch${suffix}`).getAttribute("aria-checked") === "true",
  };
}

async function submitConfig(event, { start = false } = {}) {
  if (event) event.preventDefault();
  if (busy) return;
  const config = collectConfig(event?.currentTarget || $("configForm"));
  setBusy(true);
  try {
    const result = await api("/api/config", {
      method: "POST",
      body: JSON.stringify(config),
      timeout: 20000,
    });
    for (const id of ["passwordInput", "passwordInput2"]) $(id).value = "";
    dirty = false;
    dirtyFields.clear();
    if (start) {
      const started = await api("/api/action", {
        method: "POST",
        body: JSON.stringify({ action: "start" }),
        timeout: 30000,
      });
      toast(`${result.message} ${started.message}`, "ok");
    } else {
      toast(result.message, "ok");
    }
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setBusy(false);
    await Promise.all([loadStatus(), loadLogs()]);
  }
}

async function runAction(action) {
  if (busy) return;
  setBusy(true);
  const buttons = $$(`[data-action="${action}"]`);
  buttons.forEach((button) => setButtonLoading(button, true));
  try {
    const result = await api("/api/action", {
      method: "POST",
      body: JSON.stringify({ action }),
      timeout: 30000,
    });
    $("lastResult").textContent = result.message;
    $("overviewLastResult").textContent = result.message;
    const network = result.data;
    const tone = network?.error || network?.state === "error"
      ? "error"
      : network && network.online === false && ["check", "login"].includes(action)
        ? "warning"
        : "ok";
    toast(result.message, tone);
  } catch (error) {
    $("lastResult").textContent = error.message;
    $("overviewLastResult").textContent = error.message;
    toast(error.message, "error");
  } finally {
    buttons.forEach((button) => setButtonLoading(button, false));
    setBusy(false);
    await Promise.all([loadStatus(), loadLogs()]);
  }
}

async function detectPortal(button) {
  const oldValue = $("portalInput").value;
  button.disabled = true;
  setButtonLoading(button, true);
  try {
    const { data } = await api("/api/detect-portal");
    if ($("portalInput").value === oldValue) {
      $("portalInput").value = data.portalUrl;
      $("portalInput2").value = data.portalUrl;
      dirty = true;
      dirtyFields.add("portalInput");
      toast("已获取门户地址，请保存配置。", "ok");
    }
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonLoading(button, false);
    button.disabled = busy;
  }
}

function wireForms() {
  $$("form").forEach((form) => {
    form.addEventListener("input", (event) => {
      dirty = true;
      if (event.target.id) dirtyFields.add(event.target.id);
      const pair = FIELD_PAIRS.find(([, ids]) => ids.includes(event.target.id));
      if (pair) {
        for (const id of pair[1]) {
          if (id !== event.target.id) $(id).value = event.target.value;
        }
      }
    });
  });
  $("configForm").addEventListener("submit", (event) => submitConfig(event, { start: true }));
  $("configForm2").addEventListener("submit", (event) => submitConfig(event, { start: false }));

  $$("[data-action]").forEach((button) =>
    button.addEventListener("click", () => runAction(button.dataset.action)),
  );
  $("detectPortalButton").addEventListener("click", (event) => detectPortal(event.currentTarget));
  $("detectPortalButton2").addEventListener("click", (event) => detectPortal(event.currentTarget));

  $$("[data-operator-group]").forEach((group) =>
    $$("[role=radio]", group).forEach((option) =>
      option.addEventListener("click", () => {
        setOperator(option.dataset.value);
        dirty = true;
      }),
    ),
  );

  for (const [id, targets] of [["autoStartSwitch", "autoStartSwitch2"], ["autoStartSwitch2", "autoStartSwitch"]]) {
    $(id).addEventListener("click", (event) => {
      const next = event.currentTarget.getAttribute("aria-checked") !== "true";
      setSwitch($(id), next);
      setSwitch($(targets), next);
      dirty = true;
      dirtyFields.add(id);
    });
  }

  $$("[data-log-tail]").forEach((group) =>
    $$("[role=radio]", group).forEach((option) =>
      option.addEventListener("click", () => {
        $$("[data-log-tail] [role=radio]").forEach((other) =>
          other.setAttribute("aria-checked", String(other.dataset.value === option.dataset.value)),
        );
        $("logTail").value = option.dataset.value;
        loadLogs();
      }),
    ),
  );

  $("autoRefreshSwitch").addEventListener("click", (event) => {
    setSwitch(event.currentTarget, event.currentTarget.getAttribute("aria-checked") !== "true");
  });

  $("toggleLogButton").addEventListener("click", (event) => {
    const output = $("logOutput");
    const collapsed = output.hidden;
    output.hidden = !collapsed;
    event.currentTarget.textContent = output.hidden ? "展开" : "收起";
    event.currentTarget.setAttribute("aria-expanded", String(!output.hidden));
  });

  $("downloadLogButton").addEventListener("click", downloadLog);
  $("downloadLogButton2").addEventListener("click", downloadLog);
  $("refreshLogsButton").addEventListener("click", () => loadLogs());
}

/* --------------------------------------------------------------- startup -- */
function wireGlobal() {
  $("menuButton").addEventListener("click", () =>
    $("sidebarDrawer").hidden ? openDrawer() : closeDrawer(),
  );
  $("sidebarScrim").addEventListener("click", () => closeDrawer());

  window.addEventListener("hashchange", () => showPage(true));
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    if (!/^#(overview|network|logs|account|guide)(\/.*)?$/.test(link.getAttribute("href"))) return;
    if ($("searchDialog").open) $("searchDialog").close();
    if (location.hash === link.getAttribute("href")) showPage(true);
  });

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openSearch();
    }
    if (event.key === "Escape" && !$("sidebarDrawer").hidden) closeDrawer();
    if (event.key === "Tab" && !$("sidebarDrawer").hidden) {
      const controls = $$("#sidebarDrawer a, #sidebarDrawer button").filter((node) => node.getClientRects().length);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && event.target === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && event.target === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  });

  wideLayout.addEventListener("change", (event) => {
    if (event.matches) closeDrawer(false);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadStatus();
  });
}

async function poll() {
  if (document.visibilityState === "visible" && $("autoRefreshSwitch").getAttribute("aria-checked") === "true") {
    await Promise.all([loadStatus(), loadLogs()]);
  }
  setTimeout(poll, 5000);
}

settings = loadSettings();
applySettings();
mountIcons();
wireDialogs();
wireSettingsDialog();
wireSearch();
wireForms();
wireGlobal();
bindNavClicks();
setBusy(false);
showPage();
Promise.all([loadStatus(), loadLogs()]).finally(() => setTimeout(poll, 5000));
