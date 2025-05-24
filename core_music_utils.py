# --- START OF FILE utilities/core_music_utils.py (役割特化・修正版) ---
import logging
import re
from typing import Optional, Dict, Any, List

# music21 のサブモジュールを個別にインポート
from music21 import meter, harmony, pitch
from music21 import chord as m21chord   # 統一エイリアス

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125  # 音楽的意味を持つ最小音価


# ╭──────────────────────────────────────────────────────────╮
# │  基本ユーティリティ                                     │
# ╰──────────────────────────────────────────────────────────╯
def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    ts_str = ts_str or "4/4"
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning(f"CoreUtils: Invalid TimeSignature '{ts_str}'. 4/4 にフォールバックします。")
        return meter.TimeSignature("4/4")
    except Exception as e:
        logger.error(f"CoreUtils: TimeSignature 生成時に想定外エラー: {e}. 4/4 にフォールバック。", exc_info=True)
        return meter.TimeSignature("4/4")


# tension “(#9,b13)” などを Music21 が受け入れる形へ
def _convert_parenthesized_tensions(label: str) -> str:
    """
    C7(#9,b13)  →  C7#9b13
    C7(b9,#11) →  C7addb9#11
    （ベース部+数字）以降に丸かっこのみが付いているケースだけを対象にする。
    """
    m = re.match(r'^([A-G][#\-]?[A-Za-z0-9]*)\s*\(([^)]+)\)$', label)
    if not m:
        return label
    base, tension_block = m.groups()
    out_parts: List[str] = []
    for t in tension_block.split(','):
        t = t.strip()
        if not t:
            continue
        # b9 → addb9, #9 → #9 など
        if t.lower().startswith('b') and t[1:].isdigit():
            out_parts.append(f'add{t}')
        else:
            out_parts.append(t)
    return base + ''.join(out_parts)


# tension ブロック展開用ヘルパ
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
    if seg in {"omit3", "omit5", "omitroot"}:
        return seg
    logger.debug(f"CoreUtils: 未知のテンション '{seg}' はそのまま保持。")
    return seg


def _addify_if_needed_core(match: re.Match) -> str:
    prefix = match.group(1) or ""
    number = match.group(2)
    if prefix.lower().endswith(
        ('sus', 'add', 'maj', 'm', 'dim', 'aug', 'b5', 'ø', '7', '9', '11', '13')
    ):
        # 後ろに数字が無い場合のみ add を付与
        if not prefix or not prefix[-1].isdigit():
            return f'{prefix}add{number}'
    return match.group(0)


