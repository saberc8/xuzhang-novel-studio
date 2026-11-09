# Codex 操作与源码开发指南

这份指南分为两种用法：**通过 `novelstudio` MCP 操作小说工作台**，以及 **让 Codex 直接阅读、修改和验证系统源码**。两者可以在同一个本地项目使用。

工作台负责原著、框架、进度、证据、版本和导出；Codex 当前会话负责实际阅读、创作和判断。网页上的「交给 Codex」生成交接任务，不会自动启动一个后台写作模型。

## 1. 在 Codex 中打开源码

```bash
git clone https://github.com/saberc8/xuzhang-novel-studio.git
cd xuzhang-novel-studio
```

在 Codex 桌面应用中将这个目录作为本地项目打开。使用已安装的 Codex CLI 时，在该目录运行 `codex`。先完成客户端登录，并按客户端提示信任你自己检查过的项目。

根目录 [AGENTS.md](../AGENTS.md) 记录本仓库的开发约定。它面向修改源码的 Codex；小说项目中的时代、人物和改编范围仍以网页保存并锁定的框架为准。

可复制给 Codex 的安装指令：

```text
请先读取 README.md、AGENTS.md 和 docs/CODEX_GUIDE.md，
检查 uv、Python、Node.js、npm 与 PostgreSQL 是否可用。
按仓库的快速启动步骤安装锁定依赖并运行本地工作台。
保留已有 .env 和数据库，不打印其中的密码或密钥。
如缺少账号或 MCP 密钥，完成不依赖它们的准备后，说明需要我在网页完成的具体步骤。
```

## 2. 启动工作台

准备 Python 3.12+、uv、Node.js 22+ 与已运行的 PostgreSQL 16+。首次使用且数据库不存在时创建数据库：

```bash
createdb xuzhang
./run.sh
```

脚本会同步依赖、在缺少时从 `.env.example` 创建 `.env`、检查数据库连接并启动前后端。打开 `http://127.0.0.1:5173`，注册账号并登录。

默认配置：

```dotenv
NOVEL_DATABASE_URL=postgresql://localhost/xuzhang
NOVEL_DATABASE_SCHEMA=public
NOVEL_API_URL=http://127.0.0.1:8010
NOVEL_PUBLIC_URL=http://127.0.0.1:8010
```

数据库服务、数据库本身和数据库角色须先准备好；应用只创建表和索引。数据库密码属于你的本机配置，不写进公共文档或 Git。

## 3. 创建个人 MCP 密钥

1. 登录工作台，打开「连接与设置」。
2. 创建个人 MCP 密钥，保存这次显示的完整值。
3. 在本机 `.env` 中加入 `NOVEL_API_TOKEN=<你的个人密钥>`。
4. 从仓库根目录运行：

```bash
uv run python scripts/configure_mcp.py --write
```

脚本生成 `.codex/config.toml`，使用当前仓库的绝对路径和虚拟环境 Python。已有其他 MCP 配置与有效的项目专用密钥会保留；若之前只有占位值，会尝试从 `.env` 补齐。生成配置的权限为 `0600`，Git 已忽略这个文件。

重新连接 `novelstudio`，或在客户端重新打开这个项目的会话。依据 [OpenAI 官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)，项目级 `.codex/config.toml` 只在受信任项目中加载。只改文件后继续沿用旧连接，可能仍看到旧工具或旧 schema。

### 本地 STDIO 配置示例

下面是说明模板，优先使用脚本生成。将绝对路径替换为你自己的位置：

```toml
[mcp_servers.novelstudio]
command = "/absolute/path/to/xuzhang-novel-studio/.venv/bin/python"
args = ["-m", "backend.app.mcp_server"]
cwd = "/absolute/path/to/xuzhang-novel-studio"
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.novelstudio.env]
NOVEL_API_URL = "http://127.0.0.1:8010"
NOVEL_API_TOKEN = "替换为你在工作台创建的个人密钥"
```

`NOVEL_API_TOKEN` 是此工作台的账号密钥，用于访问同一账号的数据。它与模型 API Key 是不同用途的凭据。

### 验证连接

在 Codex 中发送：

```text
请使用 novelstudio MCP：
1. 读取 get_adaptation_guide(section="workflow")。
2. 调用 list_books 和 list_adaptations，确认能够访问我的账号。
3. 只报告连接状态与已有项目，不创建新作品，也不打印任何密钥。
```

能发现工具却在读取时失败，通常需要继续核对后端运行状态、地址、个人密钥和账号，不应关闭认证。

## 4. 跑通第一个小说项目

没有自己的测试文件时，可以生成程序自带的合成样本：

```bash
uv run python scripts/make_demo.py
```

在网页「原著书架」上传生成的 `examples/雾港来信.epub`。该样本由仓库源码生成，不依赖个人小说或网络下载。

