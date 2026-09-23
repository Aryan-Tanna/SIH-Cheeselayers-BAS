"""Severity earcons, synthesized in code -- no audio files to ship.

numpy is imported inside functions, not at module scope: it arrives with
the optional extras, and src/ must import cleanly on a core-only install
(see pyproject.toml).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Short linear fade on each note edge. Without it a sine that starts or
# stops mid-cycle clicks audibly, which reads as a glitch, not a signal.
_FADE_MS = 8.0


@dataclass(frozen=True, slots=True)
class EarconSpec:
    notes_hz: tuple[float, ...]
    note_ms: float
    gap_ms: float

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "EarconSpec":
        notes = tuple(float(f) for f in cfg["notes_hz"])
        if not notes:
            raise ValueError("earcon notes_hz must not be empty")
        return cls(notes_hz=notes, note_ms=float(cfg["note_ms"]), gap_ms=float(cfg.get("gap_ms", 0)))


def render_earcon(spec: EarconSpec, sample_rate: int) -> Any:
    """Mono float32 samples in [-1, 1]."""
    import numpy as np

    n_note = max(1, int(sample_rate * spec.note_ms / 1000.0))
    n_gap = int(sample_rate * spec.gap_ms / 1000.0)
    n_fade = min(n_note // 2, int(sample_rate * _FADE_MS / 1000.0))

    envelope = np.ones(n_note, dtype=np.float32)
    if n_fade > 0:
        ramp = np.linspace(0.0, 1.0, n_fade, dtype=np.float32)
        envelope[:n_fade] = ramp
        envelope[-n_fade:] = ramp[::-1]

    t = np.arange(n_note, dtype=np.float32) / sample_rate
    parts = []
    for i, hz in enumerate(spec.notes_hz):
        if i > 0 and n_gap > 0:
            parts.append(np.zeros(n_gap, dtype=np.float32))
        # 0.6 peak leaves headroom so a tone never clips after gain.
        parts.append((0.6 * np.sin(2 * np.pi * hz * t) * envelope).astype(np.float32))
    return np.concatenate(parts)
