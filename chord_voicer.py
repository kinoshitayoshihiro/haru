# --- START OF FILE generators/chord_voicer.py ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, interval, tempo, key,
                     chord as m21chord, volume as m21volume)
import random
import logging

logger = logging.getLogger(__name__)

DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM: int = 3
VOICING_STYLE_CLOSED = "closed"
VOICING_STYLE_OPEN = "open"
VOICING_STYLE_SEMI_CLOSED = "semi_closed"
VOICING_STYLE_DROP2 = "drop2"
VOICING_STYLE_FOUR_WAY_CLOSE = "four_way_close"

class ChordVoicer:
    def __init__(self,
                 default_instrument=m21instrument.StringInstrument(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        try:
            from .core_music_utils import get_time_signature_object # Try to use central util
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except ImportError:
            logger.warning("ChordVoicer: core_music_utils.get_time_signature_object not found. Using direct meter.TimeSignature.")
            try:
                self.global_time_signature_obj = meter.TimeSignature(global_time_signature)
            except meter.MeterException:
                logger.error(f"ChordVoicer: Invalid global TS '{global_time_signature}'. Defaulting to 4/4.")
                self.global_time_signature_obj = meter.TimeSignature("4/4")


    def _apply_voicing_style(
            self,
            m21_cs: harmony.ChordSymbol,
            style_name: str,
            target_octave_for_bottom_note: Optional[int] = DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM,
            num_voices_target: Optional[int] = None
    ) -> List[pitch.Pitch]:
        if not m21_cs.pitches:
            logger.warning(f"ChordVoicer._apply_style: ChordSymbol '{m21_cs.figure}' has no pitches.")
            return []

        voiced_pitches_list: List[pitch.Pitch] = []
        original_pitches_sorted = sorted(list(m21_cs.pitches), key=lambda p: p.ps)
        temp_cs_for_voicing = harmony.ChordSymbol(m21_cs.figure) # 操作用コピー

        try:
            if style_name == VOICING_STYLE_OPEN:
                voiced_pitches_list = list(temp_cs_for_voicing.openPosition(inPlace=False).pitches)
            elif style_name == VOICING_STYLE_SEMI_CLOSED:
                closed_p = sorted(list(temp_cs_for_voicing.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
                if len(closed_p) >= 2:
                    bass_of_cs = temp_cs_for_voicing.bass()
                    if bass_of_cs and closed_p[0].name == bass_of_cs.name:
                        new_bass_p = closed_p[0].transpose(-12)
                        voiced_pitches_list = sorted([new_bass_p] + closed_p[1:], key=lambda p: p.ps)
                    else: voiced_pitches_list = closed_p
                else: voiced_pitches_list = closed_p
            elif style_name == VOICING_STYLE_DROP2:
                closed_for_drop2 = sorted(list(temp_cs_for_voicing.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
                if len(closed_for_drop2) >= 2:
                    idx_to_drop = -1
                    if len(closed_for_drop2) >= 4: idx_to_drop = -2
                    elif len(closed_for_drop2) == 3: idx_to_drop = 1
                    if idx_to_drop != -1 :
                        pitches_copy = list(closed_for_drop2); pitch_to_drop_obj = pitches_copy.pop(idx_to_drop)
                        dropped_pitch_obj = pitch_to_drop_obj.transpose(-12)
                        voiced_pitches_list = sorted(pitches_copy + [dropped_pitch_obj], key=lambda p: p.ps)
                    else: voiced_pitches_list = closed_for_drop2
                else: voiced_pitches_list = closed_for_drop2
            elif style_name == VOICING_STYLE_FOUR_WAY_CLOSE:
                temp_m21_chord = m21chord.Chord(temp_cs_for_voicing.pitches)
                if len(temp_m21_chord.pitches) >= 4 :
                    try: temp_m21_chord.fourWayClose(inPlace=True); voiced_pitches_list = list(temp_m21_chord.pitches)
                    except Exception as e_4way: logger.warning(f"CV: fourWayClose for {temp_cs_for_voicing.figure} failed: {e_4way}. Defaulting."); voiced_pitches_list = list(temp_cs_for_voicing.closedPosition(inPlace=False).pitches)
                else: logger.debug(f"CV: Not enough pitches for fourWayClose on {temp_cs_for_voicing.figure}. Using closed."); voiced_pitches_list = list(temp_cs_for_voicing.closedPosition(inPlace=False).pitches)
            else:
                if style_name != VOICING_STYLE_CLOSED: logger.debug(f"CV: Unknown style '{style_name}'. Defaulting to closed for {temp_cs_for_voicing.figure}.")
                voiced_pitches_list = list(temp_cs_for_voicing.closedPosition(inPlace=False).pitches)
        except Exception as e_style_app:
            logger.error(f"CV._apply_style: Error applying '{style_name}' to '{m21_cs.figure}': {e_style_app}. Defaulting.", exc_info=True)
            voiced_pitches_list = original_pitches_sorted

        if not voiced_pitches_list: voiced_pitches_list = original_pitches_sorted

        if num_voices_target is not None and voiced_pitches_list:
            if len(voiced_pitches_list) > num_voices_target:
                # 簡易的に低い方から指定数取得（より洗練されたロジックも検討可）
                voiced_pitches_list = sorted(voiced_pitches_list, key=lambda p:p.ps)[:num_voices_target]
                logger.debug(f"CV: Reduced voices to {num_voices_target} for '{m21_cs.figure}'.")

        if voiced_pitches_list and target_octave_for_bottom_note is not None:
            current_bottom_p = min(voiced_pitches_list, key=lambda p: p.ps)
            ref_p_name = m21_cs.root().name if m21_cs.root() else 'C'
            target_bottom_ps_val = pitch.Pitch(f"{ref_p_name}{target_octave_for_bottom_note}").ps
            oct_diff = round((target_bottom_ps_val - current_bottom_p.ps) / 12.0)
            shift_semitones = int(oct_diff * 12)
            if shift_semitones != 0:
                logger.debug(f"CV: Shifting '{m21_cs.figure}' by {shift_semitones} semitones for target bottom octave {target_octave_for_bottom_note}.")
                try: voiced_pitches_list = [p.transpose(shift_semitones) for p in voiced_pitches_list]
                except Exception as e_trans: logger.error(f"CV: Error transposing for octave adjustment: {e_trans}")
        return voiced_pitches_list

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        chord_part = stream.Part(id="ChordVoicerPart")
        chord_part.insert(0, self.default_instrument)
        chord_part.append(tempo.MetronomeMark(number=self.global_tempo))
        chord_part.append(self.global_time_signature_obj)

        if not processed_chord_stream: logger.info("CV.compose: Empty stream."); return chord_part
        logger.info(f"CV.compose: Processing {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            offset_ql = float(blk_data.get("offset", 0.0))
            duration_ql = float(blk_data.get("q_length", 4.0))
            chord_label = blk_data.get("chord_label", "C")
            
            # modular_composerから渡される "chords_params" (または "chord_params") を期待
            part_params = blk_data.get("chords_params", blk_data.get("chord_params", {}))

            voicing_style = part_params.get("chord_voicing_style", VOICING_STYLE_CLOSED)
            target_octave = part_params.get("chord_target_octave", DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM)
            num_voices = part_params.get("chord_num_voices") # Optional
            chord_velocity = int(part_params.get("chord_velocity", 64))

            logger.debug(f"CV Block {blk_idx+1}: {chord_label}, Style:{voicing_style}, Oct:{target_octave}, Voices:{num_voices}")
            try:
                cs = harmony.ChordSymbol(chord_label)
                tensions = blk_data.get("tensions_to_add", [])
                if tensions:
                    for t_str in tensions:
                        try: cs.addCustomModification(t_str) # 柔軟なテンション追加
                        except Exception as e_add_tens: logger.warning(f"CV: Tension '{t_str}' to '{cs.figure}' failed: {e_add_tens}")
                
                if not cs.pitches: logger.warning(f"CV: No pitches for {chord_label}. Skip."); continue

                final_pitches = self._apply_voicing_style(
                    cs, voicing_style,
                    target_octave_for_bottom_note=target_octave, # メソッド定義に合わせる
                    num_voices_target=num_voices                 # メソッド定義に合わせる
                )
                if not final_pitches: logger.warning(f"CV: No pitches after voicing for {chord_label}. Skip."); continue
                
                if final_pitches:
                    chord_m21 = m21chord.Chord(final_pitches, quarterLength=duration_ql)
                    for n_in_c in chord_m21: n_in_c.volume = m21volume.Volume(velocity=chord_velocity)
                    chord_part.insert(offset_ql, chord_m21)
            except harmony.HarmonyException as he: logger.error(f"CV: HarmonyEx for '{chord_label}': {he}")
            except Exception as e_cv_blk: logger.error(f"CV.compose: Error in block {blk_idx+1} ('{chord_label}'): {e_cv_blk}", exc_info=True)
        
        logger.info(f"CV.compose: Finished. Part has {len(chord_part.flatten().notesAndRests)} elements.")
        return chord_part
# --- END OF FILE generators/chord_voicer.py ---
