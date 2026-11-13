"""Offline, synthetic-only rubric pilot. No model calls or business workspace access."""

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path


class PilotError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PilotError(message)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None,
            "expected a 64-hex SHA-256 hash")
    return value.lower()


def parse(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(PilotError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotError("expected a pure UTF-8 JSON response") from exc


def fields(obj, names):
    require(isinstance(obj, dict) and set(obj) == set(names.split()),
            "missing or unknown fields; expected: " + names)


def text(value):
    require(isinstance(value, str) and bool(value.strip()), "expected nonempty text")


def identifier(value):
    text(value)
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) is not None, "invalid ID")


def records(value, key):
    require(isinstance(value, list), "expected a list")
    ids = []
    for item in value:
        require(isinstance(item, dict) and key in item, "missing " + key)
        identifier(item[key])
        ids.append(item[key])
    require(len(set(ids)) == len(ids), "duplicate " + key)
    return set(ids)


def references(value, allowed):
    require(isinstance(value, list) and all(isinstance(x, str) for x in value),
            "references must be a list of IDs")
    require(len(value) == len(set(value)) and set(value) <= allowed, "unknown or duplicate reference")


def validate_corpus(corpus):
    require(isinstance(corpus, dict), "expected corpus object")
    version = corpus.get("schema_version")
    require(type(version) is int and version in (1, 2) and corpus.get("origin") == "synthetic",
            "only synthetic schema_version 1 or 2 is supported")
    fields(corpus, "schema_version origin baseline_framework cases evaluation_cases" +
           (" split_counts criteria_sources" if version == 2 else ""))
    expected_counts = {"train": 6, "dev": 2, "test": 4}
    if version == 2:
        expected_counts = corpus["split_counts"]
        fields(expected_counts, "train dev test")
        require(all(type(n) is int and n > 0 for n in expected_counts.values()),
                "split_counts must contain positive integers")
        sources = records(corpus["criteria_sources"], "source_id")
        require(bool(sources), "criteria_sources cannot be empty")
        for source in corpus["criteria_sources"]:
            fields(source, "source_id authority text")
            require(source["authority"] == "synthetic_fixture", "source authority must be synthetic_fixture")
            text(source["text"])
    records(corpus["baseline_framework"], "rule_id")
    for rule in corpus["baseline_framework"]:
        fields(rule, "rule_id text")
        text(rule["text"])
    records(corpus["cases"], "case_id")
    records(corpus["cases"], "paper_id")
    families = records(corpus["cases"], "family_id")
    records(corpus["cases"], "comment_id")
    require(len(families) == sum(expected_counts.values()), "incorrect distinct paper family count")
    counts = {"train": 0, "dev": 0, "test": 0}
    by_family = {}
    for case in corpus["cases"]:
        fields(case, "case_id paper_id family_id split paper_text comment_id comment_text")
        require(case["split"] in counts, "unknown split")
        counts[case["split"]] += 1
        text(case["paper_text"])
        text(case["comment_text"])
        by_family[case["family_id"]] = case
    require(counts == expected_counts, "train/dev/test family counts mismatch")
    eval_ids = records(corpus["evaluation_cases"], "case_id")
    require(len(eval_ids) == 4 * (expected_counts["dev"] + expected_counts["test"])
            and not eval_ids & {c["case_id"] for c in corpus["cases"]},
            "incorrect evaluation count or overlapping base case IDs")
    variants = {}
    paper_groups = {c["paper_id"]: (c["family_id"], c["split"]) for c in corpus["cases"]}
    for case in corpus["evaluation_cases"]:
        fields(case, "case_id paper_id family_id split variant paper_text")
        for key in ("paper_id", "family_id"):
            identifier(case[key])
        require(case["family_id"] in by_family, "unknown evaluation family")
        base = by_family[case["family_id"]]
        require(case["split"] in ("dev", "test") and case["split"] == base["split"],
                "family crosses split")
        group = (case["family_id"], case["split"])
        require(paper_groups.get(case["paper_id"], group) == group, "paper crosses family/split")
        paper_groups[case["paper_id"]] = group
        require(case["variant"] in ("defect", "repair", "alternative", "surface"), "unknown variant")
        # Case IDs must not encode a split, family, variant, or answer.
        require(not re.search(r"train|test|dev|defect|repair|alternative|surface|acceptable|issue|undetermined",
                              case["case_id"], re.I), "evaluation case_id is not opaque")
        require(case["family_id"] not in case["case_id"], "case_id leaks family")
        text(case["paper_text"])
        seen = variants.setdefault(case["family_id"], set())
        require(case["variant"] not in seen, "duplicate family variant")
        seen.add(case["variant"])
    require(set(variants) == {c["family_id"] for c in corpus["cases"] if c["split"] != "train"}
            and all(len(v) == 4 for v in variants.values()), "missing evaluation family variants")


