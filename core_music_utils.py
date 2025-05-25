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
    if scl_cls is scale.MajorScale and mode_key not in mode_map:
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

    # 0a. capitalize root
    sanitized = re.sub(r'^([a-g])', lambda m: m.group(1).upper(), sanitized)
    # 0b. word-based quality conversions
    word_map = {
        r'(?i)\b([A-G][#\-]*)\s+minor\b': r'\1m', r'(?i)\b([A-G][#\-]*)\s+major\b': r'\1maj',
        r'(?i)\b([A-G][#\-]*)\s+dim\b':   r'\1dim', r'(?i)\b([A-G][#\-]*)\s+aug\b':   r'\1aug',
    }
    for pat, rep in word_map.items(): sanitized = re.sub(pat, rep, sanitized)

    # 1. flat & sus normalization
    sanitized = re.sub(r'^([A-G])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-G])b(?![#b])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-G])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-G])b(?![#b])', r'/\1-', sanitized)
    sanitized = re.sub(r'(?i)([A-G][#\-]?(?:\d+)?)(sus)(?![24\d])', r'\g<1>sus4', sanitized)
    sanitized = re.sub(r'(?i)(sus)([24])', r'sus\2', sanitized)

    # 2. fix unbalanced parens
    if '(' in sanitized and ')' not in sanitized:
        base_part, content = sanitized.split('(',1)
        recovered = "".join(_expand_tension_block_final_v3(p) for p in content.split(','))
        sanitized = base_part + (recovered or '')
        logger.info(f"CoreUtils (sanitize): Recovered from unclosed -> '{sanitized}'")

    # 3. alt expansion: include both #9 and b13 correctly
    sanitized = re.sub(r'([A-Ga-g][#\-]?)(?:7)?alt', r'\g<1>7#9b13', sanitized, flags=re.IGNORECASE)

    # correct erroneous 'badd13' patterns to 'b13add13'
    sanitized = sanitized.replace('badd13', 'b13add13')

    # 4. flatten parens
    prev = ""; count = 0
    while '(' in sanitized and ')' in sanitized and sanitized != prev and count < 5:
        prev = sanitized; count += 1
        m = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if m:
            base, inner, suf = m.groups()
            expanded = "".join(_expand_tension_block_final_v3(p) for p in inner.split(','))
            sanitized = base + expanded + suf
        else: break

    # 5. quality mapping
    qual_map = {
        r'(?i)ø7?\b': 'm7b5', r'(?i)half[- ]?dim\b': 'm7b5', 'dimished': 'dim',
        r'(?i)diminished(?!7)': 'dim', r'(?i)diminished7': 'dim7', r'(?i)domant7?': '7',
        r'(?i)dominant7?\b': '7', r'(?i)major7': 'maj7', r'(?i)major9': 'maj9',
        r'(?i)major13': 'maj13', r'(?i)minor7': 'm7', r'(?i)minor9': 'm9',
        r'(?i)minor11': 'm11', r'(?i)minor13': 'm13', r'(?i)min(?!or\b|\.|m7b5)': 'm',
        r'(?i)aug(?!mented)': 'aug', r'(?i)augmented': 'aug', r'(?i)major(?!7|9|13|\b)': 'maj'
    }
    for pat, rep in qual_map.items(): sanitized = re.sub(pat, rep, sanitized)

    # 6. addify two-digit tensions
    try:
        sanitized = re.sub(
            r'([A-Ga-z][#\-]?(?:[mM](?:aj)?\d*|[dD]im\d*|[aA]ug\d*|ø\d*|[sS]us\d*|[aA]dd\d*|7th|6th|5th|m7b5)?)(\d{2,})(?!add|\d|th|nd|rd|st)',
            _addify_if_needed_final_v3, sanitized, flags=re.IGNORECASE)
    except Exception as e:
        logger.warning(f"CoreUtils (sanitize): _addify error: {e}. Label: {sanitized}")

    # 7. handle maj9 followed by alterations
    sanitized = re.sub(r'(maj9)(#\d+)', r'\1\2add9', sanitized, flags=re.IGNORECASE)

    # 8. final sus cleanup
    sanitized = re.sub(r'(?i)sus44$', 'sus4', sanitized)
    sanitized = re.sub(r'(?i)sus22$', 'sus2', sanitized)
    sanitized = re.sub(r'(add\d+)*add\d+', r'add\g<1>', sanitized, flags=re.IGNORECASE)

    # 9 & 10. strip spaces, commas, trailing junk
    sanitized = re.sub(r'[,\s]', '', sanitized)
    sanitized = re.sub(r'[^a-zA-Z0-9#\-/\u00f8]+$', '', sanitized)

    if not sanitized:
        logger.info(f"CoreUtils (sanitize): '{original_label}' -> empty -> Rest")
        return None
    if sanitized != original_label:
        logger.info(f"CoreUtils (sanitize): '{original_label}' -> '{sanitized}'")

    # 11. final parse test
    try:
        cs_test = harmony.ChordSymbol(sanitized)
        if not cs_test.pitches:
            logger.warning(f"CoreUtils (sanitize): '{sanitized}' has no pitches -> Rest")
            return None
    except Exception as e:
        logger.warning(f"CoreUtils (sanitize): Could not parse '{sanitized}': {e} -> Rest")
        return None
    if not re.match(r'^[A-G]', sanitized):
        logger.warning(f"CoreUtils (sanitize): '{sanitized}' invalid root -> Rest")
        return None
    return sanitized


def get_music21_chord_object(chord_label_str: Optional[str], current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    if not isinstance(chord_label_str, str) or not chord_label_str.strip():
        return None
    sanitized_label = sanitize_chord_label(chord_label_str)
    if not sanitized_label:
        return None
    try:
        cs = harmony.ChordSymbol(sanitized_label)
        if not cs.pitches:
            return None
        return cs
    except:
        return None
