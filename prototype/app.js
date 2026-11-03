/* Fleetwise 交互原型：数据、约束与 Agent 回复均在浏览器内模拟。 */
(() => {
  "use strict";
  const STORAGE_KEY = "fleetwise.prototype.v1";
  const BASE_DATE = "2026-11-02";
  const SHIFTS = ["早班", "中班", "晚班"];
  const GRADES = { HIGH: "高效率", MEDIUM: "中效率", LOW: "低效率" };
  const PAGES = { workbench: ["排班工作台", "SCHEDULING WORKSPACE", "把任务、车辆与司机，安排在合适的位置。"], plans: ["采集计划", "COLLECTION PLANS", "从每天的采集需求开始，让每一次安排都有依据。"], resources: ["车队资源", "FLEET RESOURCES", "了解每一位司机、每一辆车的可用情况。"], history: ["排班历史", "SCHEDULE HISTORY", "每一份正式安排，每一次调整，都有迹可循。"], reports: ["统计分析", "FLEET INSIGHTS", "关注任务分配与资源使用，数据来自有效正式排班。"], logs: ["操作记录", "ACTIVITY JOURNAL", "按时间回看计划、资源与排班的每一次变化。"] };
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const copy = value => JSON.parse(JSON.stringify(value));
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const btn = (label, action, style = "", extra = "", glyph = "") => `<button type="button" class="btn ${style}" data-action="${action}" ${extra}>${glyph ? icon(glyph) : ""}${label}</button>`;
  const pill = (text, tone = "neutral") => `<span class="pill ${tone}">${esc(text)}</span>`;
  const num = value => Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 3 });
  const round = value => Math.round(value * 1000) / 1000;
  const unit = mode => mode === "TAG" ? "个" : "km";
  const addDate = (date, days) => new Date(Date.parse(date + "T00:00:00Z") + days * 86400000).toISOString().slice(0, 10);
  const weekday = date => "日一二三四五六"[new Date(date + "T00:00:00Z").getUTCDay()];
  const shortDate = date => date.slice(5).replace("-", "/");
  const datesBetween = (start, end) => { const dates = []; for (let d = start; d <= end; d = addDate(d, 1)) dates.push(d); return dates; };
  const uid = prefix => `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
  const total = (items, mode) => round(items.filter(item => item.mode === mode).reduce((sum, item) => sum + Number(item.qty), 0));
  const notice = (text, tone = "info") => `<div class="notice ${tone}">${icon(tone === "error" ? "alert" : "info")}<div>${text}</div></div>`;
  const empty = (title, description, action = "", label = "", glyph = "calendar") => `<div class="empty-state"><div class="empty-illustration">${icon(glyph)}</div><h3>${title}</h3><p>${description}</p>${action ? btn(label, action, "primary", "", "plus") : ""}</div>`;

  function readStorage() { try { const value = JSON.parse(localStorage.getItem(STORAGE_KEY)); return value?.schema === 1 ? value : null; } catch { return null; } }
  function persist() { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { toast("浏览器未允许本地保存，本次修改仅在当前页面保留", true); } }
  function available(resource, date) { return resource?.active && !resource.unavailable.some(range => range.start <= date && range.end >= date); }
  function allDays(data = state) { return data.plans.flatMap(plan => Object.entries(plan.days).map(([date, day]) => ({ plan, date, day }))); }
  function formalCounts(data = state) { const counts = {}; allDays(data).forEach(({ day }) => (day.formal || []).forEach(pack => { counts[pack.driverId] = (counts[pack.driverId] || 0) + 1; })); return counts; }
  function categoryName(id, data = state) { return data.categories.find(item => item.id === id)?.name || "已归档类别"; }
  function snapshot(pack, data = state, previous = null) {
    const driver = data.drivers.find(item => item.id === pack.driverId);
    const car = data.vehicles.find(item => item.id === pack.vehicleId);
    return { ...copy(pack), capacitySnapshot: car.caps[pack.shift][pack.mode], snapshot: { driverName: previous?.driverId === pack.driverId ? previous.snapshot?.driverName || driver.name : driver.name, grade: previous?.driverId === pack.driverId ? previous.snapshot?.grade || driver.grade : driver.grade, plate: previous?.vehicleId === pack.vehicleId ? previous.snapshot?.plate || car.plate : car.plate } };
  }

  function generatePacks(data, date, plan, extraCounts = {}) {
    const demands = copy(plan.days[date].demands);
    const remaining = Object.fromEntries(demands.map(item => [item.categoryId, item.qty]));
    const drivers = data.drivers.filter(item => available(item, date));
    const counts = formalCounts(data);
    const usedDrivers = new Set(), usedCars = new Set(), packs = [];
    for (const mode of ["TAG", "ROAD"]) {
      for (const car of data.vehicles.filter(item => available(item, date))) {
        if (usedCars.has(car.id) || !demands.some(item => item.mode === mode && remaining[item.categoryId] > 0)) continue;
        for (let shift = 0; shift < 3; shift++) {
          let capacity = car.caps[shift][mode];
          if (!capacity) continue;
          const driver = drivers.filter(item => !usedDrivers.has(item.id) && item.shifts.includes(shift)).sort((a, b) => ["HIGH", "MEDIUM", "LOW"].indexOf(a.grade) - ["HIGH", "MEDIUM", "LOW"].indexOf(b.grade) || ((counts[a.id] || 0) + (extraCounts[a.id] || 0)) - ((counts[b.id] || 0) + (extraCounts[b.id] || 0)) || a.id.localeCompare(b.id))[0];
          if (!driver) continue;
          const items = [];
          for (const demand of demands.filter(item => item.mode === mode)) {
            const amount = round(Math.min(capacity, remaining[demand.categoryId]));
            if (amount > 0) { items.push({ categoryId: demand.categoryId, mode, qty: amount }); remaining[demand.categoryId] = round(remaining[demand.categoryId] - amount); capacity = round(capacity - amount); }
          }
          if (items.length) { packs.push({ id: `${date}-${car.id}-${shift}`, vehicleId: car.id, driverId: driver.id, shift, mode, items }); usedDrivers.add(driver.id); usedCars.add(car.id); }
        }
      }
    }
    return packs;
  }

  function validatePacks(data, date, plan, packs, requireNonEmpty = false) {
    const errors = [], drivers = new Set(), slots = new Set(), carModes = {}, assigned = {};
    if (requireNonEmpty && !packs.length) errors.push("没有有效任务包，不能确认空排班；需要清空正式安排时请使用取消。");
    for (const pack of packs) {
      const driver = data.drivers.find(item => item.id === pack.driverId), car = data.vehicles.find(item => item.id === pack.vehicleId);
      if (!driver || !available(driver, date)) errors.push(`${driver?.name || "司机"}在 ${date} 不可用。`);
      if (!car || !available(car, date)) errors.push(`${car?.plate || "车辆"}在 ${date} 不可用。`);
      if (!driver || !car) continue;
      if (!driver.shifts.includes(pack.shift)) errors.push(`${driver.name}不具备${SHIFTS[pack.shift]}资格。`);
      if (drivers.has(driver.id)) errors.push(`${driver.name}在同一天只能安排一个班次。`);
      drivers.add(driver.id);
      const key = `${car.id}-${pack.shift}`;
      if (slots.has(key)) errors.push(`${car.plate}${SHIFTS[pack.shift]}已有任务包。`);
      slots.add(key);
      if (carModes[car.id] && carModes[car.id] !== pack.mode) errors.push(`${car.plate}同一天不能混合 TAG 与 ROAD。`);
      carModes[car.id] = pack.mode;
      if (!pack.items.length) errors.push("任务包至少需要一项正数任务。");
      for (const item of pack.items) {
        const demand = plan.days[date].demands.find(entry => entry.categoryId === item.categoryId && entry.mode === pack.mode);
        if (!demand || item.mode !== pack.mode) errors.push("任务包包含当前模式或当日需求中不存在的类别。");
        if (!(item.qty > 0) || (pack.mode === "TAG" ? !Number.isInteger(item.qty) : Math.abs(item.qty * 1000 - Math.round(item.qty * 1000)) > 0.000001)) errors.push("Tag 必须为正整数，道路公里数最多三位小数。");
        assigned[item.categoryId] = round((assigned[item.categoryId] || 0) + item.qty);
      }
      if (round(pack.items.reduce((sum, item) => sum + item.qty, 0)) > car.caps[pack.shift][pack.mode]) errors.push(`${car.plate}${SHIFTS[pack.shift]}超出 ${num(car.caps[pack.shift][pack.mode])} ${unit(pack.mode)} 容量。`);
    }
    plan.days[date].demands.forEach(demand => { if ((assigned[demand.categoryId] || 0) > demand.qty) errors.push(`${categoryName(demand.categoryId, data)}分配量超过当日需求 ${num(demand.qty)} ${unit(demand.mode)}。`); });
    return [...new Set(errors)];
  }

  function createDemo(blank = false) {
    const data = { schema: 1, revision: 1, today: BASE_DATE, authenticated: true, categories: [ { id: "T1", mode: "TAG", name: "行人横穿" }, { id: "T2", mode: "TAG", name: "车辆切入" }, { id: "T3", mode: "TAG", name: "信号灯场景" }, { id: "R1", mode: "ROAD", name: "城市道路" }, { id: "R2", mode: "ROAD", name: "高速道路" }, { id: "R3", mode: "ROAD", name: "乡村道路" } ], drivers: [], vehicles: [], plans: [], logs: [] };
    if (blank) return data;
    const names = ["张三", "李四", "王建国", "刘海峰", "陈志远", "赵明", "周宇", "孙浩", "吴磊", "徐航", "郑凯", "林枫", "何伟", "马骏", "高鹏", "罗松", "梁晨", "宋洋", "唐毅", "许阳", "韩东", "冯涛", "曹斌", "彭越", "曾杰", "肖宁", "董力", "袁博", "潘锐", "邓峰"];
    for (let i = 0; i < 60; i++) data.drivers.push({ id: `D${String(i + 1).padStart(3, "0")}`, name: names[i % 30] + (i >= 30 ? " · 二组" : ""), phone: "", grade: i < 20 ? "HIGH" : i < 45 ? "MEDIUM" : "LOW", active: i !== 59, shifts: i % 8 === 7 ? [0, 1] : [0, 1, 2], unavailable: i === 15 || i === 47 ? [{ start: addDate(BASE_DATE, 1), end: addDate(BASE_DATE, 4), reason: "已登记请假" }] : [] });
    for (let i = 0; i < 24; i++) data.vehicles.push({ id: `V${String(i + 1).padStart(3, "0")}`, plate: `沪 A·${String(3201 + i)}`, name: i % 3 === 0 ? "采集 SUV" : "采集轿车", active: i !== 23, caps: SHIFTS.map((_, shift) => ({ TAG: 100 + (i % 3) * 20 - shift * 10, ROAD: 80 + (i % 3) * 10 - shift * 5 })), unavailable: i === 20 ? [{ start: addDate(BASE_DATE, 1), end: addDate(BASE_DATE, 5), reason: "定期保养" }] : [] });
    const demands = () => [{ categoryId: "T1", mode: "TAG", qty: 420 }, { categoryId: "T2", mode: "TAG", qty: 320 }, { categoryId: "T3", mode: "TAG", qty: 180 }, { categoryId: "R1", mode: "ROAD", qty: 180 }, { categoryId: "R2", mode: "ROAD", qty: 120 }];
    const plan = { id: "P001", name: "城市道路与场景采集 · 第 45 周", start: addDate(BASE_DATE, 1), end: addDate(BASE_DATE, 7), notes: "优先安排 TAG，城市道路与高速道路独立统计。", days: {} };
    datesBetween(plan.start, plan.end).forEach((date, index) => { const items = demands(); if (index === 3) items.forEach(item => { item.qty *= 12; }); plan.days[date] = { demands: items, draft: null, formal: null, history: [], stale: false, manual: false }; });
    data.plans.push(plan);
    for (const offset of [1, 2, 4]) { const date = addDate(BASE_DATE, offset); plan.days[date].draft = generatePacks(data, date, plan); }
    const first = plan.days[plan.start]; first.formal = first.draft.map(pack => snapshot(pack, data)); first.draft = null; first.history.push({ at: `${BASE_DATE} 09:12:00`, action: "首次确认", packs: copy(first.formal) });
    const pastDate = addDate(BASE_DATE, -1), past = { id: "P000", name: "周末常规采集", start: pastDate, end: pastDate, notes: "历史示例，只读查看。", days: { [pastDate]: { demands: demands(), draft: null, formal: null, history: [], stale: false } } };
    data.plans.push(past); past.days[pastDate].formal = generatePacks(data, pastDate, past).map(pack => snapshot(pack, data)); past.days[pastDate].history.push({ at: `${addDate(BASE_DATE, -2)} 15:30:00`, action: "首次确认", packs: copy(past.days[pastDate].formal) });
    data.logs = [{ id: "L3", at: `${BASE_DATE} 09:20:00`, action: "生成排班预览", origin: "Agent", success: true, detail: { 日期: addDate(BASE_DATE, 2), 计划: plan.name } }, { id: "L2", at: `${BASE_DATE} 09:12:00`, action: "确认正式排班", origin: "页面", success: true, detail: { 日期: plan.start, 任务包: first.formal.length, 通知: "未接入" } }, { id: "L1", at: `${BASE_DATE} 09:00:00`, action: "创建采集计划", origin: "页面", success: true, detail: { 计划: plan.name, 日期: `${plan.start} 至 ${plan.end}` } }];
    return data;
  }

  let state = readStorage() || createDemo();
  const ui = { page: "workbench", planId: "P001", date: addDate(state.today, 2), resourceTab: "drivers", resourceQuery: "", resourceGrade: "", resourceStatus: "", mode: "ALL", boardView: "grid", agentOpen: false, messages: [], pendingAgent: null, stale: false, dialogRevision: 0, planWizard: null, reportStart: addDate(state.today, -7), reportEnd: addDate(state.today, 7), logQuery: "", historyQuery: "" };
  let dialogContext = null;
  persist();
  function timestamp() { return `${state.today} ${new Date().toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}`; }
  function toast(text, error = false) { const region = $("#toast-region"); region.innerHTML = `<div class="toast ${error ? "error" : ""}">${icon(error ? "alert" : "check")}<span>${esc(text)}</span></div>`; clearTimeout(toast.timer); toast.timer = setTimeout(() => { region.innerHTML = ""; }, 4200); }
  function showError(text) { const error = $("#form-error"); if (error && $("#modal").open) { error.innerHTML = esc(text).replace(/\n/g, "<br>"); error.hidden = false; error.scrollIntoView({ block: "nearest" }); } else toast(text, true); }
  function commit(mutator, action, detail = {}, origin = "页面", expectedRevision = null) {
    const stored = readStorage();
    if (ui.stale || (stored && stored.revision !== state.revision) || (expectedRevision !== null && expectedRevision !== state.revision)) { showError("数据已发生变化，请载入最新内容并重新检查后提交。"); return false; }
    const next = copy(state);
    try { mutator(next); }
    catch (error) { state.logs.unshift({ id: uid("L"), at: timestamp(), action, origin, success: false, detail: { 原因: error.message } }); state.revision++; persist(); ui.dialogRevision = state.revision; render(); showError(error.message); return false; }
    next.logs.unshift({ id: uid("L"), at: timestamp(), action, origin, success: true, detail }); next.logs = next.logs.slice(0, 200); next.revision = state.revision + 1; state = next; persist(); ui.dialogRevision = state.revision; render(); return true;
  }
  function currentPlan() { return state.plans.find(plan => plan.id === ui.planId); }
  function currentDay() { return currentPlan()?.days[ui.date]; }
  function ensureSelection() { if (!currentPlan()) ui.planId = state.plans[0]?.id || ""; const plan = currentPlan(); if (plan && !plan.days[ui.date]) ui.date = Object.keys(plan.days).find(date => date > state.today) || plan.start; }
  function statusOf(day, date) { if (date <= state.today) return { label: "已锁定", tone: "neutral" }; if (day.formal) return { label: "已确认", tone: "green" }; if (day.draft !== null) return { label: day.stale ? "待校验" : "待确认", tone: day.stale ? "orange" : "blue" }; return { label: day.history.length ? "已取消 · 可重排" : "待排班", tone: "neutral" }; }
  function planStatus(plan) { const days = Object.values(plan.days), confirmed = days.filter(day => day.formal).length; return confirmed === days.length ? pill("全部确认", "green") : confirmed ? pill("部分确认", "blue") : days.some(day => day.history.length) ? pill("已取消", "orange") : pill("待排班"); }
  function heading(actions = "") { const [title, english, subtitle] = PAGES[ui.page]; return `<div class="page-heading"><div><div class="eyebrow">${english}</div><h1>${title}</h1><p class="heading-sub">${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`; }
  function metric(label, value, suffix, foot, hint, glyph, percent = null) { return `<div class="metric"><div class="metric-label">${label}</div><div class="metric-icon">${icon(glyph)}</div><div class="metric-number">${num(value)}<small>${suffix}</small></div><div class="metric-foot"><span>${foot}</span><span class="metric-accent">${hint}</span></div>${percent !== null ? `<span class="mini-track" style="width:${Math.min(100, percent)}%"></span>` : ""}</div>`; }
  function render() {
    ensureSelection();
    $$(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.view === ui.page));
    $("#breadcrumb-title").textContent = PAGES[ui.page][0]; $("#demo-date").textContent = state.today.replaceAll("-", "/");
    $("#draft-count").textContent = allDays().filter(({ date, day }) => date > state.today && day.draft !== null && !day.formal).length;
    $("#view").innerHTML = ({ workbench: renderWorkbench, plans: renderPlans, resources: renderResources, history: renderHistory, reports: renderReports, logs: renderLogs }[ui.page])();
    $("#stale-banner").hidden = !ui.stale;
    $("#agent-context").textContent = currentPlan() ? `当前上下文：${ui.date} · ${currentPlan().name}` : "当前没有计划，可以先创建采集计划。";
    if (!state.authenticated) renderLogin(); else $("#login-overlay").hidden = true;
  }

  function renderWorkbench() {
    const plan = currentPlan();
    const top = heading(btn("Agent 帮我排班", "agent-toggle", "", "", "spark") + btn("新建采集计划", "new-plan", "primary", "", "plus"));
    if (!plan) return top + `<div class="panel">${empty("先创建一份采集计划", "添加司机和车辆，设置每日需求，即可开始安排。也可以从演示设置载入示例。", "new-plan", "创建采集计划")}</div>`;
    const day = currentDay(), packs = day.formal || day.draft || [], dates = Object.keys(plan.days), locked = ui.date <= state.today, status = statusOf(day, ui.date);
    const tagDemand = total(day.demands, "TAG"), roadDemand = total(day.demands, "ROAD"), flat = packs.flatMap(pack => pack.items), tagAssigned = total(flat, "TAG"), roadAssigned = total(flat, "ROAD");
    const availableDrivers = state.drivers.filter(item => available(item, ui.date)).length, availableCars = state.vehicles.filter(item => available(item, ui.date)).length;
    const missing = tagAssigned < tagDemand || roadAssigned < roadDemand;
    const index = dates.indexOf(ui.date), weekStart = Math.floor(index / 7) * 7, visibleDates = dates.slice(weekStart, weekStart + 7);
    const dateStrip = visibleDates.map(date => { const info = statusOf(plan.days[date], date); return `<button class="day-button ${date === ui.date ? "active" : ""}" data-action="select-day" data-date="${date}" aria-label="查看 ${date} ${info.label}"><span class="weekday">周${weekday(date)}</span><span class="day-number">${date.slice(8)}</span><span class="day-status"><span class="status-dot"></span>${info.label}</span></button>`; }).join("");
    const noticeHtml = locked ? notice(`${icon("lock")} ${ui.date} 已锁定，仅供查看。当天突发情况线下处理。`) : day.stale ? notice("计划或资源已变更，草稿需要重新校验。确认前不会自动替换任何安排。", "") : missing && packs.length ? notice(`还有 ${num(tagDemand - tagAssigned)} 个 TAG、${num(round(roadDemand - roadAssigned))} km ROAD 未分配。可以确认有效安排，缺口不会自动滚入后续日期。`, "") : "";
    return top + `<div class="metrics">${metric("TAG 已分配", tagAssigned, "个", `需求 ${num(tagDemand)} 个`, tagAssigned === tagDemand ? "已全部分配" : `待分配 ${num(tagDemand - tagAssigned)}`, "grid", tagDemand ? tagAssigned / tagDemand * 100 : 0)}${metric("ROAD 已分配", roadAssigned, "km", `需求 ${num(roadDemand)} km`, roadAssigned === roadDemand ? "已全部分配" : `待分配 ${num(round(roadDemand - roadAssigned))}`, "truck", roadDemand ? roadAssigned / roadDemand * 100 : 0)}${metric("可用司机", availableDrivers, "人", `共 ${state.drivers.length} 位司机`, `${new Set(packs.map(pack => pack.driverId)).size} 人已安排`, "users")}${metric("可用车辆", availableCars, "辆", `共 ${state.vehicles.length} 辆车辆`, `${new Set(packs.map(pack => pack.vehicleId)).size} 辆已安排`, "truck")}</div>
    <section class="panel"><div class="panel-header"><div class="plan-picker"><span class="plan-icon">${icon("calendar")}</span><div><select id="plan-select" aria-label="选择采集计划">${state.plans.map(item => `<option value="${item.id}" ${item.id === plan.id ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select><p>${plan.start} — ${plan.end} · ${dates.length} 天 · 采集计划</p></div></div><div class="actions">${btn("需求详情", "plan-detail", "text", `data-id="${plan.id}"`)}<button class="icon-button" data-action="week-prev" aria-label="上一周" ${weekStart === 0 ? "disabled" : ""}>${icon("chevron")}</button><input type="date" id="work-date" aria-label="选择查看日期" value="${ui.date}" min="${plan.start}" max="${plan.end}"><button class="icon-button" data-action="week-next" aria-label="下一周" ${weekStart + 7 >= dates.length ? "disabled" : ""}>${icon("arrow")}</button></div></div><div class="date-strip">${dateStrip}</div></section>
    <div class="work-layout"><div>${noticeHtml}<section class="panel"><div class="toolbar"><div class="actions"><strong style="font-size:12px">${shortDate(ui.date)} 周${weekday(ui.date)}</strong>${pill(day.formal ? "正式排班" : "排班草稿", day.formal ? "green" : "blue")}${pill(status.label, status.tone)}</div><div class="actions">${!locked ? btn("新增任务包", "add-pack", "text", "", "plus") : ""}${day.formal ? btn("取消本日", "cancel-day", "small danger", locked ? "disabled" : "") : btn(day.draft !== null ? "重新生成" : "生成预览", "generate-day", "small", locked ? "disabled" : "", "spark")}${!day.formal ? btn("确认本日排班", "confirm-day", "primary small", locked || !packs.length ? "disabled" : "", "check") : ""}</div></div><div class="toolbar" style="padding-top:10px;padding-bottom:10px"><div class="segmented">${["ALL", "TAG", "ROAD"].map(mode => `<button class="segment ${ui.mode === mode ? "active" : ""}" data-action="mode-filter" data-mode="${mode}">${mode === "ALL" ? "全部模式" : mode}</button>`).join("")}</div><div class="board-meta"><span>${packs.length} 个任务包</span><div class="segmented"><button class="segment ${ui.boardView === "grid" ? "active" : ""}" data-action="board-view" data-layout="grid">车辆视图</button><button class="segment ${ui.boardView === "list" ? "active" : ""}" data-action="board-view" data-layout="list">明细列表</button></div></div></div>${packs.length ? renderBoard(packs, locked) : empty(locked ? "该日期没有正式安排" : "这一天，等待你来安排", locked ? "已锁定日期不再补排。" : "生成一份预览，或者手动新增任务包。预览不会占用正式资源。", locked ? "" : "generate-day", "生成排班预览", "grid")}<div class="board-footer">${icon(locked ? "lock" : "info")}<span>${locked ? "历史记录只读，保留当时的安排信息。" : day.formal ? "点击任务包调整；保存前展示全部差异，校验通过后生效。" : "草稿已在本地保存 · 点击任务包编辑 · 确认后才形成正式安排"}</span></div></section><div class="selection-bar"><span>连续多日，一次安排</span>${btn("批量生成预览", "batch-generate", "small", "", "spark")}<span class="spacer"></span>${btn("选择日期并批量确认", "batch-confirm", "small", "", "check")}</div></div><aside class="work-side">${renderDemandPanel(day, packs)}<section class="panel side-panel"><div class="side-title">${icon("spark")}本次排班规则</div>${["资源不足时，TAG 优先", "同一司机每天最多一个班次", "同车同日只执行一种模式", "同模式任务包直接累计容量"].map(text => `<div class="rule-item">${icon("check")}<span>${text}</span></div>`).join("")}<div class="priority-callout">效率优先：HIGH → MEDIUM → LOW<br>兼顾车辆利用率与同等级司机班次均衡</div></section><div class="notification-placeholder">${icon("bell")}<div><strong>司机通知未接入</strong><small>TODO · 本次确认不会触发发送</small></div></div></aside></div>`;
  }

  function renderBoard(packs, locked) {
    const filtered = packs.filter(pack => ui.mode === "ALL" || pack.mode === ui.mode);
    if (!filtered.length) return empty("此模式暂无任务包", "切换到其他模式，或新增一个任务包。", "", "", "grid");
    if (ui.boardView === "list") return `<div class="table-wrap"><table><thead><tr><th>车辆 / 班次</th><th>司机</th><th>模式</th><th>任务明细</th><th>操作</th></tr></thead><tbody>${filtered.map(pack => { const info = packInfo(pack); return `<tr><td>${esc(info.plate)}<small class="small-text"> / ${SHIFTS[pack.shift]}</small></td><td>${esc(info.name)} ${pill(info.grade, "neutral")}</td><td>${pill(pack.mode, pack.mode.toLowerCase())}</td><td class="wrap">${pack.items.map(item => `${esc(categoryName(item.categoryId))} ${num(item.qty)} ${unit(pack.mode)}`).join("<br>")}</td><td>${btn(locked ? "查看" : "编辑", "edit-pack", "text", `data-id="${pack.id}"`)}</td></tr>`; }).join("")}</tbody></table></div>`;
    const cars = [...new Set(filtered.map(pack => pack.vehicleId))];
    return `<div class="board"><div class="board-head"><span>车辆 / 模式</span>${SHIFTS.map((shift, index) => `<span>${["◔", "◑", "◕"][index]} ${shift}</span>`).join("")}</div>${cars.map(carId => { const carPacks = filtered.filter(pack => pack.vehicleId === carId), car = state.vehicles.find(item => item.id === carId), first = packInfo(carPacks[0]); return `<div class="board-row"><div class="vehicle-label"><strong>${esc(first.plate)}</strong><div>${pill(carPacks[0].mode, carPacks[0].mode.toLowerCase())}</div><small>${esc(car?.name || "采集车辆")}</small></div>${SHIFTS.map((_, shift) => { const pack = carPacks.find(item => item.shift === shift); if (!pack) return `<button class="empty-slot" data-action="add-pack" data-vehicle="${carId}" data-shift="${shift}" ${locked ? "disabled" : ""} aria-label="为 ${esc(first.plate)} ${SHIFTS[shift]}新增任务包">${locked ? "—" : "+ 安排"}</button>`; const info = packInfo(pack), amount = total(pack.items, pack.mode), capacity = pack.capacitySnapshot ?? car.caps[shift][pack.mode]; return `<button class="pack-card ${pack.mode.toLowerCase()}" data-action="edit-pack" data-id="${pack.id}" aria-label="${esc(info.plate)} ${SHIFTS[shift]} ${esc(info.name)}任务包"><div class="pack-title"><strong>${esc(info.name)}</strong><span class="grade-dot ${info.grade}">${info.grade === "HIGH" ? "H" : info.grade === "MEDIUM" ? "M" : "L"}</span></div><div class="pack-amount">${num(amount)}<small>${unit(pack.mode)}</small></div><div class="pack-types">${pack.items.map(item => esc(categoryName(item.categoryId))).join(" · ")}</div><div class="pack-track"><span style="width:${Math.min(100, amount / capacity * 100)}%"></span></div></button>`; }).join("")}</div>`; }).join("")}</div>`;
  }
  function packInfo(pack) { const driver = state.drivers.find(item => item.id === pack.driverId), car = state.vehicles.find(item => item.id === pack.vehicleId); return { name: pack.snapshot?.driverName || driver?.name || "已归档司机", grade: pack.snapshot?.grade || driver?.grade || "MEDIUM", plate: pack.snapshot?.plate || car?.plate || "已归档车辆" }; }
  function renderDemandPanel(day, packs) { const items = packs.flatMap(pack => pack.items); return `<section class="panel side-panel"><div class="side-title">${icon("list")}当日采集需求<span class="small-text" style="margin-left:auto">${day.demands.length} 类</span></div>${day.demands.map(demand => { const assigned = round(items.filter(item => item.categoryId === demand.categoryId).reduce((sum, item) => sum + item.qty, 0)), missing = round(demand.qty - assigned); return `<div class="demand-item ${demand.mode.toLowerCase()}"><header><span>${esc(categoryName(demand.categoryId))}</span><span class="amount">${num(assigned)} <span class="muted">/ ${num(demand.qty)}</span></span></header><div class="progress-track"><span style="width:${Math.min(100, assigned / demand.qty * 100)}%"></span></div><footer>${missing > 0 ? `待分配 ${num(missing)} ${unit(demand.mode)} · 可用班次或容量不足时保留缺口` : `已全部分配 · ${demand.mode}`}</footer></div>`; }).join("")}</section>`; }

  function renderPlans() {
    const query = (ui.planQuery || "").toLowerCase(), plans = state.plans.filter(plan => `${plan.name}${plan.id}${plan.start}${plan.end}`.toLowerCase().includes(query));
    return heading(btn("管理采集类别", "categories", "", "", "grid") + btn("新建采集计划", "new-plan", "primary", "", "plus")) + `<div class="filters" style="padding:0 0 18px"><label class="search-field">${icon("search")}<input id="plan-search" value="${esc(ui.planQuery || "")}" placeholder="搜索计划名称、日期" aria-label="搜索计划"></label><span class="small-text">共 ${state.plans.length} 份计划 · 同一日期仅归属一份计划</span></div>${plans.length ? `<div class="plan-list">${plans.map(plan => { const days = Object.values(plan.days), count = days.filter(day => day.formal).length; return `<article class="plan-card"><header><div><div class="plan-number">${esc(plan.id)} / COLLECTION PLAN</div><h3>${esc(plan.name)}</h3><div class="dates">${plan.start} — ${plan.end}</div></div>${planStatus(plan)}</header><p class="small-text">${esc(plan.notes || "暂无计划备注")}</p><div class="plan-summary"><div><strong>${days.length}<span class="small-text"> 天</span></strong><small>计划日期</small></div><div><strong>${num(days.reduce((sum, day) => sum + total(day.demands, "TAG"), 0))}</strong><small>TAG 需求 / 个</small></div><div><strong>${num(days.reduce((sum, day) => sum + total(day.demands, "ROAD"), 0))}</strong><small>ROAD 需求 / km</small></div></div><footer><span>${count} / ${days.length} 天已确认</span><div class="actions">${btn("查看需求", "plan-detail", "text", `data-id="${plan.id}"`)}${btn("进入排班", "open-plan", "small", `data-id="${plan.id}"`, "arrow")}</div></footer></article>`; }).join("")}</div>` : `<div class="panel">${empty("还没有采集计划", "从单日或一段连续日期开始，配置需要采集的类别和数量。", "new-plan", "创建计划")}</div>`}`;
  }

  function renderResources() {
    const drivers = ui.resourceTab === "drivers", list = drivers ? state.drivers : state.vehicles, query = ui.resourceQuery.toLowerCase(), date = ui.resourceDate || ui.date;
    const filtered = list.filter(item => `${item.name}${item.id}${item.plate || ""}`.toLowerCase().includes(query) && (!drivers || !ui.resourceGrade || item.grade === ui.resourceGrade) && (!ui.resourceStatus || (ui.resourceStatus === "active" ? available(item, date) : !available(item, date))));
    return heading(btn("管理采集类别", "categories", "", "", "grid") + btn(drivers ? "新增司机" : "新增车辆", "new-resource", "primary", "", "plus")) + `<div class="resource-tabs"><div class="segmented"><button class="segment ${drivers ? "active" : ""}" data-action="resource-tab" data-tab="drivers">${icon("users")} 司机 ${state.drivers.length}</button><button class="segment ${!drivers ? "active" : ""}" data-action="resource-tab" data-tab="vehicles">${icon("truck")} 车辆 ${state.vehicles.length}</button></div><span class="small-text">可用状态参考日期：${date}</span></div><section class="panel"><div class="filters"><label class="search-field">${icon("search")}<input id="resource-search" value="${esc(ui.resourceQuery)}" placeholder="${drivers ? "搜索姓名、司机编号" : "搜索车牌、车辆编号"}" aria-label="搜索资源"></label>${drivers ? `<select id="grade-filter" class="filter" aria-label="筛选效率等级"><option value="">全部效率等级</option>${Object.entries(GRADES).map(([grade, label]) => `<option value="${grade}" ${ui.resourceGrade === grade ? "selected" : ""}>${label}</option>`).join("")}</select>` : ""}<select id="resource-status" class="filter" aria-label="筛选可用状态"><option value="">全部状态</option><option value="active" ${ui.resourceStatus === "active" ? "selected" : ""}>当前可用</option><option value="inactive" ${ui.resourceStatus === "inactive" ? "selected" : ""}>不可用 / 停用</option></select><input type="date" id="resource-date" aria-label="资源可用日期" value="${date}"></div><div class="resource-table"><table><thead><tr><th>${drivers ? "司机" : "车辆"}</th><th>${drivers ? "效率等级" : "每班容量"}</th><th>${drivers ? "班次资格" : "车型"}</th><th>可用状态</th><th>${drivers ? "累计排班" : "安排班次"}</th><th>操作</th></tr></thead><tbody>${filtered.map(item => { const count = allDays().reduce((sum, { day }) => sum + (day.formal || []).filter(pack => drivers ? pack.driverId === item.id : pack.vehicleId === item.id).length, 0), off = item.unavailable.find(range => range.start <= date && range.end >= date); return `<tr><td><div class="person"><span class="avatar">${drivers ? esc(item.name[0]) : icon("truck")}</span><div><strong>${esc(drivers ? item.name : item.plate)}</strong><small>${item.id}</small></div></div></td><td>${drivers ? pill(`${GRADES[item.grade]} · ${item.grade}`, item.grade === "HIGH" ? "green" : item.grade === "MEDIUM" ? "orange" : "neutral") : `<div class="capacity-detail">TAG ${item.caps.map(cap => num(cap.TAG)).join(" / ")} 个<br>ROAD ${item.caps.map(cap => num(cap.ROAD)).join(" / ")} km</div>`}</td><td>${drivers ? item.shifts.map(index => SHIFTS[index]).join(" · ") : esc(item.name)}</td><td>${pill(!item.active ? "已停用" : off ? drivers ? "请假" : "维修" : "可用", available(item, date) ? "green" : "orange")}${off ? `<div class="small-text">${shortDate(off.start)}—${shortDate(off.end)}</div>` : ""}</td><td><span class="numeric">${count}</span> <span class="small-text">班</span></td><td><div class="table-actions">${btn("编辑", "edit-resource", "text", `data-id="${item.id}"`)}${btn(drivers ? "请假" : "维修", "unavailable", "text", `data-id="${item.id}"`)}<button class="icon-button" data-action="delete-resource" data-id="${item.id}" aria-label="删除${esc(drivers ? item.name : item.plate)}">${icon("trash")}</button></div></td></tr>`; }).join("")}</tbody></table>${!filtered.length ? empty("没有符合条件的资源", "调整筛选条件，或者新增一位司机、一辆车。", "new-resource", drivers ? "新增司机" : "新增车辆", drivers ? "users" : "truck") : ""}</div><div class="table-footer"><span>显示 ${filtered.length} / ${list.length} 条</span><span>历史引用保留 · 有引用资源可停用</span></div></section>`;
  }

  function renderHistory() {
    const query = ui.historyQuery.toLowerCase();
    const rows = allDays().filter(({ day }) => day.formal || day.history.length).filter(({ date, plan, day }) => {
      const packs = day.formal || day.history.at(-1)?.packs || [];
      const text = `${date}${plan.name}${packs.map(pack => { const info = packInfo(pack); return info.name + info.plate; }).join("")}`.toLowerCase();
      if (!text.includes(query) || (ui.hStart && date < ui.hStart) || (ui.hEnd && date > ui.hEnd)) return false;
      if (ui.hDriver && !packs.some(pack => pack.driverId === ui.hDriver)) return false;
      if (ui.hVehicle && !packs.some(pack => pack.vehicleId === ui.hVehicle)) return false;
      if (ui.hGrade && !packs.some(pack => packInfo(pack).grade === ui.hGrade)) return false;
      if (ui.hStatus && ui.hStatus !== (!day.formal ? "cancelled" : date <= state.today ? "locked" : "confirmed")) return false;
      const flat = (day.formal || []).flatMap(pack => pack.items);
      return !ui.hMissing || ["TAG", "ROAD"].some(mode => total(flat, mode) < total(day.demands, mode));
    }).sort((a, b) => b.date.localeCompare(a.date));
    const select = (id, label, values, current) => `<select id="${id}" class="filter" aria-label="${label}"><option value="">${label}</option>${values.map(([value, text]) => `<option value="${value}" ${current === value ? "selected" : ""}>${esc(text)}</option>`).join("")}</select>`;
    return heading(btn("返回排班工作台", "goto-workbench", "", "", "grid")) + notice("这里展示正式安排及变更历史。“已确认”表示安排生效，不代表已经采集完成。") + `<section class="panel">
      <div class="filters"><label class="search-field">${icon("search")}<input id="history-search" value="${esc(ui.historyQuery)}" placeholder="搜索日期、计划、司机或车牌" aria-label="搜索排班历史"></label>
      ${select("history-driver", "全部司机", state.drivers.map(item => [item.id, `${item.name} · ${item.id}`]), ui.hDriver)}
      ${select("history-vehicle", "全部车辆", state.vehicles.map(item => [item.id, item.plate]), ui.hVehicle)}
      ${select("history-grade", "全部效率等级", Object.entries(GRADES), ui.hGrade)}
      ${select("history-status", "全部确认状态", [["confirmed", "已确认"], ["locked", "已锁定"], ["cancelled", "已取消"]], ui.hStatus)}
      <input id="history-start" type="date" value="${ui.hStart || ""}" aria-label="历史开始日期"><span class="muted">—</span><input id="history-end" type="date" value="${ui.hEnd || ""}" aria-label="历史结束日期">
      <label class="history-filter-label"><input type="checkbox" id="history-missing" ${ui.hMissing ? "checked" : ""}>有未分配需求</label>${btn("重置", "history-filter-clear", "text")}</div>
      <div class="table-wrap"><table><thead><tr><th>采集日期</th><th>所属计划</th><th>任务包</th><th>TAG / ROAD 已分配</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.map(({ plan, date, day }) => {
        const flat = (day.formal || []).flatMap(pack => pack.items);
        return `<tr><td><strong class="numeric">${date}</strong><small class="small-text"> 周${weekday(date)}</small></td><td class="wrap">${esc(plan.name)}</td><td>${day.formal?.length || 0} <span class="small-text">个</span></td><td><span class="numeric">${num(total(flat, "TAG"))}</span> 个 / <span class="numeric">${num(total(flat, "ROAD"))}</span> km</td><td>${day.formal ? pill(date <= state.today ? "已锁定" : "已确认", date <= state.today ? "neutral" : "green") : pill("已取消", "orange")}</td><td><div class="table-actions">${btn("查看排班", "history-open", "text", `data-plan="${plan.id}" data-date="${date}"`)}${btn("变更记录", "day-history", "text", `data-plan="${plan.id}" data-date="${date}"`)}</div></td></tr>`;
      }).join("")}</tbody></table>${rows.length ? "" : empty("暂无符合条件的正式排班", "调整筛选条件，或先确认一份排班。")}</div><div class="table-footer"><span>符合条件 ${rows.length} 天</span><span>司机、车辆筛选定位包含该资源的日期</span></div></section>`;
  }

  function renderReports() {
    const rows = allDays().filter(({ date, day }) => day.formal && date >= ui.reportStart && date <= ui.reportEnd), packs = rows.flatMap(({ day }) => day.formal), flat = packs.flatMap(pack => pack.items), counts = {};
    packs.forEach(pack => { counts[pack.driverId] = (counts[pack.driverId] || 0) + 1; });
    const tagDemand = rows.reduce((sum, { day }) => sum + total(day.demands, "TAG"), 0), roadDemand = rows.reduce((sum, { day }) => sum + total(day.demands, "ROAD"), 0);
    const drivers = state.drivers.filter(item => counts[item.id]).sort((a, b) => counts[b.id] - counts[a.id]).slice(0, 8);
    const chart = mode => { const max = Math.max(1, ...rows.map(({ day }) => total(day.formal.flatMap(pack => pack.items), mode))); return rows.length ? `<div class="bar-chart">${rows.slice(-10).map(({ date, day }) => { const amount = total(day.formal.flatMap(pack => pack.items), mode); return `<div class="chart-column"><b>${num(amount)}</b><div class="bar ${mode.toLowerCase()}" style="height:${Math.max(2, amount / max * 130)}px"></div><small>${shortDate(date)}</small></div>`; }).join("")}</div><div class="chart-spacer"></div>` : empty("暂无正式统计数据", "先确认排班，再调整统计日期范围。", "", "", "chart"); };
    return heading(`<div class="inline-dates"><input type="date" id="report-start" aria-label="统计开始日期" value="${ui.reportStart}"><span class="muted">—</span><input type="date" id="report-end" aria-label="统计结束日期" value="${ui.reportEnd}"></div>`) + `<div class="stat-note">${icon("info")} 仅统计所选范围内的有效正式排班；草稿、已取消班次和实际采集结果不计入。</div><div class="metrics">${metric("TAG 分配量", total(flat, "TAG"), "个", `对应需求 ${num(tagDemand)} 个`, tagDemand ? `${Math.round(total(flat, "TAG") / tagDemand * 100)}% 分配率` : "暂无需求", "grid")}${metric("ROAD 分配量", total(flat, "ROAD"), "km", `对应需求 ${num(roadDemand)} km`, roadDemand ? `${Math.round(total(flat, "ROAD") / roadDemand * 100)}% 分配率` : "暂无需求", "truck")}${metric("正式班次", packs.length, "班", `${rows.length} 个采集日期`, "按有效安排统计", "calendar")}${metric("参与司机", Object.keys(counts).length, "人", `${new Set(packs.map(pack => pack.vehicleId)).size} 辆车已安排`, "不代表实际出勤", "users")}</div><div class="chart-grid"><section class="panel"><div class="panel-header"><h2>TAG 每日分配</h2>${pill("单位：个", "tag")}</div><div class="chart-body">${chart("TAG")}</div></section><section class="panel"><div class="panel-header"><h2>ROAD 每日分配</h2>${pill("单位：km", "road")}</div><div class="chart-body">${chart("ROAD")}</div></section><section class="panel"><div class="panel-header"><h2>司机排班次数</h2><small>所选范围 · 前 8 位</small></div><div class="chart-body">${drivers.length ? drivers.map(driver => `<div class="rank-row"><span class="rank-name">${esc(driver.name)}</span>${pill(driver.grade[0], driver.grade === "HIGH" ? "green" : "neutral")}<div class="progress-track"><span style="width:${counts[driver.id] / Math.max(...Object.values(counts)) * 100}%"></span></div><span class="rank-value">${counts[driver.id]} 班</span></div>`).join("") : `<p class="muted">暂无司机排班数据</p>`}</div></section><section class="panel"><div class="panel-header"><h2>车辆模式容量利用</h2><small>按各模式对应班次容量计算</small></div><div class="chart-body">${["TAG", "ROAD"].map(mode => { const chosen = packs.filter(pack => pack.mode === mode), capacity = chosen.reduce((sum, pack) => sum + (pack.capacitySnapshot ?? state.vehicles.find(car => car.id === pack.vehicleId)?.caps[pack.shift][mode] ?? 0), 0), assigned = total(chosen.flatMap(pack => pack.items), mode), percent = capacity ? Math.round(assigned / capacity * 100) : 0; return `<div class="demand-item ${mode.toLowerCase()}"><header><span>${mode} 已安排班次容量利用率</span><span class="numeric">${percent}%</span></header><div class="progress-track"><span style="width:${percent}%"></span></div><footer>已分配 ${num(assigned)} / 已安排班次容量 ${num(capacity)} ${unit(mode)}</footer></div>`; }).join("")}<div class="priority-callout">两种模式分别统计，不能将个数与公里数相加。车辆班次使用率按已安排 / 可用班次展示。</div><div class="rank-row"><span>车辆班次使用率</span><span class="rank-value" style="margin-left:auto">${(() => { const capacity = rows.reduce((sum, row) => sum + state.vehicles.filter(car => available(car, row.date)).reduce((value, car) => value + car.caps.filter(cap => cap.TAG > 0 || cap.ROAD > 0).length, 0), 0); return capacity ? Math.round(packs.length / capacity * 100) : 0; })()}%</span></div></div></section></div>`;
  }

  function renderLogs() {
    const query = ui.logQuery.toLowerCase(), logs = state.logs.filter(log => `${log.action}${log.origin}${log.at}${log.success ? "成功" : "失败"}${JSON.stringify(log.detail)}`.toLowerCase().includes(query));
    return heading(pill("关键写操作均留痕", "green")) + `<section class="panel"><div class="filters"><label class="search-field">${icon("search")}<input id="log-search" value="${esc(ui.logQuery)}" placeholder="搜索操作、日期、成功或失败" aria-label="搜索操作记录"></label><span class="small-text">车队长：周队长 · 页面与 Agent 共用权限</span></div><div class="timeline">${logs.length ? logs.map(log => `<article class="timeline-item"><span class="timeline-dot" style="${log.success ? "" : "background:#faeee7;color:#b3826b"}">${icon(log.success ? "check" : "alert")}</span><div class="timeline-content"><h3>${esc(log.action)} ${pill(log.success ? "成功" : "失败", log.success ? "green" : "red")}</h3><p>周队长 · ${esc(log.origin)}入口 · ${esc(Object.entries(log.detail || {}).slice(0, 2).map(([key, value]) => `${key}：${typeof value === "object" ? "查看详情" : value}`).join(" · "))}</p></div><div style="text-align:right"><div class="timeline-time">${esc(log.at)}</div>${btn("查看详情", "log-detail", "text", `data-id="${log.id}"`)}</div></article>`).join("") : empty("暂无操作记录", "创建计划、维护资源和确认排班后，操作会记录在这里。", "", "", "list")}</div></section>`;
  }

  function showDialog(title, description, body, footer, wide = false) {
    const dialog = $("#modal");
    if (dialog.open) dialog.close();
    dialog.classList.toggle("wide", wide); ui.dialogRevision = state.revision;
    $("#modal-content").innerHTML = `<div class="modal-header"><div><h2>${esc(title)}</h2><p>${esc(description)}</p></div><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭弹窗">${icon("close")}</button></div><div class="modal-body"><div id="form-error" class="form-error" hidden></div>${body}</div><div class="modal-footer">${footer}</div>`;
    dialog.showModal();
  }
  function closeDialog() { $("#modal").close(); dialogContext = null; }
  function confirmDialog(title, description, body, callback, label = "确认", danger = false) {
    dialogContext = { kind: "confirm", callback };
    showDialog(title, description, body, btn("返回", "close-dialog") + btn(label, "confirm-dialog", danger ? "danger" : "primary"));
  }
  function requireFuture(date) { if (!date || date <= state.today) throw new Error(`${date || "此日期"} 已锁定，只能操作 ${addDate(state.today, 1)} 及之后的日期。`); }
  function demandRows(items, group, modes = ["TAG", "ROAD"]) {
    return items.map((item, index) => `<div class="demand-row" data-demand-group="${group}">
      <select aria-label="任务模式" data-demand-mode>${modes.map(mode => `<option value="${mode}" ${item.mode === mode ? "selected" : ""}>${mode}</option>`).join("")}</select>
      <select aria-label="采集类别" data-demand-category>${state.categories.filter(category => category.mode === item.mode).map(category => `<option value="${category.id}" ${item.categoryId === category.id ? "selected" : ""}>${esc(category.name)}</option>`).join("")}</select>
      <input aria-label="需求数量" type="number" min="${item.mode === "TAG" ? "1" : ".001"}" step="${item.mode === "TAG" ? "1" : ".001"}" value="${item.qty}" data-demand-qty>
      <div class="demand-row-actions"><button class="icon-button" data-action="move-demand" data-group="${group}" data-index="${index}" data-direction="-1" aria-label="上移此需求" ${index === 0 ? "disabled" : ""}>↑</button><button class="icon-button" data-action="move-demand" data-group="${group}" data-index="${index}" data-direction="1" aria-label="下移此需求" ${index === items.length - 1 ? "disabled" : ""}>↓</button><button class="icon-button" data-action="remove-demand" data-group="${group}" data-index="${index}" aria-label="删除此需求">${icon("close")}</button></div>
    </div>`).join("");
  }
  function readDemands(group) { return $$(`[data-demand-group="${group}"]`).map(row => ({ mode: $("[data-demand-mode]", row).value, categoryId: $("[data-demand-category]", row).value, qty: Number($("[data-demand-qty]", row).value) })); }
  function validateDemands(items) {
    if (!items.length || !items.some(item => item.qty > 0)) throw new Error("每个采集日期至少需要一项正数需求。");
    const seen = new Set();
    items.forEach(item => {
      if (!state.categories.some(category => category.id === item.categoryId && category.mode === item.mode)) throw new Error("请先选择有效的采集类别。");
      if (seen.has(item.categoryId)) throw new Error("同一天的同一采集类别请合并为一项需求。");
      seen.add(item.categoryId);
      if (!Number.isFinite(item.qty) || item.qty <= 0 || (item.mode === "TAG" ? !Number.isInteger(item.qty) : Math.abs(item.qty * 1000 - Math.round(item.qty * 1000)) > .000001)) throw new Error("Tag 数量必须是正整数，道路公里数必须大于零且最多三位小数。");
    });
  }
  function firstCategory(mode = "TAG") { return state.categories.find(item => item.mode === mode)?.id || ""; }
  function validateDateRange(start, end, excludePlan = "") {
    requireFuture(start); if (!end || end < start) throw new Error("结束日期不能早于开始日期。");
    const conflicts = state.plans.filter(plan => plan.id !== excludePlan && plan.start <= end && plan.end >= start);
    if (conflicts.length) throw new Error(`日期重叠：${conflicts.map(plan => `${plan.name}（${plan.start}—${plan.end}）`).join("；")}。同一天只能属于一个计划。`);
  }
  function openPlanWizard(id = "") {
    const existing = state.plans.find(plan => plan.id === id);
    if (existing && (existing.start <= state.today || Object.values(existing.days).some(day => day.history.length || day.formal))) return toast("已有正式记录的计划请按日期调整需求，不能整体迁移日期。", true);
    const start = existing?.start || addDate(state.plans.reduce((max, plan) => plan.end > max ? plan.end : max, state.today), 1);
    const base = existing ? copy(existing.days[existing.start].demands) : [{ categoryId: firstCategory("TAG"), mode: "TAG", qty: 200 }, { categoryId: firstCategory("ROAD"), mode: "ROAD", qty: 100 }];
    ui.planWizard = { step: 0, id, name: existing?.name || "", start, end: existing?.end || addDate(start, 2), notes: existing?.notes || "", demands: base, overrides: {}, overrideDate: start, useOverride: false };
    if (existing) Object.entries(existing.days).forEach(([date, day]) => { if (JSON.stringify(day.demands) !== JSON.stringify(base)) ui.planWizard.overrides[date] = copy(day.demands); });
    drawPlanWizard();
  }
  function captureWizard() {
    const wizard = ui.planWizard;
    if (wizard.step === 0) { wizard.name = $("#plan-name").value.trim(); wizard.start = $("#plan-start").value; wizard.end = $("#plan-end").value; wizard.notes = $("#plan-notes").value.trim(); }
    if (wizard.step === 1) { wizard.demands = readDemands("base"); if (wizard.useOverride) wizard.overrides[wizard.overrideDate] = readDemands("override"); }
  }
  function drawPlanWizard() {
    const wizard = ui.planWizard;
    const steps = `<div class="stepper">${["计划信息", "每日需求", "核对并创建"].map((text, index) => `${index ? "<i></i>" : ""}<span class="${wizard.step === index ? "active" : ""}"><b>${index + 1}</b>${text}</span>`).join("")}</div>`;
    let body = "";
    if (wizard.step === 0) body = `<form id="plan-info-form"><div class="form-grid"><label class="form-field full"><span>计划名称 *</span><input id="plan-name" required placeholder="例如：11 月城市道路与场景采集" value="${esc(wizard.name)}"></label><label class="form-field"><span>开始日期 *</span><input type="date" id="plan-start" required min="${addDate(state.today, 1)}" value="${wizard.start}"></label><label class="form-field"><span>结束日期 *</span><input type="date" id="plan-end" required min="${addDate(state.today, 1)}" value="${wizard.end}"></label><label class="form-field full"><span>计划备注</span><textarea id="plan-notes" placeholder="填写采集安排的补充说明">${esc(wizard.notes)}</textarea></label></div></form><div class="priority-callout">日期包含首尾两天。同一天只能归属一个计划，今天及过去日期只供查询。</div>`;
    if (wizard.step === 1) body = `<div class="form-section-title"><span>默认每日需求</span>${btn("添加需求", "add-demand", "text", 'data-group="base"', "plus")}</div><p class="small-text">按下列顺序分配；TAG 优先。多种同模式任务可放入同一个任务包。</p><div id="base-demands">${demandRows(wizard.demands, "base")}</div><div class="subtle-separator"></div><label class="switch-label"><input type="checkbox" id="override-enabled" ${wizard.useOverride ? "checked" : ""}>为指定日期设置独立需求</label>${wizard.useOverride ? `<div class="form-section-title"><select id="override-date" class="filter" aria-label="独立需求日期">${datesBetween(wizard.start, wizard.end).map(date => `<option value="${date}" ${wizard.overrideDate === date ? "selected" : ""}>${date} 周${weekday(date)}${wizard.overrides[date] ? " · 已独立配置" : ""}</option>`).join("")}</select>${btn("添加需求", "add-demand", "text", 'data-group="override"', "plus")}</div><div id="override-demands">${demandRows(wizard.overrides[wizard.overrideDate] || wizard.demands, "override")}</div><p class="small-text">此处内容替换所选日期的全部默认需求，其他日期保持不变。</p>` : `<p class="small-text" style="margin-top:9px">已独立配置 ${Object.keys(wizard.overrides).length} 个日期。未设置的日期沿用默认需求。</p>`}`;
    if (wizard.step === 2) {
      const days = datesBetween(wizard.start, wizard.end), items = days.flatMap(date => wizard.overrides[date] || wizard.demands);
      body = `<div class="review-list"><div><span>计划名称</span><strong>${esc(wizard.name)}</strong></div><div><span>采集日期</span><strong>${wizard.start} 至 ${wizard.end}</strong></div><div><span>日期配置</span><strong>${days.length} 天 · ${Object.keys(wizard.overrides).length} 天独立需求</strong></div><div><span>备注</span><strong>${esc(wizard.notes || "—")}</strong></div></div><div class="summary-grid"><div class="summary-box"><strong>${days.length}</strong><span>采集日期 / 天</span></div><div class="summary-box"><strong>${num(total(items, "TAG"))}</strong><span>TAG 总需求 / 个</span></div><div class="summary-box"><strong>${num(total(items, "ROAD"))}</strong><span>ROAD 总需求 / km</span></div></div>${notice("保存仅创建采集需求，不会自动生成或确认正式排班。")}`;
    }
    dialogContext = { kind: "plan-wizard" };
    showDialog(wizard.id ? "编辑采集计划" : "新建采集计划", "把需求说清楚，剩下的交给排班工作台。", steps + body, btn(wizard.step ? "上一步" : "取消", wizard.step ? "wizard-back" : "close-dialog") + btn(wizard.step === 2 ? wizard.id ? "保存计划" : "确认创建计划" : "下一步", wizard.step === 2 ? "wizard-save" : "wizard-next", "primary", "", wizard.step === 2 ? "check" : "arrow"));
  }
  function wizardNext() {
    try {
      if (ui.planWizard.step === 0 && !$("#plan-info-form").reportValidity()) return;
      captureWizard(); const wizard = ui.planWizard;
      if (wizard.step === 0) { if (!wizard.name) throw new Error("请填写计划名称。"); validateDateRange(wizard.start, wizard.end, wizard.id); wizard.overrideDate = wizard.start; Object.keys(wizard.overrides).forEach(date => { if (date < wizard.start || date > wizard.end) delete wizard.overrides[date]; }); }
      else { validateDemands(wizard.demands); Object.values(wizard.overrides).forEach(validateDemands); }
      wizard.step++; drawPlanWizard();
    } catch (error) { showError(error.message); }
  }
  function saveWizard() {
    const wizard = copy(ui.planWizard), id = wizard.id || uid("P");
    const success = commit(data => {
      validateDateRange(wizard.start, wizard.end, wizard.id); validateDemands(wizard.demands); Object.values(wizard.overrides).forEach(validateDemands);
      const previous = data.plans.find(plan => plan.id === id), days = {};
      datesBetween(wizard.start, wizard.end).forEach(date => { const demands = copy(wizard.overrides[date] || wizard.demands), old = previous?.days[date]; days[date] = old ? { ...old, demands, stale: old.draft !== null && JSON.stringify(old.demands) !== JSON.stringify(demands) } : { demands, draft: null, formal: null, history: [], stale: false, manual: false }; });
      const plan = { id, name: wizard.name, start: wizard.start, end: wizard.end, notes: wizard.notes, days };
      if (previous) data.plans[data.plans.findIndex(item => item.id === id)] = plan; else data.plans.unshift(plan);
    }, wizard.id ? "修改采集计划" : "创建采集计划", { 计划: wizard.name, 日期: `${wizard.start} 至 ${wizard.end}` });
    if (success) { ui.planId = id; ui.date = wizard.start; closeDialog(); setPage("plans"); toast(wizard.id ? "计划已更新，相关草稿需重新校验" : "采集计划已创建，可以进入排班"); }
  }
  function showPlanDetail(id) {
    const plan = state.plans.find(item => item.id === id); if (!plan) return;
    const hasHistory = Object.values(plan.days).some(day => day.formal || day.history.length);
    dialogContext = { kind: "plan-detail", planId: id };
    showDialog(plan.name, `${plan.start} — ${plan.end} · ${Object.keys(plan.days).length} 天`, `<div class="detail-header">${planStatus(plan)}<div class="actions">${btn("编辑计划", "edit-plan", "small", `data-id="${id}" ${hasHistory || plan.start <= state.today ? "disabled" : ""}`, "edit")}${btn("删除计划", "delete-plan", "small danger", `data-id="${id}" ${hasHistory || plan.start <= state.today ? "disabled" : ""}`, "trash")}</div></div>${hasHistory ? notice("已有正式记录的计划保留历史。未来日期可独立调整需求，或在工作台取消当日安排。") : ""}${Object.entries(plan.days).map(([date, day]) => { const info = statusOf(day, date); return `<div class="day-detail"><header><strong>${date} 周${weekday(date)}</strong><div class="actions">${pill(info.label, info.tone)}${btn("调整需求", "edit-day-demand", "text", `data-plan="${id}" data-date="${date}" ${date <= state.today ? "disabled" : ""}`)}</div></header><p>${day.demands.map(item => `${esc(categoryName(item.categoryId))} ${num(item.qty)} ${unit(item.mode)}`).join(" · ")}</p></div>`; }).join("")}`, btn("关闭", "close-dialog") + btn("进入排班工作台", "open-plan", "primary", `data-id="${id}"`, "arrow"), true);
  }
  function showDemandEditor(planId, date) {
    const plan = state.plans.find(item => item.id === planId); if (!plan || date <= state.today) return toast("该日期已锁定", true);
    dialogContext = { kind: "day-demand", planId, date, original: copy(plan.days[date].demands) };
    showDialog("调整当日需求", `${date} · ${plan.name}`, `${plan.days[date].formal ? notice("此日已有正式排班。保存时将一并校验，不能把目标量降低至已分配量以下。") : ""}<div class="form-section-title"><span>采集类别及目标量</span>${btn("添加需求", "add-demand", "text", 'data-group="day"', "plus")}</div><div id="day-demands">${demandRows(plan.days[date].demands, "day")}</div><div id="demand-diff"></div>`, btn("取消", "close-dialog") + btn("保存并生效", "save-day-demand", "primary", "", "check"));
    updateDemandDiff();
  }
  function demandText(items) { return items.map(item => `${categoryName(item.categoryId)} ${num(item.qty)} ${unit(item.mode)}`).join("；") || "无"; }
  function diffBlock(rows) { return `<div class="diff"><header>完整变更摘要 · 仅生效你确认的内容</header>${rows.length ? rows.map(row => `<div class="diff-row"><span>${esc(row[0])}</span><span class="diff-old">${esc(row[1])}</span>${icon("arrow")}<span class="diff-new">${esc(row[2])}</span></div>`).join("") : '<div class="diff-row" style="display:block">尚未修改任何内容</div>'}</div>`; }
  function updateDemandDiff() { if (!$("#demand-diff")) return; const before = demandText(dialogContext.original), after = demandText(readDemands("day")); $("#demand-diff").innerHTML = diffBlock(before === after ? [] : [["当日需求", before, after]]); }
  function saveDayDemands() {
    const context = dialogContext, items = readDemands("day");
    if (commit(data => { requireFuture(context.date); validateDemands(items); const plan = data.plans.find(item => item.id === context.planId), day = plan.days[context.date]; day.demands = items; if (day.formal) { const errors = validatePacks(data, context.date, plan, day.formal, true); if (errors.length) throw new Error(errors.join("\n")); day.history.push({ at: timestamp(), action: "修改当日需求", packs: copy(day.formal), demands: copy(items) }); } else if (day.draft !== null) day.stale = true; }, "修改采集需求", { 日期: context.date, 修改前: demandText(context.original), 修改后: demandText(items) })) { closeDialog(); toast("当日需求已保存，其他日期不受影响"); }
  }

  function invalidateDrafts(data) { allDays(data).forEach(({ day }) => { if (day.draft !== null && !day.formal) day.stale = true; }); }
  function validateFutureFormal(data) { const failures = []; allDays(data).filter(({ date, day }) => date > data.today && day.formal).forEach(({ plan, date, day }) => { const errors = validatePacks(data, date, plan, day.formal, true); if (errors.length) failures.push(`${date}：${errors[0]}`); }); if (failures.length) throw new Error(`变更会使正式排班失效，请先调整受影响日期。\n${failures.join("\n")}`); }
  function resourceById(id) { return state.drivers.find(item => item.id === id) || state.vehicles.find(item => item.id === id); }
  function resourceReferenced(id) { return allDays().some(({ day }) => [...(day.formal || []), ...(day.draft || []), ...day.history.flatMap(history => history.packs || [])].some(pack => pack.driverId === id || pack.vehicleId === id)); }
  function showResourceEditor(id = "") {
    const drivers = id ? id.startsWith("D") : ui.resourceTab === "drivers", original = id ? copy(resourceById(id)) : null;
    const item = original || (drivers ? { name: "", phone: "", grade: "MEDIUM", active: true, shifts: [0, 1, 2], unavailable: [] } : { plate: "", name: "采集车辆", active: true, caps: SHIFTS.map(() => ({ TAG: 100, ROAD: 80 })), unavailable: [] });
    dialogContext = { kind: "resource", drivers, original, id };
    const body = `<form id="resource-form"><div class="form-grid">${drivers ? `<label class="form-field"><span>司机姓名 *</span><input id="resource-name" value="${esc(item.name)}" required placeholder="允许重名，编号唯一"></label><label class="form-field"><span>联系方式（选填）</span><input id="resource-phone" value="${esc(item.phone)}" placeholder="填写联系电话"></label><label class="form-field"><span>效率等级</span><select id="resource-grade">${Object.entries(GRADES).map(([grade, label]) => `<option value="${grade}" ${item.grade === grade ? "selected" : ""}>${grade} · ${label}</option>`).join("")}</select><small>仅影响分配优先级，不改变车辆容量。</small></label>` : `<label class="form-field"><span>车牌号 *</span><input id="resource-plate" value="${esc(item.plate)}" required placeholder="例如：沪 A·88888"></label><label class="form-field"><span>车辆名称</span><input id="resource-name" value="${esc(item.name)}" placeholder="例如：采集 SUV"></label>`}<label class="form-field"><span>启用状态</span><select id="resource-active"><option value="true" ${item.active ? "selected" : ""}>启用</option><option value="false" ${!item.active ? "selected" : ""}>停用</option></select></label></div>${drivers ? `<div class="form-section-title">班次资格</div><div class="check-row">${SHIFTS.map((shift, index) => `<label><input type="checkbox" name="qualification" value="${index}" ${item.shifts.includes(index) ? "checked" : ""}>${shift}</label>`).join("")}</div>` : `<div class="form-section-title">车辆班次容量</div><div class="capacity-inputs"><span>班次</span><span>TAG / 个</span><span>ROAD / km</span></div>${SHIFTS.map((shift, index) => `<div class="capacity-inputs"><span>${shift}</span><input aria-label="${shift} TAG容量" name="cap-TAG-${index}" type="number" min="0" step="1" value="${item.caps[index].TAG}" required><input aria-label="${shift} ROAD容量" name="cap-ROAD-${index}" type="number" min="0" step=".001" value="${item.caps[index].ROAD}" required></div>`).join("")}<p class="small-text">容量为 0 表示该班次不能执行对应模式。</p>`}</form><div id="resource-diff"></div>`;
    showDialog(`${id ? "编辑" : "新增"}${drivers ? "司机" : "车辆"}`, id ? `${id} · 历史记录保留当时信息` : "保存前检查信息，实际通知保持未接入。", body, btn("取消", "close-dialog") + btn(id ? "保存并生效" : "确认新增", "save-resource", "primary", "", "check"));
    updateResourceDiff();
  }
  function readResourceForm() {
    const context = dialogContext, base = context.original || { unavailable: [] }, drivers = context.drivers;
    const item = { ...copy(base), name: $("#resource-name").value.trim(), active: $("#resource-active").value === "true" };
    if (drivers) Object.assign(item, { phone: $("#resource-phone").value.trim(), grade: $("#resource-grade").value, shifts: $$("[name=qualification]:checked").map(input => Number(input.value)) });
    else { item.plate = $("#resource-plate").value.trim(); item.caps = SHIFTS.map((_, index) => ({ TAG: Number($(`[name=cap-TAG-${index}]`).value), ROAD: Number($(`[name=cap-ROAD-${index}]`).value) })); }
    return item;
  }
  function resourceDescription(item, drivers) { if (!item) return {}; return drivers ? { 姓名: item.name, 电话: item.phone || "未填写", 效率: item.grade, 状态: item.active ? "启用" : "停用", 资格: item.shifts.map(index => SHIFTS[index]).join(" / ") || "无" } : { 车牌: item.plate, 名称: item.name, 状态: item.active ? "启用" : "停用", ...Object.fromEntries(item.caps.map((cap, index) => [SHIFTS[index], `TAG ${cap.TAG} 个 / ROAD ${cap.ROAD} km`])) }; }
  function updateResourceDiff() { if (!$("#resource-diff")) return; const before = resourceDescription(dialogContext.original, dialogContext.drivers), after = resourceDescription(readResourceForm(), dialogContext.drivers); $("#resource-diff").innerHTML = diffBlock(Object.keys(after).filter(key => before[key] !== after[key]).map(key => [key, before[key] || "—", after[key]])); }
  function saveResource() {
    if (!$("#resource-form").reportValidity()) return;
    const context = dialogContext, item = readResourceForm(), id = context.id || uid(context.drivers ? "D" : "V"); item.id = id;
    const ok = commit(data => {
      if (context.drivers && !item.name) throw new Error("司机姓名不能为空。");
      if (!context.drivers) {
        if (!item.plate) throw new Error("车牌号不能为空。");
        if (data.vehicles.some(car => car.id !== id && car.plate.replace(/\s/g, "").toUpperCase() === item.plate.replace(/\s/g, "").toUpperCase())) throw new Error("该车牌号已存在，请勿重复创建。");
        if (item.caps.some(cap => !Number.isInteger(cap.TAG) || cap.TAG < 0 || !Number.isFinite(cap.ROAD) || cap.ROAD < 0 || Math.abs(cap.ROAD * 1000 - Math.round(cap.ROAD * 1000)) > .000001)) throw new Error("Tag 容量为非负整数，道路容量最多三位小数。");
      }
      const list = context.drivers ? data.drivers : data.vehicles, index = list.findIndex(entry => entry.id === id);
      if (index >= 0) list[index] = item; else list.push(item);
      validateFutureFormal(data); invalidateDrafts(data);
    }, `${context.id ? "修改" : "新增"}${context.drivers ? "司机" : "车辆"}`, { 对象: context.drivers ? item.name : item.plate, 修改前: resourceDescription(context.original, context.drivers), 修改后: resourceDescription(item, context.drivers) });
    if (ok) { closeDialog(); toast("资源已保存，相关草稿确认前将重新校验"); }
  }
  function showUnavailable(id) {
    const item = resourceById(id), drivers = id.startsWith("D"); if (!item) return;
    dialogContext = { kind: "unavailable", id, drivers };
    showDialog(drivers ? "登记司机请假" : "登记车辆维修", `${drivers ? item.name : item.plate} · 不可用时间按整日计算`, `<form id="unavailable-form"><div class="form-grid"><label class="form-field"><span>开始日期</span><input id="off-start" type="date" value="${(ui.resourceDate || ui.date) > state.today ? ui.resourceDate || ui.date : addDate(state.today, 1)}" min="${addDate(state.today, 1)}" required></label><label class="form-field"><span>结束日期</span><input id="off-end" type="date" value="${(ui.resourceDate || ui.date) > state.today ? ui.resourceDate || ui.date : addDate(state.today, 1)}" min="${addDate(state.today, 1)}" required></label><label class="form-field full"><span>原因（选填）</span><input id="off-reason" placeholder="例如：事假 / 定期保养"></label></div></form><div class="form-section-title">已有记录</div>${item.unavailable.length ? item.unavailable.map((range, index) => `<div class="catalog-row"><div class="catalog-name"><strong class="numeric">${range.start} — ${range.end}</strong><div class="small-text">${esc(range.reason || "未填写原因")}</div></div>${btn("移除", "remove-unavailable", "text", `data-id="${id}" data-index="${index}" ${range.start <= state.today ? "disabled" : ""}`)}</div>`).join("") : '<p class="small-text">暂无不可用记录</p>'}<div class="priority-callout">若影响未来正式排班，登记将被拒绝。请先调整排班；当天突发情况线下处理。</div>`, btn("取消", "close-dialog") + btn("确认登记", "save-unavailable", "primary", "", "check"));
  }
  function saveUnavailable() {
    if (!$("#unavailable-form").reportValidity()) return;
    const { id, drivers } = dialogContext, range = { start: $("#off-start").value, end: $("#off-end").value, reason: $("#off-reason").value.trim() };
    if (commit(data => { requireFuture(range.start); if (range.end < range.start) throw new Error("结束日期不能早于开始日期。"); const item = (drivers ? data.drivers : data.vehicles).find(entry => entry.id === id); item.unavailable.push(range); validateFutureFormal(data); invalidateDrafts(data); }, drivers ? "登记司机请假" : "登记车辆维修", { 资源: id, ...range })) { closeDialog(); toast("不可用日期已登记"); }
  }

  function packValues(pack) {
    if (!pack) return {};
    const info = packInfo(pack);
    return { 车辆: info.plate, 司机: `${info.name} (${pack.driverId})`, 班次: SHIFTS[pack.shift], 模式: pack.mode, 任务明细: demandText(pack.items) };
  }
  function showPackEditor(id = "", vehicleId = "", shift = null) {
    const plan = currentPlan(), day = currentDay(); if (!day) return;
    const existing = (day.formal || day.draft || []).find(pack => pack.id === id), locked = ui.date <= state.today;
    if (locked) { showDialog("查看历史任务包", `${ui.date} · 历史信息只读`, `<div class="review-list">${Object.entries(packValues(existing)).map(([key, value]) => `<div><span>${key}</span><strong>${esc(value)}</strong></div>`).join("")}</div>${notice("采集日期已经到来，不能修改或补排。")}`, btn("关闭", "close-dialog")); return; }
    const current = day.formal || day.draft || [], assigned = current.flatMap(pack => pack.items);
    const remaining = demand => round(demand.qty - assigned.filter(item => item.categoryId === demand.categoryId).reduce((sum, item) => sum + item.qty, 0));
    const mode = existing?.mode || current.find(pack => pack.vehicleId === vehicleId)?.mode || day.demands.find(demand => remaining(demand) > 0)?.mode || day.demands[0].mode;
    const car = state.vehicles.find(item => item.id === vehicleId) || state.vehicles.find(item => available(item, ui.date) && !current.some(pack => pack.vehicleId === item.id && pack.mode !== mode) && item.caps.some((cap, index) => cap[mode] > 0 && !current.some(pack => pack.vehicleId === item.id && pack.shift === index)));
    const chosenShift = shift ?? car?.caps.findIndex((cap, index) => cap[mode] > 0 && !current.some(pack => pack.vehicleId === car.id && pack.shift === index)) ?? 0;
    const driver = state.drivers.find(item => available(item, ui.date) && item.shifts.includes(chosenShift) && !current.some(pack => pack.driverId === item.id));
    const demand = day.demands.find(item => item.mode === mode && remaining(item) > 0) || day.demands.find(item => item.mode === mode);
    const pack = existing ? copy(existing) : { id: uid("K"), vehicleId: car?.id || "", driverId: driver?.id || "", shift: chosenShift, mode, items: [{ categoryId: demand?.categoryId || "", mode, qty: Math.min(1, Math.max(mode === "TAG" ? 1 : .001, demand ? remaining(demand) : 1)) }] };
    dialogContext = { kind: "pack", planId: plan.id, date: ui.date, original: existing ? copy(existing) : null, working: pack, formal: !!day.formal };
    drawPackEditor();
  }
  function drawPackEditor() {
    const context = dialogContext, pack = context.working, plan = state.plans.find(item => item.id === context.planId), date = context.date;
    const used = (plan.days[date].formal || plan.days[date].draft || []).filter(item => item.id !== pack.id).map(item => item.driverId);
    const body = `<form id="pack-form"><div class="form-grid"><label class="form-field"><span>车辆</span><select id="pack-vehicle" required><option value="">请选择车辆</option>${state.vehicles.map(car => `<option value="${car.id}" ${pack.vehicleId === car.id ? "selected" : ""} ${!available(car, date) ? "disabled" : ""}>${esc(car.plate)} · ${car.id}${available(car, date) ? "" : " · 不可用"}</option>`).join("")}</select></label><label class="form-field"><span>班次</span><select id="pack-shift">${SHIFTS.map((label, index) => `<option value="${index}" ${pack.shift === index ? "selected" : ""}>${label}</option>`).join("")}</select></label><label class="form-field"><span>司机</span><select id="pack-driver" required><option value="">请选择司机</option>${state.drivers.map(driver => `<option value="${driver.id}" ${pack.driverId === driver.id ? "selected" : ""} ${!available(driver, date) || used.includes(driver.id) ? "disabled" : ""}>${esc(driver.name)} · ${driver.grade} · ${driver.id}${used.includes(driver.id) ? " · 本日已安排" : !available(driver, date) ? " · 不可用" : ""}</option>`).join("")}</select></label><label class="form-field"><span>任务模式</span><select id="pack-mode">${["TAG", "ROAD"].map(mode => `<option value="${mode}" ${mode === pack.mode ? "selected" : ""} ${plan.days[date].demands.some(item => item.mode === mode) ? "" : "disabled"}>${mode}</option>`).join("")}</select></label></div><div class="form-section-title"><span>任务包明细</span>${btn("添加类别", "pack-add-item", "text", "", "plus")}</div><div id="pack-items">${pack.items.map((item, index) => `<div class="demand-row pack-demand-row" style="grid-template-columns:minmax(0,1fr) 120px 28px"><select data-pack-category aria-label="任务包采集类别">${plan.days[date].demands.filter(demand => demand.mode === pack.mode).map(demand => `<option value="${demand.categoryId}" ${item.categoryId === demand.categoryId ? "selected" : ""}>${esc(categoryName(demand.categoryId))} · 目标 ${num(demand.qty)}</option>`).join("")}</select><input data-pack-qty aria-label="任务包数量" type="number" min="${pack.mode === "TAG" ? 1 : .001}" step="${pack.mode === "TAG" ? 1 : .001}" value="${item.qty}" required><button class="icon-button" data-action="pack-remove-item" data-index="${index}" aria-label="移除此任务项">${icon("close")}</button></div>`).join("")}</div><div id="pack-capacity" class="capacity-total"></div></form><div id="pack-diff"></div>${context.formal ? '<div class="priority-callout">正式修改按单日生效。保存前原排班仍有效；任一约束不通过，保留完整原安排。</div>' : ""}`;
    showDialog(context.original ? context.formal ? "调整正式任务包" : "编辑预览任务包" : "新增任务包", `${date} · ${plan.name}`, body, `${context.original ? btn("删除任务包", "delete-pack", "danger", `data-id="${pack.id}"`) : ""}<span class="footer-note">${context.formal ? "仅生效你确认的全部变更" : "保存草稿，不占用正式资源"}</span>${btn("取消", "close-dialog")}${btn(context.formal ? "保存并生效" : "保存草稿", "save-pack", "primary", "", "check")}`, true);
    updatePackDiff();
  }
  function readPackForm() {
    const mode = $("#pack-mode").value, pack = { ...copy(dialogContext.working), vehicleId: $("#pack-vehicle").value, driverId: $("#pack-driver").value, shift: Number($("#pack-shift").value), mode, items: [] };
    pack.items = $$(".pack-demand-row").map(row => ({ categoryId: $("[data-pack-category]", row).value, mode, qty: Number($("[data-pack-qty]", row).value) }));
    delete pack.snapshot; delete pack.capacitySnapshot;
    return pack;
  }
  function updatePackDiff() {
    if (!$("#pack-diff")) return;
    const pack = readPackForm(), before = packValues(dialogContext.original), after = packValues(pack);
    $("#pack-diff").innerHTML = diffBlock(Object.keys(after).filter(key => before[key] !== after[key]).map(key => [key, before[key] || "—", after[key]]));
    const car = state.vehicles.find(item => item.id === pack.vehicleId), capacity = car?.caps[pack.shift][pack.mode] || 0, amount = total(pack.items, pack.mode);
    $("#pack-capacity").classList.toggle("invalid", amount > capacity); $("#pack-capacity").innerHTML = `容量占用 <strong>${num(amount)} / ${num(capacity)} ${unit(pack.mode)}</strong>${amount > capacity ? " · 已超出容量，保存将被拒绝" : " · 同模式直接累计"}`;
  }
  function savePack() {
    if (!$("#pack-form").reportValidity()) return;
    const context = dialogContext, pack = readPackForm(), before = packValues(context.original), after = packValues(pack);
    const ok = commit(data => {
      requireFuture(context.date); const plan = data.plans.find(item => item.id === context.planId), day = plan.days[context.date], target = copy(day.formal || day.draft || []), index = target.findIndex(item => item.id === pack.id);
      if (index >= 0) target[index] = pack; else target.push(pack);
      const errors = validatePacks(data, context.date, plan, target, !!day.formal); if (errors.length) throw new Error(errors.join("\n"));
      if (day.formal) { day.formal = target.map(item => snapshot(item, data, (day.formal || []).find(old => old.id === item.id))); day.history.push({ at: timestamp(), action: context.original ? "修改正式任务包" : "新增正式任务包", packs: copy(day.formal), before, after }); }
      else { day.draft = target; day.manual = true; day.stale = false; }
    }, context.formal ? "调整正式排班" : "修改排班草稿", { 日期: context.date, 修改前: before, 修改后: after });
    if (ok) { closeDialog(); toast(context.formal ? "正式排班已更新，原变更记录已保留" : "草稿已保存，尚未确认正式排班"); }
  }
  function deletePack(id) {
    const context = copy(dialogContext), planId = context.planId, date = context.date;
    confirmDialog("删除这份任务包？", `${date} · 删除后对应需求将恢复为未分配`, `<div class="review-list">${Object.entries(packValues(context.original)).map(([key, value]) => `<div><span>${key}</span><strong>${esc(value)}</strong></div>`).join("")}</div>${notice("司机和车辆占用会随正式修改释放；不能删除最后一份正式任务包，请改用取消本日排班。")}`, () => {
      const ok = commit(data => { requireFuture(date); const plan = data.plans.find(item => item.id === planId), day = plan.days[date], target = (day.formal || day.draft || []).filter(pack => pack.id !== id), errors = validatePacks(data, date, plan, target, !!day.formal); if (errors.length) throw new Error(errors.join("\n")); if (day.formal) { day.formal = target; day.history.push({ at: timestamp(), action: "删除正式任务包", packs: copy(target) }); } else { day.draft = target; day.manual = true; } }, "删除任务包", { 日期: date, 原任务包: packValues(context.original) });
      if (ok) toast("任务包已删除，对应需求保持未分配"); return ok;
    }, "确认删除", true);
  }

  function generateDates(planId, dates, origin = "页面") {
    const extra = {};
    const ok = commit(data => { const plan = data.plans.find(item => item.id === planId); for (const date of [...dates].sort()) { const day = plan.days[date]; if (day.formal) continue; requireFuture(date); day.draft = generatePacks(data, date, plan, extra); day.draft.forEach(pack => { extra[pack.driverId] = (extra[pack.driverId] || 0) + 1; }); day.stale = false; day.manual = false; } }, "生成排班预览", { 计划: state.plans.find(plan => plan.id === planId)?.name, 日期: dates.join("、"), 说明: "仅草稿，未确认" }, origin);
    if (ok) toast("排班预览已生成，正式安排尚未改变"); return ok;
  }
  function generateCurrent() {
    const day = currentDay(), planId = ui.planId, date = ui.date;
    if (!day || date <= state.today) return toast("该日期只读，不能生成排班", true);
    if (day.formal) return toast("此日已有正式排班，请使用任务包调整");
    if (day.draft !== null) confirmDialog("重新生成本日预览？", "当前草稿及人工调整将被覆盖", notice("重新生成仍是草稿，不会形成正式排班。请先确认无需保留当前人工调整。"), () => generateDates(planId, [date]), "覆盖并生成");
    else generateDates(planId, [date]);
  }
  function showBatchPicker(mode) {
    const plan = currentPlan(); if (!plan) return toast("请先创建计划", true);
    dialogContext = { kind: "batch", mode, planId: plan.id };
    showDialog(mode === "generate" ? "批量生成排班预览" : "选择批量确认日期", plan.name, notice(mode === "generate" ? "勾选日期的未确认草稿将重新生成，包括已有人工修改；已确认日期自动跳过。" : "按日期整体确认；任意一个待确认日期失败，本次新增确认全部回滚。已确认日期自动跳过。") + `<div class="check-row"><label><input type="checkbox" id="batch-select-all" checked>全选可操作日期</label></div><div class="day-checkboxes">${Object.entries(plan.days).map(([date, day]) => { const info = statusOf(day, date); return `<label><input type="checkbox" name="batch-date" value="${date}" ${date > state.today ? "checked" : ""}>${date} 周${weekday(date)}<small>${info.label}${!day.formal && day.draft === null && mode === "confirm" ? " · 无草稿" : ""}</small></label>`; }).join("")}</div>`, btn("取消", "close-dialog") + btn(mode === "generate" ? "生成所选日期预览" : "查看确认摘要", "batch-submit", "primary", "", mode === "generate" ? "spark" : "arrow"));
  }
  function showConfirmDates(planId, dates, origin = "页面") {
    const plan = state.plans.find(item => item.id === planId), rows = dates.map(date => ({ date, day: plan.days[date] })), newRows = rows.filter(row => !row.day.formal), packs = newRows.flatMap(row => row.day.draft || []), flat = packs.flatMap(pack => pack.items);
    const partial = newRows.some(row => total(row.day.demands, "TAG") > total((row.day.draft || []).flatMap(pack => pack.items), "TAG") || total(row.day.demands, "ROAD") > total((row.day.draft || []).flatMap(pack => pack.items), "ROAD"));
    const body = `<div class="review-list"><div><span>所属计划</span><strong>${esc(plan.name)}</strong></div><div><span>所选日期</span><strong>${dates.map(shortDate).join("、")}</strong></div><div><span>本次新增确认</span><strong>${newRows.length} 天 · ${packs.length} 个任务包</strong></div><div><span>已确认自动跳过</span><strong>${rows.length - newRows.length} 天</strong></div></div><div class="summary-grid"><div class="summary-box"><strong>${num(total(flat, "TAG"))}</strong><span>TAG 分配 / 个</span></div><div class="summary-box"><strong>${num(total(flat, "ROAD"))}</strong><span>ROAD 分配 / km</span></div><div class="summary-box"><strong>${packs.length}</strong><span>本次正式班次</span></div></div>${partial ? notice("存在未分配需求。可以确认有效安排，缺口只作提醒，不会自动进入后续排班。", "") : ""}${notice("全部待确认日期校验通过才会一起生效。通知未接入，本次不会发送司机通知。")}`;
    const revision = state.revision;
    confirmDialog("确认这些日期的排班？", "确认后将形成正式安排，草稿不再作为占位依据。", body, () => confirmDates(planId, dates, origin, revision), "确认并形成正式排班");
  }
  function confirmDates(planId, dates, origin = "页面", revision = null) {
    const source = state.plans.find(plan => plan.id === planId);
    if (dates.every(date => source.days[date].formal)) { toast("ALREADY_CONFIRMED · 所选日期均已确认，没有重复保存"); return true; }
    const ok = commit(data => { const plan = data.plans.find(item => item.id === planId), errors = []; dates.forEach(date => { const day = plan.days[date]; if (day.formal) return; if (date <= data.today) errors.push(`${date} 已锁定。`); if (day.draft === null) errors.push(`${date} 尚未生成草稿。`); else errors.push(...validatePacks(data, date, plan, day.draft, true).map(error => `${date}：${error}`)); }); if (errors.length) throw new Error(`本次新增确认全部未生效，原草稿保留。\n${errors.join("\n")}`); dates.forEach(date => { const day = plan.days[date]; if (day.formal) return; day.formal = day.draft.map(pack => snapshot(pack, data)); day.draft = null; day.stale = false; day.history.push({ at: timestamp(), action: "首次确认", packs: copy(day.formal), demands: copy(day.demands) }); }); }, "确认正式排班", { 计划: source.name, 日期: dates.join("、"), 通知: "未接入，不发送" }, origin, revision);
    if (ok) toast("所选排班已确认 · 司机通知未接入"); return ok;
  }
  function showCancelDay(planId = ui.planId, date = ui.date, origin = "页面") {
    const plan = state.plans.find(item => item.id === planId), day = plan?.days[date];
    if (!day?.formal || date <= state.today) return toast("只能取消未来日期的有效正式排班", true);
    const revision = state.revision;
    confirmDialog("取消本日正式排班？", `${date} · ${plan.name}`, `<div class="review-list"><div><span>释放班次</span><strong>${day.formal.length} 个任务包</strong></div><div><span>保留内容</span><strong>原计划需求、原安排及取消历史</strong></div></div>${notice("取消后可在原计划中重新生成预览。计划日期归属不释放，不会另建同日计划。", "")}`, () => { const ok = commit(data => { requireFuture(date); const target = data.plans.find(item => item.id === planId).days[date]; target.history.push({ at: timestamp(), action: "取消正式排班", packs: copy(target.formal) }); target.formal = null; target.draft = null; }, "取消正式排班", { 日期: date, 任务包: day.formal.length }, origin, revision); if (ok) toast("排班已取消，司机与车辆占用已释放"); return ok; }, "确认取消排班", true);
  }

  function showCategories() {
    dialogContext = { kind: "categories" };
    showDialog("采集类别", "道路类型或路况按类别管理，不改变车辆容量。", `<div id="category-list">${state.categories.map(item => `<div class="catalog-row">${pill(item.mode, item.mode.toLowerCase())}<div class="catalog-name"><input aria-label="${esc(item.name)}类别名称" data-category-id="${item.id}" value="${esc(item.name)}"></div><button class="icon-button" data-action="remove-category" data-id="${item.id}" aria-label="删除${esc(item.name)}">${icon("trash")}</button></div>`).join("")}</div><div class="subtle-separator"></div><div class="form-grid"><label class="form-field"><span>新类别模式</span><select id="new-category-mode"><option>TAG</option><option>ROAD</option></select></label><label class="form-field"><span>新类别名称</span><input id="new-category-name" placeholder="填写类别名称"></label></div><div class="actions" style="margin-top:12px">${btn("添加类别", "add-category", "small", "", "plus")}</div>`, btn("关闭", "close-dialog") + btn("保存名称修改", "save-categories", "primary", "", "check"));
  }
  function showSettings() {
    dialogContext = { kind: "settings" };
    showDialog("演示设置", "仅控制当前浏览器内的原型场景，不影响项目业务数据。", `<div class="form-grid"><label class="form-field full"><span>演示业务日期</span><input id="settings-date" type="date" value="${state.today}" required><small>默认 2026-11-02，用于体验未来可改、当天锁定。此处不是实际系统时间。</small></label></div><div class="form-section-title">快速体验场景</div><div class="actions">${btn("查看资源不足日", "demo-shortage", "small", "", "alert")}${btn("查看历史锁定日", "demo-history", "small", "", "lock")}</div><div class="subtle-separator"></div><div class="actions">${btn("恢复示例数据", "demo-reset", "small", "", "refresh")}${btn("从空白开始", "demo-blank", "small danger", "", "trash")}${btn("退出演示账号", "logout", "small", "", "logout")}</div><div class="priority-callout">当前为静态交互原型：演示数据保存在浏览器，Agent 为本地预设交互。可直接打开 index.html，无需服务端。</div>`, btn("关闭", "close-dialog") + btn("应用演示日期", "save-settings", "primary"));
  }
  function renderLogin() {
    const overlay = $("#login-overlay"); overlay.hidden = false;
    overlay.innerHTML = `<div class="login-card"><div class="brand"><span class="brand-mark">F<span></span></span><span>Fleetwise<small>司机智能排班</small></span></div><h2>欢迎回来，周队长</h2><p>一处工作空间，安排好整个车队。</p><label class="form-field"><span>演示身份</span><input value="周队长 · 车队长" readonly></label>${btn("进入演示工作空间", "login", "primary", "", "arrow")}<p class="small-text" style="margin:15px 0 0">此为单一角色登录交互演示，不执行真实身份认证。</p></div>`;
  }
  function setPage(page) { ui.page = PAGES[page] ? page : "workbench"; if (location.hash !== `#${ui.page}`) history.replaceState(null, "", `#${ui.page}`); render(); window.scrollTo({ top: 0, behavior: "instant" }); }
  const agentActions = new Map();
  function renderAgent() {
    $("#agent-panel").hidden = !ui.agentOpen;
    if (!ui.messages.length) ui.messages.push({ role: "assistant", html: `<div class="message-label">FLEETWISE / ASSISTANT</div><strong>你好，周队长。</strong><br>告诉我你需要查询或安排什么。我会根据当前演示数据给出结果，任何写入都由你最终确认。<div class="suggestions">${["查询明天的采集需求", "查询所有高效率司机", "生成当前日期排班预览", "将张三的效率等级改为高"].map(text => `<button class="suggestion" data-action="agent-suggestion" data-text="${esc(text)}">${text}</button>`).join("")}</div>` });
    $("#agent-messages").innerHTML = ui.messages.map(message => `<div class="message ${message.role}">${message.role === "user" ? esc(message.text) : message.html}</div>`).join("");
    $("#agent-messages").scrollTop = $("#agent-messages").scrollHeight;
  }
  function agentReply(html) { ui.messages.push({ role: "assistant", html }); renderAgent(); }
  function pendingAgent(title, summary, callback, successText) {
    const id = uid("A"), revision = state.revision;
    agentActions.set(id, { revision, callback, successText });
    agentReply(`<strong>${esc(title)}</strong><div class="agent-pending">${summary}<div class="actions">${btn("确认执行", "agent-confirm", "primary small", `data-id="${id}"`, "check")}${btn("取消", "agent-cancel", "small", `data-id="${id}"`)}</div></div><p class="small-text" style="margin-top:8px">未确认前，数据保持不变。</p>`);
  }
  function agentDate(text) {
    const exact = text.match(/\d{4}-\d{2}-\d{2}/); if (exact) return exact[0];
    const chinese = text.match(/(\d{1,2})月(\d{1,2})日?/); if (chinese) return `${state.today.slice(0, 4)}-${chinese[1].padStart(2, "0")}-${chinese[2].padStart(2, "0")}`;
    if (text.includes("后天")) return addDate(state.today, 2);
    if (text.includes("明天")) return addDate(state.today, 1);
    if (text.includes("今天")) return state.today;
    if (/当前|这一天|本日/.test(text)) return ui.date;
    return null;
  }
  function sendAgent(text) {
    text = text.trim(); if (!text) return;
    ui.agentOpen = true; ui.messages.push({ role: "user", text }); renderAgent();
    if (/SQL|数据库|执行代码/i.test(text)) return agentReply("我只支持采集计划、排班、司机和车辆的预定义业务操作。请描述具体业务目标；演示不执行 SQL 或任意代码。");
    if (/本周/.test(text) && /生成|确认|修改|取消/.test(text)) return agentReply(`“本周”包含今天或过去的只读日期，不能直接执行。请明确未来的起止日期；我不会自动缩减操作范围。当前演示日期为 <strong>${state.today}</strong>。`);
    const exactDates = text.match(/\d{4}-\d{2}-\d{2}/g) || [];
    if (exactDates.length > 1) return agentReply(`已识别多个日期。请在工作台选择所需日期进行批量生成或确认；演示不会只执行第一个日期。${btn("前往工作台", "goto-workbench", "small")}`);
    const date = agentDate(text), plan = date ? state.plans.find(item => item.days[date]) : currentPlan(), day = date ? plan?.days[date] : null;
    const writing = /修改|调整|改为|改成|设为|设置|改到|改高/.test(text);
    if (writing && /效率|等级/.test(text)) {
      const matches = state.drivers.filter(driver => text.includes(driver.name));
      if (matches.length !== 1) return agentReply(matches.length ? `存在重名或多个候选，请明确司机编号：${matches.map(driver => `${esc(driver.name)}（${driver.id}）`).join("、")}。` : "请提供司机姓名或编号，以及要设置的 HIGH、MEDIUM 或 LOW 等级。");
      const grade = /高|HIGH/i.test(text) ? "HIGH" : /低|LOW/i.test(text) ? "LOW" : /中|MEDIUM/i.test(text) ? "MEDIUM" : null, driver = matches[0];
      if (!grade) return agentReply("请明确要调整为高、中、低哪一个效率等级。");
      const revision = state.revision;
      return pendingAgent("请核对司机效率变更", `<div>${esc(driver.name)} · ${driver.id}</div>${diffBlock([["效率等级", driver.grade, grade]])}`, () => commit(data => { data.drivers.find(item => item.id === driver.id).grade = grade; invalidateDrafts(data); }, "修改司机效率", { 司机: driver.name, 编号: driver.id, 修改前: driver.grade, 修改后: grade }, "Agent", revision), `${driver.name}的效率等级已更新为 ${grade}。已有正式排班未自动重排。`);
    }
    if (/司机/.test(text) && /查询|所有|哪些|多少|查看/.test(text)) {
      const high = /高|HIGH/.test(text); let drivers = state.drivers.filter(driver => !high || driver.grade === "HIGH");
      if (/可用/.test(text)) { if (!date) return agentReply("司机可用性与采集日期有关。请告诉我需要查询哪一天，例如“查询明天的可用司机”。"); drivers = drivers.filter(driver => available(driver, date)); }
      return agentReply(`<strong>${date ? `${date} · ` : ""}${high ? "高效率司机" : "司机查询"}</strong><p>共 ${drivers.length} 位。${!date ? "未指定日期，此结果不代表指定日期可用。" : ""}</p>${drivers.slice(0, 8).map(driver => `<div class="agent-line">${esc(driver.name)} <span class="small-text">${driver.id}</span> ${pill(driver.grade, "green")}</div>`).join("")}${drivers.length > 8 ? `<p class="small-text">其余 ${drivers.length - 8} 位可在车队资源查看。</p>` : ""}${btn("查看车队资源", "goto-resources", "small")}`);
    }
    if (/创建|新增/.test(text) && /计划/.test(text)) return agentReply(`创建计划还需要明确每日采集类别、目标量及日期。${date ? `已识别日期 <strong>${date}</strong>。` : ""}请在表单中补齐并检查后创建。${btn("打开计划创建表单", "new-plan", "small", "", "plus")}`);
    if (/新增|修改|调整|删除/.test(text) && /车辆|司机/.test(text) && !/排班|换成|替换/.test(text)) return agentReply(`请在资源表中定位具体对象并核对完整变更。演示支持通过页面增删改，不会根据缺少容量、编号或姓名的指令直接写入。${btn("打开车队资源", "goto-resources", "small")}`);
    if (/需求|采集任务|有哪些任务|采集计划/.test(text) && /查询|查看|哪些|多少/.test(text)) {
      if (!date) return agentReply("请提供具体采集日期，例如“查询明天的采集需求”。");
      if (!day) return agentReply(`${date} 没有采集计划。${btn("创建计划", "new-plan", "small")}`);
      return agentReply(`<strong>${date} · 采集需求</strong><p>${esc(plan.name)}</p>${day.demands.map(item => `<div class="agent-line">${pill(item.mode, item.mode.toLowerCase())} ${esc(categoryName(item.categoryId))}<strong style="float:right">${num(item.qty)} ${unit(item.mode)}</strong></div>`).join("")}<div class="actions" style="margin-top:10px">${btn("查看当日排班", "history-open", "small", `data-plan="${plan.id}" data-date="${date}"`)}</div>`);
    }
    if (/生成/.test(text) && /排班|预览/.test(text)) {
      if (!date) return agentReply("请明确要生成哪一天的排班，或使用“生成当前日期排班预览”。");
      if (!day) return agentReply(`${date} 尚无采集需求，请先创建计划。`);
      if (date <= state.today) return agentReply(`${date} 已锁定，只能查询。不会自动改成其他日期。`);
      if (day.formal) return agentReply(`${date} 已有正式排班，需要调整时请修改正式任务包，不能用新预览覆盖。`);
      if (day.draft !== null && day.manual) return agentReply(`该日存在人工调整后的草稿。请在工作台明确选择“重新生成”，检查覆盖提示。${btn("查看当前草稿", "history-open", "small", `data-plan="${plan.id}" data-date="${date}"`)}`);
      const ok = generateDates(plan.id, [date], "Agent");
      return agentReply(ok ? `已生成 <strong>${date}</strong> 的预览，共 ${state.plans.find(item => item.id === plan.id).days[date].draft.length} 个任务包。<strong>尚未形成正式排班。</strong>${btn("查看预览", "history-open", "small", `data-plan="${plan.id}" data-date="${date}"`)}` : "生成未成功，请查看页面提示；正式安排没有改变。");
    }
    if (/确认/.test(text) && /排班/.test(text)) {
      if (!date || !day) return agentReply("请明确有草稿的采集日期，例如“确认当前日期排班”。");
      if (day.formal) return agentReply(`${date} 已经确认，ALREADY_CONFIRMED。本次没有重复保存，也没有发送通知。`);
      if (date <= state.today || !day.draft?.length) return agentReply("该日期已锁定，或没有有效草稿。无法确认空排班。");
      const revision = state.revision;
      return pendingAgent("确认后将形成正式安排", `<strong>${date}</strong> · ${esc(plan.name)}<div>共 ${day.draft.length} 个任务包</div><div>TAG ${num(total(day.draft.flatMap(pack => pack.items), "TAG"))} 个 · ROAD ${num(total(day.draft.flatMap(pack => pack.items), "ROAD"))} km</div><p class="small-text">存在缺口时仅提醒，不自动滚入后续日期。通知未接入。</p>`, () => confirmDates(plan.id, [date], "Agent", revision), `${date} 的排班已确认，具体结果可在正式排班和操作记录查看。司机通知未接入。`);
    }
    if (/取消/.test(text) && /排班/.test(text)) {
      if (!date || !day?.formal || date <= state.today) return agentReply("请明确一个未来日期且当前有效的正式排班。");
      const revision = state.revision;
      return pendingAgent("请确认取消范围", `<strong>${date}</strong> · ${day.formal.length} 个任务包<br>取消后释放资源，保留需求与历史，可在原计划重新排班。`, () => commit(data => { const target = data.plans.find(item => item.id === plan.id).days[date]; requireFuture(date); target.history.push({ at: timestamp(), action: "取消正式排班", packs: copy(target.formal) }); target.formal = null; target.draft = null; }, "取消正式排班", { 日期: date, 计划: plan.name }, "Agent", revision), `${date} 的正式排班已取消，原需求与历史保留。`);
    }
    if (/为什么|未分配|缺口/.test(text)) {
      if (!date || !day) return agentReply("请说明要分析的采集日期，例如“当前日期为什么有任务未分配”。");
      const packs = day.formal || day.draft || [], flat = packs.flatMap(pack => pack.items), tag = round(total(day.demands, "TAG") - total(flat, "TAG")), road = round(total(day.demands, "ROAD") - total(flat, "ROAD"));
      return agentReply(`<strong>${date} · 分配检查</strong><div>TAG 未分配 ${num(tag)} 个，ROAD 未分配 ${num(road)} km。</div>${!packs.length ? "尚无有效安排，请先生成草稿。" : tag || road ? "当前演示先安排 TAG；当可用司机、车辆班次容量不足或车辆模式已确定时，剩余需求保留为缺口。可检查资源或人工调整，缺口不会自动滚入其他日期。" : "当前需求已全部安排。这不表示实际采集已经完成。"}`);
    }
    if (/换成|替换|换为/.test(text) && /司机|张三|李四/.test(text)) return agentReply(`更换司机需要明确日期、车辆或班次，并展示全部变更。请从任务包打开编辑表单后检查保存。${btn("前往排班工作台", "goto-workbench", "small")}`);
    if (/统计|班次最多|工作量/.test(text)) return agentReply(`统计页面提供正式排班分配量、司机班次数与车辆利用情况，不包含实际采集完成率。${btn("查看统计分析", "goto-reports", "small")}`);
    agentReply(`这份原型支持部分预设自然语言交互，并非真实大模型。你可以试试查询需求、高效率司机、修改司机效率、生成或确认当前日期排班。<div class="suggestions">${["查询明天的采集需求", "查询所有高效率司机", "确认当前日期排班"].map(value => `<button class="suggestion" data-action="agent-suggestion" data-text="${value}">${value}</button>`).join("")}</div>`);
  }

  function restoreData(blank) {
    confirmDialog(blank ? "从空白数据开始？" : "恢复示例数据？", "仅替换当前浏览器的原型演示数据", notice("当前浏览器中的计划、资源、草稿和演示记录将被替换，不影响项目服务端或数据库。", ""), () => { const next = createDemo(blank); next.revision = state.revision + 1; state = next; ui.planId = blank ? "" : "P001"; ui.date = addDate(state.today, 2); ui.resourceQuery = ""; ui.resourceGrade = ""; ui.resourceStatus = ""; ui.stale = false; ui.messages = []; agentActions.clear(); persist(); render(); toast(blank ? "已进入空白场景，请先维护车队资源" : "示例数据已恢复"); return true; }, blank ? "清空并开始" : "恢复示例", true);
  }
  function showDayHistory(planId, date) {
    const day = state.plans.find(plan => plan.id === planId)?.days[date]; if (!day) return;
    showDialog("当日变更记录", `${date} · 保留当时司机、车辆与任务信息`, day.history.length ? day.history.map(entry => `<div class="day-detail"><header><strong>${esc(entry.action)}</strong><span class="small-text">${esc(entry.at)}</span></header><p>${(entry.packs || []).map(pack => { const info = packInfo(pack); return `${esc(info.plate)} ${SHIFTS[pack.shift]} · ${esc(info.name)} · ${num(total(pack.items, pack.mode))} ${unit(pack.mode)}`; }).join("<br>")}</p>${entry.before ? diffBlock(Object.keys(entry.after).filter(key => entry.before[key] !== entry.after[key]).map(key => [key, entry.before[key] || "—", entry.after[key]])) : ""}</div>`).join("") : '<p class="muted">暂无正式排班变更记录。</p>', btn("关闭", "close-dialog"), true);
  }
  function actionHandler(action, button) {
    const id = button.dataset.id;
    switch (action) {
      case "close-dialog": closeDialog(); break;
      case "confirm-dialog": { const callback = dialogContext?.callback; if (callback && callback()) closeDialog(); break; }
      case "new-plan": openPlanWizard(); break;
      case "edit-plan": openPlanWizard(id); break;
      case "wizard-next": wizardNext(); break;
      case "wizard-back": captureWizard(); ui.planWizard.step--; drawPlanWizard(); break;
      case "wizard-save": saveWizard(); break;
      case "plan-detail": showPlanDetail(id); break;
      case "open-plan": ui.planId = id; closeDialog(); ensureSelection(); setPage("workbench"); break;
      case "delete-plan": { const plan = state.plans.find(item => item.id === id); confirmDialog("删除这份未确认计划？", plan.name, notice("计划及未确认草稿将删除。存在正式历史的计划不能直接删除。", ""), () => commit(data => { const target = data.plans.find(item => item.id === id); requireFuture(target.start); if (Object.values(target.days).some(day => day.formal || day.history.length)) throw new Error("存在正式排班历史，请按日期取消未来安排。"); data.plans = data.plans.filter(item => item.id !== id); }, "删除采集计划", { 计划: plan.name }), "确认删除", true); break; }
      case "edit-day-demand": showDemandEditor(button.dataset.plan, button.dataset.date); break;
      case "save-day-demand": saveDayDemands(); break;
      case "add-demand": { const group = button.dataset.group; if (dialogContext.kind === "plan-wizard") { captureWizard(); const list = group === "base" ? ui.planWizard.demands : ui.planWizard.overrides[ui.planWizard.overrideDate]; const next = state.categories.find(item => !list.some(entry => entry.categoryId === item.id)) || state.categories[0]; if (!next) return toast("请先维护采集类别", true); list.push({ categoryId: next.id, mode: next.mode, qty: 1 }); drawPlanWizard(); } else { const list = readDemands("day"), next = state.categories.find(item => !list.some(entry => entry.categoryId === item.id)) || state.categories[0]; if (!next) return toast("请先维护采集类别", true); list.push({ categoryId: next.id, mode: next.mode, qty: 1 }); $("#day-demands").innerHTML = demandRows(list, "day"); updateDemandDiff(); } break; }
      case "remove-demand": { const group = button.dataset.group, index = Number(button.dataset.index); if (dialogContext.kind === "plan-wizard") { captureWizard(); const list = group === "base" ? ui.planWizard.demands : ui.planWizard.overrides[ui.planWizard.overrideDate]; list.splice(index, 1); drawPlanWizard(); } else { const list = readDemands("day"); list.splice(index, 1); $("#day-demands").innerHTML = demandRows(list, "day"); updateDemandDiff(); } break; }
      case "move-demand": {
        const group = button.dataset.group, index = Number(button.dataset.index), target = index + Number(button.dataset.direction);
        if (dialogContext.kind === "plan-wizard") {
          captureWizard(); const list = group === "base" ? ui.planWizard.demands : ui.planWizard.overrides[ui.planWizard.overrideDate];
          if (target < 0 || target >= list.length) break;
          [list[index], list[target]] = [list[target], list[index]]; drawPlanWizard();
        } else {
          const list = readDemands("day"); if (target < 0 || target >= list.length) break;
          [list[index], list[target]] = [list[target], list[index]]; $("#day-demands").innerHTML = demandRows(list, "day"); updateDemandDiff();
        }
        break;
      }
      case "select-day": ui.date = button.dataset.date; render(); break;
      case "week-prev": { const plan = currentPlan(); ui.date = addDate(ui.date, -7) < plan.start ? plan.start : addDate(ui.date, -7); render(); break; }
      case "week-next": { const plan = currentPlan(); ui.date = addDate(ui.date, 7) > plan.end ? plan.end : addDate(ui.date, 7); render(); break; }
      case "mode-filter": ui.mode = button.dataset.mode; render(); break;
      case "board-view": ui.boardView = button.dataset.layout; render(); break;
      case "generate-day": generateCurrent(); break;
      case "batch-generate": showBatchPicker("generate"); break;
      case "batch-confirm": showBatchPicker("confirm"); break;
      case "batch-submit": { const { planId, mode } = dialogContext, dates = $$("[name=batch-date]:checked").map(input => input.value); if (!dates.length) return showError("请至少选择一个日期。"); if (mode === "generate") { if (generateDates(planId, dates)) closeDialog(); } else showConfirmDates(planId, dates); break; }
      case "confirm-day": showConfirmDates(ui.planId, [ui.date]); break;
      case "cancel-day": showCancelDay(); break;
      case "add-pack": showPackEditor("", button.dataset.vehicle || "", button.dataset.shift === undefined ? null : Number(button.dataset.shift)); break;
      case "edit-pack": showPackEditor(id); break;
      case "save-pack": savePack(); break;
      case "delete-pack": deletePack(id); break;
      case "pack-add-item": { dialogContext.working = readPackForm(); const plan = state.plans.find(item => item.id === dialogContext.planId), mode = dialogContext.working.mode, choices = plan.days[dialogContext.date].demands.filter(item => item.mode === mode), next = choices.find(item => !dialogContext.working.items.some(entry => entry.categoryId === item.categoryId)) || choices[0]; if (!next) return showError("当日没有该模式需求。"); dialogContext.working.items.push({ categoryId: next.categoryId, mode, qty: 1 }); drawPackEditor(); break; }
      case "pack-remove-item": dialogContext.working = readPackForm(); dialogContext.working.items.splice(Number(button.dataset.index), 1); drawPackEditor(); break;
      case "resource-tab": ui.resourceTab = button.dataset.tab; ui.resourceQuery = ""; ui.resourceGrade = ""; ui.resourceStatus = ""; render(); break;
      case "new-resource": showResourceEditor(); break;
      case "edit-resource": showResourceEditor(id); break;
      case "save-resource": saveResource(); break;
      case "unavailable": showUnavailable(id); break;
      case "save-unavailable": saveUnavailable(); break;
      case "remove-unavailable": { const item = resourceById(id), range = item.unavailable[Number(button.dataset.index)]; confirmDialog("移除不可用记录？", `${range.start} — ${range.end}`, notice("此操作会恢复该日期范围的可用性，不自动修改已有排班。"), () => { const ok = commit(data => { requireFuture(range.start); const list = id.startsWith("D") ? data.drivers : data.vehicles; list.find(entry => entry.id === id).unavailable.splice(Number(button.dataset.index), 1); invalidateDrafts(data); }, "移除不可用记录", { 资源: id, 日期: `${range.start} 至 ${range.end}` }); if (ok) toast("不可用记录已移除"); return ok; }); break; }
      case "delete-resource": { const item = resourceById(id), name = item.name || item.plate; if (resourceReferenced(id)) return showDialog("该资源需要保留历史", name, notice("已有草稿、正式排班或历史引用，不能删除。可以编辑为停用；若影响未来正式排班，需先调整。", ""), btn("关闭", "close-dialog") + btn("前往编辑", "edit-resource", "primary", `data-id="${id}"`)); confirmDialog("删除这条资源？", name, notice("未被排班引用的资源可以删除。", ""), () => commit(data => { const key = id.startsWith("D") ? "drivers" : "vehicles"; data[key] = data[key].filter(entry => entry.id !== id); invalidateDrafts(data); }, "删除车队资源", { 编号: id, 名称: name }), "确认删除", true); break; }
      case "categories": showCategories(); break;
      case "add-category": { const mode = $("#new-category-mode").value, name = $("#new-category-name").value.trim(); if (!name) return showError("请填写类别名称。"); if (commit(data => { if (data.categories.some(item => item.mode === mode && item.name === name)) throw new Error("此模式下已有同名类别。"); data.categories.push({ id: uid(mode[0]), mode, name }); }, "新增采集类别", { 模式: mode, 名称: name })) { showCategories(); toast("采集类别已添加"); } break; }
      case "save-categories": { const values = $$("[data-category-id]").map(input => ({ id: input.dataset.categoryId, name: input.value.trim() })); if (commit(data => { if (values.some(item => !item.name)) throw new Error("类别名称不能为空。"); values.forEach(value => { data.categories.find(item => item.id === value.id).name = value.name; }); for (const mode of ["TAG", "ROAD"]) { const names = data.categories.filter(item => item.mode === mode).map(item => item.name); if (new Set(names).size !== names.length) throw new Error("同模式下类别名称不能重复。"); } }, "修改采集类别", { 变更: values })) { closeDialog(); toast("类别名称已保存"); } break; }
      case "remove-category": { if (allDays().some(({ day }) => day.demands.some(item => item.categoryId === id))) return showError("该类别已被计划引用，请保留历史名称或修改未确认需求后再删除。"); const item = state.categories.find(entry => entry.id === id); confirmDialog("删除采集类别？", item.name, notice("只删除未被计划引用的类别。", ""), () => commit(data => { data.categories = data.categories.filter(entry => entry.id !== id); }, "删除采集类别", { 类别: item.name }), "确认删除", true); break; }
      case "history-open": ui.planId = button.dataset.plan; ui.date = button.dataset.date; if ($("#modal").open) closeDialog(); setPage("workbench"); break;
      case "day-history": showDayHistory(button.dataset.plan, button.dataset.date); break;
      case "log-detail": { const log = state.logs.find(item => item.id === id); showDialog(log.action, `${log.at} · 周队长 · ${log.origin}入口`, `${pill(log.success ? "成功" : "失败", log.success ? "green" : "red")}<pre>${esc(JSON.stringify(log.detail, null, 2))}</pre>`, btn("关闭", "close-dialog")); break; }
      case "agent-toggle": ui.agentOpen = !ui.agentOpen; renderAgent(); if (ui.agentOpen) $("#agent-input").focus(); break;
      case "agent-suggestion": sendAgent(button.dataset.text); break;
      case "agent-confirm": { const pending = agentActions.get(id); if (!pending) return agentReply("此确认已处理，请勿重复提交。"); if (pending.revision !== state.revision || ui.stale) { agentActions.delete(id); button.disabled = true; return agentReply("数据在生成摘要后发生了变化。本次没有执行，请重新提出请求并核对新摘要。"); } const success = pending.callback(); agentActions.delete(id); button.disabled = true; if (success) agentReply(esc(pending.successText)); else agentReply("操作未成功，原业务安排保留。请查看提示并重新核对。"); break; }
      case "agent-cancel": agentActions.delete(id); button.closest(".agent-pending").innerHTML = '<span class="small-text">本次操作已取消，数据没有改变。</span>'; break;
      case "goto-workbench": setPage("workbench"); break;
      case "goto-resources": setPage("resources"); break;
      case "goto-reports": setPage("reports"); break;
      case "history-filter-clear": ui.historyQuery = ""; ["hDriver", "hVehicle", "hGrade", "hStatus", "hStart", "hEnd"].forEach(key => { ui[key] = ""; }); ui.hMissing = false; render(); break;
      case "notification": showDialog("司机通知未接入", "TODO · 此区域用于展示通知能力的预留状态", notice("原型不发送司机通知，不记录虚假发送成功状态，也不运行失败重试。"), btn("知道了", "close-dialog")); break;
      case "settings": showSettings(); break;
      case "save-settings": { const date = $("#settings-date").value; if (!date) return showError("请选择演示日期。"); if (commit(data => { data.today = date; }, "调整演示日期", { 修改前: state.today, 修改后: date })) { closeDialog(); toast("演示业务日期已更新，日期锁定规则即时生效"); } break; }
      case "demo-shortage": { const row = allDays().find(({ date, day }) => date > state.today && total(day.demands, "TAG") > 5000); if (!row) return showError("当前数据中没有资源不足示例，请先恢复示例数据。"); ui.planId = row.plan.id; ui.date = row.date; closeDialog(); setPage("workbench"); break; }
      case "demo-history": { const row = allDays().find(({ date, day }) => date <= state.today && day.formal); if (!row) return showError("当前数据中没有历史示例。"); ui.planId = row.plan.id; ui.date = row.date; closeDialog(); setPage("workbench"); break; }
      case "demo-reset": restoreData(false); break;
      case "demo-blank": restoreData(true); break;
      case "logout": state.authenticated = false; persist(); closeDialog(); render(); break;
      case "login": state.authenticated = true; persist(); render(); break;
      case "reload-data": { const latest = readStorage(); if (latest) state = latest; ui.stale = false; agentActions.clear(); closeDialog(); render(); toast("已载入最新演示数据"); break; }
      default: break;
    }
  }

  document.addEventListener("click", event => {
    const view = event.target.closest("[data-view]"); if (view) return setPage(view.dataset.view);
    const button = event.target.closest("[data-action]"); if (!button || button.disabled) return;
    event.preventDefault();
    try { actionHandler(button.dataset.action, button); } catch (error) { showError(error.message || "操作未完成，请检查输入。"); }
  });
  function renderKeepingFocus(id) { const field = document.getElementById(id), position = field?.selectionStart; render(); const next = document.getElementById(id); if (next) { next.focus(); if (position !== null) try { next.setSelectionRange(position, position); } catch { /* 日期输入无需设置选择范围。 */ } } }
  document.addEventListener("input", event => {
    const input = event.target;
    const searches = { "resource-search": "resourceQuery", "plan-search": "planQuery", "history-search": "historyQuery", "log-search": "logQuery" };
    if (searches[input.id]) { ui[searches[input.id]] = input.value; return renderKeepingFocus(input.id); }
    if (input.closest("#pack-form")) updatePackDiff();
    if (input.closest("#resource-form")) updateResourceDiff();
    if (input.closest("#day-demands")) updateDemandDiff();
  });
  document.addEventListener("change", event => {
    const input = event.target;
    const historyFilters = { "history-driver": "hDriver", "history-vehicle": "hVehicle", "history-grade": "hGrade", "history-status": "hStatus", "history-start": "hStart", "history-end": "hEnd", "history-missing": "hMissing" };
    if (historyFilters[input.id]) { ui[historyFilters[input.id]] = input.type === "checkbox" ? input.checked : input.value; render(); return; }
    if (input.id === "plan-select") { ui.planId = input.value; ensureSelection(); render(); }
    if (input.id === "work-date") { if (currentPlan()?.days[input.value]) { ui.date = input.value; render(); } }
    if (input.id === "resource-date") { ui.resourceDate = input.value; render(); }
    if (input.id === "grade-filter") { ui.resourceGrade = input.value; render(); }
    if (input.id === "resource-status") { ui.resourceStatus = input.value; render(); }
    if (input.id === "report-start" || input.id === "report-end") { const start = $("#report-start").value, end = $("#report-end").value; if (!start || !end || start > end) return toast("统计结束日期不能早于开始日期", true); ui.reportStart = start; ui.reportEnd = end; render(); }
    if (input.id === "batch-select-all") $$("[name=batch-date]").forEach(checkbox => { checkbox.checked = input.checked; });
    if (input.id === "override-enabled") { captureWizard(); ui.planWizard.useOverride = input.checked; if (input.checked && !ui.planWizard.overrides[ui.planWizard.overrideDate]) ui.planWizard.overrides[ui.planWizard.overrideDate] = copy(ui.planWizard.demands); drawPlanWizard(); }
    if (input.id === "override-date") { captureWizard(); ui.planWizard.overrideDate = input.value; if (!ui.planWizard.overrides[input.value]) ui.planWizard.overrides[input.value] = copy(ui.planWizard.demands); drawPlanWizard(); }
    if (input.matches("[data-demand-mode]")) { const row = input.closest(".demand-row"), select = $("[data-demand-category]", row); select.innerHTML = state.categories.filter(item => item.mode === input.value).map(item => `<option value="${item.id}">${esc(item.name)}</option>`).join(""); const qty = $("[data-demand-qty]", row); qty.step = input.value === "TAG" ? "1" : ".001"; qty.min = qty.step; updateDemandDiff(); }
    if (input.id === "pack-mode") { const pack = readPackForm(), plan = state.plans.find(item => item.id === dialogContext.planId), first = plan.days[dialogContext.date].demands.find(item => item.mode === input.value); pack.items = first ? [{ categoryId: first.categoryId, mode: input.value, qty: 1 }] : []; dialogContext.working = pack; drawPackEditor(); }
    else if (input.closest("#pack-form")) updatePackDiff();
    if (input.closest("#resource-form")) updateResourceDiff();
    if (input.closest("#day-demands")) updateDemandDiff();
  });
  $("#agent-form").addEventListener("submit", event => { event.preventDefault(); const input = $("#agent-input"); sendAgent(input.value); input.value = ""; });
  $("#agent-input").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("#agent-form").requestSubmit(); } });
  document.addEventListener("submit", event => { if (event.target.id !== "agent-form") event.preventDefault(); });
  $("#modal").addEventListener("click", event => { if (event.target === $("#modal")) { const rect = $("#modal").getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeDialog(); } });
  $("#modal").addEventListener("cancel", () => { dialogContext = null; });
  window.addEventListener("storage", event => { if (event.key === STORAGE_KEY && event.newValue && event.newValue !== JSON.stringify(state)) { ui.stale = true; $("#stale-banner").hidden = false; } });
  window.addEventListener("hashchange", () => setPage(location.hash.slice(1)));
  ui.page = PAGES[location.hash.slice(1)] ? location.hash.slice(1) : "workbench";
  render(); renderAgent();
})();
