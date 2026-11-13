"""Exercise the installed DSH profile with synthetic data and a local mock only.

Default invocation is a dry run. --mock uses no real key or model, starts no Web
service, accepts no caller prompt/endpoint, and saves each run in a fresh folder.
This is a transport probe, not an extraction adapter or an OS sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import uuid


DSH_ROOT = Path(r"D:\Agent Workspace\DeepSeekHarness\deepseek-harness")
NODE = Path(r"D:\Agent Workspace\DeepSeekHarness\runtime\node-v24.22.2-win-x64\node.exe")
DSH_SHA = "fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159"
OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "work/trial-20261108/dsh-probe"
PROMPT = 'Synthetic transport test. Return exactly this JSON: {"synthetic":true,"opinions":[]}'
ANSWER = '{"synthetic":true,"opinions":[]}'
DISABLED = (
    "session-log-deepseek", "plugin-package-inventory-deepseek",
    "persistent-bash", "persistent-pwsh", "terminal-bash", "terminal-pwsh",
    "tool-fs", "tool-working-directory", "mcp-resources", "compaction-basic",
    "image-offload", "llm-retry",
)


def overlay_text() -> str:
    """Return a fixed patch; caller-supplied plugins and JS are not accepted."""
    return "".join(f"- id: {name}\n  disabled: true\n" for name in DISABLED) + (
        "- id: sandbox-policy\n  config:\n    mode: read-only\n"
        "    workspaceRoot: !!js process.cwd()\n"
        "- id: system-prompt\n  config:\n"
        "    includeHarnessIdentity: false\n    includeRuntimeContext: false\n"
        "    personaPrefix: 'Process only the supplied synthetic text. Return JSON.'\n"
        "- id: llm-deepseek\n  config:\n    apiKeyEnv: DEEPSEEK_API_KEY\n"
        "    defaultContextWindow: 16384\n    streamIdleTimeoutMs: 10000\n"
    )


def isolated_environment(run: Path, port: int) -> dict[str, str]:
    """Keep host credentials, proxies, Node hooks, and DSH settings out."""
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
    env.update({
        "PATH": str(NODE.parent), "DSH_HOME": str(run / "home"),
        "HOME": str(run / "os-home"), "USERPROFILE": str(run / "os-home"),
        "APPDATA": str(run / "os-home/appdata"), "LOCALAPPDATA": str(run / "os-home/local"),
        "TEMP": str(run / "temp"), "TMP": str(run / "temp"),
        "DEEPSEEK_API_KEY": "synthetic-mock-key", "DSH_TELEMETRY_DISABLED": "1",
        "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{port}/v1",
        "DSH_CONTEXT_WINDOW": "16384", "DSH_PROBE_PORT": str(port),
    })
    return env


def guard_text() -> str:
    """Fail closed on other Node socket destinations, including proxy attempts."""
    return """import net from 'node:net';
