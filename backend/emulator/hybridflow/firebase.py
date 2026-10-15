"""Minimal Firebase Realtime Database REST client (standard library only).

Used by the device emulator and the Streamlit frontend. Paths are relative to
/devices/<device id>.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request


class Firebase:
    def __init__(self, db_url: str, device: str, auth: str | None = None, timeout: float = 10):
        self.base = db_url.rstrip("/") + "/devices/" + urllib.parse.quote(device)
        self.auth = auth or ""
        self.timeout = timeout

    def url(self, path: str = "", query: dict | None = None) -> str:
        u = f"{self.base}/{path}.json" if path else f"{self.base}.json"
        params = dict(query or {})
        if self.auth:
            params["auth"] = self.auth
        return u + ("?" + urllib.parse.urlencode(params) if params else "")

    def request(self, method: str, path: str = "", body=None, query: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url(path, query), data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            text = resp.read().decode() or "null"
            return json.loads(text)

    def latest(self, path: str, limit: int):
        """The newest `limit` children of a push list, oldest first."""
        data = self.request("GET", path, query={"orderBy": '"ts"', "limitToLast": limit}) or {}
        items = [dict(v, id=k) for k, v in data.items() if isinstance(v, dict)]
        return sorted(items, key=lambda x: x.get("ts") or 0)
