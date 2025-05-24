# --- START OF FILE generator/guitar_generator.py (ヒューマナイズ外部化版) ---
# import music21 # 不要なため削除
from typing import List, Dict, Optional, Tuple, Any, Sequence, Union

# music21 のサブモジュールを個別にインポート
from music21 import stream
from music21 import note
from music21 import harmony
from music21 import pitch
from music21 import meter
from music21 import duration
from music21 import instrument as m21instrument # 指摘された通りエイリアスでインポート
from music21 import scale
from music21 import interval
from music21 import tempo
from music21 import key
from music21 import chord as m21chord # 指摘された通りエイリアスでインポート
from music21 import articulations
from music21 import volume as m21volume # 他のファイルとの整合性を考慮しエイリアスを維持
from music21 import expressions

import random
import logging
# import numpy as np # humanizer.py に移管
# import copy      # humanizer.py に移管

# ユーティリティのインポート
try:
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES 
except ImportError:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("GuitarGen: Could not import from utilities. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: # meter を使用
        if not ts_str: ts_str = "4/4"; return meter.TimeSignature(ts_str)
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
        if not label or label.strip().lower() in ["rest", "n.c.", "nc", "none"]: return None
        return label.strip()
    def apply_humanization_to_part(part, template_name=None, custom_params=None): return part
    HUMANIZATION_TEMPLATES = {}

logger = logging.getLogger(__name__)

# --- 定数 ---
DEFAULT_GUITAR_OCTAVE_RANGE: Tuple[int, int] = (2, 5)
GUITAR_STRUM_DELAY_QL: float = 0.02
MIN_STRUM_NOTE_DURATION_QL: float = 0.05
STYLE_BLOCK_CHORD = "block_chord"; STYLE_STRUM_BASIC = "strum_basic"; STYLE_ARPEGGIO = "arpeggio"
STYLE_POWER_CHORDS = "power_chords"; STYLE_MUTED_RHYTHM = "muted_rhythm"; STYLE_SINGLE_NOTE_LINE = "single_note_line"


class GuitarGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 default_instrument=m21instrument.AcousticGuitar(), # m21instrument を使用
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.rhythm_library = rhythm_library if rhythm_library is not None else {}
        if "guitar_default_quarters" not in self.rhythm_library:
             self.rhythm_library["guitar_default_quarters"] = {"description": "Default quarter note strums/hits", "pattern": [{"offset":i, "duration":1.0, "velocity_factor":0.8-(i%2*0.05)} for i in range(4)]}
             logger.info("GuitarGen: Added 'guitar_default_quarters' to rhythm_library.")
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _get_guitar_friendly_voicing(
        self, cs: harmony.ChordSymbol, num_strings: int = 6, # m21_cs を cs に変更 (ローカル変数名)
        preferred_octave_bottom: int = 2, max_octave_top: int = 5,
        voicing_style: str = "standard"
    ) -> List[pitch.Pitch]: # pitch を使用
        if not cs or not cs.pitches: return []
        original_pitches = list(cs.pitches); root = cs.root()
        voiced_pitches: List[pitch.Pitch] = [] # pitch を使用
        if voicing_style == "power_chord_root_fifth" and root:
            p_root = pitch.Pitch(root.name) # pitch を使用
            while p_root.ps < pitch.Pitch(f"E{preferred_octave_bottom}").ps: p_root.octave += 1 # pitch を使用
            while p_root.ps > pitch.Pitch(f"A{preferred_octave_bottom+1}").ps: p_root.octave -=1 # pitch を使用
            p_fifth = p_root.transpose(interval.PerfectFifth()) # interval を使用
            p_octave_root = p_root.transpose(interval.PerfectOctave()) # interval を使用
            voiced_pitches = [p_root, p_fifth]
            if p_octave_root.ps <= pitch.Pitch(f"G{max_octave_top}").ps: voiced_pitches.append(p_octave_root) # pitch を使用
            return sorted(list(set(voiced_pitches)), key=lambda p: p.ps)[:num_strings]
        try:
            temp_chord = cs.semiClosedPosition(forceOctave=preferred_octave_bottom, inPlace=False) if voicing_style == "open" and hasattr(cs, 'semiClosedPosition') else cs.closedPosition(forceOctave=preferred_octave_bottom, inPlace=False)
            candidate_pitches = sorted(list(temp_chord.pitches), key=lambda p: p.ps)
        except Exception: candidate_pitches = sorted(original_pitches, key=lambda p:p.ps)
        if not candidate_pitches: return []
        bottom_target_ps = pitch.Pitch(f"E{preferred_octave_bottom}").ps # pitch を使用
        if candidate_pitches[0].ps < bottom_target_ps - 6:
            oct_shift = round((bottom_target_ps - candidate_pitches[0].ps) / 12.0)
            candidate_pitches = [p.transpose(oct_shift * 12) for p in candidate_pitches]; candidate_pitches.sort(key=lambda p: p.ps)
        selected_dict: Dict[str, pitch.Pitch] = {} # pitch を使用
        for p_cand in candidate_pitches:
            if p_cand.name not in selected_dict and pitch.Pitch(f"E{DEFAULT_GUITAR_OCTAVE_RANGE[0]-1}").ps <= p_cand.ps <= pitch.Pitch(f"G{DEFAULT_GUITAR_OCTAVE_RANGE[1]+1}").ps: # pitch を使用
                selected_dict[p_cand.name] = p_cand
        voiced_pitches = sorted(list(selected_dict.values()), key=lambda p:p.ps)
        return voiced_pitches[:num_strings]


    def _create_notes_from_event(
        self, cs: harmony.ChordSymbol, guitar_params: Dict[str, Any], # m21_cs を cs に変更
        event_abs_offset: float, event_duration_ql: float, event_velocity: int
    ) -> List[Union[note.Note, m21chord.Chord]]: # note, m21chord を使用
        notes_for_event: List[Union[note.Note, m21chord.Chord]] = [] # note, m21chord を使用
        style = guitar_params.get("guitar_style", STYLE_BLOCK_CHORD)
        
        num_strings = guitar_params.get("guitar_num_strings", 6)
        preferred_octave = guitar_params.get("guitar_target_octave", 3)
        voicing_style_name = guitar_params.get("guitar_voicing_style", "standard")
        chord_pitches = self._get_guitar_friendly_voicing(cs, num_strings, preferred_octave, voicing_style_name)
        if not chord_pitches: return []

        if style == STYLE_BLOCK_CHORD:
            ch = m21chord.Chord(chord_pitches, quarterLength=event_duration_ql * 0.9) # m21chord を使用
            for n_in_ch in ch.notes: n_in_ch.volume.velocity = event_velocity # volume を使用 (m21volumeではない)
            ch.offset = event_abs_offset 
            notes_for_event.append(ch)
        elif style == STYLE_STRUM_BASIC:
            is_down = guitar_params.get("strum_direction", "down").lower() == "down"
            play_order = list(reversed(chord_pitches)) if is_down else chord_pitches
            for i, p_obj in enumerate(play_order):
                n = note.Note(p_obj) # note を使用
                n.duration = duration.Duration(quarterLength=max(MIN_STRUM_NOTE_DURATION_QL, event_duration_ql * 0.9)) # duration を使用
                n.offset = event_abs_offset + (i * GUITAR_STRUM_DELAY_QL) 
                vel_adj = int(((len(play_order)-1-i)/(len(play_order)-1)*10)-5) if is_down and len(play_order)>1 else (int((i/(len(play_order)-1)*10)-5) if len(play_order)>1 else 0)
                n.volume = m21volume.Volume(velocity=max(1, min(127, event_velocity + vel_adj))) # m21volume を使用
                notes_for_event.append(n)
        elif style == STYLE_ARPEGGIO:
            arp_pattern_type = guitar_params.get("arpeggio_type", "up") # 文字列またはリストを想定
            arp_note_dur_ql = guitar_params.get("arpeggio_note_duration_ql", 0.5)
            
            ordered_arp_pitches: List[pitch.Pitch] = [] # pitch を使用
            if isinstance(arp_pattern_type, list): # インデックスのリストの場合
                 ordered_arp_pitches = [chord_pitches[idx % len(chord_pitches)] for idx in arp_pattern_type if chord_pitches]
            elif arp_pattern_type == "down":
                ordered_arp_pitches = list(reversed(chord_pitches))
            elif arp_pattern_type == "up_down" and len(chord_pitches) > 2 : # up_down を追加
                ordered_arp_pitches = chord_pitches + list(reversed(chord_pitches[1:-1]))
            else: # "up" またはデフォルト
                ordered_arp_pitches = chord_pitches

            current_offset_in_event = 0.0; arp_idx = 0
            while current_offset_in_event < event_duration_ql and ordered_arp_pitches:
                p_play = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                actual_arp_dur = min(arp_note_dur_ql, event_duration_ql - current_offset_in_event)
                if actual_arp_dur < MIN_NOTE_DURATION_QL / 4: break
                n = note.Note(p_play, quarterLength=actual_arp_dur * 0.95) # note を使用
                n.volume.velocity = event_velocity # volume を使用 (m21volumeではない)
                n.offset = event_abs_offset + current_offset_in_event 
                notes_for_event.append(n)
                current_offset_in_event += arp_note_dur_ql; arp_idx += 1
        elif style == STYLE_MUTED_RHYTHM:
            mute_note_dur = guitar_params.get("mute_note_duration_ql", 0.1)
            mute_interval = guitar_params.get("mute_interval_ql", 0.25)
            t_mute = 0.0
            if not chord_pitches: return [] # chord_pitchesが空の場合は何もしない
            root_mute = chord_pitches[0] # 少なくとも1音はあるはず
            while t_mute < event_duration_ql:
                actual_mute_dur = min(mute_note_dur, event_duration_ql - t_mute)
                if actual_mute_dur < MIN_NOTE_DURATION_QL / 8: break
                n = note.Note(root_mute); n.articulations = [articulations.Staccatissimo()] # note, articulations を使用
                n.duration.quarterLength = actual_mute_dur # duration を使用
                n.volume.velocity = int(event_velocity * 0.6) + random.randint(-5,5) # volume を使用 (m21volumeではない)
                n.offset = event_abs_offset + t_mute 
                notes_for_event.append(n)
                t_mute += mute_interval
        return notes_for_event


    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part: # stream を使用
        guitar_part = stream.Part(id="Guitar") # stream を使用
        guitar_part.insert(0, self.default_instrument)
        guitar_part.insert(0, tempo.MetronomeMark(number=self.global_tempo)) # tempo を使用
        guitar_part.insert(0, self.global_time_signature_obj.clone())

        if not processed_chord_stream: return guitar_part
        logger.info(f"GuitarGen: Starting for {len(processed_chord_stream)} blocks.")

        all_generated_elements_for_part: List[Union[note.Note, m21chord.Chord]] = [] # note, m21chord を使用

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", 4.0))
            chord_label_str = blk_data.get("chord_label", "C")
            guitar_params = blk_data.get("part_params", {}).get("guitar", {})
            if not guitar_params: continue

            sanitized_label = sanitize_chord_label(chord_label_str)
            cs_obj: Optional[harmony.ChordSymbol] = None # harmony を使用
            if sanitized_label:
                try: 
                    cs_obj = harmony.ChordSymbol(sanitized_label) # harmony を使用
                    if not cs_obj.pitches: cs_obj = None # ピッチがない場合はNone扱い
                except Exception: 
                    cs_obj = None
            if cs_obj is None: # None の場合はこのブロックをスキップ
                logger.warning(f"GuitarGen: Skipping block {blk_idx+1} due to invalid chord label: '{chord_label_str}'")
                continue


            rhythm_key = guitar_params.get("guitar_rhythm_key", "guitar_default_quarters")
            rhythm_details = self.rhythm_library.get(rhythm_key, self.rhythm_library.get("guitar_default_quarters"))
            if not rhythm_details or "pattern" not in rhythm_details: continue
            pattern_events = rhythm_details.get("pattern", [])

            for event_def in pattern_events:
                event_offset_in_pattern = float(event_def.get("offset", 0.0))
                event_duration_in_pattern = float(event_def.get("duration", 1.0))
                event_velocity_factor = float(event_def.get("velocity_factor", 1.0))
                abs_event_start_offset = block_offset_ql + event_offset_in_pattern
                max_possible_event_dur = block_duration_ql - event_offset_in_pattern
                actual_event_dur = min(event_duration_in_pattern, max_possible_event_dur)
                if actual_event_dur < MIN_NOTE_DURATION_QL / 2: continue
                event_base_velocity = int(guitar_params.get("guitar_velocity", 70) * event_velocity_factor)

                generated_elements = self._create_notes_from_event(
                    cs_obj, guitar_params, abs_event_start_offset, actual_event_dur, event_base_velocity
                )
                all_generated_elements_for_part.extend(generated_elements)
        
        global_guitar_params = processed_chord_stream[0].get("part_params", {}).get("guitar", {}) if processed_chord_stream else {}
        if global_guitar_params.get("guitar_humanize", global_guitar_params.get("humanize", False)): # humanizeキーも考慮
            h_template = global_guitar_params.get("guitar_humanize_style_template", 
                                                 global_guitar_params.get("humanize_style_template", "default_guitar_subtle")) # humanize_style_templateも考慮
            h_custom = {
                k.replace("default_guitar_humanize_", "").replace("guitar_humanize_", "").replace("humanize_", ""): v # humanize_も除去
                for k, v in global_guitar_params.items()
                if (k.startswith("guitar_humanize_") or k.startswith("default_guitar_humanize_") or k.startswith("humanize_")) 
                   and not k.endswith("_template") and not k.endswith("humanize") and not k.endswith("_opt") # _optも除外
            }
            logger.info(f"GuitarGen: Humanizing guitar part (template: {h_template}, custom: {h_custom})")
            
            temp_part_for_humanize = stream.Part() # stream を使用
            for el in all_generated_elements_for_part:
                temp_part_for_humanize.insert(el.offset, el) 
            
            guitar_part = apply_humanization_to_part(temp_part_for_humanize, template_name=h_template, custom_params=h_custom)
            guitar_part.id = "Guitar" 
            if not guitar_part.getElementsByClass(m21instrument.Instrument).first(): # m21instrument を使用
                guitar_part.insert(0, self.default_instrument)
            if not guitar_part.getElementsByClass(tempo.MetronomeMark).first(): # tempo を使用
                guitar_part.insert(0, tempo.MetronomeMark(number=self.global_tempo)) # tempo を使用
            if not guitar_part.getElementsByClass(meter.TimeSignature).first(): # meter を使用
                guitar_part.insert(0, self.global_time_signature_obj.clone())
            # KeySignature は通常Scoreレベルで設定されるが、Partにあっても問題はない
            # if not guitar_part.getElementsByClass(key.Key).first():
            #     # 最初のブロックのキー情報を取得して設定するなどの処理
            #     first_block_tonic = processed_chord_stream[0].get("tonic_of_section", "C") if processed_chord_stream else "C"
            #     first_block_mode = processed_chord_stream[0].get("mode", "major") if processed_chord_stream else "major"
            #     guitar_part.insert(0, key.Key(first_block_tonic, first_block_mode))


        else: 
            for el in all_generated_elements_for_part:
                guitar_part.insert(el.offset, el)

        logger.info(f"GuitarGen: Finished. Part has {len(guitar_part.flatten().notesAndRests)} elements.")
        return guitar_part

# --- END OF FILE generator/guitar_generator.py ---
