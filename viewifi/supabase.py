"""Supabase integration — same tables the Android app uses, so a Linux host
mixes seamlessly with Android hosts under one account.

- Signs in with email/password (GoTrue REST) -> user JWT for RLS
- Polls `device_commands` (arm/disarm from the geofence / Android user mode)
- Upserts `host_registry` heartbeat so this host appears in the app's
  multi-host selector by name

Requires the SQL in docs/supabase_schema.sql of the Viewifi app repo.
"""

import json
import time
import urllib.parse
import urllib.request


class SupabaseBridge:
    def __init__(self, url, anon_key, email, password, device_id, device_name):
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.email = email
        self.password = password
        self.device_id = device_id
        self.device_name = device_name
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0.0

    @property
    def enabled(self):
        return bool(self.url and self.anon_key and self.email and self.password)

    # ---------- auth ----------

    def _auth(self, grant, payload):
        req = urllib.request.Request(
            f"{self.url}/auth/v1/token?grant_type={grant}",
            data=json.dumps(payload).encode(),
            headers={
                "apikey": self.anon_key,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def sign_in(self):
        try:
            if self.refresh_token and time.time() < self.expires_at - 60:
                return
            if self.refresh_token:
                data = self._auth("refresh_token", {"refresh_token": self.refresh_token})
            else:
                data = self._auth("password", {"email": self.email, "password": self.password})
            self.access_token = data["access_token"]
            self.refresh_token = data.get("refresh_token", self.refresh_token)
            self.expires_at = time.time() + int(data.get("expires_in", 3600))
        except Exception as e:
            print(f"[supabase] sign-in failed: {e}")

    # ---------- rest ----------

    def _rest(self, method, path, body=None, extra_headers=None):
        self.sign_in()
        if not self.access_token:
            return None
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.url}/rest/v1/{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read().decode()
            return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                # token expired mid-run: force refresh once
                self.expires_at = 0
                self.sign_in()
            print(f"[supabase] {method} {path} -> HTTP {e.code}")
            return None
        except Exception as e:
            print(f"[supabase] {method} {path} failed: {e}")
            return None

    # ---------- device_commands ----------

    def poll_commands(self, since_ms):
        """Commands newer than since_ms: list of dicts with cmd/device_id."""
        from datetime import datetime, timezone
        iso = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).isoformat()
        q = urllib.parse.quote(f"gt.{iso}")
        rows = self._rest("GET", f"device_commands?created_at={q}&order=id.asc")
        return rows or []

    # ---------- host_registry ----------

    def heartbeat(self):
        from datetime import datetime, timezone
        self._rest(
            "POST",
            "host_registry",
            body={
                "device_id": self.device_id,
                "name": self.device_name,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            },
            extra_headers={"Prefer": "resolution=merge-duplicates"},
        )