def frozen_write(path, data):
    require(not path.is_symlink(), "linked artifact refused")
    if path.exists():
        require(path.is_file() and path.read_bytes() == data, "different content would overwrite: " + path.name)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def save_manifest(run, manifest):
    data = canonical(manifest)
    # This local checksum detects accidental edits; it is not a signature or access control.
    (run / "manifest.json").write_bytes(data)
    (run / "manifest.sha256").write_text(digest(data) + "\n", encoding="ascii")


def add_artifacts(run, manifest, files):
    for name, data in files.items():
        path = run / name
        require(not path.exists() or path.read_bytes() == data, "artifact content conflict: " + name)
    for name, data in files.items():
        frozen_write(run / name, data)
        manifest["files"][name] = digest(data)
    save_manifest(run, manifest)


def load_run(run):
    require(run.is_dir() and not run.is_symlink(), "missing or linked run directory")
    data = (run / "manifest.json").read_bytes()
    require(digest(data) == (run / "manifest.sha256").read_text(encoding="ascii").strip(),
            "manifest checksum mismatch")
    manifest = parse(data)
    require(manifest["protocol"] in ("rubric-pilot-v1", "rubric-pilot-v2"), "unknown run protocol")
    sha256_text(manifest["oracle_sha256"])
    source = Path(manifest["corpus_path"])
    require(not source.is_symlink() and digest(source.read_bytes()) == manifest["corpus_sha256"],
            "external corpus changed")
    for name, expected in manifest["files"].items():
        path = run / name
        require(not path.is_symlink() and path.is_file() and digest(path.read_bytes()) == expected,
                "frozen artifact changed: " + name)
    require((run / "corpus.raw.json").read_bytes() == source.read_bytes(), "frozen corpus mismatch")
    corpus = parse((run / "corpus.canonical.json").read_bytes())
    validate_corpus(corpus)
    require(manifest["protocol"] == "rubric-pilot-v" + str(corpus["schema_version"]),
            "corpus/run protocol mismatch")
    if corpus["schema_version"] == 2:
        require(manifest["criteria_sha256"] == digest(canonical(corpus["criteria_sources"])),
                "criteria sources changed")
    require(canonical(parse(source.read_bytes())) == canonical(corpus), "canonical corpus mismatch")
    return manifest, corpus


def stage_key(stage, arm=None, split=None):
    if stage in ("induce", "predict", "refine"):
        require(split is None, "split only applies to apply stage")
        require(arm in (None, "initial") if stage != "refine" else arm in (None, "refined"),
                "incorrect arm for stage")
        return stage
    require(stage == "apply" and arm in ("initial", "refined") and split in ("dev", "test"),
            "apply requires --arm and --split")
    return "apply-" + arm + "-" + split


def accepted(run, key):
    name = key + ".accepted.json"
    manifest = parse((run / "manifest.json").read_bytes())
    path = run / name
    require(name in manifest["files"] and path.is_file(), "accepted prerequisite missing: " + key)
    return parse(path.read_bytes())


RULE_SCHEMA = {"rules": [{"rule_id": "opaque ID", "requirement": "nonempty text",
                         "applicable_when": "nonempty text, or unknown",
                         "exceptions": "nonempty text, or none/unknown",
                         "support_comment_ids": ["training comment ID"],
                         "unknowns": "nonempty text, or none"}]}
INSTRUCTIONS = ("Use only the input below. Do not use tools, files, network, or prior conversation. "
                "Return one pure JSON object matching output_schema exactly, with no extra keys or fences. "
                "These are candidate rules for a fictional synthetic exercise, without formal authority.\n")


