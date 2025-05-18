# --- START OF FILE generators/drum_generator.py ---
import music21 # music21 をトップレベルでインポート

from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import stream, note, tempo, meter, instrument as m21instrument, volume, duration
import random
import logging

try:
    from .core_music_utils import get_time_signature_object, MIN_NOTE_DURATION_QL
except ImportError:
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: # Optional
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    logging.warning("DrumGen: Could not import from .core_music_utils. Using fallbacks.")


logger = logging.getLogger(__name__)

GM_DRUM_MAP: Dict[str, int] = {
    "kick": 36, "acoustic_bass_drum": 35, "bd": 36, "snare": 38, "acoustic_snare": 38, "sd": 38,
    "electric_snare": 40, "low_tom": 41, "lt": 41, "closed_hi_hat": 42, "chh": 42,
    "low_mid_tom": 43, "pedal_hi_hat": 44, "phh": 44, "mid_tom": 45, "mt": 45,
    "open_hi_hat": 46, "ohh": 46, "high_mid_tom": 47, "crash_cymbal_1": 49, "crash": 49, "crash1": 49,
    "high_tom": 50, "ht": 50, "ride_cymbal_1": 51, "ride": 51, "ride1": 51, "chinese_cymbal": 52,
    "ride_bell": 53, "tambourine": 54, "tamb": 54, "splash_cymbal": 55, "splash": 55,
    "cowbell": 56, "cow": 56, "crash_cymbal_2": 57, "crash2": 57, "vibraslap": 58,
    "ride_cymbal_2": 59, "ride2": 59, "claps": 39, "hand_clap": 39, "rim_shot": 37, "rim":37,
}

