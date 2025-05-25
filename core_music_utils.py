import music21
import logging
from music21 import meter, harmony, pitch, scale
from typing import Optional, Dict, Any, List
import re

logger = logging.getLogger(__name__)
MIN_NOTE_DURATION_QL: float = 0.125


def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    ts_str = ts_str or "4/4"
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning(f"CoreUtils (GTSO): Invalid TS '{ts_str}'. Default 4/4.")
        return meter.TimeSignature("4/4")
    except Exception as e_ts:
        logger.error(f"CoreUtils (GTSO): Error for TS '{ts_str}': {e_ts}. Default 4/4.", exc_info=True)
        return meter.TimeSignature("4/4")


def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> scale.ConcreteScale:
    mode_key = (mode_str or "major").lower()
    tonic_val = tonic_str or "C"
    try:
        tonic_p = pitch.Pitch(tonic_val)
    except Exception:
        logger.error(f"CoreUtils (BuildScale): Invalid tonic '{tonic_val}'. Defaulting to C.")
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
        logger.warning(f"CoreUtils (BuildScale): Unknown mode '{mode_key}'. Using MajorScale with {tonic_p.name}.")
    try:
        return scl_cls(tonic_p)
    except Exception as e_create:
        logger.error(f"CoreUtils (BuildScale): Error creating '{scl_cls.__name__}' for {tonic_p.name}: {e_create}. Fallback C Major.", exc_info=True)
        return scale.MajorScale(pitch.Pitch("C"))


def _expand_tension_block_final_v3(seg: str) -> str:
    seg = seg.strip().lower()
    if not seg: return ""
    if seg.startswith(("#", "b")): return seg
    if seg.startswith("add"):
        match_add_num = re.match(r'add(\d+)', seg)
        if match_add_num: return f"add{match_add_num.group(1)}"
        logger.debug(f"CoreUtils (_ETB): Invalid 'add' format '{seg}', treating as empty.")
        return ""
    if seg.isdigit(): return f"add{seg}"
    if seg in ["omit3", "omit5", "omitroot"]: return seg
    logger.debug(f"CoreUtils (_ETB): Unknown tension '{seg}', passing as is.")
    return seg


def _addify_if_needed_final_v3(match: re.Match) -> str:
    prefix = match.group(1) or ""
    number = match.group(2)
    if prefix.lower().endswith(('sus', 'add', 'maj', 'm', 'dim', 'aug', 'b5', 'ø', '7', '9', '11', '13', '#', 'b')):
        return match.group(0)
    return f'{prefix}add{number}'


