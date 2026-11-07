"""Keyless, synthetic checks for the mock-only DSH bridge."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from experiments import dsh_bridge as bridge


class DshBridgeTests(unittest.TestCase):
    def request(self):
        return {"model": "deepseek-flash", "max_tokens": 256, "stream": True,
                "tools": [], "messages": [{"role": "user", "content": bridge.PROMPT}]}

    def test_default_does_not_start_process_or_network(self):
        with patch.object(bridge, "run_mock") as run, redirect_stdout(io.StringIO()) as output:
            bridge.main([])
        run.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["model_requests"], 0)

    def test_real_endpoint_or_caller_prompt_options_are_refused(self):
        for args in (["--endpoint", "https://example.invalid"], ["--prompt", "private text"], ["--api-key", "synthetic"]):
            with self.subTest(args=args), redirect_stdout(io.StringIO()), patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    bridge.main(args)

    def test_environment_drops_host_keys_proxies_and_node_hooks(self):
        with patch.dict(bridge.os.environ, {"DEEPSEEK_API_KEY": "host-secret", "HTTP_PROXY": "host-proxy", "NODE_OPTIONS": "host-hook", "DSH_HOME": "host-home"}):
            env = bridge.isolated_environment(Path("isolated"), 12345)
        self.assertEqual(env["DEEPSEEK_API_KEY"], "synthetic-mock-key")
        self.assertEqual(env["DEEPSEEK_BASE_URL"], "http://127.0.0.1:12345/v1")
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("NODE_OPTIONS", env)
        self.assertNotEqual(env["DSH_HOME"], "host-home")

    def test_model_can_receive_no_tools_or_upload_extensions(self):
        bridge.validate_request(self.request())
        for field, value in (("tools", [{"name": "pwsh"}]), ("dsh_session_log", {}), ("dsh_plugin_packages", [])):
            body = self.request() | {field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                bridge.validate_request(body)

    def test_composed_config_must_disable_every_dangerous_plugin(self):
        valid = bridge.overlay_text()
        bridge.validate_dump(valid)
        with self.assertRaises(ValueError):
            bridge.validate_dump(valid.replace("  disabled: true", "  disabled: false", 1))

    def test_enqueue_receipt_and_idle_are_not_completion(self):
        for frames in ([{"id": 2, "result": {"kind": "prompt", "messageId": "synthetic"}}],
                       [{"method": "session.status", "params": {"status": "idle"}}]):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                bridge.terminal_result(frames)

    def test_only_completed_terminal_with_expected_assistant_json_passes(self):
        def event(kind, data):
            return {"method": "session.event", "params": {"event": {"type": kind, "data": data}}}
        frames = [event("assistant/message", {"message": {"content": [{"type": "text", "text": bridge.ANSWER}]}}),
                  event("turn/end", {"reason": {"kind": "completed"}})]
        self.assertEqual(bridge.terminal_result(frames), {"synthetic": True, "opinions": []})
        frames[-1]["params"]["event"]["data"]["reason"]["kind"] = "error"
        with self.assertRaises(ValueError):
            bridge.terminal_result(frames)


if __name__ == "__main__":
    unittest.main()
