"""Explicitly approved, score-blind DeepSeek comparison using the shared local adapter.

No discovery, retries, redirects, proxies, tools or provider fallback. This CLI
never imports candidates: an editor can inspect model-artifacts before ingestion.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import version
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments import extract_local as local

MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"
PRICING_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
# Integer nano-CNY, using published peak prices, not a statement of billing.
NANO = 1_000_000_000
INPUT_MISS = 2_000
INPUT_HIT = 40
OUTPUT = 8_000
CHAT_BYTE_ALLOWANCE = 16_384
LEDGER_FILENAME = "deepseek-budget.sqlite3"


def require(condition, code):
    if not condition:
        raise ValueError(code)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def money(value):
    try:
        amount = Decimal(str(value))
        require(amount.is_finite() and amount > 0 and amount <= 5, "E_BUDGET")
        return int(amount * NANO)
    except (ArithmeticError, TypeError):
        raise ValueError("E_BUDGET") from None


def approval_ledger_identity(plan_hash, ledger_path):
    """Bind an approval to one canonical ledger, independently of its location.

    This digest detects inconsistent approval fields; the local approval file
    remains the authorization record, not a cryptographic signature.
    """
    value = str(ledger_path)
    path = Path(value)
    require(path.is_absolute() and path.name == LEDGER_FILENAME, "E_APPROVAL_LEDGER_PATH")
    require(value == str(path.resolve()), "E_APPROVAL_LEDGER_PATH")
    return local.digest(plan_hash + "\n" + value)


def validate_plan(plan_path, approval_path, alias):
    """Approval is checked before loading a workspace, a model, or a secret."""
    plan_path = Path(plan_path).resolve()
    raw = plan_path.read_bytes()
    plan_hash = local.digest(raw)
    plan = json.loads(raw)
    approval = load_json(approval_path)
    require(isinstance(approval, dict) and approval.get("schema_version") == 1
            and approval.get("approved") is True, "E_APPROVAL_REQUIRED")
    require(approval.get("plan_sha256") == plan_hash, "E_APPROVAL_PLAN_CHANGED")
    require(isinstance(approval.get("ledger_path"), str), "E_APPROVAL_LEDGER_PATH")
    ledger_path = Path(approval["ledger_path"])
    ledger_identity = approval_ledger_identity(plan_hash, approval["ledger_path"])
    require(approval.get("ledger_identity") == ledger_identity, "E_APPROVAL_LEDGER_IDENTITY")
    require(isinstance(approval.get("approved_at"), str) and approval["approved_at"].strip()
            and isinstance(approval.get("user_approval_reference"), str)
            and approval["user_approval_reference"].strip(), "E_APPROVAL_REFERENCE")
    require(isinstance(plan, dict) and plan.get("schema_version") == 1, "E_PLAN_SCHEMA")
    require(plan.get("model") == MODEL and plan.get("endpoint") == ENDPOINT, "E_OFFICIAL_ENDPOINT_MODEL")
    cap = min(money(plan.get("budget_cny")), money(approval.get("max_cost_cny")))
    require(type(plan.get("max_calls")) is int and 1 <= plan["max_calls"] <= 20, "E_CALL_LIMIT")
    require(type(plan.get("max_output_tokens")) is int and 256 <= plan["max_output_tokens"] <= 8192,
            "E_OUTPUT_LIMIT")
    items = plan.get("items")
    require(isinstance(items, list) and items, "E_PLAN_ITEMS")
    aliases = set()
    for entry in items:
        require(isinstance(entry, dict) and isinstance(entry.get("alias"), str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", entry["alias"])
                and entry["alias"] not in aliases, "E_PLAN_ALIAS")
        aliases.add(entry["alias"])
        require(entry.get("visibility") in {"visibility_unknown", "author_visible"}, "E_INTERNAL_SECTION")
        require(isinstance(entry.get("text"), str) and local.digest(entry["text"]) == entry.get("outbound_text_sha256"),
                "E_OUTBOUND_HASH")
        require(isinstance(entry.get("workspace"), str) and entry["workspace"], "E_PLAN_WORKSPACE")
        require(isinstance(entry.get("redactions"), list), "E_REDACTIONS")
        previous = 0
        for span in entry["redactions"]:
            require(isinstance(span, dict) and type(span.get("start")) is int and type(span.get("end")) is int
                    and previous <= span["start"] < span["end"] <= len(entry["text"])
                    and isinstance(span.get("category"), str) and span["category"].strip(), "E_REDACTIONS")
            previous = span["end"]
    require(alias in aliases, "E_ITEM_SELECTION")
    item = next(entry for entry in items if entry["alias"] == alias)
    workspace = (plan_path.parent / item["workspace"]).resolve()
    require((workspace / "review.sqlite3").is_file(), "E_WORKSPACE_EMPTY")
    from reviewproto.core import ReviewError
    from reviewproto.store import Workspace
    try:
        store = Workspace(workspace)
        try:
            state = store.state()
        finally:
            store.close()
    except ReviewError as error:
        raise ValueError(str(error)) from None
    require(item.get("source_id") == state["source"]["source_id"] == state["source"]["sha256"], "E_SOURCE_MISMATCH")
    sections = [s for s in state["sections"] if s["section_id"] == item.get("section_id")]
    require(len(sections) == 1, "E_SECTION_SELECTION")
    section = sections[0]
    require(section["visibility"] in {"visibility_unknown", "author_visible"}
            and section["visibility"] == item["visibility"], "E_INTERNAL_SECTION")
    require(local.digest(section["text"]) == item.get("source_text_sha256"), "E_SECTION_CHANGED")
    require(len(section["text"]) == len(item["text"]), "E_REDACTION_LENGTH")
    cursor = 0
    for span in item["redactions"]:
        require(section["text"][cursor:span["start"]] == item["text"][cursor:span["start"]], "E_REDACTION_OUTSIDE")
        cursor = span["end"]
    require(section["text"][cursor:] == item["text"][cursor:], "E_REDACTION_OUTSIDE")
    return plan, item, section, workspace, plan_hash, cap, ledger_path, ledger_identity


def reservation_amount(body_bytes, max_output_tokens):
    """Conservative nano-CNY hold shared by preflight and atomic reservation."""
    return (body_bytes + CHAT_BYTE_ALLOWANCE) * INPUT_MISS + max_output_tokens * OUTPUT


class Ledger:
    """One transactionally reserved budget for every item/process in a plan."""

    def __init__(self, path, plan_hash, cap, max_calls):
        self.path = Path(path)
        self.plan_hash, self.cap, self.max_calls = plan_hash, cap, max_calls
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id=1), plan_hash TEXT, cap INTEGER, max_calls INTEGER)")
            db.execute("CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, alias TEXT, run_id TEXT, reserved INTEGER, cost INTEGER, status TEXT, usage TEXT)")
            db.execute("INSERT OR IGNORE INTO meta VALUES (1, ?, ?, ?)", (plan_hash, cap, max_calls))
            require(db.execute("SELECT plan_hash,cap,max_calls FROM meta WHERE id=1").fetchone()
                    == (plan_hash, cap, max_calls), "E_LEDGER_PLAN_CHANGED")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, alias, run_id, body_bytes, max_output_tokens):
        # UTF-8 bytes upper-bound ordinary text tokenization; allowance covers
        # chat framing. Keep this conservative reservation if usage is unknown.
        reserved = reservation_amount(body_bytes, max_output_tokens)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT reserved,cost,status FROM calls").fetchall()
            require(not any(status != "known" for _, _, status in rows), "E_USAGE_UNKNOWN_STOP")
            require(len(rows) < self.max_calls, "E_MAX_CALLS")
            require(sum(cost if cost is not None else hold for hold, cost, _ in rows) + reserved <= self.cap,
                    "E_BUDGET_EXHAUSTED")
            call_id = db.execute("INSERT INTO calls(alias,run_id,reserved,status) VALUES (?,?,?,'pending')",
                                 (alias, run_id, reserved)).lastrowid
        return call_id, reserved

    def check_available(self, body_sizes, max_output_tokens):
        """Read-only preflight; reserve remains the authoritative atomic gate."""
        with self.connect() as db:
            rows = db.execute('SELECT reserved,cost,status FROM calls').fetchall()
        require(not any(status != 'known' for _, _, status in rows), 'E_USAGE_UNKNOWN_STOP')
        require(len(rows) + len(body_sizes) <= self.max_calls, 'E_MAX_CALLS')
        total = sum(reservation_amount(size, max_output_tokens) for size in body_sizes)
        require(sum(cost if cost is not None else hold for hold, cost, _ in rows) + total <= self.cap, 'E_BUDGET_EXHAUSTED')

    def settle(self, call_id, usage):
        cost = None
        if isinstance(usage, dict):
            prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
            if type(prompt) is int and prompt >= 0 and type(completion) is int and completion >= 0:
                hit = usage.get("prompt_cache_hit_tokens", 0)
                miss = usage.get("prompt_cache_miss_tokens", prompt - hit if type(hit) is int else -1)
                if type(hit) is int and type(miss) is int and min(hit, miss) >= 0 and hit + miss == prompt:
                    cost = hit * INPUT_HIT + miss * INPUT_MISS + completion * OUTPUT
        with self.connect() as db:
            reserved = db.execute("SELECT reserved FROM calls WHERE id=?", (call_id,)).fetchone()[0]
            status = "known" if cost is not None and cost <= reserved else "unknown"
            db.execute("UPDATE calls SET cost=?,status=?,usage=? WHERE id=?",
                       (cost, status, json.dumps(usage), call_id))
        return status, cost


def official_post(body, key):
    # Exact endpoint constant, default TLS certificate validation, no proxies or redirects.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), local.NoRedirect())
    request = urllib.request.Request(ENDPOINT, data=body,
              headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    try:
        with opener.open(request, timeout=900) as response:
            require(response.geturl() == ENDPOINT, "E_REDIRECT")
            raw = response.read(16_000_001)
            require(len(raw) <= 16_000_000, "E_RESPONSE_TOO_LARGE")
            try:
                return json.loads(raw)
            except ValueError:
                return {"transport_error": "E_RESPONSE_JSON", "body": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as error:
        # Preserve error responses only in the trusted artifacts; never print
        # provider messages or exception strings that could echo private data.
        try:
            raw = error.read(16_000_000)
        finally:
            error.close()
        return {"transport_error": "E_DEEPSEEK_HTTP", "http_status": error.code,
                "body": raw.decode("utf-8", errors="replace")}


def scrub(value, key):
    if isinstance(value, str):
        return value.replace(key, "[SECRET_REMOVED]") if key else value
    if isinstance(value, list):
        return [scrub(v, key) for v in value]
    if isinstance(value, dict):
        return {scrub(k, key): scrub(v, key) for k, v in value.items()}
    return value


def validate_content(content):
    require(isinstance(content, str) and content.strip(), "E_MODEL_BLANK_CONTENT")
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        raise ValueError("E_MODEL_JSON") from None
    require(isinstance(value, dict) and set(value) == {"extractions"}
            and isinstance(value["extractions"], list), "E_MODEL_SCHEMA")
    fields = set(local.ATTRIBUTES["opinion"])
    for extraction in value["extractions"]:
        require(isinstance(extraction, dict) and set(extraction) == {"opinion", "opinion_attributes"}
                and isinstance(extraction["opinion"], str) and extraction["opinion"], "E_MODEL_SCHEMA")
        attrs = extraction["opinion_attributes"]
        require(isinstance(attrs, dict) and set(attrs) == fields, "E_MODEL_SCHEMA")
        for name, attr in attrs.items():
            require((isinstance(attr, list) and all(isinstance(x, str) for x in attr))
                    if name in local.LIST_ATTRIBUTES else isinstance(attr, str), "E_MODEL_SCHEMA")
            if name in local.ENUMS:
                require(attr in local.ENUMS[name], "E_MODEL_SCHEMA")
    return content


def mask_filter(candidates, section, redactions):
    accepted, errors = [], []
    for candidate in candidates:
        if any(e["start"] < span["end"] and span["start"] < e["end"]
               for e in candidate["evidence"] for span in redactions):
            errors.append("E_QUOTE_REDACTED")
        elif any(section["text"][e["start"]:e["end"]] != e["quote"] for e in candidate["evidence"]):
            errors.append("E_ORIGINAL_QUOTE_MISMATCH")
        else:
            candidate["review_flags"] = [f for f in candidate["review_flags"] if f != "local_model_candidate"]
            candidate["review_flags"].append("external_model_candidate")
            accepted.append(candidate)
    return accepted, errors


def instruction_text():
    return local.INSTRUCTION + '\nOutput json conforming to this JSON schema:\n' + json.dumps(local.schema(), ensure_ascii=False)


def request_body(prompt, plan):
    return json.dumps({'model': MODEL, 'temperature': 0, 'max_tokens': plan['max_output_tokens'],
        'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'},
        'messages': [{'role': 'system', 'content': instruction_text()}, {'role': 'user', 'content': prompt}]},
        ensure_ascii=False).encode('utf-8')


def preflight(plan_path, approval_path, alias, run_id, window_chars=600, *, workspace=None, section_id=None):
    """Render the actual v3 prompts and check budget before launcher decryption.

    The collector returns empty extractions locally; it has no transport or key
    getter. Concurrent consumers are checked again by Ledger.reserve at send.
    """
    checked = validate_plan(plan_path, approval_path, alias)
    plan, item, original, selected, fingerprint, cap, ledger_path, _ = checked
    require(re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id) is not None, 'E_RUN_ID')
    require(type(window_chars) is int and 300 <= window_chars <= 6000, 'E_WINDOW_SIZE')
    if workspace is not None:
        require(Path(workspace).resolve() == selected, 'E_PLAN_WORKSPACE_MISMATCH')
    if section_id is not None:
        require(section_id == item['section_id'], 'E_SECTION_SELECTION')
    from reviewproto.store import linklike
    folder = selected / 'model-artifacts' / run_id
    require(not any(linklike(p) for p in [folder, *folder.parents]), 'E_WORKSPACE_LINK')
    require(not folder.exists(), 'E_RUN_EXISTS')
    from reviewproto.batch import source_state
    require(not any(r['run_id'] == run_id for r in source_state(selected).get('extraction_runs', [])), 'E_RUN_EXISTS')
    import langextract as lx
    from langextract.core import base_model, tokenizer, types
    sizes = []
    class Collector(base_model.BaseLanguageModel):
        def infer(self, batch_prompts, **kwargs):
            for prompt in batch_prompts:
                sizes.append(len(request_body(prompt, plan)))
                yield [types.ScoredOutput(score=None, output='{"extractions": []}')]
    for _, window, kind in local.windows(dict(original, text=item['text']), window_chars):
        if window.strip() and kind != 'oversize_paragraph':
            lx.extract(text_or_documents=window, prompt_description=instruction_text(), examples=local.examples(lx),
                model=Collector(), tokenizer=tokenizer.UnicodeTokenizer(), fence_output=False,
                use_schema_constraints=False, show_progress=False, max_workers=1, batch_length=1,
                max_char_buffer=max(len(window) + 1, 10000), extraction_passes=1,
                resolver_params={'enable_fuzzy_alignment': False, 'accept_match_lesser': False, 'suppress_parse_errors': False})
    Ledger(ledger_path, fingerprint, cap, plan['max_calls']).check_available(sizes, plan['max_output_tokens'])
    return checked


def run(plan_path, approval_path, alias, run_id, window_chars=600, *, transport=None, key_getter=None):
    started_at = datetime.now(timezone.utc).isoformat()
    plan, item, original, workspace, fingerprint, cap, ledger_path, ledger_identity = validate_plan(plan_path, approval_path, alias)
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id) is not None, "E_RUN_ID")
    require(type(window_chars) is int and 300 <= window_chars <= 6000, "E_WINDOW_SIZE")
    adapter_hash = local.digest(Path(__file__).read_bytes())
    local_hash = local.digest(Path(local.__file__).read_bytes())
    import langextract as lx
    from langextract.core import base_model, tokenizer, types
    logging.getLogger("absl").setLevel(logging.ERROR)
    folder = workspace / "model-artifacts" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    ledger = Ledger(ledger_path, fingerprint, cap, plan["max_calls"])
    instruction = instruction_text()
    calls, candidates, errors, outcomes, grounding = [], [], [], [], []
    scope = {}
    stopped = False
    send = transport or official_post

    def save(name, value):
        (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    class DeepSeekModel(base_model.BaseLanguageModel):
        def infer(self, batch_prompts, **kwargs):
            nonlocal stopped
            for prompt in batch_prompts:
                # Do not rely on a stale approval/source after a long model call.
                current = validate_plan(plan_path, approval_path, alias)
                require(current[4] == fingerprint and current[5] == cap, "E_APPROVAL_PLAN_CHANGED")
                require(current[6] == ledger_path and current[7] == ledger_identity, "E_APPROVAL_LEDGER_CHANGED")
                require(not stopped, "E_USAGE_UNKNOWN_STOP")
                body = request_body(prompt, plan)
                call_id, reserved = ledger.reserve(alias, run_id, len(body), plan["max_output_tokens"])
                call = {"ledger_call_id": call_id, "scope": dict(scope), "prompt_sha256": local.digest(prompt),
                        "body_sha256": local.digest(body), "reserved_upper_bound_cny": reserved / NANO,
                        "status": "reserved", "request_attempted": False,
                        "started_at": None, "finished_at": None, "seconds": 0.0}
                calls.append(call)
                key, answer, usage = "", None, None
                try:
                    key = (key_getter or (lambda: os.environ.get("DEEPSEEK_API_KEY", "")))()
                    require(isinstance(key, str) and bool(key.strip()), "E_API_KEY_REQUIRED")
                    call["request_attempted"] = True
                    call["started_at"] = datetime.now(timezone.utc).isoformat()
                    request_started = time.monotonic()
                    try:
                        answer = send(body, key)
                    finally:
                        call["seconds"] = time.monotonic() - request_started
                        call["finished_at"] = datetime.now(timezone.utc).isoformat()
                    usage = scrub(answer.get("usage"), key) if isinstance(answer, dict) else None
                    call["answer"] = scrub(answer, key)
                    if isinstance(answer, dict) and answer.get("transport_error"):
                        raise ValueError(answer["transport_error"])
                    choice = answer["choices"][0]
                    call["finish_reason"] = choice.get("finish_reason")
                    require(choice.get("finish_reason") == "stop", "E_MODEL_FINISH")
                    content = scrub(validate_content(choice["message"].get("content")), key)
                    call["status"] = "responded"
                except Exception as error:
                    code = str(error) if isinstance(error, ValueError) and re.fullmatch(r"E_[A-Z_]+", str(error)) else "E_DEEPSEEK_REQUEST"
                    call.update(status="failed", error=code, error_type=type(error).__name__)
                    raise ValueError(code) from None
                finally:
                    status, cost = ledger.settle(call_id, usage)
                    stopped = status != "known"
                    call.update(usage=scrub(usage, key), usage_status=status,
                                estimated_peak_cost_cny=cost / NANO if cost is not None else None)
                    save(f"response-{len(calls):03}.json", scrub(call, key))
                yield [types.ScoredOutput(score=None, output=content)]

    outbound = dict(original, text=item["text"])
    for number, (offset, window, kind) in enumerate(local.windows(outbound, window_chars)):
        if not window.strip():
            continue
        scope = {"section_id": original["section_id"], "window_start": offset, "window_end": offset + len(window)}
        outcome = dict(scope, window_kind=kind)
        outcomes.append(outcome)
        if stopped:
            errors.append("E_USAGE_UNKNOWN_STOP")
            outcome.update(status="skipped", errors=["E_USAGE_UNKNOWN_STOP"])
            break
        if kind == "oversize_paragraph":
            errors.append("E_OVERSIZE_PARAGRAPH_REQUIRES_REVIEW")
            outcome.update(status="skipped", errors=["E_OVERSIZE_PARAGRAPH_REQUIRES_REVIEW"])
            continue
        try:
            document = lx.extract(text_or_documents=window, prompt_description=instruction, examples=local.examples(lx),
                                  model=DeepSeekModel(), tokenizer=tokenizer.UnicodeTokenizer(), fence_output=False,
                                  use_schema_constraints=False, show_progress=False, max_workers=1, batch_length=1,
                                  max_char_buffer=max(len(window) + 1, 10000), extraction_passes=1,
                                  resolver_params={"enable_fuzzy_alignment": False, "accept_match_lesser": False, "suppress_parse_errors": False})
            grounding.append({"scope": dict(scope), "extractions": [{"class": e.extraction_class,
                              "text": e.extraction_text, "attributes": e.attributes,
                              "interval": [e.char_interval.start_pos, e.char_interval.end_pos] if e.char_interval else None}
                             for e in document.extractions or []]})
            new, _, failures = local.convert(document, outbound, window, offset, f"{alias}-w{number}-")
            new, masked = mask_filter(new, original, item["redactions"])
            failures.extend(masked)
            candidates.extend(new)
            errors.extend(failures)
            outcome.update(status="converted", candidates=len(new), errors=failures)
        except Exception as error:
            code = str(error) if isinstance(error, ValueError) and re.fullmatch(r"E_[A-Z_]+", str(error)) else "E_DEEPSEEK_EXTRACTION"
            errors.append(code)
            outcome.update(status="failed", errors=[code], error_type=type(error).__name__)
    unique = {}
    for candidate in candidates:
        key = json.dumps({k: v for k, v in candidate.items() if k != "external_id"}, ensure_ascii=False, sort_keys=True)
        unique.setdefault(key, candidate)
    if stopped and "E_USAGE_UNKNOWN_STOP" not in errors:
        errors.append("E_USAGE_UNKNOWN_STOP")
    # The core importer accepts producer status complete/failed and derives
    # partial/zero_candidates itself after validating the supplied candidates.
    status = "complete" if unique or not errors else "failed"
    result = {"schema_version": 1, "source_id": item["source_id"], "run_id": run_id,
              "extractor": "langextract-" + version("langextract") + "-deepseek", "model": MODEL,
              "status": status, "errors": errors, "candidates": list(unique.values()),
              "sections": [{"section_id": original["section_id"], "text_sha256": item["source_text_sha256"]}],
              "config": {"plan_sha256": fingerprint, "alias": alias, "endpoint": ENDPOINT,
                         "ledger_identity": ledger_identity,
                         "prompt_version": local.PROMPT_VERSION, "prompt_sha256": local.digest(instruction),
                         "protocol": "v3",
                         "schema_sha256": local.digest(json.dumps(local.schema(), sort_keys=True)),
                         "adapter_sha256": adapter_hash, "local_adapter_sha256": local_hash,
                         "score_blind": True, "input_scope": "single_approved_section_window",
                         "temperature": 0, "thinking": "disabled", "window_chars": window_chars,
                         "max_output_tokens": plan["max_output_tokens"], "model_requests": sum(c["request_attempted"] for c in calls),
                         "external_model_requests": sum(c["request_attempted"] for c in calls), "pricing_source": PRICING_SOURCE,
                         "cost_basis": "published_peak_estimate_not_actual_charge",
                         "started_at": started_at,
                         "finished_at": datetime.now(timezone.utc).isoformat()}}
    save("candidates.json", result)
    save("grounding.json", grounding)
    save("windows.json", outcomes)
    return result


def summary_outcome(result):
    if result["status"] == "failed":
        return "failed"
    if result["errors"]:
        return "partial"
    return "complete" if result["candidates"] else "zero_candidates"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--item", required=True, help="Exactly one approved alias; no implicit all-items mode")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--window-chars", type=int, default=600)
    args = parser.parse_args()
    result = run(args.plan, args.approval, args.item, args.run_id or "deepseek-" + uuid.uuid4().hex, args.window_chars)
    print(json.dumps({"run_id": result["run_id"], "status": result["status"], "candidates": len(result["candidates"]),
                      "summary_outcome": summary_outcome(result), "errors": len(result["errors"]),
                      "model_requests": result["config"]["model_requests"]}))
    return 0 if summary_outcome(result) in {"complete", "zero_candidates"} else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        print(str(error) if isinstance(error, ValueError) and re.fullmatch(r"E_[A-Z_]+", str(error))
              else "E_DEEPSEEK_SETUP", file=sys.stderr)
        raise SystemExit(2)
