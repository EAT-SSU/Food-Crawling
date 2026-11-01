"""Fetch the dormitory menu page from a residential line for the menu Lambda.

The dormitory site serves a maintenance page to datacenter IPs, so the Lambda
asks this relay instead. It only forwards one fixed URL with validated
gyear/gmonth/gday values and returns the original bytes unchanged.
"""
from __future__ import annotations

import hmac
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOURCE_URL = "https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php"
TOKEN = os.environ["DORM_RELAY_TOKEN"]
LIMITS = {"gyear": (2020, 2100), "gmonth": (1, 12), "gday": (1, 31)}


def _week(query: str) -> dict[str, int] | None:
    values = urllib.parse.parse_qs(query)
    week: dict[str, int] = {}
    for name, (low, high) in LIMITS.items():
        raw = values.get(name, [""])
        if len(raw) != 1 or not raw[0].isdigit() or not low <= int(raw[0]) <= high:
            return None
        week[name] = int(raw[0])
    return week


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not hmac.compare_digest(self.headers.get("X-Relay-Token", ""), TOKEN):
            self.send_error(403)
            return
        week = _week(urllib.parse.urlsplit(self.path).query)
        if week is None:
            self.send_error(400)
            return
        query = urllib.parse.urlencode({"viewform": "B0001_foodboard_list", **week})
        try:
            with urllib.request.urlopen(f"{SOURCE_URL}?{query}", timeout=20) as source:
                body = source.read()
                content_type = source.headers.get("Content-Type", "text/html")
        except Exception as error:
            self.log_message("source failed: %s", type(error).__name__)
            self.send_error(502)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "30085"))), Handler).serve_forever()
