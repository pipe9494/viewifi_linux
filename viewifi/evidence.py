"""Optional real-world evidence capture — best effort, zero hard deps.

Photo: `fswebcam` or `ffmpeg` against /dev/video0 (USB webcam / Pi Camera).
Audio: `arecord` (ALSA, present on Raspberry Pi OS).

Both return bytes or None when the tool or device is missing.
"""

import shutil
import subprocess


def capture_photo():
    """JPEG bytes from the default webcam, or None."""
    if shutil.which("fswebcam"):
        try:
            out = subprocess.run(
                ["fswebcam", "-d", "/dev/video0", "-r", "1280x720",
                 "--no-banner", "-q", "-"],  # "-" writes JPEG to stdout
                capture_output=True, timeout=20,
            )
            if out.returncode == 0 and len(out.stdout) > 1000:
                return out.stdout
        except Exception:
            pass
    if shutil.which("ffmpeg"):
        try:
            out = subprocess.run(
                ["ffmpeg", "-f", "v4l2", "-frames:v", "1", "-i", "/dev/video0",
                 "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                capture_output=True, timeout=20,
            )
            if out.returncode == 0 and len(out.stdout) > 1000:
                return out.stdout
        except Exception:
            pass
    return None


def record_audio(seconds=5):
    """WAV bytes from the default ALSA mic, or None."""
    if not shutil.which("arecord"):
        return None
    try:
        out = subprocess.run(
            ["arecord", "-d", str(seconds), "-f", "cd", "-t", "wav", "-q", "-"],
            capture_output=True, timeout=seconds + 10,
        )
        if out.returncode == 0 and len(out.stdout) > 1000:
            return out.stdout
    except Exception:
        pass
    return None