def legacy_prompt_payload(run, corpus, stage, arm, split):
    train = [c for c in corpus["cases"] if c["split"] == "train"]
    comments = [{"case_id": c["case_id"], "comment_id": c["comment_id"],
                 "comment_text": c["comment_text"]} for c in train]
    papers = [{"case_id": c["case_id"], "paper_text": c["paper_text"]} for c in train]
    if stage == "induce":
        return {"task": "Induce initial candidate rules from these training papers and comments.",
                "cases": papers, "training_comments": comments, "output_schema": RULE_SCHEMA}
    initial = accepted(run, "induce")
    if stage == "predict":
        return {"task": "Predict a reviewer comment for every training paper using these fixed rules.",
                "rules": initial["rules"], "cases": papers,
                "output_schema": {"predictions": [{"case_id": "each training case ID exactly once",
                                                     "predicted_comment": "nonempty text", "rule_ids": []}]}}
    if stage == "refine":
        predictions = accepted(run, "predict")
        return {"task": "Diagnose training mismatches and revise the rules once. Distinguish rule_gap, "
                        "reviewer_error, model_error, insufficient_material; do not assume every reference "
                        "comment is correct. Use only training evidence.",
                "rules": initial["rules"], "cases": papers, "training_comments": comments,
                "predictions": predictions["predictions"],
                "output_schema": {"diagnostics": [{"case_id": "training case ID", "kind":
                                                   "rule_gap|reviewer_error|model_error|insufficient_material",
                                                   "rationale": "nonempty text"}], **RULE_SCHEMA}}
    rules = initial if arm == "initial" else accepted(run, "refine")
    # Freeze the single revision before either evaluation branch is exposed.
    accepted(run, "refine")
    cases = [{"case_id": c["case_id"], "paper_text": c["paper_text"]}
             for c in corpus["evaluation_cases"] if c["split"] == split]
    cases.sort(key=lambda c: c["case_id"])
    random.Random(617103).shuffle(cases)
    return {"task": "Apply only the fixed rules to every paper. Use undetermined when material is "
                    "insufficient. rule_ids may be empty when unknown. Return each case ID exactly once.",
            "rules": rules["rules"], "cases": cases,
            "output_schema": {"decisions": [{"case_id": "each input case ID exactly once",
                                             "verdict": "issue|acceptable|undetermined", "rule_ids": [],
                                             "rationale": "nonempty text"}]}}


def prompt_payload(run, corpus, stage, arm, split):
    payload = legacy_prompt_payload(run, corpus, stage, arm, split)
    if corpus["schema_version"] == 2:
        payload["criteria_sources"] = corpus["criteria_sources"]
        payload["task"] = payload["task"].replace("Apply only the fixed rules", "Apply the criteria sources")
        payload["task"] += (" The explicit criteria_sources govern every judgment. Candidate rules are "
                            "operational aids only; if they conflict, follow the criteria sources. "
                            "Do not infer missing policy from reference comments.")
        if stage in ("induce", "refine"):
            # Copy, rather than mutate the shared v1 schema.
            payload["output_schema"] = parse(canonical(payload["output_schema"]))
            schema = payload["output_schema"]["rules"][0]
            schema["source_ids"] = ["visible criteria source ID; at least one"]
            schema["support_comment_ids"] = ["training comment ID only; may be empty"]
    return payload


V2_INSTRUCTIONS = ("The native controller may read only its single designated prompt file and write only "
                   "its single designated response file. File I/O tools are permitted solely for those "
                   "two designated paths. Do not use other tools, files, network, repository entry "
                   "points, history, or prior conversation may be accessed. This is a prompt-level I/O "
                   "constraint, not an enforced sandbox. Use only the input below. Return one pure JSON "
                   "object matching output_schema exactly, without extra keys or fences. These are "
                   "fictional synthetic criteria and candidate rules, without real formal authority.\n")


def make_prompt(run, manifest, corpus, stage, arm=None, split=None):
    key = stage_key(stage, arm, split)
    payload = canonical(prompt_payload(run, corpus, stage, arm, split))
    instructions = INSTRUCTIONS if corpus["schema_version"] == 1 else V2_INSTRUCTIONS
    data = instructions.encode("utf-8") + payload
    files = {key + ".input.json": payload, key + ".prompt.txt": data,
             key + ".prompt-record.json": canonical({"input_sha256": digest(payload),
                                                     "prompt_sha256": digest(data),
                                                     "model": "gpt-6.1-sol", "reasoning_effort": "high",
                                                     "context": "fresh", "tool_isolation": "prompt_only"})}
    add_artifacts(run, manifest, files)
    return key


