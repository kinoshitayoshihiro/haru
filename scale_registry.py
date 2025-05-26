# scale_registry.py – Revised 2025-05-27
# ------------------------------------------------------------
# Centralised factory for returning music21 scale objects based on
# a (tonic, mode) tuple.  Handles renamed and missing classes
# (Pentatonic → Major/MinorPentatonicScale, optional Blues/WholeTone/Octatonic)
# with graceful fallbacks and legacy aliases.
# ------------------------------------------------------------
from __future__ import annotations
from functools import lru_cache
from typing import Dict, Callable

from music21 import scale, pitch

__all__ = [
    "get",
    "ScaleRegistry",
    "build_scale_object",
]

# ---------------------------------------------------------------------
# _resolve_scale_class
#   Normalize mode string and map to available music21 Scale classes,
#   using getattr fallbacks where classes may not exist.
# ---------------------------------------------------------------------

def _resolve_scale_class(mode: str) -> Callable[[pitch.Pitch], scale.ConcreteScale]:
    mode_lc = mode.lower()
    _mapping: Dict[str, Callable[[pitch.Pitch], scale.ConcreteScale]] = {
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
        # pentatonic
        "majorpentatonic": getattr(scale, "MajorPentatonicScale", getattr(scale, "PentatonicScale", scale.MajorScale)),
        "minorpentatonic": getattr(scale, "MinorPentatonicScale", scale.MinorScale),
        "pentatonic": getattr(scale, "MajorPentatonicScale", getattr(scale, "PentatonicScale", scale.MajorScale)),
        # blues / whole-tone / octatonic with fallbacks
        "blues": getattr(scale, "BluesScale", getattr(scale, "MinorPentatonicScale", scale.MinorScale)),
        "wholetone": getattr(scale, "WholeToneScale", scale.MajorScale),
        "octatonic": getattr(scale, "OctatonicScale", scale.WholeToneScale),
    }

    if mode_lc not in _mapping:
        raise ValueError(f"Unsupported mode name: {mode}")
    return _mapping[mode_lc]

# ---------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------

@lru_cache(maxsize=128)
def get(tonic: str | pitch.Pitch, mode: str = "major") -> scale.ConcreteScale:
    """Return a singleton music21 Scale instance for the given tonic + mode."""
    tonic_pitch = pitch.Pitch(tonic)
    scale_cls = _resolve_scale_class(mode)
    return scale_cls(tonic_pitch)

# ---------------------------------------------------------------------
# legacy aliases
# ---------------------------------------------------------------------

ScaleRegistry = get
setattr(ScaleRegistry, "get", get)

def build_scale_object(tonic: str | pitch.Pitch, mode: str = "major") -> scale.ConcreteScale:
    """Backward‑compat shim for old code."""
    return get(tonic, mode)
