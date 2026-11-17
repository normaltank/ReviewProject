"""No raw exceptions, source paths or text in terminal diagnostics."""
import argparse
import sys

from .core import ReviewError, require
from .local_io import read_json


API_HINTS = {
    'E_ATTENTION_JSON_FORMAT': 'E_ATTENTION_JSON_FORMAT: invalid JSON draft retained; inspect format repair and unprocessed source scopes.',
    'E_ATTENTION_SCHEMA_FORMAT': 'E_ATTENTION_SCHEMA_FORMAT: schema-invalid draft retained; inspect format repair and unprocessed source scopes.',
    'E_ATTENTION_API_MODEL': 'Use --provider deepseek --model deepseek-flash (4.1 Flash / 1017). Pro is disabled.',
    'E_DEEPSEEK_CREDENTIAL_MISSING': 'Set DEEPSEEK_API_KEY or explicitly save an API key in the desktop model settings.',
    'E_DEEPSEEK_CREDENTIAL_STORE': 'Re-save the API key as the current Windows user or set DEEPSEEK_API_KEY.'}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ReviewError("E_ARGUMENTS")


def main(argv=None):
    workspace = None
    try:
        parser = SafeParser(prog="python -m reviewproto", description="Local trusted-editor attention analysis; no author export.")
        sub = parser.add_subparsers(dest="command", required=True)
        sub.add_parser("desktop")
        sub.add_parser("workbench")
        for command in ('attention-build', 'attention-apply', 'attention-recover', 'attention-migrate', 'attention-import-a'):
            item = sub.add_parser(command)
            item.add_argument('--workspace', required=True)
            if command != 'attention-recover':
                item.add_argument('input')
            if command in {'attention-migrate', 'attention-import-a'}:
                item.add_argument('--actor', required=True)
                item.add_argument('--reason', required=True)
        for command in ('attention-generate','attention-preview','attention-accept'):
            item = sub.add_parser(command)
            item.add_argument('--workspace', required=True)
            item.add_argument('--run-id', required=True)
            if command == 'attention-generate':
                source = item.add_mutually_exclusive_group(required=True)
                source.add_argument('--replay')
                source.add_argument('--local', action='store_true')
                source.add_argument('--provider', choices=('local','deepseek'))
                item.add_argument('--record', action='append')
                item.add_argument('--endpoint')
                item.add_argument('--model')
                item.add_argument('--max-output-tokens', type=int)
                item.add_argument('--context-chars', type=int, default=24000)
            if command == 'attention-accept':
                item.add_argument('--actor', required=True)
                item.add_argument('--reason', required=True)
        args = parser.parse_args(argv)
        if args.command.startswith('attention-'):
            from .attention import AttentionWorkspace
            workspace = AttentionWorkspace(args.workspace)
            if args.command in {'attention-generate','attention-preview','attention-accept'}:
                from .attention_candidates import generate, preview, accept, ReplayProvider, LocalProvider, request_audit
                if args.command == 'attention-generate':
                    if args.replay:
                        replay = read_json(args.replay)
                        responses = [c['response'] for c in replay['calls'] if 'response' in c] if isinstance(replay,dict) and 'calls' in replay else replay
                        require(isinstance(responses,list),'E_ATTENTION_RESPONSE')
                        provider = ReplayProvider(responses)
                    elif args.provider=='deepseek':
                        from .attention_api_provider import DeepSeekProvider, API_ENDPOINT, API_MODELS, API_DEFAULT_TOKENS
                        provider = DeepSeekProvider(args.endpoint or API_ENDPOINT,args.model or API_MODELS[0],args.max_output_tokens if args.max_output_tokens is not None else API_DEFAULT_TOKENS)
                    else:
                        from .local_model_profiles import DEFAULT_MODEL
                        provider = LocalProvider(args.endpoint or 'http://127.0.0.1:8766/v1',args.model or DEFAULT_MODEL,args.max_output_tokens if args.max_output_tokens is not None else 4096)
                    run = generate(workspace,args.run_id,provider,args.record,args.context_chars)
                elif args.command == 'attention-preview':
                    run = preview(workspace,args.run_id)
                else:
                    result = accept(workspace,args.run_id,actor=args.actor,reason=args.reason)
                    print('OK attention-accept revision=' + str(result['revision']) + ' material=' + result['material_status'])
                    return 0
                audit=request_audit(run)
                if any(c.get('purpose')=='format_repair' for c in run.get('calls',[])):
                    repairs=audit['format_repair_count']
                    print('FORMAT_REPAIR requests='+(str(repairs) if repairs is not None else 'unknown')+' original_failures_preserved=yes')
                for error in run.get('errors',[]):
                    if error['code'] in API_HINTS: print(API_HINTS[error['code']],file=sys.stderr)
                if audit['unfinished']:
                    pending=audit['pending_response']
                    print('ATTEMPT_AUDIT pending_response='+(str(pending) if pending is not None else 'unknown')+' result_and_usage=unknown server_receipt_not_confirmed=yes automatic_retry=no')
                print('CANDIDATES status=' + run['status'] + ' mode=' + run['mode'] + ' opinions=' + str(len(run['patch']['edits'])) + ' requests=' + (str(audit['count']) if audit['count'] is not None else 'unknown'))
                return 2 if run['status'] in {'partial','failed','running'} else 0
            elif args.command == 'attention-build':
                result = workspace.build(input_path=args.input)
            elif args.command == 'attention-apply':
                result = workspace.apply(input_path=args.input)
            elif args.command == 'attention-import-a':
                result = workspace.import_a(args.input, actor=args.actor, reason=args.reason)
            elif args.command == 'attention-migrate':
                result = workspace.migrate_working_draft(args.input, actor=args.actor, reason=args.reason)
            else:
                result = workspace.recover()
            print('OK ' + args.command + ' revision=' + str(result['revision']) + ' material=' + result['material_status'])
            return 0
        if args.command in {"desktop", "workbench"}:
            from .desktop import main as desktop_main
            return desktop_main()
    except Exception as error:
        code = str(error) if isinstance(error, ReviewError) else "E_INTERNAL"
        print(code, file=sys.stderr)
        if code in API_HINTS: print(API_HINTS[code],file=sys.stderr)
        return 2
    finally:
        if workspace is not None:
            workspace.close()
