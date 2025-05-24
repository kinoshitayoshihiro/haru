# --- START OF FILE utilities/core_music_utils.py (役割特化版) ---
# import music21 # 不要なため削除 (個別にインポートするため)
import logging
import re # re モジュールをインポート
from typing import Optional, Dict, Any, List

# music21 のサブモジュールを個別にインポート
from music21 import meter
from music21 import harmony
from music21 import pitch
from music21 import chord as m21chord # エイリアスを m21chord に統一

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125 # 音楽的意味を持つ最小の音価

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: # meter を使用
    ts_str = ts_str or "4/4"
    try:
        return meter.TimeSignature(ts_str) # meter を使用
    except meter.MeterException: # meter を使用
        logger.warning(f"CoreUtils: Invalid TimeSignature string '{ts_str}'. Defaulting to 4/4.")
        return meter.TimeSignature("4/4") # meter を使用
    except Exception as e_ts:
        logger.error(f"CoreUtils: Unexpected error creating TimeSignature from '{ts_str}': {e_ts}. Defaulting to 4/4.", exc_info=True)
        return meter.TimeSignature("4/4") # meter を使用

def _expand_tension_block_core(seg: str) -> str: 
    seg = seg.strip().lower()
    if not seg: return ""
    if seg.startswith(("#", "b")): return seg # Python 3.8以前では ("#", "b") のようにタプルにする
    if seg.startswith("add"):
        match_add_num = re.match(r'add(\d+)', seg)
        if match_add_num: return f"add{match_add_num.group(1)}"
        return "" 
    if seg.isdigit(): return f"add{seg}"
    if seg in ["omit3", "omit5", "omitroot"]: return seg
    logger.debug(f"CoreUtils (_expand_tension_block_core): Unknown tension '{seg}', passing as is.")
    return seg

def _addify_if_needed_core(match: re.Match) -> str: 
    prefix = match.group(1) or ""
    number = match.group(2)
    if prefix.lower().endswith(('sus', 'add', 'maj', 'm', 'dim', 'aug', 'b5', 'ø', '7', '9', '11', '13')):
        if not prefix or not prefix[-1].isdigit():
             return f'{prefix}add{number}'
        return match.group(0)
    return f'{prefix}add{number}'

