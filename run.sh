#!/usr/bin/env bash
# Run from any working directory; keep configuration and data in this project.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'HELP'
用法：./run.sh [--api-port 8010]

安装锁定版本的依赖、检查 PostgreSQL，然后启动前后端。
需要 uv、Node.js 20.19+ / 22+、npm，以及已启动的 PostgreSQL 16+。
数据库连接从 .env 或 NOVEL_DATABASE_URL 环境变量读取。
首次使用前请创建数据库（默认：createdb xuzhang）。

网页：http://127.0.0.1:5173
API：http://127.0.0.1:8010/docs（可通过 --api-port 更改）
按 Ctrl+C 同时停止前后端。
HELP
  exit 0
fi

for tool in uv node npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf '缺少 %s，请先安装后重新运行。\n' "$tool" >&2
    exit 1
  fi
done

node -e '
const [major, minor] = process.versions.node.split(".").map(Number);
if (!(major >= 22 || (major === 20 && minor >= 19))) {
  console.error("需要 Node.js 20.19+ 或 22+，当前为 " + process.version);
  process.exit(1);
}
'

if [[ ! -f .env ]]; then
  cp .env.example .env
  printf '已从 .env.example 创建 .env。\n'
fi

printf '\n正在同步 Python 依赖……\n'
uv sync --frozen

printf '\n正在检查 PostgreSQL 连接……\n'
uv run --frozen python - <<'PY'
import sys

import psycopg

from backend.app.config import Settings

try:
    settings = Settings()
    with psycopg.connect(settings.database_url, connect_timeout=5) as connection:
        connection.execute("SELECT 1")
except psycopg.Error:
    # Connection errors may contain credentials; keep diagnostics local and safe.
    print("无法连接 PostgreSQL。请确认数据库服务已启动、数据库已创建，"
          "并检查 .env 中的 NOVEL_DATABASE_URL。", file=sys.stderr)
    print("使用默认本机配置时，可运行：createdb xuzhang", file=sys.stderr)
    sys.exit(1)
print("数据库连接正常。")
PY

printf '\n正在同步前端依赖……\n'
npm ci --prefix frontend --no-audit --no-fund

exec uv run --frozen python scripts/dev.py "$@"
