"""Frozen DOCX evidence and deliberately restricted, score-blind candidates.

Offsets count Python Unicode code points on unnormalised cell paragraph text.
Only the independently inspected, two-cell score template is accepted.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from decimal import Decimal

from docx import Document
from docx.oxml.ns import qn

SCHEMA = 1
PARSER = "verified-two-cell-v3-style-merge-closed"
EXTRACTOR = "paragraph-conditional-baseline-v2"
SCORE_NAMES = (
    "创新性与科学性（1-5分）", "工作量（1-5分）", "学术范式（1-5分）",
    "语言表达与逻辑关系（1-5分）",
)
PUBLIC_LABELS = {"评审意见": "visibility_unknown", "评审意见（作者可见）": "author_visible"}
PRIVATE_LABEL = "其他意见（作者不可见）"


class ReviewError(Exception):
    """Safe diagnostic code only: never include source text or paths."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(ok, code="E_VALIDATION"):
    if not ok:
        raise ReviewError(code)


def native_cell_text(cell):
    """Independently decode the small native-text subset we can freeze exactly.

    Formatting properties and zero-width bookmarks are allowed. Generated text,
    revision containers and all other unrecognised content require manual intake;
    python-docx omitting a node is never evidence that the cell was empty.
    """
    from lxml import etree
    marker_tags = {qn("w:" + name) for name in ("bookmarkStart", "bookmarkEnd", "proofErr")}

    def xml_text(node):
        # CT_P/CT_R override .text with python-docx's flattened view; use the
        # underlying XML descriptor so this decoder remains independent.
        return etree._Element.text.__get__(node) or ""

    def container(node):
        require(not xml_text(node).strip(), "E_UNSUPPORTED_FEATURE")
        require(all(not (child.tail or "").strip() for child in node), "E_UNSUPPORTED_FEATURE")

    def properties(node):
        # Numbering supplies visible characters not present in paragraph.text.
        require(not list(node.iter(qn("w:numPr"))), "E_UNSUPPORTED_FEATURE")
        require(all(not xml_text(element).strip() for element in node.iter()), "E_UNSUPPORTED_FEATURE")

    def marker(node):
        require(len(node) == 0 and not xml_text(node).strip(), "E_UNSUPPORTED_FEATURE")

    def run(node):
        container(node)
        result = []
        for child in node:
            if child.tag == qn("w:rPr"):
                properties(child)
                continue
            require(len(child) == 0, "E_UNSUPPORTED_FEATURE")
            if child.tag == qn("w:t"):
                result.append(xml_text(child))
            elif child.tag in {qn("w:tab"), qn("w:ptab")}:
                marker(child)
                result.append("\t")
            elif child.tag in {qn("w:cr"), qn("w:br")}:
                marker(child)
                require(child.tag != qn("w:br") or child.get(qn("w:type"), "textWrapping") == "textWrapping", "E_UNSUPPORTED_FEATURE")
                result.append("\n")
            elif child.tag == qn("w:lastRenderedPageBreak"):
                marker(child)  # Pagination metadata, not an authored text token.
            else:
                raise ReviewError("E_UNSUPPORTED_FEATURE")
        return "".join(result)

    def hyperlink(node):
        container(node)
        result = []
        for child in node:
            if child.tag == qn("w:r"):
                result.append(run(child))
            elif child.tag in marker_tags:
                marker(child)
            else:
                raise ReviewError("E_UNSUPPORTED_FEATURE")
        return "".join(result)

    def paragraph(node):
        container(node)
        result = []
        for child in node:
            if child.tag == qn("w:pPr"):
                properties(child)
            elif child.tag == qn("w:r"):
                result.append(run(child))
            elif child.tag == qn("w:hyperlink"):
                result.append(hyperlink(child))
            elif child.tag in marker_tags:
                marker(child)
            else:
                raise ReviewError("E_UNSUPPORTED_FEATURE")
        return "".join(result)

    container(cell)
    result = []
    for child in cell:
        if child.tag == qn("w:tcPr"):
            properties(child)
        elif child.tag == qn("w:p"):
            result.append(paragraph(child))
        else:
            raise ReviewError("E_UNSUPPORTED_FEATURE")
    return "\n".join(result)


