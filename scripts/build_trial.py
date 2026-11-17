"""Build a Windows x64 trial from explicit code/resource inputs, never a tree copy.

Official PyInstaller 6.22.3 docs: runtime-information.rst, usage.rst and
COPYING.txt (bootloader exception). Output remains in ignored work/.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import hashlib
import importlib.metadata as metadata
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = (
    "workbench.html", "workbench.js", "workbench.css",
    "attention_editor.js", "attention_positions.js", "attention_views.js",
    "attention_web.css", "attention_map.js", "local_model_profiles.json",
)
EXCLUDED = (
    "tkinter", "_tkinter", "reviewproto.native_ui", "reviewproto.desktop",
    "reviewproto.attention_input_ui", "reviewproto.attention_candidate_ui",
    "pytest", "unittest", "IPython", "matplotlib", "numpy", "pandas",
)
LICENSE_PACKAGES = (
    "pyinstaller", "python-docx", "lxml", "typing_extensions",
    "jsonschema", "attrs", "referencing", "rpds-py", "jsonschema-specifications",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@contextmanager
def trial_config(key_file):
    """Private input is never copied into source, command arguments or logs."""
    if key_file is None:
        yield None
        return
    try:
        key = key_file.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        raise SystemExit("Cannot read private trial credential file") from None
    if not key or not key.isascii() or any(c.isspace() for c in key):
        raise SystemExit("Invalid private trial credential format")
    with tempfile.TemporaryDirectory(prefix="ReviewProject-trial-staging-") as temporary:
        staging = Path(temporary).resolve()
        if staging.is_relative_to(ROOT):
            raise SystemExit("Private trial staging must be outside the source tree")
        config = staging / "trial-config.json"
        write_json(config, {"deepseek_api_key": key})
        yield config


def collect_licenses(target):
    target.mkdir()
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python LICENSE.txt is required")
    shutil.copy2(python_license, target / "Python-LICENSE.txt")
    versions = {}
    for name in LICENSE_PACKAGES:
        dist = metadata.distribution(name)
        versions[name] = dist.version
        found = []
        for item in dist.files or ():
            # Only distribution license files, never package tests or examples.
            if ".dist-info/" in str(item) and any(
                token in str(item).lower() for token in ("license", "copying")
            ):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    destination = target / name / Path(*item.parts[1:])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    found.append(destination.relative_to(target).as_posix())
        if not found:
            raise RuntimeError(f"Missing distribution license: {name}")
    (target / "THIRD_PARTY_NOTICES.txt").write_text(
        "ReviewProject Windows x64 trial runtime\n\n"
        "CPython " + platform.python_version() + " (PSF and bundled component notices): Python-LICENSE.txt\n"
        + "\n".join(name + " " + version + ": " + name + "/" for name, version in versions.items())
        + "\n\nPyInstaller's bootloader exception permits combined executable distribution;\n"
        "its runtime hooks use Apache-2.0. See its complete COPYING.txt.\n"
        "lxml includes its binary wheel component notices (libxml2/libxslt/zlib/iconv).\n"
        "Windows runtime DLLs supplied with CPython retain their applicable vendor terms.\n"
        "Project code has no separate open-source license grant.\n",
        encoding="utf-8",
    )
    return versions


def audit_bundle(bundle, work):
    """Accept only analyzed runtime outputs and explicit release additions."""
    toc = (work / "pyinstaller" / "ReviewProject" / "Analysis-00.toc").read_text(encoding="utf-8")
    for forbidden in ("'tkinter", "'_tkinter", "'reviewproto.desktop'", "'reviewproto.native_ui'"):
        if forbidden in toc:
            raise RuntimeError("Retired UI reached module graph: " + forbidden)
    collected = ast.literal_eval((work / "pyinstaller" / "ReviewProject" / "COLLECT-00.toc").read_text(encoding="utf-8"))
    runtime = {name.replace("\\", "/") for name, source, kind in collected[0]}
    for path in bundle.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle)
        normalized = relative.as_posix()
        names = {p.lower() for p in relative.parts}
        if names & {".git", ".tools", ".venv", "tests", "worktrees", "credentials", "afeedback", "bfeedback"}:
            raise RuntimeError("Forbidden directory in bundle: " + str(relative))
        if path.name.startswith(".env") or path.suffix.lower() in {".sqlite3", ".db", ".dpapi", ".log", ".docx"}:
            raise RuntimeError("User/development data in bundle: " + str(relative))
        if any(part.lower().startswith(("tcl", "tk8")) for part in relative.parts):
            raise RuntimeError("Tk runtime in bundle: " + str(relative))
        if relative.parts[0] not in {"ReviewProject.exe", "_internal", "licenses", "README_TRIAL.txt", "BUILD_INFO.json", "CONTENTS.sha256"}:
            raise RuntimeError("Unexpected release addition: " + str(relative))
        if relative.parts[0] == "_internal" and relative.relative_to("_internal").as_posix() not in runtime:
            raise RuntimeError("File absent from PyInstaller collection: " + normalized)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "work" / "trial-builds")
    parser.add_argument("--trial-key-file", type=Path,
                        help="Explicit private credential file for an authorized private trial ZIP")
    args = parser.parse_args(argv)
    if sys.platform != "win32" or platform.architecture()[0] != "64bit":
        raise SystemExit("Build on 64-bit Windows with 64-bit CPython")
    if metadata.version("pyinstaller") != "6.22.3":
        raise SystemExit("Install requirements-build.txt first")
    entry = ROOT / "reviewproto" / "workbench_launcher.py"
    if not entry.is_file():
        raise SystemExit("Integrated Web launcher is required; do not bundle the retired desktop")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True)
    if dirty.strip():
        raise SystemExit("Commit tracked changes before creating an attributable trial")
    work = args.output.resolve() / ("ReviewProject-win-x64-" + commit[:12])
    # Refuse overwrite; each release build is recoverable and attributable.
    work.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
               "--name", "ReviewProject", "--noupx", "--distpath", str(work / "dist"),
               "--workpath", str(work / "pyinstaller"), "--specpath", str(work), "--paths", str(ROOT)]
    for name in RESOURCES:
        source = ROOT / "reviewproto" / name
        if not source.is_file():
            raise SystemExit("Required resource missing: " + name)
        command.extend(["--add-data", str(source) + ":reviewproto"])
    for module in EXCLUDED:
        command.extend(["--exclude-module", module])
    command.append(str(entry))
    with trial_config(args.trial_key_file) as config:
        if config is not None:
            command[-1:-1] = ["--add-data", str(config) + ":reviewproto"]
        with (work / "build.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
    bundle = work / "dist" / "ReviewProject"
    shutil.copy2(ROOT / "packaging" / "README_TRIAL.txt", bundle / "README_TRIAL.txt")
    versions = collect_licenses(bundle / "licenses")
    write_json(bundle / "BUILD_INFO.json", {
        "commit": commit, "python": platform.python_version(), "architecture": "Windows-x64",
        "packages": versions, "resource_allowlist": list(RESOURCES), "excluded_modules": list(EXCLUDED),
        "embedded_trial_credential": args.trial_key_file is not None,
        "examples": "Explicit synthetic example is created by the Web workbench; no user data is copied.",
    })
    audit_bundle(bundle, work)
    manifest = "".join(sha(p) + "  " + p.relative_to(bundle).as_posix() + "\n"
                       for p in sorted(bundle.rglob("*")) if p.is_file())
    (bundle / "CONTENTS.sha256").write_text(manifest, encoding="utf-8")
    archive = work / (work.name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                output.write(path, "ReviewProject/" + path.relative_to(bundle).as_posix())
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(sha(archive) + "  " + archive.name + "\n", encoding="ascii")
    print(json.dumps({"commit": commit, "zip": str(archive), "checksum": str(checksum),
                      "files": sum(p.is_file() for p in bundle.rglob("*"))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
