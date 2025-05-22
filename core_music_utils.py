# --- START OF FILE generators/core_music_utils.py (Harugoro x o3 統合最終版 v2) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, Tuple, List
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

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> Optional[scale.ConcreteScale]:
    mode_key = (mode_str or "major").lower()
    tonic_val = tonic_str or "C"
    try:
        tonic_p = pitch.Pitch(tonic_val)
    except Exception:
        logger.error(f"BuildScale: Invalid tonic '{tonic_val}'. Defaulting to C.")
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
    scl_cls = mode_map.get(mode_key)
    if scl_cls:
        try:
            return scl_cls(tonic_p)
        except Exception as e_create:
            logger.error(f"BuildScale: Error creating '{scl_cls.__name__}' for {tonic_p.name}: {e_create}. Fallback C Major.", exc_info=True)
            return scale.MajorScale(pitch.Pitch("C"))
    else: # scl_cls is None if mode_key not in mode_map
        logger.warning(f"BuildScale: Unknown mode '{mode_key}'. Using MajorScale with {tonic_p.name}.")
        return scale.MajorScale(tonic_p)


def _expand_tension_block(t_block: str) -> str:
    """Helper to convert a raw tension segment to music21‑friendly string."""
    t_block = t_block.strip()
    if not t_block: return ""
    # music21 can handle (#9), (b9), (add11), (11) in some contexts, but likes "add" for bare numbers generally
    if t_block.startswith(("#", "b")):
        return t_block # 例: #9, b13
    if t_block.lower().startswith("add"):
        return t_block # 例: add11
    if t_block.isdigit(): # bare digits
        return f"add{t_block}" #例: 11 -> add11
    return t_block # その他のキーワード (omitなど) はそのまま

