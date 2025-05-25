# --- START OF FILE generator/drum_generator.py (エラー修正・.clone()修正版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence, Union, cast

# music21 のサブモジュールを正しい形式でインポート
import music21.stream as stream
import music21.note as note
import music21.tempo as tempo
import music21.meter as meter
import music21.instrument as m21instrument
import music21.volume as m21volume
import music21.duration as duration
import music21.pitch as pitch
import music21.chord      as m21chord

import random
import logging

# ユーティリティのインポート
try:
    from utilities.core_music_utils import get_time_signature_object, MIN_NOTE_DURATION_QL
    from utilities.humanizer import apply_humanization_to_element, HUMANIZATION_TEMPLATES
except ImportError:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("DrumGen: Could not import from utilities. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"; return meter.TimeSignature(ts_str)
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    def apply_humanization_to_element(element, template_name=None, custom_params=None): return element
    HUMANIZATION_TEMPLATES = {}


logger = logging.getLogger(__name__)

GM_DRUM_MAP = {"kick":36, "bd":36, "snare":38, "sd":38, "chh":42, "phh":44, "ohh":46, "crash":49, "ride":51, "claps":39, "rim":37, "lt":41, "mt":45, "ht":50, "hat":42}
DEFAULT_DRUM_PATTERNS_LIB = {"default_drum_pattern": {"description":"Default simple kick/snare","time_signature":"4/4","pattern":[{"instrument":"kick","offset":0.0,"velocity":90,"duration":0.1},{"instrument":"snare","offset":1.0,"velocity":90,"duration":0.1},{"instrument":"kick","offset":2.0,"velocity":90,"duration":0.1},{"instrument":"snare","offset":3.0,"velocity":90,"duration":0.1}]},"no_drums":{"description":"Silence","time_signature":"4/4","pattern":[]}}


class DrumGenerator:
    def __init__(self,
                 drum_pattern_library: Optional[Dict[str, Dict[str, Any]]] = None,
                 default_instrument=m21instrument.Percussion(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.drum_pattern_library = drum_pattern_library if drum_pattern_library is not None else {}
        if "default_drum_pattern" not in self.drum_pattern_library: self.drum_pattern_library["default_drum_pattern"] = DEFAULT_DRUM_PATTERNS_LIB["default_drum_pattern"]; logger.info("DrumGen: Added 'default_drum_pattern'.")
        if "no_drums" not in self.drum_pattern_library: self.drum_pattern_library["no_drums"] = DEFAULT_DRUM_PATTERNS_LIB["no_drums"]; logger.info("DrumGen: Added 'no_drums'.")
        custom_styles = ["no_drums_or_sparse_cymbal", "no_drums_or_gentle_cymbal_swell", "no_drums_or_sparse_chimes"]
        for cds in custom_styles:
            if cds not in self.drum_pattern_library: self.drum_pattern_library[cds] = {"description":f"{cds} (auto-added)","time_signature":"4/4","pattern":[]}; logger.info(f"DrumGen: Added placeholder for '{cds}'.")
        self.default_instrument = default_instrument
        if hasattr(self.default_instrument, 'midiChannel'): self.default_instrument.midiChannel = 9
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)


    def _create_drum_hit(self, drum_sound_name: str, velocity_val: int, duration_ql_val: float = 0.125) -> Optional[note.Note]:
        midi_val = GM_DRUM_MAP.get(drum_sound_name.lower().replace(" ","_").replace("-","_"))
        if midi_val is None: logger.warning(f"DrumGen: Sound '{drum_sound_name}' not in GM_DRUM_MAP. Skip."); return None
        try:
            hit = note.Note()
            hit.pitch = pitch.Pitch()
            hit.pitch.midi = midi_val
            hit.duration = duration.Duration(quarterLength=max(MIN_NOTE_DURATION_QL/4, duration_ql_val))
            hit.volume = m21volume.Volume(velocity=max(1,min(127,velocity_val)))
            return hit
        except Exception as e: logger.error(f"DrumGen: Error creating hit '{drum_sound_name}': {e}", exc_info=True); return None

    def _apply_drum_pattern_to_measure(
        self, target_part: stream.Part, pattern_events: List[Dict[str, Any]],
        measure_abs_start_offset: float, measure_duration_ql: float, base_velocity: int,
        humanize_params_for_hit: Optional[Dict[str, Any]] = None
    ):
        if not pattern_events: return
        for event_def in pattern_events:
            instrument_name = event_def.get("instrument")
            event_offset_in_pattern = float(event_def.get("offset", 0.0))
            event_duration_ql = float(event_def.get("duration", 0.125))
            event_velocity = event_def.get("velocity"); event_velocity_factor = event_def.get("velocity_factor")
            if not instrument_name: continue
            final_velocity = int(event_velocity) if event_velocity is not None else (int(base_velocity * float(event_velocity_factor)) if event_velocity_factor is not None else base_velocity)
            final_velocity = max(1, min(127, final_velocity))
            if event_offset_in_pattern < measure_duration_ql:
                actual_hit_duration_ql = min(event_duration_ql, measure_duration_ql - event_offset_in_pattern)
                if actual_hit_duration_ql < MIN_NOTE_DURATION_QL / 8: continue
                drum_hit = self._create_drum_hit(instrument_name, final_velocity, actual_hit_duration_ql)
                if drum_hit:
                    if humanize_params_for_hit:
                        drum_hit = cast(note.Note, apply_humanization_to_element(drum_hit, custom_params=humanize_params_for_hit))

                    insert_at_offset = measure_abs_start_offset + event_offset_in_pattern
                    # apply_humanization_to_element がオフセットを変更する場合、ここで加味する
                    if hasattr(drum_hit, 'offset') and drum_hit.offset != 0.0: # Humanizerがオフセットを付加した場合
                        insert_at_offset += drum_hit.offset
                        drum_hit.offset = 0 # Partへinsertする前に要素自体のオフセットは0にリセット
                    target_part.insert(insert_at_offset, drum_hit)


    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        drum_part = stream.Part(id="Drums")
        drum_part.insert(0, self.default_instrument)
        drum_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))

        if self.global_time_signature_obj:
            ts_copy = meter.TimeSignature(self.global_time_signature_obj.ratioString)
            drum_part.insert(0, ts_copy)
        else:
            logger.warning("DrumGen: global_time_signature_obj is None. Defaulting to 4/4 for drum_part.")
            drum_part.insert(0, meter.TimeSignature("4/4"))


        if not processed_chord_stream: return drum_part
        logger.info(f"DrumGen: Starting for {len(processed_chord_stream)} blocks.")

        measures_since_last_fill = 0
        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength if self.global_time_signature_obj else 4.0))
            drum_params = blk_data.get("part_params", {}).get("drums", {})
            style_key = drum_params.get("drum_style_key", "default_drum_pattern")
            base_velocity = int(drum_params.get("drum_base_velocity", 80))
            fill_interval = drum_params.get("drum_fill_interval_bars", 0)
            fill_options = drum_params.get("drum_fill_keys", [])
            block_fill_key = drum_params.get("drum_fill_key_override")

            humanize_this_block = drum_params.get("humanize_opt", drum_params.get("humanize", True))
            humanize_params_for_hits_in_block: Optional[Dict[str, Any]] = None
            if humanize_this_block:
                template_name = drum_params.get("template_name", drum_params.get("humanize_style_template", "drum_loose_fbm"))
                base_h_params = HUMANIZATION_TEMPLATES.get(template_name, HUMANIZATION_TEMPLATES.get("default_subtle", {}))
                humanize_params_for_hits_in_block = base_h_params.copy()

                custom_h_from_translate = drum_params.get("custom_params")
                if isinstance(custom_h_from_translate, dict):
                    humanize_params_for_hits_in_block.update(custom_h_from_translate)
                else:
                    custom_h_overrides = {
                        k.replace("humanize_",""):v for k,v in drum_params.items()
                        if k.startswith("humanize_") and not k.endswith("_template") and not k == "humanize" and not k == "humanize_opt"
                    }
                    humanize_params_for_hits_in_block.update(custom_h_overrides)
                logger.debug(f"DrumGen Blk {blk_idx+1}: Humanize params: {humanize_params_for_hits_in_block}")


            style_def = self.drum_pattern_library.get(style_key)
            if not style_def or "pattern" not in style_def:
                logger.warning(f"DrumGen: Style key '{style_key}' not found or invalid in drum_pattern_library. Using default_drum_pattern.")
                style_def = self.drum_pattern_library.get("default_drum_pattern", DEFAULT_DRUM_PATTERNS_LIB["default_drum_pattern"])

            main_pattern_events = style_def.get("pattern", [])
            pattern_ts_str = style_def.get("time_signature", self.global_time_signature_str)
            p_ts_obj = get_time_signature_object(pattern_ts_str)
            p_bar_dur = p_ts_obj.barDuration.quarterLength if p_ts_obj else 4.0
            if p_bar_dur <= 0:
                logger.warning(f"DrumGen: Pattern time signature for '{style_key}' results in non-positive bar duration ({p_bar_dur}). Skipping block.")
                continue

            current_block_time_ql = 0.0
            if blk_data.get("is_first_in_section", False): measures_since_last_fill = 0

            while current_block_time_ql < block_duration_ql - MIN_NOTE_DURATION_QL / 4:
                measure_start_abs = block_offset_ql + current_block_time_ql
                current_measure_iter_dur = min(p_bar_dur, block_duration_ql - current_block_time_ql)
                if current_measure_iter_dur < MIN_NOTE_DURATION_QL: break

                pattern_to_apply = main_pattern_events; applied_fill = False
                is_eff_last_measure_of_block = (current_block_time_ql + current_measure_iter_dur >= block_duration_ql - MIN_NOTE_DURATION_QL / 8)


                if block_fill_key and is_eff_last_measure_of_block:
                    fill_def = style_def.get("fill_ins", {}).get(block_fill_key)
                    if fill_def: pattern_to_apply = fill_def; applied_fill = True; logger.debug(f"DrumGen: Applying override fill '{block_fill_key}' at {measure_start_abs:.2f}")
                elif not applied_fill and fill_interval > 0 and fill_options and \
                     (measures_since_last_fill + (current_measure_iter_dur / p_bar_dur if p_bar_dur > 0 else 1) >= fill_interval) and \
                     is_eff_last_measure_of_block :
                    chosen_f_key = random.choice(fill_options)
                    fill_def = style_def.get("fill_ins", {}).get(chosen_f_key)
                    if fill_def: pattern_to_apply = fill_def; applied_fill = True; logger.debug(f"DrumGen: Applying scheduled fill '{chosen_f_key}' at {measure_start_abs:.2f}")

                self._apply_drum_pattern_to_measure(
                    drum_part, pattern_to_apply, measure_start_abs,
                    current_measure_iter_dur, base_velocity,
                    humanize_params_for_hits_in_block
                )

                if applied_fill: measures_since_last_fill = 0
                if current_measure_iter_dur >= p_bar_dur - MIN_NOTE_DURATION_QL / 8 :
                    measures_since_last_fill +=1

                current_block_time_ql += current_measure_iter_dur

        logger.info(f"DrumGen: Finished. Part has {len(list(drum_part.flatten().notesAndRests))} elements.")
        return drum_part
# --- END OF FILE generator/drum_generator.py ---
