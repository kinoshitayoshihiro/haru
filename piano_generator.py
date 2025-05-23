# --- START OF FILE generators/piano_generator.py (2023-05-22 修正案) ---
from typing import cast, List, Dict, Optional, Tuple, Any, Sequence
import music21
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key,
                     chord as m21chord, expressions, volume as m21volume)
import random
import logging

try:
    from .core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
except ImportError:
    # --- Fallback definitions if core_music_utils is not found ---
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("PianoGen: Could not import from .core_music_utils. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125

    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except meter.MeterException:
            logger_fallback.warning(f"Fallback get_time_signature_object: Invalid TS '{ts_str}'. Defaulting to 4/4.")
            return meter.TimeSignature("4/4")
        except Exception as e_ts_fb:
            logger_fallback.error(f"Fallback get_time_signature_object: Error for TS '{ts_str}': {e_ts_fb}. Defaulting to 4/4.")
            return meter.TimeSignature("4/4")

    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: # Fallback sanitize_chord_label
        if not label or not isinstance(label, str) or label.strip().lower() in ["rest", "n.c.", "nc", "none"]:
            return None
        label_out = label.strip().replace('maj7', 'M7').replace('mi7', 'm7').replace('ø7', 'm7b5')
        if label_out.count('(') > label_out.count(')') and label_out.endswith('('):
            label_out = label_out[:-1]
        # Very basic check, music21 will handle more complex cases or fail
        try:
            harmony.ChordSymbol(label_out)
            return label_out
        except Exception:
            logger_fallback.warning(f"Fallback sanitize_chord_label used for '{label}', result '{label_out}' may not be fully effective or parseable.")
            # Try original if sanitized fails
            try:
                harmony.ChordSymbol(label)
                return label
            except Exception:
                logger_fallback.error(f"Fallback sanitize_chord_label: Neither sanitized '{label_out}' nor original '{label}' parseable. Returning None.")
                return None
    # --- End of Fallback definitions ---

logger = logging.getLogger(__name__)

DEFAULT_PIANO_LH_OCTAVE: int = 2
DEFAULT_PIANO_RH_OCTAVE: int = 4

class PianoGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None, # This should be piano_patterns from rhythm_library.json
                 chord_voicer_instance: Optional[Any] = None,
                 default_instrument_rh=m21instrument.Piano(),
                 default_instrument_lh=m21instrument.Piano(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.rhythm_library = rhythm_library if rhythm_library is not None else {}
        # Ensure default rhythms exist
        default_piano_key = "default_piano_quarters"
        if default_piano_key not in self.rhythm_library:
             self.rhythm_library[default_piano_key] = {
                 "pattern": [
                     {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.8},
                     {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.75},
                     {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.8},
                     {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.75}
                 ], "description": "Default quarter notes (auto-added)"}
             logger.info(f"PianoGen: Added '{default_piano_key}' to rhythm_library as it was missing.")

        fallback_key = "piano_fallback_block" # Used if a specific rhythm_key is invalid
        if fallback_key not in self.rhythm_library:
            temp_ts_obj_init = get_time_signature_object(global_time_signature)
            bar_ql_init = temp_ts_obj_init.barDuration.quarterLength
            self.rhythm_library[fallback_key] = {
                "pattern": [{"offset":0.0, "duration": bar_ql_init, "velocity_factor":0.7}],
                "description": "Fallback single block chord (auto-added)"}
            logger.info(f"PianoGen: Added '{fallback_key}' to rhythm_library as it was missing.")

        self.chord_voicer = chord_voicer_instance
        if not self.chord_voicer:
            logger.warning("PianoGen: No ChordVoicer instance provided. Voicing will use basic internal logic.")

        self.instrument_rh = default_instrument_rh
        self.instrument_lh = default_instrument_lh
        self.global_tempo = global_tempo
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _get_piano_chord_pitches(
            self, m21_cs: Optional[harmony.ChordSymbol],
            num_voices_param: Optional[int],
            target_octave_param: int, voicing_style_name: str
    ) -> List[pitch.Pitch]:
        if m21_cs is None or not m21_cs.pitches: # If it's a Rest or ChordSymbol without pitches
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
        
        # Fallback simple voicing if ChordVoicer is not available or fails
        logger.debug(f"PianoGen: Using simple internal voicing for '{m21_cs.figure}'.")
        try:
            temp_chord = m21_cs.closedPosition(inPlace=False)
            if not temp_chord.pitches: return []
            
            current_bottom = min(temp_chord.pitches, key=lambda p: p.ps)
            root_name = m21_cs.root().name if m21_cs.root() else 'C' # Default to C if root is somehow None
            target_bottom_ps = pitch.Pitch(f"{root_name}{target_octave_param}").ps
            
            oct_shift = round((target_bottom_ps - current_bottom.ps) / 12.0)
            voiced_pitches = sorted([p.transpose(oct_shift * 12) for p in temp_chord.pitches], key=lambda p: p.ps)
            
            if final_num_voices_for_voicer is not None and len(voiced_pitches) > final_num_voices_for_voicer:
                # If too many voices, take from bottom up to num_voices_target
                return voiced_pitches[:final_num_voices_for_voicer]
            return voiced_pitches
        except Exception as e_simple:
            logger.warning(f"PianoGen: Simple voicing for '{m21_cs.figure}' failed: {e_simple}. Returning raw pitches.", exc_info=True)
            # As a last resort, return raw pitches sorted, possibly truncated
            raw_p_list = sorted(list(m21_cs.pitches), key=lambda p_sort: p_sort.ps)
            if final_num_voices_for_voicer is not None and raw_p_list:
                return raw_p_list[:final_num_voices_for_voicer]
            return raw_p_list if raw_p_list else []

    def _apply_pedal_to_part(self, part_to_apply_pedal: stream.Part, block_offset: float, block_duration: float):
        if block_duration > 0.25: # Only apply pedal for reasonably long blocks
            pedal_on_expr = expressions.TextExpression("Ped.")
            pedal_off_expr = expressions.TextExpression("*")
            
            # Ensure pedal on/off times are within the block and sensible
            pedal_on_time = block_offset + 0.01 
            pedal_off_time = block_offset + block_duration - 0.05 
            
            if pedal_off_time > pedal_on_time:
                part_to_apply_pedal.insert(pedal_on_time, pedal_on_expr)
                part_to_apply_pedal.insert(pedal_off_time, pedal_off_expr)

    def _generate_piano_hand_part_for_block(
            self, hand_LR: str,
            m21_cs_or_rest: Optional[music21.Music21Object],
            block_offset_ql: float, block_duration_ql: float,
            hand_specific_params: Dict[str, Any], # Parameters specific to this hand for this block
            rhythm_patterns_for_piano: Dict[str, Any] # The "piano_patterns" dict from rhythm_library
    ) -> List[Tuple[float, music21.Music21Object]]:
        
        elements_with_offsets: List[Tuple[float, music21.Music21Object]] = []
        
        # Get parameters for the current hand, falling back to defaults if not specified
        # These keys should match what modular_composer.py's translate_keywords_to_params sets
        rhythm_key = hand_specific_params.get(f"piano_{hand_LR.lower()}_rhythm_key")
        velocity = int(hand_specific_params.get(f"piano_velocity_{hand_LR.lower()}", 64))
        voicing_style = hand_specific_params.get(f"piano_{hand_LR.lower()}_voicing_style", "closed")
        target_octave = int(hand_specific_params.get(f"piano_{hand_LR.lower()}_target_octave", 
                                                     DEFAULT_PIANO_RH_OCTAVE if hand_LR == "RH" else DEFAULT_PIANO_LH_OCTAVE))
        num_voices = hand_specific_params.get(f"piano_{hand_LR.lower()}_num_voices") # Can be None
        arp_note_ql = float(hand_specific_params.get("piano_arp_note_ql", 0.5)) # Used if arpeggio style
        perform_style_keyword = hand_specific_params.get(f"piano_{hand_LR.lower()}_style_keyword", "simple_block") # For arpeggio check

        # Handle Rest objects
        if isinstance(m21_cs_or_rest, note.Rest):
            logger.debug(f"Piano {hand_LR} block: Is a Rest for duration {block_duration_ql}. Adding a single rest.")
            # For simplicity, add a single rest for the block duration.
            # Could be enhanced to use rhythm_key to create rhythmic rests if needed.
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            elements_with_offsets.append((block_offset_ql, rest_obj))
            return elements_with_offsets
        
        # Ensure we have a valid ChordSymbol object at this point
        if not m21_cs_or_rest or not isinstance(m21_cs_or_rest, harmony.ChordSymbol) or not m21_cs_or_rest.pitches:
            logger.warning(f"Piano {hand_LR}: No valid ChordSymbol or pitches provided for block at offset {block_offset_ql}. Skipping hand part for this block.")
            # Add a rest for the block duration if no valid chord
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            elements_with_offsets.append((block_offset_ql, rest_obj))
            return elements_with_offsets
        
        m21_cs: harmony.ChordSymbol = cast(harmony.ChordSymbol, m21_cs_or_rest)

        logger.debug(f"Piano {hand_LR} block: Chord '{m21_cs.figure}', RhythmKey '{rhythm_key}', Style '{perform_style_keyword}'")
        
        base_voiced_pitches = self._get_piano_chord_pitches(m21_cs, num_voices, target_octave, voicing_style)
        if not base_voiced_pitches:
            logger.warning(f"Piano {hand_LR}: No voiced pitches for {m21_cs.figure} at offset {block_offset_ql}. Skipping hand part.")
            rest_obj = note.Rest(quarterLength=block_duration_ql) # Add rest if voicing fails
            elements_with_offsets.append((block_offset_ql, rest_obj))
            return elements_with_offsets

        rhythm_details = rhythm_patterns_for_piano.get(rhythm_key if rhythm_key else "") # Handle None rhythm_key
        if not rhythm_details or "pattern" not in rhythm_details:
            logger.warning(f"Piano {hand_LR}: Rhythm key '{rhythm_key}' invalid or pattern missing. Using fallback 'piano_fallback_block'.")
            rhythm_details = rhythm_patterns_for_piano.get("piano_fallback_block")
            if not rhythm_details or "pattern" not in rhythm_details: # Fallback for the fallback
                logger.error(f"Piano {hand_LR}: Fallback rhythm 'piano_fallback_block' also missing pattern! Cannot generate notes.")
                rest_obj = note.Rest(quarterLength=block_duration_ql)
                elements_with_offsets.append((block_offset_ql, rest_obj))
                return elements_with_offsets
        
        pattern_events = rhythm_details.get("pattern", [])

        for event_params in pattern_events:
            event_offset_in_pattern = float(event_params.get("offset", 0.0))
            event_duration_in_pattern = float(event_params.get("duration", self.global_time_signature_obj.beatDuration.quarterLength))
            event_velocity_factor = float(event_params.get("velocity_factor", 1.0))
            
            # Calculate absolute start time and actual duration for this event within the block
            abs_event_start_offset_ql = block_offset_ql + event_offset_in_pattern
            
            # Ensure event does not exceed block boundary
            # Max possible duration for this event is from its start to the end of the block
            max_event_duration_ql = block_duration_ql - event_offset_in_pattern
            actual_event_duration_ql = min(event_duration_in_pattern, max_event_duration_ql)

            if actual_event_duration_ql < MIN_NOTE_DURATION_QL / 4.0: # Too short to play
                continue

            current_event_velocity = int(velocity * event_velocity_factor)

            # Arpeggio for RH
            if hand_LR == "RH" and "arpeggio" in perform_style_keyword.lower() and base_voiced_pitches:
                arp_type = rhythm_details.get("arpeggio_type", "up") # Get from rhythm pattern if specified
                ordered_arp_pitches: List[pitch.Pitch]
                if arp_type == "down": ordered_arp_pitches = list(reversed(base_voiced_pitches))
                elif "up_down" in arp_type: 
                    ordered_arp_pitches = base_voiced_pitches + (list(reversed(base_voiced_pitches[1:-1])) if len(base_voiced_pitches) > 2 else [])
                else: # Default to "up"
                    ordered_arp_pitches = base_voiced_pitches
                
                current_offset_in_arp_event = 0.0
                arp_idx = 0
                while current_offset_in_arp_event < actual_event_duration_ql:
                    if not ordered_arp_pitches: break # Should not happen if base_voiced_pitches is not empty
                    
                    p_arp = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                    single_arp_note_actual_dur = min(arp_note_ql, actual_event_duration_ql - current_offset_in_arp_event)
                    
                    if single_arp_note_actual_dur < MIN_NOTE_DURATION_QL / 4.0: break
                    
                    # Apply a slight staccato (0.95 factor) to arpeggiated notes for clarity
                    arp_note_obj = note.Note(p_arp, quarterLength=single_arp_note_actual_dur * 0.95)
                    arp_note_obj.volume = m21volume.Volume(velocity=current_event_velocity + random.randint(-3, 3)) # Slight velocity variation
                    elements_with_offsets.append((abs_event_start_offset_ql + current_offset_in_arp_event, arp_note_obj))
                    
                    current_offset_in_arp_event += arp_note_ql # Use the defined arp_note_ql for stepping
                    arp_idx += 1
            
            # Block chords or single notes (for LH or non-arpeggio RH)
            else:
                pitches_to_play_this_event: List[pitch.Pitch] = []
                if hand_LR == "LH":
                    lh_event_type = event_params.get("type", "root").lower() # Get from rhythm pattern
                    lh_root_candidate = min(base_voiced_pitches, key=lambda p: p.ps) if base_voiced_pitches else (m21_cs.root() if m21_cs else pitch.Pitch(f"C{DEFAULT_PIANO_LH_OCTAVE}"))

                    if lh_event_type == "root" and lh_root_candidate: 
                        pitches_to_play_this_event.append(lh_root_candidate)
                    elif lh_event_type == "octave_root" and lh_root_candidate: 
                        pitches_to_play_this_event.extend([lh_root_candidate, lh_root_candidate.transpose(12)])
                    elif lh_event_type == "root_fifth" and lh_root_candidate:
                        pitches_to_play_this_event.append(lh_root_candidate)
                        root_for_fifth = m21_cs.root() or lh_root_candidate # Ensure we have a root
                        fifth_cand = root_for_fifth.transpose(interval.PerfectFifth())
                        # Try to place fifth in a reasonable octave relative to the root
                        fifth_p = pitch.Pitch(fifth_cand.name, octave=lh_root_candidate.octave)
                        if fifth_p.ps < lh_root_candidate.ps + 3 : fifth_p.octave +=1 # Ensure fifth is above or close
                        pitches_to_play_this_event.append(fifth_p)
                    elif base_voiced_pitches: # Default to playing the lowest voiced pitch for LH if type is unknown
                        pitches_to_play_this_event.append(min(base_voiced_pitches, key=lambda p:p.ps))
                    
                    pitches_to_play_this_event = [p for p in pitches_to_play_this_event if p is not None] # Filter out Nones
                else: # Right Hand (non-arpeggio)
                    pitches_to_play_this_event = base_voiced_pitches

                if pitches_to_play_this_event:
                    element_to_add: music21.Music21Object
                    # Apply a slight staccato (0.9 factor) for block chords/notes
                    actual_play_duration = actual_event_duration_ql * 0.9 
                    if len(pitches_to_play_this_event) == 1:
                        element_to_add = note.Note(pitches_to_play_this_event[0], quarterLength=actual_play_duration)
                        element_to_add.volume = m21volume.Volume(velocity=current_event_velocity)
                    else:
                        element_to_add = m21chord.Chord(pitches_to_play_this_event, quarterLength=actual_play_duration)
                        for n_in_chord in element_to_add: # Set velocity for each note in the chord
                            n_in_chord.volume = m21volume.Volume(velocity=current_event_velocity)
                    elements_with_offsets.append((abs_event_start_offset_ql, element_to_add))
        
        return elements_with_offsets

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Score:
        piano_score = stream.Score(id="PianoScore")
        piano_rh_part = stream.Part(id="PianoRH"); piano_rh_part.insert(0, self.instrument_rh)
        piano_lh_part = stream.Part(id="PianoLH"); piano_lh_part.insert(0, self.instrument_lh)
        
        # Add tempo and time signature to the score (and parts if necessary, though score is usually enough)
        piano_score.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        piano_score.insert(0, self.global_time_signature_obj)
        # Optionally, add to parts too if issues with MIDI export, but generally not needed
        # piano_rh_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        # piano_rh_part.insert(0, self.global_time_signature_obj.clone()) # clone to avoid issues
        # piano_lh_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        # piano_lh_part.insert(0, self.global_time_signature_obj.clone())

        if not processed_chord_stream:
            logger.info("PianoGen: Empty processed_chord_stream. Returning empty piano score.")
            piano_score.append(piano_rh_part)
            piano_score.append(piano_lh_part)
            return piano_score
            
        logger.info(f"PianoGen: Starting composition for {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset = float(blk_data.get("offset", 0.0))
            block_dur = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            chord_lbl_original = blk_data.get("chord_label", "C") # Default to C if no label
            
            # Parameters for piano for this specific block, derived by modular_composer
            piano_params_for_block = blk_data.get("part_params", {}).get("piano", {})
            
            logger.debug(f"Piano Blk {blk_idx+1}: Offset={block_offset}, Dur={block_dur}, OrigLabel='{chord_lbl_original}', Params: {piano_params_for_block}")

            cs_or_rest_obj: Optional[music21.Music21Object] = None
            
            # Sanitize and create ChordSymbol or Rest object
            # sanitize_chord_label should return None for rests or unparseable chords
            sanitized_label_for_cs = sanitize_chord_label(chord_lbl_original)

            if sanitized_label_for_cs is None: # Indicates a rest or unparseable chord
                cs_or_rest_obj = note.Rest(quarterLength=block_dur)
                logger.info(f"PianoGen: Block {blk_idx+1} (orig: '{chord_lbl_original}') is a Rest or unparseable. Duration: {block_dur}")
            else:
                try:
                    cs_or_rest_obj = harmony.ChordSymbol(sanitized_label_for_cs)
                    if not cs_or_rest_obj.pitches: # Double check for pitches after parsing
                        logger.warning(f"PianoGen: Chord '{sanitized_label_for_cs}' (orig: '{chord_lbl_original}') in block {blk_idx+1} parsed but has no pitches. Treating as Rest.")
                        cs_or_rest_obj = note.Rest(quarterLength=block_dur)
                except harmony.HarmonyException as he:
                    logger.error(f"PianoGen: HarmonyException for chord '{sanitized_label_for_cs}' (orig: '{chord_lbl_original}') in block {blk_idx+1}: {he}. Treating as Rest.")
                    cs_or_rest_obj = note.Rest(quarterLength=block_dur)
                except Exception as e_cs:
                    logger.error(f"PianoGen: Unexpected error creating ChordSymbol for '{sanitized_label_for_cs}' (orig: '{chord_lbl_original}') in block {blk_idx+1}: {e_cs}. Treating as Rest.", exc_info=True)
                    cs_or_rest_obj = note.Rest(quarterLength=block_dur)
            
            # piano_patterns_from_lib is self.rhythm_library (passed during __init__)
            rh_elems = self._generate_piano_hand_part_for_block(
                "RH", cs_or_rest_obj, block_offset, block_dur, 
                piano_params_for_block, self.rhythm_library
            )
            for off, el in rh_elems: piano_rh_part.insert(off, el)
            
            lh_elems = self._generate_piano_hand_part_for_block(
                "LH", cs_or_rest_obj, block_offset, block_dur, 
                piano_params_for_block, self.rhythm_library
            )
            for off, el in lh_elems: piano_lh_part.insert(off, el)
            
            # Apply pedal if specified and not a rest block
            if piano_params_for_block.get("piano_apply_pedal", True) and not isinstance(cs_or_rest_obj, note.Rest):
                # Apply pedal to LH part as it often carries the harmonic foundation
                self._apply_pedal_to_part(piano_lh_part, block_offset, block_dur)

        piano_score.append(piano_rh_part)
        piano_score.append(piano_lh_part)
        
        # Clean up parts (remove overlaps, sort, etc.) - music21 often handles this, but explicit can be good
        # piano_rh_part.makeMeasures(inPlace=True) # Optional: structure into measures
        # piano_lh_part.makeMeasures(inPlace=True) # Optional
        # piano_score.stripTies(inPlace=True) # Optional: if ties are causing issues

        logger.info(f"PianoGen: Finished composition. RH elements: {len(piano_rh_part.flatten().notesAndRests)}, LH elements: {len(piano_lh_part.flatten().notesAndRests)}")
        return piano_score

# --- END OF FILE generators/piano_generator.py ---
