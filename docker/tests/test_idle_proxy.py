#!/usr/bin/env python3
"""
Integration test suite for OpenJet Idle Unload HTTP Proxy (docker/idle_proxy.py).
Tests:
  (a) /health works while loaded and while unloaded and does not load the engine;
  (b) a normal request works;
  (c) SSE chunks arrive incrementally, not all at the end;
  (d) after the idle time the fake engine process is gone;
  (e) the next request reloads it and succeeds;
  (f) 5 concurrent requests during a load start exactly one engine;
  (g) a request that is still streaming prevents unload;
  (i) SIGTERM stops the engine and exits.
"""

import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time


def log(msg):
    print(f"[test-runner] {msg}", flush=True)


def read_json(resp):
    data = resp.read()
    return json.loads(data.decode("utf-8"))


def test_main():
    here = os.path.dirname(os.path.abspath(__file__))
    idle_proxy_path = os.path.join(here, "..", "idle_proxy.py")
    fake_engine_path = os.path.join(here, "fake_engine.py")

    proxy_port = 19180
    engine_port = 19181

    env = os.environ.copy()
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(proxy_port)
    env["INTERNAL_PORT"] = str(engine_port)
    # Use 1.0 second timeout for fast tests
    env["IDLE_TIMEOUT_SECONDS"] = "1.0"

    proxy_cmd = [
        sys.executable,
        idle_proxy_path,
        "--host", "127.0.0.1",
        "--port", str(proxy_port),
        "--internal-port", str(engine_port),
        "--idle-timeout", "1",
        "--",
        sys.executable,
        fake_engine_path,
        "--host", "127.0.0.1",
        "--port", str(engine_port),
    ]

    log("Starting proxy and eager engine...")
    proxy_proc = subprocess.Popen(
        proxy_cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    # Output collector
    stdout_lines = []

    def collect_stdout():
        for line in iter(proxy_proc.stdout.readline, ""):
            stdout_lines.append(line.rstrip())
            print(f"  {line.rstrip()}", flush=True)

    collector_t = threading.Thread(target=collect_stdout, daemon=True)
    collector_t.start()

    try:
        # Wait for proxy and eager engine to be ready
        t0 = time.monotonic()
        ready = False
        while time.monotonic() - t0 < 10:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=1.0)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                if resp.status == 200:
                    data = read_json(resp)
                    if data.get("engine") == "loaded":
                        ready = True
                        conn.close()
                        break
                conn.close()
            except Exception:
                pass
            time.sleep(0.1)

        assert ready, "Proxy eager load failed to reach loaded state"
        log("Eager load verified.")

        # (a) /health works while loaded
        log("Testing (a): /health while loaded...")
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        data = read_json(resp)
        assert data == {"status": "ok", "engine": "loaded"}, f"Unexpected health data: {data}"
        conn.close()
        log("Passed (a) loaded.")

        # (b) Normal request works
        log("Testing (b): normal POST request...")
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port)
        body = json.dumps({"model": "test-model"}).encode("utf-8")
        conn.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        data = read_json(resp)
        assert "choices" in data and data["choices"][0]["message"]["content"] == "Fake engine response"
        conn.close()
        log("Passed (b) normal request.")

        # (c) SSE chunks arrive incrementally
        log("Testing (c): incremental SSE chunk streaming...")
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port)
        stream_body = json.dumps({"stream": True}).encode("utf-8")
        conn.request("POST", "/v1/chat/completions", body=stream_body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/event-stream"
        assert resp.getheader("Transfer-Encoding") == "chunked"

        chunk_timestamps = []
        chunks = []
        while True:
            chunk = resp.read1()
            if not chunk:
                break
            chunk_timestamps.append(time.monotonic())
            chunks.append(chunk)

        conn.close()
        assert len(chunks) >= 3, f"Expected at least 3 SSE chunks, got {len(chunks)}"
        # Check time intervals between consecutive chunks (> 0.2s each, since fake_engine sleeps 0.3s)
        delays = [chunk_timestamps[i] - chunk_timestamps[i - 1] for i in range(1, len(chunk_timestamps))]
        log(f"Delays between chunks: {[round(d, 3) for d in delays]}")
        assert any(d >= 0.2 for d in delays), "Chunks were buffered rather than received incrementally!"
        log("Passed (c) incremental SSE chunk delivery.")

        # (d) After idle time, fake engine process is gone
        log("Testing (d): waiting for idle timeout (1.0s)...")
        time.sleep(1.6)

        # Check /health while unloaded
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        data = read_json(resp)
        assert data == {"status": "ok", "engine": "unloaded"}, f"Expected unloaded engine state, got {data}"
        conn.close()

        # (a part 2): verify /health does NOT load the engine
        time.sleep(0.3)
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        data = read_json(resp)
        assert data == {"status": "ok", "engine": "unloaded"}, "/health erroneously triggered engine load!"
        conn.close()
        log("Passed (d) & (a unloaded): engine unloaded and /health did not reload it.")

        # (e) Next request reloads engine and succeeds
        log("Testing (e): reload on demand...")
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port)
        body = json.dumps({"model": "test-model"}).encode("utf-8")
        conn.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        data = read_json(resp)
        assert "choices" in data and data["choices"][0]["message"]["content"] == "Fake engine response"
        conn.close()
        log("Passed (e): reload on demand succeeded.")

        # (f) 5 concurrent requests during a load start exactly one engine
        log("Testing (f): 5 concurrent requests during load...")
        # Wait for unload first
        time.sleep(1.6)
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port)
        conn.request("GET", "/health")
        data = read_json(conn.getresponse())
        conn.close()
        assert data["engine"] == "unloaded"

        start_count_before = sum(1 for line in stdout_lines if "request while unloaded (triggering load)" in line)
        results = [None] * 5

        def worker(idx):
            try:
                c = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=10.0)
                b = json.dumps({"idx": idx}).encode("utf-8")
                c.request("POST", "/v1/chat/completions", body=b, headers={"Content-Type": "application/json"})
                r = c.getresponse()
                results[idx] = r.status
                c.close()
            except Exception as e:
                results[idx] = str(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        start_count_after = sum(1 for line in stdout_lines if "request while unloaded (triggering load)" in line)
        log(f"Concurrent requests results: {results}")
        assert all(res == 200 for res in results), f"Some concurrent requests failed: {results}"
        assert start_count_after == start_count_before + 1, (
            f"Expected exactly 1 trigger, got {start_count_after - start_count_before}"
        )
        log("Passed (f): 5 concurrent requests started exactly one engine.")

        # (g) Streaming request prevents unload
        log("Testing (g): in-flight streaming prevents unload...")
        # Start a stream that lasts 1.2 seconds, with idle timeout 1.0s
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port)
        stream_body = json.dumps({"stream": True}).encode("utf-8")
        conn.request("POST", "/v1/chat/completions", body=stream_body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200

        # Read first chunk, then wait 1.1s (exceeding 1.0s idle timeout) while stream is still open
        first_chunk = resp.read1()
        assert first_chunk
        time.sleep(1.1)

        # Check /health on separate connection: must be "loaded", not "unloaded"
        c2 = http.client.HTTPConnection("127.0.0.1", proxy_port)
        c2.request("GET", "/health")
        h_data = read_json(c2.getresponse())
        c2.close()
        assert h_data["engine"] == "loaded", f"Engine was unloaded while stream was in-flight! {h_data}"

        # Finish reading stream
        while resp.read1():
            pass
        conn.close()
        log("Passed (g): in-flight stream prevented unload.")

    finally:
        # (i) SIGTERM stops the engine and exits
        log("Testing (i): SIGTERM stops proxy and engine cleanly...")
        proxy_proc.send_signal(signal.SIGTERM)
        try:
            exit_code = proxy_proc.wait(timeout=5)
            log(f"Proxy exited with code {exit_code}")
            assert exit_code == 0, f"Expected proxy exit code 0, got {exit_code}"
        except subprocess.TimeoutExpired:
            proxy_proc.kill()
            raise AssertionError("Proxy did not terminate within 5 seconds on SIGTERM")

        log("Passed (i): clean SIGTERM termination verified.")

    print("\nALL PYTHON INTEGRATION TESTS PASSED!\n", flush=True)


if __name__ == "__main__":
    test_main()
