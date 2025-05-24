# --- START OF FILE generator/vocal_generator.py (インポート形式修正 v5) ---
import music21 # name 'music21' is not defined エラー対策
from typing import List, Dict, Optional, Any, Tuple, Union, cast 

# music21 のサブモジュールを正しい形式でインポート
import music21.stream as stream
import music21.note as note
import music21.pitch as pitch
import music21.meter as meter
import music21.duration as duration
import music21.instrument as m21instrument # check_imports.py の期待する形式
import music21.tempo as tempo
import music21.key as key
import music21.expressions as expressions
import music21.volume as m21volume
import music21.articulations as articulations
import music21.dynamics as dynamics
# import music21.chord as m21chord # このファイルでは m21chord を直接使用していないため、一旦コメントアウト
from music21 import exceptions21 

import logging
import json
import re
import copy
import random
import math 

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

MIN_NOTE_DURATION_QL = 0.125 
DEFAULT_BREATH_DURATION_QL: float = 0.25
MIN_DURATION_FOR_BREATH_AFTER_NOTE_QL: float = 1.0 
PUNCTUATION_FOR_BREATH: Tuple[str, ...] = ('、', '。', '！', '？', ',', '.', '!', '?')


try:
    from utilities.core_music_utils import get_time_signature_object
except ImportError:
    logger_fallback_util = logging.getLogger(__name__ + ".fallback_core_util")
    logger_fallback_util.warning("VocalGen: Could not import get_time_signature_object from utilities. Using basic fallback.")
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: 
        if not ts_str: ts_str = "4/4"; return meter.TimeSignature(ts_str)
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")

try:
    from utilities.humanizer import apply_humanization_to_element 
except ImportError:
    logger_fallback_humanizer = logging.getLogger(__name__ + ".fallback_humanizer_vocal")
    logger_fallback_humanizer.warning("VocalGen: Could not import humanizer.apply_humanization_to_element. Humanization will be basic.")
    def apply_humanization_to_element(element, template_name=None, custom_params=None): return element


