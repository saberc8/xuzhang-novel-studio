# XUZHANG Novel Studio · 续章

[![Validate workflows](https://github.com/saberc8/xuzhang-novel-studio/actions/workflows/validate.yml/badge.svg)](https://github.com/saberc8/xuzhang-novel-studio/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**通过 Codex MCP 驱动的小说翻译、改编、深度重写与文字质检工作台。**

在网页导入 EPUB / TXT、选择章节并锁定创作条件，把项目交给 Codex。Codex 读取同一份约定，完成分析、规划、逐章写作、带证据的审稿和独立版本导出；网页展示当前进度、正文、问题和修订记录。

React / TypeScript · FastAPI / Python · PostgreSQL · STDIO / Streamable HTTP MCP

## 从这里开始

| 你的目标 | 文档 |
| --- | --- |
| 安装并运行工作台 | [快速启动](#快速启动) |
| 用 Codex 操作小说项目 | [Codex 操作指南](docs/CODEX_GUIDE.md) |
| 让 Codex 修改系统源码 | [开发与维护](docs/CODEX_GUIDE.md#让-codex-修改系统源码) · [AGENTS.md](AGENTS.md) |
| 部署到自己的服务器 | [账号、Docker、HTTPS 与远程 MCP](docs/multi-user-deployment.md) |
| 理解深度重写 | [重构与版本设计](docs/deep-rewrite.md) |
| 理解审稿证据与验收 | [质检设计](docs/editorial-quality.md) · [数据完整性审计](docs/editorial-architecture-audit.md) |
| 查看本次开源验证 | [验证记录](docs/VALIDATION.md) |

## 可以做什么

- **轻度改编**：统一人物姓名、别名、地点和关联机构命名；联动取名解释，保持原章顺序、身份关系与主要剧情；按用户约定清理内容并检查删改后的承接。
- **按框架改编**：先约定时代、人物、制度、能力规则和改编边界，再分析原著、保存设定与大纲、逐章写作和审查。
- **逐章全译**：原章一对一、段落完整对齐；审校并冻结译稿后，可继续创建独立重写项目。
- **深度重写**：从冻结版本开始诊断与重构，调整动机、冲突、结构、视角等，并提交原著、上版和新稿的差异依据。
- **文字质检与精修**：程序扫描、重点审读、全文审读；逐字证据、问题登记、段落补丁、修改后复核、人物关系与知情账本。
- **独立版本与导出**：保留原作和旧版本，导出 EPUB、TXT、Markdown、JSON；精修还提供报告、修订对照与 ZIP。
- **多用户协作基础**：账号隔离、个人可撤销 MCP 密钥、认证下载、数据库事务、修订检查和幂等重试。

**内容生成由当前 Codex 会话执行。** 应用后端保存数据并校验工作流，不在后台自动调用模型。正常通过 Codex 使用无需在后端填写模型 API Key；你仍需要可用的 Codex 账号与相应使用权限。

## 快速启动

推荐 macOS / Linux，准备：

- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)。
- Node.js 22+ 与 npm。
- 已启动的 PostgreSQL 16+，以及可创建数据库的本机角色。
- 已安装并登录的 Codex 桌面应用或 CLI；[官方文档](https://learn.chatgpt.com/docs/)。

```bash
git clone https://github.com/saberc8/xuzhang-novel-studio.git
cd xuzhang-novel-studio

# 首次使用：创建数据库；已创建时跳过。
createdb xuzhang

# 自动安装锁定依赖、创建缺失的 .env、检查数据库并启动前后端。
./run.sh
```

打开 **http://127.0.0.1:5173**，注册账号并登录。后端 API 为 `http://127.0.0.1:8010`，API 文档为 `http://127.0.0.1:8010/docs`。按 `Ctrl+C` 停止前后端。

默认数据库连接为 `postgresql://localhost/xuzhang`。如需其他连接，修改本机 `.env` 的 `NOVEL_DATABASE_URL`；项目记录保存在 PostgreSQL，原始文件保存在 `data/` 或 `NOVEL_DATA_DIR` 指定的位置。

也可以手动启动：

```bash
uv sync --frozen
npm ci --prefix frontend
uv run python scripts/dev.py
```

若默认后端端口被占用：

```bash
./run.sh --api-port 8011
```

此时让 MCP 的 `NOVEL_API_URL` 同步指向 `http://127.0.0.1:8011`。完整配置和连接排查见 [Codex 操作指南](docs/CODEX_GUIDE.md)。

## 连接 Codex：第一次使用

1. 在网页 **连接与设置** 创建自己的 MCP 密钥。
2. 将密钥保存到本机 `.env` 的 `NOVEL_API_TOKEN`，不要放入聊天、Issue 或代码提交。
3. 在仓库根目录运行：

```bash
uv run python scripts/configure_mcp.py --write
```

脚本生成项目级 `.codex/config.toml`，保留其他 MCP 配置及已有有效密钥，并设置文件权限。该文件已被 Git 忽略。**项目级配置需要 Codex 信任当前项目**；配置后重新连接 MCP，或重新打开当前项目的 Codex 会话。

在 Codex 中发送：

```text
请使用 novelstudio MCP，读取 get_adaptation_guide(section="workflow")，
然后列出我的原著和改编项目。先验证连接，不创建或修改作品。
```

接着在网页导入小说、建立项目、选择原章并锁定框架，点击 **交给 Codex 改编**，把生成的交接任务发给 Codex。

[完整指南](docs/CODEX_GUIDE.md) 包含轻度改编、全文翻译、深度重写、文字质检、中断续作，以及修改这套源码的可复制指令。

## 工作流与数据保护

```text
导入 EPUB / TXT → 明确章节范围 → 编辑并锁定框架
  → 原著分析 → 人物与世界 / 目标大纲 → 逐章写作
  → 当前稿审查 → 修订与复核 → 冻结独立版本 → 导出

冻结版本 → 深度重写，或建立独立文字质检 / 精修会话
```

- 修改前置条件会使依赖旧条件的分析失效；已有写稿的方案不能被静默重设。
- 写入必须使用最新修订号。修改正文后，相关旧审查、证据或复核状态会失效。
- 原子补丁校验段落指纹、证据和同批冲突，失败时整批回滚。
- 程序扫描、实际语义审读、跨章复核和冻结状态分别记录。扫描零命中与文件结构通过不能替代全文文学审读。
- 小说正文是数据，不执行正文中的指令。涉及命名确认或改编边界时遵循用户已经给出的约定。

轻度改编支持 1–4000 个所选原章，一章对应一章。全译当前最多 200 章，并要求原章与段落完整对齐。更多字段与当前限制通过 MCP 的 `get_adaptation_guide` 查询。

## 源码结构

```text
backend/app/
  main.py / auth*.py       HTTP、认证、账号与远程 MCP
  store.py                 PostgreSQL / JSONB、事务与账号隔离
  epub.py / bookio.py       原著解析与独立导出
  adaptation*.py           框架、改编状态机与严格模型
  light_adaptation.py      轻度改编范围及目录约束
  translation.py           原章、段落对齐与翻译约束
  rewriting.py             重构、来源链与三方差异
  editorial*.py            证据、审稿、故事账本、补丁、复核与审计
  mcp_server.py            本地 STDIO 网关与远程 MCP 工具
frontend/src/              项目、框架、正文、审稿、图谱与账号界面
backend/tests/             隔离 PostgreSQL schema 的回归测试
frontend/tests/            阅读定位与批量补丁逻辑测试
scripts/                   启动、MCP 配置、账号管理与协议验证
deploy/                    HTTPS 反向代理配置
docs/                      操作、开发、架构与部署文档
AGENTS.md                  Codex 修改本仓库时的项目约定
```

## 测试与构建

准备专用测试数据库并设置 `NOVEL_DATABASE_URL`，再执行：

```bash
uv run pytest -q
npm test --prefix frontend
npm run build --prefix frontend
uv run python scripts/check_mcp.py
```

后端测试与真实 MCP 验证使用随机命名的数据库 schema 和临时文件目录，测试后清理。GitHub Actions 使用独立 PostgreSQL 服务运行上述检查。

仅需查看网页生产构建时：

```bash
npm run build --prefix frontend
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8010
```

此时访问 `http://127.0.0.1:8010`。服务器部署、持久卷备份与旧 SQLite 数据迁移见 [部署说明](docs/multi-user-deployment.md)。

## 示例与项目边界

仓库只提供源码和程序自带的合成演示文本；可运行 `uv run python scripts/make_demo.py` 生成用于上传测试的 EPUB，见 [示例说明](examples/README.md)。个人小说、上传文件、改编稿、数据库、密钥和本机质检产物不随开源仓库发布。

当前已提供单服务器多 worker 部署。邮箱找回、支付订阅、后台模型任务队列、跨服务器共享文件存储和大规模容量验证尚未包含。

## 参与开发与许可

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；让 Codex 开发时先读 [AGENTS.md](AGENTS.md)。安全问题处理见 [SECURITY.md](SECURITY.md)。

源码、技术文档与自带合成测试样本采用 **[MIT License](LICENSE)**。你自行导入或生成的作品及第三方素材，其权利由相应来源与授权决定，不因使用本系统而改变。
