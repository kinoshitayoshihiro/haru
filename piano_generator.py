# --- START OF FILE generators/piano_generator.py (修正版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key,
                     chord as m21chord, expressions, volume as m21volume)

import random
import logging

try:
    # ★★★ core_music_utils から sanitize_chord_label をインポート ★★★
    from .core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
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
    # ★★★ フォールバック用の sanitize_chord_label (簡易版) ★★★
    def sanitize_chord_label(label: str) -> str:
        logger.warning(f"Fallback sanitize_chord_label used for '{label}'. May not be fully effective.")
        label = label.replace('maj7', 'M7').replace('mi7', 'm7')
        if label.count('(') > label.count(')') and label.endswith('('):
            label = label[:-1]
        return label
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
        fallback_key = "piano_fallback_block"
        if fallback_key not in self.rhythm_library:
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
            self, m21_cs: Optional[harmony.ChordSymbol], # ★★★ ChordSymbolがNoneの可能性を許容 ★★★
            num_voices_param: Optional[int],
            target_octave_param: int, voicing_style_name: str
    ) -> List[pitch.Pitch]:
        # ★★★ m21_cs が None (Restなど) の場合は空リストを返す ★★★
        if m21_cs is None:
            return []

        final_num_voices_for_voicer = num_voices_param if num_voices_param is not None and num_voices_param > 0 else None
        if self.chord_voicer and hasattr(self.chord_voicer, '_apply_voicing_style'):
            try:
                return self.chord_voicer._apply_voicing_style(
                    m21_cs, voicing_style_name,
                    target_octave_for_bottom_note=target_octave_param,
                    num_voices_target=final_num_voices_for_voicer
                )
            except TypeError as te:
                logger.error(f"PianoGen: TypeError calling ChordVoicer for '{m21_cs.figure}': {te}. Using simple voicing.", exc_info=True)
            except Exception as e_cv:
                 logger.warning(f"PianoGen: Error using ChordVoicer for '{m21_cs.figure}': {e_cv}. Simple voicing.", exc_info=True)
        
        logger.debug(f"PianoGen: Using simple internal voicing for '{m21_cs.figure}'.")
        if not m21_cs.pitches: return [] # ChordSymbolがあってもピッチがない場合
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
            logger.warning(f"PianoGen: Simple voicing for '{m21_cs.figure}': {e_simple}. Raw.", exc_info=True)
            raw_p_list = sorted(list(m21_cs.pitches), key=lambda p_sort: p_sort.ps)
            return raw_p_list[:final_num_voices_for_voicer] if final_num_voices_for_voicer is not None and raw_p_list else raw_p_list if raw_p_list else []

    def _apply_pedal_to_part(self, part_to_apply_pedal: stream.Part, block_offset: float, block_duration: float):
        if block_duration > 0.25:
            pedal_on_expr = expressions.TextExpression("Ped.")
            pedal_off_expr = expressions.TextExpression("*")
            pedal_on_time = block_offset + 0.01
            pedal_off_time = block_offset + block_duration - 0.05
            if pedal_off_time > pedal_on_time:
                part_to_apply_pedal.insert(pedal_on_time, pedal_on_expr)
                part_to_apply_pedal.insert(pedal_off_time, pedal_off_expr)

    def _generate_piano_hand_part_for_block(
            self, hand_LR: str,
            m21_cs_or_rest: Optional[music21.Music21Object], # ★★★ ChordSymbol または Rest を受け取る ★★★
            block_offset_ql: float, block_duration_ql: float,
            hand_specific_params: Dict[str, Any],
            rhythm_library_for_piano: Dict[str, Any]
    ) -> List[Tuple[float, music21.Music21Object]]:
        elements_with_offsets: List[Tuple[float, music21.Music21Object]] = []
        
        rhythm_key = hand_specific_params.get(f"piano_{hand_LR.lower()}_rhythm_key")
        velocity = int(hand_specific_params.get(f"piano_velocity_{hand_LR.lower()}", 64))
        voicing_style = hand_specific_params.get(f"piano_{hand_LR.lower()}_voicing_style", "closed")
        target_octave = int(hand_specific_params.get(f"piano_{hand_LR.lower()}_target_octave", DEFAULT_PIANO_RH_OCTAVE if hand_LR == "RH" else DEFAULT_PIANO_LH_OCTAVE))
        num_voices = hand_specific_params.get(f"piano_{hand_LR.lower()}_num_voices")
        arp_note_ql = float(hand_specific_params.get("piano_arp_note_ql", 0.5))
        perform_style_keyword = hand_specific_params.get(f"piano_{hand_LR.lower()}_style_keyword", "simple_block")

        # ★★★ m21_cs_or_restがRestオブジェクトの場合の処理 ★★★
        if isinstance(m21_cs_or_rest, note.Rest):
            logger.debug(f"Piano{hand_LR} block: Is a Rest for duration {block_duration_ql}. Adding rest.")
            # リズムパターンに基づいて休符を分割するか、ブロック全体を単一の休符にするか
            # ここでは簡略化のため、単一の休符をブロックの先頭に追加
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            elements_with_offsets.append((block_offset_ql, rest_obj))
            return elements_with_offsets
        
        # ★★★ m21_cs_or_rest が None またはピッチを持たないChordSymbolの場合 ★★★
        if not m21_cs_or_rest or not hasattr(m21_cs_or_rest, 'pitches') or not m21_cs_or_rest.pitches:
            logger.warning(f"Piano{hand_LR}: No valid ChordSymbol or pitches provided. Skipping hand part.")
            return []
        
        # この時点で m21_cs_or_rest は有効な ChordSymbol であると仮定できる
        m21_cs: harmony.ChordSymbol = cast(harmony.ChordSymbol, m21_cs_or_rest)

        logger.debug(f"Piano{hand_LR} block: Chord '{m21_cs.figure}', RhythmKey '{rhythm_key}', Style '{perform_style_keyword}'")
        base_voiced_pitches = self._get_piano_chord_pitches(m21_cs, num_voices, target_octave, voicing_style)
        if not base_voiced_pitches:
            logger.warning(f"Piano{hand_LR}: No voiced pitches for {m21_cs.figure}. Skipping."); return []

        rhythm_details = rhythm_library_for_piano.get(rhythm_key)
        if not rhythm_details or "pattern" not in rhythm_details:
            logger.warning(f"Piano{hand_LR}: Rhythm key '{rhythm_key}' invalid. Using fallback 'piano_fallback_block'.")
            rhythm_details = rhythm_library_for_piano.get("piano_fallback_block", {"pattern":[{"offset":0.0, "duration":block_duration_ql, "velocity_factor":0.7}]})
            if not rhythm_details.get("pattern"): logger.error(f"Piano{hand_LR}: Fallback rhythm also missing pattern!"); return []
        pattern_events = rhythm_details.get("pattern", [])

        for event_params in pattern_events:
            # (以降のイベント処理ロジックは前回提示のものをベースに、m21_cs を使用)
            event_offset = float(event_params.get("offset", 0.0))
            event_dur = float(event_params.get("duration", self.global_time_signature_obj.beatDuration.quarterLength))
            event_vf = float(event_params.get("velocity_factor", 1.0))
            abs_start_offset = block_offset_ql + event_offset
            actual_event_duration = min(event_dur, block_duration_ql - event_offset)
            if actual_event_duration < MIN_NOTE_DURATION_QL / 4.0: continue
            current_event_vel = int(velocity * event_vf)

            if hand_LR == "RH" and "arpeggio" in perform_style_keyword.lower() and base_voiced_pitches:
                arp_type = rhythm_details.get("arpeggio_type", "up")
                ordered_arp_pitches: List[pitch.Pitch]
                if arp_type == "down": ordered_arp_pitches = list(reversed(base_voiced_pitches))
                elif "up_down" in arp_type: ordered_arp_pitches = base_voiced_pitches + (list(reversed(base_voiced_pitches[1:-1])) if len(base_voiced_pitches) > 2 else [])
                else: ordered_arp_pitches = base_voiced_pitches
                current_offset_in_arp_event, arp_idx = 0.0, 0
                while current_offset_in_arp_event < actual_event_duration:
                    if not ordered_arp_pitches: break
                    p_arp = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                    single_arp_note_dur = min(arp_note_ql, actual_event_duration - current_offset_in_arp_event)
                    if single_arp_note_dur < MIN_NOTE_DURATION_QL / 4.0: break
                    arp_note_obj = note.Note(p_arp, quarterLength=single_arp_note_dur * 0.95)
                    arp_note_obj.volume = m21volume.Volume(velocity=current_event_vel + random.randint(-2, 2))
                    elements_with_offsets.append((abs_start_offset + current_offset_in_arp_event, arp_note_obj))
                    current_offset_in_arp_event += arp_note_ql; arp_idx += 1
            else:
                pitches_to_play_this_event = []
                if hand_LR == "LH":
                    lh_event_type = event_params.get("type", "root").lower()
                    lh_root_candidate = min(base_voiced_pitches, key=lambda p: p.ps) if base_voiced_pitches else (m21_cs.root() if m21_cs else pitch.Pitch(f"C{DEFAULT_PIANO_LH_OCTAVE}"))
                    if lh_event_type == "root" and lh_root_candidate: pitches_to_play_this_event.append(lh_root_candidate)
                    elif lh_event_type == "octave_root" and lh_root_candidate: pitches_to_play_this_event.extend([lh_root_candidate, lh_root_candidate.transpose(12)])
                    elif lh_event_type == "root_fifth" and lh_root_candidate:
                        pitches_to_play_this_event.append(lh_root_candidate)
                        if m21_cs: # m21_cs が None でないことを確認
                            root_for_fifth = m21_cs.root() or lh_root_candidate
                            fifth_cand = root_for_fifth.transpose(interval.PerfectFifth())
                            fifth_p = pitch.Pitch(fifth_cand.name, octave=lh_root_candidate.octave)
                            if fifth_p.ps < lh_root_candidate.ps + 3 : fifth_p.octave +=1
                            pitches_to_play_this_event.append(fifth_p)
                    elif base_voiced_pitches: pitches_to_play_this_event.append(min(base_voiced_pitches, key=lambda p:p.ps))
                    pitches_to_play_this_event = [p for p in pitches_to_play_this_event if p is not None]
                else: pitches_to_play_this_event = base_voiced_pitches
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

        if not processed_chord_stream: logger.info("PianoGen: Empty stream."); piano_score.extend([piano_rh_part, piano_lh_part]); return piano_score
        logger.info(f"PianoGen: Starting for {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset = float(blk_data.get("offset", 0.0))
            block_dur = float(blk_data.get("q_length", 4.0))
            chord_lbl_original = blk_data.get("chord_label", "C")
            piano_params = blk_data.get("piano_params", {})
            logger.debug(f"Piano Blk {blk_idx+1}: OrigLabel='{chord_lbl_original}', Params: {piano_params}")

            cs_or_rest_obj: Optional[music21.Music21Object] = None # ★★★ 型ヒント変更 ★★★
            sanitized_label = ""
            if chord_lbl_original.lower() in ["rest", "n.c.", "nc"]: # ★★★ "Rest" の処理 ★★★
                cs_or_rest_obj = note.Rest(quarterLength=block_dur) # ブロック全体の休符として一旦作成
                logger.info(f"PianoGen: Block {blk_idx+1} is a Rest.")
            else:
                try:
                    sanitized_label = sanitize_chord_label(chord_lbl_original) # ★★★ ラベルを整形 ★★★
                    cs_or_rest_obj = harmony.ChordSymbol(sanitized_label)
                    if not cs_or_rest_obj.pitches: # ピッチがない場合は警告してRest扱いにするかスキップ
                        logger.warning(f"PianoGen: Chord '{sanitized_label}' (orig: '{chord_lbl_original}') in block {blk_idx+1} has no pitches. Treating as Rest for this block.")
                        cs_or_rest_obj = note.Rest(quarterLength=block_dur)
                except harmony.HarmonyException as he:
                    logger.error(f"PianoGen: HarmonyException for chord '{sanitized_label}' (orig: '{chord_lbl_original}') in block {blk_idx+1}: {he}. Skipping piano for this block.")
                    cs_or_rest_obj = note.Rest(quarterLength=block_dur) # エラーの場合もRestとして扱う
                except Exception as e_cs: # その他の予期せぬエラー
                    logger.error(f"PianoGen: Error creating ChordSymbol for '{sanitized_label}' (orig: '{chord_lbl_original}') in block {blk_idx+1}: {e_cs}. Skipping piano.", exc_info=True)
                    cs_or_rest_obj = note.Rest(quarterLength=block_dur)

            piano_rhythm_lib_patterns = self.rhythm_library # 通常は__init__でpiano_patternsのみに絞り込まれている
            
            # cs_or_rest_obj を渡す
            rh_elems = self._generate_piano_hand_part_for_block("RH", cs_or_rest_obj, block_offset, block_dur, piano_params, piano_rhythm_lib_patterns)
            for off, el in rh_elems: piano_rh_part.insert(off, el)
            
            lh_elems = self._generate_piano_hand_part_for_block("LH", cs_or_rest_obj, block_offset, block_dur, piano_params, piano_rhythm_lib_patterns)
            for off, el in lh_elems: piano_lh_part.insert(off, el)
            
            if piano_params.get("piano_apply_pedal", True) and not isinstance(cs_or_rest_obj, note.Rest): # 休符以外にペダル
                self._apply_pedal_to_part(piano_lh_part, block_offset, block_dur)

        piano_score.append(piano_rh_part); piano_score.append(piano_lh_part)
        logger.info(f"PianoGen: Finished. RH notes: {len(piano_rh_part.flatten().notes)}, LH notes: {len(piano_lh_part.flatten().notes)}")
        return piano_score
# --- END OF FILE generators/piano_generator.py ---
