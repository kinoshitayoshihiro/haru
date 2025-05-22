# --- START OF FILE generators/core_music_utils.py (修正案) ---
import music21
import logging
from music21 import meter, pitch, scale, harmony # harmony をインポート
from typing import Optional, Dict, Any, Tuple, List
import re # 正規表現モジュールをインポート

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
    """
    ChordSymbolのパースエラーを防ぐためにコードラベルを整形・修正する。
    music21 v9.x での ChordSymbol のパース挙動を考慮。
    """
    if not isinstance(label, str):
        logger.warning(f"sanitize_chord_label: Input label '{label}' is not a string. Returning as is.")
        return str(label)

    original_label = label
    sanitized_label = label

    # 0. "N.C." や "Rest" はそのまま返す (music21 は Rest を解釈できる)
    if sanitized_label.upper() in ["N.C.", "NC", "REST"]:
        logger.debug(f"sanitize_chord_label: Label '{original_label}' is a non-chord symbol. Returning as is.")
        return "Rest" # music21.harmony.NoChord() も使えるが、Restで統一

    # 1. 基本的な品質表記の正規化 (music21標準へ)
    # 大文字小文字を区別せずに置換 (例: maj7, Maj7, MAJ7 -> M7)
    replacements = {
        r'maj7': 'M7', r'Maj7': 'M7', r'MAJ7': 'M7',
        r'maj9': 'M9', r'Maj9': 'M9', r'MAJ9': 'M9',
        r'maj13': 'M13', r'Maj13': 'M13', r'MAJ13': 'M13',
        r'min7': 'm7', r'Mi7': 'm7', r'MI7': 'm7', # mi7 も考慮
        r'min9': 'm9', r'Mi9': 'm9', r'MI9': 'm9',
        r'min11': 'm11', r'Mi11': 'm11', r'MI11': 'm11',
        r'min13': 'm13', r'Mi13': 'm13', r'MI13': 'm13',
        r'dim7': 'dim7', r'dim': 'dim', # dim はそのままで良いことが多い
        r'aug': 'aug', # aug もそのままで良いことが多い
        r'dom7': '7', # dominant 7th
        r'sus4': 'sus4', r'sus': 'sus4', # sus は sus4 と解釈されることが多い
        # よくある括弧なしのadd表記 (例: Cadd9 -> C(add9) music21のパーサーが直接解釈しやすい形へ)
        # ただし、これは後段の括弧処理と競合する可能性があるので注意深く扱う
        # r'add9': '(add9)', r'add11': '(add11)', r'add13': '(add13)',
    }
    for old, new in replacements.items():
        sanitized_label = re.sub(old, new, sanitized_label, flags=re.IGNORECASE)

    # 2. スラッシュコードのベース音のフラット表記修正 (例: C/Bb -> C/B-)
    #    およびルート音のフラット表記
    #    ([A-G])b([M|m|dim|aug|7|9|11|13|sus|alt|\d|/|\(|$])
    #    音名 + 'b' + 後続が品質や数字やスラッシュや括弧や終端
    def correct_flat_notation(s):
        # ルート音のフラット (例: BbM7 -> B-M7)
        s = re.sub(r'([A-Ga-g])b([MmDd79]|M(?![a-z])|[Dd](?![a-z])|aug|dim|sus|alt|ø|\^\d*|\d|$|\(|\))', r'\1-\2', s) # M, Dの後は数字か終端
        # ベース音のフラット (例: C/Bb -> C/B-)
        s = re.sub(r'/([A-Ga-g])b($|\s)', r'/\1-\2', s)
        return s

    sanitized_label = correct_flat_notation(sanitized_label)


    # 3. テンション/オルタレーションの括弧処理と内容の整形
    #   例: Am7(add11) -> Am7(add11) : music21は "Am7(add11)" を解釈できる
    #   例: C7(#9,b13) -> C7(#9, b13) or C7alt(#9, b13)
    #   例: E7(b9) -> E7(b9)

    # (addX) や (#X,bY) 形式の処理
    # music21.harmony.ChordSymbolは括弧内のテンション指定に対応している
    # ただし、括弧内の書式は music21.harmony.alterationToValue の仕様に準拠する必要がある
    # e.g., "(add9)", "(#9, b13)", "(omit5)"
    # 不完全な括弧 (例: "m7(") が問題になっているケースへの対処
    if '(' in sanitized_label and ')' not in sanitized_label:
        if sanitized_label.endswith('('): # "Xm7(" のようなケース
            logger.warning(
                f"sanitize_chord_label: Label '{original_label}' had an unmatched opening parenthesis at the end. Removing it."
            )
            sanitized_label = sanitized_label[:-1]
        # 他の不完全な括弧は複雑なので、music21のパーサーに任せる

    # addX や omitX の表記を music21 がより好む形式 (括弧付き) にする (もし括弧がなければ)
    # 例: Am7add11 -> Am7(add11)
    # (これは意図しない変換をする可能性もあるので慎重に)
    # match_add_omit = re.match(r'([A-G][b#-]?[^ao]*(?:M|m|dim|aug|sus|alt|ø|\^)?\d*)((?:add|omit)\d+)', sanitized_label, re.IGNORECASE)
    # if match_add_omit:
    #    base_chord = match_add_omit.group(1)
    #    tension_mod = match_add_omit.group(2)
    #    sanitized_label = f"{base_chord}({tension_mod})"


    # music21 が特定の記号の前にスペースを要求/許容する場合がある
    # 例: "C7#9" -> "C7 #9" の方が安定する場合も (パーサー次第)
    # 現状のログからは、これが直接の原因ではなさそうなので、一旦複雑な置換は避ける

    # 特殊なケース: Fmaj9(#11) のような表記。 music21 は Fmaj9(add#11) や FM9alt(#11) は受け付ける
    # FM9(#11) が直接エラーになるのは 'M9(' の部分なので、基本的な M9 への置換がまず重要
    # "M9(#11)" は "major-ninth" の後に alter指定をする "M9 alter(#11)" や
    # "M9(add#11)"のように、具体的な指示が必要かもしれない。
    # ここでは、括弧内の `#` や `b` の直前にスペースを挿入してみる (music21 v9 のパーサー改善に期待)
    def format_alterations_in_parentheses(s):
        def replace_func(match):
            content = match.group(2)
            # カンマやスペースで区切られていない連続したオルタレーションを整形
            # 例: (#9b13) -> (#9, b13)
            content = re.sub(r'([#b])(\d+)([#b])(\d+)', r'\1\2, \3\4', content) # #9b13 -> #9, b13
            content = re.sub(r'([#b])(\d+)', r' \1\2', content) # (b9) -> ( b9)
            content = content.replace(',', ', ') # カンマの後にスペース
            content = re.sub(r'\s+', ' ', content).strip() # 余分なスペースを整理
            return f"{match.group(1)}({content})"

        # 例: C7(#9,b13) -> C7(#9, b13)
        # 例: Am7(add11) -> Am7(add11) (これは変化なし)
        # 例: C7(#9b13) -> C7(#9, b13)
        return re.sub(r'([A-G][b#-]?[^()]*\d*)(\([^)]+\))', replace_func, s)

    sanitized_label = format_alterations_in_parentheses(sanitized_label)


    # 最終チェック：予期せぬ変更をしていないか、music21.harmony.ChordSymbolでテスト
    # (これはこの関数内では難しいので、呼び出し元で try-except するのが現実的)
    if sanitized_label != original_label:
        logger.info(f"sanitize_chord_label: Sanitized '{original_label}' to '{sanitized_label}'")
    else:
        logger.debug(f"sanitize_chord_label: Label '{original_label}' was not changed.")

    return sanitized_label

