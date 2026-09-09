"""Configuration: ~/.viewifi/config.json with an interactive --setup wizard.

Only the Telegram token/chat_id are needed for local alerts; the Supabase
block enables the geofence commands and multi-host pairing with the app.
"""

import json
import os
import uuid

CONFIG_DIR = os.path.expanduser("~/.viewifi")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DB_PATH = os.path.join(CONFIG_DIR, "events.db")

DEFAULTS = {
    "zone": "Home",
    "sensitivity": 2.5,
    "sample_interval_ms": 250,
    "surveillance": True,
    "heartbeat_minutes": 60,
    "digest_enabled": False,
    "digest_hour": 8,
    "protected_schedule_enabled": False,
    "protected_start_min": 0,
    "protected_end_min": 360,
    "evidence_photo": False,
    "evidence_audio": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "supabase_url": "",
    "supabase_anon_key": "",
    "supabase_email": "",
    "supabase_password": "",
    "device_name": "Linux Host",
    "device_id": "",
    "last_command_check_ms": 0,
}


def load():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"[config] could not read {CONFIG_PATH}: {e}")
    if not cfg["device_id"]:
        cfg["device_id"] = str(uuid.uuid4())
        save(cfg)
    return cfg


def save(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)


def setup_wizard():
    cfg = load()
    print("Viewifi host setup (Enter keeps the current value)\n")

    def ask(key, label, secret=False):
        cur = cfg.get(key, "")
        shown = ("*" * 8 if secret and cur else cur)
        val = input(f"{label} [{shown}]: ").strip()
        if val:
            cfg[key] = val

    ask("zone", "Zone name (e.g. Living room)")
    ask("device_name", "This host's display name")
    ask("sensitivity", "Sensitivity (0.5 - 5.0, lower = more sensitive)")
    cfg["sensitivity"] = float(cfg["sensitivity"])
    ask("telegram_bot_token", "Telegram bot token (from @BotFather)", secret=True)
    ask("telegram_chat_id", "Telegram chat ID")
    print("\nSupabase (optional — geofence + multi-host with the Android app):")
    ask("supabase_url", "  Project URL", secret=False)
    ask("supabase_anon_key", "  Anon key", secret=True)
    ask("supabase_email", "  Account email")
    ask("supabase_password", "  Account password", secret=True)
    print("\nEvidence (requires fswebcam/arecord installed):")
    for key, label in (("evidence_photo", "  Capture photo on alarm? (y/n)"),
                       ("evidence_audio", "  Record audio clip on alarm? (y/n)")):
        val = input(f"{label} [{'y' if cfg[key] else 'n'}]: ").strip().lower()
        if val:
            cfg[key] = val.startswith("y")
    save(cfg)
    print(f"\nSaved to {CONFIG_PATH}")
    return cfg
