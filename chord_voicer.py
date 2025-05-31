# --- START OF FILE generators/chord_voicer.py (emotion_humanizer連携強化・改修版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence

# music21 のサブモジュールを正しい形式でインポート
import music21.stream as stream
import music21.note as note
import music21.harmony as harmony
import music21.pitch as pitch
import music21.meter as meter
import music21.duration as duration
import music21.instrument as m21instrument
import music21.interval as interval
import music21.tempo as tempo
import music21.key as key
import music21.chord      as m21chord
import music21.volume as m21volume
from music21 import expressions
from music21 import articulations # 明示的にインポート
import re
import random
import logging

logger = logging.getLogger(__name__)

# --- core_music_utils からのインポート試行 ---
try:
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label
    logger.info("ChordVoicer: Successfully imported from utilities.core_music_utils.")
except ImportError:
    logger.warning("ChordVoicer: Could not import from utilities.core_music_utils. Using basic fallbacks.")
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
        if label is None: return "Rest"
        s = str(label).strip().replace('(', '').replace(')', '')
        if s.upper() in ['NC', 'N.C.', 'NOCHORD', 'SILENCE', '-', 'REST']: return "Rest"
        s = s.replace('Bb', 'B-').replace('Eb', 'E-').replace('Ab', 'A-').replace('Db', 'D-').replace('Gb', 'G-')
        s = s.replace('△', 'maj').replace('M', 'maj')
        if 'majaj' in s: s = s.replace('majaj', 'maj')
        s = s.replace('ø', 'm7b5').replace('Φ', 'm7b5')
        return s

DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM: int = 3
VOICING_STYLE_CLOSED = "closed"
VOICING_STYLE_OPEN = "open"
VOICING_STYLE_SEMI_CLOSED = "semi_closed"
VOICING_STYLE_DROP2 = "drop2"
VOICING_STYLE_DROP3 = "drop3"
VOICING_STYLE_DROP24 = "drop2and4"
VOICING_STYLE_FOUR_WAY_CLOSE = "four_way_close"
DEFAULT_VOICING_STYLE = VOICING_STYLE_CLOSED

