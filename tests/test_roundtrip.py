"""Acceptance through the CLI and (optionally) a local Chromium browser."""

import copy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from docx import Document

from experiments.make_demo import COMMENTS, PRIVATE_COMMENT, sample_bytes


ROOT = Path(__file__).resolve().parents[1]


class RoundTripAcceptance(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "form.docx"
        self.source.write_bytes(sample_bytes())
        self.workspace = self.root / "review"
        self.cli("run", self.source, "--origin", "synthetic")

    def cli(self, *args, success=True):
        result = subprocess.run(
            [sys.executable, "-m", "reviewproto", *map(str, args), "--workspace", str(self.workspace)],
            cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(result.returncode, 0 if success else 2, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def state(self):
        return json.loads((self.workspace / "state.json").read_text(encoding="utf-8"))

    def select_patch(self, quote):
        state = self.state()
        cid = next(c["candidate_id"] for c in state["candidates"] if c["evidence"][0]["quote"] == quote)
        path = self.workspace / "one.json"
        self.cli("review", "--candidate", cid, "--output", path)
        patch = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(patch["edits"]), 1)
        return path, patch

    def test_import_binds_physical_word_cells_and_internal_audience(self):
        state = self.state()
        original = self.source.read_bytes()
        self.assertEqual(original, (self.workspace / "source.docx").read_bytes())
        self.assertEqual(hashlib.sha256(original).hexdigest(), state["source"]["source_id"])
        self.assertEqual([s["raw_value"] for s in state["scores"]], ["3.5", "", "4", " 4.0 "])
        self.assertEqual(state["source"]["reported_manuscript_id"]["raw_value"], "DEMO-001")
        self.assertFalse(state["source"]["submitted_version_confirmed"])
        self.assertEqual([s["visibility"] for s in state["sections"]], ["visibility_unknown", "internal_only"])
        table = Document(BytesIO(original)).tables[0]
        for section in state["sections"]:
            # First grid cell and first physical cell coincide for these comment rows.
            paragraphs = table.cell(section["locator"]["row"], 0).paragraphs
            frozen = [section["text"][p["start"]:p["end"]] for p in section["paragraphs"]]
            self.assertEqual(frozen, [p.text for p in paragraphs])
        self.assertEqual([s["reason_relation"] for s in state["scores"]], ["unknown"] * 4)
        self.cli("export-author", success=False)
        for record in (self.workspace / "runs").glob("*.json"):
            content = record.read_text(encoding="utf-8")
            self.assertNotIn(PRIVATE_COMMENT, content)
            self.assertNotIn(str(self.source), content)

    def test_conditional_edit_history_survives_repeat_apply_run_and_recovery(self):
        before = self.state()
        path, patch = self.select_patch(COMMENTS[1])
        fields = patch["edits"][0]["fields"]
        ref = fields["evidence"][0]
        segments = COMMENTS[1].split("；")
        first = dict(ref, quote=segments[0], end=ref["start"] + len(segments[0]))
        second = dict(ref, quote=segments[1], start=first["end"] + 1)
        branches = [{"condition": "若能取得逐周记录", "action": "可补一张对照表", "evidence_indices": [0]},
                    {"condition": "否则", "action": "请说明资料的覆盖范围", "evidence_indices": [1]}]
        fields.update(status="confirmed", interpretation="explicit", evidence=[first, second],
                      conditions=[{"text": "若能取得逐周记录", "meaning": "known", "evidence_indices": [0],
                                   "provenance": "explicit"}],
                      alternatives=[{"relation": "conditional_branches", "branches": branches, "provenance": "explicit"}])
        patch.update(actor="synthetic-test-fixture", reason="合成往返测试：分别绑定两条原文路径")
        path.write_text(json.dumps(patch, ensure_ascii=False), encoding="utf-8")
        self.cli("apply", path)
        saved = self.state()
        for cmd in (("apply", path), ("run", self.source, "--origin", "synthetic")):
            self.cli(*cmd)
        (self.workspace / "state.json").write_text("incomplete projection", encoding="utf-8")
        self.cli("recover")
        self.assertEqual(saved, self.state())
        self.assertEqual(saved["scores"], before["scores"])
        self.assertEqual(saved["candidates"], before["candidates"])
        self.assertEqual(len(saved["decisions"]), 1)
        self.assertEqual(saved["decisions"][0]["value"]["alternatives"][0]["branches"], branches)
        self.assertEqual(saved["decisions"][0]["value"]["requirement_strength"], "unknown")
        self.assertEqual(saved["decisions"][0]["actor"], "synthetic-test-fixture")
        self.assertTrue(saved["decisions"][0]["at"])

    def test_forged_cross_section_or_cross_version_edit_rolls_back(self):
        _, patch = self.select_patch(COMMENTS[0])
        patch.update(actor="synthetic-test-fixture", reason="scope test")
        patch["edits"][0]["fields"]["status"] = "confirmed"
        before = self.state()
        other = next(c for c in before["candidates"] if c["visibility"] == "internal_only")
        mixed = copy.deepcopy(patch)
        mixed["edits"][0]["fields"]["evidence"] = other["evidence"]
        different = dict(patch, source_id="a" * 64)
        for bad in (mixed, different):
            path = self.workspace / "bad.json"
            path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
            message = self.cli("apply", path, success=False)
            self.assertNotIn(PRIVATE_COMMENT, message)
            self.assertEqual(self.state(), before)
        changed = Document(self.source)
        changed.tables[0].cell(5, 3).text = "4.5"
        revised = self.root / "other-version.docx"
        changed.save(revised)
        self.cli("run", revised, "--origin", "synthetic", success=False)
        self.assertEqual(self.state(), before)

    @unittest.skipUnless(os.getenv("REVIEW_BROWSER_BINARY"), "browser acceptance needs a local Chromium binary")
    def test_editor_page_downloads_one_patch_and_restores_saved_decision(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ["REVIEW_BROWSER_BINARY"], headless=True)
            context = browser.new_context(offline=True, accept_downloads=True)
            page = context.new_page()
            requests, errors = [], []
            page.on("request", lambda request: requests.append(request.url))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto((self.workspace / "report.html").as_uri())
            page.locator("#actor").fill("synthetic-browser-fixture")
            page.locator("#reason").fill("合成浏览器往返")
            page.locator("#status").select_option("confirmed")
            page.locator("#object").fill("合成研究方法")
            with page.expect_download() as download:
                page.locator("#download").click()
            saved_patch = self.workspace / "browser-edit.json"
            download.value.save_as(saved_patch)
            self.cli("apply", saved_patch)
            page.reload()
            self.assertIn("合成研究方法", page.locator("body").inner_text())
            self.assertEqual(self.state()["decisions"][0]["actor"], "synthetic-browser-fixture")
            self.assertFalse(errors, errors)
            self.assertFalse([u for u in requests if u.startswith(("http:", "https:"))])
            browser.close()


if __name__ == "__main__":
    unittest.main()
