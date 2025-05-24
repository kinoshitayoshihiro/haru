# --- START OF FILE generators/chord_voicer.py (修正案) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence

# music21のサブモジュールを個別にインポート
from music21 import stream
from music21 import note
from music21 import harmony
from music21 import pitch
from music21 import meter
from music21 import duration
from music21 import instrument as m21instrument # エイリアスを m21instrument に統一
from music21 import interval
from music21 import tempo
from music21 import key
from music21 import chord as m21chord # エイリアスを m21chord に統一 (Chordクラスそのものではなくモジュールとして)
from music21 import volume as m21volume # エイリアスを m21volume に統一
from music21 import expressions # update_imports.py の出力にはなかったが、元コードで使用の可能性あり
# from music21 import dynamics # update_imports.py の出力にあったが、元コードで使用箇所が見当たらないためコメントアウト (必要なら解除)

import random
import logging
import re # sanitize_chord_label のフォールバックで使用

logger = logging.getLogger(__name__)

# --- core_music_utils からのインポート試行 ---
try:
    from .core_music_utils import get_time_signature_object, sanitize_chord_label
    logger.info("ChordVoicer: Successfully imported from .core_music_utils.")
except ImportError as e_import_core:
    try:
        from core_music_utils import get_time_signature_object, sanitize_chord_label
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

        def sanitize_chord_label(label: Optional[str]) -> Optional[str]: # labelをOptional[str]に変更
            logger.warning(f"CV Fallback sanitize_chord_label used for '{label}'. This is a basic version.")
            if label is None: return None # Noneチェックを追加
            label_str = str(label)
            label_str = label_str.replace('maj7', 'M7').replace('mi7', 'm7').replace('min7', 'm7')
            label_str = label_str.replace('Maj7', 'M7').replace('Mi7', 'm7').replace('Min7', 'm7')
            if len(label_str) > 1 and label_str[1] == 'b' and label_str[0] in 'ABCDEFGabcdefg':
                 if not (len(label_str) > 2 and label_str[2].isalpha()):
                    label_str = label_str[0] + '-' + label_str[2:]
            if label_str.count('(') > label_str.count(')') and label_str.endswith('('):
                label_str = label_str[:-1]
            return label_str
        # --- フォールバック定義ここまで ---

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
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except NameError: 
             logger.critical("ChordVoicer __init__: CRITICAL - get_time_signature_object is not defined! Defaulting to basic 4/4.")
             self.global_time_signature_obj = meter.TimeSignature("4/4")
        except Exception as e_ts_init:
            logger.error(f"ChordVoicer __init__: Error initializing time signature from '{global_time_signature}': {e_ts_init}. Defaulting to 4/4.", exc_info=True)
            self.global_time_signature_obj = meter.TimeSignature("4/4")

    def _apply_voicing_style(
            self,
            m21_cs: Optional[harmony.ChordSymbol],
            style_name: str,
            target_octave_for_bottom_note: Optional[int] = DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM,
            num_voices_target: Optional[int] = None
    ) -> List[pitch.Pitch]:

        if m21_cs is None:
            logger.debug("CV._apply_style: ChordSymbol is None. Returning empty list.")
            return []
        if not m21_cs.pitches:
            logger.debug(f"CV._apply_style: ChordSymbol '{m21_cs.figure}' has no pitches. Returning empty list.")
            return []

        voiced_pitches_list: List[pitch.Pitch] = []
        original_closed_pitches = sorted(list(m21_cs.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
        
        if not original_closed_pitches:
            logger.warning(f"CV._apply_style: ChordSymbol '{m21_cs.figure}' resulted in no pitches after closedPosition. Returning empty list.")
            return []

        current_pitches_for_voicing = list(original_closed_pitches)

        try:
            if style_name == VOICING_STYLE_OPEN:
                temp_chord_for_open = m21chord.Chord(current_pitches_for_voicing) # m21chord.Chord を使用
                voiced_pitches_list = list(temp_chord_for_open.openPosition(inPlace=False).pitches)
            elif style_name == VOICING_STYLE_SEMI_CLOSED:
                if len(current_pitches_for_voicing) >= 2:
                    lowest_pitch = current_pitches_for_voicing[0]
                    new_bass_p = lowest_pitch.transpose(-12)
                    voiced_pitches_list = sorted([new_bass_p] + current_pitches_for_voicing[1:], key=lambda p: p.ps)
                else:
                    voiced_pitches_list = current_pitches_for_voicing
            elif style_name == VOICING_STYLE_DROP2:
                if len(current_pitches_for_voicing) >= 2:
                    pitches_copy = list(current_pitches_for_voicing)
                    if len(pitches_copy) >= 4:
                        pitch_to_drop = pitches_copy.pop(-2)
                        dropped_pitch = pitch_to_drop.transpose(-12)
                        voiced_pitches_list = sorted(pitches_copy + [dropped_pitch], key=lambda p: p.ps)
                    elif len(pitches_copy) == 3:
                         pitch_to_drop = pitches_copy.pop(1)
                         dropped_pitch = pitch_to_drop.transpose(-12)
                         voiced_pitches_list = sorted(pitches_copy + [dropped_pitch], key=lambda p:p.ps)
                    else:
                        voiced_pitches_list = current_pitches_for_voicing
                else:
                    voiced_pitches_list = current_pitches_for_voicing
            elif style_name == VOICING_STYLE_FOUR_WAY_CLOSE:
                temp_m21_chord_for_4way = m21chord.Chord(current_pitches_for_voicing) # m21chord.Chord を使用
                if len(temp_m21_chord_for_4way.pitches) >= 4 :
                    try:
                        temp_m21_chord_for_4way.fourWayClose(inPlace=True)
                        voiced_pitches_list = list(temp_m21_chord_for_4way.pitches)
                    except Exception as e_4way:
                        logger.warning(f"CV: fourWayClose for '{m21_cs.figure}' failed: {e_4way}. Defaulting to closed.")
                        voiced_pitches_list = current_pitches_for_voicing
                else:
                    logger.debug(f"CV: Not enough pitches ({len(temp_m21_chord_for_4way.pitches)}) for fourWayClose on {m21_cs.figure}. Using closed.")
                    voiced_pitches_list = current_pitches_for_voicing
            else: 
                if style_name != VOICING_STYLE_CLOSED:
                    logger.debug(f"CV: Unknown style '{style_name}'. Defaulting to closed for '{m21_cs.figure}'.")
                voiced_pitches_list = current_pitches_for_voicing

        except Exception as e_style_app:
            logger.error(f"CV._apply_style: Error applying voicing style '{style_name}' to '{m21_cs.figure}': {e_style_app}. Defaulting to original closed pitches.", exc_info=True)
            voiced_pitches_list = list(original_closed_pitches)

        if not voiced_pitches_list:
            logger.warning(f"CV._apply_style: Voicing style '{style_name}' resulted in empty pitches for '{m21_cs.figure}'. Using original closed pitches.")
            voiced_pitches_list = list(original_closed_pitches)

        if num_voices_target is not None and voiced_pitches_list:
            if len(voiced_pitches_list) > num_voices_target:
                voiced_pitches_list = sorted(voiced_pitches_list, key=lambda p: p.ps)[:num_voices_target]
                logger.debug(f"CV: Reduced voices to {num_voices_target} for '{m21_cs.figure}' (from bottom).")

        if voiced_pitches_list and target_octave_for_bottom_note is not None:
            current_bottom_pitch_obj = min(voiced_pitches_list, key=lambda p: p.ps)
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
        return voiced_pitches_list

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        chord_part = stream.Part(id="ChordVoicerPart")
        try:
            chord_part.insert(0, self.default_instrument)
            chord_part.append(tempo.MetronomeMark(number=self.global_tempo))
            chord_part.append(self.global_time_signature_obj)
        except Exception as e_init_part:
            logger.error(f"CV.compose: Error setting up initial part elements: {e_init_part}", exc_info=True)

        if not processed_chord_stream:
            logger.info("CV.compose: Received empty processed_chord_stream.")
            return chord_part
        logger.info(f"CV.compose: Processing {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            offset_ql = float(blk_data.get("offset", 0.0))
            duration_ql = float(blk_data.get("q_length", 4.0))
            chord_label_original: Optional[str] = blk_data.get("chord_label", "C") # Optional[str] に変更
            
            part_params: Dict[str, Any] = blk_data.get("chords_params", blk_data.get("chord_params", {}))
            voicing_style: str = part_params.get("chord_voicing_style", VOICING_STYLE_CLOSED)
            target_octave: Optional[int] = part_params.get("chord_target_octave")
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
                sanitized_label = sanitize_chord_label(chord_label_original)
                if sanitized_label is None: # sanitize_chord_label が None を返すケース
                    is_block_effectively_rest = True
                    logger.info(f"CV Block {blk_idx+1}: Label '{chord_label_original}' sanitized to Rest.")
                else:
                    try:
                        cs_obj = harmony.ChordSymbol(sanitized_label)
                        if not cs_obj.pitches:
                            logger.info(f"CV: ChordSymbol '{sanitized_label}' (orig: '{chord_label_original}') resulted in no pitches. Treating as Rest.")
                            is_block_effectively_rest = True
                    except music21.harmony.HarmonyException as he:
                        logger.error(f"CV: HarmonyException creating ChordSymbol for '{sanitized_label}' (orig: '{chord_label_original}'): {he}. Treating as Rest.")
                        is_block_effectively_rest = True
                    except Exception as e_cs_create:
                        logger.error(f"CV: General Exception creating ChordSymbol for '{sanitized_label}' (orig: '{chord_label_original}'): {e_cs_create}. Treating as Rest.", exc_info=False)
                        is_block_effectively_rest = True
            
            if is_block_effectively_rest:
                logger.debug(f"CV Block {blk_idx+1}: Handled as Rest. No chord added to part.")
                continue

            if cs_obj is None:
                logger.error(f"CV Block {blk_idx+1}: cs_obj is unexpectedly None for non-Rest label '{chord_label_original}'. Skipping.")
                continue

            tensions_to_add_list: List[str] = blk_data.get("tensions_to_add", [])
            if tensions_to_add_list:
                logger.debug(f"CV: Attempting to add tensions {tensions_to_add_list} to {cs_obj.figure}")
                for tension_str in tensions_to_add_list:
                    try:
                        num_match = re.search(r'(\d+)', tension_str)
                        if num_match:
                            interval_num = int(num_match.group(1))
                            cs_obj.add(interval_num)
                            logger.debug(f"  CV: Added tension based on '{tension_str}' to {cs_obj.figure}")
                        else:
                             logger.warning(f"  CV: Could not parse tension number from '{tension_str}' for {cs_obj.figure}")
                    except Exception as e_add_tension:
                        logger.warning(f"  CV: Error adding tension '{tension_str}' to '{cs_obj.figure}': {e_add_tension}")

            if not cs_obj.pitches:
                logger.warning(f"CV Block {blk_idx+1}: Chord '{cs_obj.figure}' has no pitches after tension additions. Treating as Rest.")
                continue

            final_voiced_pitches = self._apply_voicing_style(
                cs_obj,
                voicing_style,
                target_octave_for_bottom_note=target_octave,
                num_voices_target=num_voices
            )

            if not final_voiced_pitches:
                logger.warning(f"CV Block {blk_idx+1}: No pitches returned after voicing style for '{cs_obj.figure}'. Skipping.")
                continue
            
            new_chord_m21 = m21chord.Chord(final_voiced_pitches) # m21chord.Chord を使用
            new_chord_m21.duration = duration.Duration(duration_ql)
            try:
                vol = m21volume.Volume(velocity=chord_velocity) # m21volume を使用
                notes_for_chord = []
                for p_note in final_voiced_pitches: # 変数名を p_note に変更
                    n = note.Note(p_note)
                    n.volume = vol 
                    notes_for_chord.append(n)
                if notes_for_chord:
                    new_chord_with_velocity = m21chord.Chord(notes_for_chord, quarterLength=duration_ql) # m21chord.Chord を使用
                    chord_part.insert(offset_ql, new_chord_with_velocity)
                    logger.debug(f"  CV: Added chord {new_chord_with_velocity.pitchedCommonName} with vel {chord_velocity} at offset {offset_ql}")
                else:
                    logger.warning(f"CV Block {blk_idx+1}: notes_for_chord was empty after creating notes with velocity.")
            except Exception as e_add_final:
                logger.error(f"CV Block {blk_idx+1}: Error adding final chord for '{cs_obj.figure if cs_obj else 'N/A'}': {e_add_final}", exc_info=True)
        
        logger.info(f"CV.compose: Finished composition. Part contains {len(list(chord_part.flatten().notesAndRests))} elements.")
        return chord_part

# --- END OF FILE generators/chord_voicer.py ---
