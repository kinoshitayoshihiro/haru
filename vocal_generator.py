# --- START OF FILE generator/vocal_generator.py (2023-05-23 強化案) ---
# import music21 # 不要なため削除
from typing import List, Dict, Optional, Any, Tuple, Union, cast # cast を追加

# music21 のサブモジュールを個別にインポート
from music21 import stream
from music21 import note
from music21 import pitch
from music21 import meter
from music21 import duration
from music21 import instrument as m21instrument
from music21 import tempo
from music21 import key
from music21 import expressions
from music21 import volume as m21volume
from music21 import articulations
from music21 import dynamics
from music21 import chord as m21chord # update_imports.py の指摘に基づき追加
from music21 import exceptions21 # 元のコードで使用されているため追加

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

MIN_NOTE_DURATION_QL = 0.125 
DEFAULT_BREATH_DURATION_QL: float = 0.25
MIN_DURATION_FOR_BREATH_AFTER_NOTE_QL: float = 1.0 
PUNCTUATION_FOR_BREATH: Tuple[str, ...] = ('、', '。', '！', '？', ',', '.', '!', '?')

# --- Humanization functions (integrated for now, can be in a separate humanizer.py) ---
# utilities.humanizer を使用するため、ここの定義は削除またはコメントアウトを推奨
# def generate_fractional_noise(...): ...
# HUMANIZATION_TEMPLATES_VOCAL = {...}
# def apply_humanization_to_notes(...): ...
# --- End Humanization functions ---

# ユーティリティのインポート (get_time_signature_objectなどが必要な場合)
try:
    from utilities.core_music_utils import get_time_signature_object
except ImportError:
    logger_fallback_util = logging.getLogger(__name__ + ".fallback_core_util")
    logger_fallback_util.warning("VocalGen: Could not import get_time_signature_object from utilities. Using basic fallback.")
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: # meter を使用
        if not ts_str: ts_str = "4/4"; return meter.TimeSignature(ts_str)
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")

# VocalGenerator が Humanizer を利用する場合のインポート
try:
    from utilities.humanizer import apply_humanization_to_element # 個々の音符に適用する場合
    # from utilities.humanizer import apply_humanization_to_part # パート全体に適用する場合
except ImportError:
    logger_fallback_humanizer = logging.getLogger(__name__ + ".fallback_humanizer")
    logger_fallback_humanizer.warning("VocalGen: Could not import humanizer functions. Humanization might not work as expected.")
    def apply_humanization_to_element(element, template_name=None, custom_params=None): return element
    # def apply_humanization_to_part(part, template_name=None, custom_params=None): return part