def parse_docx(data: bytes) -> dict:
    require(len(data) <= 40_000_000, "E_INPUT_LIMIT")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            require(sum(i.file_size for i in archive.infolist()) <= 100_000_000, "E_INPUT_LIMIT")
            names = archive.namelist()
            # These features need their own source/visibility mapping before support.
            require(not any(n.startswith("word/comments") for n in names), "E_UNSUPPORTED_FEATURE")
            from lxml import etree
            for part in ("word/footnotes.xml", "word/endnotes.xml"):
                if part in names:
                    root = etree.fromstring(archive.read(part), etree.XMLParser(resolve_entities=False, no_network=True))
                    require(all(e.get(qn("w:type")) in {"separator", "continuationSeparator"} for e in root), "E_UNSUPPORTED_FEATURE")
        doc = Document(io.BytesIO(data))
    except ReviewError:
        raise
    except Exception:
        raise ReviewError("E_DOCX_READ") from None
    body = doc.element.body
    validate_styles(doc)
    forbidden = ("ins", "del", "moveTo", "moveFrom", "moveToRangeStart", "moveToRangeEnd", "moveFromRangeStart", "moveFromRangeEnd",
                 "cellIns", "cellDel", "cellMerge", "drawing", "pict", "object", "altChunk", "sdt", "fldSimple", "instrText", "txbxContent",
                 "vanish", "specVanish", "webHidden", "footnoteReference", "endnoteReference")
    require(not any(list(body.iter(qn("w:" + tag))) for tag in forbidden), "E_UNSUPPORTED_FEATURE")
    # A continuation cell has no independent value. Never interpret a shared
    # visual score/comment as one filled cell followed by an empty cell.
    require(not list(body.iter(qn("w:vMerge"))), "E_UNSUPPORTED_FEATURE")
    for element in body.iter():
        tag = element.tag
        require(isinstance(tag, str), "E_UNSUPPORTED_FEATURE")
        require(not tag.startswith(("{http://schemas.openxmlformats.org/officeDocument/2006/math}",
                                    "{http://schemas.openxmlformats.org/markup-compatibility/2006}")), "E_UNSUPPORTED_FEATURE")
        require(not (tag.startswith("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}") and tag.endswith("Change")), "E_UNSUPPORTED_FEATURE")
    tables = list(body.findall(qn("w:tbl")))
    require(len(tables) == 1 and len(list(body.iter(qn("w:tbl")))) == 1, "E_TEMPLATE_TABLES")
    rows = tables[0].findall(qn("w:tr"))
    cells = [row.findall(qn("w:tc")) for row in rows]
    require(len(rows) == 13 and [len(c) for c in cells] == [1, 2, 4, 2, 1, 2, 2, 2, 2, 1, 1, 1, 1], "E_TEMPLATE_STRUCTURE")

    def cell_text(cell):
        # python-docx handles native line breaks and tabs without normalisation.
        from docx.table import _Cell
        text = _Cell(cell, doc.tables[0]).text
        require(native_cell_text(cell) == text, "E_TEXT_MAPPING")
        return text

    texts = [[cell_text(c) for c in row] for row in cells]
    score_rows = [(r, row) for r, row in enumerate(texts) if row and row[0] in SCORE_NAMES]
    require(len(score_rows) == 4 and {row[0] for _, row in score_rows} == set(SCORE_NAMES), "E_SCORE_LABELS")
    require([r for r, _ in score_rows] == list(range(score_rows[0][0], score_rows[0][0] + 4)), "E_TEMPLATE_STRUCTURE")
    scores = []
    for r, row in score_rows:
        require(len(row) == 2, "E_SCORE_STRUCTURE")
        raw = row[1]
        missing = not raw.strip()
        status = "unfilled" if missing else "present"
        number = None
        if not missing:
            if raw.strip().casefold() in {"不适用", "不适用项", "n/a", "na", "not applicable"}:
                status = "not_applicable"
            elif not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", raw.strip()):
                status = "unparseable"
            else:
                value = Decimal(raw.strip())
                if 1 <= value <= 5:
                    number = str(value)
                else:
                    status = "out_of_range"
        scores.append({"label": row[0], "raw_value": raw, "value": number,
                       "missing_state": status,
                       "missing_reason": "unknown" if number is None else "not_applicable",
                       "review_required": status != "present",
                       "scale": {"minimum": 1, "maximum": 5, "version": "unknown", "source_label": row[0]},
                       "locator": {"table": 0, "row": r, "cell": 1}, "reason_relation": "unknown"})
    end_scores = score_rows[-1][0]
    remainder = texts[end_scores + 1:]
    require(len(remainder) == 4 and all(len(row) == 1 for row in remainder), "E_SECTION_STRUCTURE")
    require(remainder[0][0] in PUBLIC_LABELS and remainder[2][0] == PRIVATE_LABEL, "E_SECTION_LABELS")
    source_id = digest(data)
    sections = []
    for index, offset in enumerate((1, 3)):
        r = end_scores + 1 + offset
        label = texts[r - 1][0]
        raw_text = texts[r][0]
        require(not re.search(r"作者[不可见\s]*可见|作者不可见|保密|confidential", raw_text, re.IGNORECASE), "E_AMBIGUOUS_VISIBILITY")
        from docx.table import _Cell
        paragraphs = _Cell(cells[r][0], doc.tables[0]).paragraphs
        mapping, cursor = [], 0
        for p, paragraph in enumerate(paragraphs):
            text = paragraph.text
            mapping.append({"paragraph": p, "start": cursor, "end": cursor + len(text)})
            cursor += len(text) + 1
        require("\n".join(p.text for p in paragraphs) == raw_text, "E_TEXT_MAPPING")
        sections.append({"section_id": f"section-{index + 1}", "source_id": source_id,
                         "label": label, "visibility": PUBLIC_LABELS.get(label, "internal_only"),
                         "text": raw_text, "normalization": "none", "offset_unit": "unicode_codepoint",
                         "locator": {"part": "word/document.xml", "table": 0, "row": r, "cell": 0},
                         "paragraphs": mapping})
    reported = [{"label": row[c], "raw_value": row[c + 1],
                 "locator": {"part": "word/document.xml", "table": 0, "row": r, "cell": c + 1}}
                for r, row in enumerate(texts[:score_rows[0][0]])
                for c in range(len(row) - 1) if row[c].strip() == "稿件ID"]
    require(len(reported) <= 1, "E_MANUSCRIPT_AMBIGUOUS")
    return {"schema_version": SCHEMA, "revision": 0,
            "source": {"source_id": source_id, "sha256": source_id, "kind": "native_docx", "access": "trusted_editors_only",
                       "manuscript_id": "unknown", "reported_manuscript_id": reported[0] if reported else None,
                       "origin": "unknown", "manuscript_version": "unknown", "submitted_version_confirmed": False},
            "review": {"review_id": source_id, "reviewer_id": "unknown", "round": "unknown", "form_version": "unknown",
                       "independence": "unknown", "paper_verification": "not_checked", "standard_alignment": "pending_comparison"},
            "versions": {"parser": PARSER, "extractor": EXTRACTOR, "annotation": "1", "framework": "unavailable"},
            "coverage": {"interpreted": "four_score_cells_and_two_comment_cells_only",
                         "excluded": "identity_header_cells_and_outside_table_paragraphs_not_interpreted",
                         "outside_table_paragraphs": [{"part": "word/document.xml", "paragraph": i, "characters": len(p.text)}
                                                      for i, p in enumerate(doc.paragraphs)],
                         "paper_content": "not_checked", "manual_source_check_required": True},
            "scores": scores, "sections": sections, "candidates": [], "decisions": [], "applied_patches": {}}


