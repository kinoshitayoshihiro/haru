# --- START OF FILE generators/guitar_generator.py (2023-05-23 統合・強化版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence, Union
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key,
                     chord as m21chord, articulations, volume as m21volume, expressions) # expressions を追加
import random
import logging
import numpy as np
import copy

try:
    from .core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
except ImportError:
    # --- Fallback definitions ---
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("GuitarGen: Could not import from .core_music_utils. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"; return meter.TimeSignature(ts_str)
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
        if not label or label.strip().lower() in ["rest", "n.c.", "nc", "none"]: return None
        return label.strip()
    # --- End Fallback ---

logger = logging.getLogger(__name__)

# --- 定数 (GuitarGenerator用) ---
DEFAULT_GUITAR_OCTAVE_RANGE: Tuple[int, int] = (2, 5) # E2 to E5/F5
GUITAR_STRUM_DELAY_QL: float = 0.02 # Strum delay in quarter lengths
MIN_STRUM_NOTE_DURATION_QL: float = 0.05 # Minimum duration for a strummed note if not full chord duration

# Guitar playing styles (can be extended)
STYLE_BLOCK_CHORD = "block_chord" # Simple block chord
STYLE_STRUM_BASIC = "strum_basic" # Basic strumming based on rhythm pattern
STYLE_ARPEGGIO = "arpeggio"     # Generic arpeggio, details from rhythm pattern or params
STYLE_POWER_CHORDS = "power_chords"
STYLE_MUTED_RHYTHM = "muted_rhythm"
STYLE_SINGLE_NOTE_LINE = "single_note_line" # For riffs or simple melodies on guitar

# --- Humanization functions (can be moved to core_music_utils if shared) ---
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
    m21_element: Union[note.Note, m21chord.Chord],
    params: Dict[str, Any] # Expects keys like 'time_variation', 'duration_percentage', etc.
) -> Union[note.Note, m21chord.Chord]:
    
    element_copy = copy.deepcopy(m21_element)
    time_var = params.get('time_variation', 0.01)
    dur_perc = params.get('duration_percentage', 0.03)
    vel_var = params.get('velocity_variation', 5)
    use_fbm = params.get('use_fbm_time', False)
    fbm_scale = params.get('fbm_time_scale', 0.01)
    fbm_h = params.get('fbm_hurst', 0.6)

    if use_fbm: time_shift = generate_fractional_noise(1, hurst=fbm_h, scale_factor=fbm_scale)[0]
    else: time_shift = random.uniform(-time_var, time_var)
    
    element_copy.offset += time_shift
    if element_copy.offset < 0: element_copy.offset = 0.0

    if element_copy.duration:
        original_ql = element_copy.duration.quarterLength
        dur_change = original_ql * random.uniform(-dur_perc, dur_perc)
        new_ql = max(MIN_NOTE_DURATION_QL / 8, original_ql + dur_change)
        element_copy.duration.quarterLength = new_ql

    notes_to_affect = element_copy.notes if isinstance(element_copy, m21chord.Chord) else [element_copy]
    for n_obj in notes_to_affect:
        if isinstance(n_obj, note.Note):
            base_vel = n_obj.volume.velocity if hasattr(n_obj, 'volume') and n_obj.volume and n_obj.volume.velocity is not None else 64
            vel_change = random.randint(-vel_var, vel_var)
            final_vel = max(1, min(127, base_vel + vel_change))
            if hasattr(n_obj, 'volume') and n_obj.volume is not None: n_obj.volume.velocity = final_vel
            else: n_obj.volume = volume.Volume(velocity=final_vel)
    return element_copy

# Global humanization templates (can be moved to a config file or core_utils)
HUMANIZATION_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "default_guitar_subtle": {"time_variation": 0.015, "duration_percentage": 0.04, "velocity_variation": 6},
    "guitar_strum_loose": {"time_variation": 0.025, "duration_percentage": 0.06, "velocity_variation": 10, "use_fbm_time": True, "fbm_time_scale": 0.015},
    "guitar_arpeggio_precise": {"time_variation": 0.008, "duration_percentage": 0.02, "velocity_variation": 4},
    "guitar_power_chord_tight": {"time_variation": 0.01, "duration_percentage": 0.02, "velocity_variation": 5},
    "guitar_mute_funky": {"time_variation": 0.02, "duration_percentage": 0.1, "velocity_variation": 8, "use_fbm_time": True, "fbm_time_scale": 0.01},
}

class GuitarGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 default_instrument=m21instrument.AcousticGuitar(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.rhythm_library = rhythm_library if rhythm_library else {}
        # Ensure a very basic default rhythm pattern exists if none provided
        if "guitar_default_quarters" not in self.rhythm_library:
             self.rhythm_library["guitar_default_quarters"] = {
                 "description": "Default quarter note strums/hits for guitar.",
                 "pattern": [ # List of event dicts
                     {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.8, "articulation": "normal"},
                     {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.75, "articulation": "normal"},
                     {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.8, "articulation": "normal"},
                     {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.75, "articulation": "normal"}
                 ]
             }
             logger.info("GuitarGen: Added 'guitar_default_quarters' to rhythm_library.")

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _get_guitar_friendly_voicing(
        self,
        m21_cs: harmony.ChordSymbol,
        num_strings: int = 6,
        preferred_octave_bottom: int = 2, # E2 is common lowest
        max_octave_top: int = 5,          # Around C5-E5
        voicing_style: str = "standard"   # "standard", "open", "power_chord_root_fifth", "drop_d_power"
    ) -> List[pitch.Pitch]:
        if not m21_cs or not m21_cs.pitches: return []

        original_pitches = list(m21_cs.pitches)
        root = m21_cs.root()
        bass = m21_cs.bass()

        voiced_pitches: List[pitch.Pitch] = []

        if voicing_style == "power_chord_root_fifth":
            if root:
                p_root = pitch.Pitch(root.name)
                # Find a suitable octave for the root (E2-A3 range)
                while p_root.ps < pitch.Pitch(f"E{preferred_octave_bottom}").ps: p_root.octave += 1
                while p_root.ps > pitch.Pitch(f"A{preferred_octave_bottom+1}").ps: p_root.octave -=1
                
                p_fifth = p_root.transpose(interval.PerfectFifth())
                p_octave_root = p_root.transpose(interval.PerfectOctave())
                voiced_pitches = [p_root, p_fifth]
                if p_octave_root.ps <= pitch.Pitch(f"G{max_octave_top}").ps: # Add octave if within range
                    voiced_pitches.append(p_octave_root)
            return sorted(list(set(voiced_pitches)), key=lambda p: p.ps)[:num_strings]

        # Standard/Open voicing logic (simplified)
        try:
            # Try to get a reasonable spread using music21's capabilities
            if voicing_style == "open" and hasattr(m21_cs, 'semiClosedPosition'):
                 # semiClosed can sometimes give more open voicings
                temp_chord = m21_cs.semiClosedPosition(forceOctave=preferred_octave_bottom, inPlace=False)
            else:
                temp_chord = m21_cs.closedPosition(forceOctave=preferred_octave_bottom, inPlace=False)
            
            candidate_pitches = sorted(list(temp_chord.pitches), key=lambda p: p.ps)
        except Exception:
            candidate_pitches = sorted(original_pitches, key=lambda p:p.ps)

        if not candidate_pitches: return []

        # Adjust overall octave to fit guitar range better if needed
        # Ensure lowest note is not below E2 generally
        bottom_note_target_ps = pitch.Pitch(f"E{preferred_octave_bottom}").ps
        if candidate_pitches[0].ps < bottom_note_target_ps - 6: # Significantly lower
            oct_shift = round((bottom_note_target_ps - candidate_pitches[0].ps) / 12.0)
            candidate_pitches = [p.transpose(oct_shift * 12) for p in candidate_pitches]
            candidate_pitches.sort(key=lambda p: p.ps)
        
        # Select up to num_strings, prioritizing unique pitch classes, then lower notes
        selected_pitches_dict: Dict[str, pitch.Pitch] = {} #音名で管理して重複を避ける
        for p_cand in candidate_pitches:
            if p_cand.name not in selected_pitches_dict:
                if p_cand.ps >= pitch.Pitch(f"E{DEFAULT_GUITAR_OCTAVE_RANGE[0]-1}").ps and \
                   p_cand.ps <= pitch.Pitch(f"G{DEFAULT_GUITAR_OCTAVE_RANGE[1]+1}").ps : # 緩い音域チェック
                    selected_pitches_dict[p_cand.name] = p_cand
        
        voiced_pitches = sorted(list(selected_pitches_dict.values()), key=lambda p:p.ps)

        # If not enough unique pitches, add octaves or higher chord tones if available in original
        if len(voiced_pitches) < num_strings:
            for p_orig in sorted(original_pitches, key=lambda p:p.ps, reverse=True): # Higher tones first
                if len(voiced_pitches) >= num_strings: break
                # Try to add an octave of an existing voiced pitch if it's different
                for vp_idx, vp_existing in enumerate(voiced_pitches):
                    if vp_existing.name == p_orig.name: # Already have this pitch class
                        # Try adding an octave higher if not present and in range
                        p_oct_up = vp_existing.transpose(12)
                        if p_oct_up.ps <= pitch.Pitch(f"G{max_octave_top+1}").ps and \
                           not any(p.ps == p_oct_up.ps for p in voiced_pitches):
                            voiced_pitches.append(p_oct_up)
                            voiced_pitches.sort(key=lambda p:p.ps)
                            if len(voiced_pitches) >= num_strings: break
                if len(voiced_pitches) >= num_strings: break
                # If pitch class not present, add it if in range
                if not any(vp.name == p_orig.name for vp in voiced_pitches):
                    p_adjusted = pitch.Pitch(p_orig.name) # Start with base name
                    # Find a suitable octave
                    if voiced_pitches: p_adjusted.octave = voiced_pitches[-1].octave # Start near highest current
                    else: p_adjusted.octave = preferred_octave_bottom +1
                    while p_adjusted.ps < voiced_pitches[-1].ps if voiced_pitches else bottom_note_target_ps : p_adjusted.octave +=1
                    while p_adjusted.ps > pitch.Pitch(f"G{max_octave_top+1}").ps: p_adjusted.octave -=1
                    
                    if p_adjusted.ps >= bottom_note_target_ps and not any(p.name == p_adjusted.name for p in voiced_pitches):
                         voiced_pitches.append(p_adjusted)
                         voiced_pitches.sort(key=lambda p:p.ps)


        return voiced_pitches[:num_strings]


    def _create_notes_from_event(
        self,
        m21_cs: harmony.ChordSymbol,
        guitar_params: Dict[str, Any],
        event_abs_offset: float,
        event_duration_ql: float,
        event_velocity: int
    ) -> List[Union[note.Note, m21chord.Chord]]:
        
        notes_for_event: List[Union[note.Note, m21chord.Chord]] = []
        style = guitar_params.get("guitar_style", STYLE_BLOCK_CHORD)
        num_strings = guitar_params.get("guitar_num_strings", 6)
        preferred_octave = guitar_params.get("guitar_target_octave", 3) # For voicing
        voicing_style_name = guitar_params.get("guitar_voicing_style", "standard") # "standard", "open", "power_chord_root_fifth"

        chord_pitches = self._get_guitar_friendly_voicing(m21_cs, num_strings, preferred_octave, voicing_style_name)
        if not chord_pitches: return []

        if style == STYLE_BLOCK_CHORD:
            ch = m21chord.Chord(chord_pitches, quarterLength=event_duration_ql * 0.9) # Slight staccato
            for n_in_ch in ch.notes: n_in_ch.volume.velocity = event_velocity
            notes_for_event.append(ch)

        elif style == STYLE_STRUM_BASIC:
            # Strum direction can be part of guitar_params or rhythm_event_params
            is_down = guitar_params.get("strum_direction", "down").lower() == "down"
            
            # Create individual notes for strum
            play_order = list(reversed(chord_pitches)) if is_down else chord_pitches
            for i, p_obj in enumerate(play_order):
                n = note.Note(p_obj)
                # Each strummed note lasts for the event duration, but starts delayed
                n.duration = duration.Duration(quarterLength=max(MIN_STRUM_NOTE_DURATION_QL, event_duration_ql * 0.9))
                n.offset = event_abs_offset + (i * GUITAR_STRUM_DELAY_QL) # Absolute offset for this note
                
                # Velocity variation for strum
                vel_adj = 0
                if len(play_order) > 1:
                    vel_adj = int(((len(play_order) - 1 - i) / (len(play_order) - 1) * 10) - 5) if is_down else int((i / (len(play_order) - 1) * 10) - 5)
                
                n.volume = volume.Volume(velocity=max(1, min(127, event_velocity + vel_adj)))
                notes_for_event.append(n)
        
        elif style == STYLE_ARPEGGIO:
            arp_pattern_type = guitar_params.get("arpeggio_type", "up") # "up", "down", "updown", "random" or list of indices
            arp_note_dur_ql = guitar_params.get("arpeggio_note_duration_ql", 0.5) # e.g., 8th notes
            
            ordered_arp_pitches: List[pitch.Pitch]
            if isinstance(arp_pattern_type, list): # Index pattern
                ordered_arp_pitches = [chord_pitches[i % len(chord_pitches)] for i in arp_pattern_type]
            elif arp_pattern_type == "down": ordered_arp_pitches = list(reversed(chord_pitches))
            elif arp_pattern_type == "updown":
                ordered_arp_pitches = chord_pitches + (list(reversed(chord_pitches[1:-1])) if len(chord_pitches) > 2 else [])
            elif arp_pattern_type == "random": ordered_arp_pitches = random.sample(chord_pitches, len(chord_pitches))
            else: ordered_arp_pitches = chord_pitches # Default "up"

            current_offset_in_event = 0.0
            arp_idx = 0
            while current_offset_in_event < event_duration_ql and ordered_arp_pitches:
                p_to_play = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                actual_arp_note_dur = min(arp_note_dur_ql, event_duration_ql - current_offset_in_event)
                if actual_arp_note_dur < MIN_NOTE_DURATION_QL / 4: break

                n = note.Note(p_to_play, quarterLength=actual_arp_note_dur * 0.95)
                n.volume.velocity = event_velocity
                n.offset = event_abs_offset + current_offset_in_event # Absolute offset
                notes_for_event.append(n)
                current_offset_in_event += arp_note_dur_ql
                arp_idx += 1
        
        elif style == STYLE_MUTED_RHYTHM:
            mute_note_dur = guitar_params.get("mute_note_duration_ql", 0.1)
            mute_interval = guitar_params.get("mute_interval_ql", 0.25) # e.g., 16th notes
            t_mute = 0.0
            root_pitch_for_mute = chord_pitches[0] # Use the lowest note of the voicing for muted hits
            while t_mute < event_duration_ql:
                actual_mute_dur = min(mute_note_dur, event_duration_ql - t_mute)
                if actual_mute_dur < MIN_NOTE_DURATION_QL / 8: break
                
                n = note.Note(root_pitch_for_mute)
                n.articulations = [articulations.Staccatissimo()] # Make it very short and percussive
                n.duration.quarterLength = actual_mute_dur
                n.volume.velocity = int(event_velocity * 0.6) + random.randint(-5,5) # Lower velocity for mutes
                n.offset = event_abs_offset + t_mute
                notes_for_event.append(n)
                t_mute += mute_interval
        
        # Add other styles like STYLE_POWER_CHORDS, STYLE_SINGLE_NOTE_LINE here
        
        return notes_for_event


    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        guitar_part = stream.Part(id="Guitar")
        guitar_part.insert(0, self.default_instrument)
        guitar_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        guitar_part.insert(0, self.global_time_signature_obj.clone())

        if not processed_chord_stream:
            logger.info("GuitarGen: Empty stream. Returning empty part.")
            return guitar_part
            
        logger.info(f"GuitarGen: Starting for {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            chord_label_str = blk_data.get("chord_label", "C")
            
            guitar_params = blk_data.get("part_params", {}).get("guitar", {})
            if not guitar_params: # If no specific guitar params, skip or use very basic default
                logger.debug(f"Guitar Blk {blk_idx+1}: No guitar_params. Skipping.")
                continue

            logger.debug(f"Guitar Blk {blk_idx+1}: Chord '{chord_label_str}', Offset {block_offset_ql}, Params: {guitar_params}")

            # Humanization settings for this block
            humanize_this_block = guitar_params.get("guitar_humanize", False)
            humanize_settings = None
            if humanize_this_block:
                template_key = guitar_params.get("guitar_humanize_style_template", "default_guitar_subtle")
                base_humanize_params = HUMANIZATION_TEMPLATES.get(template_key, HUMANIZATION_TEMPLATES["default_guitar_subtle"])
                humanize_settings = base_humanize_params.copy()
                # Allow overrides from guitar_params
                for k_h, v_h in guitar_params.items():
                    if k_h.startswith("guitar_humanize_") and k_h.replace("guitar_humanize_", "") in humanize_settings:
                        try:
                            # Attempt to cast to the type of the default value in template
                            target_type = type(humanize_settings[k_h.replace("guitar_humanize_", "")])
                            humanize_settings[k_h.replace("guitar_humanize_", "")] = target_type(v_h)
                        except ValueError:
                            logger.warning(f"GuitarGen: Could not cast humanize param {k_h} to target type.")


            m21_cs: Optional[harmony.ChordSymbol] = None
            sanitized_label = sanitize_chord_label(chord_label_str)
            if sanitized_label:
                try:
                    m21_cs = harmony.ChordSymbol(sanitized_label)
                    if not m21_cs.pitches: m21_cs = None # Treat as rest if no pitches
                except Exception as e_cs:
                    logger.warning(f"GuitarGen: Error parsing chord '{sanitized_label}' (orig: {chord_label_str}): {e_cs}. Treating as Rest.")
                    m21_cs = None
            
            if m21_cs is None: # Handle as rest or skip
                # Could insert a rest into guitar_part if desired for explicit silence
                # For now, just skip generating notes for this block
                logger.info(f"GuitarGen: Blk {blk_idx+1} ('{chord_label_str}') is Rest or unparseable. Skipping guitar notes.")
                continue

            # Get rhythm pattern for this block
            # rhythm_key is now expected to be in guitar_params from modular_composer
            rhythm_key = guitar_params.get("guitar_rhythm_key", "guitar_default_quarters")
            rhythm_details = self.rhythm_library.get(rhythm_key)
            
            if not rhythm_details or "pattern" not in rhythm_details:
                logger.warning(f"GuitarGen: Rhythm key '{rhythm_key}' for guitar not found or pattern missing. Using fallback 'guitar_default_quarters'.")
                rhythm_details = self.rhythm_library.get("guitar_default_quarters")
                if not rhythm_details or "pattern" not in rhythm_details:
                    logger.error("GuitarGen: Fallback guitar rhythm 'guitar_default_quarters' also invalid. Skipping block.")
                    continue
            
            pattern_events = rhythm_details.get("pattern", []) # List of event dicts

            for event_def in pattern_events:
                event_offset_in_pattern = float(event_def.get("offset", 0.0))
                event_duration_in_pattern = float(event_def.get("duration", 1.0)) # Default duration of 1 beat for an event
                event_velocity_factor = float(event_def.get("velocity_factor", 1.0))
                # Articulation or specific strum direction can be in event_def
                # event_articulation = event_def.get("articulation", "normal") 
                # event_strum_dir = event_def.get("strum_direction") 

                abs_event_start_offset = block_offset_ql + event_offset_in_pattern
                
                # Ensure event is within the block's duration
                max_possible_event_dur = block_duration_ql - event_offset_in_pattern
                actual_event_dur = min(event_duration_in_pattern, max_possible_event_dur)

                if actual_event_dur < MIN_NOTE_DURATION_QL / 2: continue

                event_base_velocity = int(guitar_params.get("guitar_velocity", 70) * event_velocity_factor)

                # Create notes for this specific event based on style, chord, and event params
                # The _create_notes_from_event will use guitar_params which can include style
                generated_elements = self._create_notes_from_event(
                    m21_cs,
                    guitar_params, # Pass all guitar params for this block
                    abs_event_start_offset, # Pass absolute start for the event
                    actual_event_dur,
                    event_base_velocity
                )
                
                for el in generated_elements:
                    # Offset is already absolute from _create_notes_from_event
                    if humanize_settings:
                        el = apply_note_humanization(el, humanize_settings)
                    guitar_part.insert(el.offset, el)
        
        logger.info(f"GuitarGen: Finished. Part has {len(guitar_part.flatten().notesAndRests)} elements.")
        return guitar_part

# --- END OF FILE generators/guitar_generator.py ---
