# --- START OF FILE generators/core_music_utils.py (修正版) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, Tuple, Union
import re

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    if not ts_str: ts_str = "4/4"
    try: return meter.TimeSignature(ts_str)
    except meter.MeterException: logger.warning(f"GTSO: Invalid TS '{ts_str}'. Default 4/4."); return meter.TimeSignature("4/4")
    except Exception as e: logger.error(f"GTSO: Error for TS '{ts_str}': {e}. Default 4/4.", exc_info=True); return meter.TimeSignature("4/4")

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> Optional[scale.ConcreteScale]:
    # (前回の修正を維持、ここでは省略)
    effective_mode_str = mode_str if mode_str else "major"; effective_tonic_str = tonic_str if tonic_str else "C"
    try: tonic_p = pitch.Pitch(effective_tonic_str)
    except: logger.error(f"BuildScale: Invalid tonic '{effective_tonic_str}'. Default C."); tonic_p = pitch.Pitch("C")
    mode_map: Dict[str, Any] = {"ionian": scale.MajorScale, "major": scale.MajorScale, "dorian": scale.DorianScale,"phrygian": scale.PhrygianScale, "lydian": scale.LydianScale,"mixolydian": scale.MixolydianScale,"aeolian": scale.MinorScale, "minor": scale.MinorScale,"locrian": scale.LocrianScale,"harmonicminor": scale.HarmonicMinorScale,"melodicminor": scale.MelodicMinorScale}
    s_class = mode_map.get(effective_mode_str.lower())
    if s_class:
        try: return s_class(tonic_p)
        except: logger.error(f"BuildScale: Error creating {s_class.__name__} with {tonic_p}. Fallback C Major."); return scale.MajorScale(pitch.Pitch("C"))
    else: logger.warning(f"BuildScale: Mode '{effective_mode_str}' unknown for {tonic_p}. Default Major."); return scale.MajorScale(tonic_p)


