"""WiFi RSSI sampling on Linux.

Sources, in order of preference:
1. `iw dev <iface> link`  -> "signal: -55 dBm"  (best, per-station)
2. /proc/net/wireless     -> level column (dBm when the driver reports it)
3. `iwconfig <iface>`     -> Signal level=-55 dBm  (legacy fallback)

`sample()` returns an int dBm or None when WiFi is down/unreadable.
"""

import os
import re
import subprocess

_IW_SIGNAL = re.compile(r"signal:\s*(-?\d+)\s*dBm")
_IWCONFIG_SIGNAL = re.compile(r"Signal level=(-?\d+)\s*dBm")


def find_interface():
    """First wireless interface reported by `iw dev`, or from /sys."""
    try:
        out = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True, timeout=5
        ).stdout
        m = re.findall(r"Interface\s+(\S+)", out)
        if m:
            return m[0]
    except Exception:
        pass
    try:
        for name in sorted(os.listdir("/sys/class/net")):
            if os.path.isdir(f"/sys/class/net/{name}/wireless"):
                return name
    except Exception:
        pass
    return None


class WifiSampler:
    def __init__(self, iface=None):
        self.iface = iface or find_interface()

    def sample(self):
        """Current RSSI in dBm, or None when unavailable."""
        if not self.iface:
            return None
        v = self._iw_link()
        if v is None:
            v = self._proc_net_wireless()
        if v is None:
            v = self._iwconfig()
        return v

    def _iw_link(self):
        try:
            out = subprocess.run(
                ["iw", "dev", self.iface, "link"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            m = _IW_SIGNAL.search(out)
            return int(m.group(1)) if m else None
        except Exception:
            return None

    def _proc_net_wireless(self):
        try:
            with open("/proc/net/wireless") as f:
                for line in f.readlines()[2:]:
                    parts = line.split()
                    if parts and parts[0].rstrip(":") == self.iface:
                        # columns: iface status link level noise ...
                        level = parts[3].rstrip(".")
                        return int(float(level))  # dBm when negative
        except Exception:
            return None
        return None

    def _iwconfig(self):
        try:
            out = subprocess.run(
                ["iwconfig", self.iface], capture_output=True, text=True, timeout=5
            ).stdout
            m = _IWCONFIG_SIGNAL.search(out)
            return int(m.group(1)) if m else None
        except Exception:
            return None
