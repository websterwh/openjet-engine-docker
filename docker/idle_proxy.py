#!/usr/bin/env python3
"""
Lightweight stdlib-only HTTP proxy for OpenJet engine that unloads the engine
process when idle to free GPU VRAM, and reloads it on the next incoming request.
"""

import argparse
import http.client
import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time


class EngineManager:
    """Manages the OpenJet engine subprocess lifecycle and idle timeout."""

    def __init__(self, engine_cmd, internal_port, timeout_seconds):
        self.engine_cmd = engine_cmd
        self.internal_port = internal_port
        self.timeout_seconds = timeout_seconds

        self.lock = threading.Lock()
        self.state = "unloaded"  # "unloaded", "loading", "loaded"
        self.load_event = threading.Event()
        self.load_error = None
        self.engine_proc = None

        self.in_flight = 0
        self.in_flight_lock = threading.Lock()
        self.last_activity = time.monotonic()

        self.shutdown_event = threading.Event()
        self.watchdog_thread = None

    def start_watchdog(self):
        if self.timeout_seconds > 0:
            self.watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self.watchdog_thread.start()

    def _watchdog_loop(self):
        while not self.shutdown_event.is_set():
            time.sleep(0.2)
            with self.lock:
                if self.state == "loaded" and self.engine_proc is not None:
                    # Check if engine crashed unexpectedly
                    poll_code = self.engine_proc.poll()
                    if poll_code is not None:
                        print(f"[idle-proxy] engine exited (code {poll_code})", flush=True)
                        self.state = "unloaded"
                        self.engine_proc = None
                        self.load_event.clear()
                        continue

                    with self.in_flight_lock:
                        in_flight = self.in_flight
                        last_act = self.last_activity

                    if in_flight == 0:
                        elapsed = time.monotonic() - last_act
                        if elapsed >= self.timeout_seconds:
                            idle_display = (
                                f"{self.timeout_seconds / 60.0:.0f} min"
                                if self.timeout_seconds >= 60
                                else f"{self.timeout_seconds:.1f}s"
                            )
                            print(f"[idle-proxy] unloading after {idle_display} idle", flush=True)
                            self._stop_engine_locked()

    def ensure_loaded(self, trigger_reason=""):
        """Ensures the engine is loaded. Blocks until loaded or failure."""
        should_start = False
        with self.lock:
            if self.state == "loaded":
                return True
            if self.state == "unloaded":
                if trigger_reason:
                    print(f"[idle-proxy] {trigger_reason}", flush=True)
                self.state = "loading"
                self.load_event.clear()
                self.load_error = None
                should_start = True

        if should_start:
            threading.Thread(target=self._load_worker, daemon=True).start()

        # Wait up to 10 minutes (600s) for engine load
        ready = self.load_event.wait(timeout=600)
        with self.lock:
            if not ready or self.state != "loaded":
                return False
            return True

    def _load_worker(self):
        print("[idle-proxy] engine starting", flush=True)
        t0 = time.monotonic()
        try:
            # Start engine with its own process group
            proc = subprocess.Popen(
                self.engine_cmd,
                start_new_session=True,
            )
        except Exception as e:
            with self.lock:
                self.load_error = str(e)
                self.state = "unloaded"
                self.load_event.set()
            return

        with self.lock:
            self.engine_proc = proc

        # Poll internal health check until ready or timed out (600s)
        ready = False
        while time.monotonic() - t0 < 600:
            if self.shutdown_event.is_set():
                break

            ret = proc.poll()
            if ret is not None:
                print(f"[idle-proxy] engine exited (code {ret})", flush=True)
                with self.lock:
                    self.load_error = f"Engine exited prematurely with code {ret}"
                    self.state = "unloaded"
                    self.engine_proc = None
                    self.load_event.set()
                return

            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.internal_port, timeout=1.0)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                if resp.status == 200:
                    ready = True
                    conn.close()
                    break
                conn.close()
            except Exception:
                pass
            time.sleep(0.1)

        dur = time.monotonic() - t0
        with self.lock:
            if ready:
                print(f"[idle-proxy] engine ready ({dur:.1f}s)", flush=True)
                self.state = "loaded"
                with self.in_flight_lock:
                    self.last_activity = time.monotonic()
                self.load_event.set()
            else:
                self._stop_engine_locked()
                self.load_error = "Timed out waiting for engine health check"
                self.state = "unloaded"
                self.load_event.set()

    def _stop_engine_locked(self):
        proc = self.engine_proc
        if proc is None:
            self.state = "unloaded"
            self.load_event.clear()
            return

        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            try:
                proc.terminate()
            except Exception:
                pass

        # Wait up to 30 seconds for graceful exit
        t_kill = time.monotonic()
        while time.monotonic() - t_kill < 30:
            if proc.poll() is not None:
                break
            time.sleep(0.1)

        if proc.poll() is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

        code = proc.poll()
        print(f"[idle-proxy] engine exited (code {code if code is not None else 0})", flush=True)
        self.state = "unloaded"
        self.engine_proc = None
        self.load_event.clear()

    def stop(self):
        """Clean shutdown of engine on proxy termination."""
        self.shutdown_event.set()
        with self.lock:
            self._stop_engine_locked()

    def enter_request(self):
        with self.in_flight_lock:
            self.in_flight += 1

    def exit_request(self):
        with self.in_flight_lock:
            self.in_flight -= 1
            self.last_activity = time.monotonic()

    def get_state(self):
        with self.lock:
            return self.state