class VocalGenerator:
    def __init__(self,
                 default_instrument=m21instrument.Vocalist(), # m21instrument を使用
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _parse_midivocal_data(self, midivocal_data: List[Dict]) -> List[Dict]:
        parsed_notes = []
        for item_idx, item in enumerate(midivocal_data):
            try:
                offset = float(item["Offset"]) # 元のキー名 "Offset" を使用
                pitch_name = str(item["Pitch"])  # 元のキー名 "Pitch" を使用
                length = float(item["Length"]) # 元のキー名 "Length" を使用
                velocity = int(item.get("Velocity", 70))

                if not pitch_name: logger.warning(f"Vocal note #{item_idx+1} empty pitch. Skip."); continue
                try: pitch.Pitch(pitch_name) # pitch を使用
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

    def _insert_breaths(self, notes_with_lyrics: List[note.Note], breath_duration_ql: float) -> List[Union[note.Note, note.Rest]]: # note を使用
        if not notes_with_lyrics: return []
        logger.info(f"Inserting breaths (duration: {breath_duration_ql}qL).")
        
        output_elements: List[Union[note.Note, note.Rest]] = [] # note を使用
        
        for i, current_note in enumerate(notes_with_lyrics):
            original_offset = current_note.offset
            original_duration_ql = current_note.duration.quarterLength
            
            insert_breath_flag = False
            shorten_note_for_breath = False

            if current_note.lyric and any(punc in current_note.lyric for punc in PUNCTUATION_FOR_BREATH):
                if original_duration_ql > breath_duration_ql + MIN_NOTE_DURATION_QL / 4: 
                    shorten_note_for_breath = True
                    insert_breath_flag = True
                    logger.debug(f"Breath planned after note (punctuation): {current_note.pitch} at {original_offset:.2f}")
                else:
                    logger.debug(f"Note {current_note.pitch} at {original_offset:.2f} too short for breath (punctuation).")
            
            if not insert_breath_flag and original_duration_ql >= MIN_DURATION_FOR_BREATH_AFTER_NOTE_QL:
                if i + 1 < len(notes_with_lyrics):
                    next_note = notes_with_lyrics[i+1]
                    gap_to_next = next_note.offset - (original_offset + original_duration_ql)
                    if gap_to_next < breath_duration_ql * 0.75: 
                        if original_duration_ql > breath_duration_ql + MIN_NOTE_DURATION_QL / 4:
                            shorten_note_for_breath = True
                            insert_breath_flag = True
                            logger.debug(f"Breath planned after note (long note, small gap): {current_note.pitch} at {original_offset:.2f}")
                        else:
                            logger.debug(f"Note {current_note.pitch} at {original_offset:.2f} too short for breath (long note).")
                else: 
                    insert_breath_flag = True 
                    shorten_note_for_breath = False 
                    logger.debug(f"Breath planned after last note: {current_note.pitch} at {original_offset:.2f}")

            if shorten_note_for_breath:
                current_note.duration.quarterLength = original_duration_ql - breath_duration_ql
            output_elements.append(current_note)

            if insert_breath_flag:
                breath_offset = current_note.offset + current_note.duration.quarterLength 
                can_add_breath = True
                if i + 1 < len(notes_with_lyrics):
                    if breath_offset + breath_duration_ql > notes_with_lyrics[i+1].offset + 0.001:
                        can_add_breath = False
                        logger.debug(f"Breath at {breath_offset:.2f} would overlap next note at {notes_with_lyrics[i+1].offset:.2f}. Skipping.")
                
                if can_add_breath:
                    breath_rest = note.Rest(quarterLength=breath_duration_ql) # note を使用
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
                humanize_opt: bool = True, # このオプションは modular_composer から渡される
                humanize_template_name: Optional[str] = "vocal_ballad_smooth", # 同上
                humanize_custom_params: Optional[Dict[str, Any]] = None # 同上
                ) -> stream.Part: # stream を使用

        vocal_part = stream.Part(id="Vocal") # stream を使用
        vocal_part.insert(0, self.default_instrument)
        vocal_part.append(tempo.MetronomeMark(number=self.global_tempo)) # tempo を使用
        vocal_part.append(self.global_time_signature_obj.clone())

        parsed_vocal_notes_data = self._parse_midivocal_data(midivocal_data)
        if not parsed_vocal_notes_data:
            logger.warning("VocalGen: No valid notes parsed from midivocal_data. Returning empty part.")
            return vocal_part

        notes_with_lyrics: List[note.Note] = [] # note を使用
        current_section_name: Optional[str] = None
        current_lyrics_for_section: List[str] = []
        current_lyric_idx: int = 0
        last_lyric_assigned_offset: float = -1.001
        LYRIC_OFFSET_THRESHOLD: float = 0.005

        for note_data in parsed_vocal_notes_data:
            note_offset = note_data["offset"]
            note_pitch_str = note_data["pitch_str"]
            note_q_length = note_data["q_length"]
            note_velocity = note_data.get("velocity", 70) 

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
                m21_n = note.Note(note_pitch_str, quarterLength=note_q_length) # note を使用
                m21_n.volume = m21volume.Volume(velocity=note_velocity) # m21volume を使用
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
            
            m21_n.offset = note_offset 
            notes_with_lyrics.append(m21_n)
        
        final_elements: List[Union[note.Note, note.Rest]] = [] # note を使用

        if insert_breaths_opt:
            final_elements = self._insert_breaths(notes_with_lyrics, breath_duration_ql_opt)
        else:
            final_elements = cast(List[Union[note.Note, note.Rest]], notes_with_lyrics) # cast を使用

        if humanize_opt:
            # apply_humanization_to_element を使用して個々の音符をヒューマナイズ
            temp_humanized_elements = []
            for el in final_elements:
                if isinstance(el, note.Note): # note を使用
                    # humanize_custom_params には、テンプレートに加えて上書きするパラメータが含まれる想定
                    # apply_humanization_to_element はテンプレート名とカスタムパラメータの両方を受け取れるように修正が必要
                    # ここでは、humanize_custom_params が HUMANIZATION_TEMPLATES の内容を上書きした最終的なパラメータ辞書であると仮定
                    # または、apply_humanization_to_element がテンプレート名と個別オーバーライドを分けて受け取るようにする
                    # VocalGenerator内の apply_humanization_to_notes のロジックを参考にする
                    
                    # 修正案: humanizer.py の apply_humanization_to_element を使う
                    # humanize_custom_params は、テンプレートで定義されたキーを上書きする辞書
                    # template_name は modular_composer から渡される
                    humanized_el = apply_humanization_to_element(el, template_name=humanize_template_name, custom_params=humanize_custom_params)
                    temp_humanized_elements.append(humanized_el)
                else: # Rest
                    temp_humanized_elements.append(el)
            final_elements = temp_humanized_elements


        for el in final_elements:
            vocal_part.insert(el.offset, el)
        
        logger.info(f"VocalGen: Finished. Final part has {len(vocal_part.flatten().notesAndRests)} elements.")
        return vocal_part

# --- END OF FILE generator/vocal_generator.py ---
