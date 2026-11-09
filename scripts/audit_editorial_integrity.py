"""Run the read-only architectural audit through a fresh, authenticated STDIO MCP.

Exit 0 means data integrity passed, not literary acceptance. See acceptance_gaps.
Credentials are loaded by the normal MCP configuration and are never printed.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def call(session, name, **arguments):
    result = await session.call_tool(name, arguments)
    if result.isError:
        raise RuntimeError(f"MCP {name}: " + next(c.text for c in result.content if c.type == "text"))
    if result.structuredContent:
        return result.structuredContent
    return json.loads(next(c.text for c in result.content if c.type == "text"))


async def run(args):
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "backend.app.mcp_server"], cwd=str(ROOT))
    async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        available = (await session.list_tools()).tools
        tool = next(t for t in available if t.name == "audit_editorial_integrity")
        if not tool.annotations or not tool.annotations.readOnlyHint:
            raise RuntimeError("架构审计工具未声明只读")
        before = await call(session, "get_editorial_review", review_id=args.review_id)
        result = await call(session, "audit_editorial_integrity", review_id=args.review_id)
        after = await call(session, "get_editorial_review", review_id=args.review_id)
    result["execution"] = {"at_utc": datetime.now(timezone.utc).isoformat(), "transport": "stdio MCP → HTTP → PostgreSQL",
                           "discovered_tools": len(available), "read_only_annotation": True,
                           "before_revision": before["revision"], "after_revision": after["revision"],
                           "review_unchanged": before == after}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"integrity_passed": result["integrity_passed"], "scope": result["scope"],
                      "acceptance_gaps": [g["code"] for g in result["acceptance_gaps"]],
                      "literary_reread_performed": result["literary_reread_performed"],
                      "execution": result["execution"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0 if result["integrity_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
