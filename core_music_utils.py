# --- START OF FILE utilities/core_music_utils.py (役割特化版) ---
import logging
import re
from typing import Optional, Dict, Any, List

# music21 のサブモジュールを個別にインポート
from music21 import meter
from music21 import harmony
from music21 import pitch
from music21 import chord as m21chord  # エイリアスを m21chord に統一

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125  # 音楽的意味を持つ最小の音価

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    ts_str = ts_str or "4/4"
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning(f"CoreUtils: Invalid TimeSignature '{ts_str}'. Defaulting to 4/4.")
        return meter.TimeSignature("4/4")
    except Exception as e_ts:
        logger.error(f"CoreUtils: Error creating TimeSignature '{ts_str}': {e_ts}. Defaulting to 4/4.", exc_info=True)
        return meter.TimeSignature("4/4")

def _expand_tension_block_core(seg: str) -> str:
    seg = seg.strip().lower()
    if not seg:
        return ""
    if seg.startswith(("#", "b")):
        return seg
    if seg.startswith("add"):
        m = re.match(r'add(\d+)', seg)
        return f"add{m.group(1)}" if m else ""
    if seg.isdigit():
        return f"add{seg}"
    if seg in ["omit3", "omit5", "omitroot"]:
        return seg
    logger.debug(f"CoreUtils (_expand): Unknown tension '{seg}', passing as is.")
    return seg

def _addify_if_needed_core(match: re.Match) -> str:
    prefix, number = match.group(1), match.group(2)
    if prefix and re.search(r'(sus|add|maj|m|dim|aug|b5|ø|7|9|11|13)$', prefix, re.IGNORECASE):
        # すでに接頭辞に数字系があればそのまま
        return match.group(0)
    return f"{prefix}add{number}"

def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    if not label or not isinstance(label, str):
        logger.debug(f"CoreUtils (sanitize): Label '{label}' invalid → Rest.")
        return None

    original = label.strip()
    if not original or original.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        logger.debug(f"CoreUtils (sanitize): '{original}' → Rest.")
        return None

    s = original

    # major/minor/dim/aug の略記
    word_map = {
        r'(?i)\b([A-G][#\-]*)\s+minor\b': r'\1m',
        r'(?i)\b([A-G][#\-]*)\s+major\b': r'\1maj',
        r'(?i)\b([A-G][#\-]*)\s+dim\b':   r'\1dim',
        r'(?i)\b([A-G][#\-]*)\s+aug\b':   r'\1aug',
    }
    for pat, rep in word_map.items():
        s = re.sub(pat, rep, s)

    # 先頭小文字→大文字
    s = re.sub(r'^([a-g])', lambda m: m.group(1).upper(), s)

    # フラット記号・ダブルフラット
    s = re.sub(r'^([A-G])bb', r'\1--', s)
    s = re.sub(r'^([A-G])b(?![#b])', r'\1-', s)
    s = re.sub(r'/([A-G])bb', r'/\1--', s)
    s = re.sub(r'/([A-G])b(?![#b])', r'/\1-', s)

    # sus の正規化
    s = re.sub(r'(?i)([A-G][#\-]?(?:\d+)?)(sus)(?![24\d])', r'\1sus4', s)
    s = re.sub(r'(?i)(sus)([24])', r'sus\2', s)
    s = re.sub(r'(?i)(?<!\d)(sus)(?![24])', 'sus4', s)
    s = re.sub(r'sus([24])\1$', r'sus\1', s, flags=re.I)

    # ──────────── 丸括弧付きテンションの変換 ────────────
    # 例: C7(#9,b13) → C7#9b13
    def _paren_to_suffix(m: re.Match) -> str:
        base, tensions = m.group(1), m.group(2)
        parts: List[str] = []
        for t in tensions.split(','):
            t = t.strip()
            # b9 は addb9、その他はそのまま
            if t.lower().startswith('b') and t[1:].isdigit():
                parts.append(f"add{t}")
            else:
                parts.append(t)
        return base + "".join(parts)

    s = re.sub(
        r'^([A-G][#\-]?\d*)(?:\(([^)]+)\))$',
        _paren_to_suffix,
        s
    )
    # ──────────── ここまで ────────────

    # alt/dominant/major7… などのマッピング
    qual_map = {
        r'(?i)ø7?\b': 'm7b5', r'(?i)half[- ]?dim\b': 'm7b5',
        r'(?i)diminished(?!7)': 'dim', r'(?i)diminished7': 'dim7',
        r'(?i)dominant7?\b': '7', r'(?i)major7': 'maj7',
        r'(?i)major9': 'maj9', r'(?i)major13': 'maj13',
        r'(?i)minor7': 'm7', r'(?i)minor9': 'm9',
        r'(?i)minor11': 'm11', r'(?i)minor13': 'm13',
        r'(?i)min(?!or\b|\.|m7b5)': 'm',
        r'(?i)aug(?!mented)': 'aug', r'(?i)augmented': 'aug',
    }
    for pat, rep in qual_map.items():
        s = re.sub(pat, rep, s)

    # 数字が続く場合 addify
    try:
        s = re.sub(
            r'([A-G][#\-]?(?:m(?:aj)?\d*|maj\d*|dim\d*|aug\d*|ø\d*|sus\d*|add\d*|7th|6th|5th|m7b5)?)([1-9]\d)',
            _addify_if_needed_core,
            s,
            flags=re.IGNORECASE
        )
    except Exception as e_add:
        logger.warning(f"CoreUtils (sanitize): _addify error for '{s}': {e_add}")

    # 重複する add を削除
    s = re.sub(r'addadd', 'add', s, flags=re.I)
    s = re.sub(r'(add\d+)(?=.*\1)', '', s, flags=re.I)

    # 空白・カンマ削除、末尾不要文字カット
    s = re.sub(r'[,\s]', '', s)
    s = re.sub(r'[^A-Za-z0-9#/\\-]+$', '', s)

    if not s:
        logger.info(f"CoreUtils (sanitize): '{original}' → empty → Rest.")
        return None

    if s != original:
        logger.info(f"CoreUtils (sanitize): '{original}' → '{s}'")
    else:
        logger.debug(f"CoreUtils (sanitize): '{original}' unchanged.")

    # 最後に Music21 でパース確認
    try:
        cs = harmony.ChordSymbol(s)
        if not cs.pitches:
            logger.warning(f"CoreUtils (sanitize): '{s}' parsed OK but no pitches → Rest.")
            return None
    except Exception as e_h:
        logger.warning(f"CoreUtils (sanitize): Could not parse '{s}' ({e_h}) → Rest.")
        return None

    return s

def get_music21_chord_object(chord_label_str: Optional[str]) -> Optional[harmony.ChordSymbol]:
    sanitized = sanitize_chord_label(chord_label_str)
    if not sanitized:
        return None
    try:
        cs = harmony.ChordSymbol(sanitized)
        return cs if cs.pitches else None
    except Exception as e:
        logger.error(f"CoreUtils (get_obj): '{sanitized}' → Exception {e}.")
        return None

# --- END OF FILE utilities/core_music_utils.py ---