import { syncBuiltinESMExports } from 'node:module';
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const first = Array.isArray(args[0]) ? args[0][0] : args[0];
  const opts = typeof first === 'object' && first !== null ? first : {port:first, host:args[1]};
  if (opts.host !== '127.0.0.1' || Number(opts.port) !== Number(process.env.DSH_PROBE_PORT) || opts.path) {
    throw new Error('DSH_PROBE_NETWORK_DENIED');
  }
  return connect.apply(this, args);
};
syncBuiltinESMExports();
"""


def validate_request(body: dict) -> None:
    """Reject unexpected model inputs instead of serving a permissive mock."""
    allowed = {"model", "messages", "system", "stream", "max_tokens", "thinking", "output_config", "temperature", "top_p", "tools"}
    if set(body) - allowed:
        raise ValueError(f"unexpected request fields: {sorted(set(body) - allowed)}")
    if body.get("tools"):
        raise ValueError("model tools are forbidden")
    encoded = json.dumps(body, ensure_ascii=False)
    if "dsh_session_log" in encoded or "dsh_plugin_packages" in encoded:
        raise ValueError("extra upload fields are forbidden")
    if body.get("model") != "deepseek-flash" or body.get("max_tokens") != 256:
        raise ValueError("unexpected model or output cap")


class MockServer(ThreadingHTTPServer):
    """One local discovery endpoint and one fixed synthetic completion."""

    daemon_threads = True

    def __init__(self):
        self.requests: list[dict] = []
        self.failures: list[str] = []
        super().__init__(("127.0.0.1", 0), MockHandler)


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.server.requests.append({"method": "GET", "path": self.path})
        if self.path != "/v1/models":
            self.send_error(404)
            return
        data = json.dumps({"object": "list", "data": [{"id": "deepseek-flash", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 100000:
                raise ValueError("unexpected request length")
            body = json.loads(self.rfile.read(length))
            self.server.requests.append({"method": "POST", "path": self.path, "body": body})
            if self.path != "/v1/messages":
                raise ValueError("unexpected endpoint")
            if sum(r["method"] == "POST" for r in self.server.requests) != 1:
                raise ValueError("more than one model request")
            validate_request(body)
        except (ValueError, TypeError) as exc:
            self.server.failures.append(str(exc))
            self.send_error(400)
            return
        events = [
            {"type": "message_start", "message": {"id": "mock-message", "type": "message", "role": "assistant", "model": "deepseek-flash", "content": [], "usage": {"input_tokens": 3, "output_tokens": 0}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": ANSWER}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 12}},
            {"type": "message_stop"},
        ]
        data = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data.encode())))
        self.end_headers()
        self.wfile.write(data.encode())


def validate_dump(dump: str) -> None:
    """Check composed rows before starting the runtime."""
    for name in DISABLED:
        match = re.search(r"(?m)^- id: " + re.escape(name) + r"\s*$([\s\S]*?)(?=^- id: |\Z)", dump)
        if match is None or re.search(r"(?m)^  disabled: true\s*$", match[1]) is None:
            raise ValueError(f"disabled plugin missing from composed config: {name}")
    if "mode: read-only" not in dump:
        raise ValueError("read-only policy missing")


class RpcClient:
    """Read notifications while correlating responses; receipts are not results."""

    def __init__(self, process: subprocess.Popen):
        self.process = process
        self.frames: list[dict] = []
        self.lines = queue.Queue()
        self.next_id = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def call(self, method: str, params=None, timeout=25):
        self.next_id += 1
        request = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            request["params"] = params
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            if line is None:
                raise RuntimeError("DSH exited before RPC completion")
            frame = json.loads(line)
            self.frames.append(frame)
            if "method" in frame and "id" in frame:
                self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": frame["id"], "error": {"code": -32601, "message": "Probe denies host requests"}}) + "\n")
                self.process.stdin.flush()
            elif frame.get("id") == self.next_id:
                if "error" in frame:
                    raise RuntimeError(f"DSH RPC failure: {frame['error']}")
                return frame["result"]


def terminal_result(frames: list[dict]) -> dict:
    events = [f["params"]["event"] for f in frames if f.get("method") == "session.event"]
    terminal = [e for e in events if e["type"] == "turn/end"]
    messages = [e for e in events if e["type"] == "assistant/message"]
    if not terminal or terminal[-1]["data"]["reason"]["kind"] != "completed" or not messages:
        raise ValueError("completed terminal and assistant message required")
    text = "".join(b["text"] for b in messages[-1]["data"]["message"]["content"] if b["type"] == "text")
    if text != ANSWER:
        raise ValueError("mock response mismatch")
    return json.loads(text)


def git_state(repo: Path) -> dict:
    def command(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, encoding="utf-8").strip()
    return {"head": command("rev-parse", "HEAD"), "status": command("status", "--porcelain"), "diff_sha256": hashlib.sha256(command("diff", "HEAD").encode()).hexdigest()}


def run_mock() -> dict:
    before = git_state(DSH_ROOT)
    if before["head"] != DSH_SHA:
        raise ValueError("DSH revision changed; inspect the profile before probing")
    run = OUTPUT_ROOT / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    for name in ("home", "os-home/appdata", "os-home/local", "temp", "cwd"):
        (run / name).mkdir(parents=True, exist_ok=True)
    patch, guard = run / "overlay.yml", run / "network-guard.mjs"
    patch.write_text(overlay_text(), encoding="utf-8")
    guard.write_text(guard_text(), encoding="utf-8")
    server = MockServer()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    env = isolated_environment(run, server.server_port)
    command = [str(NODE), "--import", guard.as_uri(), str(DSH_ROOT / "apps/cli/lib/bin.js"), "--profile", "sdk-minimal", "--patch", str(patch)]
    client = process = None
    summary = {"mode": "mock", "real_model_requests": 0, "semantic_quality": "not_evaluated", "run_dir": str(run), "dsh_before": before}
    try:
        denied = subprocess.run(
            [str(NODE), "--import", guard.as_uri(), "--input-type=module", "--eval",
             "import net from 'node:net'; try { net.connect({host:'192.0.2.1',port:443}); process.exit(2); } catch(e) { if(e.message!=='DSH_PROBE_NETWORK_DENIED') throw e; console.log(e.message); }"],
            cwd=run / "cwd", env=env, text=True, encoding="utf-8", capture_output=True, timeout=10,
        )
        (run / "network-guard-check.log").write_text(denied.stdout + denied.stderr, encoding="utf-8")
        if denied.returncode != 0 or denied.stdout.strip() != "DSH_PROBE_NETWORK_DENIED":
            raise ValueError("network guard failed its preflight")
        summary["other_socket_destination_denied"] = True
        dump = subprocess.run(command + ["--dump-config"], cwd=run / "cwd", env=env, text=True, encoding="utf-8", capture_output=True, timeout=25)
        (run / "config-dump.yml").write_text(dump.stdout, encoding="utf-8")
        (run / "config-dump-stderr.log").write_text(dump.stderr, encoding="utf-8")
        dump.check_returncode()
        validate_dump(dump.stdout)
        with (run / "stderr.log").open("w", encoding="utf-8") as errors:
            process = subprocess.Popen(command, cwd=run / "cwd", env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8")
            client = RpcClient(process)
            summary["initialize"] = client.call("initialize", {"cwd": str(run / "cwd"), "provider": "deepseek-official", "model": "deepseek-flash", "maxTokens": 256})
            summary["receipt"] = client.call("session/query", {"sessionId": "synthetic-probe", "contentBlocks": [{"type": "text", "text": PROMPT}]})
            client.call("session/wait", {"sessionId": "synthetic-probe"})
            summary["result"] = terminal_result(client.frames)
            client.call("shutdown")
            process.stdin.close()
            process.wait(timeout=10)
            if process.returncode != 0:
                raise ValueError("DSH did not exit cleanly")
        posts = [r for r in server.requests if r["method"] == "POST"]
        if len(posts) != 1 or server.failures:
            raise ValueError("mock request audit failed")
        summary.update(status="passed", mock_model_requests=len(posts), discovery_requests=sum(r["method"] == "GET" for r in server.requests), tools=[], extra_upload_fields=[], process_exit=process.returncode)
    except Exception as exc:
        summary.update(status="failed", error=str(exc))
        raise
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        if client:
            client.reader.join(timeout=3)
            (run / "rpc.jsonl").write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in client.frames), encoding="utf-8")
        if process:
            for stream in (process.stdin, process.stdout):
                if stream and not stream.closed:
                    stream.close()
        (run / "requests.json").write_text(json.dumps(server.requests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["dsh_after"] = git_state(DSH_ROOT)
        summary["dsh_source_unchanged"] = before == summary["dsh_after"]
        summary["owned_process_stopped"] = process is None or process.poll() is not None
        (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not summary["dsh_source_unchanged"]:
        raise ValueError("DSH source changed during probe; inspect before proceeding")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)
    result = run_mock() if args.mock else {"mode": "dry-run", "model_requests": 0, "real_endpoints": "refused", "profile": "sdk-minimal", "next": "--mock executes one built-in synthetic task against a new loopback mock"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
