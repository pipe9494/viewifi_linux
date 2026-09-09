"""Viewifi motion detection engine — Python port of the Android engine.

Identical tuned logic to MotionDetectionEngine.kt (v1.1+):
- EWMA calm baseline (mean + deviation), learned ONLY from calm samples
- short-window (12 samples) z-score spike test + per-hour baselines
- debounce: 3 consecutive elevated samples to trigger
- hysteresis: 3 calm samples to release
- sigma floor 0.8 dBm (RSSI is integer-quantized)

States: IDLE / CALIBRATING / MONITORING.
Levels: NONE / LOW / MEDIUM / HIGH.

Run `python3 -m viewifi.engine` for the built-in self-test (7 scenarios).
"""

import math
import time
from collections import deque
from datetime import datetime

BUFFER = 100
CALIBRATION_MS = 30_000
MIN_SIGMA = 0.8
WIN = 12
HITS = 3
RELEASE = 3
ALPHA = 0.05
MIN_HOUR_SAMPLES = 30

IDLE, CALIBRATING, MONITORING = "IDLE", "CALIBRATING", "MONITORING"
NONE, LOW, MEDIUM, HIGH = "NONE", "LOW", "MEDIUM", "HIGH"


class MotionEngine:
    def __init__(self, sensitivity=2.5):
        self.sensitivity = sensitivity
        self.state = IDLE
        self.rssi_buffer = deque(maxlen=BUFFER)
        self.dev_window = deque(maxlen=WIN)
        self.hour_sum = [0.0] * 24
        self.hour_sq = [0.0] * 24
        self.hour_n = [0] * 24
        self.elevated_run = 0
        self.calm_run = 0
        self.calm_mean = 0.0
        self.calm_dev = 0.0
        self.calibrated = False
        self.baseline = 0.0
        self.sigma = 0.0  # live effective baseline sigma (for rendering)
        self.calib_start = 0.0

    # ---------------- lifecycle ----------------

    def start_calibration(self):
        self.reset()
        self.state = CALIBRATING
        self.calib_start = now_ms()

    def arm(self):
        if self.state != IDLE:
            return
        if self.calibrated:
            self.state = MONITORING
        else:
            self.start_calibration()

    def disarm(self):
        self.state = IDLE

    def reset(self):
        self.state = IDLE
        self.rssi_buffer.clear()
        self.dev_window.clear()
        self.hour_sum = [0.0] * 24
        self.hour_sq = [0.0] * 24
        self.hour_n = [0] * 24
        self.elevated_run = 0
        self.calm_run = 0
        self.calm_mean = 0.0
        self.calm_dev = 0.0
        self.calibrated = False
        self.baseline = 0.0
        self.sigma = 0.0

    # ---------------- core ----------------

    def process(self, rssi, ts=None):
        """Feed one RSSI reading. Returns the motion level string."""
        ts = ts if ts is not None else now_ms()
        self.rssi_buffer.append(rssi)

        if self.state == CALIBRATING:
            self._accumulate_hourly(rssi, ts)
            if ts - self.calib_start >= CALIBRATION_MS and len(self.rssi_buffer) > 2:
                self.baseline = mean(self.rssi_buffer)
                self.sigma = max(std(self.rssi_buffer), MIN_SIGMA)
                self.calibrated = True
                self.calm_mean = self.baseline
                self.calm_dev = self.sigma
                self.state = MONITORING
            return NONE

        if self.state != MONITORING:
            return NONE

        base_sigma = max(self._hour_std() or self.calm_dev or MIN_SIGMA, MIN_SIGMA)
        dev = abs(rssi - self.calm_mean)
        z = dev / base_sigma
        self.dev_window.append(dev)
        wsd = std(self.dev_window)
        wz = wsd / base_sigma

        # Current sample must itself be perturbed; the window test can only
        # trigger when the current sample also deviates a little.
        elevated = z > self.sensitivity * 0.6 or (wz > self.sensitivity and z > 1.5)

        if elevated:
            self.elevated_run += 1
            self.calm_run = 0
        else:
            self.calm_run += 1
            if self.calm_run >= RELEASE:
                self.elevated_run = 0

        level = NONE
        if self.elevated_run >= HITS and self.calibrated:
            ratio = max(z, wz * 0.9) / max(self.sensitivity, 0.001)
            level = HIGH if ratio >= 4.0 else MEDIUM if ratio >= 2.0 else LOW

        if not elevated:
            # Learn only from calm samples — motion must not inflate the
            # threshold and hide itself later.
            self._accumulate_hourly(rssi, ts)
            self.calm_mean = self.calm_mean * (1 - ALPHA) + rssi * ALPHA
            self.calm_dev = self.calm_dev * (1 - ALPHA) + dev * ALPHA
            self.sigma = base_sigma

        return level

    # ---------------- helpers ----------------

    def _accumulate_hourly(self, rssi, ts):
        h = datetime.fromtimestamp(ts / 1000).hour
        self.hour_sum[h] += rssi
        self.hour_sq[h] += float(rssi) * rssi
        self.hour_n[h] += 1

    def _hour_std(self):
        h = datetime.now().hour
        n = self.hour_n[h]
        if n < MIN_HOUR_SAMPLES:
            return None
        m = self.hour_sum[h] / n
        var = self.hour_sq[h] / n - m * m
        return math.sqrt(max(var, 0.0))

    def snapshot(self):
        return list(self.rssi_buffer)

    def classify(self):
        """Heuristic pattern: Rhythmic / Pet-like / Human-like / ''."""
        values = list(self.rssi_buffer)
        if len(values) < 8:
            return ""
        m = mean(values)
        sd = max(std(values), 0.001)
        rel_amp = sd / max(self.sigma, 0.5)
        # zero-crossing interval regularity
        intervals = []
        prev_t = None
        prev_sign = 0
        for v in values:
            d = v - m
            sign = 1 if d > sd * 0.3 else -1 if d < -sd * 0.3 else 0
            if sign and sign != prev_sign and prev_sign:
                if prev_t is not None:
                    intervals.append(1)  # coarse: sample count between crossings
                prev_t = 0
            elif prev_t is not None:
                prev_t += 1
            if sign:
                prev_sign = sign
        if len(intervals) < 3:
            return "Human-like"
        avg = sum(intervals) / len(intervals)
        cv = math.sqrt(sum((i - avg) ** 2 for i in intervals) / len(intervals)) / max(avg, 1)
        if cv < 0.35 and len(intervals) >= 4:
            return "Rhythmic"
        if rel_amp < 3.0:
            return "Pet-like"
        return "Human-like"


