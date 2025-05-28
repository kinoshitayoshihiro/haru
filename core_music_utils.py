# --- START OF FILE utilities/core_music_utils.py (インデントエラーと自己参照インポート修正版) ---
import music21
from music21 import pitch, harmony, key, meter, stream, note, chord
import re
import logging
# typingモジュールからのインポートはここで行う
from typing import List, Dict, Optional, Any, Tuple, Union, cast, Sequence

logger = logging.getLogger(__name__)
_ROOT_RE_STRICT = re.compile(r'^([A-G](?:[#b]{1,2}|[ns])?)(?![#b])')
MIN_NOTE_DURATION_QL = 0.0625 # 64分音符程度を最小音価とする

def get_time_signature_object(ts_str: Optional[str]) -> Optional[meter.TimeSignature]:
    if not ts_str: return None
    try: return meter.TimeSignature(ts_str)
    except Exception: logger.error(f"CoreUtils: Invalid time signature string: {ts_str}"); return None

def get_key_signature_object(tonic: Optional[str], mode: Optional[str] = 'major') -> Optional[key.Key]:
    if not tonic: return None
    try: return key.Key(tonic, mode.lower() if mode else 'major')
    except Exception: logger.error(f"CoreUtils: Invalid key signature: {tonic} {mode}"); return None

def calculate_note_times(current_beat: float, duration_beats: float, bpm: float) -> Tuple[float, float]:
    start_time_seconds = (current_beat / bpm) * 60.0
    duration_seconds = (duration_beats / bpm) * 60.0
    end_time_seconds = start_time_seconds + duration_seconds
    return start_time_seconds, end_time_seconds

def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
    """
    入力されたコードラベルを music21 が解釈しやすい形式に近づける。
    - 全角英数を半角に
    - 不要な空白削除
    - ルート音のフラットを'-'に (例: Bb -> B-)
    - テンションのフラット 'b' はそのまま保持
    - '△'や'M'を'maj'に
    - 'ø'や'Φ'を'm7b5'に (ハーフディミニッシュ)
    - 'NC', 'N.C.', 'Rest' などは "Rest" に統一
    - 括弧やカンマは削除 (music21は非対応)
    """
    if label is None or not str(label).strip():
        logger.debug(f"CoreUtils (sanitize): Empty or None label received, returning 'Rest'.")
        return "Rest"

    original_label = str(label)
    s = original_label.strip()

    # 全角を半角に
    s = s.translate(str.maketrans('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ＃♭＋－／．（）０１２３４５６７８9',
                                  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#b+-/.()0123456789'))
    s = s.replace(' ', '') # 空白除去

    # No Chord / Rest 系の統一
    if s.upper() in ['NC', 'N.C.', 'NOCHORD', 'SILENCE', '-', 'REST']:
        logger.debug(f"CoreUtils (sanitize): Label '{original_label}' identified as Rest.")
        return "Rest"

    # ルート音のフラット記号の正規化 (例: Bb -> B-)
    # A-G の直後の 'b' のみを '-' に置換する。
    # ただし、その後に数字が続く場合はテンションの可能性があるため、ここでは単純な置換は避ける。
    # より安全なアプローチ: まずルート音とそれ以外を分離しようと試みる
    root_match = re.match(r"([A-G])([#b-]?)", s)
    if root_match:
        root_note_str = root_match.group(1)
        accidental_str = root_match.group(2)
        remaining_part_str = s[len(root_match.group(0)):]

        if accidental_str == 'b':
            accidental_str = '-'
        
        # テンションやadd/omit部分の 'b' はそのままにするため、remaining_part_str は変更しない
        s = root_note_str + accidental_str + remaining_part_str
    else:
        # ルート音すらマッチしない場合は、予期せぬ形式の可能性が高い
        logger.warning(f"CoreUtils (sanitize): Could not match a valid root note in '{s}' (from '{original_label}').")
        # この時点でエラーとして None を返すか、あるいはさらに処理を試みるか
        # ここでは、後続の処理に任せるが、最終的に music21 がパースできなければ None になる

    # 品質に関するエイリアス変換
    s = s.replace('△', 'maj').replace('M', 'maj') 
    s = s.replace('ø', 'm7b5').replace('Φ', 'm7b5') 
    s = s.replace('aug', '+') 
    s = s.replace('diminished', 'dim').replace('°', 'dim')

    # 括弧とカンマの除去
    s = s.replace('(', '').replace(')', '').replace(',', '')
    
    # 'power' は music21 が解釈できる
    # 'sus' は music21 が解釈できる (sus2, sus4)

    # 最終チェック: music21でパース試行
    try:
        cs_test = harmony.ChordSymbol(s)
        # music21が解釈できても、ルート音が取れない場合がある (例: "major" だけなど)
        if cs_test.root():
            logger.debug(f"CoreUtils (sanitize): Original='{original_label}', SanitizedTo='{s}', ParsedRoot='{cs_test.root().nameWithOctave}'")
            return s
        else:
            logger.warning(f"CoreUtils (sanitize): Sanitized form '{s}' (from '{original_label}') parsed by music21 but NO ROOT. Treating as potentially invalid.")
            return None 
    except Exception as e_parse:
        logger.warning(f"CoreUtils (sanitize): Final form '{s}' (from '{original_label}') FAILED music21 parsing ({type(e_parse).__name__}: {e_parse}). Returning None.")
        return None

# --- END OF FILE utilities/core_music_utils.py ---
