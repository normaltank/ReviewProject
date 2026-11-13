"""Small review domain: immutable suggestions, explicit decisions and registries.

The schema-1 envelope remains readable. New fields are additive; old candidate
IDs and decision histories are never rewritten during migration.
"""
import copy

from .core import EDIT_FIELDS, digest, require, validate_candidate


def current_views(state):
    latest = {d["candidate_id"]: d["value"] for d in state["decisions"]}
    return [latest.get(c["candidate_id"], c) for c in state["candidates"]]


def effective_views(state):
    return [c for c in current_views(state) if c["status"] == "confirmed"]


def candidate_value(state, section_id, cid, fields=None, origin="human_decision"):
    sections = {s["section_id"]: s for s in state["sections"]}
    require(section_id in sections, "E_EVIDENCE_SCOPE")
    value = {"candidate_id": cid, "section_id": section_id, "visibility": sections[section_id]["visibility"],
             "origin": origin, "status": "needs_review", "interpretation": "unknown", "evidence": [],
             "object": "unknown", "attributes": [], "direction": "unknown", "speech_function": "unknown",
             "requirement_strength": "unknown", "severity": "unknown", "action": "unknown", "conditions": [],
             "alternatives": [], "conditional_actions": [], "relations": [], "reasons": [], "concept_ids": [], "clause_links": [], "negation": "unknown",
             "paper_verification": "not_checked", "standard_alignment": "pending_comparison", "review_flags": []}
    fields = fields or {}
    require(isinstance(fields, dict) and set(fields) <= EDIT_FIELDS, "E_PATCH_FIELDS")
    value.update(copy.deepcopy(fields))
    return value


def validate_extensions(value, state, refs):
    actions = value.get('conditional_actions', [])
    require(isinstance(actions, list) and len(actions) <= 100, 'E_CONDITIONAL_ACTION')
    for action in actions:
        require(isinstance(action, dict) and set(action) == {'condition', 'action', 'meaning', 'provenance', 'evidence_indices'}, 'E_CONDITIONAL_ACTION')
        require(action['meaning'] in {'known', 'unknown'} and action['provenance'] in {'explicit', 'inferred', 'unknown'}, 'E_CONDITIONAL_ACTION')
        refs(action['evidence_indices'])
        quotes = [value['evidence'][i]['quote'] for i in action['evidence_indices']]
        for name in ('condition', 'action'):
            phrase = action[name]
            require(isinstance(phrase, str) and phrase.strip() and len(phrase) <= 20000, 'E_CONDITIONAL_ACTION')
            if phrase == 'unknown':
                require(action['meaning'] == action['provenance'] == 'unknown', 'E_CONDITIONAL_ACTION_QUOTE')
            else:
                require(any(phrase in quote for quote in quotes), 'E_CONDITIONAL_ACTION_QUOTE')
        if value.get('origin') == 'model_candidate' and value.get('status') == 'pending_review':
            require(action['meaning'] == 'unknown', 'E_MACHINE_CONDITIONAL_ACTION')
    require(isinstance(value.get("negation", "unknown"), str) and 0 < len(value.get("negation", "unknown")) <= 20000, "E_NEGATION")
    ids = value.get("concept_ids", [])
    concepts = {c["concept_id"] for c in state.get("concepts", [])}
    require(isinstance(ids, list) and all(isinstance(i, str) and i in concepts for i in ids) and len(set(ids)) == len(ids), "E_CONCEPT_ID")
    reasons = value.get("reasons", [])
    require(isinstance(reasons, list), "E_REASON")
    for reason in reasons:
        require(isinstance(reason, dict) and set(reason) == {"text", "provenance", "evidence_indices"}, "E_REASON")
        require(isinstance(reason["text"], str) and bool(reason["text"].strip()) and reason["provenance"] in {"explicit", "inferred", "unknown"}, "E_REASON")
        refs(reason["evidence_indices"])
    links = value.get("clause_links", [])
    clauses = {c["clause_id"] for c in state.get("clauses", [])}
    require(isinstance(links, list), "E_CLAUSE_LINK")
    for link in links:
        require(isinstance(link, dict) and set(link) == {"clause_id", "relation", "provenance", "evidence_indices"}, "E_CLAUSE_LINK")
        require(link["clause_id"] in clauses and link["relation"] in {"covered", "partial", "condition_difference", "potential_conflict", "pending_comparison"}, "E_CLAUSE_LINK")
        require(link["provenance"] in {"explicit", "inferred", "unknown"}, "E_CLAUSE_LINK")
        refs(link["evidence_indices"])


