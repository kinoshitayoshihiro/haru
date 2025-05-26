# --- START OF FILE utilities/scale_registry.py (Haruさんご提供版) ---
# scale_registry.py – Revised 2025‑05‑27
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
from typing import Dict, Callable, Union # Union を typing からインポート

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

def _resolve_scale_class(mode: str) -> Callable[[pitch.Pitch], scale.ConcreteScale]: # 引数を pitch.Pitch に変更
    mode_lc = mode.lower()

    # getattrの第3引数に適切なフォールバックを指定
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
        # pentatonic (music21 >= 9.5 uses MajorPentatonicScale / MinorPentatonicScale)
        # getattrのフォールバックとして、具体的なスケールクラスを指定
        "majorpentatonic": getattr(scale, "MajorPentatonicScale", getattr(scale, "PentatonicScale", scale.MajorScale)),
        "minorpentatonic": getattr(scale, "MinorPentatonicScale", scale.MinorScale), # MinorScaleへのフォールバックが適切か検討
        "pentatonic": getattr(scale, "MajorPentatonicScale", getattr(scale, "PentatonicScale", scale.MajorScale)), # デフォルトはメジャーペンタトニック
        # blues / whole‑tone / octatonic
        "blues": scale.BluesScale,
        "wholetone": scale.WholeToneScale,
        "octatonic": scale.OctatonicScale,
        "chromatic": scale.ChromaticScale, # ChromaticScale を追加
        "harmonicminor": scale.HarmonicMinorScale, # HarmonicMinorScale を追加
        "melodicminor": scale.MelodicMinorScale, # MelodicMinorScale を追加
    }

    if mode_lc not in _mapping:
        # 未知のモードの場合、動的ルックアップを試みる (より安全な方法)
        # 例: "mycustomscale" -> music21.scale.Mycustomscale
        # ただし、music21のスケールクラス名は通常大文字で始まるため、モード名を適切に変換
        mode_title_case = mode_lc.replace("_", " ").title().replace(" ", "")
        if not mode_title_case.endswith("Scale"):
             scale_class_name_candidate = mode_title_case + "Scale"
        else:
             scale_class_name_candidate = mode_title_case

        dynamic_scl_cls = getattr(scale, scale_class_name_candidate, None)
        if dynamic_scl_cls and issubclass(dynamic_scl_cls, scale.Scale):
            # 動的に見つかったクラスを返す
            return dynamic_scl_cls
        else:
            # それでも見つからなければエラー
            raise ValueError(f"Unsupported mode name: {mode} (and dynamic lookup for '{scale_class_name_candidate}' failed)")

    return _mapping[mode_lc]

# ---------------------------------------------------------------------
# public helpers
# ---------------------------------------------------------------------

@lru_cache(maxsize=128)
def get(tonic: Union[str, pitch.Pitch], mode: str = "major") -> scale.ConcreteScale: # tonic の型ヒントを Union に変更
    """Return a *singleton* scale object for the given tonic + mode.

    The result is cached so repeated look‑ups incur zero overhead.
    """
    # tonicが文字列の場合のみPitchオブジェクトに変換
    tonic_pitch_obj = pitch.Pitch(tonic) if isinstance(tonic, str) else tonic
    
    scale_cls = _resolve_scale_class(mode)
    try:
        return scale_cls(tonic_pitch_obj)
    except Exception as e:
        logger.error(f"ScaleRegistry: Could not instantiate scale {scale_cls.__name__} with tonic {tonic_pitch_obj.name}: {e}. Defaulting to C Major.")
        return scale.MajorScale(pitch.Pitch("C"))


# alias retained for backwards compatibility
# ScaleRegistry クラスとして定義し、getメソッドを持つ形の方が望ましい場合もあるが、
# Haruさんの既存コードとの互換性を最優先する
class ScaleRegistry:
    @staticmethod
    def get(tonic: Union[str, pitch.Pitch], mode: str = "major") -> scale.ConcreteScale:
        return get(tonic, mode) # キャッシュ機能付きのgetを呼び出す

    # get_pitches, mode_tensions, avoid_degrees は現状のコードにはないため、
    # 必要であれば以前のバージョンから移植または再定義が必要です。
    # ここでは、Haruさん提供のコードの範囲に合わせます。

# --- END OF FILE utilities/scale_registry.py (Haruさんご提供版適用) ---
