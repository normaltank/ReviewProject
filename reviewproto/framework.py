"""Local evidence-backed candidate frameworks and review drafts; no publication."""
from __future__ import annotations

import copy
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import zipfile

from .core import ReviewError, digest, require
from .understanding import current_views

SOURCE_LIMIT = 40_000_000
PACKAGE_LIMIT = 240_000_000
BOOK_LIMIT = 10_000_000
REVIEW_PAYLOAD_LIMIT = 10_000_000
MUTABLE_RULE = {"requirement", "applicable_when", "exceptions", "strength", "strength_provenance", "checks"}
RELATIONS = {"covered", "partial", "condition_difference", "potential_conflict", "uncovered", "pending_comparison"}


def framework_digest(book):
    """Canonical schema-1 book hash, identical to persisted imports encoding."""
    from .store import encoded
    return digest(encoded(book))


def text(value, code="E_FRAMEWORK_SHAPE"):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 100_000, code)


def texts(value):
    require(isinstance(value, list) and len(value) <= 1000, "E_FRAMEWORK_SHAPE")
    for item in value:
        text(item)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value), "E_FRAMEWORK_ID")


def checked_path(root, relative):
    from .store import linklike
    require(isinstance(relative, str) and "\\" not in relative and ":" not in relative, "E_FRAMEWORK_PATH")
    rel = PurePosixPath(relative)
    require(not rel.is_absolute() and len(rel.parts) == 2 and rel.parts[0] == "sources" and
            all(p not in {".", ".."} for p in rel.parts) and str(rel) == relative, "E_FRAMEWORK_PATH")
    root = Path(root).absolute()
    target = root.joinpath(*rel.parts)
    require(all(not linklike(p) for p in [root, *root.parents, target.parent, target]), "E_FRAMEWORK_LINK")
    require(target.resolve().is_relative_to(root.resolve()), "E_FRAMEWORK_PATH")
    return target


def load_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "E_FRAMEWORK_JSON")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ReviewError("E_FRAMEWORK_JSON")))
    except ReviewError:
        raise
    except Exception:
        raise ReviewError("E_FRAMEWORK_JSON") from None


def native_ppt(data):
    from lxml import etree
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            require(len(entries) <= 10000 and len({e.filename for e in entries}) == len(entries), "E_FRAMEWORK_ZIP_LIMIT")
            require(sum(e.file_size for e in entries) <= 200_000_000 and
                    all(e.file_size <= 40_000_000 and e.file_size <= max(1, e.compress_size) * 1000 and not e.flag_bits & 1 for e in entries), "E_FRAMEWORK_ZIP_LIMIT")
            slides = {}
            ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
            for entry in entries:
                match = re.fullmatch(r"ppt/slides/slide([1-9][0-9]*)\.xml", entry.filename)
                if not match:
                    continue
                raw = archive.read(entry)
                require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "E_FRAMEWORK_XML")
                tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
                slides[int(match[1])] = ["".join((n.text or "") if n.tag == ns + "t" else "\n"
                                                   for n in p.iter() if n.tag in {ns + "t", ns + "br"})
                                             for p in tree.iter(ns + "p")]
            require(bool(slides), "E_FRAMEWORK_PPT")
            return slides
    except ReviewError:
        raise
    except Exception:
        raise ReviewError("E_FRAMEWORK_PPT") from None


def pointer_value(document, pointer):
    require(isinstance(pointer, str) and pointer.startswith("/") and len(pointer) < 2000, "E_FRAMEWORK_POINTER")
    value, parent = document, None
    try:
        for raw in pointer[1:].split("/"):
            require(re.search(r"~(?![01])", raw) is None, "E_FRAMEWORK_POINTER")
            key = raw.replace("~1", "/").replace("~0", "~")
            parent = value
            if isinstance(value, list):
                require(re.fullmatch(r"0|[1-9][0-9]*", key) is not None, "E_FRAMEWORK_POINTER")
                value = value[int(key)]
            else:
                require(isinstance(value, dict), "E_FRAMEWORK_POINTER")
                value = value[key]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ReviewError("E_FRAMEWORK_POINTER") from None
    require(isinstance(value, str), "E_FRAMEWORK_POINTER")
    return value, parent


