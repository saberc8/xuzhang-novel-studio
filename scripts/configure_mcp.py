"""Print or write project-scoped Codex MCP configuration; preserve unrelated tables."""
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings  # noqa: E402

TOKEN_PLACEHOLDER = "请替换为网页创建的个人密钥"


def configuration(api_url: str | None = None, *, api_token: str = TOKEN_PLACEHOLDER) -> str:
    def literal(value):
        return json.dumps(str(value), ensure_ascii=False)

    python = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return (
        "[mcp_servers.novelstudio]\n"
        f"command = {literal(python)}\n"
        'args = ["-m", "backend.app.mcp_server"]\n'
        f"cwd = {literal(ROOT)}\n"
        "startup_timeout_sec = 20\n"
        "tool_timeout_sec = 120\n\n"
        "[mcp_servers.novelstudio.env]\n"
        f"NOVEL_API_URL = {literal(api_url or Settings().api_url)}\n"
        f"NOVEL_API_TOKEN = {literal(api_token)}\n"
    )


def merge(existing: str, new: str) -> str:
    parts = re.split(r"(?m)(?=^\[)", existing)
    retained = [part for part in parts if not re.match(r"\[mcp_servers\.novelstudio(?:\.[^\]]+)?\]", part)]
    return "".join(retained).rstrip() + "\n\n" + new if any(part.strip() for part in retained) else new


def write_configuration(file: Path, api_url: str | None = None) -> bool:
    existing = file.read_text(encoding="utf-8") if file.exists() else ""
    saved = tomllib.loads(existing).get("mcp_servers", {}).get("novelstudio", {}).get("env", {}).get("NOVEL_API_TOKEN")
    # A generated placeholder is not a credential. Fill it from .env, while
    # retaining a real project-specific key and never printing either secret.
    token = saved if saved and saved not in {TOKEN_PLACEHOLDER, "替换为网页创建的个人密钥"} else Settings().api_token
    config = configuration(api_url, api_token=token or TOKEN_PLACEHOLDER)
    file.parent.mkdir(parents=True, exist_ok=True)
    import os
    with os.fdopen(os.open(file, os.O_WRONLY | os.O_CREAT, 0o600), "w", encoding="utf-8") as target:
        os.fchmod(target.fileno(), 0o600)
        target.write(merge(existing, config))
        target.truncate()
    return bool(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write .codex/config.toml for this project")
    parser.add_argument("--api-url", help="Backend URL; defaults to NOVEL_API_URL or .env")
    options = parser.parse_args()
    if options.write:
        file = ROOT / ".codex/config.toml"
        configured = write_configuration(file, options.api_url)
        print(f"已写入 {file}\n重新打开项目或重启 Codex 会话后，检查 novelstudio MCP。")
        if not configured:
            print("尚未配置个人密钥：请将网页创建的密钥保存为 .env 的 NOVEL_API_TOKEN，再次运行 --write。")
    else:
        # Printable instructions intentionally omit credentials from .env.
        print(configuration(options.api_url))