def now_ms():
    return int(time.time() * 1000)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def std(xs):
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


# ---------------- self-test ----------------

def _selftest():
    def calm(n, base=-62, jitter=(0, 0, 1, 0, -1)):
        return [base + jitter[i % len(jitter)] for i in range(n)]

    scenarios = [
        ("frozen signal 60s", [-62] * 120, False),
        ("normal ±1dBm drift", calm(240), False),
        ("brief crossing 5s", calm(40) + [-66, -68, -65, -64, -67, -66, -68, -65, -64, -66] + calm(40), True),
        ("1s bounce", calm(40) + [-70, -69] + calm(40), False),
        ("prolonged presence", calm(40) + [-62 + (-6 if i % 3 == 0 else 5 if i % 3 == 1 else -4) for i in range(60)] + calm(20), True),
        ("slow thermal drift", [-62 - i // 75 for i in range(600)], False),
        ("motion after drift", [-62 - i // 150 for i in range(300)] + [-70, -73, -71, -74, -72] + calm(20, -67), True),
    ]
    ok = True
    for name, samples, expect in scenarios:
        e = MotionEngine()
        # simulate calibration first
        e.state = CALIBRATING
        e.calib_start = 0
        for i, s in enumerate(samples):
            e.process(s, ts=40_000 + i * 500)  # pretend calibration done
        hits = []
        e2 = MotionEngine()
        e2.calm_mean = -62.0 if "after drift" not in name else -64.0
        e2.calm_dev = 0.4
        e2.calibrated = True
        e2.state = MONITORING
        for s in samples:
            lv = e2.process(s)
            if lv != NONE:
                hits.append(lv)
        detected = bool(hits)
        passed = detected == expect
        ok &= passed
        print(f"{'PASS' if passed else 'FAIL'}  {name} -> {'DETECTED' if detected else 'clean'}")
    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
