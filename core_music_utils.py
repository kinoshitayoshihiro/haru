# --- START OF FILE generators/core_music_utils.py (真・完成版) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, List
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

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> scale.ConcreteScale:
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
    scl_cls = mode_map.get(mode_key, scale.MajorScale)
    if scl_cls is scale.MajorScale and mode_key not in mode_map :
        logger.warning(f"BuildScale: Unknown mode '{mode_key}'. Using MajorScale with {tonic_p.name}.")
    try:
        return scl_cls(tonic_p)
    except Exception as e_create:
        logger.error(f"BuildScale: Error creating '{scl_cls.__name__}' for {tonic_p.name}: {e_create}. Fallback C Major.", exc_info=True)
        return scale.MajorScale(pitch.Pitch("C"))

def _expand_tension_block_final(seg: str) -> str: # Renamed for clarity
    seg = seg.strip().lower()
    if not seg: return ""
    if seg.startswith(("#", "b")): return seg
    if seg.startswith("add"):
        match_add_num = re.match(r'add(\d+)', seg)
        if match_add_num: return f"add{match_add_num.group(1)}"
        return "" 
    if seg.isdigit(): return f"add{seg}"
    if seg in ["omit3", "omit5", "omitroot"]: return seg
    logger.debug(f"Sanitize (_expand_tension_block): Unknown tension '{seg}', passing as is.")
    return seg

# o3さん提案のコールバック関数 for addXX
def _addify_if_needed(match: re.Match) -> str:
    prefix = match.group(1) or "" # prefix can be None if it's start of string
    number = match.group(2)
    # すでにadd, sus, maj, m, dim, aug, 7thなどの品質やルート音で終わっている場合は変換しない
    # X7 11 -> X7add11
    # C 11  -> Cadd11
    # Cmaj11 (これはmajの後に数字なのでaddしない) -> X
    # Amadd9 ->そのまま
    # Dsus11 -> Dsusadd11 -> X (Dsus4add11ならOK)
    
    # 簡易的なチェック：prefixが品質や数字で終わっているか
    if prefix.lower().endswith(('sus', 'add', 'maj', 'm', 'dim', 'aug', 'b5', 'ø', '7', '9', '11', '13')):
        # さらに、prefixの末尾が数字の場合(例: G7 で 11が続く)は、
        # その数字がテンションの一部として既に解釈されるべきか、
        # それとも新しい "add" テンションとして解釈されるべきか。
        # music21は G711 を G7(add11) とは解釈しないので、addを補う必要があるケースが多い。
        # ただし、Am7add11 のような場合は Am7add11add11 になってしまう。
        # ここでは、"bare number"の前にスペースがないことを前提とし、
        # prefixの末尾が数字 *でない* 場合にaddを付加する、というより安全な方向に。
        if not prefix or not prefix[-1].isdigit():
             return f'{prefix}add{number}'
        return match.group(0) # そのまま返す (例: maj7 の後の 11 は maj7add11 にしたいが、Amadd11 は Amadd11add11 にしたくない)
                               # このロジックはまだ改善の余地あり。一旦o3さんの「基本的にはadd」方針で。
    return f'{prefix}add{number}'


