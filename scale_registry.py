# --- START OF FILE utilities/scale_registry.py (役割特化版) ---
import logging
from typing import Optional, Dict, Any, List
from music21 import pitch, scale

logger = logging.getLogger(__name__)

# スケールオブジェクトをキャッシュするための辞書 (モジュールレベル)
_scale_cache: Dict[Tuple[str, str], scale.ConcreteScale] = {}

def build_scale_object(tonic_str: Optional[str], mode_str: Optional[str]) -> scale.ConcreteScale:
    """
    指定されたトニックとモードに基づいてmusic21のScaleオブジェクトを生成またはキャッシュから取得します。
    """
    tonic_name = (tonic_str or "C").capitalize() # C, D, E, F#, Gb など
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
        # 必要に応じて他のスケールも追加
    }
    
    scl_cls = mode_map.get(mode_name)
    
    if scl_cls is None: # マップにないモード名の場合
        # music21が直接解釈できるモード名か試す (例: "DiminishedScale")
        try:
            scl_obj = getattr(scale, mode_name.capitalize() + "Scale")(tonic_p) # 例: "diminished" -> DiminishedScale
            logger.info(f"ScaleRegistry: Created scale {scl_obj} for {tonic_name} {mode_name} (dynamic lookup).")
            _scale_cache[cache_key] = scl_obj
            return scl_obj
        except (AttributeError, TypeError, Exception) as e_dyn_scale:
            logger.warning(f"ScaleRegistry: Unknown mode '{mode_name}' and dynamic lookup failed ({e_dyn_scale}). Using MajorScale for {tonic_name}.")
            scl_cls = scale.MajorScale # フォールバック
    
    try:
        final_scale = scl_cls(tonic_p)
        logger.info(f"ScaleRegistry: Created and cached scale {final_scale} for {tonic_name} {mode_name}.")
        _scale_cache[cache_key] = final_scale
        return final_scale
    except Exception as e_create:
        logger.error(f"ScaleRegistry: Error creating '{scl_cls.__name__}' for {tonic_p.name}: {e_create}. Fallback C Major.", exc_info=True)
        fallback_scale = scale.MajorScale(pitch.Pitch("C"))
        _scale_cache[cache_key] = fallback_scale # フォールバックもキャッシュ（エラー再発防止）
        return fallback_scale

class ScaleRegistry:
    """
    スケールオブジェクトの取得と管理を行うクラス。
    将来的には、より高度なキャッシュ戦略やスケールプロパティへのアクセスを提供可能。
    現状は build_scale_object 関数をラップする形でも良い。
    """
    @staticmethod
    def get(tonic: str, mode: str) -> scale.ConcreteScale:
        return build_scale_object(tonic, mode)

    @staticmethod
    def get_pitches(tonic: str, mode: str, min_octave: int = 2, max_octave: int = 5) -> List[pitch.Pitch]:
        scl = build_scale_object(tonic, mode)
        return scl.getPitches(pitch.Pitch(f'{scl.tonic.name}{min_octave}'), pitch.Pitch(f'{scl.tonic.name}{max_octave}'))

    @staticmethod
    def mode_tensions(mode: str) -> List[int]: # bass_utils や melody_utils で使われる想定
        mode_lower = mode.lower()
        # これは簡易的な例。より詳細な音楽理論に基づく定義が必要。
        if mode_lower in ["major", "ionian", "lydian"]: return [2, 6, 9, 11, 13] # 9th, #11th(Lydian), 13th
        if mode_lower in ["minor", "aeolian", "dorian", "phrygian"]: return [2, 4, 6, 9, 11, 13] # 9th, 11th, 13th (b13 for Aeolian/Phrygian)
        if mode_lower == "mixolydian": return [2, 4, 6, 9, 11, 13] # 9th, 13th (b7 is chord tone)
        return [2, 4, 6] # Default tensions

    @staticmethod
    def avoid_degrees(mode: str) -> List[int]: # 同上
        mode_lower = mode.lower()
        if mode_lower == "major": return [4] # Avoid F over Cmaj7 for too long
        if mode_lower == "dorian": return []
        if mode_lower == "phrygian": return [2, 6] # b2, b6 are characteristic but can clash
        if mode_lower == "lydian": return []
        if mode_lower == "mixolydian": return [4] # Avoid 4th if not sus
        if mode_lower == "aeolian": return [6] # Avoid b6 if not harmonized carefully
        if mode_lower == "locrian": return [1, 2, 3, 4, 5, 6, 7] # Everything is an avoid note :)
        return []
# --- END OF FILE utilities/scale_registry.py ---