class ChordVoicer:
    def __init__(self,
                 default_instrument=m21instrument.KeyboardInstrument(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        try:
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
            if self.global_time_signature_obj is None:
                logger.warning("ChordVoicer __init__: get_time_signature_object returned None. Defaulting to 4/4.")
                self.global_time_signature_obj = meter.TimeSignature("4/4")
        except Exception as e_ts_init:
            logger.error(f"ChordVoicer __init__: Error initializing time signature from '{global_time_signature}': {e_ts_init}. Defaulting to 4/4.", exc_info=True)
            self.global_time_signature_obj = meter.TimeSignature("4/4")

    def _apply_voicing_style(
            self,
            cs_obj: harmony.ChordSymbol,
            style_name: str,
            target_octave_for_bottom_note: int = DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM,
            num_voices_target: Optional[int] = None
    ) -> List[pitch.Pitch]:
        if not cs_obj.pitches:
            logger.debug(f"CV._apply_style: ChordSymbol '{cs_obj.figure}' has no pitches. Returning empty list.")
            return []
        try:
            temp_chord_for_closed = m21chord.Chord(cs_obj.pitches)
            original_closed_pitches = sorted(list(temp_chord_for_closed.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
        except Exception as e_closed:
            logger.warning(f"CV._apply_style: Could not get closed position for '{cs_obj.figure}': {e_closed}. Using raw pitches.")
            original_closed_pitches = sorted(list(cs_obj.pitches),  key=lambda p: p.ps)

        if not original_closed_pitches: return []
        current_pitches_for_voicing = list(original_closed_pitches)
        voiced_pitches_list: List[pitch.Pitch] = []

        try:
            if style_name == VOICING_STYLE_OPEN:
                temp_chord = m21chord.Chord(current_pitches_for_voicing)
                voiced_pitches_list = list(temp_chord.openPosition(inPlace=False).pitches)
            elif style_name == VOICING_STYLE_DROP2:
                if len(current_pitches_for_voicing) >= 2:
                    temp_pitches = list(current_pitches_for_voicing)
                    if len(temp_pitches) >= 2: # 2声以上で有効
                        if len(temp_pitches) >= 4: # 4声以上の場合は上から2番目
                            second_highest = temp_pitches.pop(-2)
                        elif len(temp_pitches) == 3: # 3声の場合は真ん中
                            second_highest = temp_pitches.pop(1)
                        else: # 2声の場合は高い方 (実質ルートが下がる)
                            second_highest = temp_pitches.pop(1)
                        second_highest_dropped = second_highest.transpose(-12)
                        voiced_pitches_list = sorted(temp_pitches + [second_highest_dropped], key=lambda p: p.ps)
                    else: voiced_pitches_list = current_pitches_for_voicing
                else: voiced_pitches_list = current_pitches_for_voicing
            elif style_name == VOICING_STYLE_FOUR_WAY_CLOSE:
                if len(current_pitches_for_voicing) >= 4:
                    temp_chord = m21chord.Chord(current_pitches_for_voicing)
                    try:
                        temp_chord.fourWayClose(inPlace=True)
                        voiced_pitches_list = list(temp_chord.pitches)
                    except Exception as e_4way:
                        logger.warning(f"CV: fourWayClose for '{cs_obj.figure}' failed: {e_4way}. Defaulting to closed.")
                        voiced_pitches_list = current_pitches_for_voicing
                else:
                    logger.debug(f"CV: Not enough pitches for fourWayClose on {cs_obj.figure}. Using closed.")
                    voiced_pitches_list = current_pitches_for_voicing
            elif style_name == VOICING_STYLE_SEMI_CLOSED:
                if len(current_pitches_for_voicing) >= 1: # 最低1音あればルートは作れる
                    root_note = cs_obj.root()
                    if root_note:
                        bass_pitch = pitch.Pitch(root_note.name)
                        bass_pitch.octave = target_octave_for_bottom_note # 指定オクターブにルートを配置
                        
                        other_pitches = [p for p in original_closed_pitches if p.name != root_note.name]
                        # 残りの音でクローズボイシングをベース音より上に作る
                        upper_voices = []
                        if other_pitches:
                            temp_upper_chord = m21chord.Chord(other_pitches)
                            closed_upper_pitches = sorted(list(temp_upper_chord.closedPosition(inPlace=False).pitches), key=lambda p:p.ps)
                            # ベース音より高い位置になるように調整
                            if closed_upper_pitches:
                                lowest_upper = min(closed_upper_pitches, key=lambda p:p.ps)
                                shift_needed = 0
                                while lowest_upper.ps <= bass_pitch.ps:
                                    lowest_upper.transpose(12, inPlace=True)
                                    shift_needed +=12
                                if shift_needed > 0:
                                    upper_voices = [p.transpose(shift_needed) for p in closed_upper_pitches]
                                else:
                                    upper_voices = closed_upper_pitches
                        voiced_pitches_list = sorted([bass_pitch] + upper_voices, key=lambda p: p.ps)
                    else: voiced_pitches_list = current_pitches_for_voicing
                else: voiced_pitches_list = current_pitches_for_voicing
            else:
                if style_name != VOICING_STYLE_CLOSED:
                    logger.debug(f"CV: Unknown voicing style '{style_name}'. Defaulting to closed for '{cs_obj.figure}'.")
                voiced_pitches_list = current_pitches_for_voicing
        except Exception as e_style_app:
            logger.error(f"CV._apply_style: Error applying voicing style '{style_name}' to '{cs_obj.figure}': {e_style_app}. Defaulting to closed.", exc_info=True)
            voiced_pitches_list = list(original_closed_pitches)

        if not voiced_pitches_list: voiced_pitches_list = list(original_closed_pitches)

        if num_voices_target is not None and voiced_pitches_list:
            if len(voiced_pitches_list) > num_voices_target:
                # より音楽的な声部削減（例：ルートと主要テンションを残すなど）も検討可能
                voiced_pitches_list = sorted(voiced_pitches_list, key=lambda p: p.ps)[:num_voices_target]
        
        if voiced_pitches_list:
            current_bottom_pitch_obj = min(voiced_pitches_list, key=lambda p: p.ps)
            ref_pitch_for_octave = cs_obj.bass() if cs_obj.bass() is not None else cs_obj.root()
            if ref_pitch_for_octave is None: ref_pitch_for_octave = pitch.Pitch("C")

            target_bottom_ref_pitch = pitch.Pitch(ref_pitch_for_octave.name)
            target_bottom_ref_pitch.octave = target_octave_for_bottom_note
            octave_difference = round((target_bottom_ref_pitch.ps - current_bottom_pitch_obj.ps) / 12.0)
            semitones_to_shift = int(octave_difference * 12)
            if semitones_to_shift != 0:
                voiced_pitches_list = [p.transpose(semitones_to_shift) for p in voiced_pitches_list]
        
        return sorted(voiced_pitches_list, key=lambda p: p.ps)

    def compose(self, processed_chord_events: List[Dict]) -> stream.Part:
        chord_part = stream.Part(id="ChordsVoiced")
        try:
            chord_part.insert(0, self.default_instrument)
            if self.global_tempo:
                chord_part.append(tempo.MetronomeMark(number=self.global_tempo))
            if self.global_time_signature_obj:
                chord_part.append(self.global_time_signature_obj.clone())
            else:
                chord_part.append(meter.TimeSignature("4/4"))
        except Exception as e_init_part:
            logger.error(f"CV.compose: Error setting up initial part elements: {e_init_part}", exc_info=True)

        if not processed_chord_events:
            logger.info("CV.compose: Received empty processed_chord_events.")
            return chord_part
        logger.info(f"CV.compose: Processing {len(processed_chord_events)} chord events.")

        for event_idx, event_data in enumerate(processed_chord_events):
            abs_offset = event_data.get("absolute_offset") # modular_composer.pyの出力に合わせる
            humanized_duration = event_data.get("q_length") # modular_composer.pyの出力に合わせる
            chord_symbol_str = event_data.get("chord_symbol_for_voicing")
            specified_bass_str = event_data.get("specified_bass_for_voicing")
            
            # emotion_params からベロシティとアーティキュレーションを取得
            emotion_params = event_data.get("emotion_params", {})
            humanized_velocity = emotion_params.get("velocity", 64)
            humanized_articulation_str = emotion_params.get("articulation")

            # part_params からボイシングスタイルなどを取得
            # modular_composer.py の prepare_stream_for_generators で part_params["chords"] に設定される想定
            voicing_params = event_data.get("part_params", {}).get("chords", {})
            if not voicing_params: # フォールバック
                voicing_params = event_data.get("part_params", {}).get("piano", {}) # ピアノ設定を流用

            voicing_style_name = voicing_params.get("voicing_style", DEFAULT_VOICING_STYLE)
            # target_octave, num_voices は DEFAULT_CONFIG の piano 設定などを参照するように変更
            default_piano_cfg = DEFAULT_CONFIG.get("default_part_parameters",{}).get("piano",{})
            target_oct = voicing_params.get("target_octave", default_piano_cfg.get("default_rh_target_octave", DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM))
            num_voices = voicing_params.get("num_voices", default_piano_cfg.get("default_rh_num_voices"))


            if chord_symbol_str is None or chord_symbol_str.lower() == "rest":
                logger.debug(f"  CV Event {event_idx+1}: '{chord_symbol_str}' is Rest. Skipping.")
                continue

            try:
                # sanitize_chord_label は emotion_humanizer.py で適用済みのはずだが、念のため
                final_chord_symbol_str = sanitize_chord_label(chord_symbol_str)
                if not final_chord_symbol_str or final_chord_symbol_str.lower() == "rest":
                    logger.debug(f"  CV Event {event_idx+1}: Sanitized to Rest. Skipping.")
                    continue
                
                cs = harmony.ChordSymbol(final_chord_symbol_str)
                if specified_bass_str:
                    final_bass_str = sanitize_chord_label(specified_bass_str) # ベース音もサニタイズ
                    if final_bass_str and final_bass_str.lower() != "rest":
                        cs.bass(final_bass_str)
            except Exception as e_cs:
                logger.error(f"  CV Event {event_idx+1}: Failed to create ChordSymbol from '{final_chord_symbol_str}' (bass: {specified_bass_str}): {e_cs}. Skipping.")
                continue

            if not cs.pitches:
                logger.warning(f"  CV Event {event_idx+1}: ChordSymbol '{cs.figure}' has no pitches. Skipping.")
                continue

            voiced_pitches = self._apply_voicing_style(
                cs,
                voicing_style_name,
                target_octave_for_bottom_note=target_oct,
                num_voices_target=num_voices
            )

            if not voiced_pitches:
                logger.warning(f"  CV Event {event_idx+1}: No pitches after voicing for '{cs.figure}'. Skipping.")
                continue

            notes_for_final_chord = []
            for p_obj in voiced_pitches:
                n = note.Note(p_obj)
                n.volume = m21volume.Volume(velocity=humanized_velocity)
                if humanized_articulation_str:
                    if humanized_articulation_str == "staccato": n.articulations.append(articulations.Staccato())
                    elif humanized_articulation_str == "tenuto": n.articulations.append(articulations.Tenuto())
                    elif humanized_articulation_str == "accented": n.articulations.append(articulations.Accent())
                notes_for_final_chord.append(n)

            if notes_for_final_chord:
                final_chord_obj = m21chord.Chord(notes_for_final_chord, quarterLength=humanized_duration)
                chord_part.insert(abs_offset, final_chord_obj)
                logger.debug(f"  CV: Added {final_chord_obj.pitchedCommonName} ({[p.nameWithOctave for p in final_chord_obj.pitches]}) vel:{humanized_velocity} art:'{humanized_articulation_str}' at {abs_offset:.2f} dur:{humanized_duration:.2f}")
            else:
                logger.warning(f"  CV Event {event_idx+1}: No notes to form a chord for '{cs.figure}'.")

        logger.info(f"CV.compose: Finished. Part '{chord_part.id}' contains {len(list(chord_part.flatten().notesAndRests))} elements.")
        return chord_part

# --- END OF FILE generators/chord_voicer.py ---