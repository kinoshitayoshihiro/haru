# --- START OF FILE generator/vocal_generator.py (2023-05-23 強化案) ---
import music21
from typing import List, Dict, Optional, Any, Tuple, Union
from music21 import (stream, note, pitch, meter, duration, instrument as m21instrument,
                     tempo, key, expressions, volume as m21volume, articulations, dynamics) # dynamics を追加
import logging
import json
import re
import copy
import random
import math # For Gaussian fallback

# NumPy import attempt and flag
NUMPY_AVAILABLE = False
np = None
try:
    import numpy
    np = numpy
    NUMPY_AVAILABLE = True
    logging.info("VocalGen(Humanizer): NumPy found. Fractional noise generation is enabled.")
except ImportError:
    logging.warning("VocalGen(Humanizer): NumPy not found. Fractional noise will use Gaussian fallback.")


logger = logging.getLogger(__name__)

MIN_NOTE_DURATION_QL = 0.125 # 以前は0.25だったが、より短い音も許容
DEFAULT_BREATH_DURATION_QL: float = 0.25
MIN_DURATION_FOR_BREATH_AFTER_NOTE_QL: float = 1.0 # 短い音の後でもブレスを検討できるように調整
PUNCTUATION_FOR_BREATH: Tuple[str, ...] = ('、', '。', '！', '？', ',', '.', '!', '?')

# --- Humanization functions (integrated for now, can be in a separate humanizer.py) ---
def generate_fractional_noise(length: int, hurst: float = 0.7, scale_factor: float = 1.0) -> List[float]:
    if not NUMPY_AVAILABLE or np is None:
        # Fallback to Gaussian noise if NumPy is not available
        return [random.gauss(0, scale_factor / 3) for _ in range(length)] # Simpler noise
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

HUMANIZATION_TEMPLATES_VOCAL: Dict[str, Dict[str, Any]] = {
    "vocal_default_subtle": {"time_variation": 0.02, "duration_percentage": 0.03, "velocity_variation": 6, "use_fbm_time": False},
    "vocal_ballad_smooth": {"time_variation": 0.025, "duration_percentage": 0.05, "velocity_variation": 4, "use_fbm_time": True, "fbm_time_scale": 0.01, "fbm_hurst": 0.7},
    "vocal_pop_energetic": {"time_variation": 0.015, "duration_percentage": 0.02, "velocity_variation": 8, "use_fbm_time": True, "fbm_time_scale": 0.008},
    "vocal_rap_percussive": {"time_variation": 0.01, "duration_percentage": 0.10, "velocity_variation": 10, "use_fbm_time": False}, # Shorter, punchier
}

