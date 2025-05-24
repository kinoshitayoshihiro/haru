# --- START OF FILE generator/melody_generator.py (修正・ブラッシュアップ版) ---
from __future__ import annotations
"""melody_generator.py – *lightweight rewrite*
... (docstringは変更なし) ...
"""
from typing import Dict, List, Sequence, Any, Tuple, Optional, Union # Union を追加
import random
import logging

# music21 のサブモジュールを個別にインポート
from music21 import stream
from music21 import note
from music21 import harmony
from music21 import tempo
from music21 import meter
from music21 import instrument as m21instrument
from music21 import key
from music21 import pitch # コード内で使用されているため追加

# melody_utils と humanizer をインポート
try:
    from .melody_utils import generate_melodic_pitches # 同じディレクトリなので相対インポート
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label # sanitize_chord_label を追加
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils") # logger_fallback を定義
    logger_fallback.error(f"MelodyGenerator: Failed to import required modules (melody_utils or humanizer or core_music_utils): {e}")
    def generate_melodic_pitches(*args, **kwargs): return [] # Dummy
    def apply_humanization_to_part(part, *args, **kwargs): return part # Dummy
    MIN_NOTE_DURATION_QL = 0.125 # Dummy
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature("4/4") # meter を使用
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: # ダミーの sanitize_chord_label を追加
        if not label or label.strip().lower() in ["rest", "n.c.", "nc", "none"]: return None
        return label.strip()
    HUMANIZATION_TEMPLATES = {}


logger = logging.getLogger(__name__)

