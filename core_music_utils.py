# --- START OF FILE generators/core_music_utils.py (修正案 2025-05-22 夜) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, Tuple, List
import re

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125 # (これはこのファイルでは使われていないが、他で使われている可能性あり)

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

    # --- Harugoro様提案の修正ポイントを統合 ---
    # 1) 再帰的に括弧テンションを展開 (Harugoro様のwhileループ案)
    #    例: C7(#9,b13) -> C7#9b13, Am7(add11) -> Am7add11
    #    music21が "(#9,b13)" や "(add11)" の形を好むことを考慮し、
    #    ここでは「括弧を完全に除去」するのではなく、「二重括弧を除去し、中身を維持」する方向に調整。
    #    ただし、もしHarugoro様の意図が「括弧そのものを削除」であれば、以下を調整。
    temp_sanitized = sanitized
    iteration_count = 0
    max_iterations = 5 # 無限ループ防止
    while '(' in temp_sanitized and ')' in temp_sanitized and iteration_count < max_iterations:
        iteration_count += 1
        # 最も内側の括弧から処理するイメージ (実際は最も左の括弧から)
        m = re.search(r'^(.*?)(\([^)]*\))(.*)$', temp_sanitized) # 修正: 非貪欲マッチと中身をキャプチャ
        if not m:
            break
        pre_paren, paren_content_with_parens, post_paren = m.groups()
        
        # 括弧の中身だけ取り出す
        paren_content_inner = paren_content_with_parens[1:-1]
        
        # 中身のカンマや空白を削除するか、music21が解釈できる形に整形するか
        # Harugoro様の案: re.sub(r'[,\s]', '', tens) -- カンマとスペースを完全に除去
        # ここでは music21 v9 の挙動に期待し、過度な除去はせず、スペースの正規化程度に留める
        paren_content_cleaned = re.sub(r'\s*,\s*', ',', paren_content_inner.strip()) # カンマ周りのスペース整理
        paren_content_cleaned = re.sub(r'\s+', ' ', paren_content_cleaned) # 連続スペースを一つに

        # 再構築: Harugoro様案では base + tens_cleaned + suf (括弧を除去)
        # music21 は括弧付きを好むため、ここでは括弧を維持
        temp_sanitized = f"{pre_paren}({paren_content_cleaned}){post_paren}"

        # 二重括弧が生じていたら単純化
        temp_sanitized = temp_sanitized.replace('((', '(').replace('))', ')')

    sanitized = temp_sanitized
    
    # 二重括弧の最終チェックと除去 (もし残っていた場合)
    while '((' in sanitized or '))' in sanitized:
        sanitized = sanitized.replace('((', '(').replace('))', ')')

    # 2) 末尾に残った '(' を除去 (Harugoro様の提案)
    sanitized = sanitized.rstrip('(')


    # ステップ 1b: 基本的な品質表記の正規化 (大文字小文字区別なし)
    # ★ Harugoro様の提案「Quality変換を削除（maj/minをそのまま残す）」は、
    #    括弧付きの場合に影響するとのこと。
    #    ここでは、括弧処理の後で品質変換を行うことで、影響を最小限に抑えることを試みる。
    #    または、music21がmaj/minを受け付けるなら変換しないのも手。
    #    テスト結果に応じて、このブロックの有効/無効を判断。
    #    現状、`Fmaj7` は `FM7` にしない方が安全かもしれないというテスト結果を踏まえ、
    #    この変換は控えめにするか、問題が再発しないか注視する。
    #    今回はHarugoro様提案の「変換削除」に近い形として、問題のあるmaj->Mは避ける
    quality_replacements = {
        # r'(?i)maj7': 'M7', # これが括弧付きで問題を起こす可能性を指摘されたためコメントアウト
        # r'(?i)maj9': 'M9',
        # r'(?i)maj13': 'M13',
        r'(?i)min7': 'm7', r'(?i)mi7': 'm7',
        r'(?i)min9': 'm9', r'(?i)mi9': 'm9',
        r'(?i)min11': 'm11',r'(?i)mi11': 'm11',
        r'(?i)min13': 'm13',r'(?i)mi13': 'm13',
        r'(?i)dom7': '7',
        r'(?i)half-diminished': 'ø', r'(?i)ø7': 'ø', r'm7b5': 'ø',
        r'(?i)diminished7': 'dim7', r'(?i)dim7': 'dim7',
        r'(?i)diminished(?!\()': 'dim', # dim( のように括弧が続く場合は除外
        r'(?i)dim(?!7|\()': 'dim',      # dim7 や dim( を除外
        r'(?i)augmented(?!\()': 'aug',
        r'(?i)aug(?!m|\()': 'aug',
    }
    for old, new in quality_replacements.items():
        sanitized = re.sub(old, new, sanitized)

    # 3) sus4 / sus2 重複ガード (Harugoro様の提案: 末尾アンカーと数字指定)
    #    Csus4 -> Csus4 (変化なし)
    #    C7sus -> C7sus4
    #    Csus44 -> Csus4 (もし発生していたら修正)
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized) # 事後処理
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized) # 事後処理
    # `sus` で終わり、直後に4や2がない場合 -> `sus4`
    sanitized = re.sub(r'(?i)(sus)(?![24])', r'\14', sanitized)


    # ステップ 2: ルート音とベース音の臨時記号を正規化
    parts = sanitized.split('/')
    root_part_str = parts[0]
    bass_part_str = parts[1] if len(parts) > 1 else None

    def normalize_note_part(part_str):
        if not part_str: return ""
        # 基本的な臨時記号の正規化
        part_str = part_str.replace('bb', '--').replace('b', '-')
        # music21は "Cb" より "C-" を好む。"C##" は "Cx" だが "C##" も可
        return part_str

    sanitized_root = normalize_note_part(root_part_str)
    sanitized_bass = normalize_note_part(bass_part_str) if bass_part_str else None

    if sanitized_bass:
        sanitized = f"{sanitized_root}/{sanitized_bass}"
    else:
        sanitized = sanitized_root

    # 4) alt 展開 (Harugoro様の提案)
    #    music21 は alt をそのまま解釈しない
    #    Xalt  -> X7#9b13 (最も一般的な解釈)
    #    X7alt -> X7#9b13
    #    これは、ChordSymbol オブジェクト作成後に alter する方がより music21 的ではあるが、
    #    文字列置換で対応するならこのように。
    if re.fullmatch(r'[A-G][#\-]*alt', sanitized, flags=re.IGNORECASE):
        sanitized = sanitized.lower().replace('alt', '7(#9,b13)') # music21が解釈しやすいように括弧付きに
    elif re.fullmatch(r'[A-G][#\-]*7alt', sanitized, flags=re.IGNORECASE):
        sanitized = sanitized.lower().replace('alt', '(#9,b13)') # 同上
    # さらに具体的に #(sharp), b(flat) の記号に変換するなら:
    sanitized = sanitized.replace("#9", " sharp9").replace("b9", " flat9") # (など、alterationToValue の仕様に合わせる)
    sanitized = sanitized.replace("#11", " sharp11").replace("b11", " flat11")
    sanitized = sanitized.replace("#13", " sharp13").replace("b13", " flat13")
    # スペースで区切られた方がmusic21のパーサーは安定する傾向
    sanitized = sanitized.replace("sharp", " #").replace("flat", " b") # 例 C7( #9, b13)

    # 不要なスペースの最終整理（特に括弧の内外、カンマ周り）
    sanitized = re.sub(r'\s*\(\s*', '(', sanitized)
    sanitized = re.sub(r'\s*\)\s*', ')', sanitized)
    sanitized = re.sub(r'\s*,\s*', ',', sanitized)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip() # 全体から余分なスペースを削除

    if sanitized != original_label:
        logger.info(f"sanitize_chord_label: Sanitized '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"sanitize_chord_label: Label '{original_label}' required no changes by sanitization.")

    return sanitized


def get_music21_chord_object(chord_label_str: str, current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    # ... (変更なし、ただし呼び出す sanitize_chord_label が新しくなっている) ...
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
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    # Harugoro様の提案テストケース + 既存テストケース
    harugoro_tests = {
        "E7(b9)": "E7(b9)", # music21 can parse this
        "C7(#9,b13)": "C7(#9,b13)", # music21 can parse this (with correct spacing)
        "Am7(add11)": "Am7(add11)", # music21 can parse this
        "Csus4": "Csus4",
        "Esus4(b9)": "Esus4(b9)",
        "Calt": "C7(#9,b13)",
        "C7alt": "C7(#9,b13)",
    }

    test_labels_from_log = [
        "Am7(add11)", "E7(b9)", "C7sus4", "Fmaj7(add9)",
        "Bbmaj9(#11)", "C7(#9,b13)", "Dm7(add13)", "A7(b9)",
        "Fmaj7(add9,13)", "C/Bb", "Ebmaj7(#11)", "Bbmaj7(#11)",
        "Fmaj9(#11)"
    ]
    additional_tests = [
        "Cmaj7", "Fmaj7", "Cm7b5", "G7sus",
        "Dbmaj7", "Ebm7", "Abmaj7", "Bbm6",
        "FM7", "B-M7", "C", "Am", "G", "Dbm",
        "N.C.", "Rest", "", "GM7(", "Am7(add11",
        "C#m7", "F#7", "C7(b9,#11)", "Gaug", "Fdim",
        "Gsus", "F/G", "Am/G#", "D/F#",
        "Esus4(b9)", "Bb", "Eb/G", "C#",
        "Am7", "Dm7", "GM7",
        "C M7", "C min7", "C dom7", "C half-diminished", "C diminished", "C augmented",
        "C7 sus", "CbbM7" # double flat test
    ]
    
    all_unique_labels = sorted(list(set(test_labels_from_log + additional_tests + list(harugoro_tests.keys()))))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro Nightly Build) ---")
    successful_parses = 0
    failed_parses = 0
    
    # ここでエラーログから特定されたラベルもテスト対象に追加
    error_prone_labels_from_previous_log = [
        "Am7(add11)", "E7(b9)", "C7sus4", "Fmaj7(add9)", "Bbmaj9(#11)", "C7(#9,b13)", 
        "Dm7(add13)", "A7(b9)", "Fmaj7(add9,13)", "Ebmaj7(#11)", "Bbmaj7(#11)", 
        "Fmaj9(#11)", "Calt", "C7alt"
    ]
    all_unique_labels = sorted(list(set(all_unique_labels + error_prone_labels_from_previous_log)))


    for label_orig in all_unique_labels:
        expected_sanitized = harugoro_tests.get(label_orig) # Harugoro様の期待値があればそれ
        sanitized_result = sanitize_chord_label(label_orig)
        
        test_pass_str = ""
        if expected_sanitized:
            if sanitized_result == expected_sanitized:
                test_pass_str = "✔ (Expected match)"
            else:
                test_pass_str = f"✘ (Expected '{expected_sanitized}')"
        
        print(f"Original: '{label_orig:<15}' -> Sanitized: '{sanitized_result:<15}' {test_pass_str}")

        cs_obj = None
        if sanitized_result and sanitized_result.upper() not in ["N.C.", "NC", "REST"]:
            try:
                cs_obj = harmony.ChordSymbol(sanitized_result)
                if cs_obj and cs_obj.pitches:
                    print(f"  music21 parsed: {cs_obj.figure:<20} (Pitches: {[p.name for p in cs_obj.pitches]})")
                    successful_parses += 1
                else:
                    figure_str = cs_obj.figure if cs_obj else "N/A"
                    print(f"  music21 parsed '{sanitized_result}' as ChordSymbol, BUT NO PITCHES (figure: {figure_str}). Interpreted as REST.")
                    failed_parses += 1
            except Exception as e:
                print(f"  music21 ERROR parsing sanitized '{sanitized_result}': {type(e).__name__}: {e}")
                failed_parses += 1
        elif sanitized_result.upper() == "REST":
            print(f"  Interpreted as Rest.")
        else:
            print(f"  Sanitized to empty or unhandled: '{sanitized_result}'")
            failed_parses +=1

    print(f"\n--- Sanitization Test Summary (Harugoro Nightly Build) ---")
    total_tests = successful_parses + failed_parses
    success_rate = (successful_parses / total_tests * 100) if total_tests > 0 else 0
    print(f"Total unique labels tested: {total_tests}")
    print(f"Successfully parsed ChordSymbols with pitches: {successful_parses} ({success_rate:.2f}%)")
    print(f"Failed/Rest/NoPitches ChordSymbols: {failed_parses}")

# --- END OF FILE generators/core_music_utils.py ---
