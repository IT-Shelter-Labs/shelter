"""Shared JSON framing and constant-time token checks for local services."""
import json
import secrets


def token_matches(supplied, expected):
    return bool(expected) and secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def send_json(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