def validate_styles(doc):
    """Reject generated/hidden text in active style inheritance, not all styles.

    Ordinary documents ship unused list/hidden styles. Only referenced styles,
    their basedOn ancestors and document defaults affect this support decision.
    Cycles and missing ancestors cannot establish a safe text mapping.
    """
    root = doc.styles.element
    styles = {s.get(qn("w:styleId")): s for s in root.findall(qn("w:style"))}
    dangerous = {qn("w:" + name) for name in ("vanish", "specVanish", "webHidden", "numPr")}

    def safe(node):
        require(not any(e.tag in dangerous for e in node.iter()), "E_UNSUPPORTED_FEATURE")

    defaults = root.find(qn("w:docDefaults"))
    if defaults is not None:
        safe(defaults)
    checked = set()

    def check(sid, trail=()):
        require(sid in styles and sid not in trail, "E_STYLE_CHAIN")
        if sid in checked:
            return
        style = styles[sid]
        safe(style)
        parent = style.find(qn("w:basedOn"))
        if parent is not None:
            check(parent.get(qn("w:val")), trail + (sid,))
        checked.add(sid)

    for style in styles.values():
        if style.get(qn("w:default")) in {"1", "true", "on"}:
            check(style.get(qn("w:styleId")))
    for tag in ("pStyle", "rStyle", "tblStyle"):
        for reference in doc.element.body.iter(qn("w:" + tag)):
            check(reference.get(qn("w:val")))


