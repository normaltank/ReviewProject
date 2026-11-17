"""Shared local file and strict JSON operations for trusted editing workspaces."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .core import ReviewError, require

PRIVATE_IGNORE = b"*\n# Managed private reviewproto workspace; never commit local data.\n"
LIMIT = 10_000_000


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


def checked_local(path):
    path = Path(path).absolute()
    require(all(not linklike(p) for p in [path, *path.parents]), 'E_BATCH_LINK')
    return path.resolve()


def bounded(value):
    require(len(encoded(value)) <= LIMIT, 'E_BATCH_LIMIT')
    return value


def read_json(path):
    return bounded(load_json(read_input(checked_local(path), LIMIT, 'E_BATCH_LIMIT')))
