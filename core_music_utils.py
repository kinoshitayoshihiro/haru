# --- START OF FILE generators/core_music_utils.py (修正案 2025-05-23) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, Tuple, List
import re

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
        logger.warning(f"sanitize_chord_label: Input label '{label}' is not a string. Returning as is.")
        return str(label)

    original_label = label
    sanitized = label.strip()

    if sanitized.upper() in ["N.C.", "NC", "REST", ""]:
        logger.debug(f"Sanitizing '{original_label}' to 'Rest'")
        return "Rest"

    # ステップ A: テンション内の変化記号をプレースホルダに (例: (b9) -> (@b9@))
    # これにより、後続の全体的な 'b' -> '-' 置換でテンションの 'b' が変更されるのを防ぐ
    sanitized = re.sub(r'([#b])(\d+)', r'@\1\2@', sanitized)
    # logger.debug(f"After placeholder: {sanitized}")

    # ステップ B & C (部分): 括弧を展開し、addテンションを連結、括弧内スペース・カンマ除去
    # 1. (add11) -> (11) のように "add" を削除 (数字だけ残すことで連結を意図)
    sanitized = re.sub(r'add(\d+)', r'\1', sanitized, flags=re.IGNORECASE)
    # logger.debug(f"After 'add' removal: {sanitized}")

    # 2. 括弧を展開し、中身を連結 (括弧内のスペース・カンマは除去)
    #    例: Am7(11) -> Am711
    #    例: C7(@#9@,@b13@) -> C7@#9@@b13@
    def flatten_parenthesis_content(match_obj):
        content_inside_parentheses = match_obj.group(1)
        return re.sub(r'[,\s]', '', content_inside_parentheses)
    
    # このループは、ネストされた括弧や、複雑な括弧表記を段階的に平坦化することを目的とする。
    # Cmaj7(add9(b5))のようなものは想定しないが、(X,(Y))のようなものは平坦化できる。
    temp_sanitized_paren = sanitized
    for _ in range(3): # 最大3回の繰り返しで、たいていの単純なネストは解消されるはず
        new_sanitized_paren = re.sub(r'\(([^)]+)\)', flatten_parenthesis_content, temp_sanitized_paren)
        if new_sanitized_paren == temp_sanitized_paren:
            break
        temp_sanitized_paren = new_sanitized_paren
    sanitized = temp_sanitized_paren
    # logger.debug(f"After parenthesis flattening: {sanitized}")

    # ステップ D (部分): 特定の maj7/maj9 と #11 の連結パターン
    # 例: Fmaj7@#11@ -> Fmaj7#11 (プレースホルダ復元後に再度処理する方がよいかも)
    # ここでは、もし "maj7#11" のような形になっていれば、それを維持する意図。
    # Harugoro様の提案: label = re.sub(r'(maj[79])#?11', r'\1#11', label)
    # #?11 だと #がなくても#11になるので、#11の場合のみを対象とする。
    sanitized = re.sub(r'(maj[79])(#11)', r'\1\2', sanitized, flags=re.IGNORECASE)
    # logger.debug(f"After maj[79](#11) fix: {sanitized}")

    # 全体的なスペース除去（括弧展開後にもう一度）
    sanitized = re.sub(r'\s', '', sanitized)
    # logger.debug(f"After all space removal: {sanitized}")
    
    # ステップ F: 品質関連の正規化 (ø, half-dim, dim, dom など)
    sanitized = sanitized.replace('ø7', 'm7b5').replace('ø', 'm7b5')
    sanitized = re.sub(r'(?i)half[-]?dim', 'm7b5', sanitized)
    sanitized = re.sub(r'(?i)diminished', 'dim', sanitized)
    sanitized = re.sub(r'(?i)dominant7', '7', sanitized)
    # エラーログのタイポ修正
    sanitized = sanitized.replace('dimished', 'dim').replace('domant7', '7')
    # 基本的な品質 (majは維持、minはmへ)
    sanitized = re.sub(r'(?i)minor7', 'm7', sanitized)
    sanitized = re.sub(r'(?i)minor9', 'm9', sanitized)
    sanitized = re.sub(r'(?i)minor11', 'm11', sanitized)
    sanitized = re.sub(r'(?i)minor13', 'm13', sanitized)
    sanitized = re.sub(r'(?i)min(?!or\b)', 'm', sanitized) # Cmin -> Cm (minorワードは避ける)

    # logger.debug(f"After quality normalization: {sanitized}")

    # altコードの展開 (プレースホルダ使用)
    if re.fullmatch(r'[A-Ga-g][#\-]*alt', sanitized, flags=re.IGNORECASE):
        base_note = sanitized[:-3]
        sanitized = f"{base_note}7@#9@@b13@" # プレースホルダでテンション指定
    elif re.fullmatch(r'[A-Ga-g][#\-]*7alt', sanitized, flags=re.IGNORECASE):
        base_note_and_7 = sanitized[:-3]
        sanitized = f"{base_note_and_7}@#9@@b13@"
    # logger.debug(f"After alt expansion: {sanitized}")

    # susコードの正規化 (Harugoro様の修正 \g<1>4 を適用)
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized)
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)
    try:
        # `sus` で終わり、直後に数字(2か4)がない場合 -> `sus4`
        sanitized = re.sub(r'(?i)(sus)(?![24\d])', r'\g<1>4', sanitized)
    except re.error as e_re_sus:
        logger.warning(f"sanitize_chord_label: Regex error during sus normalization for '{sanitized}': {e_re_sus}")
    # logger.debug(f"After sus normalization: {sanitized}")

    # ステップ A の復元: プレースホルダを元に戻す (例: @b9@ -> b9)
    sanitized = sanitized.replace('@b', 'b').replace('@#', '#').replace('@@', '') # @@は二重プレースホルダ予防の名残
    # logger.debug(f"After placeholder restoration: {sanitized}")

    # ルート音とベース音の臨時記号をmusic21標準形へ (例: Bb -> B-, C/Db -> C/D-)
    parts = sanitized.split('/')
    root_part_str = parts[0]
    bass_part_str = parts[1] if len(parts) > 1 else None

    def normalize_note_accidentals_final(note_str_param):
        if not note_str_param: return ""
        # 'b' を '-' に置換 (ただし、m7b5のような品質内のbは避ける。多くは既にプレースホルダで保護済のはず)
        # この段階では、ルート音とベース音名に含まれる 'b' のみを対象とする
        # 例: Cbmaj7 -> C-maj7, Gm7b5 (ここは変更なしのはず)
        
        # ルート音/ベース音のみの'b'を'-'に (正規表現で音名部分のみをターゲット)
        # 先頭の音名部分とベースの音名部分
        def replace_acc_in_note_name(match_obj):
            name = match_obj.group(1)
            acc = match_obj.group(2)
            rest = match_obj.group(3)
            acc = acc.replace('bb', '--').replace('b', '-')
            return name + acc + rest

        note_str_param = re.sub(r'^([A-Ga-g])([#b\-]{0,2})(.*)', replace_acc_in_note_name, note_str_param)
        return note_str_param

    sanitized_root = normalize_note_accidentals_final(root_part_str)
    sanitized_bass = normalize_note_accidentals_final(bass_part_str) if bass_part_str else None

    if sanitized_bass:
        sanitized = f"{sanitized_root}/{sanitized_bass}"
    else:
        sanitized = sanitized_root
    # logger.debug(f"After root/bass accidental normalization: {sanitized}")

    # 最後の整形: 末尾の開き括弧除去、全体的な重複スペースなど
    sanitized = sanitized.rstrip('(')
    sanitized = re.sub(r'\s+', ' ', sanitized).strip() # 最終的なスペース整理

    if sanitized != original_label:
        logger.info(f"sanitize_chord_label: Sanitized '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"sanitize_chord_label: Label '{original_label}' required no changes by sanitization process.")
    return sanitized

# (get_music21_chord_object と if __name__ == '__main__': は前回提示版(2025-05-22 深夜)を使用してください)
# 以下に再掲しますが、上記の sanitize_chord_label に合わせてテストケースは調整しています。

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
    
    # Harugoro様の最新テストケースと期待値
    harugoro_final_tests_expected = {
        "C7(b9,#11,add13)": "C7b9#1113", # プレースホルダ復元と連結後
        "Fmaj7(add9)":      "Fmaj79",     # 同上
        "Bbmaj7(#11)":      "B-maj7#11",  # 同上 (ルートフラット正規化含む)
        "Cø7":              "Cm7b5",      # 品質正規化
        "C7alt":            "C7#9b13",    # alt展開と連結後
        # Susテスト
        "Dsus": "Dsus4", "Gsus4": "Gsus4", "Asus2": "Asus2", "Csus44": "Csus4",
        # ログからのその他重要ケース
        "Am7(add11)": "Am711",
        "E7(b9)": "E7b9",
        "C7(#9,b13)": "C7#9b13",
        "Fmaj7(add9,13)": "Fmaj7913",
        "Bbmaj9(#11)": "B-maj9#11",
        "Calt": "C7#9b13",
    }
    
    additional_test_cases = [
        "Cmaj7", "Cm7b5", "G7sus","Dbmaj7", "Ebm7", "Abmaj7", "Bbm6",
        "N.C.", "Rest", "", "  Db  ","GM7(", "Am7(add11", "C#m7", "F#7",
        "F/G", "Am/G#", "D/F#", "CbbM7", "C##M7", "Cminor7", "Cdominant7"
    ]
    
    all_labels_to_test = sorted(list(set(list(harugoro_final_tests_expected.keys()) + additional_test_cases)))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro Build v3) ---")
    successful_parses = 0; failed_parses = 0; rest_count = 0; no_pitch_count = 0

    for label_orig in all_labels_to_test:
        expected_sanitized_val = harugoro_final_tests_expected.get(label_orig)
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
            
    print(f"\n--- Test Summary (Harugoro Build v3) ---")
    total_attempted = successful_parses + failed_parses + no_pitch_count
    total_processed = len(all_labels_to_test)
    print(f"Total labels processed: {total_processed}")
    print(f"Successfully parsed w/ pitches: {successful_parses} / {total_attempted} non-Rest attempts ({ (successful_parses/total_attempted*100) if total_attempted > 0 else 0 :.2f}%)")
    print(f"Parsed but no pitches (Rest): {no_pitch_count}")
    print(f"Failed to parse: {failed_parses}")
    print(f"Explicitly 'Rest' (N.C., etc.): {rest_count}")
    print(f"Est. overall success (incl. explicit Rests): { (successful_parses + rest_count) / total_processed * 100 if total_processed > 0 else 0 :.2f}%")

# --- END OF FILE generators/core_music_utils.py ---
