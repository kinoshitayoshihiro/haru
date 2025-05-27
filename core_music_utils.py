# --- START OF FILE utilities/core_music_utils.py (役割特化版ベース + o3さん最新方針適用・改) ---
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
    ts_str = ts_str or "4/4"
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException: # music21.meter.MeterException をキャッチ
        logger.warning(f"CoreUtils (GTSO): Invalid TimeSignature string '{ts_str}'. Defaulting to 4/4.")
        return meter.TimeSignature("4/4")
    except Exception as e_ts:
        logger.error(f"CoreUtils (GTSO): Unexpected error creating TimeSignature from '{ts_str}': {e_ts}. Defaulting to 4/4.", exc_info=True)
        return meter.TimeSignature("4/4")

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> scale.ConcreteScale:
    mode_key = (mode_str or "major").lower(); tonic_val = tonic_str or "C"
    try: tonic_p = pitch.Pitch(tonic_val)
    except Exception: tonic_p = pitch.Pitch("C"); logger.error(f"Invalid tonic '{tonic_val}'. Default C.")
    mode_map: Dict[str, Any] = {"ionian": scale.MajorScale, "major": scale.MajorScale, "dorian": scale.DorianScale, "phrygian": scale.PhrygianScale, "lydian": scale.LydianScale, "mixolydian": scale.MixolydianScale, "aeolian": scale.MinorScale, "minor": scale.MinorScale, "locrian": scale.LocrianScale, "harmonicminor": scale.HarmonicMinorScale, "melodicminor": scale.MelodicMinorScale}
    scl_cls = mode_map.get(mode_key, scale.MajorScale)
    if scl_cls is scale.MajorScale and mode_key not in mode_map: logger.warning(f"Unknown mode '{mode_key}'. Major.")
    try: return scl_cls(tonic_p)
    except Exception: logger.error(f"Error creating scale. Fallback C Major.", exc_info=True); return scale.MajorScale(pitch.Pitch("C"))