class DrumGenerator:
    def __init__(self,
                 drum_pattern_library: Optional[Dict[str, Dict[str, Any]]] = None,
                 default_instrument=m21instrument.Percussion(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.drum_pattern_library = drum_pattern_library if drum_pattern_library is not None else {}
        default_drum_key = "default_drum_basic_4_4"
        if default_drum_key not in self.drum_pattern_library:
            self.drum_pattern_library[default_drum_key] = {
                "description": "Default simple kick and snare (auto-added).",
                "time_signature": "4/4", # 必須
                "pattern": [ # pattern は hits と同じ形式を期待
                    {"instrument": "kick", "offset": 0.0, "velocity": 90, "duration": 0.1},
                    {"instrument": "snare", "offset": 1.0, "velocity": 90, "duration": 0.1},
                    {"instrument": "kick", "offset": 2.0, "velocity": 90, "duration": 0.1},
                    {"instrument": "snare", "offset": 3.0, "velocity": 90, "duration": 0.1}
                ]
            }
            logger.info(f"DrumGen: Added '{default_drum_key}' to drum_pattern_library.")

        self.default_instrument = default_instrument
        if hasattr(self.default_instrument, 'midiChannel'):
            try: self.default_instrument.midiChannel = 9
            except: logger.warning("DrumGen: Could not set midiChannel for drums.")
        
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature # ★★★ 文字列も保持 ★★★
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _create_drum_hit(self, drum_sound_name: str, velocity_val: int, duration_ql_val: float = 0.125) -> Optional[note.Note]:
        midi_val = GM_DRUM_MAP.get(drum_sound_name.lower().replace(" ", "_"))
        if midi_val is None:
            logger.warning(f"DrumGen: Sound '{drum_sound_name}' not in GM_DRUM_MAP. Skipping hit.")
            return None
        try:
            hit = note.Note()
            hit.pitch.midi = midi_val
            hit.duration = duration.Duration(quarterLength=max(0.01, duration_ql_val))
            final_vel = max(1, min(127, velocity_val + random.randint(-3, 3)))
            hit.volume = volume.Volume(velocity=final_vel) # ★ volume を使用
            return hit
        except Exception as e_create:
            logger.error(f"DrumGen: Error creating hit '{drum_sound_name}': {e_create}", exc_info=True)
            return None

    def _apply_drum_pattern_to_measure(
            self, target_part: stream.Part,
            pattern_definition: List[Dict[str, Any]], # オブジェクトのリストを期待
            measure_abs_start_offset: float,
            measure_actual_dur_ql: float,
            base_velocity_overall: int = 80): # パターン全体の基本ベロシティ

        if not pattern_definition: return
        for hit_data in pattern_definition:
            drum_name = hit_data.get("instrument")
            hit_offset_in_pattern = float(hit_data.get("offset", 0.0))
            # パターン内のベロシティ指定があればそれを使い、なければ全体のベースベロシティを使う
            hit_vel_from_pattern = hit_data.get("velocity")
            final_hit_velocity = int(hit_vel_from_pattern if hit_vel_from_pattern is not None else base_velocity_overall)
            hit_dur_ql = float(hit_data.get("duration", 0.125)) # デフォルト16分

            if not drum_name: logger.warning("DrumGen: Hit data missing 'instrument' key."); continue

            if hit_offset_in_pattern < measure_actual_dur_ql:
                actual_hit_dur = min(hit_dur_ql, measure_actual_dur_ql - hit_offset_in_pattern)
                if actual_hit_dur < 0.01: continue
                
                drum_hit = self._create_drum_hit(drum_name, final_hit_velocity, actual_hit_dur)
                if drum_hit:
                    target_part.insert(measure_absolute_start_offset + hit_offset_in_pattern, drum_hit)
                    logger.debug(f"DrumHit: {drum_name} @{measure_absolute_start_offset + hit_offset_in_pattern:.2f} (Vel:{final_hit_velocity}, Dur:{actual_hit_dur:.2f})")

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        drum_part = stream.Part(id="Drums")
        drum_part.insert(0, self.default_instrument)
        drum_part.append(tempo.MetronomeMark(number=self.global_tempo))
        drum_part.append(self.global_time_signature_obj)

        if not processed_chord_stream: logger.info("DrumGen: Empty stream."); return drum_part
        logger.info(f"DrumGen: Starting for {len(processed_chord_stream)} blocks.")
        
        current_abs_offset_ql: float = 0.0
        measures_since_last_fill_glob: int = 0 

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_q_length = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            drum_params = blk_data.get("drum_params", {})
            style_key = drum_params.get("drum_style_key", "default_drum_pattern")
            base_vel_for_block = int(drum_params.get("drum_base_velocity", 80))
            fill_interval = int(drum_params.get("drum_fill_interval_bars", 0))
            fill_key_options = drum_params.get("drum_fill_keys", [])
            block_specific_fill_key = drum_params.get("drum_fill_key_override")

            logger.debug(f"DrumBlock {blk_idx+1}: Style '{style_key}', Offset {current_abs_offset_ql:.2f}, Len {block_q_length:.2f}")

            style_definition = self.drum_pattern_library.get(style_key)
            # ★★★ AttributeError回避のための修正 ★★★
            if not style_definition: # スタイル定義そのものが存在しない場合
                logger.warning(f"DrumGen: Style key '{style_key}' not found in library. Using 'default_drum_pattern'.")
                style_definition = self.drum_pattern_library.get("default_drum_pattern", {}) # 空辞書フォールバック
            
            base_pattern_hits_list = style_definition.get("pattern", style_definition.get("hits")) # "pattern" or "hits"
            
            if not base_pattern_hits_list and style_key != "no_drums":
                logger.warning(f"DrumGen: Pattern/hits for style '{style_key}' is empty. Trying default.")
                style_definition = self.drum_pattern_library.get("default_drum_pattern", {})
                base_pattern_hits_list = style_definition.get("pattern", style_definition.get("hits"))
                if not base_pattern_hits_list and style_key != "no_drums": # デフォルトもダメならスキップ
                    logger.error("DrumGen: Default drum pattern also missing/empty. Skipping block."); current_abs_offset_ql += block_q_length; continue
            
            if style_key == "no_drums" or not base_pattern_hits_list:
                logger.debug(f"DrumGen: Style is '{style_key}' or no pattern. Skipping hits."); current_abs_offset_ql += block_q_length; continue

            pattern_ts_str = style_definition.get("time_signature", self.global_time_signature_str)
            p_ts_obj = get_time_signature_object(pattern_ts_str)
            p_bar_dur = p_ts_obj.barDuration.quarterLength
            if p_bar_dur <= 0: logger.error(f"Invalid bar duration {p_bar_dur} for pattern {style_key}."); current_abs_offset_ql += block_q_length; continue

            num_measures_total = int( (block_q_length + p_bar_dur - 0.001) // p_bar_dur ); num_measures_total = max(1, num_measures_total)

            for meas_idx in range(num_measures_total):
                meas_start_abs = current_abs_offset_ql + (meas_idx * p_bar_dur)
                actual_dur_this_measure = min(p_bar_dur, (current_abs_offset_ql + block_q_length) - meas_start_abs)
                if actual_dur_this_measure < 0.01 : continue
                
                measures_since_last_fill_glob +=1
                pattern_this_iter = base_pattern_hits_list
                applied_f_key = None
                is_last_full_measure = (meas_idx == num_measures_total -1) and (actual_dur_this_measure >= p_bar_dur - 0.01)

                if block_specific_fill_key and blk_data.get("is_last_in_section") and is_last_full_measure:
                    fill_data = style_definition.get("fill_ins", {}).get(block_specific_fill_key)
                    if fill_data: pattern_this_iter = fill_data; applied_f_key = block_specific_fill_key
                elif fill_interval > 0 and fill_options and (measures_since_last_fill_glob % fill_interval == 0) and is_last_full_measure:
                    chosen_f = random.choice(fill_options)
                    fill_data = style_def.get("fill_ins", {}).get(chosen_f)
                    if fill_data: pattern_this_iter = fill_data; applied_f_key = chosen_f
                
                if applied_f_key: logger.info(f"DrumFill: Applied '{applied_f_key}' at {meas_start_abs:.2f}"); measures_since_last_fill_glob = 0
                
                self._apply_drum_pattern_to_measure(drum_part, pattern_this_iter, meas_start_abs, actual_dur_this_measure, base_vel_for_block) # ★ base_vel_for_block を使用
            
            current_abs_offset_ql += block_q_length
        logger.info(f"DrumGen: Finished. Part elements: {len(drum_part.flatten().notesAndRests)}")
        return drum_part

# --- END OF FILE generators/drum_generator.py ---