def apply_humanization_to_notes(
    notes_to_humanize: List[Union[note.Note, m21chord.Chord]], # Vocal usually only has Notes
    template_name: Optional[str] = "vocal_default_subtle",
    custom_params: Optional[Dict[str, Any]] = None
) -> List[Union[note.Note, m21chord.Chord]]:
    
    humanized_elements = []
    params = HUMANIZATION_TEMPLATES_VOCAL.get(template_name or "vocal_default_subtle", HUMANIZATION_TEMPLATES_VOCAL["vocal_default_subtle"]).copy()
    if custom_params:
        params.update(custom_params)

    time_var = params.get('time_variation', 0.01)
    dur_perc = params.get('duration_percentage', 0.03)
    vel_var = params.get('velocity_variation', 5)
    use_fbm = params.get('use_fbm_time', False)
    fbm_scale = params.get('fbm_time_scale', 0.01)
    fbm_h = params.get('fbm_hurst', 0.6)

    fbm_time_shifts = []
    if use_fbm and NUMPY_AVAILABLE and len(notes_to_humanize) > 0:
        fbm_time_shifts = generate_fractional_noise(len(notes_to_humanize), hurst=fbm_h, scale_factor=fbm_scale)
    
    for idx, element in enumerate(notes_to_humanize):
        element_copy = copy.deepcopy(element)
        
        if use_fbm and NUMPY_AVAILABLE and idx < len(fbm_time_shifts):
            time_shift = fbm_time_shifts[idx]
        else:
            if use_fbm and not NUMPY_AVAILABLE and idx == 0: # Log only once per call
                 logger.debug("Humanizer: FBM time shift requested for vocal but NumPy not available. Using uniform random.")
            time_shift = random.uniform(-time_var, time_var)
        
        element_copy.offset += time_shift
        if element_copy.offset < 0: element_copy.offset = 0.0

        if element_copy.duration:
            original_ql = element_copy.duration.quarterLength
            duration_change = original_ql * random.uniform(-dur_perc, dur_perc)
            new_ql = max(MIN_NOTE_DURATION_QL / 4, original_ql + duration_change) # Ensure very short notes are possible
            try:
                element_copy.duration.quarterLength = new_ql
            except music21.exceptions21.DurationException as e: # music21.duration.DurationException
                logger.warning(f"Humanizer: DurationException setting qL to {new_ql} for element {element_copy}: {e}. Skipping duration change.")


        if isinstance(element_copy, note.Note): # Vocals are typically single notes
            base_vel = element_copy.volume.velocity if hasattr(element_copy, 'volume') and element_copy.volume and element_copy.volume.velocity is not None else 70 # Default vocal velocity
            vel_change = random.randint(-vel_var, vel_var)
            final_vel = max(1, min(127, base_vel + vel_change))
            if hasattr(element_copy, 'volume') and element_copy.volume is not None:
                element_copy.volume.velocity = final_vel
            else:
                element_copy.volume = volume.Volume(velocity=final_vel)
        humanized_elements.append(element_copy)
        
    return humanized_elements
# --- End Humanization functions ---

