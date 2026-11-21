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


TIMER_PROBE = (
    "const start = Date.now();"
    "setTimeout(() => console.log(Date.now() - start), 2000)"
)


def verify_timer_clock(binary):
    """Timers must follow the kernel clock.

    Bun 1.3.14 drives JS timers from rdtsc, scaled by the frequency in CPUID leaf 0x15.
    On VMs whose guest TSC runs at another rate (GCP Sapphire Rapids reports 1900 MHz
    for a 2700 MHz TSC) every timer fires at 0.70x its delay, including the shell
    tool's command timeout. The probe only reproduces on such hosts, so the embedded
    Bun version is pinned as well.
    """
    environment = {**os.environ, "BUN_BE_BUN": "1"}
    version = subprocess.check_output([str(binary), "--version"], env=environment, text=True).strip()
    assert version != "1.3.14", "Bun 1.3.14 timers ignore the kernel clock"
    elapsed = int(
        subprocess.check_output([str(binary), "-e", TIMER_PROBE], env=environment, text=True, timeout=30).strip()
    )
    assert 1950 <= elapsed <= 3000, f"setTimeout(2000) fired after {elapsed} ms"
    return version, elapsed


if __name__ == "__main__":
    binary = Path(sys.argv[1]).resolve()
    bun, elapsed = verify_timer_clock(binary)
    print(f"embedded Bun {bun}: setTimeout(2000) fired after {elapsed} ms")
    for retries, expected in [(None, 6), (0, 1), (12, 13)]:
        # Detached dependency installers can outlive the CLI; the CI runner owns leftover cache cleanup.
        with tempfile.TemporaryDirectory(prefix="opencode-retry-", ignore_cleanup_errors=True) as root:
            verify(binary, Path(root), retries, expected)
        print(f"maxRetries={retries}: {expected} calls in one session")
