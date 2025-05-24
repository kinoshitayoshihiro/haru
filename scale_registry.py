# --- START OF FILE utilities/scale_registry.py (確認・コメント追加版) ---
import logging
from typing import Optional, Dict, Any, List, Tuple # Tuple を追加
from music21 import pitch, scale

logger = logging.getLogger(__name__)

# スケールオブジェクトをキャッシュするための辞書 (モジュールレベル)
_scale_cache: Dict[Tuple[str, str], scale.ConcreteScale] = {}

def build_scale_object(tonic_str: Optional[str], mode_str: Optional[str]) -> scale.ConcreteScale:
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
        tonic_p = pitch.Pitch(tonic_name)
    except Exception:
        logger.error(f"ScaleRegistry: Invalid tonic '{tonic_name}'. Defaulting to C.")
        tonic_p = pitch.Pitch("C")
    
    mode_map: Dict[str, Any] = {
        "ionian": scale.MajorScale, "major": scale.MajorScale,
        "dorian": scale.DorianScale, "phrygian": scale.PhrygianScale,
        "lydian": scale.LydianScale, "mixolydian": scale.MixolydianScale,
        "aeolian": scale.MinorScale, "natural_minor": scale.MinorScale, "minor": scale.MinorScale,
        "locrian": scale.LocrianScale,
        "harmonicminor": scale.HarmonicMinorScale, "harmonic_minor": scale.HarmonicMinorScale,
        "melodicminor": scale.MelodicMinorScale, "melodic_minor": scale.MelodicMinorScale,
        "wholetone": scale.WholeToneScale, "whole_tone": scale.WholeToneScale,
        "chromatic": scale.ChromaticScale,
        "majorpentatonic": scale.MajorPentatonicScale, "major_pentatonic": scale.MajorPentatonicScale,
        "minorpentatonic": scale.MinorPentatonicScale, "minor_pentatonic": scale.MinorPentatonicScale,
        "blues": scale.BluesScale
    }
    
    scl_cls = mode_map.get(mode_name)
    
    if scl_cls is None:
        try:
            # music21.scale モジュールに直接アクセスしてクラスを取得しようと試みる
            # 例: mode_name が "Diminished" なら scale.DiminishedScale を探す
            scale_class_name = mode_name.capitalize().replace("_", "") + "Scale" # "whole_tone" -> "WholeToneScale"
            if not scale_class_name.endswith("Scale"): # 念のため
                 scale_class_name += "Scale"

            scl_cls_dynamic = getattr(scale, scale_class_name, None)
            if scl_cls_dynamic and issubclass(scl_cls_dynamic, scale.Scale): # music21.scale.Scaleのサブクラスであるか確認
                scl_obj = scl_cls_dynamic(tonic_p)
                logger.info(f"ScaleRegistry: Created scale {scl_obj} for {tonic_name} {mode_name} (dynamic lookup: {scale_class_name}).")
                _scale_cache[cache_key] = scl_obj
                return scl_obj
            else:
                raise AttributeError(f"Scale class {scale_class_name} not found or not a valid scale in music21.scale")
        except (AttributeError, TypeError, Exception) as e_dyn_scale:
            logger.warning(f"ScaleRegistry: Unknown mode '{mode_name}' and dynamic lookup failed ({e_dyn_scale}). Using MajorScale for {tonic_name}.")
            scl_cls = scale.MajorScale
    
    try:
        final_scale = scl_cls(tonic_p)
        logger.info(f"ScaleRegistry: Created and cached scale {final_scale} for {tonic_name} {mode_name}.")
        _scale_cache[cache_key] = final_scale
        return final_scale
    except Exception as e_create:
        logger.error(f"ScaleRegistry: Error creating '{scl_cls.__name__}' for {tonic_p.name}: {e_create}. Fallback C Major.", exc_info=True)
        fallback_scale = scale.MajorScale(pitch.Pitch("C"))
        _scale_cache[cache_key] = fallback_scale
        return fallback_scale

class ScaleRegistry:
    @staticmethod
    def get(tonic: str, mode: str) -> scale.ConcreteScale:
        """指定されたトニックとモードの music21.scale.ConcreteScale オブジェクトを取得します。"""
        return build_scale_object(tonic, mode)

    @staticmethod
    def get_pitches(tonic: str, mode: str, min_octave: int = 2, max_octave: int = 5) -> List[pitch.Pitch]:
        """指定された範囲のスケール構成音を取得します。"""
        scl = build_scale_object(tonic, mode)
        # getPitches の引数が Pitch オブジェクトであることを確認
        try:
            p_start = pitch.Pitch(f'{scl.tonic.name}{min_octave}')
            p_end = pitch.Pitch(f'{scl.tonic.name}{max_octave}')
            return scl.getPitches(p_start, p_end)
        except Exception as e_get_pitches:
            logger.error(f"ScaleRegistry: Error in get_pitches for {tonic} {mode}: {e_get_pitches}. Returning empty list.")
            return []


    @staticmethod
    def mode_tensions(mode: str) -> List[int]:
        mode_lower = mode.lower()
        # (この部分は前回と同様の簡易的な定義)
        if mode_lower in ["major", "ionian", "lydian"]: return [2, 6, 9, 11, 13]
        if mode_lower in ["minor", "aeolian", "dorian", "phrygian"]: return [2, 4, 6, 9, 11, 13]
        if mode_lower == "mixolydian": return [2, 4, 6, 9, 11, 13]
        return [2, 4, 6]

    @staticmethod
    def avoid_degrees(mode: str) -> List[int]:
        mode_lower = mode.lower()
        # (この部分は前回と同様の簡易的な定義)
        if mode_lower == "major": return [4]
        if mode_lower == "dorian": return []
        if mode_lower == "phrygian": return [2, 6]
        if mode_lower == "lydian": return []
        if mode_lower == "mixolydian": return [4]
        if mode_lower == "aeolian": return [6]
        if mode_lower == "locrian": return [1, 2, 3, 4, 5, 6, 7]
        return []
# --- END OF FILE utilities/scale_registry.py ---