def prepare(corpus_path, output, oracle_sha256):
    oracle_sha256 = sha256_text(oracle_sha256)
    corpus_path = corpus_path.resolve()
    data = corpus_path.read_bytes()
    corpus = parse(data)
    validate_corpus(corpus)
    require(not output.is_symlink(), "linked output refused")
    if (output / "manifest.json").exists():
        manifest, old = load_run(output)
        require(manifest["corpus_path"] == str(corpus_path) and canonical(old) == canonical(corpus)
                and manifest["oracle_sha256"] == oracle_sha256,
                "existing run has different input")
        make_prompt(output, manifest, old, "induce")
        return
    require(not output.exists() or not any(output.iterdir()), "output must be a new or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"protocol": "rubric-pilot-v" + str(corpus["schema_version"]), "corpus_path": str(corpus_path),
                "corpus_sha256": digest(data), "canonical_sha256": digest(canonical(corpus)),
                "oracle_sha256": oracle_sha256, "shuffle_seed": 617103, "files": {}}
    if corpus["schema_version"] == 2:
        manifest["criteria_sha256"] = digest(canonical(corpus["criteria_sources"]))
    add_artifacts(output, manifest, {"corpus.raw.json": data, "corpus.canonical.json": canonical(corpus)})
    make_prompt(output, manifest, corpus, "induce")


def validate_rules(rules, corpus):
    records(rules, "rule_id")
    require(bool(rules), "rules cannot be empty")
    comments = {c["comment_id"] for c in corpus["cases"] if c["split"] == "train"}
    for rule in rules:
        fields(rule, "rule_id requirement applicable_when exceptions support_comment_ids unknowns" +
               (" source_ids" if corpus["schema_version"] == 2 else ""))
        for key in ("requirement", "applicable_when", "exceptions", "unknowns"):
            text(rule[key])
        references(rule["support_comment_ids"], comments)
        if corpus["schema_version"] == 1:
            require(bool(rule["support_comment_ids"]), "rule needs training comment support")
        else:
            references(rule["source_ids"], {s["source_id"] for s in corpus["criteria_sources"]})
            require(bool(rule["source_ids"]), "rule needs criteria source support")


def validate_response(response, payload, corpus, stage):
    if stage in ("induce", "refine"):
        fields(response, "rules" if stage == "induce" else "diagnostics rules")
        validate_rules(response["rules"], corpus)
        if stage == "refine":
            ids = records(response["diagnostics"], "case_id")
            require(ids <= {c["case_id"] for c in corpus["cases"] if c["split"] == "train"},
                    "diagnostic references a held-out case")
            for diagnostic in response["diagnostics"]:
                fields(diagnostic, "case_id kind rationale")
                require(diagnostic["kind"] in ("rule_gap", "reviewer_error", "model_error",
                                                "insufficient_material"), "unknown diagnostic kind")
                text(diagnostic["rationale"])
        return
    name = "predictions" if stage == "predict" else "decisions"
    fields(response, name)
    ids = records(response[name], "case_id")
    require(ids == {c["case_id"] for c in payload["cases"]}, "missing or extra case IDs")
    allowed = {r["rule_id"] for r in payload["rules"]}
    for item in response[name]:
        fields(item, "case_id predicted_comment rule_ids" if stage == "predict"
               else "case_id verdict rule_ids rationale")
        references(item["rule_ids"], allowed)
        if stage == "predict":
            text(item["predicted_comment"])
        else:
            require(item["verdict"] in ("issue", "acceptable", "undetermined"), "unknown verdict")
            text(item["rationale"])