def sanitize_chord_label(label: Optional[str]) -> Optional[str]: # o3さんスタイル: RestはNone
    if not label or not isinstance(label, str):
        logger.debug(f"Sanitize: Label '{label}' None/not str -> None (Rest)")
        return None 
    
    original_label = label
    sanitized = label.strip()

    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"Sanitize: '{original_label}' -> None (Rest direct match).")
        return None

    # 0. ワードベースの品質変換
    word_map = {
        r'(?i)\b([A-Ga-g][#\-]*)\s+minor\b': r'\1m',
        r'(?i)\b([A-Ga-g][#\-]*)\s+major\b': r'\1maj',
        r'(?i)\b([A-Ga-g][#\-]*)\s+dim\b':   r'\1dim',
        r'(?i)\b([A-Ga-g][#\-]*)\s+aug\b':   r'\1aug',
    }
    for pat, rep in word_map.items():
        sanitized = re.sub(pat, rep, sanitized)
    
    # 0b. ルート音の先頭文字を大文字化 (o3さん提案)
    sanitized = re.sub(r'^([a-g])', lambda m: m.group(1).upper(), sanitized)


    # 1. ルート音とスラッシュベース音のフラット正規化
    sanitized = re.sub(r'^([A-G])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-G])b(?![#b])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-G])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-G])b(?![#b])', r'/\1-', sanitized)
    
    # 1b. SUS正規化 (o3さん最終パッチを参考に、処理順序を調整)
    sanitized = re.sub(r'(?i)([A-G][#\-]?(?:\d+)?)(sus)(?![24\d])', r'\g<1>sus4', sanitized)
    sanitized = re.sub(r'(?i)(sus)([24])', r'sus\2', sanitized)
    # ── 重複 addXX を 1 個に統合 ──────────────────────────
    sanitized = re.sub(r'(add\\d+)(?=.*\\1)', '', sanitized)

    # ── alt 変換後の 13 の冗長 add を除去 ──────────────
    sanitized = sanitized.replace('badd13', 'b13')\
                         .replace('#add13', '#13')

    # ── sus44 → sus4 ガード（念のため再確認） ───────────
    sanitized = re.sub(r'sus([24])\\1$', r'sus\\1', sanitized, flags=re.I)
    # SUS 補完と重複ガード
    sanitized = re.sub(r'(?i)(?<!\d)(sus)(?![24])', 'sus4', sanitized)
    sanitized = re.sub(r'sus([24])\1$', r'sus\1', sanitized, flags=re.I)

    # addXX 重複除去（最終 add だけ残す）
    sanitized = re.sub(r'(add\d+)(?=.*\1)', '', sanitized)

    # alt 展開
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt',
                       r'\g<1>7#9b13', sanitized, flags=re.I)
    sanitized = sanitized.replace('badd13', 'b13').replace('#add13', '#13')

    # ── ①②③ まとめて解決 ──────────────────────────

    # alt ⇒ 7#9b13 展開直後に置く
    sanitized = sanitized.replace('badd13', 'b13').replace('#add13', '#13')

    # 連続 “addaddXX” → “addXX”
    sanitized = re.sub(r'addadd', 'add', sanitized, flags=re.I)

    # 重複 addXX 語が 2 回以上並んでいたら 1 つに
    sanitized = re.sub(r'(add\d+)(?=.*\\1)', '', sanitized, flags=re.I)

    # 2. 括弧の不均衡修正
    if '(' in sanitized and ')' not in sanitized:
        logger.info(f"Sanitize: Detected unclosed parenthesis in '{original_label}'.")
        base_part = sanitized.split('(')[0]
        content_after_paren = sanitized.split('(', 1)[1] if len(sanitized.split('(', 1)) > 1 else ""
        if content_after_paren.strip():
            recovered_tensions = "".join(_expand_tension_block_final(p) for p in content_after_paren.split(','))
            if recovered_tensions:
                sanitized = base_part + recovered_tensions
                logger.info(f"Sanitize: Recovered from unclosed: '{recovered_tensions}' -> '{sanitized}'")
            else: sanitized = base_part; logger.info(f"Sanitize: No valid tensions from unclosed, kept -> '{sanitized}'")
        else: sanitized = base_part; logger.info(f"Sanitize: Empty after unclosed, kept -> '{sanitized}'")

    # 3. altコード展開
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt', r'\g<1>7#9b13', sanitized, flags=re.IGNORECASE)
    
    # 4. 括弧の平坦化
    prev_sanitized_state = "" ; loop_count = 0
    while '(' in sanitized and ')' in sanitized and sanitized != prev_sanitized_state and loop_count < 5:
        prev_sanitized_state = sanitized; loop_count += 1
        match = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if match:
            base, inner_content, suf = match.groups()
            tension_parts = [seg.strip() for seg in inner_content.split(',')]
            expanded_inner_content = "".join(_expand_tension_block_final(p) for p in tension_parts)
            sanitized = base + expanded_inner_content + suf
        else: break

    # 5. 品質関連の正規化
    sanitized = re.sub(r'(?i)ø7?\b', 'm7b5', sanitized)
    sanitized = re.sub(r'(?i)half[- ]?dim\b', 'm7b5', sanitized)
    sanitized = sanitized.replace('dimished', 'dim')
    sanitized = re.sub(r'(?i)diminished(?!7)', 'dim', sanitized)
    sanitized = re.sub(r'(?i)diminished7', 'dim7', sanitized)
    sanitized = sanitized.replace('domant7', '7')
    sanitized = re.sub(r'(?i)dominant7?\b', '7', sanitized)
    sanitized = re.sub(r'(?i)major7', 'maj7', sanitized)
    sanitized = re.sub(r'(?i)major9', 'maj9', sanitized)
    sanitized = re.sub(r'(?i)major13', 'maj13', sanitized)
    sanitized = re.sub(r'(?i)minor7', 'm7', sanitized)
    sanitized = re.sub(r'(?i)minor9', 'm9', sanitized)
    sanitized = re.sub(r'(?i)minor11', 'm11', sanitized)
    sanitized = re.sub(r'(?i)minor13', 'm13', sanitized)
    sanitized = re.sub(r'(?i)min(?!or\b|\.|m7b5)', 'm', sanitized) 
    sanitized = re.sub(r'(?i)aug(?!mented)', 'aug', sanitized)
    sanitized = re.sub(r'(?i)augmented', 'aug', sanitized)
    sanitized = re.sub(r'(?i)major(?!7|9|13|\b)', 'maj', sanitized) 
                                                       
    # 6. o3さん提案のコールバック関数 _addify_if_needed を使用したadd補完
    #    look-behind を使わない安全な方法
    #    パターン: (何らかのコードのルートや品質)([#b]?\d{1,2})? の後に (\d{2,}) が続く場合
    #    (ルートや品質)(２桁以上の数字) → (ルートや品質)add(２桁以上の数字)
    #    この正規表現はまだ改善が必要かもしれないが、基本的な考え方として導入
    try: # _addify_if_needed を使うために re.sub に関数を渡す
        sanitized = re.sub(r'([A-Ga-g][#\-]?(?:m(?:aj)?\d*|maj\d*|dim\d*|aug\d*|ø\d*|sus\d*|add\d*|7th|6th|5th|m7b5)?)([1-9]\d)(?!add|\d|th|nd|rd|st)', _addify_if_needed, sanitized, flags=re.IGNORECASE)
    except Exception as e_addify: # パターンエラーなどがあればログに
        logger.warning(f"Sanitize: Error during _addify call: {e_addify}. Label: {sanitized}")


    # 7. maj9(#...) -> maj7(#...)add9 (o3さん提案の正しいグループ参照)
    sanitized = re.sub(r'(maj)9(#\d+)', r'\g<1>7\g<2>add9', sanitized, flags=re.IGNORECASE)

    # 8. susコードの重複等最終修正
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized)
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)

    # 9. 全体的なスペース・カンマの最終除去
    sanitized = re.sub(r'[,\s]', '', sanitized)
    
    # 10. 末尾に残った可能性のある不要な文字の除去
    sanitized = re.sub(r'[^a-zA-Z0-9#\-/\u00f8]+$', '', sanitized)

    if sanitized != original_label:
        logger.info(f"Sanitize: '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"Sanitize: Label '{original_label}' no change.")

    # 11. 最終パース試行 (o3さん提案) → パースできなければ None を返す
    try:
        if sanitized:
             harmony.ChordSymbol(sanitized) # パース試行（結果は使わない）
        else: # サニタイズの結果、空文字列になったらNone (Rest扱い)
            logger.info(f"Sanitize: Resulted in empty string for '{original_label}', returning None (Rest).")
            return None
    except Exception as e_final_parse:
        logger.warning(f"Sanitize: Final sanitized form '{sanitized}' (from '{original_label}') could not be parsed by music21 ({type(e_final_parse).__name__}: {e_final_parse}). Fallback to None (Rest).")
        return None 

    if not re.match(r'^[A-G]', sanitized): # ルート音がアルファベットで始まらないものはNone (Rest扱い)
        logger.warning(f"Sanitize: Final form '{sanitized}' does not start with a note name. Fallback to None (Rest).")
        return None
        
    return sanitized

def get_music21_chord_object(chord_label_str: Optional[str], current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    if not isinstance(chord_label_str, str) or not chord_label_str.strip():
        logger.debug(f"get_obj: Input '{chord_label_str}' empty/not str. As Rest (None).")
        return None

    sanitized_label = sanitize_chord_label(chord_label_str) # これが None を返す可能性あり
    
    if not sanitized_label: # sanitize_chord_labelがNoneを返したら、それはRest扱い
        logger.debug(f"get_obj: sanitize_chord_label returned None for '{chord_label_str}'. As Rest.")
        return None

    cs = None
    try:
        cs = harmony.ChordSymbol(sanitized_label) # sanitize_chord_labelの最後で既にパース試行済みだが、ここで正式にオブジェクト取得
        if not cs.pitches:
            logger.info(f"get_obj: Parsed '{sanitized_label}' (orig:'{chord_label_str}') but no pitches (fig: {cs.figure}). As Rest (None).")
            return None
        logger.info(f"get_obj: Successfully parsed '{sanitized_label}' (orig:'{chord_label_str}') as {cs.figure}")
        return cs
    except Exception as e:
        logger.error(f"get_obj: Exception for '{sanitized_label}' (orig:'{chord_label_str}'): {type(e).__name__}: {e}. As Rest (None).")
    return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    
    # 期待値はこの「真・完成版」の sanitize_chord_label が生成するであろう文字列、またはNone
    final_expected_outcomes_true_final = {
        "E7(b9)": "E7b9", "C7(#9,b13)": "C7#9b13", "C7(b9,#11,add13)": "C7b9#11add13",
        "C7alt": "C7#9b13", "Fmaj7(add9)": "Fmaj7add9", "Fmaj7(add9,13)": "Fmaj7add9add13", 
        "Bbmaj7(#11)": "B-maj7#11", 
        "Cø7": "Cm7b5", "Cm7b5": "Cm7b5", "Cø": "Cm7b5",
        "Am7(add11)": "Am7add11", "Am7(add11": "Am7add11", 
        "Dsus": "Dsus4", "Gsus4": "Gsus4", "Asus2": "Asus2", "Csus44": "Csus4",
        "Bbmaj9(#11)": "B-maj7#11add9", 
        "F#7": "F#7", "Calt": "C7#9b13", "silence": None, # RestはNone
        "Cminor7": "Cm7", "Gdominant7": "G7",
        "Bb": "B-", "Ebm": "E-m", "F#": "F#", "Dbmaj7": "D-maj7",
        "G7SUS": "G7sus4", 
        "d minor": "Dm", "e dim": "Edim", "C major7": "Cmaj7", "G AUG": "Gaug",
        "G7sus": "G7sus4",
        "bad(input": None, # パース不能はNone (Rest扱い)
        "": None, "N.C.": None, # これらもNone (Rest扱い)
    }
    
    other_tests_true_final = [
        "Rest", "  Db  ", "GM7(", "G diminished", "C major",
        "C/Bb", "CbbM7", "C##M7", 
        "C(omit3)", "Fmaj7(add9", "Gsus"
    ]
    
    all_labels_to_test_true_final = sorted(list(set(list(final_expected_outcomes_true_final.keys()) + other_tests_true_final)))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro x o3 True Masterpiece) ---")
    s_parses_tm = 0; f_parses_tm = 0; r_count_tm = 0; exp_match_tm = 0; exp_mismatch_tm = 0

    for label_orig in all_labels_to_test_true_final:
        expected_val = final_expected_outcomes_true_final.get(label_orig)
        # sanitize_chord_label が None を返す可能性があるので、その場合の期待値も None に合わせる
        if expected_val is None and sanitize_chord_label(label_orig) == "Rest": # sanitizeが"Rest"を返したが期待がNone
            sanitized_res_for_print = "Rest" # 表示上は"Rest"
        elif expected_val == "Rest" and sanitize_chord_label(label_orig) is None: # sanitizeがNoneを返したが期待が"Rest"
            sanitized_res_for_print = "None (effectively Rest)"
        else:
            sanitized_res_for_print = sanitize_chord_label(label_orig)


        if sanitize_chord_label(label_orig) is None and expected_val is None: # 両方NoneならOK
            eval_str = "✔ (Exp OK, None as Rest)" ; exp_match_tm +=1
        elif sanitize_chord_label(label_orig) == "Rest" and expected_val is None : # sanitizeがRest、期待がNone
             eval_str = "✔ (Exp OK, Rest as None)" ; exp_match_tm +=1
        elif expected_val: # 文字列比較
            if sanitize_chord_label(label_orig) == expected_val: eval_str = "✔ (Exp OK)"; exp_match_tm +=1
            else: eval_str = f"✘ (Exp: '{expected_val}')"; exp_mismatch_tm +=1
        else: # 期待値なし
             eval_str = ""
        
        print(f"Original: '{label_orig:<18}' -> Sanitized: '{str(sanitized_res_for_print):<25}' {eval_str}")

        cs_obj_tm = get_music21_chord_object(label_orig) 
        
        if cs_obj_tm:
            try: fig_disp = cs_obj_tm.figure
            except: fig_disp = "[ErrFig]"
            print(f"  music21 obj: {fig_disp:<25} (Pitches: {[p.name for p in cs_obj_tm.pitches]})"); s_parses_tm += 1
        elif sanitize_chord_label(label_orig) is None or sanitize_chord_label(label_orig).upper() == "REST":
            print(f"  Interpreted as Rest by sanitize_chord_label (returned None or 'Rest').")
            r_count_tm += 1
        else:
            print(f"  music21 FAILED or NO PITCHES for sanitized '{sanitize_chord_label(label_orig)}' (get_obj returned None)")
            f_parses_tm += 1

    print(f"\n--- Test Summary (Harugoro x o3 True Masterpiece) ---")
    total_labels_tm = len(all_labels_to_test_true_final)
    attempted_to_parse_tm = total_labels_tm - r_count_tm

    print(f"Total unique labels processed: {total_labels_tm}")
    if exp_match_tm + exp_mismatch_tm > 0:
      print(f"Matches with expected sanitization: {exp_match_tm}")
      print(f"Mismatches with expected sanitization: {exp_mismatch_tm}")
    print(f"Successfully parsed by music21 (Chord obj with pitches): {s_parses_tm} / {attempted_to_parse_tm} non-Rest attempts")
    print(f"Failed to parse or no pitches by music21: {f_parses_tm}")
    print(f"Explicitly 'Rest' (returned None or 'Rest' by sanitize): {r_count_tm}")
    
    overall_success_rate_tm = ((s_parses_tm + r_count_tm) / total_labels_tm * 100) if total_labels_tm > 0 else 0
    print(f"Estimated overall functional success (incl. Rests): {overall_success_rate_tm:.2f}%")

# --- END OF FILE generators/core_music_utils.py ---
