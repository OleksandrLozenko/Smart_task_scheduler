from __future__ import annotations

import math
import struct
import threading
import time
import wave
from pathlib import Path
from tempfile import gettempdir

_qt_effect = None
_qt_effect_ready = False
_alert_wave_path = Path(gettempdir()) / "flowgrid_timer_alert_v2.wav"


def _play_windows_alerts() -> None:
    import winsound

    try:
        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
        # Repeating alternating tones to mimic an alarm clock pattern.
        for _ in range(2):
            for freq, duration in ((1480, 190), (988, 190), (1480, 190), (988, 260)):
                winsound.Beep(freq, duration)
                time.sleep(0.03)
    except RuntimeError:
        for _ in range(4):
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            time.sleep(0.1)


def _ensure_alert_wave() -> Path:
    if _alert_wave_path.exists():
        return _alert_wave_path

    sample_rate = 44100
    frames = bytearray()

    # Alarm-like repeating pattern for clear completion feedback.
    segments = [
        (0.18, 1480.0, 1.0),
        (0.04, 0.0, 0.0),
        (0.18, 988.0, 0.98),
        (0.06, 0.0, 0.0),
        (0.18, 1480.0, 1.0),
        (0.04, 0.0, 0.0),
        (0.24, 988.0, 1.0),
        (0.12, 0.0, 0.0),
        (0.18, 1480.0, 1.0),
        (0.04, 0.0, 0.0),
        (0.18, 988.0, 0.98),
        (0.06, 0.0, 0.0),
        (0.18, 1480.0, 1.0),
        (0.04, 0.0, 0.0),
        (0.28, 988.0, 1.0),
    ]

    for duration, frequency, gain in segments:
        count = int(sample_rate * duration)
        for index in range(count):
            if frequency <= 0.0:
                value = 0
            else:
                # Soft release at tone tail to avoid clicks.
                release = int(count * 0.12)
                if index < count - release:
                    envelope = 1.0
                else:
                    envelope = max(0.0, (count - index) / max(1, release))
                sample = math.sin(2.0 * math.pi * frequency * (index / sample_rate))
                value = int(32767 * 0.72 * gain * envelope * sample)
            frames.extend(struct.pack("<h", value))

    with wave.open(str(_alert_wave_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))

    return _alert_wave_path


def _mark_effect_ready() -> None:
    global _qt_effect_ready
    if _qt_effect is None:
        return

    try:
        from PySide6.QtMultimedia import QSoundEffect
    except Exception:
        return

    if _qt_effect.status() == QSoundEffect.Ready:
        _qt_effect_ready = True


def _play_loaded_effect() -> None:
    if _qt_effect is None or not _qt_effect_ready:
        return
    _qt_effect.stop()
    _qt_effect.play()


def _play_qt_alert() -> bool:
    global _qt_effect

    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtMultimedia import QSoundEffect
    except Exception:
        return False

    if _qt_effect is None:
        try:
            _qt_effect = QSoundEffect()
            _qt_effect.setSource(QUrl.fromLocalFile(str(_ensure_alert_wave())))
            _qt_effect.setLoopCount(1)
            _qt_effect.setVolume(1.0)
            _qt_effect.statusChanged.connect(_mark_effect_ready)
        except Exception:
            _qt_effect = None
            return False

    if _qt_effect_ready:
        _qt_effect.stop()
        _qt_effect.play()
        return True

    # If loading is still in progress, schedule a short delayed play attempt.
    QTimer.singleShot(120, _play_loaded_effect)
    return True


def play_completion_alert() -> None:
    if _play_qt_alert():
        return

    try:
        import winsound  # noqa: F401

        threading.Thread(target=_play_windows_alerts, daemon=True).start()
        return
    except Exception:
        pass

    try:
        from PySide6.QtWidgets import QApplication

        QApplication.beep()
    except Exception:
        pass