def accept(run, stage, arm, split, response_path, execution_id):
    manifest, corpus = load_run(run)
    key = stage_key(stage, arm, split)
    text(execution_id)
    require(len(execution_id) <= 500, "execution ID too long")
    data = response_path.read_bytes()
    # Count original executions, not accept submissions. A binding is immutable,
    # including failed raw output; resubmitting it cannot turn it into a new call.
    event_key = "execution-" + digest(canonical([key, execution_id]))
    event_name = event_key + ".json"
    if corpus["schema_version"] == 2:
        for _, prior in execution_records(run, manifest):
            require(prior["execution_id"] != execution_id or prior["stage"] == key,
                    "execution ID reused for another stage")
    if event_name in manifest["files"]:
        prior = parse((run / event_name).read_bytes())
        require(prior["response_sha256"] == digest(data), "execution ID already bound to different response")
        require(prior["status"] != "failed", "execution previously failed: " + prior.get("error", ""))
    event = {"stage": key, "execution_id": execution_id, "response_sha256": digest(data),
             "raw_response_bytes": len(data), "native_tokens": "unknown",
             "pure_inference_seconds": "unknown", "actual_steps": 1}
    try:
        require(key + ".prompt.txt" in manifest["files"], "generate the corresponding prompt before accept")
        payload = parse((run / (key + ".input.json")).read_bytes())
        require(canonical(payload) == canonical(prompt_payload(run, corpus, stage, arm, split)),
                "prompt prerequisites changed")
        response = parse(data)
        validate_response(response, payload, corpus, stage)
        provenance = {**event, "canonical_sha256": digest(canonical(response)),
                      "prompt_sha256": manifest["files"][key + ".prompt.txt"],
                      "input_sha256": manifest["files"][key + ".input.json"]}
        add_artifacts(run, manifest, {key + ".response.raw.json": data,
                                      key + ".accepted.json": canonical(response),
                                      key + ".execution.json": canonical(provenance),
                                      event_key + ".response.raw.json": data,
                                      event_name: canonical({**event, "status": "accepted"})})
    except (PilotError, OSError, TypeError, KeyError) as exc:
        if event_name not in manifest["files"]:
            add_artifacts(run, manifest, {event_key + ".response.raw.json": data,
                                          event_name: canonical({**event, "status": "failed", "error": str(exc)})})
        raise


def execution_records(run, manifest):
    return [(name, parse((run / name).read_bytes())) for name in manifest["files"]
            if name.startswith("execution-") and name.endswith(".json") and ".response." not in name]


STAGES = [("induce", None, None), ("predict", None, None), ("refine", None, None)] + [
    ("apply", arm, split) for arm in ("initial", "refined") for split in ("dev", "test")]


def evaluate(run, oracle_path, *, persist=True):
    manifest, corpus = load_run(run)
    raw = oracle_path.read_bytes()
    require(digest(raw) == manifest["oracle_sha256"], "oracle differs from precommitted SHA-256")
    oracle = parse(raw)
    fields(oracle, "schema_version provenance decisions")
    require(type(oracle["schema_version"]) is int and oracle["schema_version"] == 1
            and oracle["provenance"] == "synthetic_axiom_review", "incorrect oracle provenance")
    ids = records(oracle["decisions"], "case_id")
    require(ids == {c["case_id"] for c in corpus["evaluation_cases"]}, "oracle ID coverage mismatch")
    for item in oracle["decisions"]:
        fields(item, "case_id verdict policy_ids rationale disputed")
        require(item["verdict"] in ("issue", "acceptable", "undetermined"), "unknown oracle verdict")
        require(type(item["disputed"]) is bool, "disputed must be boolean")
        references(item["policy_ids"], set(item["policy_ids"]) if isinstance(item["policy_ids"], list) else set())
        for policy_id in item["policy_ids"]:
            identifier(policy_id)
        if corpus["schema_version"] == 2:
            references(item["policy_ids"], {s["source_id"] for s in corpus["criteria_sources"]})
            require(bool(item["policy_ids"]), "oracle needs visible criteria source support")
        text(item["rationale"])
    truth = {d["case_id"]: d for d in oracle["decisions"]}
    report = {"complete": True, "oracle_sha256": digest(raw), "splits": {},
              "native_tokens": "unknown", "pure_inference_seconds": "unknown",
              "raw_response_bytes": 0, "actual_steps": 0, "accepted_steps": 0, "failed_steps": 0,
              "accepted_response_bytes": 0, "failed_response_bytes": 0,
              "limitations": "Synthetic axioms only; no human gold labels, cost or labor savings measured."}
    for _, execution in execution_records(run, manifest):
        report["raw_response_bytes"] += execution["raw_response_bytes"]
        report["actual_steps"] += execution["actual_steps"]
        status = execution["status"]
        report[status + "_steps"] += 1
        report[status + "_response_bytes"] += execution["raw_response_bytes"]
    for split in ("dev", "test"):
        selected = [c["case_id"] for c in corpus["evaluation_cases"] if c["split"] == split]
        eligible = [case_id for case_id in selected if not truth[case_id]["disputed"]]
        result = {"total": len(selected), "disputed_excluded": len(selected) - len(eligible),
                  "denominator": len(eligible), "arms": {}}
        predictions = {}
        for arm in ("initial", "refined"):
            key = stage_key("apply", arm, split)
            present = key + ".accepted.json" in manifest["files"]
            report["complete"] = report["complete"] and present
            predictions[arm] = ({d["case_id"]: d["verdict"] for d in accepted(run, key)["decisions"]}
                                if present else {})
            stats = dict.fromkeys(("correct", "incorrect", "undetermined", "correct_undetermined",
                                   "failed_or_missing", "issue_missed", "acceptable_penalized"), 0)
            for case_id in eligible:
                predicted = predictions[arm].get(case_id)
                expected = truth[case_id]["verdict"]
                if predicted is None:
                    stats["failed_or_missing"] += 1
                elif predicted == "undetermined":
                    stats["undetermined"] += 1
                    stats["correct_undetermined"] += expected == "undetermined"
                elif predicted == expected:
                    stats["correct"] += 1
                else:
                    stats["incorrect"] += 1
                stats["issue_missed"] += expected == "issue" and predicted != "issue"
                stats["acceptable_penalized"] += expected == "acceptable" and predicted == "issue"
            stats["correct_total"] = stats["correct"] + stats["correct_undetermined"]
            stats["errors_total"] = len(eligible) - stats["correct_total"]
            result["arms"][arm] = stats
        paired = dict.fromkeys(("improved", "regressed", "both_correct", "both_wrong", "unpaired"), 0)
        for case_id in eligible:
            before = predictions["initial"].get(case_id)
            after = predictions["refined"].get(case_id)
            if before is None or after is None:
                paired["unpaired"] += 1
            else:
                expected = truth[case_id]["verdict"]
                outcome = (before == expected, after == expected)
                paired[{(False, True): "improved", (True, False): "regressed",
                        (True, True): "both_correct", (False, False): "both_wrong"}[outcome]] += 1
        result["paired"] = paired
        report["splits"][split] = result
    if corpus["schema_version"] == 2:
        report["complete"] = (report["complete"] and report["failed_steps"] == 0 and all(
            stage_key(*spec) + ".accepted.json" in manifest["files"] for spec in STAGES))
    # A new snapshot name preserves evaluations made before later outputs arrive.
    encoded = canonical(report)
    name = "evaluation-" + digest(encoded) + ".json"
    # Keep the independent oracle external. Other commands never read its bytes,
    # even through generic run-integrity checks; its exact input hash is recorded.
    if persist:
        add_artifacts(run, manifest, {name: encoded})
    return report


