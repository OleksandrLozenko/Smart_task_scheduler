from __future__ import annotations


def format_seconds(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, int(total_seconds)), 60)
    return f"{minutes:02d}:{seconds:02d}"
