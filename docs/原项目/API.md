# API 与后续开发说明

运行服务后，以 `/docs` 或 `/openapi.json` 为请求字段和校验规则的准确依据。

## 响应与错误

成功：`{"success": true, "data": ...}`。

失败：`{"success": false, "error": {"code": "DRIVER_CONFLICT", "message": "具体原因", "details": ...}}`。

校验失败为 HTTP 422，资源未找到为 404，版本 / 业务冲突为 409，密钥错误为 401，SQLite 暂不可用为 503。确认业务失败的 `error.details` 包含 `rolled_back: true` 和空的 `newly_confirmed_dates`。

司机、车辆、计划 ID 使用整数，预览 ID 使用字符串。日期采用 `YYYY-MM-DD`，时间戳采用 UTC（含 Z 后缀）；前端按浏览器本地时区显示。道路公里数必须传字符串，例如 `"80.125"`。

列表接口 `/plans`、`/schedules`、`/notifications` 支持 `limit`（1–500，默认 100）与 `offset`。前端会自动翻页读取。`/audit-logs` 返回最近 100 条；预览历史返回最近 100 条。

## 接口索引

| 领域 | 接口 |
|---|---|
| 计划 | POST /api/plans；GET /api/plans；GET /api/plans/{id}；GET /api/plans/{id}/daily-tasks |
| 司机 | GET /api/drivers；GET /api/drivers/{id}；GET /api/drivers/available?date=...&shift=MORNING；POST /api/drivers；PUT /api/drivers/{id} |
| 车辆 | GET /api/vehicles；GET /api/vehicles/{id}；GET /api/vehicles/available?date=...&task_mode=TAG；POST /api/vehicles；PUT /api/vehicles/{id} |
| 班次 | GET /api/shifts；PUT /api/shifts/{code} |
| 不可用日期 | GET /api/{drivers或vehicles}/{id}/unavailability；POST 同一路径；DELETE /api/unavailability/{id} |
| 预览 | POST /api/schedules/preview；GET /api/schedules/previews?plan_id=...；GET /api/schedules/previews/{id} |
| 调整 | PATCH /api/schedules/previews/{id}/assignments/{assignment_id}；POST /api/schedules/previews/{id}/assignments；DELETE /api/schedules/previews/{id}/assignments/{assignment_id}?expected_version=... |
| 放弃 | POST /api/schedules/previews/{id}/discard |
| 确认 | POST /api/schedules/confirm |
| 正式排班 | GET /api/schedules?plan_id=...&start_date=...&end_date=... |
| 统计 | GET /api/schedules/statistics?plan_id=...&start_date=...&end_date=... |
| 通知 | GET /api/notifications?status=FAILED；GET /api/notifications/{id}；POST /api/notifications/{id}/retry |
| 系统 | GET /api/capabilities；GET /api/audit-logs；GET /health |

资源写接口是管理页面所需的专用业务接口，并非通用数据库 CRUD 工具。资源更新使用 PUT 完整替换可配置字段，不提供删除历史资源的接口，请使用 DISABLED 停用。

## 创建计划

```json
{
  "title": "11 月采集任务",
  "start_date": "2026-11-05",
  "end_date": "2026-11-11",
  "tag_requirements": [{"tag_type": "Tag-A", "daily_count": 100}],
  "road_requirements": [{"road_type": "CITY", "daily_km": "80"}],
  "daily_overrides": [
    {
      "date": "2026-11-07",
      "tag_requirements": [{"tag_type": "Tag-B", "daily_count": 50}],
      "road_requirements": [{"road_type": "HIGHWAY", "daily_km": "120"}]
    }
  ]
}
```

每日覆盖配置替换当日全部需求。目标均为正数，任务类型不可重复，单计划最大 366 天。

## 生成预览

```json
{"plan_id": 1, "start_date": "2026-11-05", "end_date": "2026-11-11", "algorithm": "GREEDY_V1"}
```

返回 `data.operation_status`、`data.previews[]`、`data.confirmed_schedules[]`。已覆盖的计划日期返回旧预览 / 正式排班，仅对未覆盖日期创建新预览；重叠范围可能涉及多份预览，因此结果采用数组，调用者应逐份展示。

预览字段：`preview_id`、`preview_version`、`lifecycle_status`、`status`、`expires_at`、`daily_results[]`。`status` 是 FULL / PARTIAL / NO_ASSIGNMENT 覆盖状态；`lifecycle_status` 是 PENDING / PARTIALLY_CONFIRMED / CONFIRMED / DISCARDED / EXPIRED。

