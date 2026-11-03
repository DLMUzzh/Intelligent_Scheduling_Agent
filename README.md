# Fleetwise · 司机智能排班系统

当前交付包含项目基础与公共能力，以及第二阶段的采集类别、司机、车辆、请假和维修管理。运行入口采用 Vue 3、TypeScript、Element Plus、FastAPI、SQLAlchemy 和 SQLite。

现状分析、复用方案、实现说明及验证记录见 [第一阶段实施记录](docs/implementation/01.基础与公共能力.md) 和 [第二阶段实施记录](docs/implementation/02.基础资料管理.md)。功能及契约依据见 [设计文档](docs/design/05.设计方案评审结果.md)。

## Windows 启动

在工程目录执行，或双击 start.bat。

```powershell
.\start.ps1
# 依赖及前端已构建时
.\start.ps1 -NoInstall
# 使用其他本机端口
.\start.ps1 -NoInstall -Port 8010
# 后端开发重载
.\start.ps1 -NoInstall -Reload
```

启动脚本创建 Python 3.12 环境，按 requirements.lock 安装依赖，使用 Node.js 24 构建前端，然后启动单应用进程。系统 Node 版本不符合时，脚本在 .runtime 中安装项目内 Node 24。构建完成后，-NoInstall 启动只需要 Python。

