#!/usr/bin/env python3
"""
A small stdlib-only fake OpenJet engine HTTP server for CPU-only testing.
Implements /health, normal JSON responses, and slow SSE chunked streaming.
"""

import argparse
import http.server
import json
import signal
import sys
import time


class FakeEngineHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass  # Quiet logging

    def do_GET(self):
        clean_path = self.path.split("?")[0]
        if clean_path in ("/health", "/v1/health"):
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        elif clean_path == "/test":
            body = json.dumps({"result": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        clean_path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        stream = False
        try:
            parsed = json.loads(raw_body or b"{}")
            stream = bool(parsed.get("stream", False))
        except Exception:
            pass

        if stream:
            # Slow SSE streaming response
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for i in range(4):
                    chunk_data = f"data: chunk {i}\n\n".encode("utf-8")
                    self.wfile.write(b"%x\r\n" % len(chunk_data) + chunk_data + b"\r\n")
                    self.wfile.flush()
                    time.sleep(0.3)
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            # Normal JSON response
            body = json.dumps({
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "Fake engine response"}}]
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()


def main():
    parser = argparse.ArgumentParser(description="Fake OpenJet engine for test suite")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=18081, help="Bind port")
    args, _ = parser.parse_known_args()

    httpd = http.server.ThreadingHTTPServer((args.host, args.port), FakeEngineHandler)
    httpd.daemon_threads = True

    def sig_handler(signum, frame):
        httpd.server_close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
