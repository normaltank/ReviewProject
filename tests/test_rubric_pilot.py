"""Synthetic-only tests for the offline pilot's observable stage boundaries."""

import contextlib
import copy
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from experiments import rubric_pilot as pilot


def corpus_fixture():
    cases, evaluation = [], []
    for index in range(12):
        split = "train" if index < 6 else "dev" if index < 8 else "test"
        case = {"case_id": f"b{index:03}", "paper_id": f"p{index:03}", "family_id": f"f{index:03}",
                "split": split, "paper_text": f"SYNTHETIC_PAPER_{index}",
                "comment_id": f"c{index:03}", "comment_text": f"SECRET_COMMENT_{index}"}
        cases.append(case)
        if split != "train":
            for offset, variant in enumerate(("defect", "repair", "alternative", "surface")):
                evaluation.append({"case_id": f"q{index * 4 + offset:04}", "paper_id": case["paper_id"],
                                   "family_id": case["family_id"], "split": split, "variant": variant,
                                   "paper_text": f"SYNTHETIC_EVALUATION_{index}_{offset}"})
    return {"schema_version": 1, "origin": "synthetic", "baseline_framework":
            [{"rule_id": "a001", "text": "FORBIDDEN_A_BASELINE"}], "cases": cases,
            "evaluation_cases": evaluation}


def rules(requirement="Synthetic requirement"):
    return {"rules": [{"rule_id": "r001", "requirement": requirement,
                       "applicable_when": "synthetic material", "exceptions": "unknown",
                       "support_comment_ids": ["c000"], "unknowns": "unknown"}]}


def corpus_v2_fixture(counts=None):
    counts = counts or {"train": 2, "dev": 1, "test": 2}
    cases, evaluation = [], []
    for split, count in counts.items():
        for _ in range(count):
            index = len(cases)
            case = {"case_id": f"b{index:03}", "paper_id": f"p{index:03}", "family_id": f"f{index:03}",
                    "split": split, "paper_text": f"SYNTHETIC_PAPER_{index}",
                    "comment_id": f"c{index:03}", "comment_text": f"SECRET_COMMENT_{index}"}
            cases.append(case)
            if split != "train":
                for offset, variant in enumerate(("defect", "repair", "alternative", "surface")):
                    evaluation.append({"case_id": f"q{index * 4 + offset:04}", "paper_id": case["paper_id"],
                                       "family_id": case["family_id"], "split": split, "variant": variant,
                                       "paper_text": f"SYNTHETIC_EVALUATION_{index}_{offset}"})
    return {"schema_version": 2, "origin": "synthetic", "split_counts": counts,
            "criteria_sources": [{"source_id": "s001", "authority": "synthetic_fixture",
                                  "text": "EXPLICIT_CRITERIA: at least two synthetic settings suffice."}],
            "baseline_framework": [{"rule_id": "a001", "text": "FORBIDDEN_A_BASELINE"}],
            "cases": cases, "evaluation_cases": evaluation}