def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    if not label or not isinstance(label, str):
        logger.debug(f"CoreUtils (sanitize): Label '{label}' None/not str -> None (Rest)")
        return None 
    
    original_label = label
    sanitized = label.strip()

    if not sanitized or sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"CoreUtils (sanitize): '{original_label}' -> None (Rest direct match).")
        return None

    # 0a. ルート音の先頭文字を大文字化 (o3さん提案)
    sanitized = re.sub(r'^([a-g])', lambda m: m.group(1).upper(), sanitized)
    
    # 0b. ワードベースの品質変換
    word_map = {
        r'(?i)\b([A-G][#\-]*)\s+minor\b': r'\1m', r'(?i)\b([A-G][#\-]*)\s+major\b': r'\1maj',
        r'(?i)\b([A-G][#\-]*)\s+dim\b':   r'\1dim', r'(?i)\b([A-G][#\-]*)\s+aug\b':   r'\1aug',
    }
    for pat, rep in word_map.items(): sanitized = re.sub(pat, rep, sanitized)

    # 1. フラット正規化 & SUS正規化
    sanitized = re.sub(r'^([A-G])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-G])b(?![#b])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-G])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-G])b(?![#b])', r'/\1-', sanitized)
    sanitized = re.sub(r'(?i)([A-G][#\-]?(?:\d+)?)(sus)(?![24\d])', r'\g<1>sus4', sanitized)
    sanitized = re.sub(r'(?i)(sus)([24])', r'sus\2', sanitized)

    # 2. 括弧の不均衡修正
    if '(' in sanitized and ')' not in sanitized:
        logger.info(f"CoreUtils (sanitize): Detected unclosed parenthesis in '{original_label}'.")
        base_part = sanitized.split('(')[0]
        content_after = sanitized.split('(', 1)[1] if len(sanitized.split('(', 1)) > 1 else ""
        if content_after.strip():
            recovered = "".join(_expand_tension_block_final_v3(p) for p in content_after.split(','))
            if recovered:
                sanitized = base_part + recovered
                logger.info(f"CoreUtils (sanitize): Recovered from unclosed: '{recovered}' -> '{sanitized}'")
            else:
                sanitized = base_part; logger.info(f"CoreUtils (sanitize): No valid tensions from unclosed, kept -> '{sanitized}'")
        else:
            sanitized = base_part; logger.info(f"CoreUtils (sanitize): Empty after unclosed, kept -> '{sanitized}'")

    # 3. altコード展開
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt', r'\g<1>7#9b13', sanitized, flags=re.IGNORECASE)
    sanitized = sanitized.replace('badd13', 'b13').replace('#add13', '#13')

    # 4. 括弧の平坦化
    prev = ""; count = 0
    while '(' in sanitized and ')' in sanitized and sanitized != prev and count < 5:
        prev = sanitized; count += 1
        match = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if match:
            base, inner, suf = match.groups()
            expanded = "".join(_expand_tension_block_final_v3(p) for p in inner.split(','))
            sanitized = base + expanded + suf
        else:
            break

    # 5. 品質関連の正規化
    qual_map = {
        r'(?i)ø7?\b': 'm7b5', r'(?i)half[- ]?dim\b': 'm7b5', 'dimished': 'dim',
        r'(?i)diminished(?!7)': 'dim', r'(?i)diminished7': 'dim7', r'(?i)domant7?': '7',
        r'(?i)dominant7?\b': '7', r'(?i)major7': 'maj7', r'(?i)major9': 'maj9',
        r'(?i)major13': 'maj13', r'(?i)minor7': 'm7', r'(?i)minor9': 'm9',
        r'(?i)minor11': 'm11', r'(?i)minor13': 'm13', r'(?i)min(?!or\b|\.|m7b5)': 'm',
        r'(?i)aug(?!mented)': 'aug', r'(?i)augmented': 'aug', r'(?i)major(?!7|9|13|\b)': 'maj'
    }
    for pat, rep in qual_map.items(): sanitized = re.sub(pat, rep, sanitized)
                                                       
    # 6. 'add'補完
    try:
        sanitized = re.sub(r'([A-Ga-z][#\-]?(?:[mM](?:aj)?\d*|[dD]im\d*|[aA]ug\d*|ø\d*|[sS]us\d*|[aA]dd\d*|7th|6th|5th|m7b5)?)(\d{2,})(?!add|\d|th|nd|rd|st)', _addify_if_needed_final_v3, sanitized, flags=re.IGNORECASE)
    except Exception as e_addify:
        logger.warning(f"CoreUtils (sanitize): Error during _addify call: {e_addify}. Label: {sanitized}")

    # 7. maj9(#...) -> maj7(#...)add9
    sanitized = re.sub(r'(maj)9(#\d+)', r'\g<1>7\g<2>add9', sanitized, flags=re.IGNORECASE)

    # 8. susコードの最終修正
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized)
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)
    sanitized = re.sub(r'(add\d+)(\1)+', r'\1', sanitized, flags=re.IGNORECASE)

    # 9. 全体のスペース・カンマ除去
    sanitized = re.sub(r'[,\s]', '', sanitized)

    # 10. 不要末尾文字除去
    sanitized = re.sub(r'[^a-zA-Z0-9#\-/\u00f8]+$', '', sanitized)

    if not sanitized:
        logger.info(f"CoreUtils (sanitize): Label '{original_label}' resulted in empty string. Returning None (Rest).")
        return None

    if sanitized != original_label:
        logger.info(f"CoreUtils (sanitize): '{original_label}' -> '{sanitized}'")

    # 11. 最終パース試行
    try:
        cs_test = harmony.ChordSymbol(sanitized)
        if not cs_test.pitches:
            logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') parsed but has NO PITCHES. Fallback to None (Rest).")
            return None
    except Exception as e_final_parse:
        logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' (from '{original_label}') could not be parsed by music21 ({type(e_final_parse).__name__}: {e_final_parse}). Fallback to None (Rest).")
        return None

    if not re.match(r'^[A-G]', sanitized):
        logger.warning(f"CoreUtils (sanitize): Final form '{sanitized}' does not start with a valid note name. Fallback to None (Rest).")
        return None
        
    return sanitized


def get_music21_chord_object(chord_label_str: Optional[str], current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    if not isinstance(chord_label_str, str) or not chord_label_str.strip():
        logger.debug(f"CoreUtils (get_obj): Input '{chord_label_str}' empty/not str. As Rest (None).")
        return None
    sanitized_label = sanitize_chord_label(chord_label_str)
    if not sanitized_label:
        logger.debug(f"CoreUtils (get_obj): sanitize_chord_label returned None for '{chord_label_str}'. As Rest.")
        return None
    try:
        cs = harmony.ChordSymbol(sanitized_label)
        if not cs.pitches:
            logger.info(f"CoreUtils (get_obj): Parsed '{sanitized_label}' (orig:'{chord_label_str}') but no pitches (fig: {cs.figure}). As Rest (None).")
            return None
        logger.info(f"CoreUtils (get_obj): Successfully parsed '{sanitized_label}' (orig:'{chord_label_str}') as {cs.figure}")
        return cs
    except Exception as e:
        logger.error(f"CoreUtils (get_obj): Exception for '{sanitized_label}' (orig:'{chord_label_str}'): {type(e).__name__}: {e}. As Rest (None).")
    return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    # Test harness omitted for brevity
