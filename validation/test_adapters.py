"""Offline regression checks for transcript normalization and multi-harness runs.

Run: python3 -m unittest discover -s validation -p 'test_*.py'
All fixtures are synthetic; no local harness data or API key is needed.
"""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch


loader = importlib.machinery.SourceFileLoader("sc", str(pathlib.Path(__file__).resolve().parents[1] / "judge-my-ai-habits"))
spec = importlib.util.spec_from_loader(loader.name, loader)
sc = importlib.util.module_from_spec(spec)
loader.exec_module(sc)


def record(typ, payload, second=0):
    return {"timestamp": f"2026-01-01T00:00:{second:02d}Z", "type": typ, "payload": payload}


def message(role, text, second=1):
    return record("response_item", {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}, second)


def completed(kind, text, second, item_id):
    return record("event_msg", {"type": "item_completed", "turn_id": "turn", "item": {
        "type": kind, "id": item_id, "content": [{"type": "Text", "text": text}]}}, second)


def usage(input=100, output=20, cached=40, reasoning=5):
    return {"input_tokens": input, "output_tokens": output, "cached_input_tokens": cached,
            "reasoning_output_tokens": reasoning, "total_tokens": input + output}


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.adapter = sc.Codex(self.root)

    def rollout(self, name, records, sid="abc", **meta):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        rows = [record("session_meta", {"id": sid, "timestamp": "2026-01-01T00:00:00Z", "cli_version": "test", **meta})] + records
        p.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"partial":')
        return p

    def test_legacy_messages_and_cumulative_tokens(self):
        rows = [message("user", "<environment_context>injected</environment_context>"),
                message("user", "# AGENTS.md instructions for a project"),
                message("developer", "instructions"), message("user", "Find the bug"),
                record("response_item", {"type": "function_call", "name": "shell", "arguments": json.dumps({"command": ["bash", "-lc", "git status"]}), "call_id": "call"}, 2),
                record("response_item", {"type": "function_call_output", "call_id": "call", "output": "PRIVATE OUTPUT"}, 3),
                message("assistant", "Fixed", 4)]
        rows += [record("event_msg", {"type": "token_count", "info": {"total_token_usage": usage()}}, i) for i in (5, 6)]
        self.rollout("sessions/old.jsonl", rows)
        session = self.adapter.sessions()[0]
        state, metrics, _ = sc.analyze(session, self.adapter.messages(session["id"]))
        self.assertEqual(metrics["user_messages"], 1)
        self.assertEqual(state["agent_actions"], ["shell: git status"])
        self.assertNotIn("PRIVATE OUTPUT", json.dumps(state))
        row = sc.base_row("test", session, [], "test")
        self.assertEqual(row["tokens_total"], 120)
        self.assertEqual(row["tokens_input"], 60)
        self.assertEqual(row["tokens_output"], 15)

    def test_modern_events_segments_and_usage_are_not_duplicated(self):
        token = record("token_usage_record", {"response_id": "resp", "usage": usage()}, 4)
        rows = [message("user", "Question"), completed("UserMessage", "Question", 1, "u"),
                message("assistant", "Answer", 3), completed("AgentMessage", "Answer", 3, "a"), token,
                record("event_msg", {"type": "token_count", "info": {"total_token_usage": usage(999)}}, 5)]
        self.rollout("sessions/a.jsonl", rows)
        self.rollout("archived_sessions/b.jsonl", rows + [record("token_usage_record", {"response_id": "resp2", "usage": usage()}, 8)], history_base={"thread_id": "abc"})
        self.root.joinpath("session_index.jsonl").write_text(json.dumps({"id": "abc", "thread_name": "A title"}))
        sessions = self.adapter.sessions()
        self.assertEqual(len(sessions), 1)
        self.assertNotIn("fork", sessions[0])
        self.assertEqual(sessions[0]["title"], "A title")
        state, metrics, _ = sc.analyze(sessions[0], self.adapter.messages("codex:abc"))
        self.assertEqual(metrics["user_messages"], 1)
        self.assertEqual(metrics["assistant_messages"], 1)
        self.assertEqual(sc.base_row("test", sessions[0], [], "test")["tokens_total"], 240)

    def test_exec_uses_executed_actions_not_wrapper_or_outputs(self):
        self.rollout("sessions/a.jsonl", [message("user", "Delegate"),
            record("response_item", {"type": "custom_tool_call", "name": "exec", "call_id": "c", "input": 'await tools.exec_command({"cmd":"codex exec task"})'}, 2),
            record("event_msg", {"type": "item_completed", "item": {"type": "CommandExecution", "id": "exec", "command": ["zsh", "-lc", "codex exec task"], "stdout": "SECRET"}}, 3),
            record("response_item", {"type": "custom_tool_call_output", "call_id": "c", "output": "SECRET"}, 4), message("assistant", "Done", 5)])
        session = self.adapter.sessions()[0]
        state, metrics, ai = sc.analyze(session, self.adapter.messages(session["id"]))
        self.assertEqual(metrics["tool_calls"], 1)
        self.assertEqual(ai, ["codex"])
        self.assertEqual(state["agent_actions"], ["shell: codex exec task"])
        self.assertNotIn("SECRET", json.dumps(state))

    def test_literal_code_fallback_and_discovery(self):
        self.assertEqual(sc.codex_code_tools("text(ALL_TOOLS.filter(x => x.name))"), [])
        parts = sc.codex_code_tools('await tools.exec_command({"cmd":"ls"}); await tools.spawn_agent({"message":"review"})')
        self.assertEqual([p["name"] for p in parts], ["shell", "subagent"])
        self.assertEqual(sc.codex_code_tools("await tools.exec_command(dynamicArgs)")[0]["name"], "execute")

    def test_tool_vocabulary_and_patch_contents(self):
        self.assertEqual(sc.codex_tool("js", {"code": "1"}, "mcp__browser")[0]["name"], "browser.js")
        self.assertEqual(sc.codex_tool("mcp__browser__click", {})[0]["name"], "browser.click")
        parts = sc.codex_tool("apply_patch", "*** Begin Patch\n*** Update File: a.py\n+PRIVATE CONTENT\n*** Add File: b.py\n*** End Patch")
        self.assertEqual([p["state"]["input"]["path"] for p in parts], ["a.py", "b.py"])
        self.assertNotIn("PRIVATE CONTENT", json.dumps(parts))
        self.assertEqual(sc.codex_event_tools({"type": "Extension", "kind": "web.search", "action": {"type": "openPage", "url": "https://example.com"}})[0]["name"], "webfetch")

    def test_temp_paths_do_not_claim_another_ai_agent(self):
        part = sc.codex_tool("shell", {"command": "cat /tmp/codex-remote-attachments/11111111-1111-1111-1111-111111111111/a.pdf"})[0]
        _, _, ai = sc.analyze({}, [{"type": "assistant", "content": [part]}])
        self.assertEqual(ai, [])

    def test_program_child_fork_and_unknown_usage(self):
        self.rollout("sessions/root.jsonl", [message("user", "Hi"), message("assistant", "Hello", 2)], source="vscode")
        self.rollout("sessions/child.jsonl", [message("assistant", "Done", 9)], sid="child", source={"subagent": {"thread_spawn": {"parent_thread_id": "abc"}}})
        self.rollout("sessions/fork.jsonl", [], sid="fork", forked_from_id="abc", source="exec")
        roots, children = sc.group_sessions(self.adapter.sessions())
        root = next(s for s in roots if s["id"] == "codex:abc")
        fork = next(s for s in roots if s["id"] == "codex:fork")
        row = sc.base_row("test", root, children[root["id"]], "test")
        self.assertEqual(row["subagent_sessions"], 1)
        self.assertEqual(row["updated_ms"], sc.iso_ms("2026-01-01T00:00:09Z"))
        self.assertIsNone(row["tokens_total"])
        self.assertEqual(row["launched_by_program"], 0)
        self.assertEqual(sc.base_row("test", fork, [], "test")["launched_by_program"], 1)
        self.assertEqual(fork["fork"]["sessionID"], "codex:abc")

    def test_metadata_only_changes_do_not_rescore(self):
        self.rollout("sessions/a.jsonl", [message("assistant", "Done", 2), record("event_msg", {"type": "thread_settings_applied"}, 50)])
        self.assertEqual(self.adapter.sessions()[0]["time"]["updated"], sc.iso_ms("2026-01-01T00:00:02Z"))

    def test_resuming_after_upgrade_keeps_legacy_turns_and_tokens(self):
        self.rollout("sessions/old.jsonl", [message("user", "Old request"), message("assistant", "Old answer", 2),
            record("event_msg", {"type": "token_count", "info": {"total_token_usage": usage()}}, 3)])
        self.rollout("sessions/new.jsonl", [message("user", "New request", 5), completed("UserMessage", "New request", 5, "u"),
            message("assistant", "New answer", 6), completed("AgentMessage", "New answer", 6, "a"),
            record("token_usage_record", {"response_id": "new", "usage": usage()}, 7),
            record("event_msg", {"type": "token_count", "info": {"total_token_usage": usage(200, 40)}}, 8)])
        session = self.adapter.sessions()[0]
        state, metrics, _ = sc.analyze(session, self.adapter.messages(session["id"]))
        self.assertEqual([u["text"] for u in state["user_messages"]], ["Old request", "New request"])
        self.assertEqual(metrics["assistant_messages"], 2)
        self.assertEqual(sc.base_row("test", session, [], "test")["tokens_total"], 240)

    def test_nested_children_roll_up_once(self):
        sessions = [{"id": "root", "time": {"created": 1000, "updated": 1000}, "tokens": {"input": 10}},
                    {"id": "child", "parentID": "root", "time": {"updated": 2000}, "tokens": {"input": 20}},
                    {"id": "grandchild", "parentID": "child", "time": {"updated": 3000}, "tokens": {"input": 30}}]
        roots, children = sc.group_sessions(sessions)
        self.assertEqual(len(roots), 1)
        row = sc.base_row("test", roots[0], children["root"], "test")
        self.assertEqual(row["subagent_sessions"], 2)
        self.assertEqual(row["tokens_total"], 60)
        self.assertEqual(row["updated_ms"], 3000)

    def test_pre_envelope_rollouts_keep_repeated_prompts_without_fabricating_usage(self):
        path = self.root / "sessions" / "ancient.jsonl"
        path.parent.mkdir()
        rows = [{"id": "old", "timestamp": "2025-09-05T16:11:52Z", "instructions": "not a user prompt"},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "continue"}]},
                {"record_type": "snapshot"},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "continue"}]},
                {"type": "function_call", "name": "shell", "call_id": "call", "arguments": '{"command":["bash","-lc","ls"]}'},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done"}]}]
        path.write_text("\n".join(json.dumps(r) for r in rows))
        session = self.adapter.sessions()[0]
        state, metrics, _ = sc.analyze(session, self.adapter.messages(session["id"]))
        self.assertEqual(session["id"], "codex:old")
        self.assertEqual(session["time"]["created"], sc.iso_ms(rows[0]["timestamp"]))
        self.assertEqual(session["time"]["updated"], int(path.stat().st_mtime * 1000))
        self.assertEqual(metrics["user_messages"], 2)
        self.assertEqual(state["agent_actions"][-1], "shell: ls")
        self.assertEqual(state["agent_final_reply"], "Done")
        self.assertIsNone(session["tokens"])

    def test_native_web_and_image_calls_are_counted_without_output_content(self):
        self.rollout("sessions/a.jsonl", [message("user", "Look up and illustrate"),
            record("response_item", {"type": "web_search_call", "id": "w", "action": None}, 2),
            record("response_item", {"type": "web_search_call", "id": "f", "action": {"type": "find_in_page", "url": "https://example.com"}}, 3),
            record("response_item", {"type": "image_generation_call", "id": "i", "result": "PRIVATE IMAGE BYTES"}, 4),
            message("assistant", "Done", 5)])
        session = self.adapter.sessions()[0]
        state, metrics, _ = sc.analyze(session, self.adapter.messages(session["id"]))
        self.assertEqual(metrics["tool_calls"], 3)
        self.assertEqual(state["agent_actions"], ["websearch: ", "webfetch: https://example.com", "imagegen: generate an image"])
        self.assertNotIn("PRIVATE IMAGE BYTES", json.dumps(state))


class MultiHarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "test.sqlite"
        self.args = argparse.Namespace(harness="all", db=str(self.db_path), machine="test", model=sc.DEFAULT_MODEL,
            dry_run=False, since=None, session=None, rescore=False, rescore_changed=False, limit=None, workers=2, open=False)
        self.calls = []

    def harness(self, name, created):
        class Adapter:
            def version(self):
                return "test"
            def sessions(self):
                return [{"id": name + ":session", "time": {"created": created, "updated": created}, "tokens": None}]
            def messages(self, sid):
                return [{"type": "user", "text": "Hi"}, {"type": "assistant", "content": [{"type": "text", "text": "Hello"}]}]
        adapter = Adapter()
        adapter.name = name
        return lambda: adapter

    def fake_score(self, adapter, jev, machine, session, children, version):
        self.calls.append(adapter.name)
        row = sc.base_row(machine, session, children, version)
        row.update(harness=adapter.name, status="scored", origin="personal_work", scorer_hash=sc.SCORER_HASH,
                   complexity=0, leverage=0, jev_model=sc.DEFAULT_MODEL)
        return row, 0

    def run_score(self, registry):
        with patch.dict(sc.HARNESSES, registry, clear=True), patch.dict("os.environ", {"TYPESAFE_API_KEY": "test"}), \
                patch.object(sc, "score_one", self.fake_score), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            sc.cmd_score(self.args)

    def test_global_limit_incremental_and_combined_dashboard(self):
        registry = {name: self.harness(name, time) for name, time in [("opencode", 1000), ("claude", 3000), ("codex", 2000)]}
        self.args.limit = 2
        self.run_score(registry)
        self.assertEqual(set(self.calls), {"claude", "codex"})
        self.args.limit = None
        self.calls.clear()
        self.run_score(registry)
        self.assertEqual(self.calls, ["opencode"])
        self.calls.clear()
        self.run_score(registry)
        self.assertEqual(self.calls, [])
        db = sc.connect(self.db_path)
        self.addCleanup(db.close)
        self.assertEqual({r["h"] for r in sc.dashboard_payload(db, self.db_path)["sessions"]}, set(registry))
        self.assertTrue(self.db_path.with_name("dashboard.html").exists())

    def test_missing_harness_is_skipped_but_explicit_selection_fails(self):
        def missing():
            raise sc.HarnessUnavailable("not installed")
        self.run_score({"opencode": missing, "codex": self.harness("codex", 1000)})
        self.assertEqual(self.calls, ["codex"])
        self.args.harness = "opencode"
        with self.assertRaises(SystemExit):
            self.run_score({"opencode": missing})

    def test_broken_harness_does_not_prevent_other_scores(self):
        def broken():
            raise RuntimeError("bad data")
        with self.assertRaisesRegex(SystemExit, "incomplete discovery"):
            self.run_score({"opencode": broken, "codex": self.harness("codex", 1000)})
        self.assertEqual(self.calls, ["codex"])

    def test_no_harness_found_fails(self):
        def missing():
            raise sc.HarnessUnavailable("not installed")
        with self.assertRaisesRegex(SystemExit, "no supported harness"):
            self.run_score({"codex": missing})

    def test_explicit_harness_does_not_discover_others(self):
        def unexpected():
            self.fail("unselected harness opened")
        self.args.harness = "codex"
        self.run_score({"opencode": unexpected, "claude": unexpected, "codex": self.harness("codex", 1000)})
        self.assertEqual(self.calls, ["codex"])

    def test_cli_defaults_to_all(self):
        with patch("sys.argv", ["judge-my-ai-habits"]), patch.object(sc, "cmd_score") as score:
            sc.main()
        self.assertEqual(score.call_args.args[0].harness, "all")
        self.assertIsNone(score.call_args.args[0].open)

    def test_scored_sessions_cost_no_jev_calls_on_rerun(self):
        stamp = {"updated": 1000}
        class Adapter:
            name = "codex"
            def version(self):
                return "test"
            def sessions(self):
                return [{"id": "codex:s", "time": {"created": 1000, "updated": stamp["updated"]}, "tokens": None}]
            def messages(self, sid):
                return []
        registry = {"codex": lambda: Adapter()}
        self.run_score(registry)
        self.assertEqual(self.calls, ["codex"])
        self.calls.clear()
        stamp["updated"] = 2000  # the session grew after it was scored
        self.run_score(registry)
        self.assertEqual(self.calls, [])
        self.args.rescore_changed = True
        self.run_score(registry)
        self.assertEqual(self.calls, ["codex"])
        self.calls.clear()
        self.args.rescore_changed = False
        self.run_score(registry)
        self.assertEqual(self.calls, [])

    def test_rescore_reasons(self):
        h = sc.SCORER_HASH
        self.assertEqual(sc.rescore_reason(None, 1), "new")
        self.assertEqual(sc.rescore_reason((1, "scored", h), 1), "scored")
        self.assertEqual(sc.rescore_reason((1, "scored", h), 2), "grown")
        self.assertEqual(sc.rescore_reason((1, "scored", h), 2, rescore_changed=True), "changed")
        self.assertEqual(sc.rescore_reason((1, "scored", "old"), 1), "questions")
        self.assertEqual(sc.rescore_reason((1, "error", h), 1), "retry")
        self.assertEqual(sc.rescore_reason((1, "empty", h), 1), "empty")
        self.assertEqual(sc.rescore_reason((1, "empty", h), 2), "recheck")
        self.assertEqual(sc.rescore_reason((1, "scored", h), 1, rescore=True), "rescore")
        self.assertEqual(sc.describe_pending({"scored": 1345, "new": 3}), "1,345 already scored, skipped; 3 new to score")


