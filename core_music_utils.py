# --- START OF FILE utilities/core_music_utils.py (テンション処理改善試行) ---
import music21
import logging
from music21 import meter, harmony, pitch, scale
from typing import Optional, Dict, Any, List
import re

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125

_ROOT_RE_STRICT = re.compile(r'^([A-G](?:[#b]{1,2}|[ns])?)(?![#b])') 
_ROOT_RE_SIMPLE = re.compile(r'^[A-G][#b]?') 

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    ts_str = ts_str or "4/4"; return meter.TimeSignature(ts_str) # 短縮

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> scale.ConcreteScale:
    mode_key = (mode_str or "major").lower(); tonic_val = tonic_str or "C"
    try: tonic_p = pitch.Pitch(tonic_val)
    except Exception: tonic_p = pitch.Pitch("C"); logger.error(f"Invalid tonic '{tonic_val}'. Default C.")
    mode_map: Dict[str, Any] = {"ionian": scale.MajorScale, "major": scale.MajorScale, "dorian": scale.DorianScale, "phrygian": scale.PhrygianScale, "lydian": scale.LydianScale, "mixolydian": scale.MixolydianScale, "aeolian": scale.MinorScale, "minor": scale.MinorScale, "locrian": scale.LocrianScale, "harmonicminor": scale.HarmonicMinorScale, "melodicminor": scale.MelodicMinorScale}
    scl_cls = mode_map.get(mode_key, scale.MajorScale)
    if scl_cls is scale.MajorScale and mode_key not in mode_map: logger.warning(f"Unknown mode '{mode_key}'. Major.")
    try: return scl_cls(tonic_p)
    except Exception: logger.error(f"Error creating scale. Fallback C Major.", exc_info=True); return scale.MajorScale(pitch.Pitch("C"))

def _expand_tension_block_final_polish(seg: str) -> str:
    seg = seg.strip().lower()
    if not seg: return ""
    if seg.startswith(("#", "b")): return seg 
    if seg.startswith("add"):
        match_add_num = re.match(r'add(\d+)', seg)
        if match_add_num: return f"add{match_add_num.group(1)}"
        return "" 
    if seg.isdigit(): return f"add{seg}" 
    if seg in ["omit3", "omit5", "omitroot"]: return seg
    return seg # 不明なものはそのまま返す

def _addify_callback_final_polish(match: re.Match) -> str:
    prefix = match.group(1) or ""
    number = match.group(2)
    if prefix.lower().endswith(('sus', 'sus4', 'sus2', 'add', 'maj', 'm', 'min', 'dim', 'aug', 'ø', 'alt', '7', '9', '11', '13', 'b5', '#5', 'b9', '#9', '#11', 'b13', 'th', 'nd', 'rd', 'st')):
        return match.group(0) 
    return f'{prefix}add{number}'

