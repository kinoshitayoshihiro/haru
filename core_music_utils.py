# --- START OF FILE generators/core_music_utils.py (修正案 2025-05-22 16:xx) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony
from typing import Optional, Dict, Any, Tuple, List
import re

logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL: float = 0.125

def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
    if not ts_str:
        ts_str = "4/4"
        logger.debug(f"get_time_signature_object: ts_str is None, defaulting to '4/4'.")
    try:
        return meter.TimeSignature(ts_str)
    except meter.MeterException:
        logger.warning(f"get_time_signature_object: Invalid TimeSignature string '{ts_str}'. Defaulting to 4/4.")
        return meter.TimeSignature("4/4")
    except Exception as e_ts:
        logger.error(f"get_time_signature_object: Unexpected error creating TimeSignature from '{ts_str}': {e_ts}. Defaulting to 4/4.", exc_info=True)
        return meter.TimeSignature("4/4")

def build_scale_object(mode_str: Optional[str], tonic_str: Optional[str]) -> Optional[scale.ConcreteScale]:
    effective_mode_str = mode_str if mode_str else "major"
    effective_tonic_str = tonic_str if tonic_str else "C"
    logger.debug(f"build_scale_object: Attempting scale for {effective_tonic_str} {effective_mode_str}")
    try:
        tonic_p = pitch.Pitch(effective_tonic_str)
    except Exception as e_tonic:
        logger.error(f"build_scale_object: Invalid tonic string '{effective_tonic_str}': {e_tonic}. Defaulting tonic to C.")
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
    scale_class = mode_map.get(effective_mode_str.lower())
    if scale_class:
        try:
            return scale_class(tonic_p)
        except Exception as e_create:
            logger.error(f"build_scale_object: Error creating scale '{scale_class.__name__}' "
                         f"with tonic '{tonic_p.nameWithOctave if tonic_p else 'N/A'}': {e_create}. Fallback C Major.", exc_info=True)
            return scale.MajorScale(pitch.Pitch("C"))
    else:
        logger.warning(f"build_scale_object: Mode '{effective_mode_str}' unknown for tonic '{tonic_p.nameWithOctave if tonic_p else 'N/A'}'. Defaulting to MajorScale.")
        return scale.MajorScale(tonic_p)

