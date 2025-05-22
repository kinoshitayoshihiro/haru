# --- START OF FILE generators/core_music_utils.py (最終改訂案 2025-05-23 v2) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, Tuple, List
import re

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    # ... (変更なし) ...
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
    # ... (変更なし) ...
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
        try:
            return scale_class(tonic_p)
        except Exception as e_create:
            logger.error(f"build_scale_object: Error creating scale '{scale_class.__name__}' "
                         f"with tonic '{tonic_p.nameWithOctave if tonic_p else 'N/A'}': {e_create}. Fallback C Major.", exc_info=True)
            return scale.MajorScale(pitch.Pitch("C"))
    else:
        logger.warning(f"build_scale_object: Mode '{effective_mode_str}' unknown for tonic '{tonic_p.nameWithOctave if tonic_p else 'N/A'}'. Defaulting to MajorScale.")
        return scale.MajorScale(tonic_p)

def sanitize_chord_label(label: str) -> str:
    if not isinstance(label, str):
        logger.warning(f"Sanitize: Label '{label}' not str. Returning as is.")
        return str(label)

    original_label = label
    sanitized = label.strip()

    if sanitized.upper() in ["N.C.", "NC", "REST", ""]:
        logger.debug(f"Sanitize: '{original_label}' to 'Rest'")
        return "Rest"

    # --- Harugoro様最終パッチ案に基づく修正 ---
    # 1. トークンハック廃止。ルート音とスラッシュベースのフラットを限定的に処理
    #    b -> -, bb -> -- (シャープはそのまま)
    #    テンション内の b/# はこの段階では変更しない。
    sanitized = re.sub(r'^([A-Ga-g])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-Ga-g])b(?![#])', r'\1-', sanitized) # bの後に#が続く場合(b#9など)は除外
    sanitized = re.sub(r'/([A-Ga-g])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-Ga-g])b(?![#])', r'/\1-', sanitized)
    
    # 2. 括弧の不均衡修正 (開き括弧のみの場合)
    if '(' in sanitized and ')' not in sanitized:
        logger.info(f"Sanitize: Dangling '(', keeping content before it for '{original_label}' -> '{sanitized.split('(')[0]}'")
        sanitized = sanitized.split('(')[0]

    # 3. 括弧を展開し、中身をフラット化 (スペース・カンマ除去、キーワード維持)
    #    例: Am7(add11) -> Am7add11, C7(#9, b13) -> C7#9b13
    temp_sanitized_paren = sanitized
    prev_flatten_state = ""
    max_flatten_loops = 5
    count_flatten_loops = 0
    while '(' in temp_sanitized_paren and ')' in temp_sanitized_paren and temp_sanitized_paren != prev_flatten_state and count_flatten_loops < max_flatten_loops:
        prev_flatten_state = temp_sanitized_paren
        count_flatten_loops += 1
        match_paren = re.match(r'^(.*?)\(([^)]+)\)(.*)$', temp_sanitized_paren)
        if match_paren:
            base, tens, suf = match_paren.groups()
            tens_cleaned = re.sub(r'[,\s]', '', tens) # カンマとスペースを除去
            temp_sanitized_paren = base + tens_cleaned + suf
        else:
            break
    sanitized = temp_sanitized_paren

    # 4. "add"キーワードの正規化 (小文字にし、数字が続くことを確認)
    #    Am7add11 はこの時点で Am7add11 のままのはず
    sanitized = re.sub(r'(?i)(add)(\d+)', r'add\2', sanitized)

    # 5. maj7addX, maj9addX のような形を整形
    #    例: Fmaj79 -> Fmaj7add9 (もし flatten で add が消えていたら)
    #    例: Bbmaj7#11 -> B-maj7#11 (これは flat 正規化で B- になっているはず)
    #    この正規表現は、maj7 や maj9 の後に直接数字が続く場合に "add" を挿入する
    sanitized = re.sub(r'(?i)(maj[79])(\d+)(?!add)', r'\1add\2', sanitized)
    # 例: maj7(#11) のような形が maj7#11 になっている場合に、不要な#を整理
    sanitized = re.sub(r'(maj[79])(?:add)?(#\d+)', r'\1\2', sanitized, flags=re.IGNORECASE)


    # 6. 品質関連の正規化 (ø, half-dim, dim, dom など)
    sanitized = sanitized.replace('ø7', 'm7b5').replace('ø', 'm7b5')
    sanitized = re.sub(r'(?i)half[-]?dim', 'm7b5', sanitized)
    # エラーログのタイポと冗長表現の修正
    sanitized = sanitized.replace('dimished', 'dim').replace('domant7', '7')
    sanitized = re.sub(r'(?i)diminished(?!7)', 'dim', sanitized) # diminished (7以外) -> dim
    sanitized = re.sub(r'(?i)diminished7', 'dim7', sanitized)
    sanitized = re.sub(r'(?i)dominant7', '7', sanitized)
    sanitized = re.sub(r'(?i)augmented', 'aug', sanitized)
    
    # min 系を m へ (maj はそのまま維持)
    sanitized = re.sub(r'(?i)minor7', 'm7', sanitized)
    sanitized = re.sub(r'(?i)minor9', 'm9', sanitized)
    sanitized = re.sub(r'(?i)minor11', 'm11', sanitized)
    sanitized = re.sub(r'(?i)minor13', 'm13', sanitized)
    sanitized = re.sub(r'(?i)min(?!or\b|\.)', 'm', sanitized) # "min" で終わるか、ピリオドが続かない場合


    # 7. alt コードの展開 (music21は 'alt' を直接解釈しない)
    #    Calt -> C7#9b13
    sanitized = re.sub(r'([A-Ga-g][#\-]?)7?alt', r'\17#9b13', sanitized, flags=re.IGNORECASE)

    # 8. susコードの正規化 (Harugoro様の修正 \g<1>4 を適用)
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized)
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)
    try:
        sanitized = re.sub(r'(?i)(sus)(?![24\d])', r'\g<1>4', sanitized)
    except re.error as e_re_sus:
        logger.warning(f"Sanitize: Regex error sus normal: {e_re_sus}. Label: '{sanitized}'")
        
    # 9. 最終的な全体のスペース・カンマ除去 (かなり強力なので注意)
    #    これにより、#9 b13 -> #9b13 のようになることも期待
    sanitized = re.sub(r'[,\s]', '', sanitized)

    if sanitized != original_label:
        logger.info(f"Sanitize: '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"Sanitize: Label '{original_label}' unchanged.")
    return sanitized

# (get_music21_chord_object と if __name__ == '__main__': は前回提示版(2025-05-22 深夜)のものをベースに、
#  テストケースの期待値をHarugoro様提案に合わせるのが良いでしょう。以下に調整版を記載します。)

def get_music21_chord_object(chord_label_str: str, current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    if not chord_label_str or chord_label_str.strip().upper() in ["N.C.", "NC", "REST", ""]:
        logger.debug(f"get_music21_chord_object: Chord label '{chord_label_str}' interpreted as Rest.")
        return None

    sanitized_label = sanitize_chord_label(chord_label_str)
    cs = None
    try:
        cs = harmony.ChordSymbol(sanitized_label)
        if not cs.pitches:
            logger.debug(f"get_music21_chord_object: Parsed '{sanitized_label}' but it has no pitches. Treating as Rest.")
            return None
        logger.debug(f"get_music21_chord_object: Successfully parsed '{sanitized_label}' (original: '{chord_label_str}') as {cs.figure}")
        return cs
    except harmony.HarmonyException as he:
        logger.error(f"get_music21_chord_object: HarmonyException when parsing '{sanitized_label}' (orig: '{chord_label_str}'): {he}. Treating as Rest.")
    except music21.exceptions21.Music21Exception as m21e:
        logger.error(f"get_music21_chord_object: Music21Exception when parsing '{sanitized_label}' (orig: '{chord_label_str}'): {m21e}. Treating as Rest.")
    except Exception as e:
        logger.error(f"get_music21_chord_object: Unexpected error parsing '{sanitized_label}' (orig: '{chord_label_str}'): {e}. Treating as Rest.", exc_info=True)
    
    return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    
    # Harugoro様の最終パッチ後の期待値テストケース
    harugoro_final_expected = {
        "E7(b9)": "E7b9",
        "C7(#9,b13)": "C7#9b13",
        "C7(b9,#11,add13)": "C7b9#11add13", # 変更: add も連結
        "C7alt": "C7#9b13",
        "Fmaj7(add9)": "Fmaj7add9",     # 変更: add も連結
        "Fmaj7(add9,13)": "Fmaj7add9add13", # 変更: add も連結
        "Bbmaj7(#11)": "B-maj7#11", # B- になっている想定
        "Cø7": "Cm7b5",
        "Am7(add11)": "Am7add11",    # 変更: add も連結
        # Susテスト (これらは変更なし)
        "Dsus": "Dsus4", "Gsus4": "Gsus4", "Asus2": "Asus2", "Csus44": "Csus4",
        # ログから問題があったが、修正で期待できるもの
        "Bbmaj9(#11)": "B-maj9#11",
        "Cm7b5": "Cm7b5", # Cm7b5@ にならず Cm7b5
        "F#7": "F#7",     # F#7@ にならない
    }
    
    additional_test_cases = [
        "Cmaj7", "Dbmaj7", "Ebm7", "Abmaj7", "Bbm6",
        "N.C.", "Rest", "", "  Db  ", "GM7(", "Am7(add11", # "Am7(add11" (閉じ括弧なし)はGM7(のようにAm7になるはず
        "C#m7", "Calt",
        "F/G", "Am/G#", "D/F#", "C/Bb",
        "CbbM7", "C##M7", "Cminor7", "Cdominant7", "G7sus"
    ]
    
    all_labels_to_test = sorted(list(set(list(harugoro_final_expected.keys()) + additional_test_cases)))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro Final Build) ---")
    successful_parses = 0; failed_parses = 0; rest_count = 0; no_pitch_count = 0

    for label_orig in all_labels_to_test:
        expected_sanitized_val = harugoro_final_expected.get(label_orig)
        sanitized_result = sanitize_chord_label(label_orig)
        
        eval_str = ""
        if expected_sanitized_val:
            if sanitized_result == expected_sanitized_val: eval_str = "✔ (Exp match)"
            else: eval_str = f"✘ (Exp: '{expected_sanitized_val}')"
        
        print(f"Original: '{label_orig:<18}' -> Sanitized: '{sanitized_result:<20}' {eval_str}")

        if sanitized_result.upper() == "REST": print(f"  Interpreted as Rest."); rest_count +=1
        elif sanitized_result:
            try:
                cs = harmony.ChordSymbol(sanitized_result)
                if cs and cs.pitches:
                    try: fig = cs.figure
                    except: fig = "[ErrFig]"
                    print(f"  music21 parsed: {fig:<25} (Pitches: {[p.name for p in cs.pitches]})"); successful_parses += 1
                else:
                    fig = cs.figure if cs else "N/A"
                    print(f"  music21 parsed '{sanitized_result}' as CS, BUT NO PITCHES (figure: {fig}). Treat as REST."); no_pitch_count += 1
            except Exception as e: print(f"  music21 ERROR parsing '{sanitized_result}': {type(e).__name__}: {e}"); failed_parses += 1
        else: print(f"  Sanitized to empty: '{sanitized_result}'"); failed_parses +=1
            
    print(f"\n--- Test Summary (Harugoro Final Build) ---")
    total_attempted = successful_parses + failed_parses + no_pitch_count
    total_processed = len(all_labels_to_test)
    print(f"Total labels processed: {total_processed}")
    print(f"Successfully parsed w/ pitches: {successful_parses} / {total_attempted} non-Rest attempts ({ (successful_parses/total_attempted*100) if total_attempted > 0 else 0 :.2f}%)")
    print(f"Parsed but no pitches (Rest): {no_pitch_count}")
    print(f"Failed to parse: {failed_parses}")
    print(f"Explicitly 'Rest' (N.C., etc.): {rest_count}")
    print(f"Est. overall success (incl. explicit Rests): { (successful_parses + rest_count) / total_processed * 100 if total_processed > 0 else 0 :.2f}%")

# --- END OF FILE generators/core_music_utils.py ---
