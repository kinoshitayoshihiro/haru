# --- START OF FILE utilities/scale_registry.py (確認・コメント追加版) ---
import logging
from typing import Optional, Dict, Any, List, Tuple 

# music21 のサブモジュールを個別にインポート
from music21 import pitch
from music21 import scale

logger = logging.getLogger(__name__)

# スケールオブジェクトをキャッシュするための辞書 (モジュールレベル)
_scale_cache: Dict[Tuple[str, str], scale.ConcreteScale] = {} # scale を使用

def build_scale_object(tonic_str: Optional[str], mode_str: Optional[str]) -> scale.ConcreteScale: # scale を使用
    """
    指定されたトニックとモードに基づいてmusic21のScaleオブジェクトを生成またはキャッシュから取得します。
    この関数がこのモジュールの主要なスケール生成ロジックです。
    """
    tonic_name = (tonic_str or "C").capitalize()
    mode_name = (mode_str or "major").lower()

    cache_key = (tonic_name, mode_name)
    if cache_key in _scale_cache:
        logger.debug(f"ScaleRegistry: Returning cached scale for {tonic_name} {mode_name}.")
        return _scale_cache[cache_key]

    try:
        tonic_p = pitch.Pitch(tonic_name) # pitch を使用
    except Exception:
        logger.error(f"ScaleRegistry: Invalid tonic '{tonic_name}'. Defaulting to C.")
        tonic_p = pitch.Pitch("C") # pitch を使用
    
    mode_map: Dict[str, Any] = {
        "ionian": scale.MajorScale, "major": scale.MajorScale, # scale を使用
        "dorian": scale.DorianScale, "phrygian": scale.PhrygianScale, # scale を使用
        "lydian": scale.LydianScale, "mixolydian": scale.MixolydianScale, # scale を使用
        "aeolian": scale.MinorScale, "natural_minor": scale.MinorScale, "minor": scale.MinorScale, # scale を使用
        "locrian": scale.LocrianScale, # scale を使用
        "harmonicminor": scale.HarmonicMinorScale, "harmonic_minor": scale.HarmonicMinorScale, # scale を使用
        "melodicminor": scale.MelodicMinorScale, "melodic_minor": scale.MelodicMinorScale, # scale を使用
        "wholetone": scale.WholeToneScale, "whole_tone": scale.WholeToneScale, # scale を使用
        "chromatic": scale.ChromaticScale, # scale を使用
        "majorpentatonic": scale.MajorPentatonicScale, "major_pentatonic": scale.MajorPentatonicScale, # scale を使用
        "minorpentatonic": scale.MinorPentatonicScale, "minor_pentatonic": scale.MinorPentatonicScale, # scale を使用
        "blues": scale.BluesScale # scale を使用
    }
    
    scl_cls = mode_map.get(mode_name)
    
    if scl_cls is None:
        try:
            scale_class_name = mode_name.capitalize().replace("_", "") + "Scale" 
            if not scale_class_name.endswith("Scale"): 
                 scale_class_name += "Scale"

            scl_cls_dynamic = getattr(scale, scale_class_name, None) # scale を使用
            if scl_cls_dynamic and issubclass(scl_cls_dynamic, scale.Scale): # scale を使用
                scl_obj = scl_cls_dynamic(tonic_p)
                logger.info(f"ScaleRegistry: Created scale {scl_obj} for {tonic_name} {mode_name} (dynamic lookup: {scale_class_name}).")
                _scale_cache[cache_key] = scl_obj
                return scl_obj
            else:
                raise AttributeError(f"Scale class {scale_class_name} not found or not a valid scale in music21.scale")
        except (AttributeError, TypeError, Exception) as e_dyn_scale:
            logger.warning(f"ScaleRegistry: Unknown mode '{mode_name}' and dynamic lookup failed ({e_dyn_scale}). Using MajorScale for {tonic_name}.")
            scl_cls = scale.MajorScale # scale を使用
    
    try:
        final_scale = scl_cls(tonic_p)
        logger.info(f"ScaleRegistry: Created and cached scale {final_scale} for {tonic_name} {mode_name}.")
        _scale_cache[cache_key] = final_scale
        return final_scale
    except Exception as e_create:
        logger.error(f"ScaleRegistry: Error creating '{scl_cls.__name__}' for {tonic_p.name}: {e_create}. Fallback C Major.", exc_info=True)
        fallback_scale = scale.MajorScale(pitch.Pitch("C")) # scale, pitch を使用
        _scale_cache[cache_key] = fallback_scale
        return fallback_scale

class ScaleRegistry:
    @staticmethod
    def get(tonic: str, mode: str) -> scale.ConcreteScale: # scale を使用
        """指定されたトニックとモードの music21.scale.ConcreteScale オブジェクトを取得します。"""
        return build_scale_object(tonic, mode)

    @staticmethod
    def get_pitches(tonic: str, mode: str, min_octave: int = 2, max_octave: int = 5) -> List[pitch.Pitch]: # pitch を使用
        """指定された範囲のスケール構成音を取得します。"""
        scl = build_scale_object(tonic, mode)
        try:
            p_start = pitch.Pitch(f'{scl.tonic.name}{min_octave}') # pitch を使用
            p_end = pitch.Pitch(f'{scl.tonic.name}{max_octave}') # pitch を使用
            return scl.getPitches(p_start, p_end)
        except Exception as e_get_pitches:
            logger.error(f"ScaleRegistry: Error in get_pitches for {tonic} {mode}: {e_get_pitches}. Returning empty list.")
            return []


    @staticmethod
    def mode_tensions(mode: str) -> List[int]:
        mode_lower = mode.lower()
        if mode_lower in ["major", "ionian", "lydian"]: return [2, 6, 9, 11, 13]
        if mode_lower in ["minor", "aeolian", "dorian", "phrygian"]: return [2, 4, 6, 9, 11, 13]
        if mode_lower == "mixolydian": return [2, 4, 6, 9, 11, 13]
        return [2, 4, 6]

    @staticmethod
    def avoid_degrees(mode: str) -> List[int]:
        mode_lower = mode.lower()
        if mode_lower == "major": return [4]
        if mode_lower == "dorian": return []
        if mode_lower == "phrygian": return [2, 6]
        if mode_lower == "lydian": return []
        if mode_lower == "mixolydian": return [4]
        if mode_lower == "aeolian": return [6]
        if mode_lower == "locrian": return [1, 2, 3, 4, 5, 6, 7]
        return []
# --- END OF FILE utilities/scale_registry.py ---
