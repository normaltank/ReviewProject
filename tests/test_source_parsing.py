"""Supported original parsing, independent of retired review workflows."""
import io
import unittest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from reviewproto.core import ReviewError, parse_docx
from native_source_fixture import fixture, native_variant


class NativeSourceParsing(unittest.TestCase):
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

    def test_unknown_structure_and_nested_visibility_rejected(self):
        with self.assertRaisesRegex(ReviewError, "E_AMBIGUOUS_VISIBILITY"):
            parse_docx(fixture("Confidential notes"))
        doc = Document(io.BytesIO(fixture()))
        doc.add_table(rows=1, cols=1)
        buffer = io.BytesIO()
        doc.save(buffer)
        with self.assertRaisesRegex(ReviewError, "E_TEMPLATE_TABLES"):
            parse_docx(buffer.getvalue())

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

    def test_style_inheritance_hidden_numbering_cycles_and_vertical_merge_fail_closed(self):
        for kind in ('hidden', 'character_hidden', 'numbering', 'builtin_numbering', 'cycle', 'missing', 'default_hidden', 'table_hidden', 'vmerge'):
            with self.subTest(kind=kind):
                doc = Document(io.BytesIO(fixture()))
                if kind == 'vmerge':
                    doc.tables[0].cell(5, 3).merge(doc.tables[0].cell(6, 3))
                elif kind == 'default_hidden':
                    defaults = doc.styles.element.find(qn('w:docDefaults'))
                    defaults.append(OxmlElement('w:vanish'))
                elif kind == 'table_hidden':
                    style = doc.styles.add_style('SyntheticTable', WD_STYLE_TYPE.TABLE)
                    style.element.append(OxmlElement('w:webHidden'))
                    doc.tables[0].style = style
                elif kind == 'character_hidden':
                    parent = doc.styles.add_style('SyntheticCharParent', WD_STYLE_TYPE.CHARACTER)
                    child = doc.styles.add_style('SyntheticCharChild', WD_STYLE_TYPE.CHARACTER)
                    child.base_style = parent
                    parent.font.hidden = True
                    doc.tables[0].cell(5, 3).paragraphs[0].runs[0].style = child
                elif kind == 'builtin_numbering':
                    doc.tables[0].cell(5, 3).paragraphs[0].style = 'List Number'
                else:
                    parent = doc.styles.add_style('SyntheticParent', WD_STYLE_TYPE.PARAGRAPH)
                    child = doc.styles.add_style('SyntheticChild', WD_STYLE_TYPE.PARAGRAPH)
                    child.base_style = parent
                    doc.tables[0].cell(5, 3).paragraphs[0].style = child
                    if kind == 'hidden':
                        parent.font.hidden = True
                    elif kind == 'numbering':
                        parent.element.get_or_add_pPr().append(OxmlElement('w:numPr'))
                    elif kind == 'cycle':
                        parent.base_style = child
                    else:
                        parent.element.get_or_add_basedOn().set(qn('w:val'), 'SyntheticMissingAncestor')
                output = io.BytesIO()
                doc.save(output)
                with self.assertRaisesRegex(ReviewError, 'E_UNSUPPORTED_FEATURE|E_STYLE_CHAIN'):
                    parse_docx(output.getvalue())
        # Unused styles do not make an ordinary template unusable.
        doc = Document(io.BytesIO(fixture()))
        doc.styles.add_style('UnusedHidden', WD_STYLE_TYPE.CHARACTER).font.hidden = True
        output = io.BytesIO()
        doc.save(output)
        self.assertEqual(parse_docx(output.getvalue())['scores'], parse_docx(fixture())['scores'])

    def test_native_moved_text_and_equations_fail_closed_in_scores_and_comments(self):
        for kind in ('moveTo', 'moveFrom', 'oMath', 'oMathPara'):
            for target in ('score', 'comment'):
                with self.subTest(kind=kind, target=target):
                    with self.assertRaisesRegex(ReviewError, 'E_UNSUPPORTED_FEATURE'):
                        parse_docx(native_variant(kind, target))

    def test_raw_scores_identity_and_unicode_paragraph_coordinates_are_preserved(self):
        state = parse_docx(fixture('重复😀。\n重复😀。'))
        self.assertEqual([s['raw_value'] for s in state['scores']], ['3.5', '4.5', '', '4'])
        self.assertEqual(state['scores'][2]['missing_state'], 'unfilled')
        self.assertIsNone(state['scores'][2]['value'])
        self.assertEqual(state['source']['reported_manuscript_id']['raw_value'], 'SYNTHETIC-ID')
        self.assertFalse(state['source']['submitted_version_confirmed'])
        section = state['sections'][0]
        self.assertEqual(section['text'], '重复😀。\n重复😀。')
        self.assertEqual(section['paragraphs'], [{'paragraph': 0, 'start': 0, 'end': 9}])
        self.assertEqual(section['offset_unit'], 'unicode_codepoint')
