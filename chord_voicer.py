# --- START OF FILE generators/chord_voicer.py (修正案) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, interval, tempo, key,
                     chord as m21chord.Chord, volume as m21volume)
import random
import logging

logger = logging.getLogger(__name__) # __name__ を使うのが一般的

# --- core_music_utils からのインポート試行 ---
try:
    # PYTHONPATHが通っていればこれでOKなはず
    from .core_music_utils import get_time_signature_object, sanitize_chord_label
    logger.info("ChordVoicer: Successfully imported from .core_music_utils.")
except ImportError as e_import_core:
    # Colab環境などで PYTHONPATH の問題がある場合、または generators/ が sys.path にない場合
    try:
        from core_music_utils import get_time_signature_object, sanitize_chord_label # 相対インポートなしで試す
        logger.info("ChordVoicer: Successfully imported core_music_utils (without relative path).")
    except ImportError as e_import_direct:
        logger.warning(f"ChordVoicer: Could not import from .core_music_utils (Error: {e_import_core}) "
                       f"nor directly from core_music_utils (Error: {e_import_direct}). "
                       "Using basic fallbacks for get_time_signature_object and sanitize_chord_label.")
        # --- フォールバック定義 ---
        def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
            if not ts_str: ts_str = "4/4"
            try: return meter.TimeSignature(ts_str)
            except meter.MeterException:
                logger.warning(f"CV Fallback GTSO: Invalid TS '{ts_str}'. Default 4/4.")
                return meter.TimeSignature("4/4")
            except Exception as e_ts_fb:
                 logger.error(f"CV Fallback GTSO: Unexpected error '{ts_str}': {e_ts_fb}. Defaulting to 4/4.", exc_info=True)
                 return meter.TimeSignature("4/4")

        def sanitize_chord_label(label: str) -> str:
            logger.warning(f"CV Fallback sanitize_chord_label used for '{label}'. This is a basic version.")
            # これはあくまで基本的なフォールバック。core_music_utils.py の方がずっと高機能。
            label = str(label) # Ensure it's a string
            label = label.replace('maj7', 'M7').replace('mi7', 'm7').replace('min7', 'm7')
            label = label.replace('Maj7', 'M7').replace('Mi7', 'm7').replace('Min7', 'm7') # Case variations
            # 簡易的な 'Bb' -> 'B-'
            if len(label) > 1 and label[1] == 'b' and label[0] in 'ABCDEFGabcdefg':
                 if not (len(label) > 2 and label[2].isalpha()): # "Ebm" のようなケースでないことを確認
                    label = label[0] + '-' + label[2:]
            # 不完全な括弧
            if label.count('(') > label.count(')') and label.endswith('('):
                label = label[:-1]
            return label
        # --- フォールバック定義ここまで ---

DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM: int = 3
VOICING_STYLE_CLOSED = "closed"
VOICING_STYLE_OPEN = "open"
VOICING_STYLE_SEMI_CLOSED = "semi_closed" # This is a custom style name
VOICING_STYLE_DROP2 = "drop2"
VOICING_STYLE_FOUR_WAY_CLOSE = "four_way_close" # music21's fourWayClose

