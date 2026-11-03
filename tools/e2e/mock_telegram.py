"""E2E용 가짜 텔레그램 서버. POST /bot<token>/sendMessage를 기록하고, GET /messages로 돌려준다."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

messages = []


class H(BaseHTTPRequestHandler):
    def _send(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/sendMessage"):
            messages.append(body["text"])
        self._send({"ok": True})

    def do_GET(self):
        self._send(messages)


HTTPServer(("0.0.0.0", 8081), H).serve_forever()