# ╭──────────────────────────────────────────────────────────╮
# │  メイン：ラベル正規化                                   │
# ╰──────────────────────────────────────────────────────────╯
def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    if not label or not isinstance(label, str):
        logger.debug("CoreUtils (sanitize): ラベルが空 or 文字列ではない -> Rest 扱い")
        return None

    original_label = label
    sanitized = label.strip()

    # Rest キーワード
    if sanitized.lower() in {"rest", "r", "nc", "n.c.", "silence", "-"}:
        return None

    # まず (テンション) → サフィックス変換を試みる
    sanitized = _convert_parenthesized_tensions(sanitized)

    # major / minor など英単語の短縮
    word_map = {
        r'(?i)\b([A-G][#\-]*)\s+minor\b': r'\1m',
        r'(?i)\b([A-G][#\-]*)\s+major\b': r'\1maj',
        r'(?i)\b([A-G][#\-]*)\s+dim\b':   r'\1dim',
        r'(?i)\b([A-G][#\-]*)\s+aug\b':   r'\1aug',
    }
    for pat, repl in word_map.items():
        sanitized = re.sub(pat, repl, sanitized)

    # 頭文字を大文字に
    sanitized = re.sub(r'^([a-g])', lambda m: m.group(1).upper(), sanitized)

    # ♭♭/♭ の置換（bb→--, b→-）
    sanitized = re.sub(r'^([A-G])bb', r'\1--', sanitized)
    sanitized = re.sub(r'^([A-G])b(?![#b])', r'\1-', sanitized)
    sanitized = re.sub(r'/([A-G])bb', r'/\1--', sanitized)
    sanitized = re.sub(r'/([A-G])b(?![#b])', r'/\1-', sanitized)

    # sus の正規化
    sanitized = re.sub(r'(?i)([A-G][#\-]?(?:\d+)?)(sus)(?![24\d])', r'\1sus4', sanitized)
    sanitized = re.sub(r'(?i)(sus)([24])', r'sus\2', sanitized)
    sanitized = re.sub(r'(?i)(?<!\d)(sus)(?![24])', 'sus4', sanitized)
    sanitized = re.sub(r'sus([24])\1$', r'sus\1', sanitized, flags=re.I)

    # 7alt → 7#9b13 置換
    sanitized = re.sub(r'([A-G][#\-]?)(?:7)?alt', r'\17#9b13', sanitized, flags=re.I)

    # “badd13” → “b13” など冗長表現削除
    sanitized = sanitized.replace('badd13', 'b13').replace('#add13', '#13')

    # ( ... ) ブロックがまだあれば再展開
    for _ in range(3):
        m = re.match(r'^(.*?)\(([^)]+)\)(.*)$', sanitized)
        if not m:
            break
        base, inner, suf = m.groups()
        inner_expanded = ''.join(_expand_tension_block_core(p) for p in inner.split(','))
        sanitized = base + inner_expanded + suf

    # 各種名称の正規化
    qual_map = {
        r'(?i)ø7?\b': 'm7b5',
        r'(?i)half[- ]?dim\b': 'm7b5',
        r'(?i)diminished(?!7)': 'dim',
        r'(?i)diminished7': 'dim7',
        r'(?i)dominant7?\b': '7',
        r'(?i)major7': 'maj7',
        r'(?i)major9': 'maj9',
        r'(?i)major13': 'maj13',
        r'(?i)minor7': 'm7',
        r'(?i)minor9': 'm9',
        r'(?i)minor11': 'm11',
        r'(?i)minor13': 'm13',
        r'(?i)min(?!or\b|\.|m7b5)': 'm',
        r'(?i)aug(?!mented)': 'aug',
        r'(?i)augmented': 'aug',
        r'(?i)major(?!7|9|13|\b)': 'maj',
    }
    for pat, repl in qual_map.items():
        sanitized = re.sub(pat, repl, sanitized)

    # “m79” → “m7add9” のような add の付与
    sanitized = re.sub(
        r'([A-G][#\-]?(?:m(?:aj)?\d*|maj\d*|dim\d*|aug\d*|ø\d*|sus\d*|add\d*|7th|6th|5th|m7b5)?)([1-9]\d)'
        r'(?!add|\d|th|nd|rd|st)',
        _addify_if_needed_core,
        sanitized,
        flags=re.I,
    )

    # 重複 add の削除
    sanitized = re.sub(r'addadd', 'add', sanitized, flags=re.I)
    sanitized = re.sub(r'(add\d+)(?=.*\1)', '', sanitized, flags=re.I)

    # カンマ・空白除去 / 末尾不要記号削除
    sanitized = re.sub(r'[,\s]', '', sanitized)
    sanitized = re.sub(r'[^A-Za-z0-9#\-/\u00f8]+$', '', sanitized)

    if not sanitized:
        logger.info(f"CoreUtils: '{original_label}' → 空文字。Rest 扱い。")
        return None

    if sanitized != original_label:
        logger.info(f"CoreUtils: '{original_label}' → '{sanitized}'")
    else:
        logger.debug(f"CoreUtils: '{original_label}' 変更なし。")

    # Music21 で妥当性検査
    try:
        if not harmony.ChordSymbol(sanitized).pitches:
            logger.warning(f"CoreUtils: '{sanitized}' は pitch を持たず Rest 扱い。")
            return None
    except Exception as e:
        logger.warning(f"CoreUtils: '{sanitized}' を解析できず ({e})。Rest 扱い。")
        return None

    return sanitized


# ╭──────────────────────────────────────────────────────────╮
# │  便利ラッパー                                           │
# ╰──────────────────────────────────────────────────────────╯
def get_music21_chord_object(chord_label_str: Optional[str]) -> Optional[harmony.ChordSymbol]:
    sanitized_label = sanitize_chord_label(chord_label_str)
    if not sanitized_label:
        return None
    try:
        obj = harmony.ChordSymbol(sanitized_label)
        return obj if obj.pitches else None
    except Exception as e:
        logger.error(f"CoreUtils: ChordSymbol 生成失敗 '{sanitized_label}' ({e})")
        return None


# --- END OF FILE utilities/core_music_utils.py ---