class VocalGenerator:
    def __init__(self,
                 default_instrument=m21instrument.Vocalist(), 
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        try:
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except NameError: 
             logger.error("VocalGen init: get_time_signature_object not available. Using music21.meter directly.")
             self.global_time_signature_obj = meter.TimeSignature(global_time_signature)
        except Exception as e_ts_init:
            logger.error(f"VocalGen init: Error initializing time signature from '{global_time_signature}': {e_ts_init}. Defaulting to 4/4.", exc_info=True)
            self.global_time_signature_obj = meter.TimeSignature("4/4")


    def _parse_midivocal_data(self, midivocal_data: List[Dict]) -> List[Dict]:
        parsed_notes = []
        for item_idx, item in enumerate(midivocal_data):
            try:
                offset = float(item.get("offset", item.get("Offset", 0.0))) 
                pitch_name = str(item.get("pitch", item.get("Pitch", "")))
                length = float(item.get("length", item.get("Length", 0.0)))
                velocity = int(item.get("velocity", item.get("Velocity", 70)))

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
        for block in processed_stream:
            block_start = block.get("offset", 0.0)
            block_end = block_start + block.get("q_length", 0.0)
            if block_start <= note_offset < block_end:
                return block.get("section_name")
        logger.warning(f"VocalGen: No section found in processed_stream for note offset {note_offset:.2f}")
        return None

    def _insert_breaths(self, notes_with_lyrics: List[note.Note], breath_duration_ql: float) -> List[Union[note.Note, note.Rest]]: 
        if not notes_with_lyrics: return []
        logger.info(f"Inserting breaths (duration: {breath_duration_ql}qL).")
        
        output_elements: List[Union[note.Note, note.Rest]] = [] 
        
        for i, current_note_obj in enumerate(notes_with_lyrics): 
            original_offset = current_note_obj.offset
            original_duration_ql = current_note_obj.duration.quarterLength
            
            insert_breath_flag = False
            shorten_note_for_breath = False

            if current_note_obj.lyric and any(punc in current_note_obj.lyric for punc in PUNCTUATION_FOR_BREATH):
                if original_duration_ql > breath_duration_ql + MIN_NOTE_DURATION_QL / 4: 
                    shorten_note_for_breath = True
                    insert_breath_flag = True
                    logger.debug(f"Breath planned after note (punctuation): {current_note_obj.pitch} at {original_offset:.2f}")
                else:
                    logger.debug(f"Note {current_note_obj.pitch} at {original_offset:.2f} too short for breath (punctuation).")
            
            if not insert_breath_flag and original_duration_ql >= MIN_DURATION_FOR_BREATH_AFTER_NOTE_QL:
                if i + 1 < len(notes_with_lyrics):
                    next_note_obj = notes_with_lyrics[i+1] 
                    gap_to_next = next_note_obj.offset - (original_offset + original_duration_ql)
                    if gap_to_next < breath_duration_ql * 0.75: 
                        if original_duration_ql > breath_duration_ql + MIN_NOTE_DURATION_QL / 4:
                            shorten_note_for_breath = True
                            insert_breath_flag = True
                            logger.debug(f"Breath planned after note (long note, small gap): {current_note_obj.pitch} at {original_offset:.2f}")
                        else:
                            logger.debug(f"Note {current_note_obj.pitch} at {original_offset:.2f} too short for breath (long note).")
                else: 
                    insert_breath_flag = True 
                    shorten_note_for_breath = False 
                    logger.debug(f"Breath planned after last note: {current_note_obj.pitch} at {original_offset:.2f}")

            if shorten_note_for_breath:
                current_note_obj.duration.quarterLength = original_duration_ql - breath_duration_ql
            output_elements.append(current_note_obj)

            if insert_breath_flag:
                breath_offset = current_note_obj.offset + current_note_obj.duration.quarterLength 
                can_add_breath = True
                if i + 1 < len(notes_with_lyrics):
                    if breath_offset + breath_duration_ql > notes_with_lyrics[i+1].offset + 0.001:
                        can_add_breath = False
                        logger.debug(f"Breath at {breath_offset:.2f} would overlap next note at {notes_with_lyrics[i+1].offset:.2f}. Skipping.")
                
                if can_add_breath:
                    breath_rest = note.Rest(quarterLength=breath_duration_ql) 
                    breath_rest.offset = breath_offset 
                    output_elements.append(breath_rest)
                    logger.info(f"Breath scheduled at {breath_offset:.2f} for {breath_duration_ql:.2f}qL.")
                    
        return output_elements


    def compose(self,
                midivocal_data: List[Dict], 
                kasi_rist_data: Dict[str, List[str]], 
                processed_chord_stream: List[Dict], 
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

        for note_data_item in parsed_vocal_notes_data: 
            note_offset = note_data_item["offset"]
            note_pitch_str = note_data_item["pitch_str"]
            note_q_length = note_data_item["q_length"]
            note_velocity = note_data_item.get("velocity", 70) 

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
                m21_n_obj = note.Note(note_pitch_str, quarterLength=note_q_length) 
                m21_n_obj.volume = m21volume.Volume(velocity=note_velocity) 
            except Exception as e:
                logger.error(f"VocalGen: Failed to create Note for {note_pitch_str} at {note_offset}: {e}")
                continue

            if current_section_name and current_lyric_idx < len(current_lyrics_for_section):
                if abs(note_offset - last_lyric_assigned_offset) > LYRIC_OFFSET_THRESHOLD:
                    m21_n_obj.lyric = current_lyrics_for_section[current_lyric_idx]
                    logger.debug(f"Lyric '{m21_n_obj.lyric}' to note {m21_n_obj.nameWithOctave} at {note_offset:.2f} (Sec: {current_section_name})")
                    current_lyric_idx += 1
                    last_lyric_assigned_offset = note_offset
                else:
                    logger.debug(f"Skipped lyric for note {m21_n_obj.nameWithOctave} at same offset {note_offset:.2f} as previous.")
            
            m21_n_obj.offset = note_offset 
            notes_with_lyrics.append(m21_n_obj)
        
        final_elements: List[Union[note.Note, note.Rest]] = [] 

        if insert_breaths_opt:
            final_elements = self._insert_breaths(notes_with_lyrics, breath_duration_ql_opt)
        else:
            final_elements = cast(List[Union[note.Note, note.Rest]], notes_with_lyrics) 

        if humanize_opt:
            temp_humanized_elements = []
            try:
                for el_item in final_elements: 
                    if isinstance(el_item, note.Note): 
                        humanized_el = apply_humanization_to_element(el_item, template_name=humanize_template_name, custom_params=humanize_custom_params)
                        temp_humanized_elements.append(humanized_el)
                    else: 
                        temp_humanized_elements.append(el_item)
                final_elements = temp_humanized_elements
            except NameError: 
                 logger.warning("VocalGen: apply_humanization_to_element not available, skipping humanization for vocal notes.")
            except Exception as e_hum:
                 logger.error(f"VocalGen: Error during humanization: {e_hum}", exc_info=True)


        for el_item_final in final_elements: 
            vocal_part.insert(el_item_final.offset, el_item_final)
        
        logger.info(f"VocalGen: Finished. Final part has {len(list(vocal_part.flat.notesAndRests))} elements.") 
        return vocal_part

# --- END OF FILE generator/vocal_generator.py ---