def sanitize_chord_label(label: str) -> str:
    if not isinstance(label, str):
        logger.warning(f"sanitize_chord_label: Input label '{label}' is not a string. Returning as is.")
        return str(label)

    original_label = label
    sanitized = label.strip() # 前後の空白を除去

    if sanitized.upper() in ["N.C.", "NC", "REST", ""]:
        logger.debug(f"Sanitizing '{original_label}' to 'Rest'")
        return "Rest"

    # ステップ 1: music21が解釈しやすい基本的な品質表記に統一
    quality_replacements = {
        r'(?i)maj7': 'M7', r'(?i)maj9': 'M9', r'(?i)maj13': 'M13',
        r'(?i)min7': 'm7', r'(?i)mi7': 'm7',
        r'(?i)min9': 'm9', r'(?i)mi9': 'm9',
        r'(?i)min11': 'm11',r'(?i)mi11': 'm11',
        r'(?i)min13': 'm13',r'(?i)mi13': 'm13',
        r'(?i)dom7': '7',
        r'(?i)half-diminished': 'ø', r'(?i)ø7': 'ø', r'm7b5': 'ø', # m7b5 も ø へ
        r'(?i)diminished7': 'dim7', r'(?i)dim7': 'dim7',
        r'(?i)diminished': 'dim', r'(?i)dim(?!7)': 'dim', # dim の後に7が続かない場合のみ
        r'(?i)augmented': 'aug', r'(?i)aug(?!m)': 'aug', # aug の後に m が続かない場合
        r'(?i)sus(?!4)': 'sus4', # sus の後に4がない場合はsus4に (C7sus -> C7sus4)
                                # C7sus4 はそのまま
    }
    for old, new in quality_replacements.items():
        sanitized = re.sub(old, new, sanitized)

    # ステップ 2: ルート音とベース音の臨時記号を正規化 (例: Bb -> B-, C/Ab -> C/A-)
    # ルート音とベース音のパターンをそれぞれ処理
    # 例: Bbm7 -> B-m7,  C/Gb -> C/G-
    # 複雑なネストを避けるため、少し冗長だが個別に処理
    parts = sanitized.split('/')
    root_part = parts[0]
    bass_part = parts[1] if len(parts) > 1 else None

    # ルート音の処理 (例: BbM7 -> B-M7, F#m7 -> F#m7)
    root_match = re.match(r"([A-Ga-g])([#b-]{0,2})(.*)", root_part)
    if root_match:
        note_name, acc, rest_of_chord = root_match.groups()
        acc = acc.replace('bb', '--').replace('b', '-') # music21 style flats
        # music21 は '##' を 'x' と解釈することもあるが、'##' で問題ない場合が多い
        root_part = note_name + acc + rest_of_chord

    if bass_part:
        bass_match = re.match(r"([A-Ga-g])([#b-]{0,2})(.*)", bass_part) # ベース音もコードクオリティを持つことは稀だが一応
        if bass_match:
            bass_note_name, bass_acc, bass_rest = bass_match.groups()
            bass_acc = bass_acc.replace('bb', '--').replace('b', '-')
            bass_part = bass_note_name + bass_acc + bass_rest
        sanitized = root_part + "/" + bass_part
    else:
        sanitized = root_part


    # ステップ 3: 括弧内のテンション表記の正規化
    # 例: C7(add11) -> C7(add11) (music21が解釈可能)
    # 例: C7(#9,b13) -> C7(#9,b13) (music21が解釈可能)
    # ここでは、過度な変換を避け、music21パーサーにできるだけ任せる。
    # 以前のエラーで `((` が発生していたので、単純な二重括弧の除去のみ行う。
    sanitized = sanitized.replace('((', '(').replace('))', ')')

    # 不要なスペースの整理（括弧の内外）
    sanitized = re.sub(r'\s*\(\s*', '(', sanitized)
    sanitized = re.sub(r'\s*\)\s*', ')', sanitized)
    sanitized = re.sub(r'\s*,\s*', ',', sanitized) # カンマ周りのスペース

    # (addX) の X が数字であることを期待
    # (#X) や (bX) の X が数字であることを期待
    # music21 は `(add11)`, `(#9)`, `(b9,#11)` のような形をサポートするはず。

    # "sus44" のような重複が発生していた問題への対処
    sanitized = sanitized.replace('sus44', 'sus4')

    # エラーログ `ValueError: Invalid chord abbreviation 'm7(('` や `M9((#11))`
    # このような `X((` というパターンは、`sanitized_label` が生成されるまでの過程で
    # 既に括弧が追加されているところに、`format_alterations_in_parentheses` のような
    # 関数がさらに括弧を追加しようとした場合に発生しやすい。
    # 現状の修正では `format_alterations_in_parentheses` は使わない方向で。

    if sanitized != original_label:
        logger.info(f"sanitize_chord_label: Sanitized '{original_label}' to '{sanitized}'")
    else:
        logger.debug(f"sanitize_chord_label: Label '{original_label}' required no changes.")

    return sanitized


