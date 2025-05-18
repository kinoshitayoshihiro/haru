# --- START OF FILE generators/drum_generator.py ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import stream, note, tempo, meter, instrument as m21instrument, volume, duration
import random
import logging

try:
    from .core_music_utils import get_time_signature_object, MIN_NOTE_DURATION_QL # MIN_NOTE_DURATION_QLも使う可能性
except ImportError:
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except meter.MeterException:
             logging.getLogger(__name__).warning(f"Fallback GTSO: Invalid TS '{ts_str}'. Default 4/4.")
             return meter.TimeSignature("4/4")
        except Exception as e_gts_fb:
            logging.getLogger(__name__).error(f"Fallback GTSO: Error for TS '{ts_str}': {e_gts_fb}. Default 4/4.")
            return meter.TimeSignature("4/4")
    logging.warning("DrumGen: Could not import from .core_music_utils. Using fallbacks.")

logger = logging.getLogger(__name__)

GM_DRUM_MAP: Dict[str, int] = {
    "kick": 36, "bd": 36, "snare": 38, "sd": 38, "closed_hi_hat": 42, "chh": 42,
    "pedal_hi_hat": 44, "phh": 44, "open_hi_hat": 46, "ohh": 46,
    "crash_cymbal_1": 49, "crash": 49, "ride_cymbal_1": 51, "ride": 51,
    "claps": 39, "rim_shot": 37, "rim":37, "low_tom": 41, "lt": 41,
    "mid_tom": 45, "mt": 45, "high_tom": 50, "ht": 50,
    # ... (他の楽器も必要に応じて追加)
}
# グローバルなデフォルトパターンライブラリ（外部JSONからロードするのが理想）
DEFAULT_DRUM_PATTERNS_LIB: Dict[str, Dict[str, Any]] = {
    "default_drum_pattern": {
        "description": "Default simple kick and snare (Global Fallback).",
        "time_signature": "4/4",
        "pattern": [ # リストオブタプル (name, offset, velocity, duration)
            ("kick", 0.0, 90, 0.1), ("snare", 1.0, 90, 0.1),
            ("kick", 2.0, 90, 0.1), ("snare", 3.0, 90, 0.1)
        ]
    },
    "basic_rock_4_4": {
        "description": "Basic 4/4 rock beat.", "time_signature": "4/4",
        "pattern": [
            ("kick", 0.0, 100, 0.1), ("chh", 0.0, 80, 0.1), ("chh", 0.5, 70, 0.1),
            ("snare", 1.0, 95, 0.1), ("chh", 1.0, 80, 0.1), ("chh", 1.5, 70, 0.1),
            ("kick", 2.0, 100, 0.1), ("chh", 2.0, 80, 0.1), ("kick", 2.5, 85, 0.1),("chh", 2.5, 70, 0.1),
            ("snare", 3.0, 95, 0.1), ("chh", 3.0, 80, 0.1), ("chh", 3.5, 70, 0.1),
        ],
        "fill_ins": {"simple_snare_roll_half_bar": [("snare",0.0,80,0.125),("snare",0.125,85,0.125),("snare",0.25,90,0.125),("snare",0.375,95,0.125),("snare",0.5,100,0.125),("snare",0.625,105,0.125),("snare",0.75,110,0.125),("snare",0.875,115,0.125)]}
    },
    "no_drums": {"description": "Silence.", "time_signature": "4/4", "pattern": []}
}

