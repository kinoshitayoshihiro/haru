import logging
import re
from typing import Optional, Dict, Any

from music21 import meter, pitch, scale, harmony

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    ts_str = ts_str or "4/4"
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning("GTSO: Invalid time‑signature '%s'. Defaulting to 4/4.", ts_str)
        return meter.TimeSignature("4/4")
    except Exception as exc:
        logger.error("GTSO: Unexpected error for TS '%s': %s. Defaulting to 4/4.", ts_str, exc)
        return meter.TimeSignature("4/4")

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> scale.ConcreteScale:
    mode_key = (mode_str or "major").lower()
    tonic_val = tonic_str or "C"
    try:
        tonic_p = pitch.Pitch(tonic_val)
    except Exception:
        logger.error("BuildScale: Invalid tonic '%s'. Defaulting to C.", tonic_val)
        tonic_p = pitch.Pitch("C")
    mode_map: Dict[str, Any] = {
        "ionian": scale.MajorScale,
        "major": scale.MajorScale,
        "dorian": scale.DorianScale,
        "phrygian": scale.PhrygianScale,
        "lydian": scale.LydianScale,
        "mixolydian": scale.MixolydianScale,
        "aeolian": scale.MinorScale,
        "minor": scale.MinorScale,
        "locrian": scale.LocrianScale,
        "harmonicminor": scale.HarmonicMinorScale,
        "melodicminor": scale.MelodicMinorScale,
    }
    scl_cls = mode_map.get(mode_key, scale.MajorScale)
    if scl_cls is scale.MajorScale and mode_key not in mode_map:
        logger.warning("BuildScale: Unknown mode '%s'. Using MajorScale.", mode_key)
    try:
        return scl_cls(tonic_p)
    except Exception as exc:
        logger.error("BuildScale: Could not instantiate %s with tonic %s – %s. Falling back to C major.",
                     scl_cls.__name__, tonic_p, exc)
        return scale.MajorScale(pitch.Pitch("C"))

def _expand_tension_block(seg: str) -> str:
    """Normalize a single tension fragment for music21."""
    if seg.startswith(("#", "b", "add")):
        return seg
    return f"add{seg}"

def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    if not label or not isinstance(label, str):
        return None
    sanitized = label.strip()

    if sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        return None

    # fix dangling '('
    if '(' in sanitized and ')' not in sanitized:
        sanitized = sanitized.split('(')[0]

    # root / bass flats
    sanitized = re.sub(r'^([A-G])b', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-G])b', r'/\1-', sanitized)

    # alt expansion
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt', r'\g<1>7#9b13', sanitized, flags=re.I)

    # flatten parentheses
    while '(' in sanitized and ')' in sanitized:
        base, inner, suf = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized).groups()
        inner_flat = ''.join(_expand_tension_block(s.strip()) for s in inner.split(','))
        sanitized = base + inner_flat + suf

    # addX stays
    sanitized = re.sub(r'add(\d+)', r'add\1', sanitized, flags=re.I)

    # sus duplication
    sanitized = re.sub(r'sus([24])\1$', r'sus\1', sanitized, flags=re.I)

    # maj9#11 → maj7#11add9
    sanitized = re.sub(r'(maj)9(#\d+)', r'\g<1>7\2add9', sanitized, flags=re.I)

    # duplicate digit guard
    sanitized = re.sub(r'add(\d)(?=\1)', '', sanitized)

    sanitized = re.sub(r'[ ,]', '', sanitized)

    try:
        harmony.ChordSymbol(sanitized)
    except Exception as exc:
        logger.warning("sanitize: '%s' problematic – %s", sanitized, exc)
    return sanitized