1. 进入原著书架，导入 EPUB / TXT，并补充来源版本信息。
2. 创建改编项目，明确选择原章；建议先选1章跑通流程。
3. 填写读者、语言、方向、保留项、禁止项和目标篇幅。
4. 在「改编条件」编辑时代、人物、地点、身份、能力规则和剧情边界。
5. 确认后保存并锁定框架，点击「交给 Codex 改编」。
6. 将生成的交接任务完整发送给 Codex；它包含当前项目引用。

Codex 应先恢复这个项目、读取最新修订与 `next_action`，再继续所需步骤。已经存在的项目不应重复创建。

## 5. 轻度改编：姓名、地点与内容清理

轻度改编默认包含人物姓名、别名、地点和关联机构名称，保留原章顺序、身份关系、规则和主要剧情。用户明确只改某一类名称时遵循其限定。新旧名称表先消歧；用户要求确认时，未确认的新增命名不写入正文。

可复制任务：

```text
请通过 novelstudio MCP 继续我在工作台建立的轻度改编项目。
先读取 workflow 与 light 指南，再恢复项目的最新框架和修订号。

范围：替换人物姓名、别名、地点和关联机构名称，保留原章顺序、
身份关系、能力规则及主要事件结果。
先给出新旧名称表；已有确认沿用，新发现的独立名称先向我确认。
同名不同人、人物名与地名同形、成语和普通词须按语境区分。
公司或地点取字解释与新名字同步。

内容清理仅按本项目已约定的读者范围执行。删减后核对起因、行动、
结果、转场、人物知情和境界提升；必要的中性承接单独登记新增事实。
逐章完成真实阅读与审查，再核对导出目录和正文。
报告程序扫描、重点复核与全书文学审读各自的实际范围。
```

MCP 创建参数使用 `mode="adaptation"`、`brief.preset="light"`；原章范围最多4000章，目标章数等于所选原章数。人物表在 `framework.characters`，地点与关联机构在 `framework.setting_mappings`。完整字段以当前 `get_adaptation_guide` 返回的 schema 为准。

## 6. 完整翻译、普通改编与深度重写

### 外文原作完整翻译

在网页选择「先逐章全译」，锁定翻译约定与译名表后交给 Codex：

```text
请读取 novelstudio 的 translation 指南并继续当前全译项目。
按所选原目录一章对应一章、逐段完整翻译，不缩写或合并段落。
按游标读到本章末页，保留译名、语气与信息顺序；核对准确性和完整性。
全部所选译稿审校完成后保存独立译稿，保留最初原著来源。
```

当前全译上限为200章。要重写译稿，先完成并冻结全部所选译章，再从该版本创建深度重写。

### 普通改编

网页锁定的前置框架决定改编目标。Codex 依次完成原著分析、人物与世界、目标大纲、逐章正文和当前稿审查。不要用一份梗概代替完整章节，或在缺少证据时直接填写全部通过。

### 深度重写

从已冻结的改编或指定精修版本创建新项目，并在网页约定要改变的结构维度：

```text
请读取 rewrite 指南，从我选定的冻结版本继续深度重写项目。
保持最初原著与上版可读，按已锁定条件诊断全稿、重构并重写。
用原著、上版、新稿的当前证据解释动机、冲突和结构等变化。
逐章审查后再完成全书差异审查；不要把换词或篇幅变化当作结构变化。
```

## 7. 文字质检与精修

在完成版进入「文字质检」，选择来源版本、范围、审读深度和是否允许改稿，再复制交接任务。

| 深度 | 用途 | 不能替代的工作 |
| --- | --- | --- |
| scan | 对全部所选正文运行程序规则，产生候选 | 文学或情节语义审读 |
| focused | 全量扫描，逐章首尾及风险、关键场景重点阅读 | 尚未读到的完整正文 |
| full | 逐块阅读全部所选稿件并提交跨章判断 | 编辑对证据和理解准确性的责任 |

可复制任务：

```text
请使用 novelstudio MCP 恢复这份文字质检任务，先读 editorial 指南。
按已选深度与权限检查人物、时间、空间、物件、知情、因果和行文。
每个问题引用当前正文的准确位置与证据，区分客观冲突、角色误解、
可接受的省略和文风偏好。
有修改权限时提出最小补丁，并核对受影响后文；应用后重新扫描、
比较改前改后、补足当前稿的真实复核记录，再判断是否可保存版本。
不要将局部问题登记、关键词零命中或数据完整性通过算作全文文学通过。
```

仅定位到一处明确错误时，可按 `report.kind="findings"` 登记问题；这不增加完整分块的审读覆盖。人物、关系和知情核对使用故事账本。数据链审计使用 `audit_editorial_integrity`，它不会替你重新阅读小说。

## 8. 中断后继续同一项目

保存网页项目链接或审稿链接即可恢复。新开 Codex 会话可发送：

