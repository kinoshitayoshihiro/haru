# --- START OF FILE utilities/scale_registry.py (修正版) ---
import logging
from typing import Optional, Dict, Any, List, Tuple

# music21 のサブモジュールを個別にインポート
from music21 import pitch
from music21 import scale # music21.scale モジュールをインポート

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
    
    # スケールクラスのマッピング
    # MajorPentatonicScale を PentatonicScale (デフォルトでメジャー) に変更
    mode_map: Dict[str, Any] = {
        "ionian": scale.MajorScale, "major": scale.MajorScale,
        "dorian": scale.DorianScale, "phrygian": scale.PhrygianScale,
        "lydian": scale.LydianScale, "mixolydian": scale.MixolydianScale,
        "aeolian": scale.MinorScale, "natural_minor": scale.MinorScale, "minor": scale.MinorScale,
        "locrian": scale.LocrianScale,
        "harmonicminor": scale.HarmonicMinorScale, "harmonic_minor": scale.HarmonicMinorScale,
        "melodicminor": scale.MelodicMinorScale, "melodic_minor": scale.MelodicMinorScale, # music21では MelodicMinorScale は上行形のみが一般的
        "wholetone": scale.WholeToneScale, "whole_tone": scale.WholeToneScale,
        "chromatic": scale.ChromaticScale,
        "majorpentatonic": scale.PentatonicScale, # ★修正点: MajorPentatonicScale -> PentatonicScale
        "major_pentatonic": scale.PentatonicScale,  # ★修正点: MajorPentatonicScale -> PentatonicScale
        "minorpentatonic": scale.MinorPentatonicScale, # MinorPentatonicScaleクラスは通常存在
        "minor_pentatonic": scale.MinorPentatonicScale,
        "blues": scale.BluesScale # BluesScaleクラスも通常存在
        # 必要に応じて他のスケール (例: DiminishedScaleなど) も追加可能
    }
    
    scl_cls = mode_map.get(mode_name)
    
    if scl_cls is None:
        # 知らないモード名の場合、動的にクラス名を探す試み (より堅牢にするなら具体的なエラー処理が必要)
        try:
            # 例: "my_custom_scale" -> "MyCustomScaleScale" (music21の命名規則に合わせる)
            scale_class_name = mode_name.capitalize().replace("_", "") + "Scale"
            if not scale_class_name.endswith("Scale"): # 既にScaleで終わっている場合は追加しない
                 scale_class_name += "Scale"
            
            scl_cls_dynamic = getattr(scale, scale_class_name, None) # music21.scale モジュールから動的取得
            if scl_cls_dynamic and issubclass(scl_cls_dynamic, scale.Scale):
                scl_obj = scl_cls_dynamic(tonic_p)
                logger.info(f"ScaleRegistry: Created scale {scl_obj} for {tonic_name} {mode_name} (dynamic lookup: {scale_class_name}).")
                _scale_cache[cache_key] = scl_obj
                return scl_obj
            else:
                # getattrで見つからない、またはそれがScaleクラスではない場合
                raise AttributeError(f"Scale class '{scale_class_name}' not found or not a valid scale in music21.scale module.")
        except (AttributeError, TypeError, Exception) as e_dyn_scale: # 広めに例外をキャッチ
            logger.warning(f"ScaleRegistry: Unknown mode '{mode_name}' and dynamic lookup failed ({e_dyn_scale}). Using MajorScale for {tonic_name} as fallback.")
            scl_cls = scale.MajorScale # デフォルトフォールバック
    
    try:
        final_scale = scl_cls(tonic_p)
        logger.info(f"ScaleRegistry: Created and cached scale {final_scale} for {tonic_name} {mode_name}.")
        _scale_cache[cache_key] = final_scale
        return final_scale
    except Exception as e_create: # スケールオブジェクト生成時の一般的なエラー
        logger.error(f"ScaleRegistry: Error creating '{scl_cls.__name__ if scl_cls else 'UnknownScaleClass'}' for {tonic_p.name}: {e_create}. Fallback to C Major.", exc_info=True)
        fallback_scale = scale.MajorScale(pitch.Pitch("C"))
        _scale_cache[cache_key] = fallback_scale # エラー時もキーをキャッシュして再試行を防ぐ
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
        try:
            # scl.tonic が pitch.Pitch オブジェクトであることを確認
            if not isinstance(scl.tonic, pitch.Pitch):
                logger.error(f"ScaleRegistry: Tonic for scale {tonic} {mode} is not a Pitch object: {scl.tonic}. Using C.")
                effective_tonic_name = "C"
            else:
                effective_tonic_name = scl.tonic.name

            p_start = pitch.Pitch(f'{effective_tonic_name}{min_octave}')
            p_end = pitch.Pitch(f'{effective_tonic_name}{max_octave}')
            return scl.getPitches(p_start, p_end)
        except Exception as e_get_pitches:
            logger.error(f"ScaleRegistry: Error in get_pitches for {tonic} {mode}: {e_get_pitches}. Returning empty list.", exc_info=True)
            return []

    @staticmethod
    def mode_tensions(mode: str) -> List[int]:
        # (変更なし)
        mode_lower = mode.lower()
        if mode_lower in ["major", "ionian", "lydian"]: return [2, 6, 9, 11, 13]
        if mode_lower in ["minor", "aeolian", "dorian", "phrygian"]: return [2, 4, 6, 9, 11, 13]
        if mode_lower == "mixolydian": return [2, 4, 6, 9, 11, 13]
        return [2, 4, 6]

    @staticmethod
    def avoid_degrees(mode: str) -> List[int]:
        # (変更なし)
        mode_lower = mode.lower()
        if mode_lower == "major": return [4]
        if mode_lower == "dorian": return []
        if mode_lower == "phrygian": return [2, 6]
        if mode_lower == "lydian": return []
        if mode_lower == "mixolydian": return [4]
        if mode_lower == "aeolian": return [6]
        if mode_lower == "locrian": return [1, 2, 3, 4, 5, 6, 7]
        return []
# --- END OF FILE utilities/scale_registry.py (修正版) ---
