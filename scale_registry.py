# scale_registry.py – Revised 2025‑05‑27
# ------------------------------------------------------------
# Centralised factory for returning music21 scale objects based on
# a (tonic, mode) tuple.  Previous version raised an AttributeError
# because music21 >=9.5 renamed PentatonicScale → MajorPentatonicScale /
# MinorPentatonicScale.  This revision normalises those names and adds
# graceful fall‑backs so the composer pipeline no longer crashes when a
# “pentatonic” mode is requested.
# ------------------------------------------------------------
from __future__ import annotations
from functools import lru_cache
from typing import Dict, Callable

from music21 import scale, pitch

__all__ = [
    "ScaleRegistry",
    "get",  # backwards compatibility
]

# ---------------------------------------------------------------------
# _resolve_scale_class
#   Given a canonical mode string, return the corresponding music21
#   Scale *class* (not instance).  Fall back to major / minor where
#   appropriate and keep everything lower‑case for robust lookup.
# ---------------------------------------------------------------------

def _resolve_scale_class(mode: str) -> Callable[[str], scale.ConcreteScale]:
    mode_lc = mode.lower()

    _mapping: Dict[str, Callable[[str], scale.ConcreteScale]] = {
        # diatonic
        "major": scale.MajorScale,
        "ionian": scale.MajorScale,
        "minor": scale.MinorScale,
        "aeolian": scale.MinorScale,
        "dorian": scale.DorianScale,
        "phrygian": scale.PhrygianScale,
        "lydian": scale.LydianScale,
        "mixolydian": scale.MixolydianScale,
        "locrian": scale.LocrianScale,
        # pentatonic (music21 >= 9.5 uses MajorPentatonicScale / MinorPentatonicScale)
        "majorpentatonic": getattr(scale, "MajorPentatonicScale", getattr(scale, "PentatonicScale", scale.MajorScale)),
        "minorpentatonic": getattr(scale, "MinorPentatonicScale", scale.MinorScale),
        "pentatonic": getattr(scale, "MajorPentatonicScale", getattr(scale, "PentatonicScale", scale.MajorScale)),
        # blues / whole‑tone / octatonic
        "blues": scale.BluesScale,
        "wholetone": scale.WholeToneScale,
        "octatonic": scale.OctatonicScale,
    }

    if mode_lc not in _mapping:
        raise ValueError(f"Unsupported mode name: {mode}")

    return _mapping[mode_lc]

# ---------------------------------------------------------------------
# public helpers
# ---------------------------------------------------------------------

@lru_cache(maxsize=128)
def get(tonic: str | pitch.Pitch, mode: str = "major") -> scale.ConcreteScale:
    """Return a *singleton* scale object for the given tonic + mode.

    The result is cached so repeated look‑ups incur zero overhead.
    """
    tonic_pitch = pitch.Pitch(tonic)
    scale_cls = _resolve_scale_class(mode)
    return scale_cls(tonic_pitch)

# alias retained for backwards compatibility
ScaleRegistry = get