class MelodyGenerator:
    def __init__(
        self,
        rhythm_library: Optional[Dict[str, Dict]] = None, 
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
                "pattern": [0.0, 1.0, 2.0, 3.0], 
                "note_duration_ql": 1.0, 
                "reference_duration_ql": 4.0 
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
            details["note_duration_ql"] = default_rhythm.get("note_duration_ql", 1.0) # getを追加
        if "reference_duration_ql" not in details:
            details["reference_duration_ql"] = default_rhythm.get("reference_duration_ql", 4.0) # getを追加
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
                logger.debug(f"MelodyGenerator: Skipping melody for block {blk_idx+1} due to 'skip' flag.")
                current_total_offset += blk_data.get("q_length", 0.0)
                continue
            
            chord_label_str = blk_data.get("chord_label", "C")
            block_q_length = blk_data.get("q_length", 4.0)
            
            # get_music21_chord_object は core_music_utils からインポートされる想定
            # try-exceptブロックは維持
            try:
                # from utilities.core_music_utils import get_music21_chord_object # ここでの再インポートは不要
                cs_current_block = sanitize_chord_label(chord_label_str) # sanitize_chord_labelを使用
                if cs_current_block is None: # sanitize_chord_labelがNoneを返す場合
                    cs_m21_obj = None
                else:
                    cs_m21_obj = harmony.ChordSymbol(cs_current_block) # harmony.ChordSymbolを使用

                if cs_m21_obj is None or not cs_m21_obj.pitches: # ピッチがない場合もスキップ
                    logger.warning(f"MelodyGenerator: Could not parse chord '{chord_label_str}' or no pitches for block {blk_idx+1}. Skipping melody notes.")
                    current_total_offset += block_q_length
                    continue
            except Exception as e_chord_parse: # harmony.HarmonyException やその他のパースエラーをキャッチ
                logger.warning(f"MelodyGenerator: Error parsing chord '{chord_label_str}' for block {blk_idx+1}: {e_chord_parse}. Skipping.")
                current_total_offset += block_q_length
                continue


            tonic_for_block = blk_data.get("tonic_of_section", self.global_key_tonic)
            mode_for_block = blk_data.get("mode", self.global_key_mode)
            
            rhythm_key_for_block = melody_params.get("rhythm_key", "default_melody_rhythm")
            rhythm_details = self._get_rhythm_details(rhythm_key_for_block)
            
            beat_offsets_template = rhythm_details.get("pattern", [0.0, 1.0, 2.0, 3.0])
            base_note_duration_ql = rhythm_details.get("note_duration_ql", 
                                                     melody_params.get("note_duration_ql", 0.5)) 
            template_reference_duration = rhythm_details.get("reference_duration_ql", 4.0)
            
            stretch_factor = 1.0
            if template_reference_duration > 0:
                stretch_factor = block_q_length / template_reference_duration
            
            final_beat_offsets_for_block = [tpl_off * stretch_factor for tpl_off in beat_offsets_template if (tpl_off * stretch_factor) < block_q_length]
            if not final_beat_offsets_for_block and beat_offsets_template : # ブロックが短すぎて何も配置できない場合、最初の要素だけでも配置試行
                 if (beat_offsets_template[0] * stretch_factor) < block_q_length:
                     final_beat_offsets_for_block = [beat_offsets_template[0] * stretch_factor]


            octave_range_for_block = tuple(melody_params.get("octave_range", [4, 5]))
            
            generated_notes = generate_melodic_pitches(
                chord=cs_m21_obj, # cs_m21_obj を使用 (Noneでないことは上で確認済み)
                tonic=tonic_for_block,
                mode=mode_for_block,
                beat_offsets=final_beat_offsets_for_block, 
                octave_range=octave_range_for_block,
                rnd=self.rng,
                min_note_duration_ql=MIN_NOTE_DURATION_QL 
            )

            density_for_block = melody_params.get("density", 0.7)
            note_velocity = melody_params.get("velocity", 80) # note_velocity を定義

            for idx, n_obj in enumerate(generated_notes):
                if self.rng.random() <= density_for_block:
                    note_start_offset_in_block = final_beat_offsets_for_block[idx]
                    
                    if idx < len(final_beat_offsets_for_block) - 1:
                        next_note_start_offset_in_block = final_beat_offsets_for_block[idx+1]
                        max_dur = next_note_start_offset_in_block - note_start_offset_in_block
                    else:
                        max_dur = block_q_length - note_start_offset_in_block
                    
                    actual_dur = max(MIN_NOTE_DURATION_QL, min(max_dur, base_note_duration_ql * stretch_factor))
                    n_obj.quarterLength = actual_dur * 0.95 
                    
                    n_obj.volume = m21instrument.Volume(velocity=note_velocity) # m21instrument を使用
                    
                    melody_part.insert(current_total_offset + note_start_offset_in_block, n_obj)

            current_total_offset += block_q_length

        global_melody_params = processed_blocks[0].get("part_params", {}).get("melody", {}) if processed_blocks else {}
        if global_melody_params.get("melody_humanize", global_melody_params.get("humanize", False)):
            h_template_mel = global_melody_params.get("melody_humanize_style_template", 
                                                     global_melody_params.get("humanize_style_template", "default_subtle")) # humanize_style_templateも考慮
            h_custom_mel = {
                k.replace("melody_humanize_", "").replace("humanize_", ""): v
                for k, v in global_melody_params.items()
                if (k.startswith("melody_humanize_") or k.startswith("humanize_")) and 
                   not k.endswith("_template") and not k.endswith("humanize") and not k.endswith("_opt") # _optも除外
            }
            logger.info(f"MelodyGenerator: Applying humanization with template '{h_template_mel}' and params {h_custom_mel}")
            melody_part = apply_humanization_to_part(melody_part, template_name=h_template_mel, custom_params=h_custom_mel)
            melody_part.id = "Melody"
            if not melody_part.getElementsByClass(m21instrument.Instrument).first(): melody_part.insert(0, self.default_instrument)
            if not melody_part.getElementsByClass(tempo.MetronomeMark).first(): melody_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
            if not melody_part.getElementsByClass(meter.TimeSignature).first(): melody_part.insert(0, self.global_time_signature_obj.clone())
            if not melody_part.getElementsByClass(key.Key).first(): melody_part.insert(0, key.Key(first_block_tonic, first_block_mode))
            
        return melody_part
# --- END OF FILE generator/melody_generator.py ---