def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    if not label or not isinstance(label, str): return None
    original_label = label; sanitized = label.strip()
    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}: return None

    word_map_patterns = {
        r'(?i)\b([A-Ga-g][#b\-]*)\s+minor\b': lambda m: m.group(1) + 'm',
        r'(?i)\b([A-Ga-g][#b\-]*)\s+major\b': lambda m: m.group(1) + '', # C major -> C (majは後で付与)
        r'(?i)\b([A-Ga-g][#b\-]*)\s+diminished\b': lambda m: m.group(1) + 'dim',
        r'(?i)\b([A-Ga-g][#b\-]*)\s+augmented\b': lambda m: m.group(1) + 'aug',
        r'(?i)\b([A-Ga-g][#b\-]*)\s+dominant\s*7\b': lambda m: m.group(1) + '7',
    }
    for pat, repl_func in word_map_patterns.items():
        try: sanitized = re.sub(pat, repl_func, sanitized)
        except Exception as e_re_sub: logger.error(f"Error in re.sub for '{pat}': {e_re_sub}")

    root_match_for_case = _ROOT_RE_STRICT.match(sanitized)
    if root_match_for_case:
        root_part = root_match_for_case.group(1); rest_part = sanitized[len(root_part):]
        sanitized = root_part[0].upper() + root_part[1:].lower() + rest_part
    
    sanitized = re.sub(r'^([A-G])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-G])b(?![#b-])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-G])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-G])b(?![#b-])', r'/\1-', sanitized)
    sanitized = re.sub(r'(?i)([A-G][#\-]?(?:\d+)?)(sus)(?![24\d])', r'\g<1>sus4', sanitized) 
    sanitized = re.sub(r'(?i)(sus)([24])', r'sus\2', sanitized) 

    # 括弧処理の改善: 括弧内のテンションをカンマ区切りに整形し、music21が好む形式に近づける
    # 例: C7(#9b13) -> C7(#9,b13), Bbmaj9(#11) -> Bbmaj7(add9,#11)
    
    # C7(#9b13) のような表記を C7(#9,b13) に
    # まず括弧を探し、その中身を処理
    def process_parenthesized_tensions(s: str) -> str:
        def repl_tensions(match_obj):
            base = match_obj.group(1)
            tensions_str = match_obj.group(2)
            # テンションを個別に分離 (#9, b13, add11 など)
            # 数字の前の # や b を維持しつつ、add もキーワードとして認識
            raw_tensions = re.findall(r'([#b]?add\d+|[#b]?\d+|omit\d+|[a-zA-Z]+)', tensions_str)
            processed_tensions = []
            for t in raw_tensions:
                t_lower = t.lower()
                if t_lower.startswith("add"): # add13 -> add13
                    processed_tensions.append(t_lower)
                elif t_lower.startswith(("b", "#")): # b9, #11
                    if len(t_lower) > 1 and t_lower[1:].isdigit():
                         processed_tensions.append(t_lower)
                    else: # b alone, or # alone - unlikely valid tension here
                         processed_tensions.append(t) # そのまま
                elif t_lower.isdigit(): # 9, 11, 13 (addを補うか、基本の拡張とみなすか)
                    # music21は C9 のように数字だけでも解釈できるが、addをつけた方が明確な場合もある
                    # ここでは、他の品質指定がない場合にaddをつけることを検討できるが、一旦そのまま
                    processed_tensions.append(t)
                elif t_lower in ["omit3", "omit5", "omitroot"]:
                    processed_tensions.append(t_lower)
                else: # maj, minなど品質が誤って括弧内に入った場合などはそのまま
                    processed_tensions.append(t)
            
            # Bbmaj9(#11) -> Bbmaj7(add9,#11) のような変換
            if "maj9" in base.lower() and any(t.startswith(("#", "b")) for t in processed_tensions):
                base = base.lower().replace("maj9", "maj7")
                if "add9" not in [pt.lower() for pt in processed_tensions]:
                    processed_tensions.insert(0, "add9") # 先頭にadd9
            elif "9" == base[-1] and base[:-1].lower() != "add" and any(t.startswith(("#", "b")) for t in processed_tensions): # C9(#11) -> C7(#11,add9)
                 base = base[:-1] + "7"
                 if "add9" not in [pt.lower() for pt in processed_tensions]:
                    processed_tensions.append("add9")


            return f"{base}({','.join(processed_tensions)})" if processed_tensions else base

        # 括弧が正しく対応していない場合の処理は複雑なので、ここでは単純なケースのみを対象
        if sanitized.count('(') == 1 and sanitized.count(')') == 1:
            try:
                sanitized = re.sub(r'([A-Ga-g][#b\-]?(?:maj7|m7|7|dim7|m7b5|sus4|sus2|maj|m|dim|aug|alt|ø|6|9|11|13)?)\(([^)]+)\)', repl_tensions, sanitized)
            except Exception as e_paren_proc:
                logger.warning(f"CoreUtils (sanitize): Error processing parenthesized tensions in '{sanitized}': {e_paren_proc}")
        
        # 括弧なしで #9b13 のような表記がある場合 (例: C7#9b13)
        # これを C7(#9,b13) の形に変換する試み
        # 例: C7#9b13 -> C7(#9,b13)
        match_complex_tension = re.match(r'([A-Ga-g][#b\-]?(?:maj7|m7|7|dim7|m7b5|sus4|sus2|maj|m|dim|aug|alt|ø|6|9|11|13)?)([#b]\d+[#b]?\d*)', sanitized)
        if match_complex_tension and '(' not in sanitized : # まだ括弧がない場合のみ
            base_chord_part = match_complex_tension.group(1)
            tension_part_str = match_complex_tension.group(2)
            # テンションを分離 (#9, b13など)
            found_tensions = re.findall(r'[#b]?\d+', tension_part_str)
            if found_tensions:
                sanitized = f"{base_chord_part}({','.join(found_tensions)})"
                logger.debug(f"CoreUtils (sanitize): Converted complex tension '{original_label}' to '{sanitized}'")


    # altコード展開 (括弧処理の後にもう一度行うことで、alt(b9)のようなケースもカバーできる可能性)
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt(?:ered)?', r'\g<1>7(#9,b13)', sanitized, flags=re.IGNORECASE) # music21が好む形に

    # 品質関連の正規化 (順序が重要)
    qual_map = {
        r'(?i)half-diminished7': 'm7b5', r'(?i)halfdim7': 'm7b5', r'(?i)ø7': 'm7b5',
        r'(?i)diminished7': 'dim7', r'(?i)dim7': 'dim7',
        r'(?i)minor-major7': 'mM7', r'(?i)minmaj7': 'mM7', r'(?i)m\(maj7\)': 'mM7',
        r'(?i)major7': 'maj7', r'(?i)M7': 'maj7', # maj7はmusic21が解釈
        r'(?i)minor7': 'm7', r'(?i)min7': 'm7',
        r'(?i)dominant7': '7', r'(?i)dom7': '7',
        r'(?i)ø': 'm7b5', r'(?i)diminished': 'dim', r'(?i)dim': 'dim',
        r'(?i)augmented': 'aug', r'(?i)aug': 'aug', r'(?i)\+': 'aug',
        r'(?i)minor(?![\w\(])': 'm', r'(?i)min(?![\w\(])': 'm', # minor, min の後に文字や括弧が続かない場合
        r'(?i)major(?![\w\(])': '', r'(?i)maj(?![\w\(])': '', r'(?i)M(?!aj|\d|[#b\(])': '',
    }
    for pat, rep in qual_map.items(): sanitized = re.sub(pat, rep, sanitized)
                                                       
    # "add"補完 (コールバック方式)
    try:
      sanitized = re.sub(r'([A-Ga-z][#\-]?(?:[mM](?:aj)?\d*|[dD]im\d*|[aA]ug\d*|ø\d*|[sS]us\d*|[aA]dd\d*|7th|6th|5th|m7b5)?)(\d{2,})(?!add|\d|th|nd|rd|st|\()', _addify_callback_final_polish, sanitized, flags=re.IGNORECASE)
    except Exception as e_addify: logger.warning(f"CoreUtils (sanitize): Error during _addify call: {e_addify}. Label: {sanitized}")

    # susコードの最終修正
    sanitized = re.sub(r'(?i)sus4sus4', 'sus4', sanitized); sanitized = re.sub(r'(?i)sus2sus2', 'sus2', sanitized)
    sanitized = re.sub(r'(?i)sus42', 'sus4', sanitized); sanitized = re.sub(r'(?i)sus24', 'sus2', sanitized)
    sanitized = re.sub(r'(?i)(add)(add)+', r'\1', sanitized) 

    sanitized = re.sub(r'[,\s]', '', sanitized) # カンマとスペース除去
    # 括弧内のテンションのカンマは保持したいので、上記の除去は括弧処理の後の方が良いかもしれない。
    # ただし、music21は C7(#9,b13) のように括弧内にカンマがあっても解釈できる。

    sanitized = re.sub(r'[^a-zA-Z0-9#\-/\u00f8\+\(\),]+$', '', sanitized) # 括弧とカンマは残す
    if sanitized.lower().endswith("add") and not (len(sanitized) > 3 and sanitized.lower()[-4].isdigit()): 
        sanitized = sanitized[:-3]

    if not sanitized: return None

    if sanitized != original_label:
        logger.info(f"CoreUtils (sanitize): Sanitized '{original_label}' -> '{sanitized}' for music21 parsing attempt.")
    
    # 最終パース試行
    try:
        cs_test = harmony.ChordSymbol(sanitized)
        if not cs_test.pitches:
            logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') parsed by music21 but has NO PITCHES. Returning None (Rest).")
            return None
        if not cs_test.root():
             logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') parsed by music21 but has NO ROOT. Returning None (Rest).")
             return None
        # music21が解釈したfigureを返すことで、より標準的な表記になることを期待
        # ただし、元の表記に近い方がデバッグしやすい場合もあるので、状況に応じて sanitized を返すことも検討
        final_figure = cs_test.figure 
        logger.info(f"CoreUtils (sanitize): Successfully validated '{sanitized}' (from '{original_label}') with music21. Figure: '{final_figure}'")
        return final_figure # music21が解釈した表記を返す
    except Exception as e_final_parse:
        logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') FAILED music21 parsing ({type(e_final_parse).__name__}: {e_final_parse}). Returning None (Rest).")
        return None 

def get_music21_chord_object(chord_label_str: Optional[str], current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    if not isinstance(chord_label_str, str) or not chord_label_str.strip():
        logger.debug(f"CoreUtils (get_obj): Input '{chord_label_str}' is empty or not a string. Interpreting as Rest (returning None).")
        return None

    # sanitize_chord_label はNoneを返すことがある（Restの場合など）
    sanitized_label = sanitize_chord_label(chord_label_str) 

    if not sanitized_label: 
        logger.info(f"CoreUtils (get_obj): sanitize_chord_label returned None for '{chord_label_str}'. Interpreting as Rest.")
        return None

    cs = None
    try:
        # サニタイズされたラベルでChordSymbolオブジェクトを生成
        cs = harmony.ChordSymbol(sanitized_label) 
        if not cs.pitches:
            logger.warning(f"CoreUtils (get_obj): ChordSymbol for '{sanitized_label}' (from '{chord_label_str}') created but has NO PITCHES. Interpreting as Rest (None).")
            return None
        if not cs.root():
             logger.warning(f"CoreUtils (get_obj): ChordSymbol for '{sanitized_label}' (from '{chord_label_str}') created but has NO ROOT. Interpreting as Rest (None).")
             return None
        logger.info(f"CoreUtils (get_obj): Successfully created ChordSymbol '{cs.figure}' (from original '{chord_label_str}', sanitized to '{sanitized_label}') with pitches: {[p.nameWithOctave for p in cs.pitches]}")
        return cs
    except harmony.HarmonyException as e_harm:
        # music21でのパースに失敗した場合、ログを出力してNoneを返す (ルートオンリーのフォールバックはsanitize内で行う方針)
        logger.error(f"CoreUtils (get_obj): music21.harmony.HarmonyException for sanitized '{sanitized_label}' (from '{chord_label_str}'): {e_harm}. Returning None (Rest).")
        return None
    except Exception as e_other: 
        logger.error(f"CoreUtils (get_obj): Unexpected Exception for sanitized '{sanitized_label}' (from '{chord_label_str}'): {type(e_other).__name__}: {e_other}. Returning None (Rest).", exc_info=True)
        return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    
    # テストケースを拡充
    test_cases = {
        "E7(b9)": "E7(b9)", "C7(#9,b13)": "C7(#9,b13)", "C7(b9,#11,add13)": "C7(b9,#11,add13)",
        "C7alt": "C7(#9,b13)", "Fmaj7(add9)": "Fmaj7(add9)", "Fmaj7(add9,13)": "Fmaj7(add9,13)", 
        "Bbmaj7(#11)": "B-maj7(#11)", "Cø7": "Cm7b5", "Cm7b5": "Cm7b5", "Cø": "Cm7b5",
        "Am7(add11)": "Am7(add11)", "Am7(add11": "Am7add11", 
        "Dsus": "Dsus4", "Gsus4": "Gsus4", "Asus2": "Asus2", "Csus44": "Csus4",
        "Bbmaj9(#11)": "B-maj7(add9,#11)", # 変換後の期待値
        "F#7": "F#7", "Calt": "C7(#9,b13)", "silence": None,
        "Cminor7": "Cm7", "Gdominant7": "G7",
        "Bb": "B-", "Ebm": "E-m", "F#": "F#", "Dbmaj7": "D-maj7",
        "G7SUS": "G7sus4", "G7sus": "G7sus4", "Gsus": "Gsus4",
        "d minor": "Dm", "e dim": "Edim", "C major7": "Cmaj7", "G AUG": "Gaug", "C major": "C",
        "bad(input": None, "": None, "N.C.": None, "  Db  ": "D-",
        "GM7(": "GM7", "G diminished": "Gdim", 
        "C/Bb": "C/B-", "CbbM7": "C--M7", "C##M7": "C##M7", 
        "C(omit3)": "Comit3", "Fmaj7(add9": "Fmaj7add9",
        "Am7addadd11": "Am7add11", "Gadd": "Gadd", "Fmaj7add": "Fmaj7", 
        "Dm7addadd13": "Dm7add13", "Cadd": "Cadd", "Fmaj7addaddadd13": "Fmaj7add13",
        "B-maj9#11add": "B-maj7(add9,#11)", # 変換後の期待値
        "Gsus2/D": "Gsus2/D", "Cadd9": "Cadd9", "Am(add9)": "Amadd9",
        "Csus4/G": "Csus4/G", "Am7add11": "Am7add11", "G13": "G13", 
        "Bo7": "Bdim7", "E7b9": "E7(b9)", "Fmaj7add9": "Fmaj7(add9)", 
        "C/E": "C/E", "Gm7b5": "Gm7b5", "C7#9b13": "C7(#9,b13)", 
        "Dm7add13": "Dm7(add13)", "Em7b5": "Em7b5", "A7b9": "A7(b9)", 
        "C13": "C13", "Bbmaj9#11": "B-maj7(add9,#11)", "C/Bb": "C/B-", 
        "D7sus4": "D7sus4", "Fmaj7add9add13": "Fmaj7(add9,add13)", 
        "Ebmaj7(#11)": "E-maj7(#11)", "Bbmaj7/D": "B-maj7/D",
        "C7(#9b13)": "C7(#9,b13)", # 括弧なしテンションの変換テスト
        "C7#9b13": "C7(#9,b13)",   # 同上
        "BbmM7": "B-mM7",      # マイナーメイジャーセブンス
        "C(add9,11)": "C(add9,add11)", # 括弧内カンマ区切り
        "C(add9 add11)": "C(add9,add11)", # 括弧内スペース区切り
        "C(b9,#11)": "C(b9,#11)",
        "Cmaj": "C",
        "C minor": "Cm",
        "Cdiminished": "Cdim",
        "Caugmented": "Caug",
        "C dominant 7": "C7",
        "C sus": "Csus4",
        "C sus 2": "Csus2",
        "C(#5, b9)": "Caug(b9)", # music21は C(#5,b9) を Caug(b9) と解釈する
        "Cmaj7(#11, add13)": "Cmaj7(#11,add13)",
        "C M": "C", # 単なるMは削除
        "CmM7": "CmM7",
        "C (add9)": "C(add9)", # スペース入り括弧
        "C (add9, omit3)": "C(add9,omit3)",
        "Cadd9omit3": "Cadd9omit3",
        "C9#11": "C7(add9,#11)", # 9thコードのテンション
        "Cm9(add11)": "Cm7(add9,add11)",
        "C(add#11)": "C(add#11)", # addの後に#
        "C(addb9)": "C(addb9)",   # addの後にb
        "Cmaj13(#11)": "Cmaj7(add9,add#11,add13)", # music21の解釈に近づける
        "C13(#11,b9)": "C7(b9,add#11,add13)",
        "C7(b9,#9,#11,b13)": "C7(b9,#9,#11,b13)",
        "C7(omit3,add13)": "C7(omit3,add13)",
        "Cmaj7 no 3rd": "Cmaj7(omit3)", # omitのエイリアス
        "Cmaj7 no third": "Cmaj7(omit3)",
        "Cmaj7 no3": "Cmaj7(omit3)",
        "Cmaj7omit3": "Cmaj7omit3",
        "C(add9)(#11)": "C(add9,#11)", # 二重括弧の平坦化
        "C(add9,(#11))": "C(add9,#11)",
        "C((add9))": "C(add9)",
        "C(add9, omit3, #11, b13)": "C(add9,omit3,#11,b13)",
        "Cmaj7/G#": "Cmaj7/G#", # スラッシュコードのベース音
        "Cmaj7 / G#": "Cmaj7/G#",
        "Cmaj7/g#": "Cmaj7/G#",
        "Cmaj7 / g sharp": "Cmaj7/G#",
        "Cmaj7/g##": "Cmaj7/G##",
        "Cmaj7/g--": "Cmaj7/G--",
        "Cmaj7/gb": "Cmaj7/G-",
        "Cmaj7/g flat": "Cmaj7/G-",
        "Cmaj7/g natural": "Cmaj7/G",
        "Cmaj7/gn": "Cmaj7/G",
        "Cmaj7/g": "Cmaj7/G",
        "Cmaj7 / g": "Cmaj7/G",
        "Cmaj7/ g": "Cmaj7/G",
        "Cmaj7 /g": "Cmaj7/G",
        "Cmaj7 /  g  ": "Cmaj7/G",
        "C(add9)/E": "C(add9)/E",
        "C(add9) / E": "C(add9)/E",
        "C(add9) / e": "C(add9)/E",
        "C(add9)/ e": "C(add9)/E",
        "C(add9) /e": "C(add9)/E",
        "C(add9)  /  e  ": "C(add9)/E",
        "C(add9)/E-": "C(add9)/E-",
        "C(add9)/E--": "C(add9)/E--",
        "C(add9)/E#": "C(add9)/E#",
        "C(add9)/E##": "C(add9)/E##",
        "C(add9)/En": "C(add9)/E",
        "C(add9)/E natural": "C(add9)/E",
        "C(add9)/E flat": "C(add9)/E-",
        "C(add9)/E sharp": "C(add9)/E#",
    }
    
    other_tests = ["Rest", "Dsus2", "Dsus4", "Csu", "Am(add9)/G#"] 
    all_labels_to_test = sorted(list(set(list(test_cases.keys()) + other_tests)))

    print("\n--- Running sanitize_chord_label Test Cases (Harugoro x o3 Masterpiece Final Polish - Enhanced v2) ---")
    s_parses = 0; f_parses = 0; r_count = 0; exp_match = 0; exp_mismatch = 0

    for label_orig in all_labels_to_test:
        expected_sanitized = test_cases.get(label_orig) # サニタイズ後の期待値
        sanitized_res = sanitize_chord_label(label_orig) 
        
        eval_str = ""
        if expected_sanitized is None: 
            if sanitized_res is None: eval_str = "✔ (OK, Interpreted as Rest)"; exp_match +=1
            else: eval_str = f"✘ (Exp: Rest (None), Got Sanitized: '{sanitized_res}')"; exp_mismatch +=1
        elif sanitized_res == expected_sanitized:
            eval_str = "✔ (OK, Expected Sanitized Form)"; exp_match +=1
        else: 
            eval_str = f"✘ (Exp Sanitized: '{expected_sanitized}', Got Sanitized: '{sanitized_res}')"; exp_mismatch +=1
        
        print(f"Original: '{label_orig:<25}' -> Sanitized: '{str(sanitized_res):<30}' {eval_str}")

        cs_obj = get_music21_chord_object(label_orig) 
        
        if cs_obj:
            try: fig_disp = cs_obj.figure
            except: fig_disp = "[Error Retrieving Figure]"
            pitches_str = ", ".join(sorted(list(set(p.name for p in cs_obj.pitches)))) if cs_obj.pitches else "No Pitches"
            root_str = cs_obj.root().name if cs_obj.root() else "No Root"
            bass_str = cs_obj.bass().name if cs_obj.bass() else "No Bass"
            print(f"  └─> music21 obj: '{fig_disp:<30}' Root: {root_str:<5} Bass: {bass_str:<5} (Unique Pitches: {pitches_str})")
            s_parses += 1
        elif sanitize_chord_label(label_orig) is None : 
            print(f"  └─> Interpreted as Rest (sanitize_chord_label returned None).")
            r_count += 1
        else: 
            print(f"  └─> music21 FAILED or NO PITCHES for sanitized '{sanitized_res}' (from original '{label_orig}')")
            f_parses += 1

    print(f"\n--- Test Summary (Harugoro x o3 Masterpiece Final Polish - Enhanced v2) ---")
    total_labels = len(all_labels_to_test)
    attempted_to_parse = total_labels - r_count

    print(f"Total unique labels processed: {total_labels}")
    if exp_match + exp_mismatch > 0:
      print(f"Matches with expected sanitization outcome (incl. Rest as None): {exp_match}")
      print(f"Mismatches with expected sanitization outcome: {exp_mismatch}")
    print(f"Successfully parsed by music21 (Chord obj with pitches & root): {s_parses} / {attempted_to_parse} non-Rest attempts")
    print(f"Failed to parse by music21 (or no pitches/root) after sanitization: {f_parses}")
    print(f"Interpreted as 'Rest' (sanitize_chord_label returned None): {r_count}")
    
    functional_success_count = s_parses + r_count
    overall_success_rate = (functional_success_count / total_labels * 100) if total_labels > 0 else 0
    print(f"Estimated overall functional success (parsed by music21 + correctly identified as Rest): {overall_success_rate:.2f}%")

# --- END OF FILE utilities/core_music_utils.py ---