def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    if label is None: # JSONのnullはPythonのNoneになる
        logger.debug(f"CoreUtils (sanitize): Label is None. Returning None (interpreted as Rest).")
        return None
    if not isinstance(label, str):
        logger.warning(f"CoreUtils (sanitize): Label '{label}' is not a string. Returning None (Rest).")
        return None
    
    original_label = label
    sanitized = label.strip()

    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"CoreUtils (sanitize): Label '{original_label}' matches a Rest keyword. Returning None.")
        return None

    # 0. 基本的な正規化
    # ルート音の大文字化
    root_match = _ROOT_RE_STRICT.match(sanitized)
    if not root_match: root_match = _ROOT_RE_SIMPLE.match(sanitized)
    if root_match:
        root_part = root_match.group(1)
        rest_part = sanitized[len(root_part):]
        sanitized = root_part[0].upper() + root_part[1:] + rest_part
    
    # フラット記号の統一 (b -> -)
    sanitized = sanitized.replace('bb', '--').replace('b', '-')
    
    # SUSの正規化 (sus -> sus4, sus 2 -> sus2)
    sanitized = re.sub(r'(?i)sus(?![24\d])', 'sus4', sanitized) 
    sanitized = re.sub(r'(?i)sus\s*([24])', r'sus\1', sanitized)

    # 括弧とカンマは原則として除去 (o3さんの最新方針)
    sanitized = sanitized.replace('(', '').replace(')', '').replace(',', '')
    
    # 全体的なスペースの除去
    sanitized = re.sub(r'\s+', '', sanitized)
    
    # "add" の重複削除
    sanitized = re.sub(r'(?i)(add)(add)+', r'\1', sanitized)

    # 品質関連のエイリアス変換 (シンプルなものに絞る)
    # (例: Cmajor -> C, Cminor -> Cm)
    # o3さんのmusic21_kijyun.jsonを参考に、music21が直接解釈できる形を目指す
    # ここでの過度な変換は避け、chordmap.jsonの記述を信頼する
    if sanitized.lower().endswith("major"): sanitized = sanitized[:-5] # Cmajor -> C
    elif sanitized.lower().endswith("minor"): sanitized = sanitized[:-5] + "m" # Cminor -> Cm
    elif sanitized.lower().endswith("diminished"): sanitized = sanitized[:-10] + "dim"
    elif sanitized.lower().endswith("augmented"): sanitized = sanitized[:-9] + "aug"
    
    # "maj" のみの場合は削除 (例: Cmaj -> C)
    if sanitized.lower().endswith("maj") and not sanitized.lower().endswith("maj7") and not sanitized.lower().endswith("maj9") and not sanitized.lower().endswith("maj11") and not sanitized.lower().endswith("maj13"):
        sanitized = sanitized[:-3]
    # "min" のみの場合は "m" に (例: Cmin -> Cm)
    if sanitized.lower().endswith("min") and not sanitized.lower().endswith("min7") and not sanitized.lower().endswith("min9") and not sanitized.lower().endswith("min11") and not sanitized.lower().endswith("min13"):
        sanitized = sanitized[:-3] + "m"


    if not sanitized:
        logger.info(f"CoreUtils (sanitize): Label '{original_label}' resulted in empty string after basic sanitization. Returning None (Rest).")
        return None

    if sanitized != original_label:
        logger.info(f"CoreUtils (sanitize): Basic sanitization: '{original_label}' -> '{sanitized}'")
    
    # music21による最終パース試行
    try:
        cs_test = harmony.ChordSymbol(sanitized)
        if not cs_test.pitches or not cs_test.root():
            logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') parsed by music21 but has NO PITCHES or NO ROOT. Attempting root extraction from original.")
            root_match_orig = _ROOT_RE_STRICT.match(original_label.strip())
            if not root_match_orig: root_match_orig = _ROOT_RE_SIMPLE.match(original_label.strip())
            if root_match_orig:
                root_str = root_match_orig.group(0)
                root_str_norm = root_str[0].upper() + root_str[1:].replace('b','-').replace('bb','--')
                logger.info(f"CoreUtils (sanitize): Falling back to extracted and normalized root '{root_str_norm}' for '{original_label}'.")
                try: 
                    cs_root_check = harmony.ChordSymbol(root_str_norm)
                    if cs_root_check.root(): return root_str_norm 
                except: pass
            logger.warning(f"CoreUtils (sanitize): Could not reliably extract root for '{original_label}'. Returning None (Rest).")
            return None
        
        final_figure = cs_test.figure 
        logger.info(f"CoreUtils (sanitize): Successfully validated '{sanitized}' (from '{original_label}') with music21. Returning figure: '{final_figure}'")
        return final_figure
    except Exception as e_final_parse:
        logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') FAILED music21 parsing ({type(e_final_parse).__name__}: {e_final_parse}). Attempting root extraction from original.")
        root_match_orig = _ROOT_RE_STRICT.match(original_label.strip())
        if not root_match_orig: root_match_orig = _ROOT_RE_SIMPLE.match(original_label.strip())
        if root_match_orig:
            root_str = root_match_orig.group(0)
            root_str_norm = root_str[0].upper() + root_str[1:].replace('b','-').replace('bb','--')
            logger.info(f"CoreUtils (sanitize): Falling back to extracted and normalized root '{root_str_norm}' for '{original_label}' after parse fail.")
            try:
                cs_root_check = harmony.ChordSymbol(root_str_norm)
                if cs_root_check.root(): return root_str_norm
            except: pass
        logger.warning(f"CoreUtils (sanitize): Could not extract root from '{original_label}' after parse fail. Returning None (Rest).")
        return None

