"""Viewifi Linux Host — main daemon.

Samples WiFi RSSI, runs the motion engine, raises alarms to Telegram with a
rendered signal snapshot (+ optional webcam photo / mic audio), answers
Telegram commands, syncs with the Android app through Supabase
(geofence arm/disarm, multi-host registry) and logs everything to SQLite.

Usage:
    python3 -m viewifi.main            # run the daemon
    python3 -m viewifi.main --setup    # interactive configuration
    python3 -m viewifi.main --sim      # synthetic signal demo (no WiFi needed)

Install as a 24/7 service: see systemd/viewifi-host.service or ./install.sh
"""

import argparse
import signal
import sys
import threading
import time
from datetime import datetime, timedelta

from . import config as config_mod
from . import evidence
from .engine import MotionEngine, HIGH, LOW, MEDIUM, NONE, now_ms
from .renderer import render_waveform
from .store import EventStore
from .supabase import SupabaseBridge
from .telegram import TelegramBot
from .wifi import WifiSampler

COOLDOWN_MS = 5_000


class ViewifiHost:
    def __init__(self, cfg, sim=False, iface=None, log=print):
        self.log = log
        self.cfg = cfg
        self.engine = MotionEngine(sensitivity=float(cfg["sensitivity"]))
        self.bot = TelegramBot(cfg["telegram_bot_token"], cfg["telegram_chat_id"])
        self.store = EventStore(config_mod.DB_PATH)
        self.sim = sim
        self.sampler = None if sim else WifiSampler(iface)
        self.source_name = "simulación" if sim else getattr(self.sampler, "iface", None) or "wifi"
        self.supabase = SupabaseBridge(
            cfg["supabase_url"], cfg["supabase_anon_key"],
            cfg["supabase_email"], cfg["supabase_password"],
            cfg["device_id"], cfg["device_name"],
        ) if cfg["supabase_url"] else None

        self.running = True
        self.last_alarm_ms = 0
        self.last_rssi = None
        self.wifi_down_since = None
        self._sim_t = 0.0

        # background task scheduling
        self._last_cmd_poll = 0.0
        self._last_sb_poll = 0.0
        self._last_host_hb = 0.0
        self._last_tg_hb = 0.0
        self._last_digest_day = None
        self._last_routine_day = None

    # ---------------- alarm ----------------

    def trigger_alarm(self, level, rssi, variance, connectivity=False):
        now = now_ms()
        zone = self.cfg["zone"]

        if not connectivity and self.cfg["protected_schedule_enabled"]:
            start = int(self.cfg["protected_start_min"])
            end = int(self.cfg["protected_end_min"])
            n = datetime.now()
            now_min = n.hour * 60 + n.minute
            in_window = start <= now_min < end if start <= end else (now_min >= start or now_min < end)
            if in_window and level in (LOW, MEDIUM):
                level = HIGH
            elif not in_window and level != HIGH:
                # outside the window: record silently
                self.store.add(level, rssi, variance, self.engine.classify(), zone, notified=False)
                return

        # cooldown applies to MEDIUM/LOW; HIGH always breaks through
        if level != HIGH and now - self.last_alarm_ms < COOLDOWN_MS:
            return
        self.last_alarm_ms = now

        classification = "Connectivity" if connectivity else self.engine.classify()
        self.store.add(level, rssi, variance, classification, zone, notified=True)
        self.log(f"[{datetime.now():%H:%M:%S}] ALARM {level} rssi={rssi} var={variance:.2f} {classification}")

        if not self.bot.enabled:
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        caption = (
            f"🚨 VIEWIFI — Motion Detected\n"
            f"📍 Zone: {zone} (Linux host: {self.cfg['device_name']})\n"
            f"📶 Level: {level} · Pattern: {classification or 'Unknown'}\n"
            f"📡 Signal: {rssi} dBm · Variance: {variance:.2f}\n"
            f"🕐 {ts}"
        )

        def _deliver():
            try:
                png = render_waveform(
                    self.engine.snapshot(), self.engine.calm_mean,
                    self.engine.sigma or 1.0, self.engine.sensitivity, level)
                self.bot.send_photo(png, caption)
            except Exception as e:
                self.log(f"[alarm] snapshot failed: {e}")
                self.bot.send_message(caption)
            # optional real-world evidence
            if self.cfg["evidence_photo"]:
                photo = evidence.capture_photo()
                if photo:
                    self.bot.send_photo(photo, "📷 Evidence photo / Foto de evidencia")
            if self.cfg["evidence_audio"]:
                audio = evidence.record_audio(5)
                if audio:
                    self.bot.send_audio(audio, "🎙 Evidence audio / Audio de evidencia")

        threading.Thread(target=_deliver, daemon=True).start()

    # ---------------- sampling ----------------

    def _sample(self):
        if self.sim:
            # synthetic scene: mostly calm, a disturbance every ~40s
            import math
            import random
            self._sim_t += 0.25
            base = -62 + math.sin(self._sim_t / 30) * 0.4
            if 38 < self._sim_t % 45 < 43:
                return int(base + random.choice([-6, -7, 5, -5, 6]))
            return int(base + random.choice([0, 0, 1, -1]))
        return self.sampler.sample()

    def run(self):
        self.log("Viewifi Linux host starting…")
        self.log(f"  zone={self.cfg['zone']} device={self.cfg['device_name']} ({self.cfg['device_id'][:8]})")
        self.log(f"  sensitivity={self.engine.sensitivity} interval={self.cfg['sample_interval_ms']}ms")
        if self.sim:
            self.log("  SIMULATION MODE — synthetic RSSI, no WiFi hardware used")
        elif not self.sampler.iface:
            self.log("  WARNING: no WiFi interface found — install `iw` and check the adapter")
        if self.bot.enabled:
            self.bot.send_message(
                f"🟢 VIEWIFI host online: {self.cfg['device_name']} ({self.cfg['zone']})\n"
                f"Commands: /status /arm /disarm /photo /help"
            )

        self.engine.start_calibration()
        self.log("Calibrating for 30s — keep the room still…")

        interval = max(int(self.cfg["sample_interval_ms"]), 200) / 1000.0
        bg = threading.Thread(target=self._background_loop, daemon=True)
        bg.start()

        port = int(self.cfg.get("web_port") or 8080)
        try:
            from .webserver import start_dashboard
            start_dashboard(self, port)
            self.log(f"  Panel web: http://0.0.0.0:{port}  (desde otro equipo: http://<ip-de-este-equipo>:{port})")
        except Exception as e:
            self.log(f"  WARNING: panel web no disponible en puerto {port}: {e}")

        while self.running:
            rssi = self._sample()
            ts = now_ms()
            if rssi is None:
                self._handle_wifi_down()
                time.sleep(1.0)
                continue
            self.wifi_down_since = None
            self.last_rssi = rssi

            variance = 0.0
            if len(self.engine.rssi_buffer) > 1:
                from .engine import std
                variance = std(self.engine.rssi_buffer) ** 2

            prev_state = self.engine.state
            level = self.engine.process(rssi, ts)
            if prev_state != self.engine.state and self.engine.state == "MONITORING":
                self.log(f"Calibration done: baseline={self.engine.baseline:.1f} dBm sigma={self.engine.sigma:.2f}")
                if self.bot.enabled:
                    self.bot.send_message(
                        f"✅ VIEWIFI calibrated — monitoring {self.cfg['zone']}\n"
                        f"Baseline {self.engine.baseline:.1f} dBm · σ {self.engine.sigma:.2f}"
                    )
            if level in (MEDIUM, HIGH):
                self.trigger_alarm(level, rssi, variance)

            time.sleep(interval)

    def _handle_wifi_down(self):
        if self.wifi_down_since is None:
            self.wifi_down_since = time.time()
        # WiFi gone while armed = HIGH connectivity alarm (router unplugged,
        # jamming, power cut) after 10s without a reading
        if time.time() - self.wifi_down_since > 10 and self.engine.state == "MONITORING":
            self.trigger_alarm(HIGH, self.last_rssi or 0, 0.0, connectivity=True)
            self.wifi_down_since = time.time()

    # ---------------- background tasks ----------------

    def _background_loop(self):
        while self.running:
            try:
                self._tick()
            except Exception as e:
                self.log(f"[background] {e}")
            time.sleep(5)

    def _tick(self):
        now = time.time()

        # Telegram commands
        if now - self._last_cmd_poll > 5:
            self._last_cmd_poll = now
            for cmd in self.bot.poll_commands():
                self._handle_command(cmd)

        # Supabase geofence commands + host registry heartbeat
        if self.supabase and self.supabase.enabled:
            if now - self._last_sb_poll > 15:
                self._last_sb_poll = now
                since = self.cfg["last_command_check_ms"] or now_ms()
                for row in self.supabase.poll_commands(since):
                    target = row.get("device_id")
                    if target in (None, "", self.cfg["device_id"]):
                        self._handle_command("/" + row.get("cmd", ""))
                self.cfg["last_command_check_ms"] = now_ms()
                config_mod.save(self.cfg)
            if now - self._last_host_hb > 60:
                self._last_host_hb = now
                self.supabase.heartbeat()

        # Telegram heartbeat
        hb_min = int(self.cfg["heartbeat_minutes"])
        if self.cfg["surveillance"] and hb_min > 0 and now - self._last_tg_hb > hb_min * 60:
            self._last_tg_hb = now
            if self.bot.enabled:
                self.bot.send_message(
                    f"💚 VIEWIFI heartbeat — {self.cfg['device_name']}\n"
                    f"🕐 {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                    f"📡 State: {self.engine.state} · Signal: {self.last_rssi} dBm\n"
                    f"📊 Events today: {self.store.count_today()}"
                )

        # Daily digest + routine watch, right after midnight
        today = datetime.now().date()
        if datetime.now().hour == 0 and self._last_digest_day != today:
            self._last_digest_day = today
            yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            y_ms = int(yesterday.timestamp() * 1000)
            if self.cfg["digest_enabled"] and self.bot.enabled:
                counts = self.store.day_summary(y_ms)
                total = sum(counts.values())
                self.bot.send_message(
                    f"📋 VIEWIFI daily digest — {yesterday:%Y-%m-%d}\n"
                    f"Events: {total} (HIGH {counts.get('HIGH', 0)} · "
                    f"MEDIUM {counts.get('MEDIUM', 0)} · LOW {counts.get('LOW', 0)})"
                )
            if self._last_routine_day != today:
                self._last_routine_day = today
                self._routine_watch(y_ms)

    def _routine_watch(self, y_ms):
        """Yesterday's hourly counts vs the trailing 7-day average."""
        yesterday = self.store.hourly_counts(y_ms)
        week = [self.store.hourly_counts(y_ms - d * 86_400_000) for d in range(1, 8)]
        anomalies = []
        for h in range(24):
            avg = sum(w[h] for w in week) / 7.0
            if yesterday[h] - avg >= 3 and yesterday[h] >= 3:
                anomalies.append(h)
        if anomalies and self.bot.enabled:
            hours = ", ".join(f"{h:02d}:00" for h in anomalies)
            self.bot.send_message(
                f"🧠 VIEWIFI routine watch — unusual activity at: {hours}\n"
                f"(vs your trailing 7-day average)"
            )

    def _handle_command(self, cmd):
        self.log(f"[command] {cmd}")
        if cmd == "/arm":
            self.engine.arm()
            self.bot.send_message(f"🔒 {self.cfg['device_name']} armed")
        elif cmd == "/disarm":
            self.engine.disarm()
            self.bot.send_message(f"🔓 {self.cfg['device_name']} disarmed")
        elif cmd == "/status":
            self.bot.send_message(
                f"📊 {self.cfg['device_name']} — {self.engine.state}\n"
                f"Signal: {self.last_rssi} dBm · Baseline: {self.engine.calm_mean:.1f}\n"
                f"σ: {self.engine.sigma:.2f} · Events today: {self.store.count_today()}"
            )
        elif cmd == "/photo":
            png = render_waveform(
                self.engine.snapshot(), self.engine.calm_mean,
                self.engine.sigma or 1.0, self.engine.sensitivity, "NONE")
            self.bot.send_photo(png, f"📈 {self.cfg['device_name']} signal now: {self.last_rssi} dBm")
        elif cmd == "/help":
            self.bot.send_message(
                "Viewifi commands:\n"
                "/status — state and stats\n/arm — arm monitoring\n"
                "/disarm — disarm\n/photo — current signal chart"
            )

    def apply_config(self):
        """Re-aplica la configuración editada desde el panel web."""
        self.bot = TelegramBot(self.cfg["telegram_bot_token"], self.cfg["telegram_chat_id"])
        self.engine.sensitivity = float(self.cfg["sensitivity"])

    def stop(self):
        self.running = False


def main():
    parser = argparse.ArgumentParser(prog="viewifi-host", description="Viewifi Linux host")
    parser.add_argument("--setup", action="store_true", help="interactive configuration wizard")
    parser.add_argument("--sim", action="store_true", help="synthetic signal demo (no WiFi needed)")
    parser.add_argument("--iface", help="WiFi interface (autodetected by default)")
    args = parser.parse_args()

    if args.setup:
        config_mod.setup_wizard()
        return

    cfg = config_mod.load()
    host = ViewifiHost(cfg, sim=args.sim, iface=args.iface)

    def _sigterm(*_):
        print("\nStopping Viewifi host…")
        host.stop()

    signal.signal(signal.SIGINT, _sigterm)
    signal.signal(signal.SIGTERM, _sigterm)
    host.run()


if __name__ == "__main__":
    main()
