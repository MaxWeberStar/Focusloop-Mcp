import subprocess
import json
import sys
from pathlib import Path

import pytest

from focusloop import Conflict, Store, hook


GOAL = {"objective": "完成 PRD", "deliverables": ["PRD"], "constraints": [], "non_goals": ["支付"]}


@pytest.fixture
def store(tmp_path: Path):
    instance = Store(tmp_path / "state.db", "a")
    version = instance.propose(GOAL, "fixture")
    instance.confirm(version, 0, "synthetic-user")
    yield instance
    instance.close()


def aligned(_: dict) -> dict:
    return {"verdict": "aligned", "category": None, "reason": "必要调研", "evidence": []}


def test_persistence_and_proposal_not_approval(store: Store):
    store.propose(GOAL | {"objective": "添加支付"}, "assistant")
    assert store.current()["payload"]["objective"] == "完成 PRD"
    path = store.db.execute("PRAGMA database_list").fetchone()[2]
    reopened = Store(Path(path), "a")
    assert reopened.version() == 1
    reopened.close()
    other = Store(Path(path), "b")
    assert other.current() is None
    other.close()


def test_version_conflicts_and_history(store: Store):
    version = store.propose(GOAL | {"objective": "用户改目标"}, "user")
    with pytest.raises(Conflict):
        store.confirm(version, 0, "user")
    store.confirm(version, 1, "user")
    assert store.db.execute("SELECT status FROM goals WHERE version=1").fetchone()[0] == "superseded"
    with pytest.raises(Conflict):
        store.decide("d", 1, {"text": "过时"}, "user")


def test_decision_replay_and_supersession(store: Store):
    store.decide("d1", 1, {"text": "延后支付"}, "user")
    store.decide("d1", 1, {"text": "延后支付"}, "user")
    with pytest.raises(Conflict):
        store.decide("d1", 1, {"text": "立即支付"}, "user")
    store.observe("before", {"summary": "调研"})
    store.decide("d2", 1, {"text": "允许支付", "supersedes": "d1"}, "user")
    store.observe("after", {"summary": "实现"})
    assert "d1" in [d["id"] for d in store.snapshot("before")["decisions"]]
    assert "d1" not in [d["id"] for d in store.snapshot("after")["decisions"]]


def test_observation_and_review_idempotency(store: Store):
    store.observe("e", {"summary": "调研"})
    store.observe("e", {"summary": "调研"})
    with pytest.raises(Conflict):
        store.observe("e", {"summary": "另一个动作"})
    first = store.review("e", aligned, "test")
    assert store.review("e", lambda _: pytest.fail("不应重复调用"), "test") == first
    assert store.version() == 1


@pytest.mark.parametrize("failure", [ValueError("invalid"), subprocess.TimeoutExpired("claude", 60)])
def test_failures_are_unknown(store: Store, failure: Exception):
    store.observe("e", {"summary": "调研"})
    def broken(_: dict) -> dict:
        raise failure
    assert store.review("e", broken, "test")["verdict"] == "unknown"


def test_fabricated_evidence_rejected(store: Store):
    store.observe("e", {"summary": "调研"})
    result = {"verdict": "suspected_drift", "category": "goal_replaced", "reason": "偏移",
              "evidence": [{"ref": "goal", "quote": "不存在的要求"}, {"ref": "observation", "quote": "调研"}]}
    assert store.review("e", lambda _: result, "test")["verdict"] == "unknown"


def test_old_version_and_change_during_review(store: Store):
    store.observe("e", {"summary": "调研"})
    def changing(snapshot: dict) -> dict:
        version = store.propose(GOAL | {"objective": "新目标"}, "user")
        store.confirm(version, 1, "user")
        return aligned(snapshot)
    assert store.review("e", changing, "test")["verdict"] == "unknown"
    assert store.review("e", lambda _: pytest.fail("旧版本不应判断"), "test2")["verdict"] == "unknown"


def test_hook_is_metadata_only_and_non_blocking(store: Store, capsys):
    event = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_use_id": "t", "tool_name": "Write", "tool_input": {"content": "secret"}}
    assert hook(store, event) is None
    hook(store, event)
    rows = store.db.execute("SELECT * FROM observations").fetchall()
    assert len(rows) == 1
    assert "secret" not in rows[0]["payload"]
    assert capsys.readouterr().out == ""
    assert store.review(rows[0]["id"], lambda _: pytest.fail("不能分析无语义元数据"), "test")["verdict"] == "unknown"


def test_decision_changed_before_and_during_review(store: Store):
    store.observe("before", {"summary": "实现登录"})
    store.decide("new", 1, {"text": "允许登录"}, "user")
    assert store.review("before", lambda _: pytest.fail("决定已变化"), "test")["verdict"] == "unknown"
    store.observe("during", {"summary": "实现登录"})
    def changing(snapshot: dict) -> dict:
        store.decide("later", 1, {"text": "再次延后登录"}, "user")
        return aligned(snapshot)
    assert store.review("during", changing, "test")["verdict"] == "unknown"


def test_subprocess_hooks_and_cli(tmp_path: Path):
    script = Path(__file__).resolve().parents[1] / "focusloop.py"
    database = tmp_path / "state.db"
    command = [sys.executable, str(script), "--db", str(database)]
    for name in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
        result = subprocess.run(command + ["hook"], input=json.dumps({"hook_event_name": name, "session_id": "s", "tool_use_id": "t", "tool_name": "Write"}), text=True, capture_output=True)
        assert result.returncode == 0
        assert result.stdout == ""
    result = subprocess.run(command + ["status"], text=True, capture_output=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["goal"] is None
    instance = Store(database, "focusloop-v1")
    assert instance.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 3
    instance.close()
