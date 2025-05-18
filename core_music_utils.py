# --- START OF FILE generators/core_music_utils.py ---
import music21
import logging
from music21 import meter
from typing import Optional, Dict, Any, Tuple
from music21 import pitch, scale, meter # meterを追加 (TimeSignatureのため)
import logging

logger = logging.getLogger(__name__) # ロガー名を __name__ に統一

MIN_NOTE_DURATION_QL: float = 0.125 # 32分音符程度

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> Optional[scale.ConcreteScale]:
    if not mode_str: mode_str = "major"
    if not tonic_str: tonic_str = "C"
    try:
        tonic_p = pitch.Pitch(tonic_str)
    except Exception as e_tonic: # より広範な例外をキャッチ
        logger.error(f"build_scale_object: Invalid tonic '{tonic_str}': {e_tonic}. Defaulting to C.")
        tonic_p = pitch.Pitch("C")

    mode_map: Dict[str, Any] = {
        "ionian": scale.MajorScale, "major": scale.MajorScale,
        "dorian": scale.DorianScale, "phrygian": scale.PhrygianScale,
        "lydian": scale.LydianScale, "mixolydian": scale.MixolydianScale,
        "aeolian": scale.MinorScale, "minor": scale.MinorScale,
        "locrian": scale.LocrianScale, "harmonicminor": scale.HarmonicMinorScale,
        "melodicminor": scale.MelodicMinorScale,
    }
    scale_class = mode_map.get(mode_str.lower())
    if scale_class:
        try:
            return scale_class(tonic_p)
        except Exception as e_create:
            logger.error(f"build_scale_object: Error creating scale '{scale_class.__name__}' "
                         f"with '{tonic_p.nameWithOctave}': {e_create}. Fallback C Major.", exc_info=True)
            return scale.MajorScale(pitch.Pitch("C"))
    else:
        logger.warning(f"build_scale_object: Mode '{mode_str}' unknown for '{tonic_p.name}'. Defaulting to MajorScale.")
        return scale.MajorScale(tonic_p)

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    if not ts_str: ts_str = "4/4"
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning(f"get_time_signature_object: Invalid TS string '{ts_str}'. Defaulting to 4/4.")
        return meter.TimeSignature("4/4")
    except Exception as e_ts: # 他の予期せぬエラーもキャッチ
        logger.error(f"get_time_signature_object: Unexpected error for TS '{ts_str}': {e_ts}. Defaulting to 4/4.", exc_info=True)
        return meter.TimeSignature("4/4")

# --- END OF FILE generators/core_music_utils.py ---