def sanitize_chord_label(label: Optional[str]) -> str: # "Rest" or sanitized string
    if not label or not isinstance(label, str):
        logger.warning(f"Sanitize: Label '{label}' is None or not str. Returning 'Rest'.")
        return "Rest"
    
    original_label = label
    sanitized = label.strip()

    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"Sanitize: '{original_label}' to 'Rest'.")
        return "Rest"

    # 1. フラット正規化: ルート音とスラッシュベース音の 'b' を '-' に、'bb' を '--' に
    # (テンション内の b/# はこの段階では変更しない)
    sanitized = re.sub(r'^([A-Ga-g])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-Ga-g])b(?![#b])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-Ga-g])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-Ga-g])b(?![#b])', r'/\1-', sanitized)
    
    # 2. 括弧の不均衡修正 (開き括弧のみで閉じ括弧がない場合)
    if '(' in sanitized and ')' not in sanitized:
        # 開き括弧より前の部分 + 開き括弧以降をテンションブロックとして処理しようと試みる
        parts_unclosed = sanitized.split('(', 1)
        if len(parts_unclosed) > 1 and parts_unclosed[1].strip(): # 括弧以降に内容がある場合
             expanded_tension = _expand_tension_block(parts_unclosed[1])
             sanitized = parts_unclosed[0] + expanded_tension # 括弧なしで連結
             logger.info(f"Sanitize: Corrected unclosed parenthesis for '{original_label}' to '{sanitized}'")
        else: # 括弧以降が空か、括弧がない場合
            sanitized = parts_unclosed[0] # 括弧より前だけ取る
            logger.info(f"Sanitize: Dangling '(', kept content before it for '{original_label}' to '{sanitized}'")


    # 3. altコード展開 (括弧処理の前に実施、o3さん版の正確なグループ参照)
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt', r'\g<1>7#9b13', sanitized, flags=re.IGNORECASE)

    # 4. 括弧の平坦化 (o3さん版の `_expand_tension_block` を活用)
    #    ループでネストされた括弧も処理 (例: C((#9,11)))
    prev_sanitized_state = ""
    loop_count = 0
    while '(' in sanitized and ')' in sanitized and sanitized != prev_sanitized_state and loop_count < 5:
        prev_sanitized_state = sanitized
        loop_count += 1
        match = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if match:
            base, inner_content, suf = match.groups()
            # 括弧内をコンマで分割し、各要素を _expand_tension_block で整形し、再連結
            tension_parts = [seg.strip() for seg in inner_content.split(',')]
            expanded_inner_content = "".join(_expand_tension_block(p) for p in tension_parts)
            sanitized = base + expanded_inner_content + suf
        else:
            break # マッチしなくなったらループ終了

    # 5. 品質関連の正規化 (majは基本的に維持、minはmへ等)
    #    タイポや冗長な表現も修正
    sanitized = re.sub(r'(?i)ø7?\b', 'm7b5', sanitized)
    sanitized = re.sub(r'(?i)half[- ]?dim\b', 'm7b5', sanitized)
    sanitized = sanitized.replace('dimished', 'dim')
    sanitized = re.sub(r'(?i)diminished(?!7)', 'dim', sanitized)
    sanitized = re.sub(r'(?i)diminished7', 'dim7', sanitized)
    sanitized = sanitized.replace('domant7', '7')
    sanitized = re.sub(r'(?i)dominant7?\b', '7', sanitized)
    sanitized = re.sub(r'(?i)minor7', 'm7', sanitized) # minorX -> mX
    sanitized = re.sub(r'(?i)minor9', 'm9', sanitized)
    sanitized = re.sub(r'(?i)minor11', 'm11', sanitized)
    sanitized = re.sub(r'(?i)minor13', 'm13', sanitized)
    sanitized = re.sub(r'(?i)min(?!or\b|\.|m7b5)', 'm', sanitized) # min, Cm -> m, Cm (m7b5内のmは除く)
    sanitized = re.sub(r'(?i)augmented', 'aug', sanitized)
    sanitized = re.sub(r'(?i)major', 'maj', sanitized) # Major -> maj (小文字統一)
                                                       # M -> maj はしない (Fmaj7などをFM7にしたくないため)
                                                       
    # 6. "add"キーワードの最終確認 (既にあればそのまま、なければ追加のニュアンス)
    #    この時点で Am7add11, Fmaj7add9add13 などが期待される形
    #    Fmaj79 -> Fmaj7add9 のような処理 (o3さん提案ではないが、前の議論から)
    sanitized = re.sub(r'(maj[79]|m[79]?)(\d+)(?!add|\d)', r'\1add\2', sanitized, flags=re.IGNORECASE)

    # 7. maj9(#11) 問題のピンポイント修正 (o3さん提案)
    #    B-maj9#11 -> B-maj7#11add9
    sanitized = re.sub(r'(maj)9(#\d+)', r'\17\2add9', sanitized, flags=re.IGNORECASE) # #11 は #\d+ でキャプチャ

    # 8. susコードの正規化 (Harugoro様修正 \g<1>4 を適用)
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized)
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)
    try:
        sanitized = re.sub(r'(?i)(sus)(?![24\d])', r'\g<1>4', sanitized)
    except re.error as e_re_sus:
        logger.warning(f"Sanitize: Regex error sus normal: {e_re_sus}. Label: '{sanitized}'")

    # 9. 全体的なスペース・カンマの最終除去
    sanitized = re.sub(r'[,\s]', '', sanitized)

    # 10. 末尾に予期せず残った変化記号や特殊文字の除去
    sanitized = re.sub(r'[^a-zA-Z0-9#\-/\u00f8]+$', '', sanitized) # ø (U+00F8) は許可

    if sanitized != original_label:
        logger.info(f"Sanitize: '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"Sanitize: Label '{original_label}' no change.")
    return sanitized


def get_music21_chord_object(chord_label_str: str, current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    # ... (これは前回 (Harugoro x o3 統合最終版) のままでOK) ...
    if not isinstance(chord_label_str, str) or not chord_label_str.strip():
        logger.debug(f"get_music21_chord_object: Input '{chord_label_str}' is empty or not string. Interpreted as Rest.")
        return None

    sanitized_label = sanitize_chord_label(chord_label_str) # 新しいsanitize_chord_labelを使用
    
    if not sanitized_label or sanitized_label.upper() == "REST":
        logger.debug(f"get_music21_chord_object: Sanitized to '{sanitized_label}'. Interpreted as Rest.")
        return None

    cs = None
    try:
        cs = harmony.ChordSymbol(sanitized_label)
        if not cs.pitches:
            logger.debug(f"get_music21_chord_object: Parsed '{sanitized_label}' (orig:'{chord_label_str}') but has no pitches (figure: {cs.figure}). Treating as Rest.")
            return None
        logger.debug(f"get_music21_chord_object: Successfully parsed '{sanitized_label}' (orig:'{chord_label_str}') as {cs.figure}")
        return cs
    except harmony.HarmonyException as he:
        logger.error(f"get_music21_chord_object: HarmonyException for '{sanitized_label}' (orig:'{chord_label_str}'): {he}. Treating as Rest.")
    except music21.exceptions21.Music21Exception as m21e:
        logger.error(f"get_music21_chord_object: Music21Exception for '{sanitized_label}' (orig:'{chord_label_str}'): {m21e}. Treating as Rest.")
    except Exception as e:
        logger.error(f"get_music21_chord_object: Unexpected error for '{sanitized_label}' (orig:'{chord_label_str}'): {e}. Treating as Rest.", exc_info=True)
    
    return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    
    # 最新のsanitize_chord_labelの挙動に合わせた期待値 (一部はmusic21の解釈に依存)
    final_expected_outcomes_v3 = {
        "E7(b9)": "E7b9",
        "C7(#9,b13)": "C7#9b13",
        "C7(b9,#11,add13)": "C7b9#11add13",
        "C7alt": "C7#9b13",
        "Fmaj7(add9)": "Fmaj7add9",
        "Fmaj7(add9,13)": "Fmaj7add9add13", # 複数のaddも連結される想定
        "Bbmaj7(#11)": "B-maj7#11",     # これがB-maj7#11add (maj9#11とは違う) になるか
        "Cø7": "Cm7b5",
        "Cm7b5": "Cm7b5",
        "Cø": "Cm7b5",
        "Am7(add11)": "Am7add11",
        "Am7(add11": "Am7add11", # 不完全括弧の修正後の期待値
        "Dsus": "Dsus4", "Gsus4": "Gsus4", "Asus2": "Asus2", "Csus44": "Csus4",
        "Bbmaj9(#11)": "B-maj7#11add9", # maj9(#11) -> maj7(#11)add9 への変換期待
        "F#7": "F#7",
        "Calt": "C7#9b13",
        "silence": "Rest",
        "Cminor7": "Cm7",
        "Gdominant7": "G7",
        "Bb": "B-", "Ebm": "E-m", "F#": "F#", "Dbmaj7": "D-maj7"
    }
    
    other_tests_v3 = [
        "N.C.", "Rest", "", "  Db  ", "GM7(",
        "C/Bb", "CbbM7", "C##M7", "C augmented", "G diminished",
        "C major7", "F Major9", "d minor", "e dim", "G AUG",
        "G7SUS"
    ]
    
    all_labels_to_test_v3 = sorted(list(set(list(final_expected_outcomes_v3.keys()) + other_tests_v3)))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro x o3 Final Polish) ---")
    s_parses_v3 = 0; f_parses_v3 = 0; r_count_v3 = 0; exp_match_count_v3 = 0; exp_mismatch_count_v3 = 0

    for label_orig in all_labels_to_test_v3:
        expected_val = final_expected_outcomes_v3.get(label_orig)
        sanitized_res = sanitize_chord_label(label_orig)
        
        eval_str = ""
        if expected_val:
            if sanitized_res == expected_val: eval_str = "✔ (Exp OK)"; exp_match_count_v3 +=1
            else: eval_str = f"✘ (Exp: '{expected_val}')"; exp_mismatch_count_v3 +=1
        
        print(f"Original: '{label_orig:<18}' -> Sanitized: '{sanitized_res:<25}' {eval_str}")

        cs_obj_v3 = get_music21_chord_object(label_orig) 
        
        if cs_obj_v3:
            try: fig_disp = cs_obj_v3.figure
            except: fig_disp = "[ErrFig]"
            print(f"  music21 obj: {fig_disp:<25} (Pitches: {[p.name for p in cs_obj_v3.pitches]})"); s_parses_v3 += 1
        elif sanitized_res == "Rest":
            print(f"  Interpreted as Rest by sanitize_chord_label.")
            r_count_v3 += 1
        else: # パース失敗 (get_music21_chord_objectがNoneを返し、かつsanitized_resが"Rest"でない)
            # get_music21_chord_object内のログで詳細が出る
            print(f"  music21 FAILED or NO PITCHES for sanitized '{sanitized_res}'")
            f_parses_v3 += 1

    print(f"\n--- Test Summary (Harugoro x o3 Final Polish) ---")
    total_labels_final_v3 = len(all_labels_to_test_v3)
    attempted_to_parse_count_v3 = total_labels_final_v3 - r_count_v3

    print(f"Total unique labels processed: {total_labels_final_v3}")
    if exp_match_count_v3 + exp_mismatch_count_v3 > 0:
        print(f"Matches with expected sanitization: {exp_match_count_v3}")
        print(f"Mismatches with expected sanitization: {exp_mismatch_count_v3}")
    print(f"Successfully parsed by music21 (got Chord obj with pitches): {s_parses_v3} / {attempted_to_parse_count_v3} non-Rest attempts")
    print(f"Failed to parse or no pitches by music21: {f_parses_v3}")
    print(f"Explicitly identified as 'Rest' by sanitize_chord_label: {r_count_v3}")
    
    overall_success_rate_v3 = ((s_parses_v3 + r_count_v3) / total_labels_final_v3 * 100) if total_labels_final_v3 > 0 else 0
    print(f"Estimated overall functional success (incl. Rests): {overall_success_rate_v3:.2f}%")

# --- END OF FILE generators/core_music_utils.py ---