def get_music21_chord_object(chord_label_str: str, current_key: Optional[scale.ConcreteScale] = None) -> Optional[harmony.ChordSymbol]:
    """
    与えられたコードラベル文字列から music21 の ChordSymbol オブジェクトを生成する。
    エラーが発生した場合は None を返す。
    """
    if not chord_label_str or chord_label_str.strip().upper() in ["N.C.", "NC", "REST"]:
        logger.debug(f"get_music21_chord_object: Chord label '{chord_label_str}' interpreted as Rest.")
        return None # None を返して、呼び出し側で Rest として扱ってもらう

    sanitized_label = sanitize_chord_label(chord_label_str)
    cs = None

    # パターン1: そのままパース
    try:
        cs = harmony.ChordSymbol(sanitized_label)
        logger.debug(f"get_music21_chord_object: Successfully parsed '{sanitized_label}' (original: '{chord_label_str}') as {cs.figure}")
        return cs
    except music21.harmony.HarmonyException as e_harm_initial:
        logger.warning(f"get_music21_chord_object: Initial HarmonyException for '{sanitized_label}' (orig: '{chord_label_str}'): {e_harm_initial}. Attempting fallback strategies.")
    except Exception as e_initial: # music21.pitch.AccidentalExceptionなどもこちらで捕捉
        logger.warning(f"get_music21_chord_object: Initial Music21Exception (not HarmonyException) for '{sanitized_label}' (orig: '{chord_label_str}'): {e_initial}. Attempting fallback strategies.")


    # フォールバック戦略:
    # ここでは、エラーメッセージに基づいて特化した修正を試みるよりも、
    # よりシンプルな形へのフォールバックを検討する。
    # (例: Am7(add11) -> Am7 -> Am -> A)

    # 現状の sanitize_chord_label に多くのロジックが集約されているため、
    # ここでのフォールバックは最小限にするか、あるいは
    # sanitize_chord_label の中で段階的な簡略化を試みるようにする。
    # ここでは、一旦、最初のパース失敗で None (Rest扱い) とする。
    # さらなる安定性のためには、より多くのフォールバックをここやsanitize_chord_label内に実装できる。

    logger.error(f"get_music21_chord_object: Failed to parse '{sanitized_label}' (orig: '{chord_label_str}') even after sanitization. Treating as Rest.")
    return None