def extract_section(section: dict) -> list[dict]:
    """This boundary receives one section's text and locators, never score data.

    Whole paragraphs are candidates, not asserted semantic propositions. Conditions
    spanning paragraphs remain unresolved and require editor review of the section.
    """
    result = []
    text = section["text"]
    for paragraph in section["paragraphs"]:
        start, end = paragraph["start"], paragraph["end"]
        quote = text[start:end]
        if not quote.strip():
            continue
        evidence = {"source_id": section["source_id"], "section_id": section["section_id"],
                    "start": start, "end": end, "quote": quote, "precision": "exact"}
        cid = digest((section["source_id"] + section["section_id"] + f":{start}:{end}:" + EXTRACTOR).encode())[:24]
        hints = [term for term in ("样本规模", "代表性", "有条件", "无条件", "否则", "或者", "建议", "必须", "不") if term in quote]
        candidate = {"candidate_id": cid, "section_id": section["section_id"], "visibility": section["visibility"],
                       "origin": "rule_candidate", "status": "pending_review", "interpretation": "unknown",
                       "evidence": [evidence], "object": "unknown", "attributes": [], "direction": "unknown",
                       "speech_function": "unknown", "requirement_strength": "unknown", "severity": "unknown",
                       "action": "unknown", "conditions": [], "alternatives": [], "relations": [],
                       "paper_verification": "not_checked", "standard_alignment": "pending_comparison",
                       "review_flags": ["semantic_extraction_unverified", "section_context_required"], "lexical_hints": hints}
        literal_branches(candidate, quote, start)
        result.append(candidate)
    return result


def literal_branches(candidate, paragraph, paragraph_start):
    """Narrow paired surface form only; no cross-sentence condition inference.

    Quotation and negative/metalinguistic markers abstain conservatively. This is
    a reviewable rule match, not an assertion that the paper needs either action.
    The paragraph candidate is retained, including all unmatched surrounding text.
    """
    pattern = re.compile(r"(?:^|[；;])(?P<first>有条件(?P<a1>[^，,。！？\n；;]+))[，,][ \t]*(?P<second>无条件则(?P<a2>[^。！？\n；;]+))。")
    if any(mark in paragraph for mark in ('“', '”', '‘', '’', '"', "'", '「', '」', '『', '』', '《', '》')):
        return
    for match in pattern.finditer(paragraph):
        actions = (match.group("a1"), match.group("a2"))
        if any(re.search(r"不|未|无|否|引用|原话|声称|提及|假设|例如|示例", action) for action in actions):
            continue
        indices = []
        for group in ("first", "second"):
            left, right = match.span(group)
            evidence = dict(candidate["evidence"][0], start=paragraph_start + left, end=paragraph_start + right, quote=match.group(group))
            indices.append(len(candidate["evidence"]))
            candidate["evidence"].append(evidence)
        for condition, index in zip(("有条件", "无条件"), indices):
            candidate["conditions"].append({"text": condition, "meaning": "unknown", "evidence_indices": [index], "provenance": "explicit"})
        candidate["alternatives"].append({"relation": "conditional_branches", "provenance": "explicit", "branches": [
            {"condition": "有条件", "action": actions[0], "evidence_indices": [indices[0]]},
            {"condition": "无条件", "action": actions[1], "evidence_indices": [indices[1]]}]})
        candidate["review_flags"].append("literal_conditional_pair_requires_human_review")


def extract(state: dict) -> list[dict]:
    return [candidate for section in state["sections"] for candidate in extract_section(section)]


EDIT_FIELDS = {"evidence", "object", "attributes", "direction", "speech_function", "requirement_strength", "severity", "action",
               "conditions", "alternatives", "conditional_actions", "relations", "interpretation", "status", "concept_ids", "clause_links", "reasons", "negation"}
ENUMS = {"direction": {"positive", "negative", "mixed", "neutral", "unknown"},
         "speech_function": {"evaluation", "suggestion", "requirement", "question", "description", "mixed", "unknown"},
         "requirement_strength": {"mandatory", "recommended", "optional", "unknown"},
         "severity": {"minor", "major", "critical", "unknown"},
         "interpretation": {"explicit", "inferred", "unknown"},
         "status": {"confirmed", "rejected", "needs_review", "superseded", "withdrawn"}}


