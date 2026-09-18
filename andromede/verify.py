import json
import contextlib
import signal
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def verify(binary, tmp_path, retries, expected):
    requests = []

    class OverloadedEndpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Service unavailable","type":"server_error"}}')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), OverloadedEndpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {
        "enabled_providers": ["retrytest"],
        "model": "retrytest/mock",
        "small_model": "retrytest/mock",
        "agent": {"title": {"disable": True}, "summary": {"disable": True}},
        "provider": {
            "retrytest": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Retry test",
                "options": {
                    "baseURL": f"http://127.0.0.1:{server.server_port}/v1",
                    "apiKey": "unused",
                },
                "models": {"mock": {"name": "Mock", "limit": {"context": 32768, "output": 1024}}},
            }
        },
    }
    config["autoupdate"] = False
    if retries is not None:
        config["experimental"] = {"retry": {"maxRetries": retries}}
    environment = {
        **os.environ,
        "OPENCODE_CONFIG_CONTENT": json.dumps(config),
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
        "OPENCODE_FAKE_VCS": "git",
        **{
            f"XDG_{name}_HOME": str(tmp_path / name.lower())
            for name in ("CONFIG", "DATA", "STATE", "CACHE")
        },
    }
    try:
        process = subprocess.Popen(
            [str(binary), "run", "--model", "retrytest/mock", "--format", "json", "Say hello."],
            cwd=tmp_path,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=90)
        finally:
            # CLI startup may spawn package installers; stop them before deleting their cache.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        assert len(requests) == expected, result.stderr + result.stdout
        assert all(request["model"] == "mock" for request in requests)
        assert all(request["messages"] == requests[0]["messages"] for request in requests)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        assert any(event.get("type") == "error" for event in events)
        assert len({event["sessionID"] for event in events if "sessionID" in event}) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    binary = Path(sys.argv[1]).resolve()
    for retries, expected in [(None, 6), (0, 1), (12, 13)]:
        with tempfile.TemporaryDirectory(prefix="opencode-retry-") as root:
            verify(binary, Path(root), retries, expected)
        print(f"maxRetries={retries}: {expected} calls in one session")
