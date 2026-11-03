# Fleetwise · 司机智能排班系统

当前交付为第一阶段项目基础与公共能力。运行入口采用 Vue 3、TypeScript、Element Plus、FastAPI、SQLAlchemy 和 SQLite。

完整现状分析、复用方案、实现说明及验证记录见 [第一阶段实施记录](docs/implementation/01.基础与公共能力.md)。功能及契约依据见 [设计文档](docs/design/05.设计方案评审结果.md)。

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

生产装配目前只有公共能力。业务适配器随后续业务模块接入，当前未接入的动作返回 422 VALIDATION_ERROR。测试通过专用适配器调用真实 HTTP 入口验证完整 Prepare/Confirm 流程。

已实现的接口为 Q01、W01—W04、Q20—Q21。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/v1/context | 本机上下文及数据修订 |
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
| migrations/ | Alembic 环境与冻结的初始 SQL |
| frontend/ | Vue 基础页面、统一 Fetch、公共操作 API、路由及状态 |
| tests/foundation/ | 新版单元和集成验证 |
| tests/e2e/foundation_browser.py | Windows 启动与浏览器验证 |
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
```

2026-11-03 实际执行后端 149 项测试全部通过，其中新版 101 项、旧版 48 项。前端 5 项单元测试、类型检查、生产构建、Python 编译和全量 Ruff 检查通过。Windows PowerShell 完整安装启动和 start.bat 快速启动均通过真实 Chromium 验证，监听地址检查为 127.0.0.1。测试框架仍有一项 httpx 弃用提示。

截图和原始浏览器报告位于 test-results/foundation-desktop.png、foundation-mobile.png、foundation-verification.json 和 foundation-batch-verification.json。

## 后续阶段

司机、车辆、采集任务、排班算法及排班业务、通知、DeepSeek Agent、自然语言 SQL、通用 CRUD 工具和统计看板按后续任务实施。下一阶段应按已审核专用动作接入业务适配器，并补充对应业务规则及快照验证。
