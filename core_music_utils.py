# --- START OF FILE generators/core_music_utils.py (修正版) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony # harmony をインポート (ChordSymbolのfigureチェックのため)
from typing import Optional, Dict, Any, Tuple
import re # 正規表現モジュールをインポート

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    if not ts_str:
        ts_str = "4/4"
        logger.debug(f"get_time_signature_object: ts_str is None, defaulting to '4/4'.")
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning(f"get_time_signature_object: Invalid TimeSignature string '{ts_str}'. Defaulting to 4/4.")
        return meter.TimeSignature("4/4")
    except Exception as e_ts:
        logger.error(f"get_time_signature_object: Unexpected error creating TimeSignature from '{ts_str}': {e_ts}. Defaulting to 4/4.", exc_info=True)
        return meter.TimeSignature("4/4")

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> Optional[scale.ConcreteScale]:
    # (この関数は変更なし - 前回提示の内容を維持)
    effective_mode_str = mode_str if mode_str else "major"
    effective_tonic_str = tonic_str if tonic_str else "C"
    logger.debug(f"build_scale_object: Attempting scale for {effective_tonic_str} {effective_mode_str}")
    try:
        tonic_p = pitch.Pitch(effective_tonic_str)
    except Exception as e_tonic:
        logger.error(f"build_scale_object: Invalid tonic string '{effective_tonic_str}': {e_tonic}. Defaulting tonic to C.")
        tonic_p = pitch.Pitch("C")
    mode_map: Dict[str, Any] = {
        "ionian": scale.MajorScale, "major": scale.MajorScale,
        "dorian": scale.DorianScale, "phrygian": scale.PhrygianScale,
        "lydian": scale.LydianScale, "mixolydian": scale.MixolydianScale,
        "aeolian": scale.MinorScale, "minor": scale.MinorScale,
        "locrian": scale.LocrianScale,
        "harmonicminor": scale.HarmonicMinorScale,
        "melodicminor": scale.MelodicMinorScale,
    }
    scale_class = mode_map.get(effective_mode_str.lower())
    if scale_class:
        try: return scale_class(tonic_p)
        except Exception as e_create:
            logger.error(f"build_scale_object: Error creating scale '{scale_class.__name__}' "
                         f"with tonic '{tonic_p.nameWithOctave if tonic_p else 'N/A'}': {e_create}. Fallback C Major.", exc_info=True)
            return scale.MajorScale(pitch.Pitch("C"))
    else:
        logger.warning(f"build_scale_object: Mode '{effective_mode_str}' unknown for tonic '{tonic_p.nameWithOctave if tonic_p else 'N/A'}'. Defaulting to MajorScale.")
        return scale.MajorScale(tonic_p)

# ★★★ 以下に関数を追加 ★★★
def sanitize_chord_label(label: str) -> str:
    """
    ChordSymbolのパースエラーを防ぐためにコードラベルを整形・修正する。
    """
    if not isinstance(label, str):
        logger.warning(f"sanitize_chord_label: Input label '{label}' is not a string. Returning as is.")
        return str(label) # 文字列でない場合は念のため文字列化して返す

    original_label = label # デバッグ用

    # 1. music21標準表記への置換 (例: maj7 -> M7, mi7 -> m7)
    #    大文字小文字を区別しない置換が望ましい場合もある
    label = label.replace('maj7', 'M7').replace('maj9', 'M9').replace('maj13', 'M13')
    label = label.replace('mi7', 'm7').replace('min7', 'm7')
    label = label.replace('mi9', 'm9').replace('min9', 'm9')
    label = label.replace('mi11', 'm11').replace('min11', 'm11')
    label = label.replace('mi13', 'm13').replace('min13', 'm13')
    label = label.replace('dom7', '7') # 一般的な表記だが music21 は 7 を使う

    # 2. テンション表記の括弧: "C7(b9)" -> "C7(b9)" (これはOK), "Am7(add11)" -> "Am7(add11)" (これもOK)
    #    エラーログの 'm7(' や 'maj7(' は、テンションが欠落しているか、ラベル生成時の問題の可能性。
    #    ここでは、不完全な括弧 (開き括弧だけで閉じ括弧がない) を削除する応急処置を試みる。
    #    より根本的には chordmap.json のラベル記述、またはラベルを生成するロジックの見直しが必要。
    if label.count('(') > label.count(')'):
        if label.endswith('('):
            logger.warning(f"sanitize_chord_label: Label '{original_label}' ends with '('. Removing trailing '('.")
            label = label[:-1] # 末尾の '(' を削除
        else:
            # 開き括弧が多いが、末尾ではない場合 (例: "C(add9") - これは複雑なので一旦警告のみ
            logger.warning(f"sanitize_chord_label: Label '{original_label}' has imbalanced parentheses but doesn't end with '('. Careful parsing expected.")

    # 3. フラット/シャープの表記: "BbM7" -> "B-M7" (music21推奨)
    #    正規表現で、音名(A-G)の直後にある 'b' または '#' を music21 の臨時記号に置き換える
    #    (例: "Bb" -> "B-", "C#" -> "C#")
    #    'b' が音名の一部 (B) なのか、フラット記号なのかを区別するのが難しい。
    #    ここでは、エラーで頻出していた 'bmaj7' や 'bm7' に特化した対処を試みる。
    #    正規表現で音名と品質を分離し、音名にフラット記号を正しく付与する
    
    # "Bbmaj7" -> "B-maj7", "Ebm7" -> "E-m7" など
    # この正規表現は、1文字の音名 + 'b' + 品質記号 のパターンにマッチする
    match_flat_quality = re.match(r"([A-Ga-g])b(M(?:aj)?\d*|m\d*|dim\d*|aug\d*|\d*sus\d*|\d*alt.*|$)", label)
    if match_flat_quality:
        root_note = match_flat_quality.group(1)
        quality = match_flat_quality.group(2)
        corrected_label = f"{root_note}-{quality}" # music21は '-' をフラットとして優先的に解釈
        logger.debug(f"sanitize_chord_label: Corrected flat notation from '{label}' to '{corrected_label}'")
        label = corrected_label
    
    # テンションのシャープ/フラットの前のカンマ (例: C7(#9,b13) -> C7(#9, b13) music21はカンマ区切りで複数テンション可)
    # music21.harmony.ChordSymbol は "C7(#9, b13)" や "C7 #9 b13" を解釈できるはず。
    # "C7(#9b13)" のようにカンマなしで連続していると解釈できない場合がある。
    # "(#9,b13)" -> "(#9, b13)" or "(#9 b13)" (スペースは許容されることが多い)
    # これは tensions_to_add で渡す方が安全かもしれない。
    # ここでは、あまり複雑な置換はせず、基本的なものに留める。

    # 4. "Rest" のような非コードラベルの扱い
    #    これはこの関数ではなく、呼び出し側でharmony.ChordSymbol()の前に判定するのが良い。

    if label != original_label:
        logger.info(f"sanitize_chord_label: Sanitized '{original_label}' to '{label}'")
    return label

# --- END OF FILE generators/core_music_utils.py ---