class DrumGenerator:
    def __init__(self,
                 drum_pattern_library: Optional[Dict[str, Dict[str, Any]]] = None,
                 default_instrument=m21instrument.Percussion(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.drum_pattern_library = drum_pattern_library if drum_pattern_library is not None else {}
        # 渡されたライブラリにデフォルトがなければ、グローバルなデフォルトを追加
        if "default_drum_pattern" not in self.drum_pattern_library:
            if "default_drum_pattern" in DEFAULT_DRUM_PATTERNS_LIB:
                self.drum_pattern_library["default_drum_pattern"] = DEFAULT_DRUM_PATTERNS_LIB["default_drum_pattern"]
                logger.info("DrumGen: Added 'default_drum_pattern' from global defaults.")
            else: # これもなければ警告
                logger.error("DrumGen: Critical - 'default_drum_pattern' is not defined globally either!")
        # 'no_drums' も確実に存在するようにする
        if "no_drums" not in self.drum_pattern_library:
             self.drum_pattern_library["no_drums"] = {"description": "Silence (auto-added).", "time_signature": "4/4", "pattern": []}


        self.default_instrument = default_instrument
        if hasattr(self.default_instrument, 'midiChannel'): self.default_instrument.midiChannel = 9
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _create_drum_hit(self, drum_sound_name: str, velocity_val: int, duration_ql_val: float = 0.125) -> Optional[note.Note]:
        # (変更なし)
        midi_val = GM_DRUM_MAP.get(drum_sound_name.lower().replace(" ", "_"))
        if midi_val is None: logger.warning(f"DrumGen: Sound '{drum_sound_name}' not in GM_DRUM_MAP. Skip."); return None
        try:
            hit = note.Note(); hit.pitch.midi = midi_val
            hit.duration = duration.Duration(quarterLength=max(0.01, duration_ql_val))
            hit.volume = volume.Volume(velocity=max(1, min(127, velocity_val + random.randint(-2,2))))
            return hit
        except Exception as e: logger.error(f"DrumGen: Error creating hit '{drum_sound_name}': {e}"); return None

    def _apply_drum_pattern_to_measure(
            self, target_part: stream.Part, pattern_definition: List[Any], # Tuple or Dict
            measure_abs_start: float, measure_actual_dur: float, base_vel_adj: int = 0):
        if not pattern_definition: return
        for hit_data in pattern_definition:
            try:
                if isinstance(hit_data, tuple) and len(hit_data) == 4:
                    name, offset, vel, dur = hit_data
                elif isinstance(hit_data, dict): # オブジェクト形式の場合
                    name = hit_data.get("instrument")
                    offset = float(hit_data.get("offset", 0.0))
                    vel = int(hit_data.get("velocity", 80))
                    dur = float(hit_data.get("duration", 0.125))
                else: logger.warning(f"DrumGen: Malformed hit_data {hit_data}"); continue
                if not name: continue

                if offset < measure_actual_dur:
                    actual_hit_d = min(dur, measure_actual_dur - offset)
                    if actual_hit_d < 0.01: continue
                    drum_hit = self._create_drum_hit(name, vel + base_vel_adj, actual_hit_d)
                    if drum_hit: target_part.insert(measure_abs_start + offset, drum_hit)
            except Exception as e_apply_hit: logger.error(f"DrumGen: Error applying hit {hit_data}: {e_apply_hit}")

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        drum_part = stream.Part(id="Drums")
        drum_part.insert(0, self.default_instrument)
        drum_part.append(tempo.MetronomeMark(number=self.global_tempo))
        drum_part.append(self.global_time_signature_obj)

        if not processed_chord_stream: logger.info("DrumGen: Empty stream."); return drum_part
        logger.info(f"DrumGen: Starting for {len(processed_chord_stream)} blocks.")
        
        measures_since_last_fill = 0
        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset = float(blk_data.get("offset", 0.0))
            block_q_len = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            drum_params = blk_data.get("drum_params", {})
            style_key = drum_params.get("drum_style_key", "default_drum_pattern")
            base_vel = int(drum_params.get("drum_base_velocity", 80))
            fill_interval = int(drum_params.get("drum_fill_interval_bars", 0))
            fill_options = drum_params.get("drum_fill_keys", [])
            block_fill_key = drum_params.get("drum_fill_key_override")

            logger.debug(f"DrumBlk {blk_idx+1}: Sty='{style_key}', Off={block_offset:.2f}, Len={block_q_len:.2f}")

            style_def = self.drum_pattern_library.get(style_key)
            if not style_def or not style_def.get("pattern"):
                logger.warning(f"DrumGen: Style '{style_key}' or pattern not found. Using 'default_drum_pattern'.")
                style_def = self.drum_pattern_library.get("default_drum_pattern", {}) # フォールバック
                if not style_def or not style_def.get("pattern"): # 本当に何もない場合
                    logger.error("DrumGen: Default drum pattern also invalid. Skipping block.")
                    continue
            
            base_hits = style_def.get("pattern", [])
            pattern_ts_str = style_def.get("time_signature", self.global_time_signature_str)
            p_ts_obj = get_time_signature_object(pattern_ts_str)
            p_bar_dur = p_ts_obj.barDuration.quarterLength
            if p_bar_dur <= 0: logger.error(f"Invalid bar dur {p_bar_dur} for pattern {style_key}."); continue

            num_measures_in_block = int((block_q_len + p_bar_dur - 0.001) // p_bar_dur); num_measures_in_block = max(1, num_measures_in_block)
            if blk_data.get("is_first_in_section", False): measures_since_last_fill = 0

            for m_idx in range(num_measures_in_block):
                measure_start = block_offset + (m_idx * p_bar_dur)
                actual_measure_dur = min(p_bar_dur, (block_offset + block_q_len) - measure_start)
                if actual_measure_dur < 0.01: continue
                
                current_pattern_hits = base_hits
                applied_fill = False
                is_last_full_measure = (m_idx == num_measures_in_block -1) and (actual_measure_dur >= p_bar_dur - 0.01)

                if block_fill_key and blk_data.get("is_last_in_section") and is_last_full_measure:
                    f_def = style_def.get("fill_ins", {}).get(block_fill_key)
                    if f_def: current_pattern_hits = f_def; applied_fill = True; logger.info(f"DrumFill (Block): '{block_fill_key}' at {measure_start:.2f}")
                    else: logger.warning(f"DrumFill (Block): Key '{block_fill_key}' not in fills for '{style_key}'.")
                elif not applied_fill and fill_interval > 0 and fill_options and \
                     (measures_since_last_fill + 1) % fill_interval == 0 and is_last_full_measure :
                    chosen_f_key = random.choice(fill_options)
                    f_def = style_def.get("fill_ins", {}).get(chosen_f_key)
                    if f_def: current_pattern_hits = f_def; applied_fill = True; logger.info(f"DrumFill (Interval): '{chosen_f_key}' at {measure_start:.2f}")

                self._apply_drum_pattern_to_measure(drum_part, current_pattern_hits, measure_start, actual_measure_dur, base_vel - 90)
                
                if applied_fill: measures_since_last_fill = 0
                elif actual_measure_dur >= p_bar_dur - 0.01: measures_since_last_fill +=1
        
        logger.info(f"DrumGen: Finished. Part has {len(drum_part.flatten().notesAndRests)} elements.")
        return drum_part
# --- END OF FILE generators/drum_generator.py ---