class OpenPromptTests(unittest.TestCase):
    def offer(self, choice=None, tty=True, answer=""):
        opened = []
        def fake_input(prompt):
            if isinstance(answer, BaseException):
                raise answer
            return answer
        with patch.object(sc, "open_in_browser", opened.append), patch("builtins.input", fake_input), \
                patch("sys.stdin.isatty", lambda: tty), patch("sys.stdout.isatty", lambda: tty), \
                contextlib.redirect_stderr(io.StringIO()):
            sc.offer_to_open("/tmp/dashboard.html", choice)
        return bool(opened)

    def test_enter_and_yes_open(self):
        self.assertTrue(self.offer(answer=""))
        self.assertTrue(self.offer(answer=" Y "))

    def test_no_eof_and_ctrl_c_do_not_open(self):
        self.assertFalse(self.offer(answer="n"))
        self.assertFalse(self.offer(answer=EOFError()))
        self.assertFalse(self.offer(answer=KeyboardInterrupt()))

    def test_flags_and_non_tty_never_ask(self):
        self.assertTrue(self.offer(choice=True, tty=False, answer=EOFError()))
        self.assertFalse(self.offer(choice=False, answer=""))
        self.assertFalse(self.offer(tty=False, answer=""))


if __name__ == "__main__":
    unittest.main()