```text
请继续这个已有项目：<粘贴工作台项目链接>。
通过 novelstudio MCP 获取最新状态、锁定框架、修订号和 next_action。
沿用已有范围和确认，不重新创建项目，不覆盖旧版或重置数据库。
从当前未完成阶段接着做，并如实保留尚未读完或尚未复核的范围。
```

若返回修订冲突，重新读取最新对象和上下文后再写入；不要删掉版本校验。若正文或依赖记录改变，过期证据需要重新定位并复核。

## 9. 使用远程 HTTP MCP

部署后，可以让本地 Codex 连接服务器，无需在每位使用者电脑安装 Python 后端。先在站点创建自己的个人密钥，再在 Codex 配置中设置：

```toml
[mcp_servers.novelstudio]
url = "https://novel.example.com/mcp/"
bearer_token_env_var = "NOVEL_API_TOKEN"
tool_timeout_sec = 120
```

将 `NOVEL_API_TOKEN` 设置在实际启动 Codex 的进程环境中。桌面应用不一定继承终端变量；不要将终端里设置过变量误当成桌面应用已经取得凭据。字段说明来自 [官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

服务器端通过网页上传原著；远程 HTTP MCP 不提供本机文件路径导入。该系统使用个人 Bearer 密钥，尚未实现 OAuth 自动授权。Docker、Caddy、账号与备份见 [部署说明](multi-user-deployment.md)。

## 让 Codex 修改系统源码

在仓库目录打开 Codex，先读取 [AGENTS.md](../AGENTS.md)，再给出具体触发条件、期望行为和允许修改的范围。源码开发可以不连接小说 MCP；只有操作已有小说数据时才需要对应账号的连接。

### 修复一个问题

```text
请先读 AGENTS.md 和 README.md，再检查这个问题：<描述触发条件>。
期望行为：<描述结果>。
在源码中定位原因，保留已有用户修改和生产数据。
用合成文本或隔离数据复现，完成最小修复并运行相关测试。
若涉及后端工作流或 MCP 契约，运行真实 MCP 协议验证；
若涉及前端，运行前端测试和生产构建。最后说明结果、验证和剩余限制。
```

### 新增工作流能力

```text
请在现有架构中加入：<能力和具体使用场景>。
先读取适用源码、Pydantic 模型、HTTP 路由、MCP 工具和前端入口。
让网页与 MCP 复用同一套应用服务及校验，不另建平行状态机。
保留账号隔离、事务、修订、幂等、旧版与证据失效规则。
同步修改指南与用户文案，用合成案例验证完整成功路径和关键失败分支。
```

### 验证命令

先准备专用开发/测试数据库，通过 `NOVEL_DATABASE_URL` 指定，再运行：

```bash
uv sync --frozen
npm ci --prefix frontend
uv run pytest -q
npm test --prefix frontend
npm run build --prefix frontend
uv run python scripts/check_mcp.py
```

测试使用随机 schema 与临时文件。真实协议验证会启动临时后端和 MCP 客户端，并测试认证、改编、深改、精修与导出。源码不应读取个人小说作为自动化测试材料。

### 提交与开源边界

提交前检查变更文件与 `git diff --check`。保留 `.env`、`.codex/config.toml`、`data/`、`output/`、数据库和作品文件在本机。源码许可证不改变上传作品的权利。

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 不能连接 PostgreSQL | 数据库服务、数据库是否已创建、角色权限及 `.env` 连接串 |
| Codex 没发现 novelstudio | 是否在正确仓库、项目是否受信任、配置路径、Python 路径，以及是否重连 |
| 能发现工具，读项目时401/403 | 后端地址、个人密钥是否缺失/撤销/到期、是否属于同一账号 |
| 改端口后连接失败 | 重跑 `configure_mcp.py --write --api-url http://127.0.0.1:新端口` 并重连 |
| 连接后看不到旧项目 | 账号是否一致；旧无账号数据需按部署文档显式迁移归属 |
| revision 过期 | 重新读取最新对象和上下文，不能移除版本检查 |
| 页面创建项目后没有自动写作 | 把「交给 Codex」的任务发到已连接的当前会话 |
| 审查或冻结被拒绝 | 查看 `next_action`、未读分块、过期证据、未复核补丁与未完成问题 |
| 远程 MCP 没有 import_novel | 这是本机路径工具；远程用户从网页上传文件 |
| 导出链接打开需登录 | 下载也校验同一账号；程序下载使用个人 Bearer 请求头 |

依赖下载因网络超时时，可以保留锁文件并重试 `UV_HTTP_TIMEOUT=120 uv sync --frozen`。不要为绕过下载失败随意升级依赖或删除锁文件。

## 官方配置依据

Codex 配置部分在2026-11-09按 OpenAI Docs 核对。工作台业务契约以本仓库和实时 MCP 指南为准。

- [OpenAI：MCP 连接与项目级配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [OpenAI：Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)
- [OpenAI：AGENTS.md 与开发工作流](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex)