def registry_updates(state, entries, actor, reason, at):
    require(isinstance(entries, list), "E_CONCEPT")
    existing = {c["concept_id"]: c for c in state.get("concepts", [])}
    seen = set()
    for entry in entries:
        fields = {"concept_id", "name", "definition", "positive_examples", "negative_examples", "boundary", "status", "sources"}
        require(isinstance(entry, dict) and set(entry) == fields, "E_CONCEPT")
        cid = entry["concept_id"]
        require(isinstance(cid, str) and cid.strip() and len(cid) <= 200 and cid not in seen, "E_CONCEPT")
        seen.add(cid)
        require(all(isinstance(entry[k], str) and entry[k].strip() for k in ("name", "definition", "boundary")), "E_CONCEPT")
        require(not any(other_id != cid and other["name"].strip().casefold() == entry["name"].strip().casefold() for other_id, other in existing.items()), "E_CONCEPT_DUPLICATE_NAME")
        require(entry["status"] in {"pending_confirmation", "confirmed", "deprecated"}, "E_CONCEPT")
        for key in ("positive_examples", "negative_examples"):
            require(isinstance(entry[key], list) and all(isinstance(s, str) and s.strip() for s in entry[key]), "E_CONCEPT")
        require(isinstance(entry["sources"], list) and bool(entry["sources"]), "E_CONCEPT_SOURCE")
        # Sources are local evidence descriptors, not claims of external authority.
        for source in entry["sources"]:
            require(isinstance(source, dict) and source.get("source_id") == state["source"]["source_id"], "E_CONCEPT_SOURCE")
            require(set(source) <= {"source_id", "candidate_id", "note"}, "E_CONCEPT_SOURCE")
            if "candidate_id" in source:
                require(source["candidate_id"] in {c["candidate_id"] for c in state["candidates"]}, "E_CONCEPT_SOURCE")
        state.setdefault("concept_history", []).append({"previous": copy.deepcopy(existing.get(cid)), "value": copy.deepcopy(entry),
                                                       "actor": actor, "reason": reason, "at": at, "revision": state["revision"] + 1})
        existing[cid] = copy.deepcopy(entry)
    state["concepts"] = list(existing.values())


def extraction_import(state, payload, at):
    required = {"schema_version", "source_id", "run_id", "extractor", "model", "config", "sections", "candidates"}
    require(isinstance(payload, dict) and required <= set(payload) and set(payload) <= required | {"status", "errors"}, "E_EXTRACTION_SHAPE")
    require(payload["schema_version"] == 1 and payload["source_id"] == state["source"]["source_id"], "E_EXTRACTION_SOURCE")
    require(all(isinstance(payload[k], str) and payload[k].strip() and len(payload[k]) <= 500 for k in ("run_id", "extractor", "model")), "E_EXTRACTION_RUN")
    require(isinstance(payload["config"], dict) and isinstance(payload["candidates"], list), "E_EXTRACTION_SHAPE")
    require(payload.get("status", "complete") in {"complete", "failed"}, "E_EXTRACTION_STATUS")
    require(isinstance(payload.get("errors", []), list) and all(isinstance(e, str) for e in payload.get("errors", [])), "E_EXTRACTION_STATUS")
    from .store import encoded
    fingerprint = digest(encoded(payload))
    previous = next((r for r in state.get("extraction_runs", []) if r["run_id"] == payload["run_id"]), None)
    if previous:
        require(previous["payload_sha256"] == fingerprint, "E_EXTRACTION_RUN_CONFLICT")
        return state
    sections = {s["section_id"]: s for s in state["sections"]}
    require(isinstance(payload["sections"], list) and bool(payload["sections"]), "E_EXTRACTION_SECTIONS")
    scope = set()
    for section in payload["sections"]:
        require(isinstance(section, dict) and set(section) == {"section_id", "text_sha256"}, "E_EXTRACTION_SECTIONS")
        sid = section["section_id"]
        require(sid in sections and sid not in scope and section["text_sha256"] == digest(sections[sid]["text"].encode()), "E_EXTRACTION_SECTIONS")
        scope.add(sid)
    record = {k: copy.deepcopy(payload[k]) for k in ("run_id", "extractor", "model", "config", "sections")}
    record.update(at=at, payload_sha256=fingerprint, accepted_ids=[], rejected=[], errors=copy.deepcopy(payload.get("errors", [])))
    # Persist the complete local input for replay, including failed/unknown rows.
    record["payload"] = copy.deepcopy(payload)
    for index, raw in enumerate(payload["candidates"]):
        try:
            require(payload.get("status", "complete") == "complete", "E_EXTRACTION_FAILED")
            require(isinstance(raw, dict) and {"section_id", "evidence"} <= set(raw) and set(raw) <= EDIT_FIELDS | {"section_id", "external_id", "review_flags"}, "E_EXTRACTION_CANDIDATE")
            require(raw["section_id"] in scope, "E_EVIDENCE_SCOPE")
            flags = raw.get("review_flags", [])
            require(isinstance(flags, list) and len(flags) <= 100 and all(isinstance(flag, str) and 0 < len(flag) <= 200 for flag in flags), "E_EXTRACTION_FLAGS")
            require(raw.get("external_id") is None or isinstance(raw["external_id"], str) and 0 < len(raw["external_id"]) <= 500, "E_EXTRACTION_ID")
            cid = digest((state["source"]["source_id"] + ":model:" + payload["run_id"] + ":" + str(index)).encode())[:24]
            require(cid not in {c["candidate_id"] for c in state["candidates"]}, "E_EXTRACTION_ID")
            value = candidate_value(state, raw["section_id"], cid, {k: v for k, v in raw.items() if k in EDIT_FIELDS}, "model_candidate")
            # The producer never gets to assert human confirmation.
            require(raw.get("status", "pending_review") == "pending_review", "E_MACHINE_STATUS")
            value.update(status="pending_review", run_id=payload["run_id"], external_id=raw.get("external_id"),
                         review_flags=list(dict.fromkeys(["model_semantics_unverified", "section_context_required"] + flags)))
            validate_candidate(value, state, allow_pending=True)
            state["candidates"].append(value)
            record["accepted_ids"].append(cid)
        except Exception as error:
            from .core import ReviewError
            record["rejected"].append({"index": index, "raw": copy.deepcopy(raw), "error_code": str(error) if isinstance(error, ReviewError) else "E_EXTRACTION_CANDIDATE"})
    record["status"] = ("failed" if payload.get("status") == "failed" else "partial" if record["rejected"] or record["errors"] else
                        "zero_candidates" if not record["accepted_ids"] else "complete")
    state.setdefault("extraction_runs", []).append(record)
    state["revision"] += 1
    return state


