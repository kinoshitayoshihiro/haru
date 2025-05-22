# --- START OF FILE generators/core_music_utils.py (祝・完成版 🎉) ---
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

def _expand_tension_block_o3(seg: str) -> str:
    seg = seg.strip().lower()
    if not seg: return ""
    if seg.startswith(("#", "b")): return seg
    if seg.startswith("add"):
        match_add_num = re.match(r'add(\d+)', seg)
        if match_add_num: return f"add{match_add_num.group(1)}"
        return "" 
    if seg.isdigit(): return f"add{seg}"
    if seg in ["omit3", "omit5", "omitroot"]: return seg
    logger.debug(f"Sanitize (_expand_tension_block): Unknown tension fragment '{seg}', passing as is.")
    return seg

def sanitize_chord_label(label: Optional[str]) -> str:
    if not label or not isinstance(label, str):
        logger.debug(f"Sanitize: Label '{label}' is None or not str. Returning 'Rest'.")
        return "Rest"
    
    original_label = label
    sanitized = label.strip()

    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"Sanitize: '{original_label}' -> 'Rest' (direct match).")
        return "Rest"

    # 0. ワードベースの品質変換 (o3さん提案)
    #    例: "C major" -> "Cmaj", "d minor" -> "dm"
    word_map = {
        r'(?i)\b([A-Ga-g][#\-]*)\s+minor\b': r'\1m',
        r'(?i)\b([A-Ga-g][#\-]*)\s+major\b': r'\1maj', # majのままの方がmusic21は安定
        r'(?i)\b([A-Ga-g][#\-]*)\s+dim\b':   r'\1dim',
        r'(?i)\b([A-Ga-g][#\-]*)\s+aug\b':   r'\1aug',
    }
    for pat, rep in word_map.items():
        sanitized = re.sub(pat, rep, sanitized)

    # 1. ルート音とスラッシュベース音のフラット正規化
    sanitized = re.sub(r'^([A-Ga-g])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-Ga-g])b(?![#b])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-Ga-g])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-Ga-g])b(?![#b])', r'/\1-', sanitized)
    
    # 1b. SUS正規化 (o3さん提案) - alt展開の前に置く方が良い場合もある
    #     G7SUS -> G7sus4 (大文字小文字を区別せず、数字がなければsus4を補完)
    sanitized = re.sub(r'(?i)([A-G][#\-]?(?:\d+)?)(sus)(?![24\d])', r'\1sus4', sanitized)
    #     SUS2/SUS4 -> sus2/sus4 (小文字化)
    sanitized = re.sub(r'(?i)SUS([24])', r'sus\1', sanitized)


    # 2. 括弧の不均衡修正
    if '(' in sanitized and ')' not in sanitized:
        logger.info(f"Sanitize: Detected unclosed parenthesis in '{original_label}'.")
        base_part = sanitized.split('(')[0]
        content_after_paren = sanitized.split('(', 1)[1] if len(sanitized.split('(', 1)) > 1 else ""
        if content_after_paren.strip():
            recovered_tensions = "".join(_expand_tension_block_o3(p) for p in content_after_paren.split(','))
            if recovered_tensions:
                sanitized = base_part + recovered_tensions
                logger.info(f"Sanitize: Recovered from unclosed: '{recovered_tensions}' -> '{sanitized}'")
            else: sanitized = base_part; logger.info(f"Sanitize: No valid tensions in unclosed, kept -> '{sanitized}'")
        else: sanitized = base_part; logger.info(f"Sanitize: Empty after unclosed, kept -> '{sanitized}'")

    # 3. altコード展開 (正しいグループ参照\g<1>を使用)
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt', r'\g<1>7#9b13', sanitized, flags=re.IGNORECASE)
    
    # 4. 括弧の平坦化 (_expand_tension_block_o3 を使用)
    prev_sanitized_state = "" ; loop_count = 0
    while '(' in sanitized and ')' in sanitized and sanitized != prev_sanitized_state and loop_count < 5:
        prev_sanitized_state = sanitized; loop_count += 1
        match = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if match:
            base, inner_content, suf = match.groups()
            tension_parts = [seg.strip() for seg in inner_content.split(',')]
            expanded_inner_content = "".join(_expand_tension_block_o3(p) for p in tension_parts)
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
    sanitized = re.sub(r'(?i)augmented', 'aug', sanitized)
                                                       
    # 6. "add"キーワードの最終確認と、数字のみが連結した場合の "add" 補完
    sanitized = re.sub(r'(?i)(add)(\d+)', r'add\2', sanitized) # addの小文字化
    sanitized = re.sub(r'(?i)(m[aj]?[79]?|(?<!sus)7|(?<!sus)\d)(\d{2,})(?!add|\d|th|nd|rd|st)', r'\1add\2', sanitized) # G711->G7add11

    # 7. maj9(#...) -> maj7(#...)add9 (o3さん提案の正確なグループ参照)
    sanitized = re.sub(r'(maj)9(#\d+)', r'\g<1>7\g<2>add9', sanitized, flags=re.IGNORECASE)

    # 8. susコードの重複等最終修正
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized) # Gsus44 -> Gsus4
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)

    # 9. 全体的なスペース・カンマの最終除去
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
        logger.debug(f"get_obj: Input '{chord_label_str}' empty/not str. As Rest.")
        return None
    sanitized_label = sanitize_chord_label(chord_label_str)
    if not sanitized_label or sanitized_label.upper() == "REST":
        logger.debug(f"get_obj: Sanitized to '{sanitized_label}'. As Rest.")
        return None
    cs = None
    try:
        cs = harmony.ChordSymbol(sanitized_label)
        if not cs.pitches:
            logger.info(f"get_obj: Parsed '{sanitized_label}' (orig:'{chord_label_str}') but no pitches (fig: {cs.figure}). As Rest.")
            return None
        logger.info(f"get_obj: Successfully parsed '{sanitized_label}' (orig:'{chord_label_str}') as {cs.figure}")
        return cs
    except Exception as e:
        logger.error(f"get_obj: Exception for '{sanitized_label}' (orig:'{chord_label_str}'): {type(e).__name__}: {e}. As Rest.")
    return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    
    final_expected_outcomes_vFinal = {
        "E7(b9)": "E7b9", "C7(#9,b13)": "C7#9b13", "C7(b9,#11,add13)": "C7b9#11add13",
        "C7alt": "C7#9b13", "Fmaj7(add9)": "Fmaj7add9", "Fmaj7(add9,13)": "Fmaj7add9add13", 
        "Bbmaj7(#11)": "B-maj7#11", 
        "Cø7": "Cm7b5", "Cm7b5": "Cm7b5", "Cø": "Cm7b5",
        "Am7(add11)": "Am7add11", "Am7(add11": "Am7add11", 
        "Dsus": "Dsus4", "Gsus4": "Gsus4", "Asus2": "Asus2", "Csus44": "Csus4",
        "Bbmaj9(#11)": "B-maj7#11add9", 
        "F#7": "F#7", "Calt": "C7#9b13", "silence": "Rest",
        "Cminor7": "Cm7", "Gdominant7": "G7",
        "Bb": "B-", "Ebm": "E-m", "F#": "F#", "Dbmaj7": "D-maj7",
        "G7SUS": "G7sus4", "d minor": "Dm", "e dim": "Edim", "C major7": "Cmaj7", "G AUG": "Gaug"
    }
    
    other_tests_vFinal = [
        "N.C.", "Rest", "", "  Db  ", "GM7(", "G diminished",
        "C/Bb", "CbbM7", "C##M7", 
        "bad(input", "C(omit3)", "Fmaj7(add9", "G7sus" # G7susがSUS正規化の対象になるかも
    ]
    
    all_labels_to_test_vFinal = sorted(list(set(list(final_expected_outcomes_vFinal.keys()) + other_tests_vFinal)))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro x o3 Perfection) ---")
    s_parses_vFinal = 0; f_parses_vFinal = 0; r_count_vFinal = 0; exp_match_count_vFinal = 0; exp_mismatch_count_vFinal = 0

    for label_orig in all_labels_to_test_vFinal:
        expected_val = final_expected_outcomes_vFinal.get(label_orig)
        sanitized_res = sanitize_chord_label(label_orig)
        
        eval_str = ""
        if expected_val:
            if sanitized_res == expected_val: eval_str = "✔ (Exp OK)"; exp_match_count_vFinal +=1
            else: eval_str = f"✘ (Exp: '{expected_val}')"; exp_mismatch_count_vFinal +=1
        
        print(f"Original: '{label_orig:<18}' -> Sanitized: '{sanitized_res:<25}' {eval_str}")

        cs_obj_vFinal = get_music21_chord_object(label_orig) 
        
        if cs_obj_vFinal:
            try: fig_disp = cs_obj_vFinal.figure
            except: fig_disp = "[ErrFig]"
            print(f"  music21 obj: {fig_disp:<25} (Pitches: {[p.name for p in cs_obj_vFinal.pitches]})"); s_parses_vFinal += 1
        elif sanitize_chord_label(label_orig) == "Rest":
            print(f"  Interpreted as Rest by sanitize_chord_label.")
            r_count_vFinal += 1
        else:
            print(f"  music21 FAILED or NO PITCHES for sanitized '{sanitized_res}'")
            f_parses_vFinal += 1

    print(f"\n--- Test Summary (Harugoro x o3 Perfection) ---")
    total_labels_final_vFinal = len(all_labels_to_test_vFinal)
    attempted_to_parse_count_vFinal = total_labels_final_vFinal - r_count_vFinal

    print(f"Total unique labels processed: {total_labels_final_vFinal}")
    if exp_match_count_vFinal + exp_mismatch_count_vFinal > 0:
      print(f"Matches with expected sanitization: {exp_match_count_vFinal}")
      print(f"Mismatches with expected sanitization: {exp_mismatch_count_vFinal}")
    print(f"Successfully parsed by music21 (Chord obj with pitches): {s_parses_vFinal} / {attempted_to_parse_count_vFinal} non-Rest attempts")
    print(f"Failed to parse or no pitches by music21: {f_parses_vFinal}")
    print(f"Explicitly 'Rest' by sanitize_chord_label: {r_count_vFinal}")
    
    overall_success_rate_vFinal = ((s_parses_vFinal + r_count_vFinal) / total_labels_final_vFinal * 100) if total_labels_final_vFinal > 0 else 0
    print(f"Estimated overall functional success (incl. Rests): {overall_success_rate_vFinal:.2f}%")

# --- END OF FILE generators/core_music_utils.py ---
