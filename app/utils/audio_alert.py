from __future__ import annotations

import math
import struct
import threading
import time
import wave
from pathlib import Path
from tempfile import gettempdir

SOUND_WAVE_VERSION = "v3_long"


def _repeat_segments(
    motif: list[tuple[float, float, float, float]],
    repeats: int,
    *,
    gap_seconds: float = 0.16,
) -> list[tuple[float, float, float, float]]:
    output: list[tuple[float, float, float, float]] = []
    loops = max(1, int(repeats))
    for idx in range(loops):
        output.extend(motif)
        if idx < loops - 1 and gap_seconds > 0:
            output.append((float(gap_seconds), 0.0, 0.0, 0.0))
    return output


SOUND_PRESETS: dict[str, dict[str, object]] = {
    "alarm_classic": {
        "label": "Классический будильник",
        "segments": _repeat_segments(
            [
                (0.22, 1480.0, 1480.0, 1.0),
                (0.07, 0.0, 0.0, 0.0),
                (0.24, 988.0, 988.0, 0.98),
                (0.08, 0.0, 0.0, 0.0),
                (0.26, 1480.0, 1480.0, 1.0),
                (0.10, 0.0, 0.0, 0.0),
                (0.30, 988.0, 988.0, 1.0),
            ],
            3,
            gap_seconds=0.18,
        ),
    },
    "soft_chime": {
        "label": "Мягкий колокольчик",
        "segments": _repeat_segments(
            [
                (0.34, 698.0, 698.0, 0.76),
                (0.10, 0.0, 0.0, 0.0),
                (0.36, 880.0, 880.0, 0.72),
                (0.12, 0.0, 0.0, 0.0),
                (0.40, 1174.0, 1174.0, 0.68),
            ],
            3,
            gap_seconds=0.22,
        ),
    },
    "digital": {
        "label": "Цифровой пульс",
        "segments": _repeat_segments(
            [
                (0.14, 1680.0, 1680.0, 0.94),
                (0.06, 0.0, 0.0, 0.0),
                (0.14, 1680.0, 1680.0, 0.94),
                (0.07, 0.0, 0.0, 0.0),
                (0.14, 1320.0, 1320.0, 0.92),
                (0.07, 0.0, 0.0, 0.0),
                (0.18, 1680.0, 1680.0, 0.95),
                (0.15, 0.0, 0.0, 0.0),
            ],
            4,
            gap_seconds=0.0,
        ),
    },
    "bell": {
        "label": "Колокол",
        "segments": _repeat_segments(
            [
                (0.42, 1240.0, 980.0, 0.94),
                (0.12, 0.0, 0.0, 0.0),
                (0.44, 1240.0, 860.0, 0.86),
                (0.12, 0.0, 0.0, 0.0),
                (0.50, 1240.0, 720.0, 0.80),
            ],
            2,
            gap_seconds=0.26,
        ),
    },
    "ascending": {
        "label": "Восходящий сигнал",
        "segments": _repeat_segments(
            [
                (0.22, 620.0, 860.0, 0.86),
                (0.06, 0.0, 0.0, 0.0),
                (0.22, 860.0, 1120.0, 0.90),
                (0.06, 0.0, 0.0, 0.0),
                (0.24, 1120.0, 1420.0, 0.94),
                (0.06, 0.0, 0.0, 0.0),
                (0.28, 1420.0, 1840.0, 1.0),
                (0.14, 0.0, 0.0, 0.0),
            ],
            3,
            gap_seconds=0.22,
        ),
    },
}

_qt_effects: dict[str, object] = {}
_qt_effect_ready: set[str] = set()
_wave_paths: dict[str, Path] = {}


def available_timer_sounds() -> tuple[tuple[str, str], ...]:
    return tuple((sound_id, str(meta["label"])) for sound_id, meta in SOUND_PRESETS.items())


def _normalize_sound_id(sound_id: str) -> str:
    if sound_id in SOUND_PRESETS:
        return sound_id
    return "alarm_classic"


def _sound_wave_path(sound_id: str) -> Path:
    if sound_id in _wave_paths:
        return _wave_paths[sound_id]
    path = Path(gettempdir()) / f"flowgrid_timer_{sound_id}_{SOUND_WAVE_VERSION}.wav"
    _wave_paths[sound_id] = path
    return path


def _append_segment(
    frames: bytearray,
    *,
    sample_rate: int,
    duration: float,
    freq_start: float,
    freq_end: float,
    gain: float,
) -> None:
    count = max(1, int(sample_rate * duration))
    if freq_start <= 0.0 and freq_end <= 0.0:
        frames.extend(b"\x00\x00" * count)
        return

    attack = max(1, int(sample_rate * 0.01))
    release = max(1, int(sample_rate * 0.025))
    phase = 0.0
    for index in range(count):
        t = index / max(1, count - 1)
        frequency = freq_start + (freq_end - freq_start) * t
        phase += (2.0 * math.pi * frequency) / sample_rate
        if index < attack:
            envelope = index / attack
        elif index > count - release:
            envelope = max(0.0, (count - index) / release)
        else:
            envelope = 1.0
        sample = math.sin(phase)
        value = int(32767 * 0.74 * gain * envelope * sample)
        frames.extend(struct.pack("<h", value))


