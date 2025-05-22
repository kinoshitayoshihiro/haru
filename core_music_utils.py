import logging
import re
import random
from typing import Optional, Dict, Any

from music21 import meter, pitch, scale, harmony

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global constants
# ---------------------------------------------------------------------------
MIN_NOTE_DURATION_QL: float = 0.125  # 32nd–note (quarter‑length) safety floor

# ---------------------------------------------------------------------------
# Time‑signature helpers
# ---------------------------------------------------------------------------

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    """Return a *music21* ``TimeSignature`` object.

    Falls back to **4/4** on any problem and logs a warning rather than raising.
    """
    ts = ts_str or "4/4"
    try:
        return meter.TimeSignature(ts)
    except meter.MeterException:
        logger.warning("GTSO: Invalid time‑signature '%s'. Defaulting to 4/4.", ts)
        return meter.TimeSignature("4/4")
    except Exception as exc:  # defensive – we do *not* want stray crashes here
        logger.error("GTSO: Unexpected error for TS '%s': %s. Default 4/4.", ts, exc)
        return meter.TimeSignature("4/4")

# ---------------------------------------------------------------------------
# Scale helpers
# ---------------------------------------------------------------------------

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> scale.ConcreteScale:
    """Return a *music21* scale instance.

    Unknown modes fall back to **MajorScale(tonic)** with clear logging.
    """
    mode_key = (mode_str or "major").lower()
    tonic_val = tonic_str or "C"

    try:
        tonic_p = pitch.Pitch(tonic_val)
    except Exception:  # include AccidentalException, etc.
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

    scl_cls = mode_map.get(mode_key)
    if not scl_cls:
        logger.warning("BuildScale: Unknown mode '%s'. Using MajorScale.", mode_key)
        scl_cls = scale.MajorScale

    try:
        return scl_cls(tonic_p)
    except Exception as exc:
        logger.error("BuildScale: Could not instantiate %s with tonic %s – %s. Falling back to C major.",
                     scl_cls.__name__, tonic_p, exc)
        return scale.MajorScale(pitch.Pitch("C"))

# ---------------------------------------------------------------------------
# Chord‑label sanitiser – the心臓部
# ---------------------------------------------------------------------------

def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    """Return a *music21*‑friendly chord figure.

    * ``Rest``/``NC`` tokens ⇒ ``None``
    * Flatted root letters (Bb) → "B‑"  (music21 表記)
    * Paren tensions **(b9,#11)** are flattened and concatenated → "b9#11"
    * Hanging ``("`` at end is trimmed (avoids *m7(** errors)
    * Slash‑bass flats normalised (C/Bb → C/B‑)
    * Root‑直後の孤立 ``M`` を ``maj`` へ (C M7 → Cmaj7)
    """
    if not label or not isinstance(label, str):
        return None

    original = label
    label = label.strip()

    # 1) REST tokens ---------------------------------------------------------
    if label.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        return None

    # 2) Alt は放置すると曖昧。現状は削除し tension で明示推奨
    label = label.replace("alt", "")

    # 3) Expand (tensions) ---------------------------------------------------
    m = re.search(r"^(.*?)\(([^)]+)\)(.*)$", label)
    if m:
        base, tens, suffix = m.groups()
        label = f"{base}{re.sub(r'[ ,]', '', tens)}{suffix}"

    # 4) Remove stray opening paren  (e.g. "Am7(")
    label = label.rstrip("(")

    # 5) Root‑flat normalisation (Bb→B-) ------------------------------------
    label = re.sub(r"^([A-G])b", r"\1-", label)

    # 6) Slash bass note flat normalisation (C/Bb→C/B-)
    label = re.sub(r"/([A-G])b", r"/\1-", label)

    # 7) Replace root‑直後 'M' with 'maj' (CM7→Cmaj7) -----------------------
    label = re.sub(r"(?<=^[A-G][#-]?)(M)(?=\d|add|sus|aug|dim)", "maj", label)

    if label != original:
        logger.debug("sanitize: '%s' → '%s'", original, label)

    # 8) Quick validation – try parsing. Log but never crash -----------------
    try:
        harmony.ChordSymbol(label)
    except harmony.HarmonyException as exc:
        logger.warning("sanitize: '%s' still raises HarmonyException → %s", label, exc)
    except Exception as exc:
        logger.warning("sanitize: '%s' still problematic → %s", label, exc)

    return label
