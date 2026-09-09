"""Telegram bot client — pure urllib, multipart built by hand.

- send_message / send_photo / send_audio
- getUpdates polling for remote commands (/status /arm /disarm /photo /help)
  Replies are only accepted from the configured chat_id.
"""

import json
import urllib.request
import urllib.parse
import uuid

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 15


class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = str(chat_id)
        self.offset = 0

    @property
    def enabled(self):
        return bool(self.token and self.chat_id)

    # ---------- send ----------

    def send_message(self, text):
        if not self.enabled:
            return
        data = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }).encode()
        self._post("sendMessage", data)

    def send_photo(self, photo_bytes, caption=""):
        self._send_file("sendPhoto", "photo", "snapshot.png", photo_bytes, caption)

    def send_audio(self, audio_bytes, caption=""):
        ext = "wav"
        self._send_file("sendAudio", "audio", f"evidence.{ext}", audio_bytes, caption)

    def _send_file(self, method, field, filename, payload, caption=""):
        if not self.enabled or payload is None:
            return
        boundary = uuid.uuid4().hex
        parts = []
        parts.append(f"--{boundary}\r\n"
                     f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
                     f"{self.chat_id}\r\n".encode())
        if caption:
            parts.append(f"--{boundary}\r\n"
                         f'Content-Disposition: form-data; name="caption"\r\n\r\n'
                         f"{caption}\r\n".encode())
        head = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n").encode()
        body = b"".join(parts) + head + payload + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            API.format(token=self.token, method=method),
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            urllib.request.urlopen(req, timeout=TIMEOUT).read()
        except Exception as e:
            print(f"[telegram] {method} failed: {e}")

    def _post(self, method, data):
        req = urllib.request.Request(
            API.format(token=self.token, method=method), data=data
        )
        try:
            urllib.request.urlopen(req, timeout=TIMEOUT).read()
        except Exception as e:
            print(f"[telegram] {method} failed: {e}")

    # ---------- command polling ----------

    def poll_commands(self):
        """New commands from the owner's chat: ['/arm', ...]."""
        if not self.enabled:
            return []
        url = API.format(token=self.token, method="getUpdates") + \
            f"?offset={self.offset + 1}&timeout=0&limit=10"
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
                updates = json.loads(r.read().decode()).get("result", [])
        except Exception as e:
            print(f"[telegram] getUpdates failed: {e}")
            return []
        cmds = []
        for u in updates:
            self.offset = max(self.offset, u.get("update_id", 0))
            msg = u.get("message") or u.get("edited_message") or {}
            if str(msg.get("chat", {}).get("id", "")) != self.chat_id:
                continue
            text = (msg.get("text") or "").strip().lower()
            if text.startswith("/"):
                cmds.append(text.split("@")[0])
        return cmds
