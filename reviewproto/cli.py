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
        sub.add_parser("desktop")
        item = sub.add_parser('batch-discover')
        item.add_argument('--workspace', default='work/batch-review')
        item.add_argument('--method', choices=('baseline', 'local'), required=True)
        item.add_argument('--run-id', required=True)
        item.add_argument('--rule', action='append')
        item.add_argument('--candidate', action='append')
        item.add_argument('--endpoint', default='http://127.0.0.1:8766/v1')
        item.add_argument('--model', default='reviewproject-qwen3-4b-q4km')
        item.add_argument('--max-output-tokens', type=int, default=4096)
        item.add_argument('--context-chars', type=int, default=10000)
        for command in ("batch-build", "batch-apply", "batch-recover", "batch-template", "batch-append-analysis"):
            item = sub.add_parser(command)
            if command in ("batch-build", "batch-apply", "batch-append-analysis"):
                item.add_argument("input")
            if command == "batch-template":
                item.add_argument("--output", default="decision-template.json")
            item.add_argument("--workspace", default="work/batch-review")
        for command in ("run", "review", "export-template", "apply", "render", "recover", "ingest-candidates", "ingest-clauses", "ingest-framework", "framework-template", "apply-framework-review"):
            item = sub.add_parser(command)
            item.add_argument("--workspace", default="work/review")
            if command in ("run", "apply", "ingest-candidates", "ingest-clauses", "ingest-framework", "apply-framework-review"):
                item.add_argument("input")
            if command == "run":
                item.add_argument("--origin", choices=("synthetic", "original_review", "unknown"), default="unknown")
                item.add_argument("--format", choices=("docx", "json", "csv"), default="docx")
            if command in ("review", "export-template", "framework-template"):
                item.add_argument("--output", default=None)
                item.add_argument("--candidate", default=None)
            if command == "framework-template":
                item.add_argument("--framework", default=None)
                item.add_argument("--rule", default=None)
        args = parser.parse_args(argv)
        if args.command == "desktop":
            from .desktop import main as desktop_main
            return desktop_main()
        if args.command.startswith("batch-"):
            from .batch import BatchWorkspace, read_json
            workspace = BatchWorkspace(args.workspace)
            if args.command == 'batch-discover':
                from .batch_discovery import discover
                summary = discover(workspace, method=args.method, run_id=args.run_id, rule_ids=args.rule,
                                   candidate_ids=args.candidate,
                                   endpoint=args.endpoint, model=args.model, max_output_tokens=args.max_output_tokens,
                                   context_chars=args.context_chars)
                print('DISCOVERY status=' + summary['status'] + ' issues=' + str(len(summary['issue_ids'])))
                return 2 if summary['status'] in {'partial', 'failed'} else 0
            elif args.command == "batch-build":
                workspace.build(read_json(args.input), Path(args.input).absolute().parent)
            elif args.command == "batch-apply":
                workspace.apply(input_path=args.input)
            elif args.command == "batch-recover":
                workspace.recover()
            elif args.command == "batch-append-analysis":
                workspace.append_analysis(input_path=args.input)
            else:
                from .batch import checked_local
                target = checked_local(workspace.path / args.output)
                require(target.parent == workspace.path and target.suffix == '.json' and target.name not in {'state.json'}, "E_OUTPUT_SCOPE")
                require(not target.exists(), "E_OUTPUT_EXISTS")
                with target.open('xb') as stream:
                    stream.write(encoded(workspace.review_template()))
            print("OK " + args.command)
            return 0
        workspace = Workspace(args.workspace)
        if args.command == "run":
            workspace.run(args.input, args.origin, args.format)
        elif args.command == "apply":
            workspace.apply(input_path=args.input)
        elif args.command == "ingest-candidates":
            workspace.import_extractions(input_path=args.input)
            summary = workspace.last_import_summary
            # Import success is distinct from extraction success. Do not print
            # producer error text, quotes, source paths or identities.
            print("EXTRACTION status=" + summary["status"] + " accepted=" + str(summary["accepted"]) + " rejected=" + str(summary["rejected"]))
        elif args.command == "ingest-clauses":
            workspace.import_clauses(input_path=args.input)
        elif args.command == "ingest-framework":
            workspace.import_framework(args.input)
        elif args.command == "apply-framework-review":
            workspace.apply_framework_review(input_path=args.input)
        elif args.command == "recover":
            workspace.recover()
        elif args.command in ("review", "export-template", "framework-template"):
            target = Path(args.output).absolute() if args.output else workspace.path / ("framework-review.json" if args.command == "framework-template" else "patch.json")
            from .store import linklike
            require(all(not linklike(p) for p in [target, *target.parents]), "E_WORKSPACE_LINK")
            target = target.resolve()
            require(target.is_relative_to(workspace.path) and target != workspace.path, "E_OUTPUT_SCOPE")
            name = target.name.casefold()
            parts = [p.casefold() for p in target.relative_to(workspace.path).parts]
            require(name not in {"source.docx", "source.csv", "source.json", "state.json", "report.html", ".gitignore"} and not name.startswith("review.sqlite3") and not ({"runs", "patches", "imports", "frameworks", ".git"} & set(parts)), "E_OUTPUT_RESERVED")
            require(not target.is_symlink(), "E_WORKSPACE_LINK")
            require(not target.exists(), "E_OUTPUT_EXISTS")
            patch = workspace.framework_template(args.framework, args.candidate, args.rule) if args.command == "framework-template" else workspace.review_template()
            if args.candidate is not None and args.command != "framework-template":
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
