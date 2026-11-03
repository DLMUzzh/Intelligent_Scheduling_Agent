"use strict";

const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
  calendar:
    '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M14 15h2M8 18h2"/>',
  truck:
    '<path d="M3 6h11v12H3zM14 10h4l3 4v4h-7M17 10v4h4"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
  chart: '<path d="M4 3v18h17M9 16v-5M14 16V6M19 16v-8"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  spark:
    '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 3v4M18 5h4"/>',
  shield: '<path d="M12 3 3 6v5c0 6 9 10 9 10s9-4 9-10V6zM8 12l3 3 5-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M4 12h16M14 6l6 6-6 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
  warning: '<path d="m12 3 10 18H2zM12 9v4M12 17h.01"/>',
  refresh: '<path d="M20 7a9 9 0 1 0 1 8M20 3v5h-5"/>',
  key: '<circle cx="8" cy="15" r="5"/><path d="m12 11 9-9M18 5l3 3M15 8l3 3"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.layers}</svg>`;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const n = (value) =>
  Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 3 });
const shiftNames = { MORNING: "早班", AFTERNOON: "中班", NIGHT: "晚班" };
const efficiencyNames = { HIGH: "高效率", MEDIUM: "中效率", LOW: "低效率" };
const roadNames = { CITY: "城市道路", HIGHWAY: "高速道路", RURAL: "乡村道路" };
const pageNames = {
  overview: "工作台",
  plans: "采集计划",
  scheduling: "排班工作台",
  fleet: "车队资源",
  statistics: "排班统计",
  notifications: "通知中心",
  agent: "Agent 助手",
  audit: "操作日志",
};
const statusNames = {
  CREATED: "待排班",
  CONFIRMED: "已确认",
  PARTIALLY_CONFIRMED: "部分确认",
  PENDING: "待确认",
  DISCARDED: "已放弃",
  EXPIRED: "已过期",
  FULL: "完整分配",
  PARTIAL: "部分分配",
  NO_ASSIGNMENT: "无可用分配",
  SENT: "发送成功",
  FAILED: "发送失败",
  ACTIVE: "可用",
  DISABLED: "已停用",
};
const state = {
  plans: [],
  drivers: [],
  vehicles: [],
  shifts: [],
  planId: null,
  preview: null,
  page: "overview",
  fleetTab: "drivers",
  scheduleTab: "preview",
  selected: new Set(),
  notificationStatus: "",
  scheduleStart: "",
  scheduleEnd: "",
  formalStart: "",
  formalEnd: "",
  statsStart: "",
  statsEnd: "",
};
let navigationVersion = 0;
let modalSubmit = null;

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...options.headers };
  const key = sessionStorage.getItem("fleet-api-key");
  if (key) headers["X-API-Key"] = key;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      const error = payload.error || {
        message: `请求失败 (${response.status})`,
      };
      const details = Array.isArray(error.details)
        ? error.details.map((e) => `${e.field}: ${e.message}`).join("；")
        : "";
      throw new Error(
        `${error.message}${details ? `：${details}` : ""} [${error.code || response.status}]`,
      );
    }
    $("#connection-state").textContent = "系统在线";
    return payload.data;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error("请求超时，请刷新查看当前操作状态后重试");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
const post = (path, data, method = "POST") =>
  api(path, { method, body: JSON.stringify(data) });
async function allRows(path) {
  let rows = [],
    offset = 0;
  while (true) {
    const batch = await api(
      `${path}${path.includes("?") ? "&" : "?"}limit=500&offset=${offset}`,
    );
    rows = rows.concat(batch);
    if (batch.length < 500) return rows;
    offset += 500;
  }
}
function toast(message, error = false) {
  const element = document.createElement("div");
  element.className = `toast${error ? " error" : ""}`;
  element.textContent = message;
  $("#toasts").append(element);
  setTimeout(() => element.remove(), error ? 9500 : 4500);
}
function badge(value, customLabel) {
  const color = ["FULL", "CONFIRMED", "SENT", "HIGH", "ACTIVE"].includes(value)
    ? "green"
    : ["PARTIAL", "PARTIALLY_CONFIRMED", "MEDIUM", "PENDING"].includes(value)
      ? "amber"
      : ["FAILED", "LOW", "DISABLED", "NO_ASSIGNMENT"].includes(value)
        ? "red"
        : "";
  return `<span class="badge ${color}"><i class="dot"></i>${esc(customLabel || statusNames[value] || efficiencyNames[value] || value)}</span>`;
}
const button = (label, action, style = "", attrs = "") =>
  `<button class="button ${style}" data-action="${action}" ${attrs}>${label}</button>`;