def source_text(kind, data, locator):
    """Return exact native text for content preparation; full import also checks metadata."""
    if kind == "pptx_native":
        pages = native_ppt(data)
        require(isinstance(locator, dict) and set(locator) == {"page", "paragraph"} and
                type(locator["page"]) is int and type(locator["paragraph"]) is int and
                locator["page"] in pages and 0 <= locator["paragraph"] < len(pages[locator["page"]]), "E_FRAMEWORK_LOCATOR")
        return pages[locator["page"]][locator["paragraph"]]
    require(kind == "transcript_json" and isinstance(locator, dict) and "pointer" in locator, "E_FRAMEWORK_LOCATOR")
    return pointer_value(load_json(data), locator["pointer"])[0]


def validate_book(book, source_bytes):
    fields = {"schema_version", "framework_id", "version", "title", "coverage_notes", "sources", "rules"}
    require(isinstance(book, dict) and set(book) == fields and type(book["schema_version"]) is int and book["schema_version"] == 1, "E_FRAMEWORK_SHAPE")
    for key in ("framework_id", "version"):
        identifier(book[key])
    text(book["title"])
    texts(book["coverage_notes"])
    require(isinstance(book["sources"], list) and 0 < len(book["sources"]) <= 100 and
            isinstance(book["rules"], list) and 0 < len(book["rules"]) <= 1000, "E_FRAMEWORK_SHAPE")
    sources, parsed = {}, {}
    for source in book["sources"]:
        require(isinstance(source, dict) and set(source) == {"source_id", "kind", "file", "sha256", "verification"}, "E_FRAMEWORK_SOURCE")
        sid = source["source_id"]
        identifier(sid)
        require(sid not in sources and source["kind"] in {"pptx_native", "transcript_json"}, "E_FRAMEWORK_SOURCE")
        require(source["verification"] == {"pptx_native": "native_text", "transcript_json": "machine_unchecked"}[source["kind"]], "E_FRAMEWORK_VERIFICATION")
        require(isinstance(source["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]), "E_FRAMEWORK_SOURCE_HASH")
        require(isinstance(source["file"], str) and source["file"].endswith(".pptx" if source["kind"] == "pptx_native" else ".json"), "E_FRAMEWORK_PATH")
        require(sid in source_bytes and digest(source_bytes[sid]) == source["sha256"], "E_FRAMEWORK_SOURCE_HASH")
        sources[sid] = source
        parsed[sid] = native_ppt(source_bytes[sid]) if source["kind"] == "pptx_native" else load_json(source_bytes[sid])
    ids = set()
    for rule in book["rules"]:
        required = {"rule_id", "dimension_id", "title", "requirement", "rule_type", "strength", "strength_provenance", "applicable_when", "exceptions", "unknowns", "checks", "derivation", "evidence"}
        require(isinstance(rule, dict) and set(rule) == required, "E_FRAMEWORK_RULE")
        identifier(rule["rule_id"])
        identifier(rule["dimension_id"])
        require(rule["rule_id"] not in ids, "E_FRAMEWORK_RULE")
        ids.add(rule["rule_id"])
        for key in ("title", "requirement"):
            text(rule[key])
        for key in ("applicable_when", "exceptions", "unknowns", "checks"):
            texts(rule[key])
        require(rule["rule_type"] in {"evaluation_question", "recommendation", "requirement_candidate"} and
                rule["strength"] in {"unknown", "recommended", "mandatory", "optional"} and
                rule["strength_provenance"] in {"explicit", "inferred", "unknown"} and
                rule["derivation"] in {"source_paraphrase", "editorial_operationalization"}, "E_FRAMEWORK_RULE")
        require(isinstance(rule["evidence"], list) and 0 < len(rule["evidence"]) <= 1000, "E_FRAMEWORK_EVIDENCE")
        for evidence in rule["evidence"]:
            require(isinstance(evidence, dict) and set(evidence) == {"source_id", "locator", "start", "end", "quote"}, "E_FRAMEWORK_EVIDENCE")
            sid, loc = evidence["source_id"], evidence["locator"]
            require(isinstance(sid, str) and sid in sources and isinstance(loc, dict), "E_FRAMEWORK_EVIDENCE")
            if sources[sid]["kind"] == "pptx_native":
                require(set(loc) == {"page", "paragraph"} and type(loc["page"]) is int and type(loc["paragraph"]) is int and
                        loc["page"] in parsed[sid] and 0 <= loc["paragraph"] < len(parsed[sid][loc["page"]]), "E_FRAMEWORK_LOCATOR")
                original = parsed[sid][loc["page"]][loc["paragraph"]]
            else:
                require({"pointer"} <= set(loc) <= {"pointer", "segment_id", "time_range", "ppt_page"}, "E_FRAMEWORK_LOCATOR")
                original, record = pointer_value(parsed[sid], loc["pointer"])
                if set(loc) - {"pointer"}:
                    require(isinstance(record, dict), "E_FRAMEWORK_LOCATOR")
                if "segment_id" in loc:
                    require(loc["segment_id"] == record.get("id") and isinstance(loc["segment_id"], str), "E_FRAMEWORK_SEGMENT")
                if "time_range" in loc:
                    times = loc["time_range"]
                    require(isinstance(times, list) and len(times) == 2 and all(type(t) in {int, float} and math.isfinite(t) for t in times) and
                            0 <= times[0] < times[1] and times == [record.get("start"), record.get("end")], "E_FRAMEWORK_TIMESTAMP")
                if "ppt_page" in loc:
                    require(type(loc["ppt_page"]) is int and loc["ppt_page"] >= 1 and loc["ppt_page"] == record.get("ppt_page"), "E_FRAMEWORK_LOCATOR")
            start, end = evidence["start"], evidence["end"]
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(original) and
                    original[start:end] == evidence["quote"], "E_FRAMEWORK_QUOTE")
    return book


def active_candidates(state):
    return {c["candidate_id"]: c for c in current_views(state) if c["status"] not in {"rejected", "withdrawn", "superseded"}}


def view_fingerprint(state):
    latest = {d["candidate_id"]: d["decision_id"] for d in state["decisions"]}
    return framework_digest(dict(candidates=sorted(active_candidates(state).values(), key=lambda c: c["candidate_id"]),
                                 latest_decision_ids=latest))


def refresh_reviews(state):
    fingerprint = view_fingerprint(state)
    for review in state.get("framework_reviews", []):
        for entry in review["alignments"] + review["proposals"]:
            entry["validity"] = "current" if entry["candidate_view_sha256"] == fingerprint else "needs_revalidation"
    return state


def apply_review(state, payload, at):
    required = {"schema_version", "source_id", "base_revision", "actor", "reason", "framework_sha256", "alignments", "proposals"}
    require(isinstance(payload, dict) and set(payload) == required and type(payload["schema_version"]) is int and payload["schema_version"] == 1, "E_FRAMEWORK_REVIEW")
    require(payload["source_id"] == state["source"]["source_id"], "E_FRAMEWORK_REVIEW_SOURCE")
    phash = framework_digest(payload)
    if any(r["payload_sha256"] == phash for r in state.get("framework_reviews", [])):
        return state
    require(type(payload["base_revision"]) is int and payload["base_revision"] == state["revision"], "E_REVISION_CONFLICT")
    for key in ("actor", "reason"):
        text(payload[key], "E_AUDIT_REQUIRED")
    book = next((b["book"] for b in state.get("frameworks", []) if b["sha256"] == payload["framework_sha256"]), None)
    require(book is not None, "E_FRAMEWORK_NOT_FOUND")
    rules = {r["rule_id"]: r for r in book["rules"]}
    candidates = active_candidates(state)
    require(isinstance(payload["alignments"], list) and isinstance(payload["proposals"], list) and
            bool(payload["alignments"] or payload["proposals"]), "E_FRAMEWORK_REVIEW")
    record = copy.deepcopy(payload)
    fingerprint = view_fingerprint(state)
    seen = set()
    for row in record["alignments"]:
        require(isinstance(row, dict) and set(row) == {"candidate_id", "rule_id", "relation", "provenance", "evidence_indices", "rationale"}, "E_FRAMEWORK_ALIGNMENT")
        require(row["candidate_id"] in candidates and row["rule_id"] in rules and row["relation"] in RELATIONS and row["provenance"] in {"explicit", "inferred", "unknown"}, "E_FRAMEWORK_ALIGNMENT")
        pair = (row["candidate_id"], row["rule_id"])
        require(pair not in seen, "E_FRAMEWORK_ALIGNMENT")
        seen.add(pair)
        text(row["rationale"])
        refs = row["evidence_indices"]
        require(isinstance(refs, list) and bool(refs) and all(type(i) is int and 0 <= i < len(candidates[row["candidate_id"]]["evidence"]) for i in refs) and len(set(refs)) == len(refs), "E_FRAMEWORK_ALIGNMENT_EVIDENCE")
        row.update(candidate_view_sha256=fingerprint, candidate_snapshot=copy.deepcopy(candidates[row["candidate_id"]]), validity="current")
    seen = {p["proposal_id"] for review in state.get("framework_reviews", []) for p in review["proposals"]}
    for proposal in record["proposals"]:
        required_p = {"proposal_id", "rule_id", "kind", "after", "rationale", "support_candidate_ids", "counter_candidate_ids", "validation_plan", "rollback_condition", "unknowns"}
        require(isinstance(proposal, dict) and set(proposal) == required_p, "E_FRAMEWORK_PROPOSAL")
        identifier(proposal["proposal_id"])
        require(proposal["proposal_id"] not in seen and proposal["rule_id"] in rules and proposal["kind"] in {"source_interpretation", "publisher_requirement_change"}, "E_FRAMEWORK_PROPOSAL")
        seen.add(proposal["proposal_id"])
        for key in ("rationale", "validation_plan", "rollback_condition"):
            text(proposal[key])
        texts(proposal["unknowns"])
        after = proposal["after"]
        require(isinstance(after, dict) and bool(after) and set(after) <= MUTABLE_RULE, "E_FRAMEWORK_PROPOSAL_AFTER")
        before = copy.deepcopy(rules[proposal["rule_id"]])
        for key, value in after.items():
            if key in {"applicable_when", "exceptions", "checks"}:
                texts(value)
            elif key == "strength":
                require(value in {"unknown", "recommended", "mandatory", "optional"}, "E_FRAMEWORK_PROPOSAL_AFTER")
            elif key == "strength_provenance":
                require(value in {"explicit", "inferred", "unknown"}, "E_FRAMEWORK_PROPOSAL_AFTER")
            else:
                text(value)
        require(any(value != before[key] for key, value in after.items()), "E_FRAMEWORK_PROPOSAL_NOOP")
        refs = []
        for key in ("support_candidate_ids", "counter_candidate_ids"):
            ids = proposal[key]
            require(isinstance(ids, list) and all(isinstance(cid, str) and cid in candidates for cid in ids) and len(set(ids)) == len(ids), "E_FRAMEWORK_PROPOSAL_SCOPE")
            refs.extend(ids)
        require(bool(refs) and not set(proposal["support_candidate_ids"]) & set(proposal["counter_candidate_ids"]), "E_FRAMEWORK_PROPOSAL_SCOPE")
        # Local access is inherited; a proposal may not bridge permission zones.
        require(len({(candidates[cid]["section_id"], candidates[cid]["visibility"]) for cid in refs}) == 1, "E_FRAMEWORK_PROPOSAL_SCOPE")
        merged = copy.deepcopy(before)
        merged.update(after)
        # Baseline evidence does not establish the wording introduced by either
        # kind of editorial draft, even when the baseline paraphrases a source.
        merged["derivation"] = "editorial_operationalization"
        proposal.update(before=before, after=merged, status="draft", review_status="needs_professional_review",
                        baseline_status="baseline_confirmation_required", authority="unconfirmed", candidate_view_sha256=fingerprint,
                        candidate_snapshots={cid: copy.deepcopy(candidates[cid]) for cid in refs}, validity="current",
                        after_provenance="editorial_proposal", evidence_scope="baseline_only")
    record.update(payload_sha256=phash, at=at, revision=state["revision"] + 1)
    state.setdefault("framework_reviews", []).append(record)
    state["revision"] += 1
    return state


def review_template(state, framework_sha256=None, candidate_id=None, rule_id=None):
    books = state.get("frameworks", [])
    book = next((b for b in books if b["sha256"] == framework_sha256), None) if framework_sha256 else (books[-1] if books else None)
    require(book is not None, "E_FRAMEWORK_NOT_FOUND")
    candidates = active_candidates(state)
    require(candidate_id is None or candidate_id in candidates, "E_FRAMEWORK_ALIGNMENT")
    rules = [r for r in book["book"]["rules"] if rule_id is None or r["rule_id"] == rule_id]
    require(bool(rules), "E_FRAMEWORK_RULE")
    # A targeted template avoids generating a misleading automatic cross product.
    alignments = []
    if candidate_id is not None and rule_id is not None:
        alignments.append(dict(candidate_id=candidate_id, rule_id=rule_id, relation="pending_comparison", provenance="unknown",
                               evidence_indices=list(range(len(candidates[candidate_id]["evidence"]))), rationale=""))
    return dict(schema_version=1, source_id=state["source"]["source_id"], base_revision=state["revision"], actor="", reason="",
                framework_sha256=book["sha256"], alignments=alignments, proposals=[])