if __name__ == '__main__':
    # --- Test Cases for sanitize_chord_label ---
    logging.basicConfig(level=logging.DEBUG)
    test_labels = [
        "Cmaj7", "Fmaj7", "E7(b9)", "Am7(add11)", "G7sus", "Cm7b5", "C/Bb",
        "Dbmaj7", "Ebm7", "Abmaj7", "C7(#9,b13)", "Fmaj7(add9)", "Bbmaj7",
        "Dm7(add13)", "A7(b9)", "Bbmaj9(#11)", "Fmaj7(add9,13)", "Cmaj7/F",
        "Bbm6", "Fmaj9(#11)",
        "FM7", "B-M7", "C", "Am", "G", "Dbm", # シンプルなケース
        "N.C.", "Rest",
        "GM7(", "Am7(add11", # 不完全な括弧
        "C#m7", "F#7", # シャープのルート
        "C7(b9,#11)", "Gaug", "Fdim", # その他のオルタレーションやタイプ
        "Calt", "C7alt",
        "Gsus", "Csus4", "F/G", "Am/G#",
        "Esus4(b9)", # sus とテンション
        "Bbm7(add11)" # エラーログにあった m7( のケースへの対応を期待
    ]

    print("\n--- Running sanitize_chord_label Test Cases ---")
    for label in test_labels:
        sanitized = sanitize_chord_label(label)
        print(f"Original: '{label}' -> Sanitized: '{sanitized}'")
        # 実際に music21 でパースしてみる
        cs_obj = None
        if sanitized and sanitized.strip().upper() not in ["N.C.", "NC", "REST"]:
            try:
                cs_obj = harmony.ChordSymbol(sanitized)
                if cs_obj:
                     print(f"  music21 parsed: {cs_obj.figure} (Pitches: {cs_obj.pitches})")
            except Exception as e:
                print(f"  music21 ERROR parsing sanitized '{sanitized}': {e}")
        elif sanitized.upper() == "REST":
             print(f"  Interpreted as Rest.")

    print("\n--- Running get_music21_chord_object Test Cases ---")
    for label in test_labels:
        print(f"--- Processing '{label}' ---")
        cs_obj = get_music21_chord_object(label)
        if cs_obj:
            print(f"  Successfully created ChordSymbol: {cs_obj.figure}")
            print(f"  Pitches: {[p.nameWithOctave for p in cs_obj.pitches]}")
        else:
            print(f"  Failed to create ChordSymbol or it's a Rest. Original: '{label}'")
