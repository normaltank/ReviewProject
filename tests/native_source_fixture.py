"""Synthetic native Word originals for parser and historical-source checks."""
import io
from docx import Document
from reviewproto.core import SCORE_NAMES


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