def make_proxy_handler(engine_mgr, internal_port):
    class ProxyRequestHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass  # Suppress default noisy access logs

        def do_GET(self):
            self._handle_request("GET")

        def do_POST(self):
            self._handle_request("POST")

        def do_HEAD(self):
            self._handle_request("HEAD")

        def do_PUT(self):
            self._handle_request("PUT")

        def do_DELETE(self):
            self._handle_request("DELETE")

        def do_OPTIONS(self):
            self._handle_request("OPTIONS")

        def _handle_request(self, method):
            clean_path = self.path.split("?")[0]

            # GET /health and /v1/health never load the engine and never reset the idle timer
            if clean_path in ("/health", "/v1/health") and method == "GET":
                state = engine_mgr.get_state()
                payload = json.dumps({"status": "ok", "engine": state}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            # Any other request while unloaded triggers a load
            loaded = engine_mgr.ensure_loaded(trigger_reason="request while unloaded (triggering load)")
            if not loaded:
                state = engine_mgr.get_state()
                err_msg = json.dumps({
                    "error": {
                        "message": f"OpenJet engine failed to load (state: {state})",
                        "type": "server_error"
                    }
                }).encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_msg)))
                self.end_headers()
                try:
                    self.wfile.write(err_msg)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            # Track in-flight request
            engine_mgr.enter_request()
            try:
                self._forward_to_engine(method)
            finally:
                engine_mgr.exit_request()

        def _forward_to_engine(self, method):
            content_len = int(self.headers.get("Content-Length", 0))
            req_body = self.rfile.read(content_len) if content_len > 0 else None

            # Prepare upstream headers
            headers = {}
            for k, v in self.headers.items():
                k_lower = k.lower()
                if k_lower not in ("host", "connection"):
                    headers[k] = v
            headers["Host"] = f"127.0.0.1:{internal_port}"

            conn = http.client.HTTPConnection("127.0.0.1", internal_port, timeout=600)
            try:
                conn.request(method, self.path, body=req_body, headers=headers)
                resp = conn.getresponse()
            except (BrokenPipeError, ConnectionResetError, http.client.RemoteDisconnected):
                conn.close()
                self._send_503("Engine connection reset")
                return
            except Exception as e:
                conn.close()
                self._send_503(f"Engine forwarding error: {e}")
                return

            try:
                self.send_response(resp.status, resp.reason)
                is_chunked = resp.getheader("Transfer-Encoding", "").lower() == "chunked"

                for k, v in resp.getheaders():
                    k_lower = k.lower()
                    if k_lower in ("server", "date", "connection"):
                        continue
                    self.send_header(k, v)
                self.end_headers()

                # Stream body chunk-by-chunk with immediate flush
                if is_chunked:
                    while True:
                        chunk = resp.read1()
                        if not chunk:
                            break
                        self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                else:
                    while True:
                        buf = resp.read1()
                        if not buf:
                            break
                        self.wfile.write(buf)
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # Client disconnected mid-stream; close upstream connection to abort engine generation
                conn.close()
            finally:
                conn.close()

        def _send_503(self, message):
            body = json.dumps({"error": {"message": message, "type": "server_error"}}).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    return ProxyRequestHandler


def parse_idle_timeout(val):
    """Validate IDLE_TIMEOUT: must be a non-negative integer."""
    try:
        ival = int(val)
        if ival < 0:
            raise ValueError()
        return ival
    except (ValueError, TypeError):
        print(f"ERROR: IDLE_TIMEOUT must be a non-negative integer (got '{val}').", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="OpenJet Idle Unload HTTP Proxy")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"), help="Public listen host")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "18080")), help="Public listen port")
    parser.add_argument(
        "--internal-port",
        type=int,
        default=int(os.environ.get("INTERNAL_PORT", "18081")),
        help="Internal engine port",
    )
    parser.add_argument(
        "--idle-timeout",
        default=os.environ.get("IDLE_TIMEOUT", "0"),
        help="Idle timeout in minutes (0 = disabled)",
    )
    parser.add_argument("engine_cmd", nargs=argparse.REMAINDER, help="Engine command and arguments")

    args = parser.parse_args()

    idle_timeout_min = parse_idle_timeout(args.idle_timeout)

    # Optional test override in seconds via undocumented env var
    seconds_override = os.environ.get("IDLE_TIMEOUT_SECONDS")
    if seconds_override is not None:
        try:
            timeout_seconds = float(seconds_override)
            if timeout_seconds < 0:
                raise ValueError()
        except ValueError:
            print(f"ERROR: IDLE_TIMEOUT_SECONDS must be a non-negative number (got '{seconds_override}').", file=sys.stderr)
            sys.exit(1)
    else:
        timeout_seconds = idle_timeout_min * 60.0

    cmd = args.engine_cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("ERROR: No engine command specified to run.", file=sys.stderr)
        sys.exit(1)

    engine_mgr = EngineManager(cmd, args.internal_port, timeout_seconds)

    # Signal handlers for clean shutdown
    def sig_handler(signum, frame):
        engine_mgr.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    # Eager start of the engine as required
    engine_mgr.ensure_loaded()
    engine_mgr.start_watchdog()

    handler_cls = make_proxy_handler(engine_mgr, args.internal_port)
    httpd = http.server.ThreadingHTTPServer((args.host, args.port), handler_cls)
    httpd.daemon_threads = True

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine_mgr.stop()


if __name__ == "__main__":
    main()
