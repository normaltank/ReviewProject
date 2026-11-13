"""Synthetic approval, score-blind transport, grounding and budget regressions."""
from contextlib import closing, contextmanager
import io
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from types import ModuleType, SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch

from experiments import deepseek_trial as trial
from reviewproto.store import Workspace


class DeepSeekTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Fail closed if any test accidentally tries a real connection.
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def fixture(self, text="论述清晰。", visibility="visibility_unknown", alias="one"):
        source = self.root / (alias + ".json")
        source.write_text(json.dumps({"scores": [{"label": "创新性与科学性（1-5分）", "raw_value": "4.5"}],
            "metadata": {"name": "SYNTHETIC-IDENTITY-NEVER-SEND"},
            "sections": [{"section_id": "comments", "label": "作者不可见" if visibility == "internal_only" else "评审意见",
                          "text": text, "visibility": visibility},
                         {"section_id": "private", "label": "作者不可见", "text": "PRIVATE-NEVER-SEND", "visibility": "internal_only"}]},
            ensure_ascii=False), encoding="utf-8")
        store = Workspace(self.root / (alias + "-workspace"))
        try:
            store.run(source, "synthetic", "json")
            state = store.state()
            section = state["sections"][0]
            item = {"alias": alias, "workspace": str(store.path), "source_id": state["source"]["source_id"],
                    "section_id": section["section_id"], "source_text_sha256": trial.local.digest(text),
                    "outbound_text_sha256": trial.local.digest(text), "text": text, "redactions": [],
                    "visibility": section["visibility"]}
        finally:
            store.close()
        return item

    def approve(self, items, **changes):
        plan = {"schema_version": 1, "model": trial.MODEL, "endpoint": trial.ENDPOINT, "budget_cny": 5,
                "max_calls": 20, "max_output_tokens": 8192, "items": items}
        plan.update(changes)
        self.plan = self.root / "outbound-plan.json"
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        self.approval = self.root / "approval.json"
        fingerprint = trial.local.digest(self.plan.read_bytes())
        ledger_path = str((self.root / trial.LEDGER_FILENAME).resolve())
        self.approval.write_text(json.dumps({"schema_version": 1, "plan_sha256": fingerprint,
             "approved": True, "approved_at": "2026-11-08T00:00:00Z", "user_approval_reference": "synthetic-test-only",
             "ledger_path": ledger_path, "ledger_identity": trial.approval_ledger_identity(fingerprint, ledger_path),
             "max_cost_cny": changes.get("budget_cny", 5)}), encoding="utf-8")
        return plan

    def answer(self, content='{"extractions": []}', usage=True):
        result = {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        if usage:
            result["usage"] = {"prompt_tokens": 20, "completion_tokens": 10,
                               "prompt_cache_hit_tokens": 5, "prompt_cache_miss_tokens": 15}
        return result

    @contextmanager
    def fake_langextract(self):
        lx, core = ModuleType("langextract"), ModuleType("langextract.core")
        core.base_model = Obj(BaseLanguageModel=object)
        core.tokenizer = Obj(UnicodeTokenizer=lambda: "unicode-tokenizer")
        core.types = Obj(ScoredOutput=lambda **kwargs: Obj(**kwargs))

        def extract(**kwargs):
            self.assertEqual(kwargs["tokenizer"], "unicode-tokenizer")
            self.assertFalse(kwargs["resolver_params"]["enable_fuzzy_alignment"])
            prompt = "json: Extract opinions from this single section:\n" + kwargs["text_or_documents"]
            outputs = list(kwargs["model"].infer([prompt]))
            raw = json.loads(outputs[0][0].output)
            return Obj(extractions=[Obj(extraction_class="opinion", extraction_text=x["opinion"],
                attributes=x["opinion_attributes"], char_interval=None) for x in raw["extractions"]])

        lx.extract = Mock(side_effect=extract)
        with patch.dict(sys.modules, {"langextract": lx, "langextract.core": core}), \
             patch.object(trial.local, "examples", return_value=[]), \
             patch.object(trial, "version", return_value="synthetic"):
            yield lx

    def execute(self, answer=None, alias="one", run_id="synthetic-run", transport=None):
        self.key = Mock(return_value="synthetic-secret-key")
        self.transport = transport or Mock(return_value=answer if answer is not None else self.answer())
        with self.fake_langextract():
            return trial.run(self.plan, self.approval, alias, run_id, transport=self.transport, key_getter=self.key)

    def copy_plan_and_approval(self):
        original_plan, original_approval = self.plan.read_bytes(), self.approval.read_bytes()
        directory = self.root / "copied-approval"
        directory.mkdir()
        self.plan, self.approval = directory / self.plan.name, directory / self.approval.name
        self.plan.write_bytes(original_plan)
        self.approval.write_bytes(original_approval)
        self.assertEqual(self.plan.read_bytes(), original_plan)
        self.assertEqual(self.approval.read_bytes(), original_approval)
        return directory

    def test_approval_gate_precedes_key_model_and_network(self):
        self.approve([self.fixture()])
        self.approval.write_text('{"schema_version":1,"approved":false}', encoding="utf-8")
        with patch.dict(sys.modules, {"langextract": None}), patch.dict("os.environ", {}, clear=True), \
             self.assertRaisesRegex(ValueError, "E_APPROVAL_REQUIRED"):
            self.execute()
        self.key.assert_not_called()
        self.transport.assert_not_called()

    def test_missing_approval_and_changed_plan_refuse_before_key(self):
        self.approve([self.fixture()])
        self.plan.write_bytes(self.plan.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "E_APPROVAL_PLAN_CHANGED"):
            self.execute()
        self.key.assert_not_called()
        self.approval.unlink()
        with self.assertRaises(FileNotFoundError):
            self.execute()
        self.key.assert_not_called()

    def test_source_change_internal_section_and_hash_change_refuse(self):
        item = self.fixture()
        self.approve([item])
        source = Path(item["workspace"]) / "source.json"
        source.write_bytes(source.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "E_SOURCE_CHANGED"):
            self.execute()
        self.key.assert_not_called()
        internal = self.fixture(visibility="internal_only", alias="internal")
        self.approve([internal])
        with self.assertRaisesRegex(ValueError, "E_INTERNAL_SECTION"):
            self.execute(alias="internal")
        item = self.fixture(alias="changedhash")
        item["source_text_sha256"] = "f" * 64
        self.approve([item])
        with self.assertRaisesRegex(ValueError, "E_SECTION_CHANGED"):
            self.execute(alias="changedhash")

    def test_redactions_only_permitted_ranges_and_same_codepoint_length(self):
        item = self.fixture("张三😀认为论述清晰。")
        item.update(text="□□😀认为论述清晰。", redactions=[{"start": 0, "end": 2, "category": "name"}])
        item["outbound_text_sha256"] = trial.local.digest(item["text"])
        self.approve([item])
        trial.validate_plan(self.plan, self.approval, "one")
        item["text"] = item["text"].replace("清晰", "模糊")
        item["outbound_text_sha256"] = trial.local.digest(item["text"])
        self.approve([item])
        with self.assertRaisesRegex(ValueError, "E_REDACTION_OUTSIDE"):
            self.execute()
        item["text"] += "x"
        item["outbound_text_sha256"] = trial.local.digest(item["text"])
        self.approve([item])
        with self.assertRaisesRegex(ValueError, "E_REDACTION_LENGTH"):
            self.execute()

    def extraction(self, quote, **changes):
        attrs = {key: [] if key in trial.local.LIST_ATTRIBUTES else "unknown" for key in trial.local.ATTRIBUTES["opinion"]}
        attrs.update(changes)
        return {"opinion": quote, "opinion_attributes": attrs}

    def test_mask_quotes_refused_original_offsets_retained_for_safe_quotes(self):
        item = self.fixture("张三认为论述清晰。")
        item.update(text="□□认为论述清晰。", redactions=[{"start": 0, "end": 2, "category": "name"}])
        item["outbound_text_sha256"] = trial.local.digest(item["text"])
        self.approve([item])
        content = json.dumps({"extractions": [self.extraction(item["text"]), self.extraction("论述清晰。", direction="positive")]}, ensure_ascii=False)
        result = self.execute(self.answer(content))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(trial.summary_outcome(result), "partial")
        self.assertIn("E_QUOTE_REDACTED", result["errors"])
        self.assertEqual(len(result["candidates"]), 1)
        evidence = result["candidates"][0]["evidence"][0]
        self.assertEqual((evidence["start"], evidence["end"]), (4, 9))
        self.assertEqual(evidence["source_id"], item["source_id"])
        self.assertEqual(evidence["quote"], "论述清晰。")

    def test_nested_quote_into_mask_also_rejects_the_candidate(self):
        item = self.fixture("张三提出建议。论述清晰。")
        item.update(text="□□提出建议。论述清晰。", redactions=[{"start": 0, "end": 2, "category": "name"}])
        item["outbound_text_sha256"] = trial.local.digest(item["text"])
        self.approve([item])
        content = json.dumps({"extractions": [self.extraction("论述清晰。", reason_quotes=["□□提出建议。"])]}, ensure_ascii=False)
        result = self.execute(self.answer(content))
        self.assertEqual(result["candidates"], [])
        self.assertIn("E_QUOTE_REDACTED", result["errors"])

    def test_private_permission_cannot_be_forged_in_plan(self):
        item = self.fixture(visibility="internal_only")
        item["visibility"] = "visibility_unknown"
        self.approve([item])
        with self.assertRaisesRegex(ValueError, "E_INTERNAL_SECTION"):
            self.execute()
        self.key.assert_not_called()

    def test_correct_model_json_mode_scoreblind_and_no_secret_logs(self):
        item = self.fixture()
        self.approve([item])
        result = self.execute()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(trial.summary_outcome(result), "zero_candidates")
        body, key = self.transport.call_args.args
        payload = json.loads(body)
        self.assertEqual(key, "synthetic-secret-key")
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["temperature"], 0)
        for forbidden in (b"4.5", b"SYNTHETIC-IDENTITY", b"PRIVATE-NEVER-SEND", key.encode()):
            self.assertNotIn(forbidden, body)
        self.assertNotIn("tools", payload)
        self.assertTrue(result["config"]["score_blind"])
        for path in (Path(item["workspace"]) / "model-artifacts").rglob("*.json"):
            self.assertNotIn(key, path.read_text(encoding="utf-8"))
        call = json.loads((Path(item["workspace"]) / "model-artifacts/synthetic-run/response-001.json").read_text(encoding="utf-8"))
        self.assertEqual((trial.INPUT_HIT, trial.INPUT_MISS, trial.OUTPUT), (40, 2000, 8000))
        self.assertAlmostEqual(call["estimated_peak_cost_cny"], (5 * 40 + 15 * 2000 + 10 * 8000) / trial.NANO)
        self.assertNotIn("actual_cost", call)

    def test_blank_is_failure_legitimate_empty_is_zero(self):
        self.approve([self.fixture()])
        for content in ("  \n", "", '{"extractions": []}', '{"wrong": []}', "broken"):
            with self.subTest(content=content):
                result = self.execute(self.answer(content), run_id="r" + str(abs(hash(content))))
                self.assertEqual(result["status"], "complete" if content == '{"extractions": []}' else "failed")
                self.assertEqual(trial.summary_outcome(result), "zero_candidates" if content == '{"extractions": []}' else "failed")
                if not content.strip():
                    self.assertIn("E_MODEL_BLANK_CONTENT", result["errors"])

    def test_failure_keeps_reservation_and_blocks_other_item(self):
        one, two = self.fixture(), self.fixture(alias="two")
        self.approve([one, two])
        result = self.execute(transport=Mock(side_effect=OSError("synthetic-secret-key must not leak")))
        self.assertEqual(result["status"], "failed")
        db = sqlite3.connect(self.root / "deepseek-budget.sqlite3")
        self.addCleanup(db.close)
        reserved, cost, status = db.execute("SELECT reserved,cost,status FROM calls").fetchone()
        self.assertGreater(reserved, 0)
        self.assertIsNone(cost)
        self.assertEqual(status, "unknown")
        result = self.execute(alias="two", run_id="second")
        self.assertIn("E_USAGE_UNKNOWN_STOP", result["errors"])
        self.key.assert_not_called()
        self.transport.assert_not_called()

    def test_cross_item_call_and_budget_limits_do_not_reset(self):
        one, two = self.fixture(), self.fixture(alias="two")
        self.approve([one, two], max_calls=1)
        self.execute()
        result = self.execute(alias="two", run_id="second")
        self.assertIn("E_MAX_CALLS", result["errors"])
        self.transport.assert_not_called()
        directory = self.root / "independent-budget"
        directory.mkdir()
        ledger = trial.Ledger(directory / trial.LEDGER_FILENAME, "synthetic-plan", 150_000_000, 20)
        ident, reserved = ledger.reserve("one", "a", 10, 8192)
        self.assertEqual(reserved, (10 + trial.CHAT_BYTE_ALLOWANCE) * 2000 + 8192 * 8000)
        self.assertGreater(reserved, 90_000_000)
        ledger.settle(ident, {"prompt_tokens": 15_000, "completion_tokens": 8192})
        with self.assertRaisesRegex(ValueError, "E_BUDGET_EXHAUSTED"):
            trial.Ledger(directory / trial.LEDGER_FILENAME, "synthetic-plan", 150_000_000, 20).reserve("two", "b", 10, 8192)

    def test_pending_transaction_blocks_second_process_and_unknown_usage(self):
        ledger = trial.Ledger(self.root / trial.LEDGER_FILENAME, "synthetic-plan", 5 * trial.NANO, 20)
        ident, reserved = ledger.reserve("one", "a", 10, 8192)
        second = trial.Ledger(self.root / trial.LEDGER_FILENAME, "synthetic-plan", 5 * trial.NANO, 20)
        with self.assertRaisesRegex(ValueError, "E_USAGE_UNKNOWN_STOP"):
            second.reserve("two", "b", 10, 8192)
        self.assertEqual(ledger.settle(ident, None), ("unknown", None))
        with self.assertRaisesRegex(ValueError, "E_USAGE_UNKNOWN_STOP"):
            second.reserve("two", "b", 10, 8192)

    def test_copied_plan_approval_reuses_exhausted_call_ledger(self):
        self.approve([self.fixture()], max_calls=1)
        self.assertEqual(self.execute()["status"], "complete")
        copied = self.copy_plan_and_approval()
        result = self.execute(run_id="copied-run")
        self.assertIn("E_MAX_CALLS", result["errors"])
        self.transport.assert_not_called()
        self.key.assert_not_called()
        self.assertFalse((copied / trial.LEDGER_FILENAME).exists())
        with closing(sqlite3.connect(self.root / trial.LEDGER_FILENAME)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM calls").fetchone()[0], 1)

    def test_copied_plan_approval_cannot_reset_unknown_usage_stop(self):
        self.approve([self.fixture()])
        first = self.execute(self.answer(usage=False))
        self.assertIn("E_USAGE_UNKNOWN_STOP", first["errors"])
        copied = self.copy_plan_and_approval()
        result = self.execute(run_id="copied-run")
        self.assertIn("E_USAGE_UNKNOWN_STOP", result["errors"])
        self.transport.assert_not_called()
        self.key.assert_not_called()
        self.assertFalse((copied / trial.LEDGER_FILENAME).exists())

    def test_copied_plan_approval_cannot_reset_peak_cost_budget(self):
        self.approve([self.fixture()], budget_cny=0.16)
        answer = self.answer()
        answer["usage"] = {"prompt_tokens": 10_000, "completion_tokens": 8192}
        first = self.execute(answer)
        self.assertEqual(first["status"], "complete")
        with trial.Ledger(self.root / trial.LEDGER_FILENAME, trial.local.digest(self.plan.read_bytes()),
                          160_000_000, 20).connect() as db:
            self.assertEqual(db.execute("SELECT status,cost FROM calls").fetchone(), ("known", 85_536_000))
        copied = self.copy_plan_and_approval()
        result = self.execute(run_id="copied-run")
        self.assertIn("E_BUDGET_EXHAUSTED", result["errors"])
        self.transport.assert_not_called()
        self.key.assert_not_called()
        self.assertFalse((copied / trial.LEDGER_FILENAME).exists())

    def test_approval_requires_canonical_absolute_fixed_ledger_identity(self):
        self.approve([self.fixture()])
        approved = json.loads(self.approval.read_text(encoding="utf-8"))
        cases = [("missing_path", {k: v for k, v in approved.items() if k != "ledger_path"}, "E_APPROVAL_LEDGER_PATH"),
                 ("missing_identity", {k: v for k, v in approved.items() if k != "ledger_identity"}, "E_APPROVAL_LEDGER_IDENTITY"),
                 ("wrong_identity", dict(approved, ledger_identity="f" * 64), "E_APPROVAL_LEDGER_IDENTITY"),
                 ("moved_path", dict(approved, ledger_path=str((self.root / "other" / trial.LEDGER_FILENAME).resolve())), "E_APPROVAL_LEDGER_IDENTITY"),
                 ("relative", dict(approved, ledger_path=trial.LEDGER_FILENAME), "E_APPROVAL_LEDGER_PATH"),
                 ("noncanonical", dict(approved, ledger_path=str(self.root / "other" / ".." / trial.LEDGER_FILENAME)), "E_APPROVAL_LEDGER_PATH"),
                 ("wrong_name", dict(approved, ledger_path=str((self.root / "another.sqlite3").resolve())), "E_APPROVAL_LEDGER_PATH")]
        for name, changed, code in cases:
            with self.subTest(name=name):
                self.approval.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, code):
                    self.execute(run_id=name)
                self.key.assert_not_called()
                self.transport.assert_not_called()
                self.assertFalse((self.root / trial.LEDGER_FILENAME).exists())

    def test_changed_ledger_binding_during_run_refuses_before_reservation(self):
        self.approve([self.fixture()])
        key, transport = Mock(return_value="synthetic-secret-key"), Mock(return_value=self.answer())
        with self.fake_langextract() as lx:
            extract = lx.extract.side_effect

            def change_binding(**kwargs):
                approval = json.loads(self.approval.read_text(encoding="utf-8"))
                other = self.root / "other-ledger"
                other.mkdir()
                approval["ledger_path"] = str((other / trial.LEDGER_FILENAME).resolve())
                approval["ledger_identity"] = trial.approval_ledger_identity(approval["plan_sha256"], approval["ledger_path"])
                self.approval.write_text(json.dumps(approval), encoding="utf-8")
                return extract(**kwargs)

            lx.extract.side_effect = change_binding
            result = trial.run(self.plan, self.approval, "one", "changed-binding", transport=transport, key_getter=key)
        self.assertIn("E_APPROVAL_LEDGER_CHANGED", result["errors"])
        key.assert_not_called()
        transport.assert_not_called()
        self.assertFalse((self.root / "other-ledger" / trial.LEDGER_FILENAME).exists())
        with trial.Ledger(self.root / trial.LEDGER_FILENAME, trial.local.digest(self.plan.read_bytes()), 5 * trial.NANO, 20).connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM calls").fetchone()[0], 0)

    def test_no_usage_stops_following_windows(self):
        self.approve([self.fixture("甲" * 400 + "\n" + "乙" * 400)])
        result = self.execute(self.answer(usage=False))
        self.assertEqual(self.transport.call_count, 1)
        self.assertIn("E_USAGE_UNKNOWN_STOP", result["errors"])
        self.assertEqual(result["status"], "failed")

    def test_http_error_body_is_retained_without_secret_or_retry(self):
        item = self.fixture()
        self.approve([item])
        error = trial.urllib.error.HTTPError(trial.ENDPOINT, 429, "synthetic-error", {},
                    io.BytesIO(b'{"error":"synthetic-secret-key"}'))
        opener = Mock()
        opener.open.side_effect = error
        with patch.object(trial.urllib.request, "build_opener", return_value=opener):
            result = self.execute(transport=trial.official_post)
        self.assertEqual(opener.open.call_count, 1)
        self.assertIn("E_DEEPSEEK_HTTP", result["errors"])
        response = (Path(item["workspace"]) / "model-artifacts/synthetic-run/response-001.json").read_text(encoding="utf-8")
        self.assertNotIn("synthetic-secret-key", response)
        self.assertIn("SECRET_REMOVED", response)
        self.assertEqual(json.loads(response)["answer"]["http_status"], 429)

    def test_redirect_and_proxy_disabled(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = trial.ENDPOINT
        response.read.return_value = json.dumps(self.answer()).encode()
        opener = Mock()
        opener.open.return_value = response
        with patch.object(trial.urllib.request, "build_opener", return_value=opener) as build:
            trial.official_post(b"{}", "synthetic-secret")
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], trial.local.NoRedirect)
        self.assertIsNone(build.call_args.args[1].redirect_request(None, None, None, None, None, None))
        self.assertEqual(opener.open.call_args.args[0].full_url, trial.ENDPOINT)

    def test_produced_payload_imports_through_real_workspace_for_all_outcomes(self):
        item = self.fixture()
        self.approve([item])
        cases = [("complete", [self.extraction("论述清晰。")], "complete", 1),
                 ("empty", [], "zero_candidates", 0),
                 ("partial", [self.extraction("论述清晰。"), self.extraction("不存在的合成引文。")], "partial", 1),
                 ("failed", None, "failed", 0)]
        for run_id, extractions, expected, accepted in cases:
            with self.subTest(outcome=expected):
                content = json.dumps({"extractions": extractions}, ensure_ascii=False) if extractions is not None else "   "
                result = self.execute(self.answer(content), run_id=run_id)
                self.assertEqual(result["status"], "failed" if expected == "failed" else "complete")
                self.assertEqual(trial.summary_outcome(result), expected)
                store = Workspace(Path(item["workspace"]))
                try:
                    state = store.import_extractions(input_path=Path(item["workspace"]) / "model-artifacts" / run_id / "candidates.json")
                    record = next(r for r in state["extraction_runs"] if r["run_id"] == run_id)
                    self.assertEqual(record["status"], expected)
                    self.assertEqual(len(record["accepted_ids"]), accepted)
                    self.assertEqual(record["rejected"], [])
                    self.assertEqual(record["errors"], result["errors"])
                    self.assertTrue(all(c["status"] == "pending_review" for c in state["candidates"]
                                        if c["candidate_id"] in record["accepted_ids"]))
                finally:
                    store.close()
                reopened = Workspace(Path(item["workspace"]))
                try:
                    persisted = next(r for r in reopened.state()["extraction_runs"] if r["run_id"] == run_id)
                    self.assertEqual(persisted["status"], expected)
                finally:
                    reopened.close()

    def test_call_timing_uses_monotonic_on_success_and_failure(self):
        item = self.fixture()
        self.approve([item])
        cases = [("timed-success", Mock(return_value=self.answer())),
                 ("timed-failure", Mock(side_effect=OSError("synthetic-secret-key")))]
        for run_id, send in cases:
            with self.subTest(run_id=run_id), patch.object(trial.time, "monotonic", side_effect=[100.0, 102.5]):
                result = self.execute(run_id=run_id, transport=send)
                record = json.loads((Path(item["workspace"]) / "model-artifacts" / run_id / "response-001.json").read_text(encoding="utf-8"))
                self.assertEqual(record["seconds"], 2.5)
                self.assertIsInstance(record["started_at"], str)
                self.assertIsInstance(record["finished_at"], str)
                self.assertLessEqual(record["started_at"], record["finished_at"])
                self.assertLessEqual(result["config"]["started_at"], result["config"]["finished_at"])
                self.assertNotIn("synthetic-secret-key", json.dumps(record))


if __name__ == "__main__":
    unittest.main()
