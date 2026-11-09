"""Operator-only account setup and explicit legacy ownership migration (no HTTP endpoint)."""
import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.auth import Accounts
from backend.app.config import Settings
from backend.app.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "assign-legacy", "reset-password", "disable", "enable"])
    parser.add_argument("username")
    parser.add_argument("--display-name", default="")
    args = parser.parse_args()
    settings = Settings()
    store = Store(settings.data_dir, settings.database_url, settings.database_schema)
    accounts = Accounts(store, settings)
    try:
        if args.action in {"create", "reset-password"}:
            password = getpass.getpass("新密码（至少 6 位）：")
            if password != getpass.getpass("再次输入："):
                raise ValueError("两次密码不一致")
            if args.action == "create":
                accounts.create(args.username, password, args.display_name)
            else:
                accounts.change_password(accounts.find(args.username)["id"], None, password)
            print("账号已创建。" if args.action == "create" else "密码已重置，所有登录会话及 MCP 密钥已撤销。")
        elif args.action == "assign-legacy":
            count = accounts.assign_legacy(accounts.find(args.username)["id"])
            print(f"已将 {count} 条尚未归属的旧记录归入 {args.username}，原始文件保留原位。")
        else:
            user = accounts.find(args.username)
            with store.connection() as conn:
                conn.execute("UPDATE users SET active=%s WHERE id=%s", (args.action == "enable", user["id"]))
                if args.action == "disable":
                    conn.execute("UPDATE credentials SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (user["id"],))
            print("账号已启用。" if args.action == "enable" else "账号已停用，登录会话及 MCP 密钥已撤销。")
    finally:
        store.close()


if __name__ == "__main__":
    main()