def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    """
    コードラベルをmusic21が解釈しやすい形式にサニタイズする。
    ValueError: Invalid chord abbreviation 'm7(' などのエラーに対応。
    """
    if not label or not isinstance(label, str): return None
    original_label = label
    label_lower = label.strip().lower()

    if label_lower in ["rest", "r", "silence", "none", "", "n.c.", "nc"]:
        logger.debug(f"Sanitize: '{original_label}' as Rest -> None.")
        return None

    # 特殊な全体置換
    label = label.replace("alt", "") # "alt" は解釈が曖昧なので一旦除去 (テンションで指定推奨)
    label = label.replace("sus2", "add2") # music21はadd2を好む傾向

    # "Bbmaj7" -> "B-maj7"のようなフラット表記の修正
    flat_map = {"Bb": "B-", "Eb": "E-", "Ab": "A-", "Db": "D-", "Gb": "G-"}
    for k_flat, v_flat in flat_map.items():
        if label.startswith(k_flat): # 先頭が大文字のフラット (例: Bbmaj7)
            label = label.replace(k_flat, v_flat, 1)
            break
        elif label.startswith(k_flat.lower()): # 先頭が小文字のフラット (例: bbdim) -> これはmusic21的には B--dim
            # これは非常に稀で、通常はb- (B minor flat)などを意図しない限り、
            # bが臨時記号のフラットを指すことは少ないが、念のため。
            # 'bb' (B double flat) -> 'B--' に変換すべきだが、元の意図が 'Bbm' (B flat minor) の可能性もある。
            # ここでは単純なケースのみ。
            pass # 小文字で始まる b はベース音やマイナーの可能性が高く、慎重な扱いが必要

    # 括弧の処理: 例 Am7(add11) -> Am7add11, E7(b9) -> E7b9
    # music21は "Am7add11" を直接解釈しにくい。"Am7" と "add11" に分けて処理するのが理想。
    # ここでは、まず括弧を外して連結する。その後のパースはharmony.ChordSymbolに任せる。
    # エラーログ "Invalid chord abbreviation 'm7('" のようなケースに対処するため、
    # 括弧の前後で有効なコード品質かを確認するアプローチも考えられるが、複雑化する。
    # ここでは、単純に括弧とカンマ、不要なスペースを除去し、文字を連結する。

    # 括弧が開いたまま閉じられていないケース ("Cmaj7(add9")
    if '(' in label and ')' not in label:
        logger.warning(f"Sanitize: Label '{original_label}' has unclosed parenthesis. Attempting to remove from '('.")
        label = label.split('(')[0].strip()
    # 括弧が閉じたまま開かれていないケース ("add9)Cmaj7") - あまりないが
    elif ')' in label and '(' not in label:
        logger.warning(f"Sanitize: Label '{original_label}' has unopened parenthesis. Attempting to remove up to ')'.")
        label = label.split(')')[-1].strip()

    # 括弧とその中のコンマを処理してテンションを連結
    # 例: Cmaj7(#9, b13) -> Cmaj7#9b13
    match = re.search(r'^(.*?)\((.*)\)(.*)$', label)
    if match:
        base_chord = match.group(1).strip()
        tensions_in_paren = match.group(2)
        suffix_after_paren = match.group(3).strip()
        
        # 括弧内のカンマとスペースを除去
        cleaned_tensions = re.sub(r'[,\s]', '', tensions_in_paren)
        label = base_chord + cleaned_tensions + suffix_after_paren
        logger.debug(f"Sanitize: Expanded parens in '{original_label}' to '{label}' (intermediate)")

    # "M7(" のような不正な略記を修正しようと試みる (これは元のchordmap側の品質問題が大きい)
    # 品質部分が"("で終わっている場合、おそらくテンションが続くはずが欠落している
    # 例: "Am7(" -> "Am7"
    invalid_abbreviations = ["m7(", "M7(", "7(", "m9(", "M9(", "dim(", "dim7("]
    for inv_abbr in invalid_abbreviations:
        if label.endswith(inv_abbr):
            corrected_abbr = inv_abbr[:-1] # 末尾の"("を削除
            label = label.replace(inv_abbr, corrected_abbr)
            logger.warning(f"Sanitize: Corrected likely malformed abbreviation in '{original_label}' from '{inv_abbr}' to '{corrected_abbr}', resulting in '{label}'. Review chordmap source.")
            break # 最初に見つかったものだけ修正

    # music21は "Bbm" (B flat minor) より "B-m" を好む
    label = re.sub(r'^([A-Ga-g])b([mMdDaAuUgG0-9sS#-/]+)', r'\1-\2', label)

    # スラッシュコード "C/Bb" -> "C/B-" (ベース音のフラット)
    if '/' in label:
        parts = label.split('/')
        if len(parts) == 2:
            bass_note_part = parts[1]
            # ベース音部分だけのサニタイズ (再帰呼び出しを避けるため簡易的に)
            if bass_note_part.startswith("Bb"): bass_note_part = "B-" + bass_note_part[2:]
            elif bass_note_part.startswith("Eb"): bass_note_part = "E-" + bass_note_part[2:]
            # ... 他のフラット音も同様
            label = f"{parts[0]}/{bass_note_part}"


    # 最終的な品質チェック (例: "CM" -> "Cmaj", "Cm" -> "Cmin")
    # music21は "maj" や "min" を推奨
    # ただし、"CM7" は "Cmaj7" のことなので、この種の置換は注意が必要
    label = label.replace('M', 'maj') # Cmaj7 はCM7ではなくCmaj7に

    if label != original_label:
        logger.info(f"Sanitize: Final from '{original_label}' -> '{label}'.")
    
    # さらに、この段階で test parse してみる（ただし、エラーが多いとログが冗長になる）
    try:
        test_cs = harmony.ChordSymbol(label)
        if not test_cs.pitches and label.lower() != "rest":
             logger.warning(f"Sanitize: ChordSymbol '{label}' created, but has no pitches (e.g. an empty symbol).")
    except harmony.HarmonyException as he:
        logger.warning(f"Sanitize: Resulting label '{label}' (from '{original_label}') still causes HarmonyException: {he}")
    except Exception as e_final_parse:
        logger.warning(f"Sanitize: Resulting label '{label}' (from '{original_label}') causes other Exception: {e_final_parse}")

    return label

# --- END OF FILE generators/core_music_utils.py ---