默认页面地址为 [本机工作空间](http://127.0.0.1:8000)。页面通过同源 /api/v1/context 显示真实的操作者、北京时间业务日期和数据修订。服务默认监听 127.0.0.1，固定车队长身份。按 Ctrl+C 停止服务。

首次业务数据为空。默认新库为 data/active/scheduling.db，旧库 data/scheduling.db 保留。新版配置使用 FLEET_ 前缀，配置样例见 [.env.example](.env.example)。所有相对数据库路径基于工程根目录解析。

## 基础资料使用

从左侧导航进入采集类别、车队资源、请假与维修或操作记录。

| 页面 | 当前功能 |
| --- | --- |
| 采集类别 | TAG / ROAD 查询、新增、更名、删除，同模式名称唯一；本轮已确认采用既定类别范围 |
| 车队资源 | 司机车辆切换、关键词/启用/可用日期筛选、分页、详情、编辑、删除和启停 |
| 司机表单 | 姓名、联系方式、高中低效率及早中晚资格；允许重名和全部无资格 |
| 车辆表单 | 车牌、名称、备注和六项容量；车牌按去全部空白并转大写的唯一键校验 |
| 请假与维修 | 资源搜索及分页选择、整日区间登记、编辑、取消和相交日期查询；原区间和新完整区间均执行未来日期校验 |
| 操作记录 | 关键词、对象、成功失败及日期筛选，查看主对象前后数据和关联变更 |

表单先点击“查看变更”，阅读完整摘要后点击一次“保存并生效”。车辆道路容量在页面按公里填写，最多三位小数，接口和数据库使用精确整数米。Tag 和道路容量均允许零，单列上限为 SQLite 有符号整数最大值。

请假维修区间允许重复和重叠，覆盖任一记录即整日不可用。取消其中一条后继续按剩余记录计算。当天及过去区间锁定，当天突发情况按既定规则线下处理。

版本冲突会保留编辑内容。通过“刷新版本并保留输入”明确读取当前版本，再查看完整变更。连接中断时使用“核实结果”查询原请求，当前标签页会保存待核实请求键以支持刷新恢复。

## 当前公共能力

| 能力 | 实现 |
| --- | --- |
| Prepare | 只读构建完整摘要，冻结规范输入、解析结果、依赖版本和 SHA-256，持久保存 PENDING |
| Confirm | 核对 hash、确认标记、终态、版本、日期和摘要，统一事务执行 |
| Idempotency | 相同 key/input 返回原操作，同键异内容返回 409，执行重放保留真实终态 |
| Version | 全局修订、对象版本、日正式版本校验，公共条件更新防止旧版本覆盖 |
| Audit | 固定操作者、PAGE/AGENT 入口、对象、前后内容及结果，成功与业务同事务保存 |
| 失败处理 | 明确回滚后另存失败结果，提交结果未知时使用新 Session 查询核实 |
| 响应及访问 | 七字段统一响应、稳定错误码、请求追踪、本机 Host/Origin 校验和严格 JSON 校验 |

生产装配已接入类别、司机、车辆和不可用记录的 12 个专用动作，资料写入统一经过公共协议。第一阶段测试继续用显式注入的专用测试适配器隔离公共能力验证。

已实现的接口为 Q01—Q02、Q07—Q12、W01—W04、Q20—Q21。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/v1/context | 本机上下文及数据修订 |
| GET | /api/v1/collection-categories | 类别查询及分页 |
| GET | /api/v1/drivers、/api/v1/drivers/{driver_id} | 司机查询及详情 |
| GET | /api/v1/vehicles、/api/v1/vehicles/{vehicle_id} | 车辆查询及详情 |
| GET | /api/v1/resource-unavailability、/api/v1/resource-unavailability/{unavailability_id} | 请假维修查询及详情 |
| POST | /api/v1/operations | 准备操作 |
| GET | /api/v1/operations?request_key=... | 按键核实状态 |
| GET | /api/v1/operations/{operation_id} | 摘要及真实终态 |
| POST | /api/v1/operations/{operation_id}/executions | 执行冻结内容 |
| GET | /api/v1/audit-logs | 审计筛选及分页 |
| GET | /api/v1/audit-logs/{audit_log_id} | 审计详情 |

写请求需 application/json 及允许的 Origin。默认允许主机 127.0.0.1/localhost 的 8000 和 5173 端口，实际端口随 FLEET_PORT、FLEET_FRONTEND_PORT 配置生成。页面与后台使用同一接口。GET 保持只读。

## 数据库初始化与迁移

服务启动时执行版本化迁移。也可以单独执行。

```powershell
.\.venv\Scripts\python.exe -m app.database.migrate
```

初始修订号为 0001_foundation，使用已审核的 13 表、137 字段、12 个显式索引。全部表采用 STRICT、自增 id 和逻辑关联，物理外键数量为零。Alembic 版本表适配为 schema_migrations，自增 id 加唯一 version_num。

重复初始化保持现有数据。已按审核 SQL 创建但尚无迁移号的库，完整结构检查通过后登记真实初始修订。旧库、未知结构或结构漂移均拒绝自动升级。新迁移使用显式事务，失败时结构、数据和版本号一起回滚。初始修订的降级通过恢复经过验证的备份处理。

SQLite 使用 DELETE、FULL 和默认 5000ms 有限锁等待。技术日志写入 logs/application.log，按 5MB 和 3 份历史文件轮转。业务操作及审计记录持久保留。

## 目录与复用

| 位置 | 职责 |
| --- | --- |
| app/main.py | 新版装配、来源校验、响应和前端托管 |
| app/core/runtime.py、responses.py、time.py | 新版配置、错误响应、北京时间及 UTC 时间 |
| app/database/foundation.py、migrate.py | 新版连接、事务、提交核实和迁移入口 |
| app/models/foundation.py | 新版 13 表 ORM，独立元数据 |
| app/schemas/operations.py | 严格请求、版本、摘要与结果结构 |
| app/services/confirmation_service.py | 公共 Prepare/Confirm 与幂等 |
| app/services/version_service.py、operation_audit.py | 公共版本和审计 |
| app/api/foundation.py | 公共 HTTP 接入 |
| app/api/base_data.py、app/services/base_data_queries.py | 基础资料只读接口及批量可用性、累计班次查询 |
| app/schemas/base_data.py、base_data_queries.py、resource_snapshots.py | 资料动作、查询及既有快照的严格校验 |
| app/services/base_data_service.py、base_data_effects.py | 12 个动作、唯一性、引用/正式影响检查、关联刷新 |
| app/repositories/base_data.py | 新版资料读取、分页及公开投影 |
| migrations/ | Alembic 环境与冻结的初始 SQL |
| frontend/ | Vue 基础资料页面、统一 Fetch、公共操作预览、恢复及审计查看 |
| tests/foundation/ | 新版单元和集成验证 |
| tests/base_data/ | 基础资料的业务、事务及关联保护验证 |
| tests/e2e/foundation_browser.py | Windows 启动与浏览器验证 |
| tests/e2e/base_data_browser.py | 基础资料真实浏览器全流程及故障恢复验证 |
| app/legacy_main.py | 旧版回归入口，供既有测试使用 |

旧业务源码、静态页面和原型保留作为后续复用参考。既有 48 项单元和集成测试使用 legacy_main。新入口按本阶段范围装配。

## 开发与验证

前端开发需要 Node 24，后端默认端口 8000，Vite 默认端口 5173，开发代理将 /api 转发到后端。

```powershell
# 窗口一
.\start.ps1 -NoInstall -Reload
# 窗口二，使用 Node 24 环境
Set-Location frontend
npm run dev
```

安装测试依赖并执行后端验证。

```powershell
uv pip install --python .venv/Scripts/python.exe -r requirements.lock -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests migrations
.\.venv\Scripts\python.exe -m compileall -q app migrations
```

执行前端验证。

```powershell
Set-Location frontend
npm run typecheck
npm test
npm run build
```

执行 Windows 无头浏览器验证，使用临时新库并自动关闭测试服务。

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe tests/e2e/foundation_browser.py --install
.\.venv\Scripts\python.exe tests/e2e/foundation_browser.py --batch
.\.venv\Scripts\python.exe -m tests.e2e.base_data_browser --batch
```

2026-11-03 第二阶段实际执行后端 227 项测试全部通过，包括本阶段 78 项、第一阶段 101 项和旧版 48 项。前端 23 项单元测试、类型检查及生产构建通过。Windows PowerShell 本机入口和 start.bat 快速启动均已进行真实 Chromium 验证，监听地址检查为 127.0.0.1。测试框架仍有一项 httpx 弃用提示。

截图和原始浏览器报告位于 test-results。基础验证为 foundation-*.png / json，资料联调为 base-data-*.png 和 base-data-verification.json，均为本地生成的测试产物。

## 后续阶段

后续阶段可接入采集计划及每日需求，再按已审核顺序实现草稿、排班及查询模块。新模块使用现有资料、版本、不可用区间、容量快照和公共操作协议，并遵循已审核的正式历史结构。具体阶段范围由后续任务确定。