class ChordVoicer:
    def __init__(self,
                 default_instrument=m21instrument.StringInstrument(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        try:
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except NameError: # フォールバックでも get_time_signature_object が未定義の場合
             logger.critical("ChordVoicer __init__: CRITICAL - get_time_signature_object is not defined at all! Defaulting to basic 4/4.")
             self.global_time_signature_obj = meter.TimeSignature("4/4")
        except Exception as e_ts_init:
            logger.error(f"ChordVoicer __init__: Error initializing time signature from '{global_time_signature}': {e_ts_init}. Defaulting to 4/4.", exc_info=True)
            self.global_time_signature_obj = meter.TimeSignature("4/4")

    def _apply_voicing_style(
            self,
            m21_cs: Optional[harmony.ChordSymbol], # Can be None if parsing failed or it was a Rest
            style_name: str,
            target_octave_for_bottom_note: Optional[int] = DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM,
            num_voices_target: Optional[int] = None
    ) -> List[pitch.Pitch]:

        if m21_cs is None:
            logger.debug(f"CV._apply_style: ChordSymbol is None. Returning empty list.")
            return []
        if not m21_cs.pitches: # e.g. harmony.ChordSymbol("Rest")
            logger.debug(f"CV._apply_style: ChordSymbol '{m21_cs.figure}' has no pitches (e.g., it's a Rest). Returning empty list.")
            return []

        voiced_pitches_list: List[pitch.Pitch] = []
        # 常に closedPosition を基準として扱う (inPlace=False でコピーを取得)
        original_closed_pitches = sorted(list(m21_cs.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
        
        if not original_closed_pitches: # 稀だが、closedPositionの結果が空になるケース
            logger.warning(f"CV._apply_style: ChordSymbol '{m21_cs.figure}' resulted in no pitches after closedPosition. Returning empty list.")
            return []

        current_pitches_for_voicing = list(original_closed_pitches) # 操作用のコピー

        try:
            if style_name == VOICING_STYLE_OPEN:
                # openPosition は closedPosition に基づくので、current_pitches_for_voicing を使う
                temp_chord_for_open = m21chord.Chord(current_pitches_for_voicing)
                voiced_pitches_list = list(temp_chord_for_open.openPosition(inPlace=False).pitches)
            elif style_name == VOICING_STYLE_SEMI_CLOSED: # カスタムロジック
                if len(current_pitches_for_voicing) >= 2:
                    # bass_of_cs = m21_cs.bass() # ChordSymbolのベース音
                    # ここでは、一番下の音をオクターブ下げるシンプルなものとする
                    lowest_pitch = current_pitches_for_voicing[0]
                    new_bass_p = lowest_pitch.transpose(-12)
                    voiced_pitches_list = sorted([new_bass_p] + current_pitches_for_voicing[1:], key=lambda p: p.ps)
                else:
                    voiced_pitches_list = current_pitches_for_voicing
            elif style_name == VOICING_STYLE_DROP2:
                # Drop2 は closed position の上から2番目の音をオクターブ下げる
                if len(current_pitches_for_voicing) >= 2:
                    pitches_copy = list(current_pitches_for_voicing) # 新しいリストで操作
                    if len(pitches_copy) >= 4: # 4声以上
                        pitch_to_drop = pitches_copy.pop(-2) # 上から2番目
                        dropped_pitch = pitch_to_drop.transpose(-12)
                        voiced_pitches_list = sorted(pitches_copy + [dropped_pitch], key=lambda p: p.ps)
                    elif len(pitches_copy) == 3: # 3声の場合、2番目の音 (真ん中) をドロップ
                         pitch_to_drop = pitches_copy.pop(1)
                         dropped_pitch = pitch_to_drop.transpose(-12)
                         voiced_pitches_list = sorted(pitches_copy + [dropped_pitch], key=lambda p:p.ps)
                    else: # 2声の場合は closed のまま
                        voiced_pitches_list = current_pitches_for_voicing
                else:
                    voiced_pitches_list = current_pitches_for_voicing
            elif style_name == VOICING_STYLE_FOUR_WAY_CLOSE:
                temp_m21_chord_for_4way = m21chord.Chord(current_pitches_for_voicing)
                if len(temp_m21_chord_for_4way.pitches) >= 4 :
                    try:
                        temp_m21_chord_for_4way.fourWayClose(inPlace=True) # このメソッドは inPlace=True がデフォルトの場合がある
                        voiced_pitches_list = list(temp_m21_chord_for_4way.pitches)
                    except Exception as e_4way:
                        logger.warning(f"CV: fourWayClose for '{m21_cs.figure}' failed: {e_4way}. Defaulting to closed.")
                        voiced_pitches_list = current_pitches_for_voicing
                else:
                    logger.debug(f"CV: Not enough pitches ({len(temp_m21_chord_for_4way.pitches)}) for fourWayClose on {m21_cs.figure}. Using closed.")
                    voiced_pitches_list = current_pitches_for_voicing
            else: # Default or unknown style is "closed"
                if style_name != VOICING_STYLE_CLOSED:
                    logger.debug(f"CV: Unknown style '{style_name}'. Defaulting to closed for '{m21_cs.figure}'.")
                voiced_pitches_list = current_pitches_for_voicing # closedPositionの結果をそのまま使用

        except Exception as e_style_app:
            logger.error(f"CV._apply_style: Error applying voicing style '{style_name}' to '{m21_cs.figure}': {e_style_app}. Defaulting to original closed pitches.", exc_info=True)
            voiced_pitches_list = list(original_closed_pitches) # エラー時は元のclosed position pitchesに戻す

        if not voiced_pitches_list: # スタイル適用後に空になった場合
            logger.warning(f"CV._apply_style: Voicing style '{style_name}' resulted in empty pitches for '{m21_cs.figure}'. Using original closed pitches.")
            voiced_pitches_list = list(original_closed_pitches)

        # Voice limiting
        if num_voices_target is not None and voiced_pitches_list:
            if len(voiced_pitches_list) > num_voices_target:
                # 上から num_voices_target 分取るか、下から取るか、音楽的意図による
                # ここではシンプルに下から（音高の低い順）num_voices_target 分を取得
                voiced_pitches_list = sorted(voiced_pitches_list, key=lambda p: p.ps)[:num_voices_target]
                logger.debug(f"CV: Reduced voices to {num_voices_target} for '{m21_cs.figure}' (from bottom).")

        # Octave adjustment
        if voiced_pitches_list and target_octave_for_bottom_note is not None:
            current_bottom_pitch_obj = min(voiced_pitches_list, key=lambda p: p.ps)
            # ターゲットオクターブのルート音を基準とする
            ref_pitch_name = m21_cs.root().name if m21_cs.root() else 'C'
            try:
                target_bottom_ref_pitch = pitch.Pitch(f"{ref_pitch_name}{target_octave_for_bottom_note}")
                octave_difference = round((target_bottom_ref_pitch.ps - current_bottom_pitch_obj.ps) / 12.0)
                semitones_to_shift = int(octave_difference * 12)

                if semitones_to_shift != 0:
                    logger.debug(f"CV: Shifting '{m21_cs.figure}' voiced as [{', '.join(p.nameWithOctave for p in voiced_pitches_list)}] by {semitones_to_shift} semitones for target bottom octave {target_octave_for_bottom_note} (ref root: {ref_pitch_name}).")
                    voiced_pitches_list = [p.transpose(semitones_to_shift) for p in voiced_pitches_list]
            except Exception as e_trans:
                 logger.error(f"CV: Error in octave adjustment for '{m21_cs.figure}': {e_trans}", exc_info=True)
                 #エラー時は元のピッチリストを維持する
        return voiced_pitches_list

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        chord_part = stream.Part(id="ChordVoicerPart")
        try:
            chord_part.insert(0, self.default_instrument) # 初期化時にエラーがあれば m21instrument.Instrument()など
            chord_part.append(tempo.MetronomeMark(number=self.global_tempo))
            chord_part.append(self.global_time_signature_obj)
        except Exception as e_init_part:
            logger.error(f"CV.compose: Error setting up initial part elements: {e_init_part}", exc_info=True)
            # 致命的ではないので処理は続行

        if not processed_chord_stream:
            logger.info("CV.compose: Received empty processed_chord_stream.")
            return chord_part
        logger.info(f"CV.compose: Processing {len(processed_chord_stream)} blocks.")

        current_key_obj: Optional[key.Key] = None # 必要であればセクションごとの調情報を扱う

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            offset_ql = float(blk_data.get("offset", 0.0))
            duration_ql = float(blk_data.get("q_length", 4.0)) # ql from block, not just 4.0
            chord_label_original: str = blk_data.get("chord_label", "C") # Ensure it's a string
            
            part_params: Dict[str, Any] = blk_data.get("chords_params", blk_data.get("chord_params", {}))
            voicing_style: str = part_params.get("chord_voicing_style", VOICING_STYLE_CLOSED)
            target_octave: Optional[int] = part_params.get("chord_target_octave") # None許容
            if target_octave is None : target_octave = DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM
            num_voices: Optional[int] = part_params.get("chord_num_voices")
            chord_velocity: int = int(part_params.get("chord_velocity", 64))

            logger.debug(f"CV Block {blk_idx+1}: Offset:{offset_ql} QL:{duration_ql} OrigLabel='{chord_label_original}', Style:'{voicing_style}', Oct:{target_octave}, Voices:{num_voices}, Vel:{chord_velocity}")

            cs_obj: Optional[harmony.ChordSymbol] = None
            is_block_effectively_rest = False

            if not chord_label_original or chord_label_original.strip().lower() in ["rest", "n.c.", "nc", ""]:
                logger.info(f"CV Block {blk_idx+1} is explicitly a Rest due to label: '{chord_label_original}'.")
                is_block_effectively_rest = True
            else:
                sanitized_label = sanitize_chord_label(chord_label_original) # From core_music_utils
                try:
                    cs_obj = harmony.ChordSymbol(sanitized_label)
                    # ChordSymbol("Rest") の場合や、何らかの理由でピッチが生成されない場合
                    if not cs_obj.pitches:
                        logger.info(f"CV: ChordSymbol '{sanitized_label}' (orig: '{chord_label_original}') resulted in no pitches. Treating as Rest.")
                        is_block_effectively_rest = True
                except music21.harmony.HarmonyException as he:
                    logger.error(f"CV: HarmonyException creating ChordSymbol for '{sanitized_label}' (orig: '{chord_label_original}'): {he}. Treating as Rest.")
                    is_block_effectively_rest = True
                except Exception as e_cs_create: # Includes AccidentalException etc.
                    logger.error(f"CV: General Exception creating ChordSymbol for '{sanitized_label}' (orig: '{chord_label_original}'): {e_cs_create}. Treating as Rest.", exc_info=False) # exc_info=True for more detail if needed
                    is_block_effectively_rest = True
            
            if is_block_effectively_rest:
                # 明示的なRestオブジェクトを追加するか、何もしないか。
                # 他のジェネレータとの一貫性のため、ここでは何もしない（無音区間となる）
                # 必要であれば r = note.Rest(quarterLength=duration_ql); chord_part.insert(offset_ql, r)
                logger.debug(f"CV Block {blk_idx+1}: Handled as Rest. No chord added to part.")
                continue

            if cs_obj is None: # is_block_effectively_rest でないのに cs_obj が None はあり得ないはずだが念のため
                logger.error(f"CV Block {blk_idx+1}: cs_obj is unexpectedly None for non-Rest label '{chord_label_original}'. Skipping.")
                continue

            # テンションの追加（cs_objが確実に存在する時点で行う）
            # この 'tensions_to_add' がどのように定義されているかによる。文字列のリストを想定。
            tensions_to_add_list: List[str] = blk_data.get("tensions_to_add", [])
            if tensions_to_add_list:
                logger.debug(f"CV: Attempting to add tensions {tensions_to_add_list} to {cs_obj.figure}")
                for tension_str in tensions_to_add_list:
                    try:
                        # addChordStepModification は music21.interval.Interval を取る
                        # 単純な数字(9, 11, 13)や "add9", "#11", "b13" 等をパースする必要がある
                        # ここでは ChordSymbol のfigure に直接文字列として結合してしまう方が music21 v9では扱いやすいことがある
                        # 例: cs_obj.figure = cs_obj.figure + tension_str
                        # または、より堅牢なのは cs_obj.add() や cs_obj.addChordStepModification()
                        # エラーログの add11 や #9,b13 が文字列でどのように与えられるかによる
                        # 一旦、最も安全なのは figure から再生成か、 .add(intervalNumber)
                        # 'add11' のような文字列なら
                        num_match = re.search(r'(\d+)', tension_str)
                        if num_match:
                            interval_num = int(num_match.group(1))
                            # alter_match = re.search(r'([#b]+)', tension_str) # alterも考慮する場合
                            cs_obj.add(interval_num) # 危険: これは基音からの度数
                            logger.debug(f"  CV: Added tension based on '{tension_str}' to {cs_obj.figure}")
                        else:
                             logger.warning(f"  CV: Could not parse tension number from '{tension_str}' for {cs_obj.figure}")
                    except Exception as e_add_tension:
                        logger.warning(f"  CV: Error adding tension '{tension_str}' to '{cs_obj.figure}': {e_add_tension}")

            # テンション追加後にピッチが空になっていないか再度確認
            if not cs_obj.pitches:
                logger.warning(f"CV Block {blk_idx+1}: Chord '{cs_obj.figure}' has no pitches after attempting tension additions. Treating as Rest.")
                continue # このブロックはRestとしてスキップ

            final_voiced_pitches = self._apply_voicing_style(
                cs_obj, # cs_obj はこの時点で None ではない
                voicing_style,
                target_octave_for_bottom_note=target_octave,
                num_voices_target=num_voices
            )

            if not final_voiced_pitches:
                logger.warning(f"CV Block {blk_idx+1}: No pitches returned after voicing style for '{cs_obj.figure}'. Skipping.")
                continue
            
            # music21.chord.Chord オブジェクトを作成してパートに追加
            new_chord_m21 = m21chord.Chord(final_voiced_pitches)
            new_chord_m21.duration = duration.Duration(duration_ql)
            # ベロシティ設定
            try:
                # Volumeオブジェクトを使う方がよりmusic21的
                vol = m21volume.Volume(velocity=chord_velocity)
                for p_in_chord in new_chord_m21.pitches:
                    # Noteオブジェクトは直接velocityを持てないので、Chord全体か、NoteごとのVolume
                    # ここでは Chordオブジェクトが velocityを持てないので、NoteオブジェクトごとのVolumeを設定 (やや冗長)
                    # MusicXML や MIDI 出力時にどう解釈されるかによる
                    pass # new_chord_m21.volume = vol だとうまくいかないことが多い。
                # 一般的には new_chord_m21. δυναμικό = ... だが、MIDI ベロシティとは直接対応しない
                # もっとも単純なのは、各音のNoteオブジェクトを作って velocity を設定し、それを Chord にすること。
                # ここでは、とりあえず new_chord_m21 をそのまま追加する。
                # MIDI出力時には pretty_midi などでベロシティを細かく制御する想定があるため、
                # music21 Stream内のベロシティはそこまで厳密でなくても良いかもしれない。
                # もし Note ごとにベロシティを設定するなら:
                notes_for_chord = []
                for p in final_voiced_pitches:
                    n = note.Note(p)
                    n.volume = vol # 각 음표에 볼륨(벨로시티) 설정
                    notes_for_chord.append(n)
                if notes_for_chord:
                    new_chord_with_velocity = m21chord.Chord(notes_for_chord, quarterLength=duration_ql)
                    chord_part.insert(offset_ql, new_chord_with_velocity)
                    logger.debug(f"  CV: Added chord {new_chord_with_velocity.pitchedCommonName} with vel {chord_velocity} at offset {offset_ql}")
                else:
                    logger.warning(f"CV Block {blk_idx+1}: notes_for_chord was empty after creating notes with velocity.")


            except Exception as e_add_final:
                logger.error(f"CV Block {blk_idx+1}: Error adding final chord for '{cs_obj.figure if cs_obj else 'N/A'}': {e_add_final}", exc_info=True)
        
        logger.info(f"CV.compose: Finished composition. Part contains {len(list(chord_part.flatten().notesAndRests))} elements.")
        return chord_part

# --- END OF FILE generators/chord_voicer.py ---
