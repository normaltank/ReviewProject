"""Build an offline, wholly synthetic input in the supported Word form layout."""

import argparse
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from docx import Document


SCORE_LABELS = ("创新性与科学性", "工作量", "学术范式", "语言表达与逻辑关系")
COMMENTS = (
    "方法说明清楚，但没有交代抽样方式。",
    "若能取得逐周记录，可补一张对照表；否则请说明资料的覆盖范围。",
    "样本量尚可。建议另述样本的代表性。",
    "核对图例。🌱核对图例。",
)
PRIVATE_COMMENT = "仅供编辑核对的合成标记 PRIVATE-FIXTURE-27。"


def sample_bytes() -> bytes:
    doc = Document()
    doc.core_properties.title = "合成外审表 · 流程演练"
    doc.core_properties.author = "ReviewProject synthetic fixture"
    doc.add_paragraph("期刊审稿意见表")
    doc.add_paragraph("合成样本，仅作流程测试")
    table = doc.add_table(rows=13, cols=4)

    def merged(row, start, end, text):
        cell = table.cell(row, start).merge(table.cell(row, end))
        cell.text = text
        return cell

    merged(0, 0, 3, "期刊审稿意见表")
    table.cell(1, 0).text = "期刊名称"
    merged(1, 1, 3, "演示期刊")
    for col, value in enumerate(("稿件ID", "DEMO-001", "投稿日期", "")):
        table.cell(2, col).text = value
    table.cell(3, 0).text = "稿件标题"
    merged(3, 1, 3, "完全合成的演示稿")
    merged(4, 0, 3, "评审打分")
    for row, (label, score) in enumerate(zip(SCORE_LABELS, ("3.5", "", "4", " 4.0 ")), 5):
        merged(row, 0, 2, label + "（1-5分）")
        table.cell(row, 3).text = score
    merged(9, 0, 3, "评审意见")
    comment_cell = merged(10, 0, 3, COMMENTS[0])
    for comment in COMMENTS[1:]:
        comment_cell.add_paragraph(comment)
    merged(11, 0, 3, "其他意见（作者不可见）")
    merged(12, 0, 3, PRIVATE_COMMENT)

    # DOCX normally includes the wall clock in its ZIP headers. Freeze those
    # headers so rebuilding this fixture retains the same original-file ID.
    raw = BytesIO()
    doc.save(raw)
    result = BytesIO()
    with ZipFile(raw) as source, ZipFile(result, "w") as target:
        for name in source.namelist():
            entry = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            target.writestr(entry, source.read(name))
    return result.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=Path("work/demo-input.docx"))
    path = parser.parse_args().output
    payload = sample_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            parser.exit(2, "Output exists with different contents. Choose a new path.\n")
    print("Synthetic DOCX ready.")


if __name__ == "__main__":
    main()
