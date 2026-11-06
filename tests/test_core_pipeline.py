import copy
import io
import json
from pathlib import Path
import sqlite3
import os
import subprocess
import tempfile
import concurrent.futures
import unittest
from unittest.mock import patch

from docx import Document

from reviewproto.core import ReviewError, SCORE_NAMES, digest, extract, parse_docx
from reviewproto.store import Workspace, read_input, template
from reviewproto.cli import main


def fixture(text="相同短句😀。\n相同短句😀。有条件补案例，无条件则披露待实践检验。", private="内部意见"):
    doc = Document()
    table = doc.add_table(rows=13, cols=4)
    for row in (0, 4, 9, 10, 11, 12):
        table.cell(row, 0).merge(table.cell(row, 3))
    for row in (1, 3):
        table.cell(row, 0).merge(table.cell(row, 1))
        table.cell(row, 2).merge(table.cell(row, 3))
    table.cell(2, 0).text = "稿件ID"
    table.cell(2, 1).text = "SYNTHETIC-ID"
    for index, name in enumerate(SCORE_NAMES):
        row = 5 + index
        table.cell(row, 0).merge(table.cell(row, 2))
        table.cell(row, 0).text = name
        table.cell(row, 3).text = ("3.5", "4.5", "", "4")[index]
    table.cell(9, 0).text = "评审意见"
    table.cell(10, 0).text = text
    table.cell(11, 0).text = "其他意见（作者不可见）"
    table.cell(12, 0).text = private
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def native_variant(kind, target="comment"):
    """Native Word XML regressions, not text approximations of these features."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from lxml import etree
    doc = Document(io.BytesIO(fixture()))
    cell = doc.tables[0].cell(5, 3) if target == "score" else doc.tables[0].cell(10, 0)
    paragraph = cell.paragraphs[0]._p
    if target == "score":
        for node in list(paragraph):
            if node.tag != qn("w:pPr"):
                paragraph.remove(node)
    if kind in {"moveTo", "moveFrom"}:
        node = OxmlElement("w:" + kind)
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "4" if target == "score" else "SYNTHETIC_MOVED_COMMENT"
        run.append(text)
        node.append(run)
        paragraph.append(node)
    elif kind in {"oMath", "oMathPara"}:
        equation = OxmlElement("m:oMath")
        run = OxmlElement("m:r")
        text = OxmlElement("m:t")
        text.text = "4" if target == "score" else "SYNTHETIC_FORMULA"
        run.append(text)
        equation.append(run)
        if kind == "oMathPara":
            outer = OxmlElement("m:oMathPara")
            outer.append(equation)
            equation = outer
        paragraph.append(equation)
    elif kind == "AlternateContent":
        ns = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
        node = etree.Element(ns + "AlternateContent")
        choice = etree.SubElement(node, ns + "Choice", Requires="w14")
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "4" if target == "score" else "SYNTHETIC_ALTERNATE"
        run.append(text)
        choice.append(run)
        paragraph.append(node)
    elif kind == "numPr":
        properties = paragraph.get_or_add_pPr()
        node = OxmlElement("w:numPr")
        number = OxmlElement("w:numId")
        number.set(qn("w:val"), "1")
        node.append(number)
        properties.append(node)
    else:
        run = OxmlElement("w:r")
        node = OxmlElement("w:" + kind)
        if kind == "sym":
            node.set(qn("w:font"), "Symbol")
            node.set(qn("w:char"), "F061")
        run.append(node)
        paragraph.append(run)
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "input.docx"
        self.source.write_bytes(fixture())
        self.ws = Workspace(self.root / "work")
        self.state = self.ws.run(self.source, "synthetic")

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def patch_for(self):
        p = template(self.ws.state())
        p.update(actor="测试编辑", reason="核对原文")
        p["edits"] = p["edits"][:1]
        p["edits"][0]["fields"]["status"] = "confirmed"
        return p

    def test_scores_missing_and_identity(self):
        self.assertEqual([s["raw_value"] for s in self.state["scores"]], ["3.5", "4.5", "", "4"])
        self.assertEqual(self.state["scores"][2]["missing_state"], "unfilled")
        self.assertIsNone(self.state["scores"][2]["value"])
        self.assertFalse(self.state["source"]["submitted_version_confirmed"])
        self.assertEqual(self.state["source"]["reported_manuscript_id"]["raw_value"], "SYNTHETIC-ID")

    def test_anomalous_scores_are_preserved_without_invented_values(self):
        doc = Document(io.BytesIO(fixture()))
        raw_values = ["0", "65", "4分", "不适用"]
        for index, raw in enumerate(raw_values):
            doc.tables[0].cell(5 + index, 3).text = raw
        buffer = io.BytesIO()
        doc.save(buffer)
        state = parse_docx(buffer.getvalue())
        self.assertEqual([s["raw_value"] for s in state["scores"]], raw_values)
        self.assertEqual([s["missing_state"] for s in state["scores"]], ["out_of_range", "out_of_range", "unparseable", "not_applicable"])
        self.assertTrue(all(s["value"] is None for s in state["scores"]))

    def test_unicode_discontinuous_evidence(self):
        p = self.patch_for()
        section = self.state["sections"][0]
        quote = "相同短句😀。"
        e = p["edits"][0]["fields"]["evidence"][0]
        first = dict(e, start=0, end=len(quote), quote=quote)
        start = section["text"].index(quote, 1)
        second = dict(e, start=start, end=start + len(quote), quote=quote)
        p["edits"][0]["fields"]["evidence"] = [first, second]
        state = self.ws.apply(p)
        self.assertEqual(len(state["decisions"][0]["value"]["evidence"]), 2)
        bad = template(state)
        bad.update(actor="editor", reason="bad offset")
        bad["edits"][0]["fields"]["evidence"][1]["start"] += 1
        with self.assertRaisesRegex(ReviewError, "E_EVIDENCE_QUOTE"):
            self.ws.apply(bad)

    def test_conditional_branches_roundtrip(self):
        p = self.patch_for()
        fields = p["edits"][0]["fields"]
        fields["conditions"] = [{"text": "有条件（含义未说明）", "meaning": "unknown", "evidence_indices": [0], "provenance": "explicit"}]
        fields["alternatives"] = [{"relation": "conditional_branches", "provenance": "explicit", "branches": [
            {"condition": "有条件", "action": "补案例", "evidence_indices": [0]},
            {"condition": "无条件", "action": "披露待实践检验", "evidence_indices": [0]}]}]
        fields["attributes"] = ["样本规模", "代表性"]
        fields["interpretation"] = "explicit"
        result = self.ws.apply(p)
        self.assertEqual(result["decisions"][0]["value"]["alternatives"], fields["alternatives"])
        self.assertEqual(result["decisions"][0]["value"]["requirement_strength"], "unknown")

    def test_narrow_literal_rule_retains_branch_spans_and_abstains(self):
        text = "整体表达清晰；有条件补充匿名访谈，无条件则说明资料局限。其余分析待复核😀。"
        state = parse_docx(fixture(text))
        candidates = extract(state)
        state["candidates"] = candidates
        c = candidates[0]
        self.assertEqual(c["evidence"][0]["quote"], text)
        self.assertEqual([b["action"] for b in c["alternatives"][0]["branches"]], ["补充匿名访谈", "说明资料局限"])
        self.assertTrue(all(v["meaning"] == "unknown" for v in c["conditions"]))
        self.assertEqual(c["status"], "pending_review")
        self.assertEqual(c["requirement_strength"], "unknown")
        self.assertEqual(c["relations"], [])
        from reviewproto.render import render
        report = render(state)
        self.assertIn('href="source.docx" download', report)
        self.assertIn('href="#candidate-' + c["candidate_id"] + '"', report)
        self.assertIn('id="candidate-' + c["candidate_id"] + '"', report)
        self.assertIn("具体条件含义：unknown", report)
        self.assertNotIn("在下方 JSON 填写", report)
        for evidence in c["evidence"]:
            self.assertEqual(text[evidence["start"]:evidence["end"]], evidence["quote"])
        for negative in (
            "有条件不必补访谈，无条件则说明局限。",
            "有条件补访谈，无条件则无需说明局限。",
            "有人写道：‘有条件补访谈，无条件则说明局限。’",
            "如果有条件补访谈，无条件则说明局限。",
            "有条件补访谈。无条件则说明局限。",
            "有条件补访谈，\n无条件则说明局限。",
        ):
            self.assertFalse(extract(parse_docx(fixture(negative)))[0]["alternatives"])

    def test_decision_idempotency_history_and_revision_conflict(self):
        p = self.patch_for()
        result = self.ws.apply(p)
        self.assertEqual(self.ws.apply(p), result)
        rerun = self.ws.run(self.source, "synthetic")
        self.assertEqual(rerun, result)
        stale = copy.deepcopy(p)
        stale["reason"] = "different action"
        with self.assertRaisesRegex(ReviewError, "E_REVISION_CONFLICT"):
            self.ws.apply(stale)
        update = self.patch_for()
        update["edits"][0]["fields"]["status"] = "rejected"
        self.assertEqual(len(self.ws.apply(update)["decisions"]), 2)

    def test_concurrent_edits_serialize_with_one_revision_winner(self):
        first = self.patch_for()
        second = copy.deepcopy(first)
        second["reason"] = "concurrent independent edit"
        def apply(p):
            ws = Workspace(self.ws.path)
            try:
                ws.apply(p)
                return "accepted"
            except ReviewError as error:
                return str(error)
            finally:
                ws.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply, [first, second]))
        self.assertCountEqual(results, ["accepted", "E_REVISION_CONFLICT"])
        self.assertEqual(self.ws.state()["revision"], 1)
        self.assertEqual(json.loads((self.ws.path / "state.json").read_text(encoding="utf-8"))["revision"], 1)

    def test_template_export_never_overwrites_work_or_sqlite_sidecars(self):
        workspace = str(self.ws.path)
        target = self.ws.path / "patch.json"
        self.assertEqual(main(["review", "--workspace", workspace]), 0)
        target.write_text("unfinished human edit", encoding="utf-8")
        self.assertEqual(main(["review", "--workspace", workspace]), 2)
        self.assertEqual(target.read_text(encoding="utf-8"), "unfinished human edit")
        for name in ("STATE.JSON", "Review.sqlite3-journal", "source.DOCX", "runs/not-a-patch.json"):
            self.assertEqual(main(["review", "--workspace", workspace, "--output", str(self.ws.path / name)]), 2)

    def test_scope_and_permissions_rejected_atomically(self):
        p = self.patch_for()
        p["edits"][0]["fields"]["visibility"] = "author_visible"
        with self.assertRaisesRegex(ReviewError, "E_PATCH_FIELDS"):
            self.ws.apply(p)
        p = self.patch_for()
        p["edits"][0]["fields"]["evidence"][0]["section_id"] = "section-2"
        with self.assertRaisesRegex(ReviewError, "E_EVIDENCE_SCOPE"):
            self.ws.apply(p)
        self.assertEqual(self.ws.state()["revision"], 0)

    def test_frozen_source_and_origin(self):
        with self.assertRaisesRegex(ReviewError, "E_ORIGIN_CONFLICT"):
            self.ws.run(self.source, "original_review")
        (self.ws.path / "source.docx").write_bytes(b"changed")
        with self.assertRaisesRegex(ReviewError, "E_SOURCE_CHANGED"):
            self.ws.state()

    def test_partial_output_recovery_preserves_decision(self):
        p = self.patch_for()
        with patch("reviewproto.render.render", side_effect=OSError("PRIVATE TEXT MUST NEVER APPEAR")):
            with self.assertRaises(OSError):
                self.ws.apply(p)
        self.assertEqual(self.ws.state()["revision"], 1)
        self.ws.operation("recover", self.ws.state)
        restored = json.loads((self.ws.path / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(restored["revision"], 1)
        records = [json.loads(p.read_text(encoding="utf-8")) for p in (self.ws.path / "runs").glob("*.json")]
        self.assertIn("output_failed", {r["status"] for r in records})
        self.assertNotIn("PRIVATE TEXT", json.dumps(records))

    def test_escaped_html_no_remote_resources_and_blind_boundary(self):
        source = parse_docx(fixture("<script>alert('x')</script>😀", "PRIVATE_CANARY"))
        source["candidates"] = extract(source)
        from reviewproto.render import render
        report = render(source)
        self.assertNotIn("<script>alert", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn("connect-src 'none'", report)
        with patch("reviewproto.core.extract_section", return_value=[]) as spy:
            extract(source)
        self.assertEqual(spy.call_count, 2)
        public = spy.call_args_list[0].args[0]
        self.assertNotIn("scores", public)
        self.assertNotIn("PRIVATE_CANARY", json.dumps(public))

    def test_unknown_structure_and_nested_visibility_rejected(self):
        with self.assertRaisesRegex(ReviewError, "E_AMBIGUOUS_VISIBILITY"):
            parse_docx(fixture("Confidential notes"))
        doc = Document(io.BytesIO(fixture()))
        doc.add_table(rows=1, cols=1)
        buffer = io.BytesIO()
        doc.save(buffer)
        with self.assertRaisesRegex(ReviewError, "E_TEMPLATE_TABLES"):
            parse_docx(buffer.getvalue())

    def test_success_and_unknown_template_failure_record_actual_input_sha(self):
        completed = [json.loads(p.read_text(encoding="utf-8")) for p in (self.ws.path / "runs").glob("*.json")]
        self.assertEqual(completed[0]["input_fingerprint"], digest(self.source.read_bytes()))
        unknown = self.root / "unknown.docx"
        doc = Document()
        doc.add_paragraph("SYNTHETIC_PRIVATE_UNKNOWN_TEMPLATE")
        doc.save(unknown)
        other = Workspace(self.root / "failed-workspace")
        try:
            with self.assertRaisesRegex(ReviewError, "E_TEMPLATE_TABLES"):
                other.run(unknown, "synthetic")
            record_path = next((other.path / "runs").glob("*.json"))
            text = record_path.read_text(encoding="utf-8")
            record = json.loads(text)
            self.assertEqual(record["input_fingerprint"], digest(unknown.read_bytes()))
            self.assertEqual(record["input_id"], record["input_fingerprint"])
            self.assertEqual(record["fingerprint_state"], "complete")
            self.assertEqual(record["status"], "failed")
            self.assertNotIn("SYNTHETIC_PRIVATE_UNKNOWN_TEMPLATE", text)
            self.assertNotIn(str(unknown), text)
        finally:
            other.close()

    def test_invalid_patch_json_and_read_failure_have_safe_run_records(self):
        bad = self.root / "bad-secret-name.json"
        content = b'{"SYNTHETIC_PRIVATE_INVALID_JSON":'
        bad.write_bytes(content)
        before = self.ws.state()
        self.assertEqual(main(["apply", str(bad), "--workspace", str(self.ws.path)]), 2)
        missing = self.root / "SYNTHETIC_PRIVATE_MISSING_FILE.json"
        self.assertEqual(main(["apply", str(missing), "--workspace", str(self.ws.path)]), 2)
        records = [json.loads(p.read_text(encoding="utf-8")) for p in (self.ws.path / "runs").glob("*.json")]
        failures = {r.get("error_code"): r for r in records if r["status"] == "failed"}
        self.assertEqual(failures["E_PATCH_JSON"]["input_fingerprint"], digest(content))
        self.assertEqual(failures["E_INPUT_READ"]["fingerprint_state"], "unavailable_read_error")
        self.assertIsNone(failures["E_INPUT_READ"]["input_fingerprint"])
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(records))
        self.assertEqual(self.ws.state(), before)

    def test_cli_patch_success_records_actual_bytes_and_canonical_replay(self):
        p = self.patch_for()
        path = self.root / "edit.json"
        payload = json.dumps(p, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        path.write_bytes(payload)
        self.ws.apply(input_path=path)
        records = [json.loads(p.read_text(encoding="utf-8")) for p in (self.ws.path / "runs").glob("*.json")]
        record = next(r for r in records if r["command"] == "apply")
        self.assertEqual(record["input_fingerprint"], digest(payload))
        self.assertTrue((self.ws.path / record["replay"]["input"]).is_file())
        self.assertEqual(json.loads((self.ws.path / record["replay"]["input"]).read_text(encoding="utf-8")), p)

    def test_large_wrong_inputs_use_bounded_reads_and_preserve_fingerprint(self):
        from unittest.mock import MagicMock
        large = self.root / "too-large.bin"
        payload = b"synthetic-wrong-input" * 50
        large.write_bytes(payload)
        context = {}
        with large.open("rb") as stream:
            tracked = MagicMock()
            tracked.__enter__.return_value = tracked
            tracked.fileno.return_value = stream.fileno()
            tracked.read.side_effect = stream.read
            with patch("reviewproto.store.Path.open", return_value=tracked):
                with self.assertRaisesRegex(ReviewError, "E_INPUT_LIMIT"):
                    read_input(large, 10, context=context)
        self.assertEqual(context["input_fingerprint"], digest(payload))
        self.assertTrue(all(0 < c.args[0] <= 65_536 for c in tracked.read.call_args_list))

    def test_new_workspace_preserves_unmanaged_files_and_database(self):
        for name in ("report.html", "state.json", "source.docx", "runs", "Review.sqlite3-journal"):
            directory = self.root / ("unmanaged-" + name.replace(".", "-"))
            directory.mkdir()
            file = directory / name
            file.write_bytes(b"SYNTHETIC_USER_WORK")
            with self.assertRaisesRegex(ReviewError, "E_WORKSPACE_UNMANAGED"):
                Workspace(directory)
            self.assertEqual(file.read_bytes(), b"SYNTHETIC_USER_WORK")
            self.assertFalse((directory / "review.sqlite3").exists())
        directory = self.root / "unrelated-db"
        directory.mkdir()
        database = directory / "review.sqlite3"
        conn = sqlite3.connect(database)
        conn.execute("CREATE TABLE user_work (value TEXT)")
        conn.commit()
        conn.close()
        previous_bytes = database.read_bytes()
        with self.assertRaisesRegex(ReviewError, "E_WORKSPACE_UNMANAGED"):
            Workspace(directory)
        self.assertEqual(database.read_bytes(), previous_bytes)

    def test_relation_target_types_are_validated_atomically(self):
        for relation_type, target in (("supports", self.state["scores"][0]["label"]),
                                      ("opposes", self.state["scores"][0]["label"]),
                                      ("explains_score", self.state["candidates"][0]["candidate_id"])):
            p = self.patch_for()
            p["edits"][0]["fields"]["relations"] = [{"type": relation_type, "target": target,
                                                       "provenance": "explicit", "evidence_indices": [0]}]
            with self.assertRaisesRegex(ReviewError, "E_RELATION_TARGET"):
                self.ws.apply(p)
            self.assertEqual(self.ws.state()["revision"], 0)
        valid = self.patch_for()
        valid["edits"][0]["fields"]["relations"] = [{"type": "explains_score", "target": self.state["scores"][0]["label"],
                                                      "provenance": "inferred", "evidence_indices": [0]}]
        self.assertEqual(self.ws.apply(valid)["revision"], 1)

    def test_machine_candidates_are_validated_before_freeze_or_commit(self):
        for field, value, code in (("quote", "SYNTHETIC_FORGED_QUOTE", "E_EVIDENCE_QUOTE"),
                                   ("visibility", "author_visible", "E_VISIBILITY"),
                                   ("status", "confirmed", "E_MACHINE_STATUS")):
            ws = Workspace(self.root / ("bad-machine-" + field))
            try:
                generated = copy.deepcopy(self.state["candidates"])
                if field == "quote":
                    generated[0]["evidence"][0]["quote"] = value
                else:
                    generated[0][field] = value
                with patch("reviewproto.store.extract", return_value=generated):
                    with self.assertRaisesRegex(ReviewError, code):
                        ws.run(self.source, "synthetic")
                self.assertIsNone(ws.db.execute("SELECT payload FROM state WHERE id=1").fetchone())
                self.assertFalse((ws.path / "source.docx").exists())
            finally:
                ws.close()

    def test_native_moved_text_and_equations_fail_closed_in_scores_and_comments(self):
        for kind in ("moveTo", "moveFrom", "oMath", "oMathPara"):
            for target in ("score", "comment"):
                with self.subTest(kind=kind, target=target):
                    data = native_variant(kind, target)
                    source = self.root / (kind + target + ".docx")
                    source.write_bytes(data)
                    ws = Workspace(self.root / (kind + target + "-workspace"))
                    try:
                        with self.assertRaisesRegex(ReviewError, "E_UNSUPPORTED_FEATURE"):
                            ws.run(source, "synthetic")
                        self.assertFalse((ws.path / "state.json").exists())
                        self.assertFalse((ws.path / "report.html").exists())
                        self.assertIsNone(ws.db.execute("SELECT payload FROM state WHERE id=1").fetchone())
                        raw = next((ws.path / "runs").glob("*.json")).read_text(encoding="utf-8")
                        record = json.loads(raw)
                        self.assertEqual(record["input_fingerprint"], digest(data))
                        self.assertEqual(record["error_code"], "E_UNSUPPORTED_FEATURE")
                        self.assertNotIn("SYNTHETIC_", raw)
                    finally:
                        ws.close()

    def test_unmapped_native_content_is_rejected_instead_of_dropped(self):
        for kind in ("AlternateContent", "sym", "softHyphen", "noBreakHyphen", "separator", "annotationRef", "fldChar", "ruby", "numPr"):
            for target in ("score", "comment"):
                with self.subTest(kind=kind, target=target):
                    with self.assertRaisesRegex(ReviewError, "E_UNSUPPORTED_FEATURE"):
                        parse_docx(native_variant(kind, target))

    def test_native_formatting_tabs_breaks_bookmarks_and_hyperlink_text_survive(self):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.opc.constants import RELATIONSHIP_TYPE
        doc = Document(io.BytesIO(fixture()))
        paragraph = doc.tables[0].cell(10, 0).paragraphs[0]
        run = paragraph.add_run("原生格式😀")
        run.bold, run.italic = True, True
        run.add_tab()
        run.add_break()
        run.add_text("换行后")
        bookmark = OxmlElement("w:bookmarkStart")
        bookmark.set(qn("w:id"), "99")
        bookmark.set(qn("w:name"), "synthetic")
        paragraph._p.append(bookmark)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), doc.part.relate_to("https://invalid.example/never-fetched", RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
        linked_run, text = OxmlElement("w:r"), OxmlElement("w:t")
        text.text = "超链接原文"
        linked_run.append(text)
        hyperlink.append(linked_run)
        paragraph._p.append(hyperlink)
        bookmark_end = OxmlElement("w:bookmarkEnd")
        bookmark_end.set(qn("w:id"), "99")
        paragraph._p.append(bookmark_end)
        stream = io.BytesIO()
        doc.save(stream)
        state = parse_docx(stream.getvalue())
        self.assertTrue(state["sections"][0]["text"].endswith("原生格式😀\t\n换行后超链接原文"))

    def test_cached_unsupported_source_cannot_bypass_current_checks_or_erase_history(self):
        from reviewproto.store import atomic, encoded
        data = native_variant("oMath", "comment")
        cached = copy.deepcopy(self.state)
        source_id = digest(data)
        cached["source"]["source_id"] = cached["source"]["sha256"] = source_id
        cached["review"]["review_id"] = source_id
        for section in cached["sections"]:
            section["source_id"] = source_id
        cached["candidates"] = extract(cached)
        cached["versions"]["parser"] = "verified-two-cell-v1"
        decision = copy.deepcopy(cached["candidates"][0])
        decision.update(status="confirmed", origin="human_decision", object="SYNTHETIC_SAVED_HUMAN_VALUE")
        cached["revision"] = 1
        cached["decisions"] = [{"candidate_id": decision["candidate_id"], "value": decision, "actor": "synthetic-editor", "reason": "prior verified edit", "at": "synthetic-prior-time", "revision": 1}]
        ws = Workspace(self.root / "cached-legacy")
        try:
            atomic(ws.path / "source.docx", data)
            ws.save(cached)
            raw_state = encoded(cached)
            atomic(ws.path / "state.json", raw_state)
            atomic(ws.path / "report.html", b"synthetic historic artifact")
            patch_value = template(cached)
            patch_value.update(actor="synthetic-editor", reason="must not bypass safety")
            for action in (lambda: ws.run(ws.path / "source.docx", "synthetic"),
                           lambda: ws.operation("render", ws.state),
                           lambda: ws.operation("recover", ws.state),
                           lambda: ws.apply(patch_value)):
                with self.assertRaisesRegex(ReviewError, "E_UNSUPPORTED_FEATURE"):
                    action()
            self.assertEqual(json.loads(ws.db.execute("SELECT payload FROM state WHERE id=1").fetchone()[0]), cached)
            self.assertEqual((ws.path / "state.json").read_bytes(), raw_state)
            self.assertEqual((ws.path / "report.html").read_bytes(), b"synthetic historic artifact")
            records = [json.loads(p.read_text(encoding="utf-8")) for p in (ws.path / "runs").glob("*.json")]
            self.assertEqual(len(records), 4)
            self.assertTrue(all(r["status"] == "failed" and r.get("outputs") == {} for r in records))
            self.assertTrue(all(r.get("source_fingerprint") == source_id for r in records))
        finally:
            ws.close()

    def test_private_workspace_gitignore_covers_arbitrary_names_and_preserves_other_code(self):
        git_root = self.root / "synthetic-repository"
        git_root.mkdir()
        subprocess.run(["git", "init", "--quiet", str(git_root)], check=True, capture_output=True)
        (git_root / "keep.py").write_text("# synthetic user code\n", encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "E_WORKSPACE_NOT_DEDICATED"):
            Workspace(git_root)
        self.assertFalse((git_root / ".gitignore").exists())
        ws = Workspace(git_root / "custom-private-dir")
        try:
            ws.run(self.source, "synthetic")
            patch_file = ws.path / "arbitrary-patch-name.custom"
            patch_value = template(ws.state())
            patch_value.update(actor="synthetic-editor", reason="private patch")
            patch_file.write_text(json.dumps(patch_value, ensure_ascii=False), encoding="utf-8")
            ws.apply(input_path=patch_file)
            paths = ["custom-private-dir/" + name for name in ("source.docx", "review.sqlite3", "state.json", "report.html", "arbitrary-patch-name.custom", ".gitignore")]
            ignored = subprocess.run(["git", "-C", str(git_root), "check-ignore", "--stdin", "-z"],
                                     input=b"\0".join(p.encode() for p in paths) + b"\0", capture_output=True, check=True)
            self.assertCountEqual([p.decode() for p in ignored.stdout.split(b"\0") if p], paths)
            subprocess.run(["git", "-C", str(git_root), "add", "."], check=True, capture_output=True)
            staged = subprocess.run(["git", "-C", str(git_root), "diff", "--cached", "--name-only"],
                                    check=True, capture_output=True, text=True)
            self.assertEqual(staged.stdout.splitlines(), ["keep.py"])
        finally:
            ws.close()
        unrelated = git_root / "existing-code"
        unrelated.mkdir()
        (unrelated / "module.py").write_text("# keep visible", encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "E_WORKSPACE_NOT_DEDICATED"):
            Workspace(unrelated)
        self.assertFalse((unrelated / ".gitignore").exists())
        existing_ignore = unrelated / ".gitignore"
        existing_ignore.write_text("*.cache\n", encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "E_WORKSPACE_IGNORE_EXISTS"):
            Workspace(unrelated)
        self.assertEqual(existing_ignore.read_text(encoding="utf-8"), "*.cache\n")

    def test_managed_legacy_workspace_migrates_without_losing_human_edits(self):
        self.ws.apply(self.patch_for())
        old = self.ws.state()
        self.ws.close()
        (self.root / "work" / ".gitignore").unlink()
        self.ws = Workspace(self.root / "work")
        self.assertTrue((self.ws.path / ".gitignore").read_bytes().startswith(b"*\n"))
        self.assertEqual(self.ws.run(self.source, "synthetic"), old)
        # A legacy tool database must not justify hiding unrelated code.
        self.ws.close()
        (self.root / "work" / ".gitignore").unlink()
        (self.root / "work" / "unrelated.py").write_text("# user code", encoding="utf-8")
        with self.assertRaisesRegex(ReviewError, "E_WORKSPACE_NOT_DEDICATED"):
            Workspace(self.root / "work")
        self.assertFalse((self.root / "work" / ".gitignore").exists())
        # Restore the known workspace for tearDown without modifying user code.
        (self.root / "work" / "unrelated.py").unlink()
        self.ws = Workspace(self.root / "work")

    @unittest.skipUnless(os.name == "nt", "junction regression needs Windows")
    def test_windows_junction_output_directory_is_rejected(self):
        directory = self.root / "junction-workspace"
        initial = Workspace(directory)
        initial.close()
        target = self.root / "outside-junction-target"
        target.mkdir()
        sentinel = target / "sentinel.txt"
        sentinel.write_text("synthetic untouched content", encoding="utf-8")
        junction = directory / "runs"
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True)
        if created.returncode != 0:
            self.skipTest("local junction creation unavailable")
        try:
            with self.assertRaisesRegex(ReviewError, "E_WORKSPACE_LINK"):
                Workspace(directory)
            self.assertEqual(list(target.iterdir()), [sentinel])
        finally:
            # Remove only the junction itself, never recurse into its target.
            junction.rmdir()


if __name__ == "__main__":
    unittest.main()