def get_music21_chord_object(chord_label_str: Optional[str]) -> Optional[harmony.ChordSymbol]:
    final_label_for_m21 = sanitize_chord_label(chord_label_str) 
    if not final_label_for_m21:
        return None 
    try:
        cs = harmony.ChordSymbol(final_label_for_m21) 
        if not cs.pitches or not cs.root():
            logger.warning(f"CoreUtils (get_obj): ChordSymbol for '{final_label_for_m21}' (orig: '{chord_label_str}') created but no pitches/root. Returning None.")
            return None
        logger.info(f"CoreUtils (get_obj): Successfully created ChordSymbol '{cs.figure}' (orig: '{chord_label_str}', sanitized to '{final_label_for_m21}')")
        return cs
    except Exception as e:
        logger.error(f"CoreUtils (get_obj): Exception creating ChordSymbol for '{final_label_for_m21}' (orig: '{chord_label_str}'): {e}. Returning None.", exc_info=True)
        return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    
    # o3さんの最新提案に合わせた期待値とテストケース
    test_cases = {
        # o3さん提案の期待値 (jsonのnullはPythonのNoneとしてテスト)
        "Am(add9)": "Am9",       
        None: None, 
        "Rest": None,            
        "C7(b9,#13)": "C7b9#13", 
        "Bbmaj9#11": "B-9#11",   
        "Ebmaj7(#11)": "E-maj7#11",
        "C7#9b13": "C7#9b13",
        "Gsus2/D": "Gsus2/D",
        "Cadd9": "Cadd9",
        "Am7add11": "Am7add11",
        "G13": "G13",
        "Bo7": "Bdim7", 
        "E7b9": "E7b9",
        "Fmaj7add9": "Fmaj7add9",
        "C/E": "C/E",
        "Gm7b5": "Gm7b5",
        "Dm7add13": "Dm7add13",
        "Em7b5": "Em7b5",
        "A7b9": "A7b9",
        "C13": "C13",
        "C/Bb": "C/B-",
        "D7sus4": "D7sus4",
        "Fmaj7add9add13": "Fmaj7add9add13",
        "Ebmaj7(#11)": "E-maj7#11", 
        "Bbmaj7/D": "B-maj7/D",
        "C (add9)": "Cadd9", 
    }
    
    additional_tests = ["NC", "C", "Cm", "C7", "Cmaj7", "Cdim", "Caug", "Csus4", "Csus2", "Calt", "Cmajor", "Cminor"]
    all_labels_to_test = sorted(list(set(list(test_cases.keys()) + additional_tests)))

    print("\n--- Running sanitize_chord_label Test Cases (役割特化版ベース + o3さん最新方針適用・改) ---")
    s_parses = 0; f_parses = 0; r_count = 0; exp_match = 0; exp_mismatch = 0

    for label_orig in all_labels_to_test:
        expected_figure = test_cases.get(label_orig)
        sanitized_figure_from_func = sanitize_chord_label(label_orig) 
        eval_str = ""
        if expected_figure is None: 
            if sanitized_figure_from_func is None: eval_str = "✔ (OK, Interpreted as Rest)"; exp_match +=1
            else: eval_str = f"✘ (Exp Figure: None, Got Figure: '{sanitized_figure_from_func}')"; exp_mismatch +=1
        elif sanitized_figure_from_func == expected_figure:
            eval_str = "✔ (OK, Expected Figure)"; exp_match +=1
        else: 
            eval_str = f"✘ (Exp Figure: '{expected_figure}', Got Figure: '{sanitized_figure_from_func}')"; exp_mismatch +=1
        
        print(f"Original: '{str(label_orig):<25}' -> Sanitized to Figure: '{str(sanitized_figure_from_func):<30}' {eval_str}")

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
            print(f"  └─> music21 FAILED or NO PITCHES for sanitized '{sanitized_figure_from_func}' (from original '{label_orig}')")
            f_parses += 1

    print(f"\n--- Test Summary (役割特化版ベース + o3さん最新方針適用・改) ---")
    total_labels = len(all_labels_to_test)
    attempted_to_parse = total_labels - r_count
    print(f"Total unique labels processed: {total_labels}")
    if exp_match + exp_mismatch > 0:
      print(f"Matches with expected figure outcome (incl. Rest as None): {exp_match}")
      print(f"Mismatches with expected figure outcome: {exp_mismatch}")
    print(f"Successfully parsed by music21 (Chord obj with pitches & root): {s_parses} / {attempted_to_parse} non-Rest attempts")
    print(f"Failed to parse by music21 (or no pitches/root) after sanitization: {f_parses}")
    print(f"Interpreted as 'Rest' (sanitize_chord_label returned None): {r_count}")
    functional_success_count = s_parses + r_count
    overall_success_rate = (functional_success_count / total_labels * 100) if total_labels > 0 else 0
    print(f"Estimated overall functional success (parsed by music21 + correctly identified as Rest): {overall_success_rate:.2f}%")

# --- END OF FILE utilities/core_music_utils.py ---
