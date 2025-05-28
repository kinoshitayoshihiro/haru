# --- START OF FILE utilities/core_music_utils.py (sanitize_chord_label修正版) ---
import music21
from music21 import pitch, harmony, key, meter, stream, note, chord # chordを追加
import re
import logging

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL = 0.0625 # 64分音符程度を最小音価とする

# (他の関数 ... get_time_signature_object, get_key_signature_object, calculate_note_times は変更なし)
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
    - '△'や'M'を'maj'に
    - 'ø'や'Φ'を'm7b5'に (ハーフディミニッシュ)
    - 'NC', 'N.C.', 'Rest' などは "Rest" に統一
    - 括弧やカンマは削除 (music21は非対応)
    - テンションのフラット 'b' はそのまま保持 (music21がb表記を解釈するため)
    """
    if label is None or not str(label).strip():
        return "Rest" # 空やNoneはRest扱い

    original_label = str(label)
    s = original_label.strip()

    # 全角を半角に (簡易版、より包括的なライブラリ使用も検討可)
    s = s.translate(str.maketrans('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ＃♭＋－／．（）０１２３４５６７８9',
                                  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#b+-/.()0123456789'))
    s = s.replace(' ', '') # 空白除去

    # No Chord / Rest 系の統一
    if s.upper() in ['NC', 'N.C.', 'NOCHORD', 'SILENCE', '-', 'REST']:
        return "Rest"

    # ルート音のフラット記号の正規化 (例: Bb -> B-)
    # A-G の直後の 'b' のみを '-' に置換する
    s = re.sub(r'([A-G])b', r'\1-', s)

    # 品質に関するエイリアス変換
    s = s.replace('△', 'maj').replace('M', 'maj') # M7はmaj7になる
    s = s.replace('ø', 'm7b5').replace('Φ', 'm7b5') # ハーフディミニッシュ
    s = s.replace('aug', '+') # augを+に
    s = s.replace('diminished', 'dim').replace('°', 'dim') # diminished, ° を dim に

    # 括弧とカンマの除去
    s = s.replace('(', '').replace(')', '').replace(',', '')

    # 'omit'の前の数字がない場合 (例: Comit -> Comit3) はmusic21がエラーを出すことがあるので、
    # 基本的にはomitXの形を期待するが、ここでは何もしない (music21のパーサーに委ねる)

    # 'power' は music21 が解釈できる
    # 'sus' は music21 が解釈できる (sus2, sus4)

    # 最終チェック: music21でパース試行 (ルート音抽出のため)
    try:
        # ここでのChordSymbolはあくまでルート音抽出と簡易的な検証のため
        # 厳密なパースは呼び出し元で行う
        cs_test = harmony.ChordSymbol(s)
        if cs_test.root(): # ルート音が取れればOKとする
            logger.debug(f"CoreUtils (sanitize): Original='{original_label}', Sanitized='{s}', ParsedRoot='{cs_test.root().name}'")
            return s
        else: # ルート音が取れない場合は、元のラベルからルート音だけを抽出試行
            logger.warning(f"CoreUtils (sanitize): Sanitized form '{s}' (from '{original_label}') parsed by music21 but no root. Attempting root extraction from original.")
            match_root = re.match(r"([A-G][#-]?)", original_label.strip())
            if match_root:
                extracted_root = match_root.group(1).replace('b', '-')
                logger.info(f"CoreUtils (sanitize): Extracted root '{extracted_root}' from '{original_label}' as fallback.")
                return extracted_root # ルート音だけでも返す
            return None # どうしてもダメならNone
    except Exception as e_parse:
        # music21がパースできない場合、元のラベルからルート音だけを抽出試行
        logger.warning(f"CoreUtils (sanitize): Final form '{s}' (from '{original_label}') FAILED music21 parsing ({e_parse}). Attempting root extraction from original.")
        match_root = re.match(r"([A-G][#-]?)", original_label.strip())
        if match_root:
            extracted_root = match_root.group(1).replace('b', '-') # ここでもフラットはハイフンに
            logger.info(f"CoreUtils (sanitize): Extracted root '{extracted_root}' from '{original_label}' as fallback after parse failure.")
            return extracted_root # ルート音だけでも返す
        logger.error(f"CoreUtils (sanitize): Could not extract root from '{original_label}' after sanitization and parse failure.")
        return None

# --- END OF FILE utilities/core_music_utils.py ---
