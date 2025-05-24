# --- START OF FILE generator/bass_generator.py (ヒューマナイズ外部化・修正版) ---
from __future__ import annotations
"""bass_generator.py – streamlined rewrite
Generates a **bass part** for the modular composer pipeline.
The heavy lifting (walking line, root-fifth, etc.) is delegated to
generator.bass_utils.generate_bass_measure so that this class
mainly decides **which style to use when**.
"""
from typing import Sequence, Dict, Any, Optional, List, Union, cast # cast を追加

import random
import logging

# music21 のサブモジュールを正しい形式でインポート
import music21.stream as stream
import music21.harmony as harmony
import music21.note as note
import music21.tempo as tempo
import music21.meter as meter
import music21.instrument as m21instrument # 指摘された形式
import music21.key as key
import music21.pitch as pitch # bass_utils.py で使用されているため、ここでも必要になる可能性を考慮

# ユーティリティのインポート
try:
    from .bass_utils import generate_bass_measure 
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.error(f"BassGenerator: Failed to import required modules: {e}")
    def generate_bass_measure(*args, **kwargs) -> List[note.Note]: return []
    def apply_humanization_to_part(part, *args, **kwargs) -> stream.Part: # stream.Part を返すように修正
        if isinstance(part, stream.Part):
            return part
        return stream.Part()
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature("4/4") 
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: 
        if not label or label.strip().lower() in ["rest", "n.c.", "nc", "none"]: return None
        return label.strip()
    MIN_NOTE_DURATION_QL = 0.125
    HUMANIZATION_TEMPLATES = {}


logger = logging.getLogger(__name__)

