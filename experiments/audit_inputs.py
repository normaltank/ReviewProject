"""Read B's local inventory and print only aggregate, reproducible counts."""

import argparse
from collections import Counter
from hashlib import file_digest
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
KEYWORDS = ("创新性", "工作量", "学术范式", "语言表达")


def screen_document(source):
    with ZipFile(source) as archive:
        part = archive.getinfo("word/document.xml")
        if part.file_size > 100_000_000:
            return "xml_size_limit", ()
        with archive.open(part) as xml:
            root = ET.parse(xml).getroot()
    matches = []
    for table in root.iter(W + "tbl"):
        labels = {term: [] for term in KEYWORDS}
        for row in table.findall(W + "tr"):
            cells = [
                "".join((text.text or "") for text in cell.iter(W + "t"))
                for cell in row.findall(W + "tc")
            ]
            for col, label in enumerate(cells):
                if len(label) < 100:
                    for term in KEYWORDS:
                        if term in label:
                            value = cells[col + 1].strip() if col + 1 < len(cells) else None
                            labels[term].append(value)
        if all(len(values) == 1 for values in labels.values()):
            matches.append(tuple(labels[k][0] for k in KEYWORDS))
    if len(matches) == 1:
        return "four_label_table", matches[0]
    return "unclassified", ()


def inventory(root):
    extensions = Counter()
    unique = {}
    occurrences = Counter()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        extension = path.suffix.lower() or "(no suffix)"
        extensions[extension] += 1
        if extension != ".docx":
            continue
        try:
            with path.open("rb") as source:
                key = file_digest(source, "sha256").digest()
                if key not in unique:
                    source.seek(0)
                    try:
                        unique[key] = screen_document(source)
                    except (ET.ParseError, BadZipFile, KeyError, RuntimeError):
                        unique[key] = "xml_or_package_error", ()
        except OSError:
            occurrences["unreadable_file"] += 1
            continue
        occurrences[unique[key][0]] += 1
    candidates = [scores for status, scores in unique.values() if status == "four_label_table"]
    return {
        "extensions": dict(sorted(extensions.items())),
        "docx_files": sum(occurrences.values()),
        "distinct_docx_sha256": len(unique),
        "file_occurrences": dict(occurrences),
        "distinct_by_sha256": dict(Counter(status for status, _ in unique.values())),
        "empty_adjacent_cells_by_field_distinct": {
            k: sum(scores[col] == "" for scores in candidates) for col, k in enumerate(KEYWORDS)
        },
        "distinct_candidates_with_any_empty": sum("" in scores for scores in candidates),
        "distinct_candidates_with_all_empty": sum(all(v == "" for v in scores) for scores in candidates),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("Bfeedback"))
    directory = parser.parse_args().directory
    if not directory.is_dir():
        parser.exit(2, "Input directory is missing.\n")
    print(json.dumps(inventory(directory), indent=2, ensure_ascii=False))