def clause_import(state, payload, at):
    """Accept local A evidence drafts; no transition to an effective standard."""
    import re
    from .store import encoded
    require(isinstance(payload, dict) and set(payload) == {"schema_version", "clauses"} and payload["schema_version"] == 1, "E_CLAUSE_SHAPE")
    require(isinstance(payload["clauses"], list) and bool(payload["clauses"]), "E_CLAUSE_SHAPE")
    fingerprint = digest(encoded(payload))
    if fingerprint in state.get("clause_imports", []):
        return state
    existing = {c["clause_id"]: c for c in state.get("clauses", [])}
    seen, additions = set(), []
    for clause in payload["clauses"]:
        fields = {"clause_id", "text", "source_kind", "sources"}
        require(isinstance(clause, dict) and set(clause) == fields, "E_CLAUSE_SHAPE")
        cid = clause["clause_id"]
        require(isinstance(cid, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", cid) and cid not in seen, "E_CLAUSE_ID")
        seen.add(cid)
        require(isinstance(clause["text"], str) and clause["text"].strip(), "E_CLAUSE_TEXT")
        require(clause["source_kind"] in {"direct_source_quote", "machine_synthesis", "machine_transcript"}, "E_CLAUSE_PROVENANCE")
        require(isinstance(clause["sources"], list) and bool(clause["sources"]), "E_CLAUSE_SOURCE")
        for source in clause["sources"]:
            require(isinstance(source, dict) and {"source_id", "sha256"} <= set(source) and set(source) <= {"source_id", "sha256", "page", "timestamp", "locator", "quote"}, "E_CLAUSE_SOURCE")
            require(isinstance(source["source_id"], str) and source["source_id"].strip() and isinstance(source["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]), "E_CLAUSE_SOURCE")
            require(bool({"page", "timestamp", "locator"} & set(source)), "E_CLAUSE_SOURCE")
            if "page" in source:
                require(type(source["page"]) is int and source["page"] >= 1, "E_CLAUSE_SOURCE")
            if "timestamp" in source:
                interval = source["timestamp"]
                require(isinstance(interval, list) and len(interval) == 2 and all(type(t) in {int, float} for t in interval) and 0 <= interval[0] < interval[1] < 1e9, "E_CLAUSE_SOURCE")
            if "locator" in source:
                require(isinstance(source["locator"], (str, dict)) and bool(source["locator"]), "E_CLAUSE_SOURCE")
            if "quote" in source:
                require(isinstance(source["quote"], str) and source["quote"].strip(), "E_CLAUSE_SOURCE")
        if clause["source_kind"] == "direct_source_quote":
            require(any(source.get("quote") == clause["text"] for source in clause["sources"]), "E_CLAUSE_QUOTE")
        if cid in existing:
            require(all(existing[cid][k] == clause[k] for k in fields), "E_CLAUSE_ID_CONFLICT")
            continue
        additions.append(dict(copy.deepcopy(clause), status="candidate", review_status="pending_source_review", authority="unconfirmed",
                              framework_version="unknown", imported_at=at, import_sha256=fingerprint))
    state.setdefault("clauses", []).extend(additions)
    state.setdefault("clause_imports", []).append(fingerprint)
    state["revision"] += 1
    return state
