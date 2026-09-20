"""
测试 focusloop_mcp_server.py 通过 stdio JSON-RPC 的能力。

运行: python3 tests/test_mcp_server.py
"""
import json
import subprocess
import sys
import os
from pathlib import Path


SCRIPT = Path(__file__).parent.parent / "focusloop_mcp_server.py"


def call_tool(proc: subprocess.Popen, name: str, args: dict, request_id: int = 1) -> dict:
    """发送 tool 调用请求到 MCP server，返回结果。"""
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": args,
        },
    }
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    response = json.loads(line)
    # MCP 协议把工具结果包装在 content[0].text
    # text 是 JSON 字符串，解析一次得到内层 dict
    if "result" in response and isinstance(response.get("result"), dict) and "content" in response["result"]:
        content_list = response["result"]["content"]
        if content_list and isinstance(content_list[0], dict) and "text" in content_list[0]:
            text = content_list[0]["text"]
            if isinstance(text, str):
                try:
                    response["result"]["parsed"] = json.loads(text)
                except Exception as e:
                    response["result"]["parsed"] = {"_error": str(e), "_raw": text}
            else:
                response["result"]["parsed"] = text
    return response


def list_tools(proc: subprocess.Popen) -> dict:
    request = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "tools/list",
        "params": {},
    }
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def main():
    # 准备临时环境
    import tempfile
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "state.sqlite3"
    env = os.environ.copy()
    # Hermes Agent 自身会设置 PYTHONPATH。移除它，确保测试的子进程使用
    # FocusLoop .venv 中锁定的 mcp==2.2.0，而不是父进程的 Hermes SDK。
    env.pop("PYTHONPATH", None)
    env["FOCUSLOOP_DB"] = str(db_path)
    env["FOCUSLOOP_PROJECT"] = "mcp-test"
    env["FOCUSLOOP_RULES"] = str(Path(__file__).parent.parent / "gate2" / "rules.json")

    # 启动 MCP server
    proc = subprocess.Popen(
        # 与测试进程使用同一个 .venv 解释器；PATH 中的 python3 可能是 Hermes 自身环境。
        [sys.executable, str(SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(Path(__file__).parent.parent),
    )

    try:
        # 0. Initialize handshake (MCP 协议要求)
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": -1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.1"}
            }
        }) + "\n")
        proc.stdin.flush()
        proc.stdout.readline()  # consume initialize response
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized"
        }) + "\n")
        proc.stdin.flush()

        # 1. tools/list - 列出所有工具
        print("=" * 60)
        print("1. tools/list")
        print("=" * 60)
        result = list_tools(proc)
        tools = result.get("result", {}).get("parsed", result.get("result", {})).get("tools", [])
        print(f"注册工具: {len(tools)} 个")
        for t in tools:
            print(f"  - {t['name']}: {t['description'][:60]}...")

        # 2. overview - 一站式概览
        print("\n" + "=" * 60)
        print("2. overview (无目标时)")
        print("=" * 60)
        result = call_tool(proc, "overview", {})
        print(json.dumps(result.get("result", {}).get("parsed", result.get("result", {})), ensure_ascii=False, indent=2))

        # 3. goal_propose
        print("\n" + "=" * 60)
        print("3. goal_propose")
        print("=" * 60)
        result = call_tool(proc, "goal_propose", {
            "payload": {
                "objective": "测试 MCP Server 集成",
                "deliverables": ["测试覆盖", "文档完整"],
                "constraints": ["首版只做基础"],
                "non_goals": ["暂不做商业化"],
            },
            "source": "MCP test",
        })
        print(json.dumps(result.get("result", {}).get("parsed", result.get("result", {})), ensure_ascii=False, indent=2))
        proposed_version = result["result"].get("parsed", result["result"]).get("version")

        # 4. goal_confirm (用户执行)
        print("\n" + "=" * 60)
        print("4. goal_confirm")
        print("=" * 60)
        result = call_tool(proc, "goal_confirm", {
            "version": proposed_version, "expected": 0, "source": "MCP test user"
        })
        print(json.dumps(result.get("result", {}).get("parsed", result.get("result", {})), ensure_ascii=False, indent=2))

        # 5. extract_constraints
        print("\n" + "=" * 60)
        print("5. extract_constraints")
        print("=" * 60)
        result = call_tool(proc, "extract_constraints", {
            "text": "禁止上传本地文件到云端。禁止使用第三方API。",
        })
        print(json.dumps(result.get("result", {}).get("parsed", result.get("result", {})), ensure_ascii=False, indent=2))

        # 6. confirm_constraint (Gate 1 → Gate 2 联动)
        print("\n" + "=" * 60)
        print("6. confirm_constraint (触发 Gate 2 自动同步)")
        print("=" * 60)
        candidates = result["result"].get("parsed", result["result"])["candidates"]
        for c in candidates[:2]:  # 确认前两个
            r = call_tool(proc, "confirm_constraint", {
                "id": c["id"], "text": c["text"],
                "source": "MCP test user", "confidence": "high",
            })
            print(f"  Confirmed {c['id']}: {r['result'].get('parsed', r['result'])['status']}")

        # 7. list_rules (Gate 2)
        print("\n" + "=" * 60)
        print("7. list_rules (含动态规则)")
        print("=" * 60)
        result = call_tool(proc, "list_rules", {"include_dynamic": True})
        data = result["result"].get("parsed", result["result"])
        print(f"静态规则: {data['static_rule_count']}")
        print(f"动态规则: {data['dynamic_rule_count']}")
        for d in data.get("dynamic_rules", []):
            print(f"  - {d['id']}: method={d.get('_match_method')}, tokens={d.get('_semantic_tokens')}")

        # 8. gate2_check (静态规则 + 动态规则)
        print("\n" + "=" * 60)
        print("8. gate2_check (静态 + 动态规则)")
        print("=" * 60)
        test_cmds = [
            ("调用 第三方接口", "dyn-c_auto_001 应触发"),
            ("pip install requests", "g2-003 应触发"),
            ("ls -la /tmp/", "应通过"),
        ]
        for cmd, expected in test_cmds:
            r = call_tool(proc, "gate2_check", {
                "tool_name": "Bash",
                "tool_input": {"command": cmd},
            })
            data = r["result"].get("parsed", r["result"])
            status = data.get("status", "unknown") if isinstance(data, dict) else f"NOT_DICT: {repr(data)[:80]}"
            rule_id = data.get("rule_id", "N/A") if isinstance(data, dict) else "N/A"
            print(f"  [{status}/{rule_id:18}] cmd=\"{cmd}\" ({expected})")

        # 9. drift_check (Gate 3)
        print("\n" + "=" * 60)
        print("9. drift_check (三档判定)")
        print("=" * 60)
        test_contexts = [
            (["测试覆盖", "文档完整"], "完全在范围 → aligned"),
            (["写养猫文章"], "无关 → drift"),
            (["Gate2 MCP Server"], "演进 → aligned"),
        ]
        for ctx, expected in test_contexts:
            r = call_tool(proc, "drift_check", {"context": ctx})
            data = r["result"].get("parsed", r["result"])
            print(f"  [{data['verdict']:9} drift={str(data['drift_detected']):5} score={data['overlap_score']}] {expected}")

        # 10. overview 最终
        print("\n" + "=" * 60)
        print("10. overview (最终状态)")
        print("=" * 60)
        result = call_tool(proc, "overview", {})
        print(json.dumps(result.get("result", {}).get("parsed", result.get("result", {})), ensure_ascii=False, indent=2))

        print("\n=== All MCP tool calls succeeded ===")

    finally:
        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