每日结果中包含资源名称、效率、每条明细容量利用率、分模式覆盖率、未分配量、约束校验和原因说明。全新资源信息在确认前会再次查询。

`quality` 输出算法生成耗时（毫秒）、效率等级班次数分布、司机累计班次数和同等级离散指标。每日 `quality.vehicle_utilization_dispersion_by_mode` 按 TAG / ROAD 分别计算参与车辆的已排班容量利用率离散程度，以总体标准差、最小值、最大值和样本数表示。算法耗时为原始生成耗时，人工调整用 `manually_modified` 标记。有效预览的硬约束违规数为 0；复查失效预览时约束检查在第一个错误处停止，`hard_constraint_violations_detected` 表示已发现的错误数。

## 预览修改

PATCH 示例：

```json
{"expected_version": 1, "changes": {"driver_id": 2}}
```

新增示例：

```json
{
  "expected_version": 2,
  "date": "2026-11-05",
  "vehicle_id": 1,
  "driver_id": 3,
  "shift": "MORNING",
  "task_mode": "TAG",
  "tag_allocations": [{"tag_type": "Tag-A", "count": 30}],
  "road_allocations": []
}
```

道路任务使用 `road_allocations: [{"road_type": "CITY", "km": "10.125"}]`。改变模式时同时清空另一类 allocations。成功返回完整新预览与递增版本，失败时数据和版本不变。

放弃请求：`{"expected_version": 3}`。放弃只释放剩余未确认预览的计划日期声明，不会释放正式资源或删除正式排班。

## 确认与通知

```json
{
  "preview_id": "PREV-...",
  "expected_version": 3,
  "confirm_dates": ["2026-11-05", "2026-11-06"],
  "idempotency_key": "客户端生成的唯一请求键"
}
```

HTTP 请求包含完整人工确认范围；服务端在写锁内复核版本、有效期、当前预览声明、资源资格 / 可用性、其他计划占用、容量、任务目标。事务持久化每日排班、分配明细、每日车辆模式、通知及审计日志。全部新增日期原子提交，之前确认日期跳过。

成功结果为 SUCCESS，包含新增日期、跳过日期、覆盖情况、递增预览版本及通知状态。接口在事务提交后同步模拟派发，所以通常直接返回 SENT；若发送失败则返回 FAILED，数据库中正式排班依然有效。极端派发中断时保留 PENDING，启动时恢复派发。

同一个幂等键只能对应完全相同的请求。成功后的相同请求重放返回 ALREADY_CONFIRMED，`notification_triggered` 为 false。客户端超时后可使用原始请求和原键重试；发生业务冲突后刷新预览并使用新请求键。

当前控制台发送用写锁保护并发检查 / 发送 / 标记状态。控制台外部副作用与 SQLite 不属于一个原子系统，进程在打印完成后、状态提交前崩溃可能重复日志；未来接入短信或飞书时，通道实现必须把 `idempotency_key` 传给具备幂等能力的供应商。

## 后续 Agent 对接

Agent 层目录为空，目前没有 `/api/agent/*` 接口，访问返回 404。`/api/capabilities` 明确返回 `agent.implemented=false`。通用数据库查询 / 修改工具、任意 SQL 执行、DeepSeek 密钥配置均未实现。

建议未来从经过参数校验的业务 API 接入，或在明确事务边界下调用 `services`。查询、预览、确认都必须使用真实后端结果；写入操作的授权和人工确认由 Agent 层负责，最终约束仍由业务服务保证。Agent 调用确认接口时必须携带明确的预览 ID、当前版本、日期列表和幂等键。

替换算法时实现 `SchedulingStrategy.generate(SchedulingInput) -> list[dict]`，在 `scheduling/registry.py` 注册，同时扩展 `PreviewCreate.algorithm` 的枚举。策略内不能访问数据库；新策略输出仍须通过 `ConstraintValidator`。

## 数据层

核心表包含 drivers、vehicles、shifts、driver_shift_qualifications、vehicle_shift_capacities、resource_unavailability、collection_plans、plan_tag_requirements、plan_road_requirements、daily_tasks、daily_tag_requirements、daily_road_requirements、schedule_previews、preview_day_claims、daily_schedules、schedule_assignments、assignment_tag_allocations、assignment_road_allocations、vehicle_day_modes、notifications、confirmation_operations、audit_logs。

预览 JSON 与正式排班分离。道路需求和分配均存整数米；正式明细用外键关联具体每日需求。数据库约束保证每日司机唯一、每车每班唯一、每计划每日正式排班唯一、车辆每日模式唯一及通知幂等键唯一。跨表容量、模式一致性和每日目标等规则由同一事务内的业务校验保障。