def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    if not label or not isinstance(label, str):
        logger.debug(f"CoreUtils (sanitize): Label '{label}' is None or not a string. Returning None (Rest).")
        return None
    
    original_label = label
    sanitized = label.strip()

    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"CoreUtils (sanitize): Label '{original_label}' matches a Rest keyword. Returning None.")
        return None

    word_map = {
        r'(?i)\b([A-Ga-g][#\-]*)\s+minor\b': r'\1m', r'(?i)\b([A-Ga-g][#\-]*)\s+major\b': r'\1maj',
        r'(?i)\b([A-Ga-g][#\-]*)\s+dim\b':   r'\1dim', r'(?i)\b([A-Ga-g][#\-]*)\s+aug\b':   r'\1aug',
    }
    for pat, rep in word_map.items(): sanitized = re.sub(pat, rep, sanitized)
    sanitized = re.sub(r'^([a-g])', lambda m: m.group(1).upper(), sanitized) 

    sanitized = re.sub(r'^([A-G])bb', r'\1--', sanitized); sanitized = re.sub(r'^([A-G])b(?![#b])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-G])bb', r'/\1--', sanitized); sanitized = re.sub(r'/([A-G])b(?![#b])', r'/\1-', sanitized)
    
    sanitized = re.sub(r'(?i)([A-G][#\-]?(?:\d+)?)(sus)(?![24\d])', r'\g<1>sus4', sanitized)
    sanitized = re.sub(r'(?i)(sus)([24])', r'sus\2', sanitized)
    sanitized = re.sub(r'(?i)(?<!\d)(sus)(?![24])', 'sus4', sanitized) 
    sanitized = re.sub(r'sus([24])\1$', r'sus\1', sanitized, flags=re.I) 

    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt', r'\g<1>7#9b13', sanitized, flags=re.I)
    sanitized = sanitized.replace('badd13', 'b13').replace('#add13', '#13') 

    if '(' in sanitized and ')' not in sanitized:
        base_part, content_after = sanitized.split('(', 1) if '(' in sanitized else (sanitized, "")
        if content_after.strip():
            recovered = "".join(_expand_tension_block_core(p) for p in content_after.split(','))
            sanitized = base_part + recovered if recovered else base_part
        else: sanitized = base_part
    
    prev_sanitized = ""
    for _ in range(5): 
        if '(' not in sanitized or ')' not in sanitized or sanitized == prev_sanitized: break
        prev_sanitized = sanitized
        match = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if match:
            base, inner, suf = match.groups()
            expanded_inner = "".join(_expand_tension_block_core(p) for p in inner.split(','))
            sanitized = base + expanded_inner + suf
        else: break 

    qual_map = {r'(?i)ø7?\b': 'm7b5', r'(?i)half[- ]?dim\b': 'm7b5', 'dimished': 'dim',
                r'(?i)diminished(?!7)': 'dim', r'(?i)diminished7': 'dim7', 'domant7': '7',
                r'(?i)dominant7?\b': '7', r'(?i)major7': 'maj7', r'(?i)major9': 'maj9',
                r'(?i)major13': 'maj13', r'(?i)minor7': 'm7', r'(?i)minor9': 'm9',
                r'(?i)minor11': 'm11', r'(?i)minor13': 'm13', r'(?i)min(?!or\b|\.|m7b5)': 'm',
                r'(?i)aug(?!mented)': 'aug', r'(?i)augmented': 'aug', r'(?i)major(?!7|9|13|\b)': 'maj'}
    for pat, rep in qual_map.items(): sanitized = re.sub(pat, rep, sanitized)

    try:
        sanitized = re.sub(r'([A-Ga-g][#\-]?(?:m(?:aj)?\d*|maj\d*|dim\d*|aug\d*|ø\d*|sus\d*|add\d*|7th|6th|5th|m7b5)?)([1-9]\d)(?!add|\d|th|nd|rd|st)', _addify_if_needed_core, sanitized, flags=re.IGNORECASE)
    except Exception as e_addify: logger.warning(f"CoreUtils (sanitize): Error during _addify call: {e_addify}. Label: {sanitized}")

    sanitized = re.sub(r'(maj)9(#\d+)', r'\g<1>7\g<2>add9', sanitized, flags=re.IGNORECASE)
    
    sanitized = re.sub(r'addadd', 'add', sanitized, flags=re.I)
    sanitized = re.sub(r'(add\d+)(?=.*\1)', '', sanitized, flags=re.I) 

    sanitized = re.sub(r'[,\s]', '', sanitized)
    sanitized = re.sub(r'[^a-zA-Z0-9#\-/\u00f8]+$', '', sanitized) 

    if not sanitized: 
        logger.info(f"CoreUtils (sanitize): Label '{original_label}' resulted in empty string. Returning None (Rest).")
        return None

    if sanitized != original_label: logger.info(f"CoreUtils (sanitize): '{original_label}' -> '{sanitized}'")
    else: logger.debug(f"CoreUtils (sanitize): Label '{original_label}' no change.")

    try:
        cs_test = harmony.ChordSymbol(sanitized) # harmony を使用
        if not cs_test.pitches: 
            logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') parsed but has NO PITCHES. Fallback to None (Rest).")
            return None
    except Exception as e_final_parse:
        logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') could not be parsed by music21 ({type(e_final_parse).__name__}: {e_final_parse}). Fallback to None (Rest).")
        return None 

    if not re.match(r'^[A-G]', sanitized):
        logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' does not start with a note name. Fallback to None (Rest).")
        return None
        
    return sanitized

def get_music21_chord_object(chord_label_str: Optional[str]) -> Optional[harmony.ChordSymbol]: # harmony を使用
    sanitized_label = sanitize_chord_label(chord_label_str)
    if not sanitized_label:
        return None
    try:
        cs = harmony.ChordSymbol(sanitized_label) # harmony を使用
        if not cs.pitches:
            logger.info(f"CoreUtils (get_obj): Parsed '{sanitized_label}' but no pitches. Returning None.")
            return None
        return cs
    except Exception as e:
        logger.error(f"CoreUtils (get_obj): Exception for '{sanitized_label}': {e}. Returning None.")
    return None

# (if __name__ == '__main__': のテストコードはそのまま残してOK)
# ... (前回提示のテストコード) ...
# --- END OF FILE utilities/core_music_utils.py ---
