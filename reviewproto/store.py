"""SQLite is authoritative; JSON and HTML projections are recoverable artifacts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from docx import __version__ as docx_version

from . import __version__
from .core import SCHEMA, PARSER, EXTRACTOR, ReviewError, digest, extract, parse_docx, require, validate_candidate, EDIT_FIELDS
from .intake import parse_structured
from .understanding import candidate_value, extraction_import, registry_updates

PRIVATE_IGNORE = b"*\n# Managed private reviewproto workspace; never commit local data.\n"


def linklike(path):
    """Windows directory junctions are not necessarily reported as symlinks."""
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_input(path, limit, limit_code="E_INPUT_LIMIT", context=None):
    """Hash the actual byte stream with bounded reads, retaining at most limit.

    Oversize inputs are hashed in chunks but never accumulated. If reading fails,
    the full fingerprint is unavailable and no partial digest is called an ID.
    """
    context = context if context is not None else {}
    hasher, chunks, total = hashlib.sha256(), [], 0
    try:
        with Path(path).open("rb") as stream:
            retain = os.fstat(stream.fileno()).st_size <= limit
            while True:
                chunk = stream.read(65_536)
                if not chunk:
                    break
                hasher.update(chunk)
                total += len(chunk)
                if retain and total <= limit:
                    chunks.append(chunk)
                else:
                    retain = False
                    chunks.clear()
    except OSError:
        context.update(input_fingerprint=None, fingerprint_state="unavailable_read_error")
        raise ReviewError("E_INPUT_READ") from None
    context.update(input_fingerprint=hasher.hexdigest(), fingerprint_state="complete", input_bytes=total)
    require(retain and total <= limit, limit_code)
    return b"".join(chunks)


def atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Workspace:
    APPLICATION_ID = 0x52565031

    def __init__(self, path):
        require(not linklike(Path(path).absolute()), "E_WORKSPACE_LINK")
        self.path = Path(path).resolve()
        require(self.path.parent != self.path and not (self.path / ".git").exists(), "E_WORKSPACE_NOT_DEDICATED")
        self.path.mkdir(parents=True, exist_ok=True)
        # Reject managed symlinks, including projections, so trusted local output
        # cannot silently write through a link to another location.
        reserved = {"review.sqlite3", "source.docx", "source.json", "source.csv", "state.json", "report.html", "runs", "patches", "imports"}
        for entry in self.path.iterdir():
            if entry.name.casefold() in reserved | {".gitignore"} or entry.name.casefold().startswith("review.sqlite3"):
                require(not linklike(entry) and entry.resolve().parent == self.path, "E_WORKSPACE_LINK")
        ignore = self.path / ".gitignore"
        if ignore.exists():
            require(ignore.is_file() and read_input(ignore, 4096) == PRIVATE_IGNORE, "E_WORKSPACE_IGNORE_EXISTS")
        db_path = self.path / "review.sqlite3"
        managed_source = None
        if not db_path.exists():
            require(not any(e.name.casefold() in reserved or e.name.casefold().startswith("review.sqlite3")
                            for e in self.path.iterdir()), "E_WORKSPACE_UNMANAGED")
            require(not any(e.name != ".gitignore" for e in self.path.iterdir()), "E_WORKSPACE_NOT_DEDICATED")
        else:
            # Inspect read-only before any DDL can mutate an unrelated database.
            check = None
            try:
                check = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
                application_id = check.execute("PRAGMA application_id").fetchone()[0]
                names = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                require({"state", "runs", "patches"} <= names, "E_WORKSPACE_UNMANAGED")
                row = check.execute("SELECT payload FROM state WHERE id=1").fetchone()
                if row:
                    managed_source = json.loads(row[0])["source"]["source_id"]
                if application_id != self.APPLICATION_ID:
                    # Migration for this prototype's earlier local workspaces.
                    require(application_id == 0, "E_WORKSPACE_UNMANAGED")
                    require(row is not None, "E_WORKSPACE_UNMANAGED")
                    old = json.loads(row[0])
                    require(old.get("schema_version") == SCHEMA and digest(read_input(self.path / "source.docx", 40_000_000)) == old["source"]["sha256"], "E_WORKSPACE_UNMANAGED")
            except ReviewError:
                raise
            except Exception:
                raise ReviewError("E_WORKSPACE_UNMANAGED") from None
            finally:
                if check is not None:
                    check.close()
        if not ignore.exists():
            # Legacy migrations may hide only recognised tool artifacts, not
            # unrelated source code or an existing user's directory contents.
            for entry in self.path.iterdir():
                name = entry.name.casefold()
                if name in {"runs", "patches", "imports"}:
                    require(entry.is_dir(), "E_WORKSPACE_NOT_DEDICATED")
                    for child in entry.iterdir():
                        require(child.is_file() and not linklike(child) and child.resolve().parent == entry.resolve(), "E_WORKSPACE_NOT_DEDICATED")
                        pattern = r"[0-9a-f]{32}\.json" if name == "runs" else r"[0-9a-f]{64}\.json"
                        require(re.fullmatch(pattern, child.name) is not None, "E_WORKSPACE_NOT_DEDICATED")
                        try:
                            value = json.loads(read_input(child, 10_000_000))
                            if name == "runs":
                                recognised = isinstance(value, dict) and value.get("run_id") == child.stem and "status" in value
                            elif name == "patches":
                                recognised = isinstance(value, dict) and value.get("source_id") == managed_source and "edits" in value
                            else:
                                recognised = isinstance(value, dict) and value.get("schema_version") == SCHEMA and ("candidates" in value or "clauses" in value) and digest(encoded(value)) == child.stem
                            require(recognised, "E_WORKSPACE_NOT_DEDICATED")
                        except Exception:
                            raise ReviewError("E_WORKSPACE_NOT_DEDICATED") from None
                    continue
                if name in (reserved - {"runs", "patches", "imports"}) | {"review.sqlite3-journal", "review.sqlite3-wal", "review.sqlite3-shm"}:
                    require(entry.is_file(), "E_WORKSPACE_NOT_DEDICATED")
                    continue
                require(entry.is_file() and not linklike(entry), "E_WORKSPACE_NOT_DEDICATED")
                try:
                    value = json.loads(read_input(entry, 10_000_000))
                    require(isinstance(value, dict) and value.get("schema_version") == SCHEMA and
                            value.get("source_id") == managed_source and "edits" in value, "E_WORKSPACE_NOT_DEDICATED")
                except Exception:
                    raise ReviewError("E_WORKSPACE_NOT_DEDICATED") from None
            # An ignore file cannot protect artifacts already in a Git index.
            # Git is optional outside repositories; never untrack user files.
            if any((directory / ".git").exists() for directory in self.path.parents):
                require(shutil.which("git") is not None, "E_WORKSPACE_GIT_CHECK")
                tracked = subprocess.run(["git", "-C", str(self.path), "ls-files", "-z", "--", "."],
                                         capture_output=True, timeout=10, check=False)
                require(tracked.returncode == 0, "E_WORKSPACE_GIT_CHECK")
                require(not tracked.stdout, "E_WORKSPACE_TRACKED")
            with ignore.open("xb") as stream:
                stream.write(PRIVATE_IGNORE)
                stream.flush()
                os.fsync(stream.fileno())
        self.db = sqlite3.connect(self.path / "review.sqlite3", timeout=10, isolation_level=None)
        self.db.execute(f"PRAGMA application_id={self.APPLICATION_ID}")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS patches (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def close(self):
        self.db.close()

    def state(self):
        row = self.db.execute("SELECT payload FROM state WHERE id=1").fetchone()
        require(row is not None, "E_WORKSPACE_EMPTY")
        state = json.loads(row[0])
        require(state.get("schema_version") == SCHEMA, "E_SCHEMA_VERSION")
        filename = source_filename(state)
        data = read_input(self.path / filename, 40_000_000)
        fingerprint = digest(data)
        try:
            require(fingerprint == state["source"]["sha256"], "E_SOURCE_CHANGED")
            # Recheck current support rules on every use, including old caches.
            # Never regenerate candidates or overwrite human decisions here.
            verified = parse_docx(data) if state["source"]["kind"] == "native_docx" else parse_structured(data, state["source"]["kind"])
            require(verified["scores"] == state["scores"] and verified["sections"] == state["sections"], "E_REIMPORT_REQUIRED")
        except ReviewError as error:
            error.source_fingerprint = fingerprint
            raise
        return state

    def save(self, state):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (encoded(state).decode(),))

    def _record(self, record):
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (record["run_id"], encoded(record).decode()))

    def operation(self, command, callback, input_fingerprint=None, input_context=None):
        context = input_context if input_context is not None else {}
        record = {"run_id": uuid.uuid4().hex, "command": command, "started_at": now(), "status": "running",
                  "software": __version__, "python": sys.version.split()[0], "dependencies": {"python-docx": docx_version},
                  "config": {"offline": True, "audience": "trusted_editors", "extractor": EXTRACTOR, "support_policy": PARSER},
                  "cost": {"network_calls": 0, "model_calls": 0}, "input_id": None, "input_fingerprint": input_fingerprint, "outputs": {}}
        self._record(record)
        committed = False
        try:
            self.db.execute("BEGIN IMMEDIATE")
            state = callback()
            record.update(context)
            self.save(state)
            record.update({"status": "committed", "input_id": state["source"]["source_id"], "origin": state["source"]["origin"], "revision": state["revision"],
                           "versions": state["versions"], "config_sha256": digest(encoded(record["config"]))})
            record["replay"] = {"entrypoint": "python -m reviewproto", "command": command,
                                "input": ("patches/" + context.get("patch_sha256", input_fingerprint) + ".json") if command == "apply" else
                                         ("imports/" + context["import_sha256"] + ".json") if command in {"ingest-candidates", "ingest-clauses"} else source_filename(state),
                                "origin": state["source"]["origin"], "workspace": "."}
            if command == "run":
                record["replay"]["source_format"] = {"native_docx": "docx", "structured_json": "json", "structured_csv": "csv"}[state["source"]["kind"]]
            self._record(record)
            self.db.execute("COMMIT")
            committed = True
            self.publish(record)
            return state
        except Exception as error:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            record.update(context)
            if hasattr(error, "source_fingerprint"):
                record["source_fingerprint"] = error.source_fingerprint
                record["input_id"] = error.source_fingerprint
                if record.get("input_fingerprint") is None:
                    record["input_fingerprint"] = error.source_fingerprint
            if command == "run":
                record["input_id"] = record.get("input_fingerprint")
            record.update({"status": "output_failed" if committed else "failed", "finished_at": now(),
                           "error_code": str(error) if isinstance(error, ReviewError) else "E_INTERNAL"})
            self._record(record)
            try:
                atomic(self.path / "runs" / (record["run_id"] + ".json"), encoded(record))
            except Exception:
                pass
            raise

    def publish(self, record=None):
        # A read/write transaction serializes projection publication with mutation.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            state = self.state()
            from .render import render
            snapshot, report = encoded(state), render(state).encode("utf-8")
            atomic(self.path / "state.json", snapshot)
            atomic(self.path / "report.html", report)
            if record is not None:
                record.update({"status": "complete", "finished_at": now(),
                               "published_revision": state["revision"],
                               "outputs": {"state.json": digest(snapshot), "report.html": digest(report),
                                           source_filename(state): state["source"]["sha256"]}})
                self._record(record)
            for rid, payload in self.db.execute("SELECT id, payload FROM runs").fetchall():
                atomic(self.path / "runs" / (rid + ".json"), payload.encode())
            for pid, payload in self.db.execute("SELECT id, payload FROM patches").fetchall():
                atomic(self.path / "patches" / (pid + ".json"), payload.encode())
            for iid, payload in self.db.execute("SELECT id, payload FROM imports").fetchall():
                atomic(self.path / "imports" / (iid + ".json"), payload.encode())
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def run(self, source, origin="unknown", source_format="docx"):
        # Read bytes before freezing; do not retain filename, path, identity guesses.
        context = {}
        def action():
            data = read_input(source, 40_000_000, context=context)
            old = self.db.execute("SELECT payload FROM state WHERE id=1").fetchone()
            if old:
                state = self.state()
                require(digest(data) == state["source"]["sha256"], "E_SOURCE_MISMATCH")
                require(origin == state["source"]["origin"], "E_ORIGIN_CONFLICT")
                require(state["versions"]["extractor"] == EXTRACTOR, "E_EXTRACTOR_VERSION")
                # Identical inputs/configuration reuse immutable candidates and all decisions.
                return state
            kind = {"docx": "native_docx", "json": "structured_json", "csv": "structured_csv"}.get(source_format)
            require(kind is not None, "E_SOURCE_KIND")
            state = parse_docx(data) if kind == "native_docx" else parse_structured(data, kind)
            require(origin in {"synthetic", "original_review", "unknown"}, "E_ORIGIN")
            state["source"]["origin"] = origin
            state["candidates"] = extract(state)
            for candidate in state["candidates"]:
                validate_candidate(candidate, state, allow_pending=True)
            source_path = self.path / source_filename(state)
            if source_path.exists():
                require(digest(read_input(source_path, 40_000_000)) == digest(data), "E_SOURCE_MISMATCH")
            else:
                atomic(source_path, data)
            return state
        return self.operation("run", action, input_context=context)

    def apply(self, patch=None, *, input_path=None):
        context = {}
        def action():
            nonlocal patch
            if input_path is not None:
                data = read_input(input_path, 10_000_000, "E_PATCH_LIMIT", context)
                try:
                    patch = json.loads(data)
                except Exception:
                    raise ReviewError("E_PATCH_JSON") from None
            context["patch_sha256"] = digest(encoded(patch))
            state = self.state()
            required = {"schema_version", "source_id", "base_revision", "actor", "reason", "edits"}
            require(isinstance(patch, dict) and required <= set(patch) and set(patch) <= required | {"creates", "concepts"}, "E_PATCH_SHAPE")
            require(patch["schema_version"] == SCHEMA and patch["source_id"] == state["source"]["source_id"], "E_PATCH_SOURCE")
            fingerprint = digest(encoded(patch))
            if fingerprint in state["applied_patches"]:
                return state
            require(type(patch["base_revision"]) is int and patch["base_revision"] == state["revision"], "E_REVISION_CONFLICT")
            require(all(isinstance(patch[k], str) and patch[k].strip() and len(patch[k]) <= 2000 for k in ("actor", "reason")), "E_AUDIT_REQUIRED")
            require(isinstance(patch["edits"], list) and isinstance(patch.get("creates", []), list), "E_PATCH_SHAPE")
            require(bool(patch["edits"] or patch.get("creates") or patch.get("concepts")), "E_PATCH_EMPTY")
            candidates = {c["candidate_id"]: c for c in state["candidates"]}
            previous = {d["candidate_id"]: d for d in state["decisions"]}
            seen = set()
            decisions = []
            timestamp = now()
            registry_updates(state, patch.get("concepts", []), patch["actor"], patch["reason"], timestamp)

            def decide(cid, value, kind):
                validate_candidate(value, state)
                decisions.append({"decision_id": uuid.uuid4().hex, "candidate_id": cid, "kind": kind,
                                  "revision": state["revision"] + 1, "actor": patch["actor"], "reason": patch["reason"],
                                  "at": timestamp, "patch_sha256": fingerprint, "value": value})

            additions, replaced = [], set()
            for creation in patch.get("creates", []):
                required_create = {"candidate_id", "section_id", "fields"}
                require(isinstance(creation, dict) and required_create <= set(creation) and set(creation) <= required_create | {"parent_ids", "replaces"}, "E_PATCH_CREATE")
                cid = creation["candidate_id"]
                require(isinstance(cid, str) and re.fullmatch(r"[A-Za-z0-9_-]{8,100}", cid) and cid not in candidates, "E_PATCH_CANDIDATE")
                require(isinstance(creation["fields"], dict) and creation["fields"].get("status") in {"confirmed", "needs_review"}, "E_PATCH_CREATE")
                parents, replacements = creation.get("parent_ids", []), creation.get("replaces", [])
                for references in (parents, replacements):
                    require(isinstance(references, list) and all(isinstance(i, str) and i in candidates and candidates[i]["section_id"] == creation["section_id"] for i in references), "E_PARENT_SCOPE")
                    require(len(set(references)) == len(references), "E_PARENT_SCOPE")
                value = candidate_value(state, creation["section_id"], cid, creation["fields"])
                value.update(parent_ids=copy.deepcopy(parents), replaces=copy.deepcopy(replacements))
                # Freeze a creation record separately from its review decision.
                original = copy.deepcopy(value)
                original.update(origin="human_created", status="needs_review")
                candidates[cid] = original
                state["candidates"].append(original)
                additions.append((cid, value))
                replaced.update(replacements)
            # Validation runs after all additions exist, permitting same-patch
            # relations between newly created independent opinions.
            for cid, value in additions:
                decide(cid, value, "create")
                seen.add(cid)
            for edit in patch["edits"]:
                require(isinstance(edit, dict) and set(edit) == {"candidate_id", "fields"}, "E_PATCH_EDIT")
                cid, fields = edit["candidate_id"], edit["fields"]
                require(isinstance(cid, str) and cid in candidates and cid not in seen, "E_PATCH_CANDIDATE")
                require(isinstance(fields, dict) and fields and set(fields) <= EDIT_FIELDS, "E_PATCH_FIELDS")
                seen.add(cid)
                value = copy.deepcopy(previous[cid]["value"] if cid in previous else candidates[cid])
                value.update(copy.deepcopy(fields))
                value.update({"origin": "human_decision"})
                # Human saves must choose an explicit review status.
                require(cid not in replaced, "E_PATCH_REPLACEMENT_CONFLICT")
                decide(cid, value, "edit")
            for cid in sorted(replaced):
                require(cid not in seen, "E_PATCH_REPLACEMENT_CONFLICT")
                value = copy.deepcopy(previous[cid]["value"] if cid in previous else candidates[cid])
                value.update(origin="human_decision", status="superseded")
                decide(cid, value, "replacement")
            state["revision"] += 1
            state["decisions"].extend(decisions)
            state["applied_patches"][fingerprint] = state["revision"]
            self.db.execute("INSERT OR IGNORE INTO patches VALUES (?, ?)", (fingerprint, encoded(patch).decode()))
            return state
        return self.operation("apply", action, digest(encoded(patch)) if input_path is None else None, context)

    def import_extractions(self, payload=None, *, input_path=None):
        context = {}
        def action():
            nonlocal payload
            if input_path is not None:
                try:
                    payload = json.loads(read_input(input_path, 40_000_000, context=context))
                except ReviewError:
                    raise
                except Exception:
                    raise ReviewError("E_EXTRACTION_JSON") from None
            state = extraction_import(self.state(), payload, now())
            context["import_sha256"] = digest(encoded(payload))
            self.db.execute("INSERT OR IGNORE INTO imports VALUES (?, ?)", (context["import_sha256"], encoded(payload).decode()))
            run = next(r for r in state["extraction_runs"] if r["run_id"] == payload["run_id"])
            self.last_import_summary = {"status": run["status"], "accepted": len(run["accepted_ids"]), "rejected": len(run["rejected"])}
            return state
        return self.operation("ingest-candidates", action, input_context=context)

    def import_clauses(self, payload=None, *, input_path=None):
        context = {}
        def action():
            nonlocal payload
            if input_path is not None:
                try:
                    payload = json.loads(read_input(input_path, 10_000_000, context=context))
                except ReviewError:
                    raise
                except Exception:
                    raise ReviewError("E_CLAUSE_JSON") from None
            from .understanding import clause_import
            state = clause_import(self.state(), payload, now())
            context["import_sha256"] = digest(encoded(payload))
            self.db.execute("INSERT OR IGNORE INTO imports VALUES (?, ?)", (context["import_sha256"], encoded(payload).decode()))
            return state
        return self.operation("ingest-clauses", action, input_context=context)

    def review_template(self):
        state = self.state()
        return template(state)


def template(state):
    previous = {d["candidate_id"]: d["value"] for d in state["decisions"]}
    edits = []
    for candidate in state["candidates"]:
        value = previous.get(candidate["candidate_id"], candidate)
        fields = {k: copy.deepcopy(value[k]) for k in sorted(EDIT_FIELDS) if k in value}
        if fields["status"] == "pending_review":
            fields["status"] = "needs_review"
        edits.append({"candidate_id": candidate["candidate_id"], "fields": fields})
    return {"schema_version": SCHEMA, "source_id": state["source"]["source_id"], "base_revision": state["revision"],
            "actor": "", "reason": "", "edits": edits}


def source_filename(state):
    kind = state["source"]["kind"]
    names = {"native_docx": "source.docx", "structured_json": "source.json", "structured_csv": "source.csv"}
    require(kind in names, "E_SOURCE_KIND")
    require(state["source"].get("storage_file", names[kind]) == names[kind], "E_SOURCE_KIND")
    return names[kind]
