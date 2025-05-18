# --- START OF FILE generators/piano_generator.py ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key,
                     chord as m21chord, expressions, volume as m21volume) # volumeをm21volumeとしてインポート

import random
import logging

try:
    from .core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object
except ImportError:
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except meter.MeterException:
            logging.getLogger(__name__).warning(f"Fallback get_time_signature_object: Invalid TS '{ts_str}'. Defaulting to 4/4.")
            return meter.TimeSignature("4/4")
        except Exception as e_ts_fb:
            logging.getLogger(__name__).error(f"Fallback get_time_signature_object: Error for TS '{ts_str}': {e_ts_fb}. Defaulting to 4/4.")
            return meter.TimeSignature("4/4")
    logging.warning("PianoGen: Could not import from .core_music_utils. Using fallbacks.")

logger = logging.getLogger(__name__)

DEFAULT_PIANO_LH_OCTAVE: int = 2
DEFAULT_PIANO_RH_OCTAVE: int = 4

class PianoGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 chord_voicer_instance: Optional[Any] = None,
                 default_instrument_rh=m21instrument.Piano(),
                 default_instrument_lh=m21instrument.Piano(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.rhythm_library = rhythm_library if rhythm_library is not None else {}
        default_piano_key = "default_piano_quarters"
        if default_piano_key not in self.rhythm_library:
             self.rhythm_library[default_piano_key] = {
                 "pattern": [
                     {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.8},
                     {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.75},
                     {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.8},
                     {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.75}
                 ], "description": "Default quarter notes (auto-added)"}
             logger.info(f"PianoGen: Added '{default_piano_key}' to rhythm_library.")
        fallback_key = "piano_fallback_block" # フォールバック用のリズムキー
        if fallback_key not in self.rhythm_library:
            # 拍子オブジェクトから小節長を取得する必要がある
            temp_ts_obj = get_time_signature_object(global_time_signature)
            bar_ql = temp_ts_obj.barDuration.quarterLength
            self.rhythm_library[fallback_key] = {
                "pattern": [{"offset":0.0, "duration": bar_ql, "velocity_factor":0.7}],
                "description": "Fallback single block chord (auto-added)"}
            logger.info(f"PianoGen: Added '{fallback_key}' to rhythm_library.")

        self.chord_voicer = chord_voicer_instance
        if not self.chord_voicer:
            logger.warning("PianoGen: No ChordVoicer. Voicing via basic internal logic.")

        self.instrument_rh = default_instrument_rh
        self.instrument_lh = default_instrument_lh
        self.global_tempo = global_tempo
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _get_piano_chord_pitches(
            self, m21_cs: harmony.ChordSymbol, num_voices_param: Optional[int], # パラメータ名は_paramをつけるなどして区別
            target_octave_param: int, voicing_style_name: str
    ) -> List[pitch.Pitch]:
        # ChordVoicerに渡す最終的な声部数を決定 (Noneなら制限なし、0以下も制限なしとして扱う)
        final_num_voices_for_voicer = num_voices_param if num_voices_param is not None and num_voices_param > 0 else None

        if self.chord_voicer and hasattr(self.chord_voicer, '_apply_voicing_style'):
            try:
                return self.chord_voicer._apply_voicing_style(
                    m21_cs,
                    voicing_style_name,
                    target_octave_for_bottom_note=target_octave_param, # ChordVoicerの定義に合わせる
                    num_voices_target=final_num_voices_for_voicer      # ChordVoicerの定義に合わせる
                )
            except TypeError as te:
                logger.error(f"PianoGen: TypeError calling ChordVoicer for '{m21_cs.figure if m21_cs else 'N/A'}': {te}. "
                             f"Check ChordVoicer._apply_voicing_style args. Using simple voicing.", exc_info=True)
            except Exception as e_cv:
                 logger.warning(f"PianoGen: Error using ChordVoicer for '{m21_cs.figure if m21_cs else 'N/A'}': {e_cv}. Simple voicing.", exc_info=True)
        
        logger.debug(f"PianoGen: Using simple internal voicing for '{m21_cs.figure if m21_cs else 'N/A'}'.")
        if not m21_cs or not m21_cs.pitches: return []
        try:
            temp_chord = m21_cs.closedPosition(inPlace=False)
            if not temp_chord.pitches: return []
            current_bottom = min(temp_chord.pitches, key=lambda p: p.ps)
            root_name = m21_cs.root().name if m21_cs.root() else 'C'
            target_bottom_ps = pitch.Pitch(f"{root_name}{target_octave_param}").ps
            oct_shift = round((target_bottom_ps - current_bottom.ps) / 12.0)
            voiced_pitches = sorted([p.transpose(oct_shift * 12) for p in temp_chord.pitches], key=lambda p: p.ps)
            
            if final_num_voices_for_voicer is not None and len(voiced_pitches) > final_num_voices_for_voicer:
                return voiced_pitches[:final_num_voices_for_voicer]
            return voiced_pitches
        except Exception as e_simple:
            logger.warning(f"PianoGen: Simple voicing for '{m21_cs.figure if m21_cs else 'N/A'}': {e_simple}. Raw.", exc_info=True)
            raw_p_list = sorted(list(m21_cs.pitches), key=lambda p_sort: p_sort.ps)
            return raw_p_list[:final_num_voices_for_voicer] if final_num_voices_for_voicer is not None and raw_p_list else raw_p_list if raw_p_list else []


    def _apply_pedal_to_part(self, part_to_apply_pedal: stream.Part, block_offset: float, block_duration: float):
        # (変更なし)
        if block_duration > 0.25:
            pedal_on_expr = expressions.TextExpression("Ped.")
            pedal_off_expr = expressions.TextExpression("*")
            pedal_on_time = block_offset + 0.01
            pedal_off_time = block_offset + block_duration - 0.05
            if pedal_off_time > pedal_on_time:
                part_to_apply_pedal.insert(pedal_on_time, pedal_on_expr)
                part_to_apply_pedal.insert(pedal_off_time, pedal_off_expr)

    def _generate_piano_hand_part_for_block(
            self, hand_LR: str, # "RH" or "LH"
            m21_cs: harmony.ChordSymbol,
            block_offset_ql: float,
            block_duration_ql: float,
            hand_specific_params: Dict[str, Any],
            rhythm_library_for_piano: Dict[str, Any] # ピアノ用のリズムライブラリカテゴリ
    ) -> List[Tuple[float, music21.Music21Object]]:
        elements_with_offsets: List[Tuple[float, music21.Music21Object]] = []
        
        rhythm_key = hand_specific_params.get(f"piano_{hand_LR.lower()}_rhythm_key")
        velocity = int(hand_specific_params.get(f"piano_velocity_{hand_LR.lower()}", 64))
        voicing_style = hand_specific_params.get(f"piano_{hand_LR.lower()}_voicing_style", "closed")
        target_octave = int(hand_specific_params.get(f"piano_{hand_LR.lower()}_target_octave", DEFAULT_PIANO_RH_OCTAVE if hand_LR == "RH" else DEFAULT_PIANO_LH_OCTAVE))
        num_voices = hand_specific_params.get(f"piano_{hand_LR.lower()}_num_voices") # Optional[int]
        arp_note_ql = float(hand_specific_params.get("piano_arp_note_ql", 0.5)) # RHでのみ主に使われる
        perform_style_keyword = hand_specific_params.get(f"piano_{hand_LR.lower()}_style_keyword", "simple_block")

        logger.debug(f"Piano{hand_LR} block: Chord '{m21_cs.figure}', RhythmKey '{rhythm_key}', StyleKeyword '{perform_style_keyword}'")

        base_voiced_pitches = self._get_piano_chord_pitches(m21_cs, num_voices, target_octave, voicing_style)
        if not base_voiced_pitches:
            logger.warning(f"Piano{hand_LR}: No voiced pitches for {m21_cs.figure}. Skipping hand part.")
            return []

        rhythm_details = rhythm_library_for_piano.get(rhythm_key)
        if not rhythm_details or "pattern" not in rhythm_details:
            logger.warning(f"Piano{hand_LR}: Rhythm key '{rhythm_key}' not found/invalid in piano_patterns. Using fallback 'piano_fallback_block'.")
            rhythm_details = rhythm_library_for_piano.get("piano_fallback_block", {"pattern":[{"offset":0.0, "duration":block_duration_ql, "velocity_factor":0.7}]})
            if not rhythm_details.get("pattern"): # フォールバックも失敗
                 logger.error(f"Piano{hand_LR}: Fallback rhythm 'piano_fallback_block' also missing pattern. Cannot generate notes.")
                 return []


        pattern_events = rhythm_details.get("pattern", [])

        for event_params in pattern_events:
            event_offset = float(event_params.get("offset", 0.0))
            event_dur = float(event_params.get("duration", self.global_time_signature_obj.beatDuration.quarterLength))
            event_vf = float(event_params.get("velocity_factor", 1.0))
            
            abs_start_offset = block_offset_ql + event_offset
            actual_event_duration = min(event_dur, block_duration_ql - event_offset)
            if actual_event_duration < MIN_NOTE_DURATION_QL / 4.0: continue # 短すぎるイベントはスキップ

            current_event_vel = int(velocity * event_vf)

            if hand_LR == "RH" and "arpeggio" in perform_style_keyword.lower() and base_voiced_pitches:
                arp_type = rhythm_details.get("arpeggio_type", "up") # パターン定義からアルペジオタイプ取得
                ordered_arp_pitches: List[pitch.Pitch]
                if arp_type == "down": ordered_arp_pitches = list(reversed(base_voiced_pitches))
                elif "up_down" in arp_type:
                    ordered_arp_pitches = base_voiced_pitches + (list(reversed(base_voiced_pitches[1:-1])) if len(base_voiced_pitches) > 2 else [])
                else: ordered_arp_pitches = base_voiced_pitches

                current_offset_in_arp_event = 0.0
                arp_idx = 0
                while current_offset_in_arp_event < actual_event_duration:
                    if not ordered_arp_pitches: break
                    p_arp = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                    single_arp_note_dur = min(arp_note_ql, actual_event_duration - current_offset_in_arp_event)
                    if single_arp_note_dur < MIN_NOTE_DURATION_QL / 4.0: break
                    
                    arp_note_obj = note.Note(p_arp, quarterLength=single_arp_note_dur * 0.95)
                    arp_note_obj.volume = m21volume.Volume(velocity=current_event_vel + random.randint(-2, 2))
                    elements_with_offsets.append((abs_start_offset + current_offset_in_arp_event, arp_note_obj))
                    
                    current_offset_in_arp_event += arp_note_ql
                    arp_idx += 1
            else: # 通常のコードヒットまたはLHの処理
                pitches_to_play_this_event = []
                if hand_LR == "LH":
                    lh_event_type = event_params.get("type", "root").lower() # LHパターンはtypeを持つ想定
                    if lh_event_type == "root":
                        pitches_to_play_this_event.append(min(base_voiced_pitches, key=lambda p:p.ps) if base_voiced_pitches else base_voiced_pitches[0] if base_voiced_pitches else None)
                    elif lh_event_type == "octave_root" and base_voiced_pitches:
                        lh_base_root = min(base_voiced_pitches, key=lambda p:p.ps)
                        pitches_to_play_this_event.append(lh_base_root)
                        pitches_to_play_this_event.append(lh_base_root.transpose(12))
                    elif lh_event_type == "root_fifth" and base_voiced_pitches:
                        lh_base_root = min(base_voiced_pitches, key=lambda p:p.ps)
                        pitches_to_play_this_event.append(lh_base_root)
                        root_for_fifth = m21_cs.root() or lh_base_root
                        fifth_cand = root_for_fifth.transpose(interval.PerfectFifth())
                        fifth_p = pitch.Pitch(fifth_cand.name, octave=lh_base_root.octave)
                        if fifth_p.ps < lh_base_root.ps + 3 : fifth_p.octave +=1
                        pitches_to_play_this_event.append(fifth_p)
                    else: # Default to single lowest note for LH if specific type not handled
                         if base_voiced_pitches: pitches_to_play_this_event.append(min(base_voiced_pitches, key=lambda p:p.ps))
                    
                    pitches_to_play_this_event = [p for p in pitches_to_play_this_event if p is not None] # Noneを除去

                else: # RH Block Chords
                    pitches_to_play_this_event = base_voiced_pitches

                if pitches_to_play_this_event:
                    element: music21.Music21Object
                    if len(pitches_to_play_this_event) == 1:
                        element = note.Note(pitches_to_play_this_event[0], quarterLength=actual_event_duration * 0.9)
                        element.volume = m21volume.Volume(velocity=current_event_vel)
                    else:
                        element = m21chord.Chord(pitches_to_play_this_event, quarterLength=actual_event_duration * 0.9)
                        for n_chord in element: n_chord.volume = m21volume.Volume(velocity=current_event_vel)
                    elements_with_offsets.append((abs_start_offset, element))
        return elements_with_offsets

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Score:
        piano_score = stream.Score(id="PianoScore")
        piano_rh_part = stream.Part(id="PianoRH"); piano_rh_part.insert(0, self.instrument_rh)
        piano_lh_part = stream.Part(id="PianoLH"); piano_lh_part.insert(0, self.instrument_lh)
        piano_score.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        piano_score.insert(0, self.global_time_signature_obj)

        if not processed_chord_stream: logger.info("PianoGen: Empty stream."); piano_score.append([piano_rh_part, piano_lh_part]); return piano_score
        logger.info(f"PianoGen: Starting for {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset = float(blk_data.get("offset", 0.0))
            block_dur = float(blk_data.get("q_length", 4.0))
            chord_lbl = blk_data.get("chord_label", "C")
            piano_params = blk_data.get("piano_params", {})
            logger.debug(f"Piano Blk {blk_idx+1}: '{chord_lbl}', Offset {block_offset:.2f}, Params: {piano_params}")
            try:
                cs = harmony.ChordSymbol(chord_lbl)
                if not cs.pitches: logger.warning(f"PianoGen: No pitches for {chord_lbl}."); continue
                
                # ピアノ用のリズムライブラリのカテゴリを渡す
                piano_rhythm_patterns = self.rhythm_library # __init__でpiano_patternsに絞られている想定
                
                rh_elems = self._generate_piano_hand_part_for_block("RH", cs, block_offset, block_dur, piano_params, piano_rhythm_patterns)
                for off, el in rh_elems: piano_rh_part.insert(off, el)
                
                lh_elems = self._generate_piano_hand_part_for_block("LH", cs, block_offset, block_dur, piano_params, piano_rhythm_patterns)
                for off, el in lh_elems: piano_lh_part.insert(off, el)
                
                if piano_params.get("piano_apply_pedal", True): # デフォルトTrueに
                    self._apply_pedal_to_part(piano_lh_part, block_offset, block_dur)
            except harmony.HarmonyException as he: logger.error(f"PianoGen: HarmonyEx for {chord_lbl} (blk {blk_idx+1}): {he}")
            except Exception as e: logger.error(f"PianoGen: Error in blk {blk_idx+1} ('{chord_lbl}'): {e}", exc_info=True)

        piano_score.append(piano_rh_part); piano_score.append(piano_lh_part)
        logger.info(f"PianoGen: Finished. RH notes: {len(piano_rh_part.flatten().notes)}, LH notes: {len(piano_lh_part.flatten().notes)}")
        return piano_score
# --- END OF FILE generators/piano_generator.py ---