class VocalGenerator:
    def __init__(self,
                 default_instrument=m21instrument.Vocalist(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _parse_midivocal_data(self, midivocal_data: List[Dict]) -> List[Dict]:
        # (No significant changes from previous, seems robust enough for now)
        parsed_notes = []
        for item_idx, item in enumerate(midivocal_data):
            try:
                offset = float(item["Offset"])
                pitch_name = str(item["Pitch"])
                length = float(item["Length"])
                velocity = int(item.get("Velocity", 70)) # Velocity from data if available

                if not pitch_name: logger.warning(f"Vocal note #{item_idx+1} empty pitch. Skip."); continue
                try: pitch.Pitch(pitch_name)
                except Exception as e_p: logger.warning(f"Skip vocal #{item_idx+1} invalid pitch: '{pitch_name}' ({e_p})"); continue
                if length <= 0: logger.warning(f"Skip vocal #{item_idx+1} non-positive length: {length}"); continue
                
                parsed_notes.append({"offset": offset, "pitch_str": pitch_name, "q_length": length, "velocity": velocity})
            except KeyError as ke: logger.error(f"Skip vocal item #{item_idx+1} missing key: {ke} in {item}")
            except ValueError as ve: logger.error(f"Skip vocal item #{item_idx+1} ValueError: {ve} in {item}")
            except Exception as e: logger.error(f"Unexpected error parsing vocal item #{item_idx+1}: {e} in {item}", exc_info=True)
        
        parsed_notes.sort(key=lambda x: x["offset"])
        logger.info(f"Parsed {len(parsed_notes)} valid notes from midivocal_data.")
        return parsed_notes

    def _get_section_for_note_offset(self, note_offset: float, processed_stream: List[Dict]) -> Optional[str]:
        """
        Determines the song section for a given note offset based on the processed_chord_stream.
        """
        for block in processed_stream:
            block_start = block.get("offset", 0.0)
            block_end = block_start + block.get("q_length", 0.0)
            if block_start <= note_offset < block_end:
                return block.get("section_name")
        logger.warning(f"VocalGen: No section found in processed_stream for note offset {note_offset:.2f}")
        return None # Or a default section name

    def _insert_breaths(self, notes_with_lyrics: List[note.Note], breath_duration_ql: float) -> List[Union[note.Note, note.Rest]]:
        if not notes_with_lyrics: return []
        logger.info(f"Inserting breaths (duration: {breath_duration_ql}qL).")
        
        output_elements: List[Union[note.Note, note.Rest]] = []
        
        for i, current_note in enumerate(notes_with_lyrics):
            original_offset = current_note.offset
            original_duration_ql = current_note.duration.quarterLength
            
            # Determine if a breath should be inserted AFTER this note
            insert_breath_flag = False
            shorten_note_for_breath = False

            if current_note.lyric and any(punc in current_note.lyric for punc in PUNCTUATION_FOR_BREATH):
                if original_duration_ql > breath_duration_ql + MIN_NOTE_DURATION_QL / 4: # Enough room to shorten
                    shorten_note_for_breath = True
                    insert_breath_flag = True
                    logger.debug(f"Breath planned after note (punctuation): {current_note.pitch} at {original_offset:.2f}")
                else:
                    logger.debug(f"Note {current_note.pitch} at {original_offset:.2f} too short for breath (punctuation).")
            
            # Check for long notes followed by another note with a small gap
            if not insert_breath_flag and original_duration_ql >= MIN_DURATION_FOR_BREATH_AFTER_NOTE_QL:
                if i + 1 < len(notes_with_lyrics):
                    next_note = notes_with_lyrics[i+1]
                    gap_to_next = next_note.offset - (original_offset + original_duration_ql)
                    if gap_to_next < breath_duration_ql * 0.75: # If gap is smaller than most of a breath
                        if original_duration_ql > breath_duration_ql + MIN_NOTE_DURATION_QL / 4:
                            shorten_note_for_breath = True
                            insert_breath_flag = True
                            logger.debug(f"Breath planned after note (long note, small gap): {current_note.pitch} at {original_offset:.2f}")
                        else:
                            logger.debug(f"Note {current_note.pitch} at {original_offset:.2f} too short for breath (long note).")
                else: # Last note of the phrase/song
                    insert_breath_flag = True # Can add breath without shortening
                    shorten_note_for_breath = False # No need to shorten the very last note
                    logger.debug(f"Breath planned after last note: {current_note.pitch} at {original_offset:.2f}")

            # Add the (potentially shortened) current note
            if shorten_note_for_breath:
                current_note.duration.quarterLength = original_duration_ql - breath_duration_ql
            output_elements.append(current_note)

            # Add the breath if flagged
            if insert_breath_flag:
                breath_offset = current_note.offset + current_note.duration.quarterLength # After (shortened) note
                # Check for overlap with the *next original* note's start time
                can_add_breath = True
                if i + 1 < len(notes_with_lyrics):
                    if breath_offset + breath_duration_ql > notes_with_lyrics[i+1].offset + 0.001:
                        can_add_breath = False
                        logger.debug(f"Breath at {breath_offset:.2f} would overlap next note at {notes_with_lyrics[i+1].offset:.2f}. Skipping.")
                
                if can_add_breath:
                    breath_rest = note.Rest(quarterLength=breath_duration_ql)
                    breath_rest.offset = breath_offset # Set offset explicitly for later insertion
                    output_elements.append(breath_rest)
                    logger.info(f"Breath scheduled at {breath_offset:.2f} for {breath_duration_ql:.2f}qL.")
                    
        return output_elements


    def compose(self,
                midivocal_data: List[Dict], # From JSON file like vocal_note_data_ore.json
                kasi_rist_data: Dict[str, List[str]], # Lyrics per section
                processed_chord_stream: List[Dict], # To get section names for notes
                insert_breaths_opt: bool = True,
                breath_duration_ql_opt: float = DEFAULT_BREATH_DURATION_QL,
                humanize_opt: bool = True,
                humanize_template_name: Optional[str] = "vocal_ballad_smooth",
                humanize_custom_params: Optional[Dict[str, Any]] = None
                ) -> stream.Part:

        vocal_part = stream.Part(id="Vocal")
        vocal_part.insert(0, self.default_instrument)
        vocal_part.append(tempo.MetronomeMark(number=self.global_tempo))
        vocal_part.append(self.global_time_signature_obj.clone())
        # Key signature can be added if needed, but vocals often adapt

        parsed_vocal_notes_data = self._parse_midivocal_data(midivocal_data)
        if not parsed_vocal_notes_data:
            logger.warning("VocalGen: No valid notes parsed from midivocal_data. Returning empty part.")
            return vocal_part

        notes_with_lyrics: List[note.Note] = []
        current_section_name: Optional[str] = None
        current_lyrics_for_section: List[str] = []
        current_lyric_idx: int = 0
        last_lyric_assigned_offset: float = -1.001
        LYRIC_OFFSET_THRESHOLD: float = 0.005

        for note_data in parsed_vocal_notes_data:
            note_offset = note_data["offset"]
            note_pitch_str = note_data["pitch_str"]
            note_q_length = note_data["q_length"]
            note_velocity = note_data.get("velocity", 70) # Get velocity from parsed data

            # Determine section for this note using processed_chord_stream
            section_for_this_note = self._get_section_for_note_offset(note_offset, processed_chord_stream)

            if section_for_this_note != current_section_name:
                if current_section_name and current_lyric_idx < len(current_lyrics_for_section):
                     logger.warning(f"{len(current_lyrics_for_section) - current_lyric_idx} lyrics unused in section '{current_section_name}'.")
                current_section_name = section_for_this_note
                current_lyrics_for_section = kasi_rist_data.get(current_section_name, []) if current_section_name else []
                current_lyric_idx = 0
                last_lyric_assigned_offset = -1.001
                if current_section_name: logger.info(f"VocalGen: Switched to lyric section: '{current_section_name}' ({len(current_lyrics_for_section)} syllables).")
                else: logger.warning(f"VocalGen: Note at offset {note_offset:.2f} has no section in processed_stream. Lyrics may be misaligned.")

            try:
                m21_n = note.Note(note_pitch_str, quarterLength=note_q_length)
                m21_n.volume = volume.Volume(velocity=note_velocity) # Set velocity
            except Exception as e:
                logger.error(f"VocalGen: Failed to create Note for {note_pitch_str} at {note_offset}: {e}")
                continue

            if current_section_name and current_lyric_idx < len(current_lyrics_for_section):
                if abs(note_offset - last_lyric_assigned_offset) > LYRIC_OFFSET_THRESHOLD:
                    m21_n.lyric = current_lyrics_for_section[current_lyric_idx]
                    logger.debug(f"Lyric '{m21_n.lyric}' to note {m21_n.nameWithOctave} at {note_offset:.2f} (Sec: {current_section_name})")
                    current_lyric_idx += 1
                    last_lyric_assigned_offset = note_offset
                else:
                    logger.debug(f"Skipped lyric for note {m21_n.nameWithOctave} at same offset {note_offset:.2f} as previous.")
            
            m21_n.offset = note_offset # Ensure offset is set before adding to list
            notes_with_lyrics.append(m21_n)
        
        # Elements to be added to the final part (notes, rests from breaths)
        final_elements: List[Union[note.Note, note.Rest]] = []

        if insert_breaths_opt:
            final_elements = self._insert_breaths(notes_with_lyrics, breath_duration_ql_opt)
        else:
            final_elements = notes_with_lyrics # type: ignore

        if humanize_opt:
            # Filter out Rests before sending to humanization if it only expects Notes/Chords
            notes_only_for_humanize = [el for el in final_elements if isinstance(el, note.Note)]
            humanized_notes = apply_humanization_to_notes(notes_only_for_humanize, humanize_template_name, humanize_custom_params)
            
            # Reconstruct final_elements, preserving rests and using humanized notes
            temp_final_elements = []
            h_idx = 0
            for el in final_elements:
                if isinstance(el, note.Note):
                    if h_idx < len(humanized_notes):
                        temp_final_elements.append(humanized_notes[h_idx])
                        h_idx += 1
                    else: # Should not happen if logic is correct
                        temp_final_elements.append(el) 
                else: # Rest
                    temp_final_elements.append(el)
            final_elements = temp_final_elements


        # Insert all elements into the part, music21 will handle sorting by offset
        for el in final_elements:
            vocal_part.insert(el.offset, el)
        
        logger.info(f"VocalGen: Finished. Final part has {len(vocal_part.flatten().notesAndRests)} elements.")
        return vocal_part

# --- END OF FILE generator/vocal_generator.py ---
