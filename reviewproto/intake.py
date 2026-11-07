"""Explicit structured intake; raw bytes and source field locations stay frozen."""
import csv
import io
import json
import re
from decimal import Decimal

from .core import SCHEMA, EXTRACTOR, PARSER, SCORE_NAMES, PUBLIC_LABELS, PRIVATE_LABEL, digest, require, ReviewError


def score_value(label, raw, locator):
    require(isinstance(label, str) and bool(label.strip()) and isinstance(raw, str), "E_SCORE_STRUCTURE")
    status, number = "present", None
    if not raw.strip():
        status = "unfilled"
    elif raw.strip().casefold() in {"不适用", "不适用项", "n/a", "na", "not applicable"}:
        status = "not_applicable"
    elif not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", raw.strip()):
        status = "unparseable"
    elif 1 <= Decimal(raw.strip()) <= 5:
        number = str(Decimal(raw.strip()))
    else:
        status = "out_of_range"
    return {"label": label, "raw_value": raw, "value": number, "missing_state": status,
            "missing_reason": "unknown" if number is None else "not_applicable", "review_required": status != "present",
            "scale": {"minimum": 1, "maximum": 5, "version": "unknown", "source_label": label},
            "locator": locator, "reason_relation": "unknown"}


def parse_structured(data, kind):
    require(kind in {"structured_json", "structured_csv"}, "E_SOURCE_KIND")
    source_id = digest(data)
    metadata = {}
    if kind == "structured_csv":
        try:
            rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
        except Exception:
            raise ReviewError("E_CSV_READ") from None
        require(len(rows) == 6 and all(len(row) == 6 for row in rows), "E_CSV_STRUCTURE")
        require(rows[0][::2] == ["期刊名称", "稿件ID", "投稿日期"] and rows[1][0] == "稿件标题" and not any(rows[1][2:]), "E_CSV_STRUCTURE")
        require(rows[2][::2] == list(SCORE_NAMES[:3]) and rows[3][0] == SCORE_NAMES[3] and not any(rows[3][2:]), "E_SCORE_LABELS")
        require(rows[4][0] in PUBLIC_LABELS and rows[5][0] == PRIVATE_LABEL and not any(rows[4][2:] + rows[5][2:]), "E_SECTION_LABELS")
        scores = [score_value(rows[r][c], rows[r][c + 1], {"row": r, "cell": c + 1}) for r, c in ((2, 0), (2, 2), (2, 4), (3, 0))]
        raw_sections = [{"section_id": f"section-{index + 1}", "label": rows[r][0], "text": rows[r][1],
                         "visibility": PUBLIC_LABELS.get(rows[r][0], "internal_only"), "locator": {"row": r, "cell": 1}} for index, r in enumerate((4, 5))]
        metadata = {rows[0][i]: {"raw_value": rows[0][i + 1], "locator": {"row": 0, "cell": i + 1}} for i in (0, 2, 4)}
        metadata[rows[1][0]] = {"raw_value": rows[1][1], "locator": {"row": 1, "cell": 1}}
    else:
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except Exception:
            raise ReviewError("E_STRUCTURED_JSON") from None
        require(isinstance(payload, dict) and {"scores", "sections"} <= set(payload) and set(payload) <= {"schema_version", "scores", "sections", "metadata"}, "E_STRUCTURED_SHAPE")
        require(payload.get("schema_version", 1) == 1, "E_SCHEMA_VERSION")
        require(isinstance(payload["scores"], list) and isinstance(payload["sections"], list) and bool(payload["sections"]), "E_STRUCTURED_SHAPE")
        scores = []
        for index, score in enumerate(payload["scores"]):
            require(isinstance(score, dict) and set(score) == {"label", "raw_value"}, "E_SCORE_STRUCTURE")
            scores.append(score_value(score["label"], score["raw_value"], {"pointer": f"/scores/{index}/raw_value"}))
        require(len({s["label"] for s in scores}) == len(scores), "E_SCORE_LABELS")
        raw_sections = []
        for index, section in enumerate(payload["sections"]):
            require(isinstance(section, dict) and {"section_id", "label", "text"} <= set(section) and set(section) <= {"section_id", "label", "text", "visibility"}, "E_SECTION_STRUCTURE")
            label = section["label"]
            visibility = section.get("visibility", "internal_only" if label == PRIVATE_LABEL else "visibility_unknown")
            require(visibility in {"internal_only", "visibility_unknown", "author_visible"}, "E_VISIBILITY")
            require(label != PRIVATE_LABEL or visibility == "internal_only", "E_VISIBILITY")
            # A public label alone cannot authorize expansion of an unknown label.
            require(visibility != "author_visible" or label == "评审意见（作者可见）", "E_VISIBILITY")
            raw_sections.append(dict(section, visibility=visibility, locator={"pointer": f"/sections/{index}/text"}))
        metadata = payload.get("metadata", {})
        require(isinstance(metadata, dict), "E_STRUCTURED_SHAPE")
    sections, seen = [], set()
    for section in raw_sections:
        sid, text = section["section_id"], section["text"]
        require(isinstance(sid, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sid)) and sid not in seen, "E_SECTION_ID")
        require(isinstance(section["label"], str) and isinstance(text, str), "E_SECTION_STRUCTURE")
        require(not re.search(r"作者[不可见\s]*可见|作者不可见|保密|confidential", text, re.IGNORECASE), "E_AMBIGUOUS_VISIBILITY")
        seen.add(sid)
        paragraphs, cursor = [], 0
        for index, paragraph in enumerate(text.split("\n")):
            paragraphs.append({"paragraph": index, "start": cursor, "end": cursor + len(paragraph)})
            cursor += len(paragraph) + 1
        sections.append(dict(section, source_id=source_id, normalization="none", offset_unit="unicode_codepoint", paragraphs=paragraphs))
    return {"schema_version": SCHEMA, "revision": 0,
            "source": {"source_id": source_id, "sha256": source_id, "kind": kind, "storage_file": "source.csv" if kind == "structured_csv" else "source.json",
                       "access": "trusted_editors_only", "origin": "unknown", "manuscript_id": "unknown", "manuscript_version": "unknown",
                       "submitted_version_confirmed": False, "reported_manuscript_id": metadata.get("稿件ID"), "reported_metadata": metadata},
            "review": {"review_id": source_id, "reviewer_id": "unknown", "round": "unknown", "form_version": "unknown", "independence": "unknown",
                       "paper_verification": "not_checked", "standard_alignment": "pending_comparison"},
            "versions": {"parser": PARSER + "+explicit-structured-v1", "extractor": EXTRACTOR, "annotation": "1", "framework": "unavailable"},
            "coverage": {"interpreted": "explicit_scores_and_comment_sections", "paper_content": "not_checked", "manual_source_check_required": True},
            "scores": scores, "sections": sections, "candidates": [], "decisions": [], "applied_patches": {}}
