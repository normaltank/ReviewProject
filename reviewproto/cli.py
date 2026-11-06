"""No raw exceptions, source paths or text in terminal diagnostics."""
import argparse
from pathlib import Path
import sys

from .core import ReviewError, require
from .store import Workspace, encoded


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ReviewError("E_ARGUMENTS")


def main(argv=None):
    workspace = None
    try:
        parser = SafeParser(prog="python -m reviewproto", description="Offline trusted-editor evidence review; no author export.")
        sub = parser.add_subparsers(dest="command", required=True)
        for command in ("run", "review", "export-template", "apply", "render", "recover"):
            item = sub.add_parser(command)
            item.add_argument("--workspace", default="work/review")
            if command in ("run", "apply"):
                item.add_argument("input")
            if command == "run":
                item.add_argument("--origin", choices=("synthetic", "original_review", "unknown"), default="unknown")
            if command in ("review", "export-template"):
                item.add_argument("--output", default=None)
                item.add_argument("--candidate", default=None)
        args = parser.parse_args(argv)
        workspace = Workspace(args.workspace)
        if args.command == "run":
            workspace.run(args.input, args.origin)
        elif args.command == "apply":
            workspace.apply(input_path=args.input)
        elif args.command in ("review", "export-template"):
            target = Path(args.output).resolve() if args.output else workspace.path / "patch.json"
            require(target.is_relative_to(workspace.path) and target != workspace.path, "E_OUTPUT_SCOPE")
            name = target.name.casefold()
            parts = [p.casefold() for p in target.relative_to(workspace.path).parts]
            require(name not in {"source.docx", "state.json", "report.html", ".gitignore"} and not name.startswith("review.sqlite3") and not ({"runs", "patches", ".git"} & set(parts)), "E_OUTPUT_RESERVED")
            require(not target.is_symlink(), "E_WORKSPACE_LINK")
            require(not target.exists(), "E_OUTPUT_EXISTS")
            patch = workspace.review_template()
            if args.candidate is not None:
                patch["edits"] = [e for e in patch["edits"] if e["candidate_id"] == args.candidate]
                require(len(patch["edits"]) == 1, "E_PATCH_CANDIDATE")
            # Exclusive creation prevents concurrent template exports overwriting work.
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(encoded(patch))
        else:
            workspace.operation(args.command, workspace.state)
        print("OK " + args.command)
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, ReviewError) else "E_INTERNAL"
        print(code, file=sys.stderr)
        return 2
    finally:
        if workspace is not None:
            workspace.close()