class BassGenerator:
    def __init__(
        self,
        rhythm_library: Optional[Dict[str, Dict]] = None,
        default_instrument = m21instrument.AcousticBass(), 
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        global_key_tonic: str = "C", 
        global_key_mode: str = "major",
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rhythm_library = rhythm_library if rhythm_library else {}
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        self.global_key_tonic = global_key_tonic
        self.global_key_mode = global_key_mode
        self.rng = rng or random.Random()
        
        if "bass_quarter_notes" not in self.rhythm_library:
            self.rhythm_library["bass_quarter_notes"] = {
                "description": "Default quarter note roots for bass.",
                "pattern": [
                    {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"},
                    {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}
                ]
            }
            logger.info("BassGenerator: Added 'bass_quarter_notes' to rhythm_library.")


    def _select_style(self, bass_params: Dict[str, Any], blk_musical_intent: Dict[str, Any]) -> str:
        if "style" in bass_params and bass_params["style"]:
            return bass_params["style"]
        intensity = blk_musical_intent.get("intensity", "medium").lower()
        if intensity in {"low", "medium_low"}: return "root_only"
        if intensity in {"medium"}: return "root_fifth"
        return "walking"

    def compose(self, processed_blocks: Sequence[Dict[str, Any]]) -> stream.Part:
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo)) 
        bass_part.insert(0, self.global_time_signature_obj.clone())
        
        first_block_tonic = processed_blocks[0].get("tonic_of_section", self.global_key_tonic) if processed_blocks else self.global_key_tonic
        first_block_mode = processed_blocks[0].get("mode", self.global_key_mode) if processed_blocks else self.global_key_mode
        bass_part.insert(0, key.Key(first_block_tonic, first_block_mode)) 

        current_total_offset = 0.0

        for i, blk_data in enumerate(processed_blocks):
            bass_params = blk_data.get("part_params", {}).get("bass", {})
            if not bass_params:
                current_total_offset += blk_data.get("q_length", 0.0)
                continue

            chord_label_str = blk_data.get("chord_label", "C")
            block_q_length = blk_data.get("q_length", 4.0)
            musical_intent = blk_data.get("musical_intent", {})
            
            selected_style = self._select_style(bass_params, musical_intent)
            
            cs_now_obj: Optional[harmony.ChordSymbol] = None # 変数名を変更
            sanitized_label = sanitize_chord_label(chord_label_str)
            if sanitized_label:
                try:
                    cs_now_obj = harmony.ChordSymbol(sanitized_label)
                    if not cs_now_obj.pitches: 
                        cs_now_obj = None
                except Exception:
                    cs_now_obj = None
            
            if cs_now_obj is None:
                logger.warning(f"BassGenerator: Could not parse chord '{chord_label_str}' for block {i}. Skipping.")
                current_total_offset += block_q_length
                continue

            cs_next_obj: Optional[harmony.ChordSymbol] = None # 変数名を変更
            if i + 1 < len(processed_blocks):
                next_label_str = processed_blocks[i+1].get("chord_label")
                sanitized_next_label = sanitize_chord_label(next_label_str)
                if sanitized_next_label:
                    try:
                        cs_next_obj = harmony.ChordSymbol(sanitized_next_label)
                        if not cs_next_obj.pitches:
                            cs_next_obj = None
                    except Exception:
                        cs_next_obj = None
            if cs_next_obj is None: cs_next_obj = cs_now_obj

            tonic = blk_data.get("tonic_of_section", self.global_key_tonic)
            mode = blk_data.get("mode", self.global_key_mode)
            target_octave = bass_params.get("octave", bass_params.get("bass_target_octave", 2))
            base_velocity = bass_params.get("velocity", bass_params.get("bass_velocity", 70))

            measure_pitches_template: List[pitch.Pitch] = [] 
            try:
                temp_notes = generate_bass_measure(style=selected_style, cs_now=cs_now_obj, cs_next=cs_next_obj, tonic=tonic, mode=mode, octave=target_octave)
                measure_pitches_template = [n.pitch for n in temp_notes if isinstance(n, note.Note)] 
            except Exception as e_gbm:
                logger.error(f"BassGenerator: Error in generate_bass_measure for style '{selected_style}': {e_gbm}. Using root note.")
                if cs_now_obj and cs_now_obj.root(): 
                    measure_pitches_template = [cs_now_obj.root().transpose((target_octave - cs_now_obj.root().octave) * 12)] * 4
                else: 
                    measure_pitches_template = [pitch.Pitch('C3')] * 4 


            rhythm_key = bass_params.get("rhythm_key", "bass_quarter_notes")
            rhythm_details = self.rhythm_library.get(rhythm_key, self.rhythm_library.get("bass_quarter_notes"))
            
            pattern_events = rhythm_details.get("pattern", [])
            pattern_ref_duration = rhythm_details.get("reference_duration_ql", 4.0) 

            pitch_idx = 0
            for event_data in pattern_events:
                event_offset_in_pattern = event_data.get("offset", 0.0) 
                event_duration_from_pattern = event_data.get("duration", 1.0) 
                
                scale_factor = block_q_length / pattern_ref_duration if pattern_ref_duration > 0 else 1.0

                abs_event_offset_in_block = event_offset_in_pattern * scale_factor
                actual_event_duration = event_duration_from_pattern * scale_factor
                
                if abs_event_offset_in_block >= block_q_length:
                    continue
                actual_event_duration = min(actual_event_duration, block_q_length - abs_event_offset_in_block)

                if actual_event_duration < MIN_NOTE_DURATION_QL / 2: continue

                current_pitch_obj: Optional[pitch.Pitch] = None # 変数名を変更、初期化
                if measure_pitches_template:
                    current_pitch_obj = measure_pitches_template[pitch_idx % len(measure_pitches_template)]
                    pitch_idx += 1
                else: 
                    if cs_now_obj and cs_now_obj.root(): 
                         current_pitch_obj = cs_now_obj.root().transpose((target_octave - cs_now_obj.root().octave) * 12)
                    else: 
                        current_pitch_obj = pitch.Pitch('C3') 
                
                if current_pitch_obj is None: # current_pitch_objがNoneでないことを保証
                    logger.warning(f"BassGenerator: Could not determine pitch for event. Skipping.")
                    continue

                n_bass = note.Note(current_pitch_obj) # 変数名を変更
                n_bass.quarterLength = actual_event_duration
                vel_factor = event_data.get("velocity_factor", 1.0)
                n_bass.volume = m21instrument.Volume(velocity=int(base_velocity * vel_factor)) 
                bass_part.insert(current_total_offset + abs_event_offset_in_block, n_bass)

            current_total_offset += block_q_length

        global_bass_params = processed_blocks[0].get("part_params", {}).get("bass", {}) if processed_blocks else {}
        if global_bass_params.get("bass_humanize", global_bass_params.get("humanize", False)): 
            h_template = global_bass_params.get("bass_humanize_style_template", 
                                                 global_bass_params.get("humanize_style_template", "default_subtle")) 
            h_custom = {
                k.replace("bass_humanize_", "").replace("humanize_", ""): v
                for k, v in global_bass_params.items()
                if (k.startswith("bass_humanize_") or k.startswith("humanize_")) and 
                   not k.endswith("_template") and not k.endswith("humanize") and not k.endswith("_opt") 
            }
            logger.info(f"BassGenerator: Applying humanization with template '{h_template}' and params {h_custom}")
            bass_part = apply_humanization_to_part(bass_part, template_name=h_template, custom_params=h_custom)
            bass_part.id = "Bass"
            if not bass_part.getElementsByClass(m21instrument.Instrument).first(): bass_part.insert(0, self.default_instrument) 
            if not bass_part.getElementsByClass(tempo.MetronomeMark).first(): bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo)) 
            if not bass_part.getElementsByClass(meter.TimeSignature).first(): bass_part.insert(0, self.global_time_signature_obj.clone()) 
            if not bass_part.getElementsByClass(key.Key).first(): bass_part.insert(0, key.Key(first_block_tonic, first_block_mode)) 

        return bass_part
# --- END OF FILE generator/bass_generator.py ---
