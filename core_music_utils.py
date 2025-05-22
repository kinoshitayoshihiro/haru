# --- START OF FILE generators/core_music_utils.py (真・最終統合版) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, List # Tupleを削除 (build_scale_objectの戻り値型修正のため)
import re

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    ts_str = ts_str or "4/4"
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning(f"GTSO: Invalid TS '{ts_str}'. Default 4/4.")
        return meter.TimeSignature("4/4")
    except Exception as e_ts:
        logger.error(f"GTSO: Error for TS '{ts_str}': {e_ts}. Default 4/4.", exc_info=True)
        return meter.TimeSignature("4/4")

# o3さん版 build_scale_object (戻り値型を Optional[scale.ConcreteScale] から scale.ConcreteScale へ)
# 常に何らかのScaleオブジェクトを返すため
def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> scale.ConcreteScale:
    mode_key = (mode_str or "major").lower()
    tonic_val = tonic_str or "C"
    try:
        tonic_p = pitch.Pitch(tonic_val)
    except Exception:
        logger.error(f"BuildScale: Invalid tonic '{tonic_val}'. Defaulting to C.")
        tonic_p = pitch.Pitch("C")
    
    mode_map: Dict[str, Any] = { # Any は type[scale.ConcreteScale] の意
        "ionian": scale.MajorScale, "major": scale.MajorScale,
        "dorian": scale.DorianScale, "phrygian": scale.PhrygianScale,
        "lydian": scale.LydianScale, "mixolydian": scale.MixolydianScale,
        "aeolian": scale.MinorScale, "minor": scale.MinorScale,
        "locrian": scale.LocrianScale,
        "harmonicminor": scale.HarmonicMinorScale,
        "melodicminor": scale.MelodicMinorScale,
    }
    scl_cls = mode_map.get(mode_key, scale.MajorScale) # デフォルトはMajorScale
    if scl_cls is scale.MajorScale and mode_key not in mode_map : # 未知のモードの場合の警告
        logger.warning(f"BuildScale: Unknown mode '{mode_key}'. Using MajorScale with {tonic_p.name}.")
    try:
        return scl_cls(tonic_p)
    except Exception as e_create:
        logger.error(f"BuildScale: Error creating '{scl_cls.__name__}' for {tonic_p.name}: {e_create}. Fallback C Major.", exc_info=True)
        return scale.MajorScale(pitch.Pitch("C"))


def _expand_tension_block(t_block: str) -> str:
    """Helper to convert a raw tension segment to music21‑friendly string."""
    t_block = t_block.strip().lower() # 比較のため小文字に
    if not t_block: return ""
    
    if t_block.startswith(("#", "b")):
        return t_block # 例: #9, b13
    if t_block.startswith("add"): # addキーワードがあればそれを尊重
        # addの後に続く数字が有効か確認 (例: addXYZ -> add)
        match_add_num = re.match(r'add(\d+)', t_block)
        if match_add_num:
            return f"add{match_add_num.group(1)}"
        return "add" # 数字がなければ単に"add" (これは実質エラーだが...)
    if t_block.isdigit(): # bare digits
        return f"add{t_block}" #例: 11 -> add11
    # その他 (omit等)
    if t_block in ["omit3", "omit5", "omitroot"]:
        return t_block
    return t_block # 不明なものはそのまま

