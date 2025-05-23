# --- START OF FILE generators/piano_generator.py (2023-05-23 統合・強化版) ---
from typing import cast, List, Dict, Optional, Tuple, Any, Sequence, Union
import music21
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key,
                     chord as m21chord, expressions, volume as m21volume, exceptions21)
import random
import logging
import numpy as np # For fractional noise
import copy      # For deepcopy

try:
    from .core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
except ImportError:
    # --- Fallback definitions ---
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("PianoGen: Could not import from .core_music_utils. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except meter.MeterException:
            logger_fallback.warning(f"Fallback GTSO: Invalid TS '{ts_str}'. Default 4/4.")
            return meter.TimeSignature("4/4")
        except Exception as e_ts_fb:
            logger_fallback.error(f"Fallback GTSO: Error for TS '{ts_str}': {e_ts_fb}. Default 4/4.")
            return meter.TimeSignature("4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
        if not label or not isinstance(label, str) or label.strip().lower() in ["rest", "n.c.", "nc", "none"]: return None
        label_out = label.strip().replace('maj7', 'M7').replace('mi7', 'm7').replace('ø7', 'm7b5')
        if label_out.count('(') > label_out.count(')') and label_out.endswith('('): label_out = label_out[:-1]
        try: harmony.ChordSymbol(label_out); return label_out
        except Exception:
            logger_fallback.warning(f"Fallback sanitize: '{label}' -> '{label_out}' may not parse.")
            try: harmony.ChordSymbol(label); return label
            except Exception: logger_fallback.error(f"Fallback sanitize: Neither '{label_out}' nor '{label}' parseable. -> None."); return None
    # --- End Fallback ---

logger = logging.getLogger(__name__)

DEFAULT_PIANO_LH_OCTAVE: int = 2
DEFAULT_PIANO_RH_OCTAVE: int = 4

# --- Humanization functions (inspired by music_generators_enhanced.py) ---
def generate_fractional_noise(length: int, hurst: float = 0.7, scale_factor: float = 1.0) -> List[float]:
    if length <= 0: return []
    white_noise = np.random.randn(length)
    fft_white = np.fft.fft(white_noise)
    freqs = np.fft.fftfreq(length)
    freqs[0] = 1e-6 if freqs.size > 0 and freqs[0] == 0 else freqs[0]
    filter_amplitude = np.abs(freqs) ** (-hurst)
    if freqs.size > 0: filter_amplitude[0] = 0
    fft_fbm = fft_white * filter_amplitude
    fbm_noise = np.fft.ifft(fft_fbm).real
    std_dev = np.std(fbm_noise)
    if std_dev != 0: fbm_norm = scale_factor * (fbm_noise - np.mean(fbm_noise)) / std_dev
    else: fbm_norm = np.zeros(length)
    return fbm_norm.tolist()

def apply_note_humanization(
    m21_note_or_chord: Union[note.Note, m21chord.Chord],
    time_variation: float = 0.01,
    duration_percentage: float = 0.03,
    velocity_variation: int = 5,
    use_fbm_time: bool = False,
    fbm_time_scale: float = 0.01,
    fbm_hurst: float = 0.6
) -> Union[note.Note, m21chord.Chord]:
    
    element_copy = copy.deepcopy(m21_note_or_chord)

    # Timing variation
    if use_fbm_time:
        time_shift = generate_fractional_noise(1, hurst=fbm_hurst, scale_factor=fbm_time_scale)[0]
    else:
        time_shift = random.uniform(-time_variation, time_variation)
    element_copy.offset += time_shift
    if element_copy.offset < 0: element_copy.offset = 0

    # Duration variation
    if element_copy.duration:
        original_ql = element_copy.duration.quarterLength
        duration_change = original_ql * random.uniform(-duration_percentage, duration_percentage)
        new_ql = max(MIN_NOTE_DURATION_QL / 8, original_ql + duration_change)
        element_copy.duration.quarterLength = new_ql

    # Velocity variation
    notes_to_affect = element_copy.notes if isinstance(element_copy, m21chord.Chord) else [element_copy]
    for n_obj in notes_to_affect:
        if isinstance(n_obj, note.Note) and hasattr(n_obj, 'volume') and n_obj.volume is not None:
            base_vel = n_obj.volume.velocity if n_obj.volume.velocity is not None else 64
            vel_change = random.randint(-velocity_variation, velocity_variation)
            n_obj.volume.velocity = max(1, min(127, base_vel + vel_change))
        elif isinstance(n_obj, note.Note): # No volume object, create one
            base_vel = 64
            vel_change = random.randint(-velocity_variation, velocity_variation)
            n_obj.volume = m21volume.Volume(velocity=max(1, min(127, base_vel + vel_change)))
            
    return element_copy

class PianoGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 chord_voicer_instance: Optional[Any] = None,
                 default_instrument_rh=m21instrument.Piano(),
                 default_instrument_lh=m21instrument.Piano(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.rhythm_library = rhythm_library if rhythm_library is not None else {}
        default_keys_to_add = {
            "default_piano_quarters": {
                "pattern": [{"offset": i, "duration": 1.0, "velocity_factor": 0.75 - (i%2 * 0.05)} for i in range(4)],
                "description": "Default quarter notes (auto-added)"
            },
            "piano_fallback_block": {
                "pattern": [{"offset":0.0, "duration": get_time_signature_object(global_time_signature).barDuration.quarterLength, "velocity_factor":0.7}],
                "description": "Fallback single block chord (auto-added)"
            }
        }
        for key_name, key_def in default_keys_to_add.items():
            if key_name not in self.rhythm_library:
                self.rhythm_library[key_name] = key_def
                logger.info(f"PianoGen: Added '{key_name}' to rhythm_library.")

        self.chord_voicer = chord_voicer_instance
        if not self.chord_voicer:
            logger.warning("PianoGen: No ChordVoicer. Voicing via basic internal logic.")

        self.instrument_rh = default_instrument_rh
        self.instrument_lh = default_instrument_lh
        self.global_tempo = global_tempo
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _get_piano_chord_pitches(
            self, m21_cs: Optional[harmony.ChordSymbol],
            num_voices_param: Optional[int],
            target_octave_param: int, voicing_style_name: str
    ) -> List[pitch.Pitch]:
        # (No changes from previous version, seems robust)
        if m21_cs is None or not m21_cs.pitches: return []
        final_num_voices_for_voicer = num_voices_param if num_voices_param is not None and num_voices_param > 0 else None
        if self.chord_voicer and hasattr(self.chord_voicer, '_apply_voicing_style'):
            try:
                return self.chord_voicer._apply_voicing_style(
                    m21_cs, voicing_style_name,
                    target_octave_for_bottom_note=target_octave_param,
                    num_voices_target=final_num_voices_for_voicer
                )
            except TypeError as te: logger.error(f"PianoGen: TypeError CV for '{m21_cs.figure}': {te}. Simple.", exc_info=True)
            except Exception as e_cv: logger.warning(f"PianoGen: Error CV for '{m21_cs.figure}': {e_cv}. Simple.", exc_info=True)
        logger.debug(f"PianoGen: Simple internal voicing for '{m21_cs.figure}'.")
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
            logger.warning(f"PianoGen: Simple voicing for '{m21_cs.figure}' failed: {e_simple}. Raw.", exc_info=True)
            raw_p_list = sorted(list(m21_cs.pitches), key=lambda p_sort: p_sort.ps)
            if final_num_voices_for_voicer is not None and raw_p_list: return raw_p_list[:final_num_voices_for_voicer]
            return raw_p_list if raw_p_list else []

    def _apply_pedal_to_part(self, part_to_apply_pedal: stream.Part, block_offset: float, block_duration: float):
        # (No changes from previous version)
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
            m21_cs_or_rest: Optional[music21.Music21Object],
            block_offset_ql: float, block_duration_ql: float,
            hand_specific_params: Dict[str, Any],
            rhythm_patterns_for_piano: Dict[str, Any]
    ) -> List[Tuple[float, music21.Music21Object]]:
        
        elements_with_offsets: List[Tuple[float, music21.Music21Object]] = []
        
        rhythm_key = hand_specific_params.get(f"piano_{hand_LR.lower()}_rhythm_key")
        velocity = int(hand_specific_params.get(f"piano_velocity_{hand_LR.lower()}", 64))
        voicing_style = hand_specific_params.get(f"piano_{hand_LR.lower()}_voicing_style", "closed")
        target_octave = int(hand_specific_params.get(f"piano_{hand_LR.lower()}_target_octave", 
                                                     DEFAULT_PIANO_RH_OCTAVE if hand_LR == "RH" else DEFAULT_PIANO_LH_OCTAVE))
        num_voices = hand_specific_params.get(f"piano_{hand_LR.lower()}_num_voices")
        arp_note_ql = float(hand_specific_params.get("piano_arp_note_ql", 0.5))
        perform_style_keyword = hand_specific_params.get(f"piano_{hand_LR.lower()}_style_keyword", "simple_block")
        
        # Humanization parameters for this block/hand
        humanize_this_hand = hand_specific_params.get(f"piano_humanize_{hand_LR.lower()}", hand_specific_params.get("piano_humanize", False))
        humanize_settings = None
        if humanize_this_hand:
            humanize_settings = {
                "time_variation": float(hand_specific_params.get("piano_humanize_time_var", 0.01)),
                "duration_percentage": float(hand_specific_params.get("piano_humanize_dur_perc", 0.02)),
                "velocity_variation": int(hand_specific_params.get("piano_humanize_vel_var", 4)),
                "use_fbm_time": bool(hand_specific_params.get("piano_humanize_fbm_time", False)),
                "fbm_time_scale": float(hand_specific_params.get("piano_humanize_fbm_scale", 0.005)),
                "fbm_hurst": float(hand_specific_params.get("piano_humanize_fbm_hurst", 0.7)),
            }
            # Allow style-based humanization template override (from music_generators_enhanced)
            humanize_style_template_key = hand_specific_params.get("piano_humanize_style_template")
            if humanize_style_template_key and humanize_style_template_key in humanization_templates: # Assuming humanization_templates is defined globally or passed
                template_params = humanization_templates[humanize_style_template_key]
                humanize_settings.update(template_params) # Override with template if specified

        if isinstance(m21_cs_or_rest, note.Rest):
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            elements_with_offsets.append((block_offset_ql, rest_obj))
            return elements_with_offsets
        
        if not m21_cs_or_rest or not isinstance(m21_cs_or_rest, harmony.ChordSymbol) or not m21_cs_or_rest.pitches:
            logger.warning(f"Piano {hand_LR}: No valid ChordSymbol for block at {block_offset_ql}. Adding Rest.")
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            elements_with_offsets.append((block_offset_ql, rest_obj))
            return elements_with_offsets
        
        m21_cs: harmony.ChordSymbol = cast(harmony.ChordSymbol, m21_cs_or_rest)
        logger.debug(f"Piano {hand_LR}: Chord '{m21_cs.figure}', RhythmKey '{rhythm_key}', Style '{perform_style_keyword}'")
        
        base_voiced_pitches = self._get_piano_chord_pitches(m21_cs, num_voices, target_octave, voicing_style)
        if not base_voiced_pitches:
            logger.warning(f"Piano {hand_LR}: No voiced pitches for {m21_cs.figure}. Adding Rest.")
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            elements_with_offsets.append((block_offset_ql, rest_obj))
            return elements_with_offsets

        rhythm_details = rhythm_patterns_for_piano.get(rhythm_key if rhythm_key else "")
        if not rhythm_details or "pattern" not in rhythm_details:
            logger.warning(f"Piano {hand_LR}: Rhythm key '{rhythm_key}' invalid. Using 'piano_fallback_block'.")
            rhythm_details = rhythm_patterns_for_piano.get("piano_fallback_block")
            if not rhythm_details or "pattern" not in rhythm_details:
                logger.error(f"Piano {hand_LR}: Fallback rhythm also missing pattern! Adding Rest.")
                rest_obj = note.Rest(quarterLength=block_duration_ql)
                elements_with_offsets.append((block_offset_ql, rest_obj))
                return elements_with_offsets
        
        pattern_events = rhythm_details.get("pattern", [])
        # --- EDM Style specific logic (inspired by piano_composer.py) ---
        # This could be triggered by a specific rhythm_key or perform_style_keyword
        is_edm_bounce_style = "edm_bounce" in (rhythm_key or "").lower() or "bounce" in perform_style_keyword.lower()
        is_edm_spread_style = "edm_spread" in (rhythm_key or "").lower() or "spread" in perform_style_keyword.lower()

        if is_edm_bounce_style or is_edm_spread_style:
            edm_step = 0.5 if is_edm_bounce_style else 0.25
            num_steps = int(block_duration_ql / edm_step)
            for i in range(num_steps):
                # For EDM, we might want to use the root or a simple triad more directly
                # rather than complex voicings for every hit.
                # Here, we'll use the base_voiced_pitches but could simplify.
                if not base_voiced_pitches: continue
                
                # Simple cycling through voiced pitches for variation, or just use the first few.
                current_edm_pitches = [base_voiced_pitches[j % len(base_voiced_pitches)] for j in range(min(3, len(base_voiced_pitches)))] # Play a triad
                
                if not current_edm_pitches: continue

                actual_edm_event_duration = min(edm_step, block_duration_ql - (i * edm_step))
                if actual_edm_event_duration < MIN_NOTE_DURATION_QL / 4: continue

                element_to_add: music21.Music21Object
                if len(current_edm_pitches) == 1:
                    element_to_add = note.Note(current_edm_pitches[0])
                else:
                    element_to_add = m21chord.Chord(current_edm_pitches)
                
                element_to_add.quarterLength = actual_edm_event_duration * 0.9 # Staccato
                element_to_add.volume = m21volume.Volume(velocity=velocity + random.randint(-5,5)) # Use block velocity
                
                current_event_abs_offset = block_offset_ql + i * edm_step
                if humanize_settings:
                    element_to_add = apply_note_humanization(element_to_add, **humanize_settings)
                elements_with_offsets.append((current_event_abs_offset, element_to_add))
            return elements_with_offsets
        # --- End EDM Style specific logic ---

        # --- Standard rhythm pattern application ---
        for event_params in pattern_events:
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
                
                current_offset_in_arp = 0.0; arp_idx = 0
                while current_offset_in_arp < actual_event_duration:
                    if not ordered_arp_pitches: break
                    p_arp = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                    single_arp_dur = min(arp_note_ql, actual_event_duration - current_offset_in_arp)
                    if single_arp_dur < MIN_NOTE_DURATION_QL / 4.0: break
                    
                    arp_note_obj = note.Note(p_arp, quarterLength=single_arp_dur * 0.95)
                    arp_note_obj.volume = m21volume.Volume(velocity=current_event_vel + random.randint(-3, 3))
                    
                    current_arp_note_abs_offset = abs_start_offset + current_offset_in_arp
                    if humanize_settings:
                        arp_note_obj = cast(note.Note, apply_note_humanization(arp_note_obj, **humanize_settings))
                    elements_with_offsets.append((current_arp_note_abs_offset, arp_note_obj))
                    
                    current_offset_in_arp += arp_note_ql; arp_idx += 1
            else:
                pitches_to_play = []
                if hand_LR == "LH":
                    lh_event_type = event_params.get("type", "root").lower()
                    lh_root = min(base_voiced_pitches, key=lambda p: p.ps) if base_voiced_pitches else (m21_cs.root() if m21_cs else pitch.Pitch(f"C{DEFAULT_PIANO_LH_OCTAVE}"))
                    if lh_event_type == "root" and lh_root: pitches_to_play.append(lh_root)
                    elif lh_event_type == "octave_root" and lh_root: pitches_to_play.extend([lh_root, lh_root.transpose(12)])
                    elif lh_event_type == "root_fifth" and lh_root:
                        pitches_to_play.append(lh_root)
                        root_for_fifth = m21_cs.root() or lh_root
                        fifth_cand = root_for_fifth.transpose(interval.PerfectFifth())
                        fifth_p = pitch.Pitch(fifth_cand.name, octave=lh_root.octave)
                        if fifth_p.ps < lh_root.ps + 3 : fifth_p.octave +=1
                        pitches_to_play.append(fifth_p)
                    elif base_voiced_pitches: pitches_to_play.append(min(base_voiced_pitches, key=lambda p:p.ps))
                    pitches_to_play = [p for p in pitches_to_play if p is not None]
                else: pitches_to_play = base_voiced_pitches
                
                if pitches_to_play:
                    element: music21.Music21Object
                    play_dur = actual_event_duration * 0.9
                    if len(pitches_to_play) == 1:
                        element = note.Note(pitches_to_play[0], quarterLength=play_dur)
                        element.volume = m21volume.Volume(velocity=current_event_vel)
                    else:
                        element = m21chord.Chord(pitches_to_play, quarterLength=play_dur)
                        for n_chord in element.notes: n_chord.volume = m21volume.Volume(velocity=current_event_vel)
                    
                    if humanize_settings:
                         element = apply_note_humanization(element, **humanize_settings)
                    elements_with_offsets.append((abs_start_offset, element))
        
        return elements_with_offsets

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Score:
        piano_score = stream.Score(id="PianoScore")
        piano_rh_part = stream.Part(id="PianoRH"); piano_rh_part.insert(0, self.instrument_rh)
        piano_lh_part = stream.Part(id="PianoLH"); piano_lh_part.insert(0, self.instrument_lh)
        piano_score.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        piano_score.insert(0, self.global_time_signature_obj.clone())

        if not processed_chord_stream:
            logger.info("PianoGen: Empty stream. Returning empty score.")
            piano_score.append(piano_rh_part); piano_score.append(piano_lh_part)
            return piano_score
            
        logger.info(f"PianoGen: Starting for {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset = float(blk_data.get("offset", 0.0))
            block_dur = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            chord_lbl_original = blk_data.get("chord_label", "C")
            piano_params = blk_data.get("part_params", {}).get("piano", {})
            
            # --- Vocal density integration (conceptual) ---
            # vocal_density_for_block = blk_data.get("vocal_density_info", {}).get("density_score")
            # if vocal_density_for_block is not None:
            #     if vocal_density_for_block == 0:
            #         piano_params["piano_rh_style_keyword"] = piano_params.get("piano_rh_style_on_vocal_rest", "edm_spread_rh") # Example
            #         piano_params["piano_velocity_rh"] = int(piano_params.get("piano_velocity_rh", 70) * 0.9)
            #     elif vocal_density_for_block >=3:
            #         piano_params["piano_rh_style_keyword"] = piano_params.get("piano_rh_style_on_vocal_active", "edm_bounce_rh") # Example
            #         piano_params["piano_velocity_rh"] = int(piano_params.get("piano_velocity_rh", 70) * 1.1)
            # --- End Vocal density integration ---

            logger.debug(f"Piano Blk {blk_idx+1}: Off={block_offset}, Dur={block_dur}, OrigLbl='{chord_lbl_original}', Prms: {piano_params}")

            cs_or_rest_obj: Optional[music21.Music21Object] = None
            sanitized_label = sanitize_chord_label(chord_lbl_original)

            if sanitized_label is None:
                cs_or_rest_obj = note.Rest(quarterLength=block_dur)
                logger.info(f"PianoGen: Blk {blk_idx+1} ('{chord_lbl_original}') is Rest/unparseable.")
            else:
                try:
                    cs_or_rest_obj = harmony.ChordSymbol(sanitized_label)
                    if not cs_or_rest_obj.pitches:
                        logger.warning(f"PianoGen: Chord '{sanitized_label}' (orig:'{chord_lbl_original}') parsed but no pitches. Rest.")
                        cs_or_rest_obj = note.Rest(quarterLength=block_dur)
                except Exception as e_cs:
                    logger.error(f"PianoGen: Error CS for '{sanitized_label}' (orig:'{chord_lbl_original}'): {e_cs}. Rest.", exc_info=True)
                    cs_or_rest_obj = note.Rest(quarterLength=block_dur)
            
            rh_elems = self._generate_piano_hand_part_for_block("RH", cs_or_rest_obj, block_offset, block_dur, piano_params, self.rhythm_library)
            for off, el in rh_elems: piano_rh_part.insert(off, el)
            
            lh_elems = self._generate_piano_hand_part_for_block("LH", cs_or_rest_obj, block_offset, block_dur, piano_params, self.rhythm_library)
            for off, el in lh_elems: piano_lh_part.insert(off, el)
            
            if piano_params.get("piano_apply_pedal", True) and not isinstance(cs_or_rest_obj, note.Rest):
                self._apply_pedal_to_part(piano_lh_part, block_offset, block_dur)

        piano_score.append(piano_rh_part); piano_score.append(piano_lh_part)
        logger.info(f"PianoGen: Finished. RH notes: {len(piano_rh_part.flatten().notesAndRests)}, LH notes: {len(piano_lh_part.flatten().notesAndRests)}")
        return piano_score

# Global humanization templates (can be moved to a config file or core_utils)
humanization_templates = {
    "default_subtle": {"time_variation": 0.01, "duration_percentage": 0.03, "velocity_variation": 5},
    "piano_gentle_arpeggio": {"time_variation": 0.008, "duration_percentage": 0.02, "velocity_variation": 4, "use_fbm_time": True, "fbm_time_scale": 0.005},
    "piano_block_chord": {"time_variation": 0.015, "duration_percentage": 0.04, "velocity_variation": 7},
    "piano_edm_lead": {"time_variation": 0.005, "duration_percentage": 0.01, "velocity_variation": 3, "use_fbm_time": True, "fbm_time_scale": 0.003},
    # Add more templates as needed
}
# --- END OF FILE generators/piano_generator.py ---
