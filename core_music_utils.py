# --- START OF FILE generators/core_music_utils.py (Harugoro x o3 統合最終版) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, Tuple, List
import re

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    ts_str = ts_str or "4/4" # o3さんスタイル: デフォルト値処理
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning(f"GTSO: Invalid TS '{ts_str}'. Default 4/4.") # o3さんログスタイル参考
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
    scl_cls = mode_map.get(mode_key) # キーが存在しない場合はNone
    if scl_cls:
        try:
            return scl_cls(tonic_p)
        except Exception as e_create:
            logger.error(f"BuildScale: Error creating '{scl_cls.__name__}' for {tonic_p.name}: {e_create}. Fallback C Major.", exc_info=True)
            return scale.MajorScale(pitch.Pitch("C")) # フォールバック
    else:
        logger.warning(f"BuildScale: Unknown mode '{mode_key}'. Using MajorScale with {tonic_p.name}.")
        return scale.MajorScale(tonic_p) # 不明なモードはMajorScaleで


def sanitize_chord_label(label: str) -> str: # o3さん版はOptional[str]を返すが、ここでは"Rest"文字列か整形後文字列
    if not isinstance(label, str):
        logger.warning(f"Sanitize: Label '{label}' not str. Returning as 'Rest'.")
        return "Rest" # もし厳密にNoneを返したいならこの部分を変更

    original_label = label
    sanitized = label.strip()

    # o3さん版のRest判定強化 (空文字列も含む)
    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"Sanitize: '{original_label}' to 'Rest' (via extended patterns).")
        return "Rest"

    # --- Harugoro様「最終パッチ」と "o3"さんアプローチの融合 ---
    # 1. ルート音とスラッシュベース音のフラット正規化 (b -> -, bb -> --)
    #    (シャープはmusic21標準なので基本的に変更不要)
    #    o3さん版は 'bb' に未対応だったので追加
    sanitized = re.sub(r'^([A-Ga-g])bb', r'\1--', sanitized) #  例: Bbb -> B--
    sanitized = re.sub(r'^([A-Ga-g])b(?![#b])', r'\1-', sanitized)  #  例: Bb -> B- (ただし Bb#9 の 'b' は変更しない)
    sanitized = re.sub(r'/([A-Ga-g])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-Ga-g])b(?![#b])', r'/\1-', sanitized)

    # 2. 括弧の不均衡修正 (開き括弧のみの場合、それ以前の内容を保持)
    if '(' in sanitized and ')' not in sanitized:
        logger.info(f"Sanitize: Dangling '(', keeping content before it for '{original_label}' -> '{sanitized.split('(')[0]}'")
        sanitized = sanitized.split('(')[0]
    
    # 3. 括弧を展開し、中身をフラット化 (スペース・カンマ除去、キーワード維持)
    #    o3さん版 & Harugoro様提案: while ループで対応
    prev_sanitized_state = ""
    loop_count = 0
    while '(' in sanitized and ')' in sanitized and sanitized != prev_sanitized_state and loop_count < 5: # 無限ループ防止
        prev_sanitized_state = sanitized
        loop_count += 1
        match = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if match:
            base, tens, suf = match.groups()
            # 括弧内からカンマとスペースを完全に除去 (Harugoro様の強力な平坦化)
            tens_cleaned = re.sub(r'[,\s]', '', tens)
            sanitized = base + tens_cleaned + suf
        else: # マッチしない場合はループ中断 (ありえないはずだが念のため)
            break
            
    # 4. "add" キーワードの保持・正規化 (小文字 'add' + 数字)
    sanitized = re.sub(r'(?i)(add)(\d+)', r'add\2', sanitized)

    # 5. maj7addX, maj9addX などの正規形へ
    #    (括弧展開で add が消えて数字だけが残ったケースを想定:例 Fmaj79 -> Fmaj7add9)
    sanitized = re.sub(r'(?i)(maj[79])(\d+)(?!add)', r'\1add\2', sanitized)
    #    (maj7(add#11) のような形が maj7#11 のようになった場合も、これを許容)
    sanitized = re.sub(r'(maj[79])(?:add)?(#\d+)', r'\1\2', sanitized, flags=re.IGNORECASE)


    # 6. 品質関連の正規化 (ø, half-dim, dim, dom など)
    #    o3さん版などを参考に拡充
    sanitized = re.sub(r'(?i)ø7?\b', 'm7b5', sanitized) # ø も ø7 も m7b5 に
    sanitized = re.sub(r'(?i)half[- ]?dim\b', 'm7b5', sanitized)
    sanitized = sanitized.replace('dimished', 'dim') # タイポ修正
    sanitized = re.sub(r'(?i)diminished(?!7)', 'dim', sanitized)
    sanitized = re.sub(r'(?i)diminished7', 'dim7', sanitized)
    sanitized = sanitized.replace('domant7', '7') # タイポ修正
    sanitized = re.sub(r'(?i)dominant7?\b', '7', sanitized) # dominantもdomも7に
    sanitized = re.sub(r'(?i)major7', 'maj7', sanitized) # Major7 -> maj7 (小文字統一のため)
    sanitized = re.sub(r'(?i)major9', 'maj9', sanitized)
    sanitized = re.sub(r'(?i)major13', 'maj13', sanitized)
    sanitized = re.sub(r'(?i)minor7', 'm7', sanitized)
    sanitized = re.sub(r'(?i)minor9', 'm9', sanitized)
    sanitized = re.sub(r'(?i)minor11', 'm11', sanitized)
    sanitized = re.sub(r'(?i)minor13', 'm13', sanitized)
    sanitized = re.sub(r'(?i)min(?!or\b|\.)', 'm', sanitized)
    sanitized = re.sub(r'(?i)augmented', 'aug', sanitized)


    # 7. alt コードの展開 (o3さん版の正確なグループ参照を使用)
    sanitized = re.sub(r'([A-Ga-g][#\-]?)7?alt', r'\g<1>7#9b13', sanitized, flags=re.IGNORECASE)

    # 8. susコードの正規化 (Harugoro様修正 \g<1>4)
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized) # 既に重複しているものを修正
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)
    try: # 正しいグループ参照でエラーは起きないはずだが念のため
        sanitized = re.sub(r'(?i)(sus)(?![24\d])', r'\g<1>4', sanitized)
    except re.error as e_re_sus:
        logger.warning(f"Sanitize: Regex error during sus normalization for '{sanitized}': {e_re_sus}")

    # 9. 最終的な全体の不要スペース・カンマ除去（かなり強力）
    sanitized = re.sub(r'[,\s]', '', sanitized)
    
    # 末尾に予期せず残った変化記号や特殊文字の除去（例: "Cm7b5@" -> "Cm7b5")
    sanitized = re.sub(r'[^a-zA-Z0-9#\-/\u00f8]+$', '', sanitized) # ø (U+00F8) は許可

    if sanitized != original_label:
        logger.info(f"Sanitize: '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"Sanitize: Label '{original_label}' no change.")
    return sanitized

# `get_music21_chord_object` と `if __name__ == '__main__':` は、
# 前回の「(修正案 2025-05-23 v2)」のものをベースに、
# `harugoro_final_expected` の期待値をこの新しい `sanitize_chord_label` の挙動に合わせて
# 再度調整して使用するのが理想的です。

def get_music21_chord_object(chord_label_str: str, current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    if not isinstance(chord_label_str, str) or not chord_label_str.strip(): # "" や None は Rest
        logger.debug(f"get_music21_chord_object: Input '{chord_label_str}' is empty or not string. Interpreted as Rest.")
        return None # Rest の場合は None を返す (o3さんスタイルに近づける)

    sanitized_label = sanitize_chord_label(chord_label_str)
    
    if not sanitized_label or sanitized_label.upper() == "REST": # sanitize_chord_label が "Rest" または "" を返した場合
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
    except music21.exceptions21.Music21Exception as m21e: # AccidentalException, etc.
        logger.error(f"get_music21_chord_object: Music21Exception for '{sanitized_label}' (orig:'{chord_label_str}'): {m21e}. Treating as Rest.")
    except Exception as e:
        logger.error(f"get_music21_chord_object: Unexpected error for '{sanitized_label}' (orig:'{chord_label_str}'): {e}. Treating as Rest.", exc_info=True)
    
    return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    
    # 最新のsanitize_chord_labelの挙動に合わせた期待値 (一部はmusic21の解釈に依存)
    final_expected_outcomes = {
        "E7(b9)": "E7b9",
        "C7(#9,b13)": "C7#9b13",
        "C7(b9,#11,add13)": "C7b9#11add13",
        "C7alt": "C7#9b13",
        "Fmaj7(add9)": "Fmaj7add9",
        "Fmaj7(add9,13)": "Fmaj7add9add13",
        "Bbmaj7(#11)": "B-maj7#11",
        "Cø7": "Cm7b5",         # ø7 は m7b5 へ
        "Cm7b5": "Cm7b5",       # 変更なし
        "Cø": "Cm7b5",          # ø も m7b5 へ
        "Am7(add11)": "Am7add11",
        "Dsus": "Dsus4",
        "Gsus4": "Gsus4",
        "Asus2": "Asus2",
        "Csus44": "Csus4",      # 重複修正
        "Bbmaj9(#11)": "B-maj9#11",
        "F#7": "F#7",
        "Calt": "C7#9b13",
        # "o3"さんのテストケース例
        "silence": "Rest", # sanitize_chord_label で "Rest" になる
        "Am7(add11": "Am7add11", # 不完全な括弧は修正期待
        "Cminor7": "Cm7",
        "Gdominant7": "G7",
        "Bb": "B-",
        "Ebm": "E-m",
        "F#": "F#",
        "Dbmaj7": "D-maj7"
    }
    
    other_tests = [
        "N.C.", "Rest", "", "  Db  ", "GM7(",
        "C/Bb", "CbbM7", "C##M7", "C augmented", "G diminished"
    ]
    
    all_labels_to_test_final = sorted(list(set(list(final_expected_outcomes.keys()) + other_tests)))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro x o3 Final Build) ---")
    s_parses = 0; f_parses = 0; r_count = 0; np_count = 0; exp_match_count = 0; exp_mismatch_count = 0

    for label_orig in all_labels_to_test_final:
        expected_val = final_expected_outcomes.get(label_orig)
        sanitized_res = sanitize_chord_label(label_orig)
        
        eval_str = ""
        if expected_val:
            if sanitized_res == expected_val: eval_str = "✔ (Exp OK)"; exp_match_count +=1
            else: eval_str = f"✘ (Exp: '{expected_val}')"; exp_mismatch_count +=1
        
        print(f"Original: '{label_orig:<18}' -> Sanitized: '{sanitized_res:<20}' {eval_str}")

        cs_final = get_music21_chord_object(label_orig) # get_music21_chord_objectが内部でsanitizeを呼ぶ
        
        if cs_final: # Noneでなければパース成功
            try: fig_disp = cs_final.figure
            except: fig_disp = "[ErrFig]"
            print(f"  music21 obj: {fig_disp:<25} (Pitches: {[p.name for p in cs_final.pitches]})"); s_parses += 1
        elif sanitized_res == "Rest": # sanitize_chord_label が "Rest" を返した場合
            print(f"  Interpreted as Rest by sanitize_chord_label.")
            r_count += 1
        elif get_music21_chord_object(label_orig) is None and sanitize_chord_label(label_orig) is not None and sanitize_chord_label(label_orig).upper() != "REST" : # パース失敗
            # get_music21_chord_objectのログで詳細は出るので、ここでは失敗カウントのみ
            print(f"  music21 ERROR parsing sanitized '{sanitize_chord_label(label_orig)}'") # 再度sanitizeして表示
            f_parses += 1
        # N.C.などは get_music21_chord_object が直接Noneを返す (np_countやf_parsesに二重計上しない)

    print(f"\n--- Test Summary (Harugoro x o3 Final Build) ---")
    total_labels_final = len(all_labels_to_test_final)
    # パース試行されたのは、明示的にRestにならなかったもの
    attempted_to_parse_count = total_labels_final - r_count

    print(f"Total unique labels processed: {total_labels_final}")
    if expected_val: # 期待値との比較を行った場合のみ表示
        print(f"Matches with expected sanitization: {exp_match_count}")
        print(f"Mismatches with expected sanitization: {exp_mismatch_count}")
    print(f"Successfully parsed by music21 (got Chord object with pitches): {s_parses} / {attempted_to_parse_count} non-Rest attempts")
    # f_parsesはget_music21_chord_objectがNoneを返したが、sanitize_labelが"Rest"以外だったケース
    # (実際にはget_music21_chord_object内のログで詳細エラーが出る)
    print(f"Failed to parse by music21 (error or no pitches): {f_parses + (attempted_to_parse_count - s_parses - f_parses)}") # np_countの概念は廃止
    print(f"Explicitly identified as 'Rest' by sanitize_chord_label: {r_count}")
    
    overall_success_rate = ((s_parses + r_count) / total_labels_final * 100) if total_labels_final > 0 else 0
    print(f"Estimated overall functional success (incl. explicit Rests): {overall_success_rate:.2f}%")

# --- END OF FILE generators/core_music_utils.py ---