def sanitize_chord_label(label: Optional[str]) -> str: # "Rest" or sanitized string
    if not label or not isinstance(label, str):
        logger.warning(f"Sanitize: Label '{label}' is None or not str. Returning 'Rest'.")
        return "Rest"
    
    original_label = label
    sanitized = label.strip()

    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"Sanitize: '{original_label}' to 'Rest'.")
        return "Rest"

    # 1. フラット正規化 (b -> -, bb -> --)
    sanitized = re.sub(r'^([A-Ga-g])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-Ga-g])b(?![#b])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-Ga-g])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-Ga-g])b(?![#b])', r'/\1-', sanitized)
    
    # 2. 括弧の不均衡修正 (Harugoro様のパッチ適用)
    if '(' in sanitized and ')' not in sanitized:
        logger.info(f"Sanitize: Detected unclosed parenthesis in '{original_label}'.")
        base_part = sanitized.split('(')[0]
        content_after_paren = sanitized.split('(', 1)[1] if len(sanitized.split('(', 1)) > 1 else ""
        
        # 括弧閉じ忘れケースで、addXX があればそれを優先的に保持
        # 例: Am7(add11 -> Am7add11
        # 例: Fmaj7(add9,13 のような複数テンションには未対応（単純splitのため）
        match_add_in_unclosed = re.search(r'(add\d+)', content_after_paren, flags=re.I)
        if match_add_in_unclosed:
            sanitized = base_part + match_add_in_unclosed.group(1).lower()
            logger.info(f"Sanitize: Recovered '{match_add_in_unclosed.group(1)}' from unclosed paren -> '{sanitized}'")
        else: # addXX が見つからなければ括弧以前のみ
            sanitized = base_part
            logger.info(f"Sanitize: Kept content before unclosed paren -> '{sanitized}'")

    # 3. altコード展開 (括弧処理の前に実施、正しいグループ参照\g<1>を使用)
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt', r'\g<1>7#9b13', sanitized, flags=re.IGNORECASE)

    # 4. 括弧の平坦化 (o3さん版の `_expand_tension_block` と Harugoro様パッチを適用)
    prev_sanitized_state = ""
    loop_count = 0
    while '(' in sanitized and ')' in sanitized and sanitized != prev_sanitized_state and loop_count < 5:
        prev_sanitized_state = sanitized
        loop_count += 1
        match = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if match:
            base, inner_content, suf = match.groups()
            # 括弧内をコンマで分割し、各要素を _expand_tension_block で整形し、再連結 (Harugoro様パッチの思想)
            tension_parts = [seg.strip() for seg in inner_content.split(',')]
            expanded_inner_content = "".join(_expand_tension_block(p) for p in tension_parts) # これでFmaj7(add9,13)がFmaj7add9add13になるはず
            sanitized = base + expanded_inner_content + suf
        else:
            break

    # 5. 品質関連の正規化
    sanitized = re.sub(r'(?i)ø7?\b', 'm7b5', sanitized)
    sanitized = re.sub(r'(?i)half[- ]?dim\b', 'm7b5', sanitized)
    sanitized = sanitized.replace('dimished', 'dim') # typo
    sanitized = re.sub(r'(?i)diminished(?!7)', 'dim', sanitized)
    sanitized = re.sub(r'(?i)diminished7', 'dim7', sanitized)
    sanitized = sanitized.replace('domant7', '7') # typo
    sanitized = re.sub(r'(?i)dominant7?\b', '7', sanitized)
    sanitized = re.sub(r'(?i)minor7', 'm7', sanitized)
    sanitized = re.sub(r'(?i)minor9', 'm9', sanitized)
    sanitized = re.sub(r'(?i)minor11', 'm11', sanitized)
    sanitized = re.sub(r'(?i)minor13', 'm13', sanitized)
    sanitized = re.sub(r'(?i)min(?!or\b|\.|m7b5)', 'm', sanitized)
    sanitized = re.sub(r'(?i)augmented', 'aug', sanitized)
    sanitized = re.sub(r'(?i)major', 'maj', sanitized)

    # 6. addキーワードとそれに続く数字の正規化 (例: Am7add11)
    #    (括弧展開で add が消えて 数字だけが連結された場合の対策 例: Fmaj79 -> Fmaj7add9)
    sanitized = re.sub(r'(?i)(m[aj]?[79]?|7sus4?)(\d{2,})(?!add)', r'\1add\2', sanitized)


    # 7. maj9(#11) -> maj7#11add9 修正 (o3さん提案)
    sanitized = re.sub(r'(maj)9(#\d+)', r'\17\2add9', sanitized, flags=re.IGNORECASE)

    # 8. susコードの正規化
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized)
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)
    try:
        sanitized = re.sub(r'(?i)(sus)(?![24\d])', r'\g<1>4', sanitized)
    except re.error as e_re_sus:
        logger.warning(f"Sanitize: Regex error sus normal: {e_re_sus}. Label: '{sanitized}'")

    # 9. 最終的な全体のスペース・カンマ除去
    sanitized = re.sub(r'[,\s]', '', sanitized)
    
    # 10. 末尾に残った可能性のある不要な文字の除去
    sanitized = re.sub(r'[^a-zA-Z0-9#\-/\u00f8]+$', '', sanitized)

    if sanitized != original_label:
        logger.info(f"Sanitize: '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"Sanitize: Label '{original_label}' no change.")
    return sanitized

def get_music21_chord_object(chord_label_str: Optional[str], current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    if not isinstance(chord_label_str, str) or not chord_label_str.strip():
        logger.debug(f"get_music21_obj: Input '{chord_label_str}' empty/not str. As Rest.")
        return None

    sanitized_label = sanitize_chord_label(chord_label_str)
    
    if not sanitized_label or sanitized_label.upper() == "REST":
        logger.debug(f"get_music21_obj: Sanitized to '{sanitized_label}'. As Rest.")
        return None

    cs = None
    try:
        cs = harmony.ChordSymbol(sanitized_label)
        if not cs.pitches: # ChordSymbol("Rest") など
            logger.debug(f"get_music21_obj: Parsed '{sanitized_label}' (orig:'{chord_label_str}') but no pitches (figure: {cs.figure}). As Rest.")
            return None
        logger.info(f"get_music21_obj: Successfully parsed '{sanitized_label}' (orig:'{chord_label_str}') as {cs.figure}")
        return cs
    except Exception as e: # music21.harmony.HarmonyException や music21.exceptions21.Music21Exception を含む
        logger.error(f"get_music21_obj: Exception for '{sanitized_label}' (orig:'{chord_label_str}'): {type(e).__name__}: {e}. As Rest.")
    return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    
    # 最新のsanitize_chord_labelの挙動に合わせた期待値
    final_expected_outcomes_v4 = {
        "E7(b9)": "E7b9",
        "C7(#9,b13)": "C7#9b13",
        "C7(b9,#11,add13)": "C7b9#11add13",
        "C7alt": "C7#9b13",
        "Fmaj7(add9)": "Fmaj7add9",
        "Fmaj7(add9,13)": "Fmaj7add9add13", 
        "Bbmaj7(#11)": "B-maj7#11", 
        "Cø7": "Cm7b5", "Cm7b5": "Cm7b5", "Cø": "Cm7b5",
        "Am7(add11)": "Am7add11",
        "Am7(add11": "Am7add11", # 括弧閉じ忘れ対応
        "Dsus": "Dsus4", "Gsus4": "Gsus4", "Asus2": "Asus2", "Csus44": "Csus4",
        "Bbmaj9(#11)": "B-maj7#11add9", # maj9(#11) -> maj7#11add9
        "F#7": "F#7", "Calt": "C7#9b13", "silence": "Rest",
        "Cminor7": "Cm7", "Gdominant7": "G7",
        "Bb": "B-", "Ebm": "E-m", "F#": "F#", "Dbmaj7": "D-maj7",
        "G7SUS": "G7sus4" # 大文字SUSのテスト
    }
    
    other_tests_v4 = [
        "N.C.", "Rest", "", "  Db  ", "GM7(", "G diminished",
        "C/Bb", "CbbM7", "C##M7", "C augmented", 
        "C major7", "d minor", "e dim", "G AUG",
        "bad(input", # 最終的に"bad"になる想定
        "C(omit3)", "Fmaj7(add9" # omitと閉じ忘れadd
    ]
    
    all_labels_to_test_v4 = sorted(list(set(list(final_expected_outcomes_v4.keys()) + other_tests_v4)))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro x o3 Final Polish v2) ---")
    s_parses_v4 = 0; f_parses_v4 = 0; r_count_v4 = 0; exp_match_count_v4 = 0; exp_mismatch_count_v4 = 0

    for label_orig in all_labels_to_test_v4:
        expected_val = final_expected_outcomes_v4.get(label_orig)
        sanitized_res = sanitize_chord_label(label_orig)
        
        eval_str = ""
        if expected_val:
            if sanitized_res == expected_val: eval_str = "✔ (Exp OK)"; exp_match_count_v4 +=1
            else: eval_str = f"✘ (Exp: '{expected_val}')"; exp_mismatch_count_v4 +=1
        
        print(f"Original: '{label_orig:<18}' -> Sanitized: '{sanitized_res:<25}' {eval_str}")

        cs_obj_v4 = get_music21_chord_object(label_orig) 
        
        if cs_obj_v4:
            try: fig_disp = cs_obj_v4.figure
            except: fig_disp = "[ErrFig]"
            print(f"  music21 obj: {fig_disp:<25} (Pitches: {[p.name for p in cs_obj_v4.pitches]})"); s_parses_v4 += 1
        elif sanitize_chord_label(label_orig) == "Rest": # sanitizeが"Rest"を返した場合
            print(f"  Interpreted as Rest by sanitize_chord_label.")
            r_count_v4 += 1
        else: # パース失敗
            print(f"  music21 FAILED or NO PITCHES for sanitized '{sanitized_res}' (get_obj returned None)")
            f_parses_v4 += 1

    print(f"\n--- Test Summary (Harugoro x o3 Final Polish v2) ---")
    total_labels_final_v4 = len(all_labels_to_test_v4)
    attempted_to_parse_count_v4 = total_labels_final_v4 - r_count_v4

    print(f"Total unique labels processed: {total_labels_final_v4}")
    if exp_match_count_v4 + exp_mismatch_count_v4 > 0:
        print(f"Matches with expected sanitization: {exp_match_count_v4}")
        print(f"Mismatches with expected sanitization: {exp_mismatch_count_v4}")
    print(f"Successfully parsed by music21 (Chord obj with pitches): {s_parses_v4} / {attempted_to_parse_count_v4} non-Rest attempts")
    print(f"Failed to parse or no pitches by music21: {f_parses_v4}")
    print(f"Explicitly 'Rest' by sanitize_chord_label: {r_count_v4}")
    
    overall_success_rate_v4 = ((s_parses_v4 + r_count_v4) / total_labels_final_v4 * 100) if total_labels_final_v4 > 0 else 0
    print(f"Estimated overall functional success (incl. Rests): {overall_success_rate_v4:.2f}%")

# --- END OF FILE generators/core_music_utils.py ---