def validate_candidate(candidate: dict, state: dict, *, allow_pending=False):
    sections = {s["section_id"]: s for s in state["sections"]}
    require(candidate["section_id"] in sections)
    section = sections[candidate["section_id"]]
    require(candidate["visibility"] == section["visibility"], "E_VISIBILITY")
    if allow_pending:
        require(candidate.get("origin") in {"rule_candidate", "model_candidate"} and candidate.get("status") == "pending_review", "E_MACHINE_STATUS")
    evidence = candidate["evidence"]
    require(isinstance(evidence, list) and len(evidence) > 0, "E_EVIDENCE")
    for e in evidence:
        require(isinstance(e, dict) and set(e) == {"source_id", "section_id", "start", "end", "quote", "precision"}, "E_EVIDENCE")
        require(e["source_id"] == state["source"]["source_id"] and e["section_id"] == section["section_id"], "E_EVIDENCE_SCOPE")
        require(type(e["start"]) is int and type(e["end"]) is int and 0 <= e["start"] < e["end"] <= len(section["text"]), "E_EVIDENCE_OFFSET")
        require(e["precision"] == "exact" and section["text"][e["start"]:e["end"]] == e["quote"], "E_EVIDENCE_QUOTE")
    for field, options in ENUMS.items():
        if field == "status" and allow_pending:
            options = options | {"pending_review"}
        require(isinstance(candidate[field], str) and candidate[field] in options, "E_FIELD_ENUM")
    for field in ("object", "action"):
        require(isinstance(candidate[field], str) and 0 < len(candidate[field]) <= 20_000, "E_FIELD_TEXT")
    require(isinstance(candidate["attributes"], list) and len(candidate["attributes"]) <= 100 and all(isinstance(v, str) and v for v in candidate["attributes"]), "E_ATTRIBUTES")
    def refs(value):
        require(isinstance(value, list) and value and all(type(i) is int and 0 <= i < len(evidence) for i in value), "E_EVIDENCE_REFS")
    require(isinstance(candidate["conditions"], list) and isinstance(candidate["alternatives"], list) and isinstance(candidate["relations"], list), "E_FIELD_LIST")
    for condition in candidate["conditions"]:
        require(isinstance(condition, dict) and set(condition) == {"text", "meaning", "evidence_indices", "provenance"}, "E_CONDITION")
        require(isinstance(condition["text"], str) and condition["text"] and condition["meaning"] in {"known", "unknown"}, "E_CONDITION")
        require(condition["provenance"] in {"explicit", "inferred", "unknown"}, "E_PROVENANCE")
        refs(condition["evidence_indices"])
    for group in candidate["alternatives"]:
        require(isinstance(group, dict) and set(group) == {"relation", "branches", "provenance"}, "E_ALTERNATIVE")
        require(group["relation"] in {"either_or", "conditional_branches", "unknown"} and group["provenance"] in {"explicit", "inferred", "unknown"}, "E_ALTERNATIVE")
        require(isinstance(group["branches"], list) and len(group["branches"]) >= 2, "E_ALTERNATIVE")
        for branch in group["branches"]:
            require(isinstance(branch, dict) and set(branch) == {"condition", "action", "evidence_indices"}, "E_ALTERNATIVE")
            require(all(isinstance(branch[k], str) and branch[k] for k in ("condition", "action")), "E_ALTERNATIVE")
            refs(branch["evidence_indices"])
    for relation in candidate["relations"]:
        require(isinstance(relation, dict) and set(relation) == {"type", "target", "provenance", "evidence_indices"}, "E_RELATION")
        require(relation["type"] in {"supports", "opposes", "explains", "alternative", "condition_of", "explains_score", "unknown"} and relation["provenance"] in {"explicit", "inferred", "unknown"}, "E_RELATION")
        claims = {c["candidate_id"] for c in state["candidates"] if c["section_id"] == section["section_id"]}
        score_labels = {s["label"] for s in state["scores"]}
        targets = score_labels if relation["type"] == "explains_score" else claims
        if relation["type"] == "unknown":
            targets = targets | score_labels
        require(isinstance(relation["target"], str) and relation["target"] in targets, "E_RELATION_TARGET")
        refs(relation["evidence_indices"])
    from .understanding import validate_extensions
    validate_extensions(candidate, state, refs)
