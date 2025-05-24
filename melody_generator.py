# --- START OF FILE generator/melody_generator.py (ヒューマナイズ外部化・修正版) ---
from __future__ import annotations
"""melody_generator.py – *lightweight rewrite*
... (docstringは変更なし) ...
"""
from typing import Dict, List, Sequence, Any, Tuple, Optional, Union
import random
import logging

from music21 import stream, note, harmony, tempo, meter, instrument as m21instrument, key, pitch

# ユーティリティのインポート
try:
    from .melody_utils import generate_melodic_pitches # 同じディレクトリ
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.error(f"MelodyGenerator: Failed to import required modules: {e}")
    def generate_melodic_pitches(*args, **kwargs) -> List[note.Note]: return []
    def apply_humanization_to_part(part, *args, **kwargs) -> stream.Part: return part # type: ignore
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature("4/4")
    HUMANIZATION_TEMPLATES = {}

logger = logging.getLogger(__name__)

class MelodyGenerator:
    def __init__(
        self,
        rhythm_library: Optional[Dict[str, Dict]] = None, # パターンは {"pattern": [offsets], "note_duration_ql": val}
        default_instrument = m21instrument.Flute(),
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        global_key_signature_tonic: str = "C",
        global_key_signature_mode: str = "major",
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rhythm_library = rhythm_library if rhythm_library else {}
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        self.global_key_tonic = global_key_signature_tonic
        self.global_key_mode = global_key_signature_mode
        self.rng = rng or random.Random()

        if "default_melody_rhythm" not in self.rhythm_library:
            self.rhythm_library["default_melody_rhythm"] = {
                "description": "Default melody rhythm - quarter notes",
                "pattern": [0.0, 1.0, 2.0, 3.0], # オフセットのリスト
                "note_duration_ql": 1.0, # 各音符の基本長
                "reference_duration_ql": 4.0 # パターンの基準長
            }
            logger.info("MelodyGenerator: Added 'default_melody_rhythm' to rhythm_library.")


    def _get_rhythm_details(self, rhythm_key: str) -> Dict[str, Any]:
        default_rhythm = self.rhythm_library.get("default_melody_rhythm", 
            {"pattern": [0.0,1.0,2.0,3.0], "note_duration_ql":1.0, "reference_duration_ql":4.0}
        )
        details = self.rhythm_library.get(rhythm_key, default_rhythm)
        if "pattern" not in details or not isinstance(details["pattern"], list):
            logger.warning(f"MelodyGen: Rhythm key '{rhythm_key}' invalid or missing 'pattern' list. Using default.")
            return default_rhythm
        if "note_duration_ql" not in details:
            details["note_duration_ql"] = default_rhythm["note_duration_ql"]
        if "reference_duration_ql" not in details:
            details["reference_duration_ql"] = default_rhythm["reference_duration_ql"]
        return details

    def compose(self, processed_blocks: Sequence[Dict[str, Any]]) -> stream.Part:
        melody_part = stream.Part(id="Melody")
        melody_part.insert(0, self.default_instrument)
        melody_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        melody_part.insert(0, self.global_time_signature_obj.clone())
        first_block_tonic = processed_blocks[0].get("tonic_of_section", self.global_key_tonic) if processed_blocks else self.global_key_tonic
        first_block_mode = processed_blocks[0].get("mode", self.global_key_mode) if processed_blocks else self.global_key_mode
        melody_part.insert(0, key.Key(first_block_tonic, first_block_mode))

        current_total_offset = 0.0

        for blk_idx, blk_data in enumerate(processed_blocks):
            melody_params = blk_data.get("part_params", {}).get("melody", {})
            if melody_params.get("skip", False):
                current_total_offset += blk_data.get("q_length", 0.0)
                continue
            
            chord_label_str = blk_data.get("chord_label", "C")
            block_q_length = blk_data.get("q_length", 4.0)
            
            cs_current_block = get_music21_chord_object(chord_label_str)
            if cs_current_block is None:
                current_total_offset += block_q_length
                continue

            tonic_for_block = blk_data.get("tonic_of_section", self.global_key_tonic)
            mode_for_block = blk_data.get("mode", self.global_key_mode)
            
            rhythm_key = melody_params.get("rhythm_key", "default_melody_rhythm")
            rhythm_details = self._get_rhythm_details(rhythm_key)
            
            beat_offsets_template = rhythm_details.get("pattern")
            base_note_duration_ql = rhythm_details.get("note_duration_ql")
            template_ref_duration = rhythm_details.get("reference_duration_ql")

            # ブロック長に合わせてオフセットを伸縮
            stretch_factor = block_q_length / template_ref_duration if template_ref_duration > 0 else 1.0
            final_beat_offsets_for_block = [tpl_off * stretch_factor for tpl_off in beat_offsets_template]
            
            octave_range = tuple(melody_params.get("octave_range", [4, 5]))
            
            generated_notes = generate_melodic_pitches(
                chord=cs_current_block, tonic=tonic_for_block, mode=mode_for_block,
                beat_offsets=final_beat_offsets_for_block, octave_range=octave_range,
                rnd=self.rng, min_note_duration_ql=MIN_NOTE_DURATION_QL
            )

            density = melody_params.get("density", 0.7)
            note_velocity = melody_params.get("velocity", 80)

            for idx, n_obj in enumerate(generated_notes):
                if self.rng.random() <= density:
                    # デュレーション設定
                    note_start_offset_in_block = final_beat_offsets_for_block[idx]
                    if idx < len(final_beat_offsets_for_block) - 1:
                        next_note_start_offset_in_block = final_beat_offsets_for_block[idx+1]
                        max_dur = next_note_start_offset_in_block - note_start_offset_in_block
                    else:
                        max_dur = block_q_length - note_start_offset_in_block
                    
                    # 基本デュレーションを伸縮し、最大デュレーションと最小デュレーションでクリップ
                    actual_dur = max(MIN_NOTE_DURATION_QL, min(max_dur, base_note_duration_ql * stretch_factor))
                    n_obj.quarterLength = actual_dur * 0.95 # わずかにスタッカート
                    
                    n_obj.volume = m21instrument.Volume(velocity=note_velocity)
                    melody_part.insert(current_total_offset + note_start_offset_in_block, n_obj)

            current_total_offset += block_q_length

        # --- パート全体にヒューマナイゼーションを適用 ---
        global_melody_params = processed_blocks[0].get("part_params", {}).get("melody", {}) if processed_blocks else {}
        if global_melody_params.get("melody_humanize", global_melody_params.get("humanize", False)):
            h_template = global_melody_params.get("melody_humanize_style_template", "default_subtle")
            h_custom = {
                k.replace("melody_humanize_", "").replace("humanize_", ""): v
                for k, v in global_melody_params.items()
                if (k.startswith("melody_humanize_") or k.startswith("humanize_")) and not k.endswith("_template") and not k.endswith("humanize")
            }
            logger.info(f"MelodyGenerator: Applying humanization with template '{h_template}' and params {h_custom}")
            melody_part = apply_humanization_to_part(melody_part, template_name=h_template, custom_params=h_custom)
            melody_part.id = "Melody" # ID再設定
            if not melody_part.getElementsByClass(instrument.Instrument).first(): melody_part.insert(0, self.default_instrument)
            if not melody_part.getElementsByClass(tempo.MetronomeMark).first(): melody_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
            if not melody_part.getElementsByClass(meter.TimeSignature).first(): melody_part.insert(0, self.global_time_signature_obj.clone())
            if not melody_part.getElementsByClass(key.Key).first(): melody_part.insert(0, key.Key(first_block_tonic, first_block_mode))

        return melody_part
# --- END OF FILE generator/melody_generator.py ---