function heading(
  title,
  description,
  actions = "",
  eyebrow = "Fleet operations",
) {
  return `<div class="page-heading"><div><div class="eyebrow">${esc(eyebrow)}</div><h1>${esc(title)}</h1><p class="subtitle">${esc(description)}</p></div><div class="heading-actions">${actions}</div></div>`;
}
function empty(title, description, action = "") {
  return `<div class="empty">${icon("layers")}<strong>${esc(title)}</strong><p>${esc(description)}</p>${action}</div>`;
}
function metric(label, value, unit, note, symbol) {
  return `<div class="metric-card"><div class="metric-label">${esc(label)}${icon(symbol)}</div><div class="metric-value number">${n(value)}<small>${esc(unit)}</small></div><div class="metric-note">${note}</div></div>`;
}
function dateLabel(day) {
  return new Date(`${day}T12:00:00`).toLocaleDateString("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  });
}
function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function planOptions(selected = state.planId, allowAll = false) {
  return `${allowAll ? '<option value="">全部计划</option>' : ""}${state.plans.map((p) => `<option value="${p.plan_id}" ${p.plan_id === Number(selected) ? "selected" : ""}>${esc(p.title)}</option>`).join("")}`;
}
function currentPlan() {
  return state.plans.find((p) => p.plan_id === Number(state.planId));
}
function setPlan(id) {
  state.planId = Number(id);
  const plan = currentPlan();
  state.scheduleStart = plan?.start_date || today();
  state.scheduleEnd = plan?.end_date || today();
  state.preview = null;
  state.selected.clear();
}
async function refreshBase() {
  const [plans, drivers, vehicles, shifts] = await Promise.all([
    allRows("/plans"),
    api("/drivers"),
    api("/vehicles"),
    api("/shifts"),
  ]);
  Object.assign(state, { plans, drivers, vehicles, shifts });
  if (!state.planId && plans.length) setPlan(plans[0].plan_id);
}
function mount(html) {
  $("#main").innerHTML = `<div class="page-enter">${html}</div>`;
}
async function render() {
  const version = ++navigationVersion;
  state.page = pageNames[location.hash.slice(1)]
    ? location.hash.slice(1)
    : "overview";
  const page = state.page;
  $("#breadcrumb").textContent = pageNames[page];
  $$("[data-page]").forEach((el) =>
    el.classList.toggle("active", el.dataset.page === page),
  );
  $("#main").setAttribute("aria-busy", "true");
  $("#main").innerHTML =
    '<div class="loading"><div class="spinner"></div>正在读取工作空间…</div>';
  try {
    await refreshBase();
    let html;
    if (page === "overview") html = await overviewPage();
    if (page === "plans") html = plansPage();
    if (page === "scheduling") html = await schedulingPage();
    if (page === "fleet") html = fleetPage();
    if (page === "statistics") html = await statisticsPage();
    if (page === "notifications") html = await notificationsPage();
    if (page === "agent") html = agentPage();
    if (page === "audit") html = await auditPage();
    if (version === navigationVersion) mount(html);
  } catch (error) {
    if (version === navigationVersion) {
      $("#connection-state").textContent = "连接异常";
      mount(
        heading("暂时无法读取数据", "检查服务状态或 API 访问密钥后重试。") +
          `<div class="error-banner">${esc(error.message)}</div>${button("重新加载", "refresh")}${button("配置访问密钥", "key")}`,
      );
    }
  } finally {
    if (version === navigationVersion)
      $("#main").setAttribute("aria-busy", "false");
  }
}

function planTable(plans, compact = false) {
  if (!plans.length)
    return empty(
      "创建第一个采集计划",
      "填写日期与任务需求，即可开始安排车辆和司机。",
      button(`${icon("plus")} 新建采集计划`, "new-plan", "primary"),
    );
  return `<div class="table-scroll"><table><thead><tr><th>采集计划</th><th>日期范围</th><th>每日默认需求</th><th>状态</th><th class="text-right">操作</th></tr></thead><tbody>${plans.map((p) => `<tr><td><div class="plan-title"><span class="plan-icon">${icon("layers")}</span><div><strong>${esc(p.title)}</strong><small>PLAN-${String(p.plan_id).padStart(3, "0")} · ${p.total_days} 天</small></div></div></td><td class="number">${esc(p.start_date)}<small>至 ${esc(p.end_date)}</small></td><td><strong class="number">${n(p.daily_tag_target)}</strong> <span class="muted">Tag</span><small>${n(p.daily_road_km)} km · 每日配置可不同</small></td><td>${badge(p.status)}<small>${p.confirmed_days} / ${p.total_days} 天已确认</small></td><td class="text-right">${button(compact ? "安排排班 ↗" : "进入排班 ↗", "plan-schedule", "small", `data-id="${p.plan_id}"`)} ${!compact ? button("每日需求", "plan-detail", "small", `data-id="${p.plan_id}"`) : ""}</td></tr>`).join("")}</tbody></table></div>`;
}
async function overviewPage() {
  const stats = await api("/schedules/statistics");
  return (
    heading(
      "让每一班，都有序。",
      "从采集目标到司机出发，一站完成车队排班。",
      `<span class="date-chip">${icon("calendar")}${new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" })}</span>`,
      "Your fleet, in sync",
    ) +
    `<div class="metric-grid">${metric("采集计划", state.plans.length, "个", "<b>多日期计划</b> · 每日独立需求", "layers")}${metric("可用车辆", stats.active_vehicles, "辆", "<b>独立班次容量</b> · 灵活配置", "truck")}${metric("在岗司机", stats.active_drivers, "位", `其中 <b>${state.drivers.filter((d) => d.status === "ACTIVE" && d.efficiency_level === "HIGH").length} 位高效率</b>司机`, "user")}${metric("已确认排班", stats.assignment_count, "班", `覆盖 <b>${stats.confirmed_days} 个计划日</b> · 确认后通知`, "calendar")}</div>` +
    `<section class="hero"><div><div class="eyebrow">A better way to schedule</div><h2>目标清晰，安排自有章法。</h2><p>设置每日采集需求，系统结合效率、容量与班次约束生成预览。<br>保留每一次人工判断，让确认后的安排可靠生效。</p></div><div class="hero-art" aria-hidden="true"><div class="route-line"></div><div class="route-car">${icon("truck")}</div><div class="hero-chip">● 路线有序 · 任务就绪</div></div></section>` +
    `<div class="grid-two"><section class="panel"><div class="panel-header"><div><h2>采集计划</h2><p>从一份计划，开始下一程</p></div>${button(`${icon("plus")} 新建计划`, "new-plan", "small")}</div>${planTable(state.plans.slice(0, 4), true)}<div class="panel-foot"><span>默认需求可按日期单独覆盖</span><a href="#plans">查看全部计划 →</a></div></section><section class="panel"><div class="panel-header"><div><h2>排班如何生效</h2><p>确定的规则，透明的过程</p></div>${icon("shield")}</div><div class="panel-body rule-list">${[
      ["01", "录入每日目标", "Tag 数量与道路里程分别分配、独立统计。"],
      ["02", "生成并调整预览", "效率优先、容量均衡；预览阶段不占用资源。"],
      ["03", "人工确认，立即通知", "复查最新约束，批量提交后模拟通知司机。"],
    ]
      .map(
        ([i, t, d]) =>
          `<div class="rule"><span class="rule-num">${i}</span><div><h3>${t}</h3><p>${d}</p></div></div>`,
      )
      .join(
        "",
      )}</div><div class="panel-foot"><span>未分配任务仅提醒，不自动结转</span></div></section></div>`
  );
}
function plansPage() {
  return (
    heading(
      "采集计划",
      "按日期管理 Tag 与道路需求，把采集目标变成可执行计划。",
      button(`${icon("plus")} 新建采集计划`, "new-plan", "primary"),
      "Collection plans",
    ) +
    `<section class="panel"><div class="panel-header"><h2>全部计划 <span class="badge">${state.plans.length}</span></h2><span class="inline-note">创建计划后，可在排班工作台生成预览</span></div>${planTable(state.plans)}</section>`
  );
}
function coverage(label, assigned, target, rate, road = false) {
  return `<div class="coverage-item"><div><span>${label}</span><b class="number">${n(assigned)} / ${n(target)} ${road ? "km" : "个"} · ${rate === null ? "—" : `${n(rate)}%`}</b></div><div class="progress ${road ? "road" : ""}"><span style="width:${Math.max(0, Math.min(100, rate || 0))}%"></span></div></div>`;
}
function allocationChips(a) {
  return `<div class="allocation">${a.tag_allocations.map((t) => `<span>${esc(t.tag_type)} <b class="number">${n(t.count)}</b></span>`).join("")}${a.road_allocations.map((r) => `<span>${esc(roadNames[r.road_type] || r.road_type)} <b class="number">${n(r.km)} km</b></span>`).join("")}</div>`;
}
function dayCard(day, editable) {
  const canEdit = editable && !day.confirmed;
  const valid = day.constraint_validation.valid;
  const selectable = canEdit && valid && day.assignments.length;
  const m = day.metrics;
  const unallocated = [
    ...day.unallocated.tags.map((t) => `${t.tag_type} ${n(t.count)} 个`),
    ...day.unallocated.roads.map(
      (r) => `${roadNames[r.road_type] || r.road_type} ${n(r.km)} km`,
    ),
  ];
  return `<section class="day-card"><div class="day-header"><div class="day-heading">${editable ? `<input type="checkbox" class="day-select" data-date="${day.date}" aria-label="选择 ${day.date}" ${state.selected.has(day.date) ? "checked" : ""} ${selectable ? "" : "disabled"}>` : ""}<strong>${day.date}</strong><small>${dateLabel(day.date)}</small>${day.confirmed ? badge("CONFIRMED") : badge(day.coverage_status)}</div><div class="actions">${canEdit ? button(`${icon("plus")} 添加明细`, "add-assignment", "small", `data-date="${day.date}"`) : `<span class="inline-note">正式排班 · ${day.assignments.length} 班</span>`}</div></div><div class="coverage-strip">${coverage("Tag 采集", m.tag_assigned, m.tag_target, m.tag_coverage_rate)}${coverage("道路采集", m.road_assigned_km, m.road_target_km, m.road_coverage_rate, true)}</div>${!valid ? `<div class="error-banner">${day.constraint_validation.errors.map((e) => esc(e.message)).join("；")}</div>` : ""}${day.assignments.length ? `<div class="table-scroll"><table><thead><tr><th>车辆 / 车牌</th><th>司机 / 效率</th><th>班次</th><th>任务模式</th><th>分配任务</th><th>班次利用率</th>${canEdit ? '<th class="text-right">操作</th>' : ""}</tr></thead><tbody>${day.assignments.map((a) => `<tr><td><strong>${esc(a.vehicle_name)}</strong><small>${esc(a.plate_number)}</small></td><td><strong>${esc(a.driver_name)}</strong><small>${badge(a.driver_efficiency)}</small></td><td>${shiftNames[a.shift]}</td><td>${badge(a.task_mode, a.task_mode === "TAG" ? "Tag 采集" : "道路采集")}</td><td>${allocationChips(a)}</td><td><div class="utilization"><div class="progress"><span style="width:${Math.min(100, a.capacity_utilization)}%"></span></div><small class="number">${n(a.capacity_utilization)}%</small></div></td>${canEdit ? `<td class="text-right"><button class="tiny-link" data-action="edit-assignment" data-id="${esc(a.assignment_id)}" data-date="${day.date}">编辑</button><button class="tiny-link danger" data-action="delete-assignment" data-id="${esc(a.assignment_id)}">删除</button></td>` : ""}</tr>`).join("")}</tbody></table></div>` : empty("当天暂无可执行排班", "检查可用资源，或手动添加合法排班明细。")}${unallocated.length ? `<div class="warning">${icon("warning")}<div>尚未分配：${esc(unallocated.join("；"))}<br><span class="inline-note">${esc(day.reasons.join(" "))}</span></div></div>` : ""}</section>`;
}
async function schedulingPage() {
  const tab = state.scheduleTab;
  let html = heading(
    "排班工作台",
    "先预览，再确认。每一次安排，都经过业务约束校验。",
    button(`${icon("refresh")} 刷新`, "refresh"),
    "Scheduling studio",
  );
  html += `<div class="tabs"><button class="tab ${tab === "preview" ? "active" : ""}" data-action="schedule-tab" data-tab="preview">排班预览</button><button class="tab ${tab === "formal" ? "active" : ""}" data-action="schedule-tab" data-tab="formal">正式排班</button></div>`;
  if (tab === "formal") {
    const query = new URLSearchParams();
    if (state.formalStart) query.set("start_date", state.formalStart);
    if (state.formalEnd) query.set("end_date", state.formalEnd);
    const days = await allRows(`/schedules?${query}`);
    return (
      html +
      `<div class="panel"><div class="toolbar"><label class="field">开始日期<input type="date" id="formal-start" value="${esc(state.formalStart)}"></label><label class="field">结束日期<input type="date" id="formal-end" value="${esc(state.formalEnd)}"></label>${button("筛选排班", "formal-filter", "primary")}</div></div>${days.length ? days.map((d) => `<div class="preview-meta"><h2>${esc(d.plan_title)}</h2><span class="inline-note">版本 ${d.version} · ${esc(d.algorithm)}</span></div>${dayCard(d, false)}`).join("") : empty("暂无正式排班", "在预览中选择日期，人工确认后即可在这里查看。")}`
    );
  }
  if (!state.plans.length)
    return (
      html +
      empty(
        "先创建采集计划",
        "有了每日需求，才能为车辆与司机安排任务。",
        button("新建计划", "new-plan", "primary"),
      )
    );
  const previews = await api(`/schedules/previews?plan_id=${state.planId}`);
  if (state.preview)
    state.preview = await api(
      `/schedules/previews/${state.preview.preview_id}`,
    );
  html += `<section class="panel"><div class="toolbar"><label class="field wide">采集计划<select id="schedule-plan">${planOptions()}</select></label><label class="field">开始日期<input id="schedule-start" type="date" value="${state.scheduleStart}" min="${currentPlan().start_date}" max="${currentPlan().end_date}"></label><label class="field">结束日期<input id="schedule-end" type="date" value="${state.scheduleEnd}" min="${currentPlan().start_date}" max="${currentPlan().end_date}"></label>${button(`${icon("spark")} 生成排班预览`, "generate", "primary")}</div>${previews.length ? `<div class="panel-foot"><label>历史预览 <select class="control" id="history-preview"><option value="">选择一份预览继续查看</option>${previews.map((p) => `<option value="${p.preview_id}" ${state.preview?.preview_id === p.preview_id ? "selected" : ""}>${p.start_date} — ${p.end_date} · v${p.preview_version} · ${statusNames[p.lifecycle_status] || p.lifecycle_status}</option>`).join("")}</select></label><span>相同计划与日期会复用已有预览</span></div>` : ""}</section>`;
  const p = state.preview;
  if (!p)
    return (
      html +
      empty(
        "准备好下一程安排",
        "选择计划和日期，生成独立于正式排班的可编辑预览。",
        `<span class="inline-note">GREEDY_V1 · 效率优先 · 容量均衡 · 人工确认</span>`,
      )
    );
  const editable = ["PENDING", "PARTIALLY_CONFIRMED"].includes(
    p.lifecycle_status,
  );
  const selectable = p.daily_results.filter(
    (d) =>
      !d.confirmed && d.constraint_validation.valid && d.assignments.length,
  );
  state.selected = new Set(
    [...state.selected].filter((d) => selectable.some((s) => s.date === d)),
  );
  html += `<div class="preview-meta"><div><h2>${esc(p.plan_title)} ${badge(p.lifecycle_status)}</h2><p>${p.start_date} 至 ${p.end_date} · ${p.daily_results.length} 天 · ${p.algorithm} · 版本 ${p.preview_version}</p></div><span class="preview-id">${esc(p.preview_id)}</span></div><div class="info-line">${icon("shield")}<span>${esc(p.explanation)}<br>预览有效至 ${new Date(p.expires_at).toLocaleString("zh-CN")}；确认时将重新检查资源占用。</span></div>${p.daily_results.map((d) => dayCard(d, editable)).join("")}`;
  if (editable)
    html += `<div class="sticky-confirm"><div><strong id="selection-count">已选择 ${state.selected.size} 个待确认日期</strong><p>确认后正式占用资源，并立即发送控制台模拟通知。</p></div><div class="actions">${button("全选可确认日期", "select-all", "small")}${button("放弃剩余预览", "discard", "small danger")}${button(`${icon("check")} 确认所选排班`, "confirm", "primary", `${state.selected.size ? "" : "disabled"} id="confirm-selected"`)}</div></div>`;
  return html;
}

function fleetPage() {
  let html = heading(
    "车队资源",
    "管理司机效率、班次资格、车辆容量和资源不可用日期。",
    button(
      `${icon("plus")} ${state.fleetTab === "drivers" ? "新增司机" : "新增车辆"}`,
      state.fleetTab === "drivers" ? "new-driver" : "new-vehicle",
      "primary",
    ),
    "Fleet resources",
  );
  html += `<div class="tabs"><button class="tab ${state.fleetTab === "drivers" ? "active" : ""}" data-action="fleet-tab" data-tab="drivers">司机管理 <span class="badge">${state.drivers.length}</span></button><button class="tab ${state.fleetTab === "vehicles" ? "active" : ""}" data-action="fleet-tab" data-tab="vehicles">车辆与容量 <span class="badge">${state.vehicles.length}</span></button><button class="tab ${state.fleetTab === "shifts" ? "active" : ""}" data-action="fleet-tab" data-tab="shifts">班次配置</button></div>`;
  if (state.fleetTab === "drivers")
    return (
      html +
      `<section class="panel"><div class="panel-header"><h2>司机名册</h2><span class="inline-note">效率只影响优先级，不扩大车辆容量</span></div>${state.drivers.length ? `<div class="table-scroll"><table><thead><tr><th>司机</th><th>联系方式</th><th>效率等级</th><th>班次资格</th><th>资源状态</th><th class="text-right">操作</th></tr></thead><tbody>${state.drivers.map((d) => `<tr><td><div class="driver-name"><span class="driver-avatar">${esc(d.name.slice(-1))}</span><div><strong>${esc(d.name)}</strong><small>D${String(d.id).padStart(3, "0")}</small></div></div></td><td class="number">${esc(d.phone) || "—"}</td><td>${badge(d.efficiency_level)}</td><td>${d.available_shifts.map((s) => `<span class="badge">${shiftNames[s]}</span>`).join(" ")}</td><td>${badge(d.status)}</td><td class="text-right">${button("编辑", "edit-driver", "small", `data-id="${d.id}"`)} ${button("请假 / 不可用", "unavailability", "small", `data-id="${d.id}" data-kind="drivers"`)}</td></tr>`).join("")}</tbody></table></div>` : empty("暂无司机", "新增司机并配置效率等级与班次资格。")}</section>`
    );
  if (state.fleetTab === "vehicles")
    return (
      html +
      `<div class="vehicle-grid">${
        state.vehicles
          .map(
            (v) =>
              `<section class="vehicle-card"><div class="vehicle-card-top"><div class="driver-name"><div class="vehicle-icon">${icon("truck")}</div><div><h3>${esc(v.vehicle_name)}</h3><span class="inline-note number">${esc(v.plate_number)} · V${String(v.id).padStart(3, "0")}</span></div></div>${badge(v.status)}</div><div class="vehicle-capacities">${Object.keys(
                shiftNames,
              )
                .map((s) => {
                  const c = v.capacities.find((c) => c.shift === s);
                  return `<div>${shiftNames[s]}<b class="number">${c ? n(c.max_tag_count) : 0} Tag</b><span class="number">${c ? n(c.max_road_km) : 0} km</span></div>`;
                })
                .join(
                  "",
                )}</div><footer>${button("编辑车辆与容量", "edit-vehicle", "small", `data-id="${v.id}"`)}${button("维修 / 不可用", "unavailability", "small", `data-id="${v.id}" data-kind="vehicles"`)}</footer></section>`,
          )
          .join("") || empty("暂无车辆", "新增车辆并设置各班次采集容量。")
      }</div>`
    );
  return (
    html +
    `<section class="panel"><div class="panel-header"><h2>早 / 中 / 晚班次</h2><span class="inline-note">司机每天最多一班，车辆每日最多三班</span></div><div class="table-scroll"><table><thead><tr><th>班次</th><th>代码</th><th>工作时段</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.shifts.map((s) => `<tr><td>${esc(s.name)}</td><td>${s.code}</td><td class="number">${s.start_time} — ${s.end_time}</td><td>${badge(s.enabled ? "ACTIVE" : "DISABLED")}</td><td>${button("配置班次", "edit-shift", "small", `data-code="${s.code}"`)}</td></tr>`).join("")}</tbody></table></div></section>`
  );
}
async function statisticsPage() {
  const query = new URLSearchParams();
  if (state.statsStart) query.set("start_date", state.statsStart);
  if (state.statsEnd) query.set("end_date", state.statsEnd);
  const stats = await api(`/schedules/statistics?${query}`);
  const max = Math.max(1, ...stats.driver_workloads.map((d) => d.shift_count));
  return (
    heading(
      "排班统计",
      "按正式排班统计覆盖率与资源工作量，Tag 与道路任务独立衡量。",
      "",
      "Scheduling insights",
    ) +
    `<section class="panel"><div class="toolbar"><label class="field">开始日期<input type="date" id="stats-start" value="${esc(state.statsStart)}"></label><label class="field">结束日期<input type="date" id="stats-end" value="${esc(state.statsEnd)}"></label>${button("更新统计", "stats-filter", "primary")}</div></section><div class="metric-grid">${metric("正式排班", stats.assignment_count, "班", `${stats.confirmed_days} 个计划日已确认`, "calendar")}${metric("Tag 已分配", stats.tag_assigned, "个", `目标 ${n(stats.tag_target)} 个 · 覆盖 ${stats.tag_coverage_rate ?? "—"}%`, "layers")}${metric("道路已分配", stats.road_assigned_km, "km", `目标 ${n(stats.road_target_km)} km · 覆盖 ${stats.road_coverage_rate ?? "—"}%`, "truck")}${metric("尚有未分配", stats.unallocated.length, "计划日", "仅提醒，不会自动结转到其他日期", "warning")}</div><div class="grid-two"><section class="panel"><div class="panel-header"><h2>司机工作班次</h2><span class="inline-note">同效率等级内比较工作量</span></div><div class="panel-body">${[
      "HIGH",
      "MEDIUM",
      "LOW",
    ]
      .map(
        (level) =>
          `<div class="section-heading">${badge(level)}</div>${stats.driver_workloads
            .filter((d) => d.efficiency_level === level)
            .map(
              (d) =>
                `<div class="workload-row"><strong>${esc(d.name)}</strong><div class="progress"><span style="width:${(d.shift_count / max) * 100}%"></span></div><small class="number">${d.shift_count} 班</small></div>`,
            )
            .join("")}`,
      )
      .join(
        "",
      )}</div></section><section class="panel"><div class="panel-header"><h2>车辆采集工作量</h2></div>${stats.vehicle_workloads.length ? `<div class="table-scroll"><table><thead><tr><th>车辆</th><th>班次</th><th>Tag</th><th>道路 km</th></tr></thead><tbody>${stats.vehicle_workloads.map((v) => `<tr><td>${esc(state.vehicles.find((r) => r.id === v.vehicle_id)?.vehicle_name || v.vehicle_id)}</td><td>${v.shift_count}</td><td class="number">${n(v.tag_count)}</td><td class="number">${n(v.road_km)}</td></tr>`).join("")}</tbody></table></div>` : empty("等待正式排班", "确认排班后将展示车辆工作量。")}</section></div>${stats.unallocated.length ? `<section class="panel"><div class="panel-header"><h2>未分配任务提醒</h2></div><div class="table-scroll"><table><thead><tr><th>日期 / 计划</th><th>Tag 未分配</th><th>道路未分配</th></tr></thead><tbody>${stats.unallocated.map((d) => `<tr><td>${d.date}<small>PLAN-${d.plan_id}</small></td><td>${d.tags.map((t) => `${esc(t.tag_type)}：${n(t.count)} 个`).join("<br>") || "—"}</td><td>${d.roads.map((r) => `${esc(roadNames[r.road_type] || r.road_type)}：${n(r.km)} km`).join("<br>") || "—"}</td></tr>`).join("")}</tbody></table></div></section>` : ""}`
  );
}
async function notificationsPage() {
  const rows = await allRows(
    `/notifications?${state.notificationStatus ? `status=${state.notificationStatus}` : ""}`,
  );
  return (
    heading(
      "通知中心",
      "确认成功后即时模拟发送；发送失败不会撤销正式排班。",
      button(`${icon("refresh")} 刷新状态`, "refresh"),
      "Notification center",
    ) +
    `<div class="tabs">${[
      ["", "全部通知"],
      ["SENT", "发送成功"],
      ["FAILED", "发送失败"],
      ["PENDING", "等待发送"],
    ]
      .map(
        ([key, label]) =>
          `<button class="tab ${state.notificationStatus === key ? "active" : ""}" data-action="notification-filter" data-status="${key}">${label}</button>`,
      )
      .join(
        "",
      )}</div><section class="panel"><div class="panel-header"><h2>通知记录 <span class="badge">${rows.length}</span></h2><span class="inline-note">当前渠道：控制台模拟 · 同一排班版本幂等</span></div>${rows.length ? `<div class="table-scroll"><table><thead><tr><th>通知 / 司机</th><th>创建时间</th><th>状态</th><th>通知内容</th><th class="text-right">操作</th></tr></thead><tbody>${rows.map((r) => `<tr><td><strong>${esc(r.driver_name)}</strong><small>#${r.id} · 排班明细 ${r.assignment_id} · v${r.schedule_version}</small></td><td class="number">${new Date(r.created_at).toLocaleString("zh-CN")}</td><td>${badge(r.status, r.status === "PENDING" ? "等待发送" : undefined)}<small>重试 ${r.retry_count} 次</small></td><td><details><summary>查看任务通知</summary><pre class="notification-content">${esc(r.content)}</pre>${r.error_message ? `<div class="form-error">${esc(r.error_message)}</div>` : ""}</details></td><td class="text-right">${r.status !== "SENT" ? button("重试发送", "retry-notification", "small", `data-id="${r.id}"`) : '<span class="inline-note">已送达模拟日志</span>'}</td></tr>`).join("")}</tbody></table></div>` : empty("暂无通知记录", "人工确认排班后，系统会为每条有效排班创建通知。")}</section>`
  );
}
function agentPage() {
  return (
    heading(
      "Agent 助手",
      "Agent 模块由你后续开发，现阶段通过业务页面和 API 完成排班。",
      "",
      "Agent workspace",
    ) +
    `<section class="panel agent-placeholder"><div class="agent-symbol">${icon("spark")}</div><h2>为下一步智能协作，留好位置。</h2><p>DeepSeek、Tool Calling、会话管理和工具执行尚未实现。<br>业务服务和 OpenAPI 接口已可独立使用，后续 Agent 可通过这些接口接入。</p><span class="badge amber">待开发</span><p></p><div class="mono">app/agent/ &nbsp; app/agent/tools/</div><p class="subtitle">以上目录保持为空。</p><a class="button primary" href="/docs" target="_blank" rel="noreferrer">查看业务 API ↗</a></section>`
  );
}
async function auditPage() {
  const rows = await api("/audit-logs");
  const actions = {
    CREATE_PLAN: "创建采集计划",
    CREATE_DRIVER: "新增司机",
    UPDATE_DRIVER: "更新司机",
    CREATE_VEHICLE: "新增车辆",
    UPDATE_VEHICLE: "更新车辆",
    UPDATE_SHIFT: "更新班次",
    GENERATE_PREVIEW: "生成排班预览",
    UPDATE_PREVIEW_ASSIGNMENT: "修改预览明细",
    ADD_PREVIEW_ASSIGNMENT: "新增预览明细",
    DELETE_PREVIEW_ASSIGNMENT: "删除预览明细",
    CONFIRM_SCHEDULE: "确认正式排班",
    DISCARD_PREVIEW: "放弃排班预览",
    SEND_NOTIFICATION: "发送模拟通知",
    RETRY_NOTIFICATION: "重试通知",
    ADD_UNAVAILABILITY: "登记不可用日期",
    DELETE_UNAVAILABILITY: "移除不可用日期",
  };
  return (
    heading(
      "操作日志",
      "记录关键业务变更，便于追踪预览调整、确认与通知结果。",
      button("刷新", "refresh"),
      "Activity log",
    ) +
    `<section class="panel"><div class="panel-header"><h2>最近 100 条操作</h2></div><div class="table-scroll"><table><thead><tr><th>操作</th><th>对象</th><th>操作者</th><th>时间</th><th>变更详情</th></tr></thead><tbody>${rows.map((r) => `<tr><td><strong>${esc(actions[r.action] || r.action)}</strong></td><td>${esc(r.target_type)}<small>${esc(r.target_id)}</small></td><td>${esc(r.operator_id)}</td><td class="number">${new Date(r.created_at).toLocaleString("zh-CN")}</td><td><details><summary>查看记录</summary><pre class="notification-content">${esc(JSON.stringify({ before: r.before_data, after: r.after_data }, null, 2))}</pre></details></td></tr>`).join("")}</tbody></table></div></section>`
  );
}

function openModal(title, body, submitLabel, onSubmit) {
  modalSubmit = onSubmit;
  $("#modal-content").innerHTML =
    `<form id="modal-form"><header class="modal-header"><h2 id="modal-title">${esc(title)}</h2><button type="button" class="icon-button" data-action="close-modal" aria-label="关闭">${icon("close")}</button></header><div class="modal-body">${body}<div class="form-error hidden" id="modal-error" role="alert"></div></div><footer class="modal-footer"><button type="button" class="button" data-action="close-modal">${submitLabel ? "取消" : "关闭"}</button>${submitLabel ? `<button type="submit" class="button primary" id="modal-submit">${esc(submitLabel)}</button>` : ""}</footer></form>`;
  if (!$("#modal").open) $("#modal").showModal();
}
function closeModal() {
  $("#modal").close();
  modalSubmit = null;
}
function requirementRow(kind, type = "", amount = "") {
  return `<div class="requirement-row"><input class="control requirement-type" aria-label="${kind === "tag" ? "Tag 类型" : "道路类型"}" placeholder="${kind === "tag" ? "例如 Tag-A" : "CITY / HIGHWAY / RURAL"}" maxlength="80" value="${esc(type)}" required><input class="control requirement-amount" aria-label="${kind === "tag" ? "Tag 数量" : "道路公里数"}" type="number" min="${kind === "tag" ? "1" : "0.001"}" max="${kind === "tag" ? "100000000" : "1000000"}" step="${kind === "tag" ? "1" : "0.001"}" placeholder="${kind === "tag" ? "每日数量" : "每日公里数"}" value="${esc(amount)}" required><button type="button" class="remove-row" data-action="remove-row" aria-label="移除此需求">×</button></div>`;
}
function requirementSection(kind, rows = []) {
  return `<section class="form-section"><div class="section-heading"><h3>${kind === "tag" ? "Tag 采集需求（个）" : "道路采集需求（km）"}</h3><button type="button" class="tiny-link" data-action="add-requirement" data-kind="${kind}">＋ 添加类型</button></div><div class="requirement-list" data-kind="${kind}">${rows.map((r) => requirementRow(kind, ...r)).join("")}</div></section>`;
}
function readRequirements(root) {
  const read = (kind) =>
    $$(
      ".requirement-row",
      $(`.requirement-list[data-kind="${kind}"]`, root),
    ).map((row) => ({
      type: $(".requirement-type", row).value.trim(),
      amount: $(".requirement-amount", row).value,
    }));
  return {
    tag_requirements: read("tag").map((r) => ({
      tag_type: r.type,
      daily_count: Number(r.amount),
    })),
    road_requirements: read("road").map((r) => ({
      road_type: r.type,
      daily_km: r.amount,
    })),
  };
}
function newPlan() {
  openModal(
    "新建采集计划",
    `<p class="modal-subtitle">日期首尾均包含。默认需求会展开到每一天，也可以按日期单独配置。</p><div class="form-grid"><label class="field span-2">计划名称<input name="title" maxlength="150" placeholder="例如：11 月城市道路采集" required></label><label class="field">开始日期<input name="start_date" type="date" value="${today()}" required></label><label class="field">结束日期<input name="end_date" type="date" value="${today()}" required></label><label class="field span-2">备注<textarea name="notes" maxlength="3000" placeholder="采集说明或补充信息（可选）"></textarea></label></div><div id="default-requirements">${requirementSection("tag", [["Tag-A", 100]])}${requirementSection("road", [["CITY", "80"]])}</div><section class="form-section"><div class="section-heading"><h3>指定日期的独立需求（可选）</h3><button type="button" class="tiny-link" data-action="add-override">＋ 添加日期配置</button></div><p class="inline-note">覆盖该日期的全部需求；未配置的日期使用上面的默认需求。</p><div id="daily-overrides"></div></section>`,
    "创建计划",
    async (form) => {
      const data = new FormData(form);
      const payload = {
        title: data.get("title"),
        start_date: data.get("start_date"),
        end_date: data.get("end_date"),
        notes: data.get("notes"),
        ...readRequirements($("#default-requirements", form)),
        daily_overrides: $$(".override-block", form).map((block) => ({
          date: $(".override-date", block).value,
          ...readRequirements(block),
        })),
      };
      const plan = await post("/plans", payload);
      state.plans.unshift(plan);
      setPlan(plan.plan_id);
      closeModal();
      toast("采集计划已创建，每日需求已保存");
      await render();
    },
  );
}
async function planDetail(id) {
  const p = state.plans.find((p) => p.plan_id === Number(id));
  const days = await api(`/plans/${id}/daily-tasks`);
  openModal(
    "每日采集需求",
    `<p class="modal-subtitle">${esc(p.title)} · ${p.start_date} — ${p.end_date}</p>${p.notes ? `<div class="info-line">${esc(p.notes)}</div>` : ""}<div class="table-scroll"><table><thead><tr><th>采集日期</th><th>Tag 需求</th><th>道路需求</th></tr></thead><tbody>${days.map((d) => `<tr><td>${d.date}<small>${dateLabel(d.date)}</small></td><td>${d.tag_requirements.map((t) => `${esc(t.tag_type)}：${n(t.count)} 个`).join("<br>") || "—"}</td><td>${d.road_requirements.map((r) => `${esc(roadNames[r.road_type] || r.road_type)}：${n(r.km)} km`).join("<br>") || "—"}</td></tr>`).join("")}</tbody></table></div>`,
  );
}
function driverModal(id) {
  const d = state.drivers.find((d) => d.id === Number(id));
  openModal(
    d ? "编辑司机" : "新增司机",
    `<p class="modal-subtitle">高效率优先；相同等级内按累计班次数均衡选择。</p><div class="form-grid"><label class="field">司机姓名<input name="name" maxlength="80" value="${esc(d?.name)}" required></label><label class="field">联系方式<input name="phone" maxlength="40" value="${esc(d?.phone)}"></label><label class="field">效率等级<select name="efficiency_level">${Object.entries(
      efficiencyNames,
    )
      .map(
        ([k, v]) =>
          `<option value="${k}" ${(d?.efficiency_level || "MEDIUM") === k ? "selected" : ""}>${v}</option>`,
      )
      .join(
        "",
      )}</select></label><label class="field">资源状态<select name="status"><option value="ACTIVE">可用</option><option value="DISABLED" ${d?.status === "DISABLED" ? "selected" : ""}>停用</option></select></label></div><section class="form-section"><h3>班次资格</h3><div class="checkbox-group">${Object.entries(
      shiftNames,
    )
      .map(
        ([k, v]) =>
          `<label><input type="checkbox" name="available_shifts" value="${k}" ${!d || d.available_shifts.includes(k) ? "checked" : ""}>${v}</label>`,
      )
      .join("")}</div></section>`,
    "保存司机",
    async (form) => {
      const data = new FormData(form);
      await post(
        d ? `/drivers/${d.id}` : "/drivers",
        {
          name: data.get("name"),
          phone: data.get("phone"),
          efficiency_level: data.get("efficiency_level"),
          status: data.get("status"),
          available_shifts: data.getAll("available_shifts"),
        },
        d ? "PUT" : "POST",
      );
      closeModal();
      toast("司机信息已保存");
      await render();
    },
  );
}
function vehicleModal(id) {
  const v = state.vehicles.find((v) => v.id === Number(id));
  openModal(
    v ? "编辑车辆与容量" : "新增车辆",
    `<p class="modal-subtitle">不同班次可配置不同容量。容量为 0 表示该班次不能执行对应模式。</p><div class="form-grid"><label class="field">车辆名称<input name="vehicle_name" maxlength="80" value="${esc(v?.vehicle_name)}" required></label><label class="field">车牌号<input name="plate_number" maxlength="30" value="${esc(v?.plate_number)}" required></label><label class="field">资源状态<select name="status"><option value="ACTIVE">可用</option><option value="DISABLED" ${v?.status === "DISABLED" ? "selected" : ""}>停用</option></select></label></div><section class="form-section"><h3>每班最大采集容量</h3><div class="capacity-grid">${Object.entries(
      shiftNames,
    )
      .map(([k, label]) => {
        const c = v?.capacities.find((c) => c.shift === k);
        return `<div class="capacity-box" data-shift="${k}"><h3>${label}</h3><label class="field">Tag 数量<input type="number" class="tag-capacity" min="0" max="100000000" step="1" value="${c?.max_tag_count ?? 100}" required></label><label class="field">道路里程 / km<input type="number" class="road-capacity" min="0" max="1000000" step="0.001" value="${c?.max_road_km ?? "80"}" required></label></div>`;
      })
      .join("")}</div></section>`,
    "保存车辆",
    async (form) => {
      const data = new FormData(form);
      const capacities = $$(".capacity-box", form).map((box) => ({
        shift: box.dataset.shift,
        max_tag_count: Number($(".tag-capacity", box).value),
        max_road_km: $(".road-capacity", box).value,
      }));
      await post(
        v ? `/vehicles/${v.id}` : "/vehicles",
        {
          vehicle_name: data.get("vehicle_name"),
          plate_number: data.get("plate_number"),
          status: data.get("status"),
          capacities,
        },
        v ? "PUT" : "POST",
      );
      closeModal();
      toast("车辆与各班次容量已保存");
      await render();
    },
  );
}
function shiftModal(code) {
  const s = state.shifts.find((s) => s.code === code);
  openModal(
    "配置班次",
    `<p class="modal-subtitle">${s.code} · 时间用于展示，排班冲突按自然日与班次代码校验。</p><div class="form-grid"><label class="field">班次名称<input name="name" value="${esc(s.name)}" maxlength="80" required></label><label class="field">状态<select name="enabled"><option value="true">启用</option><option value="false" ${!s.enabled ? "selected" : ""}>停用</option></select></label><label class="field">开始时间<input name="start_time" type="time" value="${s.start_time}" required></label><label class="field">结束时间<input name="end_time" type="time" value="${s.end_time}" required></label></div>`,
    "保存班次",
    async (form) => {
      const data = new FormData(form);
      await post(
        `/shifts/${code}`,
        {
          name: data.get("name"),
          enabled: data.get("enabled") === "true",
          start_time: data.get("start_time"),
          end_time: data.get("end_time"),
        },
        "PUT",
      );
      closeModal();
      toast("班次已更新");
      await render();
    },
  );
}
async function unavailabilityModal(kind, id) {
  const row = state[kind].find((r) => r.id === Number(id));
  const rows = await api(`/${kind}/${id}/unavailability`);
  openModal(
    "登记不可用日期",
    `<p class="modal-subtitle">${esc(row.name || row.vehicle_name)} · 司机请假或车辆维修期间将从排班候选中排除。</p><div class="form-grid"><label class="field">开始日期<input name="start_date" type="date" value="${today()}" required></label><label class="field">结束日期<input name="end_date" type="date" value="${today()}" required></label><label class="field span-2">原因<input name="reason" maxlength="200" placeholder="例如：年假、车辆检修"></label></div><section class="form-section"><h3>已有不可用记录</h3><div class="detail-list">${rows.map((r) => `<div class="detail-item"><div>${r.start_date} — ${r.end_date}<p>${esc(r.reason) || "无备注"}</p></div><button type="button" class="tiny-link danger" data-action="remove-unavailability" data-id="${r.id}" data-kind="${kind}" data-resource="${id}">移除</button></div>`).join("") || '<p class="inline-note">暂无记录</p>'}</div></section>`,
    "登记不可用",
    async (form) => {
      const data = new FormData(form);
      await post(`/${kind}/${id}/unavailability`, {
        start_date: data.get("start_date"),
        end_date: data.get("end_date"),
        reason: data.get("reason"),
      });
      closeModal();
      toast("不可用日期已登记");
      await render();
    },
  );
}
function assignmentModal(dayString, identifier) {
  const day = state.preview.daily_results.find((d) => d.date === dayString);
  const a = day.assignments.find(
    (a) => String(a.assignment_id) === String(identifier),
  );
  openModal(
    a ? "编辑排班明细" : "新增排班明细",
    `<p class="modal-subtitle">${dayString} · 所有更改必须通过约束校验。无效更改会保留原预览。</p><div class="form-grid"><label class="field">车辆<select name="vehicle_id">${state.vehicles.map((v) => `<option value="${v.id}" ${v.id === a?.vehicle_id ? "selected" : ""}>${esc(v.vehicle_name)} · ${esc(v.plate_number)}${v.status === "DISABLED" ? "（已停用）" : ""}</option>`).join("")}</select></label><label class="field">司机<select name="driver_id">${state.drivers.map((d) => `<option value="${d.id}" ${d.id === a?.driver_id ? "selected" : ""}>${esc(d.name)} · ${efficiencyNames[d.efficiency_level]}${d.status === "DISABLED" ? "（已停用）" : ""}</option>`).join("")}</select></label><label class="field">班次<select name="shift">${Object.entries(
      shiftNames,
    )
      .map(
        ([k, v]) =>
          `<option value="${k}" ${k === a?.shift ? "selected" : ""}>${v}</option>`,
      )
      .join(
        "",
      )}</select></label><label class="field">任务模式<select name="task_mode" id="assignment-mode"><option value="TAG">Tag 采集</option><option value="ROAD" ${a?.task_mode === "ROAD" ? "selected" : ""}>道路采集</option></select></label></div><section class="form-section"><div class="section-heading"><h3>任务分配量</h3><span class="inline-note">0 表示不分配该项</span></div><div id="assignment-allocations"></div></section>`,
    "保存到预览",
    async (form) => {
      const data = new FormData(form),
        mode = data.get("task_mode");
      const allocations = $$(".allocation-input", form)
        .filter((input) => Number(input.value) > 0)
        .map((input) =>
          mode === "TAG"
            ? { tag_type: input.dataset.type, count: Number(input.value) }
            : { road_type: input.dataset.type, km: input.value },
        );
      const assignment = {
        vehicle_id: Number(data.get("vehicle_id")),
        driver_id: Number(data.get("driver_id")),
        shift: data.get("shift"),
        task_mode: mode,
        tag_allocations: mode === "TAG" ? allocations : [],
        road_allocations: mode === "ROAD" ? allocations : [],
      };
      state.preview = await post(
        a
          ? `/schedules/previews/${state.preview.preview_id}/assignments/${a.assignment_id}`
          : `/schedules/previews/${state.preview.preview_id}/assignments`,
        a
          ? {
              expected_version: state.preview.preview_version,
              changes: assignment,
            }
          : {
              expected_version: state.preview.preview_version,
              date: dayString,
              ...assignment,
            },
        a ? "PATCH" : "POST",
      );
      closeModal();
      toast("预览已更新，尚未正式确认");
      await render();
    },
  );
  const draw = () => {
    const mode = $("#assignment-mode").value;
    const requirements =
      mode === "TAG" ? day.requirements.tags : day.requirements.roads;
    $("#assignment-allocations").innerHTML =
      requirements
        .map((t) => {
          const type = mode === "TAG" ? t.tag_type : t.road_type;
          const existing =
            mode === "TAG"
              ? a?.tag_allocations.find((x) => x.tag_type === type)?.count
              : a?.road_allocations.find((x) => x.road_type === type)?.km;
          return `<label class="field" style="margin-top:12px">${esc(roadNames[type] || type)} · 当天目标 ${n(t.count ?? t.km)} ${mode === "TAG" ? "个" : "km"}<input type="number" class="allocation-input" data-type="${esc(type)}" min="0" max="${t.count ?? t.km}" step="${mode === "TAG" ? "1" : "0.001"}" value="${existing ?? 0}" required></label>`;
        })
        .join("") || '<p class="inline-note">当天没有此模式的任务需求。</p>';
  };
  $("#assignment-mode").addEventListener("change", draw);
  draw();
}
function confirmDialog(title, message, callback, label = "确认") {
  openModal(
    title,
    `<div class="confirm-summary">${message}</div>`,
    label,
    async () => {
      await callback();
    },
  );
}
function keyModal() {
  openModal(
    "配置 API 访问密钥",
    '<p class="modal-subtitle">与服务端 .env 中 API_KEY 保持一致。只保存在当前浏览器标签页会话中。</p><label class="field">访问密钥<input type="password" name="key" autocomplete="off" placeholder="本地服务未配置密钥时可留空"></label>',
    "保存并重连",
    async (form) => {
      sessionStorage.setItem("fleet-api-key", new FormData(form).get("key"));
      closeModal();
      await render();
    },
  );
}

async function handleAction(element) {
  const { action, id, tab, date: day, kind, code } = element.dataset;
  if (action === "refresh") return render();
  if (action === "key") return keyModal();
  if (action === "close-modal") return closeModal();
  if (action === "new-plan") return newPlan();
  if (action === "plan-detail") return planDetail(id);
  if (action === "plan-schedule") {
    setPlan(id);
    state.scheduleTab = "preview";
    if (location.hash === "#scheduling") return render();
    location.hash = "scheduling";
    return;
  }
  if (action === "fleet-tab") {
    state.fleetTab = tab;
    return render();
  }
  if (action === "schedule-tab") {
    state.scheduleTab = tab;
    return render();
  }
  if (action === "new-driver" || action === "edit-driver")
    return driverModal(id);
  if (action === "new-vehicle" || action === "edit-vehicle")
    return vehicleModal(id);
  if (action === "edit-shift") return shiftModal(code);
  if (action === "unavailability") return unavailabilityModal(kind, id);
  if (action === "remove-unavailability") {
    await api(`/unavailability/${id}`, { method: "DELETE" });
    return unavailabilityModal(kind, element.dataset.resource);
  }
  if (action === "add-requirement") {
    const list = $(".requirement-list", element.closest(".form-section"));
    list.insertAdjacentHTML("beforeend", requirementRow(kind));
    return;
  }
  if (action === "remove-row") {
    element.closest(".requirement-row").remove();
    return;
  }
  if (action === "add-override") {
    $("#daily-overrides").insertAdjacentHTML(
      "beforeend",
      `<div class="override-block"><div class="section-heading"><label class="field">指定日期<input type="date" class="override-date" required></label><button type="button" class="tiny-link danger" data-action="remove-override">移除配置</button></div>${requirementSection("tag")}${requirementSection("road")}</div>`,
    );
    return;
  }
  if (action === "remove-override") {
    element.closest(".override-block").remove();
    return;
  }
  if (action === "generate") {
    state.scheduleStart = $("#schedule-start").value;
    state.scheduleEnd = $("#schedule-end").value;
    const result = await post("/schedules/preview", {
      plan_id: state.planId,
      start_date: state.scheduleStart,
      end_date: state.scheduleEnd,
      algorithm: "GREEDY_V1",
    });
    if (result.previews.length) {
      state.preview = result.previews[0];
      state.selected = new Set(
        state.preview.daily_results
          .filter(
            (d) =>
              !d.confirmed &&
              d.date >= state.scheduleStart &&
              d.date <= state.scheduleEnd &&
              d.assignments.length &&
              d.constraint_validation.valid,
          )
          .map((d) => d.date),
      );
      toast(
        result.operation_status === "CREATED"
          ? "排班预览已生成，请检查后确认"
          : "已载入当前预览；重新生成前需先放弃旧预览",
      );
    } else {
      state.scheduleTab = "formal";
      toast("所选日期已全部确认，请查看正式排班");
    }
    if (result.previews.length > 1)
      toast(
        `所选范围涉及 ${result.previews.length} 份已有预览，可在历史预览中逐份查看`,
      );
    return render();
  }
  if (action === "add-assignment" || action === "edit-assignment")
    return assignmentModal(day, id);
  if (action === "delete-assignment")
    return confirmDialog(
      "删除预览明细",
      "删除后，该条任务量会重新计入本次预览的未分配量。",
      async () => {
        state.preview = await api(
          `/schedules/previews/${state.preview.preview_id}/assignments/${id}?expected_version=${state.preview.preview_version}`,
          { method: "DELETE" },
        );
        closeModal();
        toast("明细已删除，未分配量已更新");
        await render();
      },
      "删除明细",
    );
  if (action === "discard")
    return confirmDialog(
      "放弃剩余预览",
      "未确认日期的预览将失效，之后可以重新生成。已确认日期保留正式排班。",
      async () => {
        state.preview = await post(
          `/schedules/previews/${state.preview.preview_id}/discard`,
          { expected_version: state.preview.preview_version },
        );
        state.selected.clear();
        closeModal();
        toast("剩余预览已放弃");
        await render();
      },
      "放弃预览",
    );
  if (action === "select-all") {
    const dates = state.preview.daily_results
      .filter(
        (d) =>
          !d.confirmed && d.assignments.length && d.constraint_validation.valid,
      )
      .map((d) => d.date);
    state.selected =
      state.selected.size === dates.length ? new Set() : new Set(dates);
    updateSelection();
    return;
  }
  if (action === "confirm") {
    if (!state.selected.size) throw new Error("请先选择至少一个待确认日期");
    const dates = [...state.selected].sort(),
      selectedDays = state.preview.daily_results.filter((d) =>
        dates.includes(d.date),
      );
    const partial = selectedDays.some((d) => d.coverage_status !== "FULL");
    const request = {
      preview_id: state.preview.preview_id,
      expected_version: state.preview.preview_version,
      confirm_dates: dates,
      idempotency_key: crypto.randomUUID(),
    };
    return confirmDialog(
      "确认正式排班",
      `你将确认 <strong>${dates.length} 个日期、${selectedDays.reduce((s, d) => s + d.assignments.length, 0)} 条排班</strong>。<br>所有日期通过最新约束检查后一起提交，并立即模拟通知司机。${partial ? "<br><strong>所选日期存在未分配任务，确认后仍仅作提醒，不自动结转。</strong>" : ""}<div class="confirm-dates">${dates.map((d) => `<span class="badge">${d}</span>`).join("")}</div>`,
      async () => {
        const result = await post("/schedules/confirm", request);
        state.selected.clear();
        closeModal();
        toast(
          `${result.operation_status === "ALREADY_CONFIRMED" ? "所选日期已确认，无重复写入" : "正式排班已保存"}${result.notification_status ? ` · 通知${result.notification_status === "SENT" ? "已模拟发送" : result.notification_status === "FAILED" ? "发送失败，请到通知中心重试" : "等待发送"}` : ""}`,
        );
        await render();
      },
      "确认并通知",
    );
  }
  if (action === "formal-filter") {
    state.formalStart = $("#formal-start").value;
    state.formalEnd = $("#formal-end").value;
    return render();
  }
  if (action === "stats-filter") {
    state.statsStart = $("#stats-start").value;
    state.statsEnd = $("#stats-end").value;
    return render();
  }
  if (action === "notification-filter") {
    state.notificationStatus = element.dataset.status;
    return render();
  }
  if (action === "retry-notification") {
    const result = await post(`/notifications/${id}/retry`, {});
    toast(
      result.status === "SENT"
        ? "通知已模拟发送"
        : `发送结果：${result.status}`,
      result.status === "FAILED",
    );
    return render();
  }
}
function updateSelection() {
  $$(".day-select").forEach(
    (input) => (input.checked = state.selected.has(input.dataset.date)),
  );
  if ($("#selection-count"))
    $("#selection-count").textContent =
      `已选择 ${state.selected.size} 个待确认日期`;
  if ($("#confirm-selected"))
    $("#confirm-selected").disabled = !state.selected.size;
}
document.addEventListener("click", async (event) => {
  const element = event.target.closest("[data-action]");
  if (!element || element.disabled) return;
  event.preventDefault();
  const wasDisabled = element.disabled;
  element.disabled = true;
  try {
    await handleAction(element);
  } catch (error) {
    if ($("#modal").open) {
      $("#modal-error").textContent = error.message;
      $("#modal-error").classList.remove("hidden");
    } else toast(error.message, true);
  } finally {
    if (element.isConnected) element.disabled = wasDisabled;
  }
});
document.addEventListener("change", async (event) => {
  const el = event.target;
  try {
    if (el.id === "schedule-plan") {
      setPlan(el.value);
      await render();
    }
    if (el.id === "history-preview" && el.value) {
      state.preview = await api(`/schedules/previews/${el.value}`);
      state.selected.clear();
      await render();
    }
    if (el.classList.contains("day-select")) {
      el.checked
        ? state.selected.add(el.dataset.date)
        : state.selected.delete(el.dataset.date);
      updateSelection();
    }
    if (el.id === "schedule-start") state.scheduleStart = el.value;
    if (el.id === "schedule-end") state.scheduleEnd = el.value;
  } catch (error) {
    toast(error.message, true);
  }
});
document.addEventListener("submit", async (event) => {
  if (event.target.id !== "modal-form") return;
  event.preventDefault();
  if (!modalSubmit) return;
  const submit = $("#modal-submit");
  submit.disabled = true;
  const label = submit.textContent;
  submit.textContent = "正在保存…";
  $("#modal-error").classList.add("hidden");
  try {
    await modalSubmit(event.target);
  } catch (error) {
    $("#modal-error").textContent = error.message;
    $("#modal-error").classList.remove("hidden");
    $("#modal-error").scrollIntoView({ block: "nearest" });
  } finally {
    if (submit.isConnected) {
      submit.disabled = false;
      submit.textContent = label;
    }
  }
});
$("#access-key").addEventListener("click", keyModal);
window.addEventListener("hashchange", render);
$$("[data-icon]").forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
render();
