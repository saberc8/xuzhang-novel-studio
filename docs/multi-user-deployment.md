# 多用户账号与线上部署

续章现在要求账号认证。网页使用账号、密码和 HttpOnly Cookie；MCP 使用每个用户自行创建的 Bearer 密钥。原著、改编、全译、深度重写、审稿、精修版和导出都按用户隔离。

## 使用账号

1. 打开网站，选择「创建账号」，填写账号名、显示名称和至少 6 位密码（支持纯数字）。账号名不区分大小写；它不是邮箱，不发送验证邮件。
2. 登录后上传自己的 EPUB / TXT、建立自己的改编项目。
3. 在「连接与设置」创建个人 MCP 密钥。可选 30 / 90 / 365 天；完整密钥只返回一次，服务器仅保存其 SHA-256 摘要。密钥最多同时有效 20 个。
4. 配置客户端后，MCP 读取与网页相同账号的作品。撤销或到期后连接立即失效。修改密码会撤销全部登录会话和 MCP 密钥。

密码使用独立随机盐和 scrypt 保存。浏览器会话默认 14 天，不把会话密钥放进 localStorage。浏览器写入请求校验 CSRF 令牌与 Origin；登录和注册使用共享 PostgreSQL 计数限流。下载也要求登录或 Bearer 认证，作品 URL 本身不授予权限。API 密钥不能创建新密钥、修改密码或管理账号。

## 旧工作台迁移

升级会在现有 `records` 表添加 `owner_id` 并升级主键。旧记录保留原样，归属为空，所有网页用户暂时不可见。第一位注册用户不会自动获得旧数据。

先备份 PostgreSQL 和整个 `NOVEL_DATA_DIR`，停掉旧版服务，再升级并启动新版。注册自己的账号后，在服务器执行：

```bash
uv run python scripts/accounts.py assign-legacy 你的账号名
```

该命令只把尚未归属的旧记录统一归给明确指定的已有账号，包括项目、冻结版和幂等记录；再次执行不会改动已经归属的记录。文件继续留在旧目录；新上传文件放在 `data/users/<用户ID>/<原著ID>/`。旧文件的读取同样先经过书籍归属检查。升级涉及数据库结构，回滚到旧代码前需恢复完整备份，不能直接让旧版无鉴权服务访问升级后的库。

如果仍从 SQLite 迁移，先创建目标账号，然后指定归属：

```bash
uv run python scripts/migrate_sqlite.py --owner 你的账号名
```

SQLite 迁移仍创建备份并在事务中核验记录。原始文件应放在目标服务的数据目录下，与原数据库中的原著 ID 对应。

## 用 Docker Compose 部署到自己的服务器

需要服务器上的 Docker Engine / Compose、一个域名，以及域名 DNS 指向该服务器。放行 80 / 443 端口。仓库提供 PostgreSQL、应用和自动申请 HTTPS 证书的 Caddy；应用和数据库不发布公网端口。

在项目根目录新建 `.env.production`（已被 Git 忽略）：

```dotenv
NOVEL_DOMAIN=novel.example.com
# 使用随机的长字母数字密码，避免 URL 中需要转义的字符。
XUZHANG_DB_PASSWORD=replace_with_a_long_random_alphanumeric_password
NOVEL_REGISTRATION_ENABLED=true
```

再执行：

```bash
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=100 app proxy
```

网站地址为 `https://你的域名`，HTTP MCP 为 `https://你的域名/mcp/`。Compose 自动设置 `NOVEL_PRODUCTION=true` 与 HTTPS 公网地址，浏览器 Cookie 启用 Secure。应用通过两个 worker 提供服务，登录状态、密钥撤销和身份限制共享数据库；HTTP MCP 为无状态协议处理，各请求重新认证。

`app` 信任容器网络的代理头，前提是只让 Caddy 暴露公网端口；不要给 `app` 增加公网 `ports`。如果改用其他反向代理，应限制可信代理 IP，并让代理覆盖来自外部的转发头。正文请求限制为 32 MB，单个小说文件仍限制 30 MB。

`postgres_data`、`novel_files` 与 Caddy 证书卷均持久保存。升级使用同一组卷；不要使用 `docker compose down -v`。备份必须同时覆盖 PostgreSQL 和小说文件卷；旧数据迁移也需要把原有 `data` 目录复制到 `novel_files`，并修正为容器用户 UID 10001 可读写。不能只迁移数据库。

容器里管理账号的示例：

```bash
docker compose --env-file .env.production exec app python scripts/accounts.py create owner --display-name 站点作者
docker compose --env-file .env.production exec app python scripts/accounts.py assign-legacy owner
docker compose --env-file .env.production exec app python scripts/accounts.py reset-password owner
docker compose --env-file .env.production exec app python scripts/accounts.py disable owner
docker compose --env-file .env.production exec app python scripts/accounts.py enable owner
```

密码由终端隐藏输入，不写在命令行参数中。设置 `NOVEL_REGISTRATION_ENABLED=false` 可关闭公开注册，仍能由上述命令创建账号。

## MCP 连接

HTTP 连接不要求用户安装后端代码。支持 Bearer 请求头的 MCP 客户端可直接使用 `/mcp/` 地址。Codex 配置示例：

```toml
[mcp_servers.novelstudio]
url = "https://novel.example.com/mcp/"
bearer_token_env_var = "NOVEL_API_TOKEN"
tool_timeout_sec = 120
```

在启动 Codex 的环境设置 `NOVEL_API_TOKEN` 为个人密钥；GUI 启动的桌面应用不一定继承终端环境，须确保实际客户端进程能读取该变量。`url` 与 `bearer_token_env_var` 的字段用法已按 [OpenAI 官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) 核对。其他支持自定义认证头的客户端设置 `Authorization: Bearer <个人密钥>`。此版本提供个人密钥认证，尚未实现 OAuth 自动授权；只接受 OAuth 的客户端需要后续对接。

HTTP MCP 提供 39 个工作流工具。`import_novel(path)` 仅保留在本地 STDIO 模式，避免远程用户访问服务器文件；线上用户通过网页上传原著。

本地 STDIO 有 40 个工具，可使用本机文件路径上传：

```toml
[mcp_servers.novelstudio]
command = "/你的本地项目/.venv/bin/python"
args = ["-m", "backend.app.mcp_server"]
cwd = "/你的本地项目"
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.novelstudio.env]
NOVEL_API_URL = "https://novel.example.com"
NOVEL_API_TOKEN = "替换为个人密钥"
```

`scripts/configure_mcp.py --write` 会保留既有个人密钥，并将配置权限设为 0600。新建配置使用占位值，需要本人替换。服务器不需要配置任何用户的 MCP 密钥或模型 API Key。MCP 下载地址不包含密钥，浏览器登录同一账号后即可下载；程序下载须携带 Bearer 请求头。

## 当前范围

已经实现个人账号和数据隔离、密码管理、可撤销的个人密钥、认证下载、HTTP / STDIO MCP，以及单服务器持久部署。作品生成仍由用户的 Codex 会话执行。

尚未包含邮箱验证/邮件找回、第三方登录、支付订阅、每月额度、存储计费、后台模型任务队列、管理员网页或跨服务器共享文件存储。当前文件卷方案适用于单服务器多 worker；扩容到多台服务器之前需要共享存储或对象存储，并针对实际并发量做容量测试。

## 验证

使用专用 PostgreSQL 的后端回归与真实 MCP 流程检查账号隔离、认证、跨账号拒绝、修订和导出。当前发布检查及未执行范围见 [VALIDATION.md](VALIDATION.md)。