def rules_v2():
    value = rules()
    value["rules"][0].update(source_ids=["s001"], support_comment_ids=[])
    return value


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "corpus.json"
        self.run = self.root / "run"
        self.corpus = corpus_fixture()
        self.source.write_bytes(pilot.canonical(self.corpus))
        self.expected_oracle = self.oracle()
        pilot.prepare(self.source, self.run, pilot.digest(pilot.canonical(self.expected_oracle)))

    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return pilot.main(list(map(str, args)))

    def prompt(self, stage, arm=None, split=None):
        manifest, corpus = pilot.load_run(self.run)
        return pilot.make_prompt(self.run, manifest, corpus, stage, arm, split)

    def response(self, stage, value, arm=None, split=None, execution="native-test"):
        path = self.root / "response.json"
        path.write_bytes(pilot.canonical(value))
        pilot.accept(self.run, stage, arm, split, path, execution)

    def freeze_rules(self):
        self.response("induce", rules())
        self.prompt("predict")
        self.response("predict", {"predictions": [{"case_id": c["case_id"],
                       "predicted_comment": "Prediction only", "rule_ids": ["r001"]}
                      for c in self.corpus["cases"] if c["split"] == "train"]})
        self.prompt("refine")
        self.response("refine", {"diagnostics": [{"case_id": "b000", "kind": "reviewer_error",
                                                  "rationale": "Synthetic mismatch"}], **rules("Revised")})

    def apply(self, arm, split, overrides=None):
        self.prompt("apply", arm, split)
        decisions = [{"case_id": c["case_id"], "verdict": (overrides or {}).get(c["case_id"], "acceptable"),
                      "rule_ids": [], "rationale": "Synthetic rationale"}
                     for c in self.corpus["evaluation_cases"] if c["split"] == split]
        self.response("apply", {"decisions": decisions}, arm, split)

    def oracle(self):
        oracle = {"schema_version": 1, "provenance": "synthetic_axiom_review", "decisions":
                  [{"case_id": c["case_id"], "verdict": "acceptable", "policy_ids": ["s001"],
                    "rationale": "Synthetic axiom", "disputed": False}
                   for c in self.corpus["evaluation_cases"]]}
        return oracle

    def write_oracle(self, value):
        path = self.root / "oracle.json"
        path.write_bytes(pilot.canonical(value))
        return path

    def prepare_for_oracle(self, value):
        self.run = self.root / ("run-" + str(len(list(self.root.glob("run*")))))
        pilot.prepare(self.source, self.run, pilot.digest(pilot.canonical(value)))

    def test_projection_boundaries_and_stable_order(self):
        self.freeze_rules()
        for arm in ("initial", "refined"):
            for split in ("dev", "test"):
                self.prompt("apply", arm, split)
        for path in self.run.glob("*.prompt.txt"):
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("FORBIDDEN_A_BASELINE", content)
            self.assertNotIn("oracle.json", content)
            self.assertNotIn(pilot.digest(pilot.canonical(self.expected_oracle)), content)
            for index in range(6, 12):
                self.assertNotIn(f"SECRET_COMMENT_{index}", content)
            if path.name.startswith(("predict", "apply")):
                self.assertNotIn("SECRET_COMMENT_", content)
            if path.name.startswith("apply"):
                for field in ('"family_id"', '"variant"', '"comment_id"', '"split"', '"paper_id"'):
                    self.assertNotIn(field, content)
        induce = pilot.parse((self.run / "induce.input.json").read_bytes())
        predict = pilot.parse((self.run / "predict.input.json").read_bytes())
        refine = pilot.parse((self.run / "refine.input.json").read_bytes())
        self.assertEqual(induce["cases"], refine["cases"])
        self.assertEqual(induce["cases"], predict["cases"])
        self.assertEqual(induce["training_comments"], refine["training_comments"])
        self.assertEqual(len(induce["cases"]), 6)
        for payload in (induce, predict, refine):
            self.assertEqual({c["case_id"] for c in payload["cases"]},
                             {c["case_id"] for c in self.corpus["cases"] if c["split"] == "train"})
        for index in range(6, 12):
            self.assertNotIn(f"SYNTHETIC_PAPER_{index}", str(induce))
            self.assertNotIn(f"SYNTHETIC_PAPER_{index}", str(refine))
        for split in ("dev", "test"):
            initial = pilot.parse((self.run / f"apply-initial-{split}.input.json").read_bytes())
            refined = pilot.parse((self.run / f"apply-refined-{split}.input.json").read_bytes())
            self.assertEqual(initial["cases"], refined["cases"])
            self.assertNotEqual(initial["cases"], sorted(initial["cases"], key=lambda c: c["case_id"]))

    def test_corpus_structure_split_and_opaque_ids(self):
        for mutation in (lambda c: c["evaluation_cases"][0].update(split="test"),
                         lambda c: c["cases"][0].update(family_id="f001"),
                         lambda c: c["evaluation_cases"][0].update(case_id="dev_defect"),
                         lambda c: c["evaluation_cases"].pop(),
                         lambda c: c["evaluation_cases"][0].update(variant="answer"),
                         lambda c: c.update(origin="real")):
            with self.subTest(mutation=mutation):
                corpus = copy.deepcopy(self.corpus)
                mutation(corpus)
                with self.assertRaises(pilot.PilotError):
                    pilot.validate_corpus(corpus)
        corpus = copy.deepcopy(self.corpus)
        for index, case in enumerate(corpus["evaluation_cases"]):
            case["paper_id"] = f"version{index}"
        pilot.validate_corpus(corpus)  # A variant can have its own paper-version ID.

    def test_strict_json_rules_and_comment_references(self):
        for raw in (b'{"rules":[],"rules":[]}', b'```json\n{}\n```', b'{"rules":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(pilot.PilotError):
                pilot.parse(raw)
        for mutation in (lambda r: r.update(extra="bad"),
                         lambda r: r["rules"][0].update(support_comment_ids=["c006"]),
                         lambda r: r["rules"][0].update(support_comment_ids=[]),
                         lambda r: r["rules"][0].update(unknowns=[]),
                         lambda r: r["rules"].append(copy.deepcopy(r["rules"][0]))):
            value = rules()
            mutation(value)
            with self.subTest(mutation=mutation), self.assertRaises(pilot.PilotError):
                self.response("induce", value)
        self.assertFalse((self.run / "induce.accepted.json").exists())

    def test_missing_extra_duplicate_ids_and_rule_refs(self):
        self.freeze_rules()
        self.prompt("apply", "initial", "dev")
        payload = pilot.parse((self.run / "apply-initial-dev.input.json").read_bytes())
        valid = {"decisions": [{"case_id": c["case_id"], "verdict": "issue", "rule_ids": ["r001"],
                                "rationale": "Synthetic"} for c in payload["cases"]]}
        for mutation in (lambda r: r["decisions"].pop(),
                         lambda r: r["decisions"].append(copy.deepcopy(r["decisions"][0])),
                         lambda r: r["decisions"][0].update(case_id="extra"),
                         lambda r: r["decisions"][0].update(rule_ids=["unknown"]),
                         lambda r: r["decisions"][0].update(verdict="pass"),
                         lambda r: r["decisions"][0].update(score=5)):
            value = copy.deepcopy(valid)
            mutation(value)
            with self.subTest(mutation=mutation), self.assertRaises(pilot.PilotError):
                self.response("apply", value, "initial", "dev")

    def test_response_needs_prompt_and_failure_retains_raw(self):
        path = self.root / "bad.json"
        path.write_bytes(b'{"predictions": []}')
        code = self.invoke("accept", "--run", self.run, "--stage", "predict", "--response", path,
                           "--execution-id", "failed-native-call")
        self.assertEqual(code, 2)
        logs = [p for p in self.run.glob("execution-*.json") if ".response." not in p.name]
        record = pilot.parse(logs[0].read_bytes())
        self.assertEqual(record["execution_id"], "failed-native-call")
        self.assertEqual(record["stage"], "predict")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(next(self.run.glob("execution-*.response.raw.json")).read_bytes(), path.read_bytes())
        self.assertFalse((self.run / "predict.accepted.json").exists())

    def test_tamper_and_conflicting_overwrite(self):
        self.response("induce", rules())
        self.response("induce", rules())  # Exact replay is idempotent.
        with self.assertRaises(pilot.PilotError):
            self.response("induce", rules("Different"))
        with self.assertRaises(pilot.PilotError):
            self.response("induce", rules(), execution="another-call")
        path = self.run / "induce.prompt.txt"
        original = path.read_bytes()
        path.write_bytes(original + b"tampered")
        with self.assertRaises(pilot.PilotError):
            self.prompt("predict")
        path.write_bytes(original)
        frozen = self.run / "corpus.canonical.json"
        frozen_bytes = frozen.read_bytes()
        frozen.write_bytes(frozen_bytes + b" ")
        with self.assertRaises(pilot.PilotError):
            self.prompt("predict")
        frozen.write_bytes(frozen_bytes)
        self.source.write_bytes(self.source.read_bytes() + b" ")
        with self.assertRaises(pilot.PilotError):
            self.prompt("predict")

    def test_oracle_coverage_provenance_and_boolean(self):
        mutations = (lambda o: o.update(provenance="majority_vote"),
                     lambda o: o["decisions"].pop(),
                     lambda o: o["decisions"].append(copy.deepcopy(o["decisions"][0])),
                     lambda o: o["decisions"][0].update(disputed=1),
                     lambda o: o["decisions"][0].update(case_id="extra"))
        for mutation in mutations:
            value = self.oracle()
            mutation(value)
            self.prepare_for_oracle(value)
            with self.subTest(mutation=mutation), self.assertRaises(pilot.PilotError):
                pilot.evaluate(self.run, self.write_oracle(value))

    def test_paired_scoring_disputes_and_deterministic_replay(self):
        oracle = self.oracle()
        dev = [d for d in oracle["decisions"] if d["case_id"] in
               {c["case_id"] for c in self.corpus["evaluation_cases"] if c["split"] == "dev"}]
        dev[0]["disputed"] = True
        dev[1]["verdict"] = "issue"
        dev[2]["verdict"] = "undetermined"
        self.prepare_for_oracle(oracle)
        self.freeze_rules()
        self.apply("initial", "dev", {dev[2]["case_id"]: "undetermined"})
        self.apply("refined", "dev", {dev[1]["case_id"]: "issue", dev[2]["case_id"]: "undetermined",
                                         dev[3]["case_id"]: "issue"})
        self.apply("initial", "test")
        self.apply("refined", "test")
        path = self.write_oracle(oracle)
        first = pilot.evaluate(self.run, path)
        second = pilot.evaluate(self.run, path)
        self.assertEqual(first, second)
        self.assertTrue(first["complete"])
        score = first["splits"]["dev"]
        self.assertEqual(score["denominator"], 7)
        self.assertEqual(score["disputed_excluded"], 1)
        self.assertEqual(score["arms"]["initial"]["issue_missed"], 1)
        self.assertEqual(score["arms"]["refined"]["acceptable_penalized"], 1)
        self.assertEqual(score["arms"]["initial"]["correct_undetermined"], 1)
        self.assertEqual(score["paired"], {"improved": 1, "regressed": 1, "both_correct": 5,
                                          "both_wrong": 0, "unpaired": 0})
        self.assertEqual(first["actual_steps"], 7)
        self.assertEqual(first["native_tokens"], "unknown")
        self.assertFalse(list(self.run.glob("oracle*.json")))

    def test_missing_results_never_claim_complete_or_correct(self):
        oracle = self.write_oracle(self.oracle())
        report = pilot.evaluate(self.run, oracle)
        self.assertFalse(report["complete"])
        self.assertEqual(report["splits"]["test"]["arms"]["initial"]["correct_total"], 0)
        self.assertEqual(report["splits"]["test"]["arms"]["initial"]["failed_or_missing"], 16)
        self.assertEqual(self.invoke("evaluate", "--run", self.run, "--oracle", oracle), 2)

    def test_failed_executions_count_once_per_execution_and_stage(self):
        response = self.root / "raw.json"
        response.write_bytes(b"{}")

        def submit(stage, execution):
            return self.invoke("accept", "--run", self.run, "--stage", stage, "--response", response,
                               "--execution-id", execution)

        self.assertEqual(submit("induce", "call-bad"), 2)
        self.assertEqual(submit("induce", "call-bad"), 2)
        event_key = "execution-" + pilot.digest(pilot.canonical(["induce", "call-bad"]))
        original_event = (self.run / (event_key + ".json")).read_bytes()
        self.assertEqual((self.run / (event_key + ".response.raw.json")).read_bytes(), b"{}")
        response.write_bytes(pilot.canonical(rules()))
        self.assertEqual(submit("induce", "call-bad"), 2)  # Cannot repair the old execution.
        self.assertEqual((self.run / (event_key + ".json")).read_bytes(), original_event)
        self.assertEqual(submit("induce", "call-good"), 0)
        self.assertEqual(submit("induce", "call-good"), 0)
        self.prompt("predict")
        response.write_bytes(b"{}")
        self.assertEqual(submit("predict", "call-bad"), 2)  # Same ID, distinct stage binding.
        self.assertEqual(submit("predict", "call-bad"), 2)
        oracle = self.write_oracle(self.expected_oracle)
        report = pilot.evaluate(self.run, oracle)
        self.assertEqual(report["accepted_steps"], 1)
        self.assertEqual(report["failed_steps"], 2)
        self.assertEqual(report["actual_steps"], 3)
        self.assertEqual(report["failed_response_bytes"], 4)
        self.assertEqual(report["accepted_response_bytes"], len(pilot.canonical(rules())))
        self.assertEqual(report["raw_response_bytes"], len(pilot.canonical(rules())) + 4)
        self.assertEqual(pilot.evaluate(self.run, oracle), report)
        self.assertFalse(report["complete"])
        self.assertFalse((self.run / "predict.accepted.json").exists())

    def test_prepare_rejection_leaves_unverified_directories_untouched(self):
        for name, extra in (("occupied", {}), ("not-a-run", {"manifest.json": b"{}"})):
            output = self.root / name
            output.mkdir()
            (output / "user-file.txt").write_bytes(b"preserve user content")
            for filename, data in extra.items():
                (output / filename).write_bytes(data)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            code = self.invoke("prepare", "--corpus", self.source, "--output", output,
                               "--oracle-sha256", pilot.digest(pilot.canonical(self.expected_oracle)))
            self.assertEqual(code, 2)
            self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
        output = self.root / "not-created"
        self.assertEqual(self.invoke("prepare", "--corpus", self.source, "--output", output,
                                     "--oracle-sha256", "invalid-hash"), 2)
        self.assertFalse(output.exists())

    def test_oracle_hash_precommitted_before_generation(self):
        expected_hash = pilot.digest(pilot.canonical(self.expected_oracle))
        manifest, _ = pilot.load_run(self.run)
        self.assertEqual(manifest["oracle_sha256"], expected_hash)
        pilot.prepare(self.source, self.run, expected_hash.upper())  # Same bytes hash is idempotent.
        with self.assertRaises(pilot.PilotError):
            pilot.prepare(self.source, self.run, "0" * 64)
        oracle = self.write_oracle(self.expected_oracle)
        pilot.evaluate(self.run, oracle)
        oracle.write_bytes(oracle.read_bytes() + b" ")
        with self.assertRaisesRegex(pilot.PilotError, "precommitted"):
            pilot.evaluate(self.run, oracle)

    def test_both_cli_entrypoints(self):
        repo = Path(__file__).resolve().parents[1]
        for invocation in (["-m", "experiments.rubric_pilot"], ["experiments/rubric_pilot.py"]):
            result = subprocess.run([sys.executable, *invocation, "--help"], cwd=repo,
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("prepare", result.stdout)


class RepeatPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.corpus = corpus_v2_fixture()
        self.source = self.root / "corpus.json"
        self.source.write_bytes(pilot.canonical(self.corpus))
        self.oracle = {"schema_version": 1, "provenance": "synthetic_axiom_review", "decisions": [
            {"case_id": c["case_id"], "verdict": "undetermined" if c["variant"] == "surface" else "acceptable",
             "policy_ids": ["s001"], "rationale": "Synthetic explicit criterion", "disputed": False}
            for c in self.corpus["evaluation_cases"]]}
        self.oracle_path = self.root / "oracle.json"
        self.oracle_path.write_bytes(pilot.canonical(self.oracle))
        self.runs = [self.root / f"run{index}" for index in range(3)]
        for run in self.runs:
            pilot.prepare(self.source, run, pilot.digest(self.oracle_path.read_bytes()))

    def prompt(self, run, stage, arm=None, split=None):
        manifest, corpus = pilot.load_run(run)
        pilot.make_prompt(run, manifest, corpus, stage, arm, split)

    def accept(self, run, stage, value, arm=None, split=None, execution=None):
        path = self.root / "response.json"
        path.write_bytes(pilot.canonical(value))
        execution = execution or run.name + "-" + pilot.stage_key(stage, arm, split)
        pilot.accept(run, stage, arm, split, path, execution)

    def complete(self, run, improvements=None, refined_overrides=None):
        self.accept(run, "induce", rules_v2())
        self.prompt(run, "predict")
        self.accept(run, "predict", {"predictions": [
            {"case_id": c["case_id"], "predicted_comment": "Prediction", "rule_ids": ["r001"]}
            for c in self.corpus["cases"] if c["split"] == "train"]})
        self.prompt(run, "refine")
        self.accept(run, "refine", {"diagnostics": [], **rules_v2()})
        truth = {d["case_id"]: d["verdict"] for d in self.oracle["decisions"]}
        for arm in ("initial", "refined"):
            for split in ("dev", "test"):
                self.prompt(run, "apply", arm, split)
                decisions = []
                for case in self.corpus["evaluation_cases"]:
                    if case["split"] != split:
                        continue
                    verdict = truth[case["case_id"]]
                    # Miss acceptable cases conservatively in R0; do not create false penalties.
                    if arm == "initial" and split == "test" and case["case_id"] in (improvements or []):
                        verdict = "undetermined"
                    if arm == "refined":
                        verdict = (refined_overrides or {}).get(case["case_id"], verdict)
                    decisions.append({"case_id": case["case_id"], "verdict": verdict,
                                      "rule_ids": [], "rationale": "By explicit source"})
                self.accept(run, "apply", {"decisions": decisions}, arm, split)

    def improved_cases(self):
        return [c["case_id"] for c in self.corpus["evaluation_cases"]
                if c["split"] == "test" and c["variant"] == "defect"]

    def snapshot(self, run):
        return {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}

    def test_dynamic_splits_and_source_shape(self):
        full = corpus_v2_fixture({"train": 8, "dev": 2, "test": 8})
        pilot.validate_corpus(full)
        self.assertEqual(len(full["cases"]), 18)
        self.assertEqual(len(full["evaluation_cases"]), 40)
        pilot.validate_corpus(self.corpus)
        for mutation in (lambda c: c["split_counts"].update(train=3),
                         lambda c: c["split_counts"].update(train=True),
                         lambda c: c["split_counts"].update(train=0),
                         lambda c: c["split_counts"].update(extra=1),
                         lambda c: c["criteria_sources"][0].update(authority="official"),
                         lambda c: c["criteria_sources"][0].update(case_id="q0001"),
                         lambda c: c.update(criteria_sources=[]),
                         lambda c: c["evaluation_cases"][0].update(split="train"),
                         lambda c: c["evaluation_cases"].pop()):
            value = copy.deepcopy(self.corpus)
            mutation(value)
            with self.subTest(mutation=mutation), self.assertRaises(pilot.PilotError):
                pilot.validate_corpus(value)

    def test_explicit_sources_in_all_stages_and_no_hidden_fields(self):
        run = self.runs[0]
        self.complete(run)
        for stage, arm, split in pilot.STAGES:
            key = pilot.stage_key(stage, arm, split)
            payload = pilot.parse((run / (key + ".input.json")).read_bytes())
            self.assertEqual(payload["criteria_sources"], self.corpus["criteria_sources"])
            prompt = (run / (key + ".prompt.txt")).read_text(encoding="utf-8")
            self.assertIn("prompt-level I/O constraint", prompt)
            self.assertIn("single designated prompt file", prompt)
            self.assertIn("single designated response file", prompt)
            self.assertIn("if they conflict, follow the criteria sources", prompt)
            self.assertNotIn("FORBIDDEN_A_BASELINE", prompt)
            self.assertNotIn(pilot.digest(self.oracle_path.read_bytes()), prompt)
            for case in self.corpus["cases"]:
                if case["split"] != "train" or stage in ("predict", "apply"):
                    self.assertNotIn(case["comment_text"], prompt)
            for field in ('"family_id"', '"variant"', '"paper_id"', '"split"'):
                self.assertNotIn(field, prompt)
            if stage == "apply":
                self.assertNotIn('"comment_id"', prompt)
        initial = pilot.parse((run / "induce.input.json").read_bytes())
        revised = pilot.parse((run / "refine.input.json").read_bytes())
        for name in ("criteria_sources", "cases", "training_comments"):
            self.assertEqual(initial[name], revised[name])
        for split in ("dev", "test"):
            before = pilot.parse((run / f"apply-initial-{split}.input.json").read_bytes())
            after = pilot.parse((run / f"apply-refined-{split}.input.json").read_bytes())
            self.assertEqual(before["cases"], after["cases"])

    def test_rule_sources_and_training_only_support(self):
        pilot.validate_rules(rules_v2()["rules"], self.corpus)  # source-only rules are valid.
        for mutation in (lambda r: r.update(source_ids=[]),
                         lambda r: r.update(source_ids=["not_visible"]),
                         lambda r: r.update(source_ids=["s001", "s001"]),
                         lambda r: r.pop("source_ids"),
                         lambda r: r.update(support_comment_ids=["c002"])):
            value = rules_v2()
            mutation(value["rules"][0])
            with self.subTest(mutation=mutation), self.assertRaises(pilot.PilotError):
                pilot.validate_rules(value["rules"], self.corpus)

    def test_complete_aggregate_is_readonly_and_reports_family_screen(self):
        for run in self.runs:
            self.complete(run, self.improved_cases())
        snapshots = [self.snapshot(run) for run in self.runs]
        report = pilot.aggregate(self.runs, self.oracle_path)
        self.assertTrue(report["complete"])
        self.assertTrue(report["stable_positive"])
        self.assertEqual(report["test_match_differences"], [2, 2, 2])
        self.assertEqual(report["test_difference_min"], 2)
        self.assertEqual(report["test_difference_max"], 2)
        self.assertEqual(report["test_arm_match_ranges"]["refined"], {"min": 8, "max": 8})
        self.assertEqual(report["test_family_differences"], {"f003": [1, 1, 1], "f004": [1, 1, 1]})
        self.assertEqual(report["common_improved_test_families"], ["f003", "f004"])
        self.assertEqual(report["totals"]["actual_steps"], 21)
        self.assertEqual(report["totals"]["accepted_steps"], 21)
        self.assertEqual(report["totals"]["failed_steps"], 0)
        self.assertEqual(report["totals"]["raw_response_bytes"], sum(
            len(p.read_bytes()) for run in self.runs for p in run.glob("execution-*.response.raw.json")))
        self.assertEqual(len(report["cases"]), 12)
        self.assertTrue(all(not any(c["disagreement"].values()) for c in report["cases"]))
        self.assertEqual(snapshots, [self.snapshot(run) for run in self.runs])
        self.assertEqual(report, pilot.aggregate(self.runs, self.oracle_path))
        output = self.root / "aggregate.json"
        args = ["aggregate", "--oracle", str(self.oracle_path), "--output", str(output)]
        for run in self.runs:
            args += ["--run", str(run)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pilot.main(args), 0)
        self.assertEqual(output.read_bytes(), pilot.canonical(report))
        output.write_bytes(b"preserve previous report")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(pilot.main(args), 2)
        self.assertEqual(output.read_bytes(), b"preserve previous report")

    def test_family_gate_is_per_repeat_and_disagreement_is_visible(self):
        improvements = self.improved_cases()
        self.complete(self.runs[0], improvements)
        self.complete(self.runs[1], improvements[:1])
        self.complete(self.runs[2], improvements[1:])
        report = pilot.aggregate(self.runs, self.oracle_path)
        self.assertTrue(report["complete"])
        self.assertEqual(report["test_match_differences"], [2, 1, 1])
        self.assertFalse(report["stable_positive"])
        self.assertEqual(report["common_improved_test_families"], [])
        first = next(c for c in report["cases"] if c["case_id"] == improvements[0])
        self.assertTrue(first["disagreement"]["initial"])
        self.assertFalse(first["disagreement"]["refined"])
        self.assertEqual(first["paired_outcomes"], ["improved", "improved", "both_correct"])

    def test_positive_matching_cannot_override_unknown_or_false_penalty_guard(self):
        test_cases = [c for c in self.corpus["evaluation_cases"] if c["split"] == "test"]
        improvements = [c["case_id"] for c in test_cases if c["variant"] != "surface"]
        unknown = next(c["case_id"] for c in test_cases if c["variant"] == "surface")
        for label, harmed in (("unknown", unknown), ("acceptable", improvements[0])):
            runs = [self.root / f"{label}-run{index}" for index in range(3)]
            for index, run in enumerate(runs):
                pilot.prepare(self.source, run, pilot.digest(self.oracle_path.read_bytes()))
                self.complete(run, improvements, {harmed: "issue"} if index == 2 else {})
            report = pilot.aggregate(runs, self.oracle_path)
            with self.subTest(harmed=label):
                self.assertTrue(all(d > 0 for d in report["test_match_differences"]))
                self.assertFalse(report["stable_positive"])

    def test_missing_and_failed_executions_remain_incomplete_and_counted(self):
        bad = self.root / "bad.json"
        bad.write_bytes(b"{}")
        with self.assertRaises(pilot.PilotError):
            pilot.accept(self.runs[0], "induce", None, None, bad, "failed-call")
        with self.assertRaises(pilot.PilotError):
            pilot.accept(self.runs[0], "induce", None, None, bad, "failed-call")
        # Later valid work does not erase the original failed execution.
        self.complete(self.runs[0], self.improved_cases())
        report = pilot.aggregate(self.runs, self.oracle_path)
        self.assertFalse(report["complete"])
        self.assertIsNone(report["stable_positive"])
        self.assertIsNone(report["test_difference_min"])
        self.assertEqual(report["test_match_differences"], [None, None, None])
        self.assertEqual(report["totals"]["actual_steps"], 8)
        self.assertEqual(report["totals"]["failed_steps"], 1)
        self.assertEqual(report["totals"]["failed_response_bytes"], 2)
        self.assertEqual(report["repeats"][1]["splits"]["test"]["arms"]["initial"]["failed_or_missing"], 8)
        self.assertIsNone(report["cases"][0]["disagreement"]["initial"])
        for run in self.runs[1:]:
            self.complete(run, self.improved_cases())
        report = pilot.aggregate(self.runs, self.oracle_path)
        self.assertFalse(report["complete"])
        self.assertIsNone(report["stable_positive"])
        self.assertEqual(report["totals"]["actual_steps"], 22)
        self.assertEqual(report["totals"]["accepted_steps"], 21)
        self.assertEqual(report["totals"]["failed_steps"], 1)

    def test_duplicate_paths_execution_ids_and_changed_inputs_refused(self):
        with self.assertRaisesRegex(pilot.PilotError, "exactly three"):
            pilot.aggregate(self.runs[:2], self.oracle_path)
        with self.assertRaisesRegex(pilot.PilotError, "duplicate run"):
            pilot.aggregate([self.runs[0], self.runs[0] / ".", self.runs[1]], self.oracle_path)
        for run in self.runs[:2]:
            self.accept(run, "induce", rules_v2(), execution="shared-native-ID")
        with self.assertRaisesRegex(pilot.PilotError, "reused execution ID"):
            pilot.aggregate(self.runs, self.oracle_path)
        self.prompt(self.runs[0], "predict")
        with self.assertRaisesRegex(pilot.PilotError, "reused for another stage"):
            self.accept(self.runs[0], "predict", {}, execution="shared-native-ID")
        other = self.root / "other.json"
        corpus = copy.deepcopy(self.corpus)
        corpus["criteria_sources"][0]["text"] += " changed"
        other.write_bytes(pilot.canonical(corpus))
        run = self.root / "different-source"
        pilot.prepare(other, run, pilot.digest(self.oracle_path.read_bytes()))
        with self.assertRaisesRegex(pilot.PilotError, "different corpus"):
            pilot.aggregate([self.runs[0], run, self.runs[2]], self.oracle_path)
        changed_oracle = self.root / "changed-oracle-run"
        pilot.prepare(self.source, changed_oracle, "0" * 64)
        with self.assertRaisesRegex(pilot.PilotError, "different corpus"):
            pilot.aggregate([self.runs[0], changed_oracle, self.runs[2]], self.oracle_path)
        self.oracle_path.write_bytes(self.oracle_path.read_bytes() + b" ")
        with self.assertRaisesRegex(pilot.PilotError, "precommitted"):
            pilot.aggregate([self.runs[0], self.runs[2], run], self.oracle_path)

    def test_unresolved_disputed_oracle_blocks_formal_v2_aggregate(self):
        self.oracle["decisions"][0]["disputed"] = True
        self.oracle_path.write_bytes(pilot.canonical(self.oracle))
        runs = [self.root / f"disputed{index}" for index in range(3)]
        for run in runs:
            pilot.prepare(self.source, run, pilot.digest(self.oracle_path.read_bytes()))
        with self.assertRaisesRegex(pilot.PilotError, "unresolved oracle disputes"):
            pilot.aggregate(runs, self.oracle_path)

    def test_oracle_must_cite_nonempty_visible_sources(self):
        for index, policy_ids in enumerate(([], ["hidden-policy"], ["s001", "s001"])):
            oracle = copy.deepcopy(self.oracle)
            oracle["decisions"][0]["policy_ids"] = policy_ids
            path = self.root / f"bad-oracle{index}.json"
            path.write_bytes(pilot.canonical(oracle))
            run = self.root / f"bad-oracle-run{index}"
            pilot.prepare(self.source, run, pilot.digest(path.read_bytes()))
            with self.subTest(policy_ids=policy_ids), self.assertRaises(pilot.PilotError):
                pilot.evaluate(run, path, persist=False)


if __name__ == "__main__":
    unittest.main()
