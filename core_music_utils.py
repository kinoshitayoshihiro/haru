# --- START OF FILE generators/core_music_utils.py (修正案 2025-05-22 深夜) ---
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
        logger.warning(f"sanitize_chord_label: Input label '{label}' is not a string. Returning as is.")
        return str(label)

    original_label = label
    sanitized = label.strip()

    if sanitized.upper() in ["N.C.", "NC", "REST", ""]:
        logger.debug(f"Sanitizing '{original_label}' to 'Rest'")
        return "Rest"

    # 括弧処理 (Harugoro様の while ループ案ベース、ただし括弧と中身はできるだけ維持)
    # このループは、入れ子になった括弧や、変換によって生じた不要な括弧の単純化を目指す。
    temp_sanitized = sanitized
    previous_state = "" # ループが停滞しないように
    max_iterations = 7 # 無限ループ防止のためのカウンター
    iter_count = 0

    while temp_sanitized != previous_state and iter_count < max_iterations:
        previous_state = temp_sanitized
        iter_count += 1

        # 1. 二重括弧の単純化:例: C((add9)) -> C(add9)
        temp_sanitized = temp_sanitized.replace('((', '(').replace('))', ')')

        # 2. 括弧と中身のスペース正規化と、カンマ区切り整形 (music21パーサへの配慮)
        # 例: X( #9 , b13 ) -> X(#9,b13)
        def replace_paren_content(match_obj):
            paren_group = match_obj.group(1) # 括弧とその中身 (e.g., "( #9 , b13 )")
            content_inside = paren_group[1:-1] # 中身だけ (e.g., " #9 , b13 ")
            content_cleaned = re.sub(r'\s*,\s*', ',', content_inside.strip()) # カンマ周りの空白削除+トリム
            content_cleaned = re.sub(r'\s+', ' ', content_cleaned) # 連続空白を1つに
            return f"({content_cleaned})"
        try: # re.PatternError 対策で try-except
            temp_sanitized = re.sub(r'(\([^)]*\))', replace_paren_content, temp_sanitized)
        except re.error as e_re_paren:
            logger.warning(f"sanitize_chord_label: Regex error during parenthesis content normalization for '{temp_sanitized}': {e_re_paren}")
            # エラー発生時はこのステップをスキップ


        # 3. 処理の過程で生まれた可能性のある末尾の開き括弧の除去
        if temp_sanitized.endswith('(') and temp_sanitized.count('(') > temp_sanitized.count(')'):
            temp_sanitized = temp_sanitized[:-1]
    
    sanitized = temp_sanitized
    
    # 品質表記の正規化 (majsをMにしないHarugoro様の方針を一部採用)
    # min系はmに、dom7は7に、などmusic21の基本形に寄せる
    quality_replacements = {
        r'(?i)min7': 'm7', r'(?i)mi7': 'm7', r'(?i)minor7': 'm7',
        r'(?i)min9': 'm9', r'(?i)mi9': 'm9', r'(?i)minor9': 'm9',
        r'(?i)min11': 'm11',r'(?i)mi11': 'm11',r'(?i)minor11': 'm11',
        r'(?i)min13': 'm13',r'(?i)mi13': 'm13',r'(?i)minor13': 'm13',
        r'(?i)min(?!or)': 'm', # "minor"でない "min" を "m" に (例: Cmin -> Cm)
        r'(?i)dom7': '7',
        r'(?i)half-diminished': 'ø', r'(?i)ø7': 'ø', r'(?i)m7b5': 'ø',
        r'(?i)diminished7': 'dim7', r'(?i)dim7': 'dim7',
        r'(?i)diminished(?![(\d])': 'dim', # "dim(" や "dim7" 以外
        r'(?i)dim(?![(\d7])': 'dim',    # "dim(", "dim7" 以外
        r'(?i)augmented(?![(\d])': 'aug',
        r'(?i)aug(?![(\dm])': 'aug',
        # maj は music21 がそのまま解釈できるため、Mへの積極的変換は避ける (Harugoro様の方針)
    }
    for old, new in quality_replacements.items():
        sanitized = re.sub(old, new, sanitized)

    # susコードの正規化 (Harugoro様のエラー報告と修正案を適用)
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized)
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)
    # `sus` のみ、または `sus` の後に数字以外が続く場合 -> `sus4` (Harugoro様の指摘 `\g<1>4` を使用)
    try:
        sanitized = re.sub(r'(?i)(sus)(?![24\d])', r'\g<1>4', sanitized)
    except re.error as e_re_sus: # 万が一の \g<1>4 のエラーキャッチ (通常は問題ないはず)
        logger.error(f"sanitize_chord_label: Error in sus repl: {e_re_sus}. Orig: '{sanitized}'")

    # ルート音とベース音の臨時記号の正規化
    parts = sanitized.split('/')
    root_part_str = parts[0]
    bass_part_str = parts[1] if len(parts) > 1 else None

    def normalize_note_name_notation(part_str):
        if not part_str: return ""
        # music21は "B-" を "Bb" より、"D-"を"Db"より好む。ただし変換は必須ではない。
        # 臨時記号の music21 標準形: '-' for flat, '--' for double-flat, '#' for sharp, '##' for double-sharp (or 'x')
        part_str = part_str.replace('bb', '--').replace('b', '-') # ダブルフラット、シングルフラット
        return part_str

    sanitized_root = normalize_note_name_notation(root_part_str)
    sanitized_bass = normalize_note_name_notation(bass_part_str) if bass_part_str else None

    if sanitized_bass:
        sanitized = f"{sanitized_root}/{sanitized_bass}"
    else:
        sanitized = sanitized_root
    
    # alt コードの展開 (Harugoro様提案。music21 が解釈しやすい形へ)
    # "alt" や "7alt" の後に括弧で具体的なオルタレーションを書く方が music21 にとって良い
    # 例: C7alt -> C7(b9,#9,b13) or C7(#9,b5) など (解釈は様々)
    # ここでは一般的なものとして #9 と b13 を追加
    # C7(alter G) も music21 は理解する
    def expand_alt(label_to_expand):
        # Xalt (例: Calt) -> X7(#9,b13)
        if re.fullmatch(r'[A-Ga-g][#\-]*alt', label_to_expand, flags=re.IGNORECASE):
            base_note = label_to_expand[:-3] # "alt" を削除
            return f"{base_note}7(#9,b13)"
        # X7alt (例: C7alt) -> X7(#9,b13)
        elif re.fullmatch(r'[A-Ga-g][#\-]*7alt', label_to_expand, flags=re.IGNORECASE):
            base_note_and_7 = label_to_expand[:-3] # "alt" を削除
            return f"{base_note_and_7}(#9,b13)"
        return label_to_expand
    sanitized = expand_alt(sanitized)

    # 括弧内のオルタレーション表記を music21 がより好みやすいように最終調整
    # 例: (#9,b13) -> ( #9, b13) (スペースで区切る)
    def format_alterations_in_parens(match_obj):
        content = match_obj.group(1)[1:-1] # 括弧の中身
        # sharp/flat + 数字 の形を整形 (例: #9 -> " #9")
        content = re.sub(r'([#b])(\d+)', r' \1\2', content)
        content = content.replace(',', ', ') # カンマの後にスペース
        content = re.sub(r'\s+', ' ', content).strip() # 余分なスペースを整理
        return f"({content})"
    try:
        sanitized = re.sub(r'(\([^)]+\))', format_alterations_in_parens, sanitized)
    except re.error as e_re_alt_format:
         logger.warning(f"sanitize_chord_label: Regex error during alt parenthesis formatting for '{sanitized}': {e_re_alt_format}")


    # 特殊ケース： 'Am7(add11' のように閉じ括弧がないが、意図は add11 である場合
    # 'Am7(add11' (エラーログより) -> Am7(add11)
    # 'C7(( #9, b13))' (エラーログより) -> C7(#9,b13)
    # 'm7((add11))' や '7((b9))'
    # 最初の括弧処理で対応しきれなかったものを再度チェック
    if '(' in sanitized and ')' not in sanitized:
        m_unclosed = re.match(r'(.+)\((add\d+|#\d+|b\d+|[#b]\d+[,#b\d\s]*)', sanitized)
        if m_unclosed:
            base, presumed_content = m_unclosed.groups()
            sanitized = f"{base}({presumed_content.strip()})"
            logger.info(f"Sanitizing: Attempted to fix unclosed parenthesis for '{original_label}' -> '{sanitized}'")
    
    # 最後のサニタイズ結果と元のラベルを比較
    if sanitized != original_label:
        logger.info(f"sanitize_chord_label: Sanitized '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"sanitize_chord_label: Label '{original_label}' required no changes during sanitization process.")

    return sanitized

def get_music21_chord_object(chord_label_str: str, current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    # ... (変更なし) ...
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
    
    # Harugoro様の追試推奨テストケース
    harugoro_sus_tests = {
        "Dsus": "Dsus4",
        "Gsus4": "Gsus4", # 変更なし
        "Asus2": "Asus2", # 変更なし
        "Csus44": "Csus4" # 修正されるべき
    }
    # Harugoro様の以前のテストケース
    harugoro_main_tests = {
        "E7(b9)": "E7(b9)",
        "C7(#9,b13)": "C7(#9,b13)", # 理想形
        "Am7(add11)": "Am7(add11)",
        "Csus4": "Csus4",
        "Esus4(b9)": "Esus4(b9)",
        "Calt": "C7(#9,b13)",
        "C7alt": "C7(#9,b13)",
    }

    error_prone_labels_from_log = [ # 以前のログから問題があったもの
        "Am7(add11)", "E7(b9)", "C7sus4", "Fmaj7(add9)", "Bbmaj9(#11)", 
        "C7(#9,b13)", "Dm7(add13)", "A7(b9)", "Fmaj7(add9,13)", 
        "C/Bb", "Ebmaj7(#11)", "Bbmaj7(#11)", "Fmaj9(#11)",
        "GM7(", "Am7(add11", "Calt", "C7alt", "Esus4(b9)", "Bbm7(add11)"
    ]
    
    additional_general_tests = [
        "Cmaj7", "Fmaj7", "Cminor7", "Gdominant7",
        "Cm7b5", "Cø7", "Cdim7", "Cdim", "Caug",
        "Dbmajor7", "Ebm", "A-M7",
        "Bbm6", "C M7", "D Min","E dom7", "F half-dim", "G diminished", "A augmented",
        "N.C.", "Rest", "", "  Db  ",
        "C#min7", "F#dom7", "C7(b9,#11,add13)",
        "Gsus", "F/G", "Am/G#", "D/F#", "CbbM7", "CxM7", "C##M7"
    ]
    
    all_test_labels_map = {**harugoro_sus_tests, **harugoro_main_tests}
    all_unique_labels = sorted(list(set(error_prone_labels_from_log + additional_general_tests + list(all_test_labels_map.keys()))))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro Nightly Build v2) ---")
    successful_parses = 0
    failed_parses = 0
    rest_count = 0
    no_pitch_count = 0

    for label_orig in all_unique_labels:
        expected_sanitized = all_test_labels_map.get(label_orig)
        sanitized_result = sanitize_chord_label(label_orig)
        
        test_pass_str = ""
        if expected_sanitized:
            if sanitized_result == expected_sanitized:
                test_pass_str = "✔ (Exp match)"
            else:
                test_pass_str = f"✘ (Exp: '{expected_sanitized}')"
        
        print(f"Original: '{label_orig:<18}' -> Sanitized: '{sanitized_result:<20}' {test_pass_str}")

        cs_obj = None
        if sanitized_result and sanitized_result.upper() == "REST":
            print(f"  Interpreted as Rest.")
            rest_count +=1
        elif sanitized_result:
            try:
                cs_obj = harmony.ChordSymbol(sanitized_result) # ここでパース試行
                if cs_obj and cs_obj.pitches: # 有効なピッチがあるか
                    # figure を表示する際にエラーが起きる可能性も考慮
                    try: figure_display = cs_obj.figure
                    except: figure_display = "[Error in figure display]"
                    print(f"  music21 parsed: {figure_display:<25} (Pitches: {[p.name for p in cs_obj.pitches]})")
                    successful_parses += 1
                else: # ChordSymbolオブジェクトはできたがピッチがない(例: Figure="Rest")
                    figure_str = cs_obj.figure if cs_obj else "N/A"
                    print(f"  music21 parsed '{sanitized_result}' as CS, BUT NO PITCHES (figure: {figure_str}). Treat as REST.")
                    no_pitch_count += 1
            except Exception as e:
                print(f"  music21 ERROR parsing sanitized '{sanitized_result}': {type(e).__name__}: {e}")
                failed_parses += 1
        else: # サニタイズ結果が空文字列など
            print(f"  Sanitized to empty or unhandled: '{sanitized_result}'")
            failed_parses +=1
            
    print(f"\n--- Sanitization Test Summary (Harugoro Nightly Build v2) ---")
    total_attempted_parses = successful_parses + failed_parses + no_pitch_count
    total_labels = len(all_unique_labels)
    print(f"Total unique labels processed: {total_labels}")
    print(f"Successfully parsed with pitches: {successful_parses} / {total_attempted_parses} attempted non-Rest ({ (successful_parses/total_attempted_parses*100) if total_attempted_parses > 0 else 0 :.2f}%)")
    print(f"Parsed but no pitches (Rest): {no_pitch_count}")
    print(f"Failed to parse: {failed_parses}")
    print(f"Explicitly 'Rest' (N.C., etc.): {rest_count}")
    print(f"Estimated overall success (incl. explicit Rests): { (successful_parses + rest_count) / total_labels * 100 if total_labels > 0 else 0 :.2f}%")
# --- END OF FILE generators/core_music_utils.py ---
