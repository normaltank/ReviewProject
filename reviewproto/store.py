"""SQLite is authoritative; JSON and HTML projections are recoverable artifacts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from docx import __version__ as docx_version

from . import __version__
from .core import SCHEMA, EXTRACTOR, ReviewError, digest, extract, parse_docx, require, validate_candidate, EDIT_FIELDS


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
        self.path = Path(path).resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        # Reject managed symlinks, including projections, so trusted local output
        # cannot silently write through a link to another location.
        reserved = {"review.sqlite3", "source.docx", "state.json", "report.html", "runs", "patches"}
        for entry in self.path.iterdir():
            if entry.name.casefold() in reserved or entry.name.casefold().startswith("review.sqlite3"):
                require(not entry.is_symlink(), "E_WORKSPACE_LINK")
        db_path = self.path / "review.sqlite3"
        if not db_path.exists():
            require(not any(e.name.casefold() in reserved or e.name.casefold().startswith("review.sqlite3")
                            for e in self.path.iterdir()), "E_WORKSPACE_UNMANAGED")
        else:
            # Inspect read-only before any DDL can mutate an unrelated database.
            check = None
            try:
                check = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
                application_id = check.execute("PRAGMA application_id").fetchone()[0]
                if application_id != self.APPLICATION_ID:
                    # Migration for this prototype's earlier local workspaces.
                    require(application_id == 0, "E_WORKSPACE_UNMANAGED")
                    names = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    require({"state", "runs", "patches"} <= names, "E_WORKSPACE_UNMANAGED")
                    row = check.execute("SELECT payload FROM state WHERE id=1").fetchone()
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
        self.db = sqlite3.connect(self.path / "review.sqlite3", timeout=10, isolation_level=None)
        self.db.execute(f"PRAGMA application_id={self.APPLICATION_ID}")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS patches (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def close(self):
        self.db.close()

    def state(self):
        row = self.db.execute("SELECT payload FROM state WHERE id=1").fetchone()
        require(row is not None, "E_WORKSPACE_EMPTY")
        state = json.loads(row[0])
        require(state.get("schema_version") == SCHEMA, "E_SCHEMA_VERSION")
        require(digest(read_input(self.path / "source.docx", 40_000_000)) == state["source"]["sha256"], "E_SOURCE_CHANGED")
        return state

    def save(self, state):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (encoded(state).decode(),))

    def _record(self, record):
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (record["run_id"], encoded(record).decode()))

    def operation(self, command, callback, input_fingerprint=None, input_context=None):
        context = input_context if input_context is not None else {}
        record = {"run_id": uuid.uuid4().hex, "command": command, "started_at": now(), "status": "running",
                  "software": __version__, "python": sys.version.split()[0], "dependencies": {"python-docx": docx_version},
                  "config": {"offline": True, "audience": "trusted_editors", "extractor": EXTRACTOR},
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
                                "input": ("patches/" + context.get("patch_sha256", input_fingerprint) + ".json") if command == "apply" else "source.docx",
                                "origin": state["source"]["origin"], "workspace": "."}
            self._record(record)
            self.db.execute("COMMIT")
            committed = True
            self.publish(record)
            return state
        except Exception as error:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            record.update(context)
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
                                           "source.docx": state["source"]["sha256"]}})
                self._record(record)
            for rid, payload in self.db.execute("SELECT id, payload FROM runs").fetchall():
                atomic(self.path / "runs" / (rid + ".json"), payload.encode())
            for pid, payload in self.db.execute("SELECT id, payload FROM patches").fetchall():
                atomic(self.path / "patches" / (pid + ".json"), payload.encode())
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def run(self, source, origin="unknown"):
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
            state = parse_docx(data)
            require(origin in {"synthetic", "original_review", "unknown"}, "E_ORIGIN")
            state["source"]["origin"] = origin
            state["candidates"] = extract(state)
            for candidate in state["candidates"]:
                validate_candidate(candidate, state, allow_pending=True)
            source_path = self.path / "source.docx"
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
            require(isinstance(patch, dict) and set(patch) == {"schema_version", "source_id", "base_revision", "actor", "reason", "edits"}, "E_PATCH_SHAPE")
            require(patch["schema_version"] == SCHEMA and patch["source_id"] == state["source"]["source_id"], "E_PATCH_SOURCE")
            fingerprint = digest(encoded(patch))
            if fingerprint in state["applied_patches"]:
                return state
            require(type(patch["base_revision"]) is int and patch["base_revision"] == state["revision"], "E_REVISION_CONFLICT")
            require(all(isinstance(patch[k], str) and patch[k].strip() and len(patch[k]) <= 2000 for k in ("actor", "reason")), "E_AUDIT_REQUIRED")
            require(isinstance(patch["edits"], list) and bool(patch["edits"]), "E_PATCH_EMPTY")
            candidates = {c["candidate_id"]: c for c in state["candidates"]}
            previous = {d["candidate_id"]: d for d in state["decisions"]}
            seen = set()
            decisions = []
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
                validate_candidate(value, state)
                decisions.append({"decision_id": uuid.uuid4().hex, "candidate_id": cid,
                                  "revision": state["revision"] + 1, "actor": patch["actor"], "reason": patch["reason"],
                                  "at": now(), "patch_sha256": fingerprint, "value": value})
            state["revision"] += 1
            state["decisions"].extend(decisions)
            state["applied_patches"][fingerprint] = state["revision"]
            self.db.execute("INSERT OR IGNORE INTO patches VALUES (?, ?)", (fingerprint, encoded(patch).decode()))
            return state
        return self.operation("apply", action, digest(encoded(patch)) if input_path is None else None, context)

    def review_template(self):
        state = self.state()
        return template(state)


def template(state):
    previous = {d["candidate_id"]: d["value"] for d in state["decisions"]}
    edits = []
    for candidate in state["candidates"]:
        value = previous.get(candidate["candidate_id"], candidate)
        fields = {k: copy.deepcopy(value[k]) for k in sorted(EDIT_FIELDS)}
        if fields["status"] == "pending_review":
            fields["status"] = "needs_review"
        edits.append({"candidate_id": candidate["candidate_id"], "fields": fields})
    return {"schema_version": SCHEMA, "source_id": state["source"]["source_id"], "base_revision": state["revision"],
            "actor": "", "reason": "", "edits": edits}
