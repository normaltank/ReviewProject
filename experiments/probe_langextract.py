"""Offline grounding experiment. The provider returns our synthetic fixture answers."""

import json
from importlib.metadata import version
from pathlib import Path
import re
import socket
from unittest.mock import patch


CASES = (
    ("repeat_two", "建议补图。\n建议补图。", ["建议补图。", "建议补图。"]),
    ("repeat_one", "建议补图。\n建议补图。", ["建议补图。"]),
    ("paragraphs", "背景说明。\n\n方法描述清楚。\n结论范围偏宽。", ["方法描述清楚。", "结论范围偏宽。"]),
    ("conditional", "若能取得逐周记录，可附表；否则说明资料边界。", ["若能取得逐周记录，可附表；否则说明资料边界。"]),
    ("negation", "不要求增加实验。表述尚清楚，但推论并非已被证实。", ["不要求增加实验。", "表述尚清楚，但推论并非已被证实。"]),
    ("emoji", "🧪🙂方法描述清楚。\n结论应收窄。", ["方法描述清楚。", "结论应收窄。"]),
    ("invented", "建议解释变量定义。", ["所有论文必须增加随机实验。"]),
    ("chinese_substring", "建议补充样本来源说明。", ["样本来源"]),
    ("newline", "建议\n补充图示。", ["建议 补充图示。"]),
    ("non_contiguous", "若能够公开数据。\n本段为合成干扰。\n否则披露限制。", ["若能够公开数据。", "否则披露限制。"]),
)


def alignment_rows(doc):
    result = []
    for extraction in doc.extractions or []:
        span = extraction.char_interval
        bounds = [span.start_pos, span.end_pos] if span else None
        quote = extraction.extraction_text
        result.append({
            "quote": quote,
            "span": bounds,
            "tool_alignment": extraction.alignment_status.value if extraction.alignment_status else None,
            "literal_match": bool(span and doc.text[span.start_pos:span.end_pos] == quote),
            "all_literal_starts": [m.start() for m in re.finditer(re.escape(quote), doc.text)],
        })
    return result


def run_fixture():
    import langextract as lx
    from langextract.core import base_model, tokenizer, types

    class FixtureModel(base_model.BaseLanguageModel):
        def __init__(self, answer):
            super().__init__()
            self.answer = answer

        def infer(self, batch_prompts, **kwargs):
            for _ in batch_prompts:
                yield [types.ScoredOutput(score=1.0, output=self.answer)]

    examples = [lx.data.ExampleData(text="建议改写标题。", extractions=[
        lx.data.Extraction(extraction_class="opinion", extraction_text="建议改写标题。")
    ])]

    def extract(text, payload, *, unicode_tokens=False, strict=True):
        return lx.extract(
            text_or_documents=text, prompt_description="返回原文片段", examples=examples,
            model=FixtureModel(payload), tokenizer=tokenizer.UnicodeTokenizer() if unicode_tokens else None,
            fence_output=False, use_schema_constraints=False, show_progress=False,
            max_workers=1, batch_length=1, extraction_passes=1,
            resolver_params={"enable_fuzzy_alignment": False, "accept_match_lesser": False,
                             "suppress_parse_errors": not strict},
        )

    results = []
    for name, text, quotes in CASES:
        payload = json.dumps({"extractions": [{"opinion": q} for q in quotes]}, ensure_ascii=False)
        results.append({
            "id": name, "synthetic_text": text, "fixture_quotes": quotes,
            "regex_tokenizer": alignment_rows(extract(text, payload)),
            "unicode_tokenizer": alignment_rows(extract(text, payload, unicode_tokens=True)),
            "paragraph_baseline": [[m.start(), m.end()] for m in re.finditer(r"[^\n]+", text)],
            "sentence_baseline": [[m.start(), m.end()] for m in re.finditer(r"[^。！？\n]+[。！？]?", text)],
        })
    bad_json = {}
    for strict in (False, True):
        try:
            doc = extract("这是合成文本。", "{bad json", strict=strict)
            outcome = {"candidates": len(doc.extractions or [])}
        except Exception as error:
            outcome = {"error": type(error).__name__}
        bad_json["strict" if strict else "default_parse_errors"] = outcome
    return {"langextract": version("langextract"), "scope": "synthetic_fixture_grounding_only",
            "model_requests": 0, "cases": results, "malformed_output": bad_json}


if __name__ == "__main__":
    attempts = []

    def offline(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("Network disabled for this experiment")

    with patch.object(socket.socket, "connect", offline), patch.object(socket, "create_connection", offline):
        report = run_fixture()
    report["blocked_connection_attempts"] = len(attempts)
    target = Path("work/langextract-probe/results.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(report['cases'])} synthetic cases; {len(attempts)} socket attempts. Output: {target}")
    if attempts:
        raise SystemExit(1)
