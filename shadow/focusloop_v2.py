# 只添加 observe-json 命令，其他保持不变
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from focusloop import *

# 在 main() 中添加 observe-json 子命令
def main_v2() -> int:
    parser = argparse.ArgumentParser(description="FocusLoop 本地状态与影子审查")
    parser.add_argument("--db", type=Path, default=Path(".focusloop/state.sqlite3"))
    parser.add_argument("--project", default="focusloop-v1")
    sub = parser.add_subparsers(dest="command", required=True)
    
    # 原有命令
    proposal = sub.add_parser("propose")
    proposal.add_argument("file", type=Path)
    proposal.add_argument("--source", required=True)
    
    confirmation = sub.add_parser("confirm")
    confirmation.add_argument("version", type=int)
    confirmation.add_argument("--expected", type=int, required=True)
    confirmation.add_argument("--source", required=True)
    
    decision = sub.add_parser("decide")
    decision.add_argument("id")
    decision.add_argument("payload", type=Path)
    decision.add_argument("--source", required=True)
    decision.add_argument("--supersedes")
    
    # 原有 observe 命令（字符串）
    observation = sub.add_parser("observe")
    observation.add_argument("id")
    observation.add_argument("summary")
    
    # 新增 observe-json 命令（JSON 文件）
    observation_json = sub.add_parser("observe-json")
    observation_json.add_argument("id")
    observation_json.add_argument("file", type=Path)
    
    review = sub.add_parser("review")
    review.add_argument("id")
    
    sub.add_parser("status")
    sub.add_parser("hook")
    
    args = parser.parse_args()
    store = Store(args.db, args.project)
    
    try:
        if args.command == "propose":
            version = store.propose(json.load(args.file.open()), args.source)
            result = {"proposed_version": version}
        elif args.command == "confirm":
            store.confirm(args.version, args.expected, args.source)
            result = {"confirmed_version": args.version}
        elif args.command == "decide":
            store.decide(args.id, json.load(args.payload.open()), args.source, args.supersedes)
            result = {"decision": args.id}
        elif args.command == "observe":
            store.observe(args.id, {"summary": args.summary})
            result = {"observation": args.id}
        elif args.command == "observe-json":
            payload = json.load(args.file.open())
            store.observe(args.id, payload)
            result = {"observation": args.id}
        elif args.command == "review":
            result = store.review(args.id, claude_judge, "claude-shadow-v1")
        elif args.command == "hook":
            event = json.load(sys.stdin)
            if not isinstance(event, dict):
                raise ValueError("hook 输入必须为对象")
            hook(store, event)
            return 0
        else:
            result = {"goal": store.current(), 
                     "decisions": [dict(r) for r in store.db.execute("SELECT * FROM decisions WHERE project=?", (store.project,))],
                     "reviews": [dict(r) for r in store.db.execute("SELECT * FROM reviews WHERE project=?", (store.project,))]}
        print(encode(result))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 0 if args.command == "hook" else 1
    finally:
        store.close()

if __name__ == "__main__":
    raise SystemExit(main_v2())