def aggregate(runs, oracle_path):
    """Read-only three-repeat screening; cases remain nested within families."""
    require(len(runs) == 3, "aggregate requires exactly three runs")
    paths = [Path(run).resolve() for run in runs]
    require(len(set(paths)) == 3, "duplicate run path")
    # Also reject directory aliases on filesystems with non-symlink aliases.
    require(all(not a.samefile(b) for i, a in enumerate(paths) for b in paths[i + 1:]),
            "duplicate run directory")
    loaded = [load_run(path) for path in paths]
    first_manifest, corpus = loaded[0]
    binding = (first_manifest["corpus_sha256"], first_manifest["canonical_sha256"],
               first_manifest["oracle_sha256"], digest(canonical(corpus.get("criteria_sources", []))))
    seen_executions = set()
    reports = []
    predictions = []
    for path, (manifest, current) in zip(paths, loaded):
        require(binding == (manifest["corpus_sha256"], manifest["canonical_sha256"],
                            manifest["oracle_sha256"], digest(canonical(current.get("criteria_sources", [])))),
                "runs have different corpus, oracle, or criteria sources")
        events = {}
        for name, event in execution_records(path, manifest):
            execution_id = event["execution_id"]
            text(execution_id)
            require(execution_id not in seen_executions, "reused execution ID across repeats or stages")
            seen_executions.add(execution_id)
            require(event["status"] in ("accepted", "failed") and event["actual_steps"] == 1,
                    "invalid execution accounting")
            expected_name = "execution-" + digest(canonical([event["stage"], execution_id])) + ".json"
            require(name == expected_name, "execution record binding mismatch")
            raw_name = name[:-5] + ".response.raw.json"
            require(raw_name in manifest["files"], "execution raw response missing")
            raw = (path / raw_name).read_bytes()
            require(event["response_sha256"] == digest(raw) and event["raw_response_bytes"] == len(raw),
                    "execution raw response binding mismatch")
            events[(event["stage"], execution_id)] = event
        for stage, arm, split in STAGES:
            key = stage_key(stage, arm, split)
            if key + ".accepted.json" not in manifest["files"]:
                continue
            require(all(key + suffix in manifest["files"] for suffix in
                        (".execution.json", ".response.raw.json", ".input.json", ".prompt.txt")),
                    "accepted stage provenance missing")
            provenance = parse((path / (key + ".execution.json")).read_bytes())
            event = events.get((key, provenance["execution_id"]))
            require(event is not None and event["status"] == "accepted", "accepted execution missing")
            raw = (path / (key + ".response.raw.json")).read_bytes()
            payload = prompt_payload(path, current, stage, arm, split)
            require(canonical(payload) == (path / (key + ".input.json")).read_bytes(),
                    "stage input differs from frozen prerequisites")
            instructions = INSTRUCTIONS if current["schema_version"] == 1 else V2_INSTRUCTIONS
            require(instructions.encode("utf-8") + canonical(payload) ==
                    (path / (key + ".prompt.txt")).read_bytes(), "stage prompt mismatch")
            response = accepted(path, key)
            validate_response(response, payload, current, stage)
            require(canonical(parse(raw)) == canonical(response) and digest(raw) == event["response_sha256"]
                    and provenance["response_sha256"] == digest(raw)
                    and provenance["canonical_sha256"] == digest(canonical(response))
                    and provenance["prompt_sha256"] == manifest["files"][key + ".prompt.txt"]
                    and provenance["input_sha256"] == manifest["files"][key + ".input.json"],
                    "accepted response provenance mismatch")
        report = evaluate(path, oracle_path, persist=False)
        report["complete"] = (report["complete"] and report["failed_steps"] == 0
                              and report["accepted_steps"] == len(STAGES) and all(
                                  stage_key(*spec) + ".accepted.json" in manifest["files"] for spec in STAGES))
        reports.append(report)
        predictions.append({(arm, split): {d["case_id"]: d["verdict"] for d in
                            accepted(path, stage_key("apply", arm, split))["decisions"]}
                            if stage_key("apply", arm, split) + ".accepted.json" in manifest["files"] else {}
                            for arm in ("initial", "refined") for split in ("dev", "test")})
    truth = {d["case_id"]: d for d in parse(oracle_path.read_bytes())["decisions"]}
    if corpus["schema_version"] == 2:
        require(not any(d["disputed"] for d in truth.values()),
                "unresolved oracle disputes block formal v2 aggregation")
    complete = all(report["complete"] for report in reports)
    differences = []
    for report in reports:
        arms = report["splits"]["test"]["arms"]
        differences.append(arms["refined"]["correct_total"] - arms["initial"]["correct_total"]
                           if report["complete"] else None)
    families = {}
    cases = []
    for case in corpus["evaluation_cases"]:
        case_id, split = case["case_id"], case["split"]
        values = {arm: [p[(arm, split)].get(case_id) for p in predictions]
                  for arm in ("initial", "refined")}
        expected = truth[case_id]["verdict"]
        paired = []
        for before, after in zip(values["initial"], values["refined"]):
            if truth[case_id]["disputed"]:
                paired.append("disputed_excluded")
            elif before is None or after is None:
                paired.append("unpaired")
            else:
                paired.append({(False, True): "improved", (True, False): "regressed",
                               (True, True): "both_correct", (False, False): "both_wrong"}[
                                   (before == expected, after == expected)])
        cases.append({"case_id": case_id, "split": split, "family_id": case["family_id"],
                      "disputed": truth[case_id]["disputed"], "oracle_verdict": expected,
                      "verdicts": values, "paired_outcomes": paired,
                      "disagreement": {arm: len(set(v)) > 1 if None not in v else None
                                       for arm, v in values.items()}})
        if split != "test":
            continue
        counts = families.setdefault(case["family_id"], [0, 0, 0])
        if truth[case_id]["disputed"]:
            continue
        expected = truth[case_id]["verdict"]
        for index in range(3):
            before, after = values["initial"][index], values["refined"][index]
            if before is None or after is None:
                counts[index] = None
            elif counts[index] is not None:
                counts[index] += int(after == expected) - int(before == expected)
    improved_families = [[family for family, deltas in families.items()
                          if deltas[index] is not None and deltas[index] > 0] for index in range(3)]
    common_improved = sorted(set.intersection(*(set(items) for items in improved_families)))
    no_harm = all(r["splits"]["test"]["arms"]["refined"]["acceptable_penalized"] <=
                  r["splits"]["test"]["arms"]["initial"]["acceptable_penalized"] and
                  r["splits"]["test"]["arms"]["refined"]["correct_undetermined"] >=
                  r["splits"]["test"]["arms"]["initial"]["correct_undetermined"] for r in reports)
    totals = {key: sum(r[key] for r in reports) for key in
              ("actual_steps", "accepted_steps", "failed_steps", "raw_response_bytes",
               "accepted_response_bytes", "failed_response_bytes")}
    return {"complete": complete, "corpus_sha256": binding[0], "oracle_sha256": binding[2],
            "criteria_sha256": binding[3], "runs": [str(path) for path in paths],
            "repeats": reports, "totals": totals, "test_match_differences": differences,
            "test_difference_min": min(differences) if complete else None,
            "test_difference_max": max(differences) if complete else None,
            "test_arm_match_ranges": {arm: {
                "min": min(r["splits"]["test"]["arms"][arm]["correct_total"] for r in reports) if complete else None,
                "max": max(r["splits"]["test"]["arms"][arm]["correct_total"] for r in reports) if complete else None}
                for arm in ("initial", "refined")},
            "test_family_differences": families, "improved_test_families": improved_families,
            "common_improved_test_families": common_improved,
            "cases": cases, "stable_positive": (all(d > 0 for d in differences) and no_harm
                                                   and all(len(items) >= 2 for items in improved_families))
                                                   if complete else None,
            "limitations": "Predefined synthetic screening only, not statistical significance or product "
                           "acceptance. Repeated cases are nested within paper families, not independent "
                           "papers. Missing or failed executions make screening incomplete. Model identity, "
                           "tokens, actual fees and pure inference time remain unknown."}