def _ensure_alert_wave(sound_id: str) -> Path:
    normalized = _normalize_sound_id(sound_id)
    path = _sound_wave_path(normalized)
    if path.exists():
        return path

    sample_rate = 44100
    frames = bytearray()
    preset = SOUND_PRESETS[normalized]
    for duration, freq_start, freq_end, gain in preset["segments"]:  # type: ignore[index]
        _append_segment(
            frames,
            sample_rate=sample_rate,
            duration=float(duration),
            freq_start=float(freq_start),
            freq_end=float(freq_end),
            gain=float(gain),
        )

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))
    return path


def _windows_pattern(sound_id: str) -> tuple[list[tuple[int, int]], int, float]:
    sid = _normalize_sound_id(sound_id)
    if sid == "soft_chime":
        return ([(698, 340), (880, 360), (1174, 420)], 3, 0.20)
    if sid == "digital":
        return ([(1680, 140), (1680, 140), (1320, 140), (1680, 180)], 4, 0.14)
    if sid == "bell":
        return ([(1240, 420), (980, 430), (860, 500)], 2, 0.24)
    if sid == "ascending":
        return ([(620, 220), (860, 220), (1120, 240), (1420, 280), (1840, 300)], 3, 0.20)
    return ([(1480, 220), (988, 240), (1480, 260), (988, 300)], 3, 0.18)


def _play_windows_alerts(sound_id: str) -> None:
    import winsound

    try:
        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
        pattern, repeats, gap = _windows_pattern(sound_id)
        loops = max(1, int(repeats))
        for repeat_idx in range(loops):
            for freq, duration in pattern:
                winsound.Beep(freq, duration)
                time.sleep(0.03)
            if repeat_idx < loops - 1 and gap > 0:
                time.sleep(gap)
    except RuntimeError:
        for _ in range(3):
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            time.sleep(0.18)


def _mark_effect_ready(sound_id: str) -> None:
    effect = _qt_effects.get(sound_id)
    if effect is None:
        return
    try:
        from PySide6.QtMultimedia import QSoundEffect
    except Exception:
        return

    status = effect.status()
    if status == QSoundEffect.Ready:
        _qt_effect_ready.add(sound_id)
    elif status == QSoundEffect.Error:
        _qt_effect_ready.discard(sound_id)


def _play_loaded_effect(sound_id: str) -> None:
    effect = _qt_effects.get(sound_id)
    if effect is None or sound_id not in _qt_effect_ready:
        return
    effect.stop()
    effect.play()


def _play_qt_alert(sound_id: str, volume_percent: int) -> bool:
    normalized_sound = _normalize_sound_id(sound_id)
    volume = max(0.0, min(1.0, int(volume_percent) / 100.0))

    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtMultimedia import QSoundEffect
    except Exception:
        return False

    effect = _qt_effects.get(normalized_sound)
    if effect is None:
        try:
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(str(_ensure_alert_wave(normalized_sound))))
            effect.setLoopCount(1)
            effect.statusChanged.connect(
                lambda sid=normalized_sound: _mark_effect_ready(sid)  # noqa: B023
            )
            _qt_effects[normalized_sound] = effect
        except Exception:
            _qt_effects.pop(normalized_sound, None)
            return False

    effect.setVolume(volume)
    if effect.status() == QSoundEffect.Error:
        return False

    if normalized_sound in _qt_effect_ready or effect.status() == QSoundEffect.Ready:
        _qt_effect_ready.add(normalized_sound)
        effect.stop()
        effect.play()
        return True

    QTimer.singleShot(120, lambda sid=normalized_sound: _play_loaded_effect(sid))
    return True


def _play_fallback_beep(sound_id: str) -> None:
    try:
        import winsound  # noqa: F401

        threading.Thread(target=_play_windows_alerts, args=(sound_id,), daemon=True).start()
        return
    except Exception:
        pass

    try:
        from PySide6.QtWidgets import QApplication

        for _ in range(3):
            QApplication.beep()
            time.sleep(0.2)
    except Exception:
        pass


def play_completion_alert(sound_id: str = "alarm_classic", volume_percent: int = 90) -> None:
    if _play_qt_alert(sound_id, volume_percent):
        return
    _play_fallback_beep(sound_id)


def preview_completion_alert(sound_id: str = "alarm_classic", volume_percent: int = 90) -> None:
    play_completion_alert(sound_id=sound_id, volume_percent=volume_percent)