def get_music21_chord_object(chord_label_str: str, current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    """
    与えられたコードラベル文字列から music21 の ChordSymbol オブジェクトを生成する。
    エラーが発生した場合は None を返す。
    """
    if not chord_label_str or chord_label_str.strip().upper() in ["N.C.", "NC", "REST", ""]:
        logger.debug(f"get_music21_chord_object: Chord label '{chord_label_str}' interpreted as Rest.")
        return None

    sanitized_label = sanitize_chord_label(chord_label_str)
    cs = None
    try:
        cs = harmony.ChordSymbol(sanitized_label)
        # パース成功後、もしピッチが空なら (例: ChordSymbol("Rest"))、それもRest扱いとする
        if not cs.pitches:
            logger.debug(f"get_music21_chord_object: Parsed '{sanitized_label}' but it has no pitches. Treating as Rest.")
            return None
        logger.debug(f"get_music21_chord_object: Successfully parsed '{sanitized_label}' (original: '{chord_label_str}') as {cs.figure}")
        return cs
    except harmony.HarmonyException as he:
        logger.error(f"get_music21_chord_object: HarmonyException when parsing '{sanitized_label}' (orig: '{chord_label_str}'): {he}. Treating as Rest.")
    except music21.exceptions21.Music21Exception as m21e: # pitch.AccidentalExceptionなどもこちら
        logger.error(f"get_music21_chord_object: Music21Exception when parsing '{sanitized_label}' (orig: '{chord_label_str}'): {m21e}. Treating as Rest.")
    except Exception as e:
        logger.error(f"get_music21_chord_object: Unexpected error parsing '{sanitized_label}' (orig: '{chord_label_str}'): {e}. Treating as Rest.", exc_info=True)
    
    return None # エラー時はNoneを返す


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s')
    test_labels_from_log = [
        "Am7(add11)", # -> Am7((add11)) -> m7((
        "E7(b9)",     # -> E7(( b9))  -> 7((b9))
        "C7sus4",     # -> C7sus44    -> 7sus44
        "Fmaj7(add9)",# -> FM7((add9)) -> M7((
        "Bbmaj9(#11)",# -> B-M9(( #11)) -> M9((#11))
        "C7(#9,b13)", # -> C7(( #9, b13)) -> ((#
        "Dm7(add13)", # -> Dm7((add13)) -> m7((
        "A7(b9)",     # -> A7(( b9)) -> 7((b9))
        "Fmaj7(add9,13)",# -> FM7((add9, 13)) -> m((add
        "C/Bb",
        "Ebmaj7(#11)", # -> E-M7(( #11))
        "Bbmaj7(#11)", # -> B-M7(( #11))
        "Fmaj9(#11)"   # -> FM9(( #11))
    ]
    additional_tests = [
        "Cmaj7", "Fmaj7", "Cm7b5", "G7sus",
        "Dbmaj7", "Ebm7", "Abmaj7",
        "Bbm6",
        "FM7", "B-M7", "C", "Am", "G", "Dbm",
        "N.C.", "Rest", "",
        "GM7(", "Am7(add11",
        "C#m7", "F#7",
        "C7(b9,#11)", "Gaug", "Fdim",
        "Calt", "C7alt", "C7#9b13",
        "Gsus", "F/G", "Am/G#", "D/F#",
        "Esus4(b9)",
        "Bb", "Eb/G", "C#",
        "Am7", "Dm7", "GM7"
    ]
    all_test_labels = test_labels_from_log + additional_tests

    print("\n--- Running sanitize_chord_label Test Cases ---")
    successful_parses = 0
    failed_parses = 0
    for label in sorted(list(set(all_test_labels))): # 重複を除きソート
        sanitized = sanitize_chord_label(label)
        print(f"Original: '{label}' -> Sanitized: '{sanitized}'")
        cs_obj = None
        if sanitized and sanitized.upper() not in ["N.C.", "NC", "REST"]:
            try:
                cs_obj = harmony.ChordSymbol(sanitized)
                if cs_obj:
                    if cs_obj.pitches: # ピッチが実際に生成されたか
                        print(f"  music21 parsed: {cs_obj.figure:<15} (Pitches: {[p.name for p in cs_obj.pitches]})")
                        successful_parses += 1
                    else:
                        print(f"  music21 parsed '{sanitized}' as ChordSymbol, BUT NO PITCHES (figure: {cs_obj.figure}). Interpreted as REST.")
                        failed_parses +=1 # ピッチがないものは失敗扱い
            except Exception as e:
                print(f"  music21 ERROR parsing sanitized '{sanitized}': {type(e).__name__}: {e}")
                failed_parses += 1
        elif sanitized.upper() == "REST":
            print(f"  Interpreted as Rest.")
            # REST は成功とみなすか？ここではカウントしない
        else:
            print(f"  Sanitized to empty or unhandled: '{sanitized}'")
            failed_parses +=1

    print(f"\n--- Sanitization Test Summary ---")
    print(f"Successfully parsed ChordSymbols with pitches: {successful_parses}")
    print(f"Failed/Rest/NoPitches ChordSymbols: {failed_parses}")

    print("\n--- Running get_music21_chord_object Test Cases (simulates direct use) ---")
    g_successful = 0
    g_failed = 0
    for label in sorted(list(set(all_test_labels))):
        # print(f"--- Processing original '{label}' with get_music21_chord_object ---")
        cs_obj = get_music21_chord_object(label)
        if cs_obj:
            # print(f"  Successfully created ChordSymbol: {cs_obj.figure}")
            # print(f"  Pitches: {[p.nameWithOctave for p in cs_obj.pitches]}")
            g_successful += 1
        else:
            # print(f"  Failed to create ChordSymbol or it's a Rest. Original: '{label}'")
            g_failed += 1
    print(f"\n--- get_music21_chord_object Test Summary ---")
    print(f"Successfully created ChordSymbols with pitches: {g_successful}")
    print(f"Failed or Rest interpretations: {g_failed}")

# --- END OF FILE generators/core_music_utils.py ---