def failure_log(run, command, error):
    # A rejected destination or an unverified/tampered run grants no write scope.
    try:
        manifest, _ = load_run(run)
    except (PilotError, OSError, TypeError, KeyError):
        return
    record = canonical({"command": command, "status": "failed", "error": str(error)})
    add_artifacts(run, manifest, {"failure-" + digest(record) + ".json": record})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="validate/freeze synthetic corpus; create induce prompt")
    prep.add_argument("--corpus", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--oracle-sha256", required=True,
                      help="precommitted 64-hex oracle bytes hash; no oracle path or content is read")
    prompt = commands.add_parser("prompt", help="project a stage from accepted prerequisites")
    take = commands.add_parser("accept", help="strictly validate one raw JSON response; never retry")
    for command in (prompt, take):
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--stage", choices=("predict", "refine", "apply") if command is prompt
                             else ("induce", "predict", "refine", "apply"), required=True)
        command.add_argument("--arm", choices=("initial", "refined"))
        command.add_argument("--split", choices=("dev", "test"))
    take.add_argument("--response", type=Path, required=True)
    take.add_argument("--execution-id", required=True, help="native execution identifier; tokens/timing remain unknown")
    score = commands.add_parser("evaluate", help="offline scoring only; never passed to model prompts")
    score.add_argument("--run", type=Path, required=True)
    score.add_argument("--oracle", type=Path, required=True)
    combine = commands.add_parser("aggregate", help="read-only screening of three distinct paired repeats")
    combine.add_argument("--run", type=Path, action="append", required=True)
    combine.add_argument("--oracle", type=Path, required=True)
    combine.add_argument("--output", type=Path, help="optional immutable JSON report; otherwise stdout only")
    args = parser.parse_args(argv)
    run = args.output if args.command == "prepare" else args.run
    try:
        if args.command == "prepare":
            prepare(args.corpus, args.output, args.oracle_sha256)
        elif args.command == "prompt":
            manifest, corpus = load_run(args.run)
            make_prompt(args.run, manifest, corpus, args.stage, args.arm, args.split)
        elif args.command == "accept":
            accept(args.run, args.stage, args.arm, args.split, args.response, args.execution_id)
        elif args.command == "aggregate":
            report = aggregate(args.run, args.oracle)
            if args.output is not None:
                frozen_write(args.output, canonical(report))
            print(canonical(report).decode("utf-8"), end="")
            return 0 if report["complete"] else 2
        else:
            report = evaluate(args.run, args.oracle)
            print(canonical(report).decode("utf-8"), end="")
            return 0 if report["complete"] else 2
        print("saved " + args.command)
        return 0
    except (PilotError, OSError, TypeError, KeyError) as exc:
        if args.command != "aggregate":
            failure_log(run, args.command, exc)
        print("pilot failed: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
