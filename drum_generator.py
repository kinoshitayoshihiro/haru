# --- START OF FILE generator/drum_generator.py (o3-san feedback 반영판) ---
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
# import music21.chord # Not directly used in this file

import random
import logging
import math

# ユーティリティのインポート
try:
    from utilities.core_music_utils import get_time_signature_object, MIN_NOTE_DURATION_QL
    from utilities.humanizer import apply_humanization_to_element, HUMANIZATION_TEMPLATES
except ImportError:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("DrumGen: Could not import from utilities. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        ts_str = ts_str or "4/4"
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    def apply_humanization_to_element(element, template_name=None, custom_params=None):
        # Fallback humanizer: returns element as is, meaning element.offset (if 0) remains 0.
        return element
    HUMANIZATION_TEMPLATES = {}


logger = logging.getLogger(__name__)

# General MIDI Drum Map (MIDI Channel 10 -> music21 channel index 9)
# Simplified and clarified based on o3-san's feedback
GM_DRUM_MAP = {
    "kick": 36, "acoustic_bass_drum": 35, # Standard variations
    "snare": 38, "acoustic_snare": 38, "electric_snare": 40,
    "closed_hi_hat": 42, "chh": 42,
    "pedal_hi_hat": 44, "phh": 44,
    "open_hi_hat": 46, "ohh": 46,
    "crash_cymbal_1": 49, "crash": 49, # Alias common name
    "crash_cymbal_2": 57,
    "ride_cymbal_1": 51, "ride": 51, # Alias common name
    "ride_cymbal_2": 59,
    "ride_bell": 53,
    "hand_clap": 39, "claps": 39, # Alias common name
    "side_stick": 37, "rim": 37,   # Alias common name
    "low_floor_tom": 41,   "tom_floor_low": 41, # LFT
    "high_floor_tom": 43,  "tom_floor_high": 43, # HFT (sometimes Low Tom)
    "low_tom": 45,         "tom_low": 45,     # LT
    "low_mid_tom": 47,     "tom_mid_low": 47, # LMT
    "high_mid_tom": 48,    "tom_mid_high": 48,# HMT
    "high_tom": 50,        "tom_hi": 50,      # HT
    # Common aliases for rhythm_library convenience
    "tom1": 50, # Often mapped to High Tom
    "tom2": 48, # Often mapped to High-Mid Tom or Mid Tom
    "tom3": 45, # Often mapped to Low Tom or Low-Floor Tom
    "tambourine": 54, "cowbell": 56, "vibraslap": 58,
    "shaker": 70, "agogo": 67, "cabasa": 69,
    "hat": 42 # Generic hat, maps to closed_hi_hat
}

DEFAULT_DRUM_PATTERNS_LIB = {
    "default_drum_pattern": {
        "description": "Default simple kick/snare", "time_signature": "4/4", "swing": 0.5,
        "pattern": [
            {"instrument": "kick", "offset": 0.0, "velocity": 90, "duration": 0.1},
            {"instrument": "snare", "offset": 1.0, "velocity": 90, "duration": 0.1},
            {"instrument": "kick", "offset": 2.0, "velocity": 90, "duration": 0.1},
            {"instrument": "snare", "offset": 3.0, "velocity": 90, "duration": 0.1}
        ],
        "fill_ins": {} # Explicitly empty
    },
    "no_drums": {"description": "Silence", "time_signature": "4/4", "swing": 0.5, "pattern": [], "fill_ins": {}}
}

EMOTION_TO_BUCKET: Dict[str, str] = {
    "quiet_pain_and_nascent_strength": "ballad_soft", "self_reproach_regret_deep_sadness": "ballad_soft",
    "memory_unresolved_feelings_silence": "ballad_soft", "reflective_transition_instrumental_passage": "ballad_soft",
    "deep_regret_gratitude_and_realization": "groove_mid", "supported_light_longing_for_rebirth": "groove_mid",
    "wavering_heart_gratitude_chosen_strength": "groove_mid", "hope_dawn_light_gentle_guidance": "groove_mid",
    "nature_memory_floating_sensation_forgiveness": "groove_mid",
    "acceptance_of_love_and_pain_hopeful_belief": "anthem_high", "trial_cry_prayer_unbreakable_heart": "anthem_high",
    "reaffirmed_strength_of_love_positive_determination": "anthem_high",
    "future_cooperation_our_path_final_resolve_and_liberation": "anthem_high",
    "default": "groove_mid", "neutral": "groove_mid"
}

BUCKET_INTENSITY_TO_STYLE: Dict[str, Dict[str, str]] = {
    "ballad_soft": {
        "low": "no_drums_or_gentle_cymbal_swell", "medium_low": "ballad_soft_kick_snare_8th_hat",
        "medium": "ballad_soft_kick_snare_8th_hat", "medium_high": "rock_ballad_build_up_8th_hat",
        "high": "rock_ballad_build_up_8th_hat", "default": "ballad_soft_kick_snare_8th_hat"
    },
    "groove_mid": {
        "low": "ballad_soft_kick_snare_8th_hat", "medium_low": "rock_ballad_build_up_8th_hat",
        "medium": "rock_ballad_build_up_8th_hat", "medium_high": "anthem_rock_chorus_16th_hat",
        "high": "anthem_rock_chorus_16th_hat", "default": "rock_ballad_build_up_8th_hat"
    },
    "anthem_high": {
        "low": "rock_ballad_build_up_8th_hat", "medium_low": "anthem_rock_chorus_16th_hat",
        "medium": "anthem_rock_chorus_16th_hat", "medium_high": "anthem_rock_chorus_16th_hat", # Consider a denser pattern if available
        "high": "anthem_rock_chorus_16th_hat", # Consider a denser pattern if available
        "default": "anthem_rock_chorus_16th_hat"
    },
    "default_fallback_bucket": { # Fallback if emotion isn't in EMOTION_TO_BUCKET
        "low": "no_drums", "medium_low": "default_drum_pattern", "medium": "default_drum_pattern",
        "medium_high": "default_drum_pattern", "high": "default_drum_pattern", "default": "default_drum_pattern"
    }
}

class DrumGenerator:
    def __init__(self,
                 drum_pattern_library: Optional[Dict[str, Dict[str, Any]]] = None,
                 default_instrument=m21instrument.Percussion(), # type: ignore
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.drum_pattern_library = drum_pattern_library if drum_pattern_library is not None else {}
        self.rng = random.Random() # Quick Fix 1: Initialize RNG here
        logger.info(f"DrumGen __init__: Received drum_pattern_library with {len(self.drum_pattern_library)} keys.")
        if not self.drum_pattern_library:
            logger.warning("DrumGen __init__: Received an EMPTY drum_pattern_library!")

        for default_key, default_def in DEFAULT_DRUM_PATTERNS_LIB.items():
            if default_key not in self.drum_pattern_library:
                self.drum_pattern_library[default_key] = default_def
                logger.info(f"DrumGen: Added '{default_key}' to internal library.")
        
        # Placeholder for styles that might be in BUCKET_INTENSITY_TO_STYLE but not rhythm_library
        # This ensures the generator doesn't crash if a style key is missing; it plays silence.
        # o3-san suggestion: make these minimal patterns instead of pure silence.
        # For now, keeping them as silent placeholders for explicitness.
        # A better approach for "minimal" would be to define them in rhythm_library.json.
        all_referenced_styles = set()
        for bucket_styles in BUCKET_INTENSITY_TO_STYLE.values():
            for style_key_in_lut in bucket_styles.values():
                all_referenced_styles.add(style_key_in_lut)
        
        # Add common chordmap styles too, if they're not in BUCKET_INTENSITY_TO_STYLE
        chordmap_common_styles = ["no_drums_or_sparse_cymbal", "no_drums_or_gentle_cymbal_swell", "no_drums_or_sparse_chimes"]
        all_referenced_styles.update(chordmap_common_styles)

        for style_key in all_referenced_styles:
            if style_key not in self.drum_pattern_library:
                # o3-san Item 7: Consider adding a minimal pattern here instead of just silence.
                # For example, for "ballad_soft_kick_snare_8th_hat", a very sparse kick/snare.
                # For now, sticking to silent placeholder to make missing definitions obvious.
                self.drum_pattern_library[style_key] = {
                    "description": f"Placeholder for '{style_key}' (auto-added). Define in rhythm_library.json for actual sound.",
                    "time_signature": "4/4", "swing": 0.5,
                    "pattern": [], "fill_ins": {} # Must have fill_ins for robust fill lookup
                }
                logger.info(f"DrumGen: Added silent placeholder for undefined style '{style_key}'.")

        self.default_instrument = default_instrument
        if hasattr(self.default_instrument, 'midiChannel'):
            self.default_instrument.midiChannel = 9
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        if not self.global_time_signature_obj:
            logger.error("DrumGen __init__: Failed to get global time signature object! Defaulting to 4/4.")
            self.global_time_signature_obj = meter.TimeSignature("4/4")

    def _resolve_style_key(self, emotion: str, intensity: str) -> str:
        bucket = EMOTION_TO_BUCKET.get(emotion.lower(), "default_fallback_bucket")
        style_map_for_bucket = BUCKET_INTENSITY_TO_STYLE.get(bucket)

        if not style_map_for_bucket:
            logger.error(f"DrumDyn: CRITICAL - Bucket '{bucket}' (from emotion '{emotion}') is not defined in BUCKET_INTENSITY_TO_STYLE. This should not happen if 'default_fallback_bucket' exists. Using 'default_drum_pattern'.")
            return "default_drum_pattern"
            
        resolved_style = style_map_for_bucket.get(intensity.lower()) # Try direct intensity match
        if not resolved_style: # Fallback to bucket's default, then global default
            resolved_style = style_map_for_bucket.get("default", "default_drum_pattern")
            logger.debug(f"DrumDyn: Intensity '{intensity}' in bucket '{bucket}' not directly mapped. Used fallback: '{resolved_style}'.")
        
        if resolved_style not in self.drum_pattern_library:
            logger.warning(f"DrumDyn: Dynamically resolved style_key '{resolved_style}' (for E:'{emotion}', I:'{intensity}') is NOT DEFINED in drum_pattern_library. Falling back to 'default_drum_pattern'. Please define it or check BUCKET_INTENSITY_TO_STYLE.")
            return "default_drum_pattern"
        return resolved_style

    def _choose_style_for_block(self, blk_data: Dict[str, Any]) -> str:
        drum_params_for_block = blk_data.get("part_params", {}).get("drums", {})
        explicit_style_key = drum_params_for_block.get("drum_style_key")

        # Priority 1: Explicit style key from parameters, if it's valid and exists
        if explicit_style_key and explicit_style_key.lower() != "default_style": # "default_style" means "let dynamic logic choose"
            if explicit_style_key in self.drum_pattern_library:
                logger.debug(f"DrumGen Blk {blk_data.get('section_name', 'N/A')}-{blk_data.get('chord_label', 'N/A')}: Using explicit style_key: {explicit_style_key}")
                return explicit_style_key
            else:
                logger.warning(f"DrumGen Blk {blk_data.get('section_name', 'N/A')}: Explicit style_key '{explicit_style_key}' NOT FOUND in library. Attempting dynamic selection.")
        
        # Priority 2: Musical intent
        intent: Dict[str, str] = blk_data.get("musical_intent", {})
        emotion = intent.get("emotion", "default") # Default emotion if not specified
        intensity = intent.get("intensity", "medium") # Default intensity
        
        resolved_style = self._resolve_style_key(emotion, intensity)
        logger.info(f"DrumGen Blk {blk_data.get('section_name', 'N/A')}-{blk_data.get('chord_label', 'N/A')}: Dynamic style for E:'{emotion}', I:'{intensity}' -> '{resolved_style}'")
        return resolved_style

    def _create_drum_hit(self, drum_sound_name: str, velocity_val: int, duration_ql_val: float = 0.125) -> Optional[note.Note]:
        """Creates a music21.note.Note for a drum hit."""
        # Normalize sound name
        normalized_sound_name = drum_sound_name.lower().replace(" ","_").replace("-","_")
        if normalized_sound_name == "ghost_snare":
            normalized_sound_name = "acoustic_snare" # Treat ghost snare as regular snare with lower velocity
            logger.debug(f"DrumGen: Mapping 'ghost_snare' to 'acoustic_snare' for MIDI.")
        
        # Use the unified GM_DRUM_MAP
        midi_val = GM_DRUM_MAP.get(normalized_sound_name)
        
        if midi_val is None:
            logger.warning(f"DrumGen: Sound name '{drum_sound_name}' (normalized to '{normalized_sound_name}') not found in GM_DRUM_MAP. Skipping hit.")
            return None
        try:
            hit = note.Note()
            hit.pitch = pitch.Pitch()
            hit.pitch.midi = midi_val
            hit.duration = duration.Duration(quarterLength=max(MIN_NOTE_DURATION_QL / 8.0, duration_ql_val)) # Drums are usually short
            hit.volume = m21volume.Volume(velocity=max(1, min(127, velocity_val))) # Ensure velocity is 1-127
            hit.offset = 0.0 # Initialize offset to 0, humanizer might shift this
            return hit
        except Exception as e:
            logger.error(f"DrumGen: Error creating drum hit for '{drum_sound_name}' with MIDI value {midi_val}: {e}", exc_info=True)
            return None

    def _apply_swing_to_offset(self, offset_in_pattern: float, swing_ratio: float, beat_duration_ql: float, time_signature_obj: meter.TimeSignature) -> float:
        """
        Applies swing to an offset. Assumes swing typically affects 8th note subdivisions.
        swing_ratio: 0.5 = straight. Values typically 0.5 to ~0.75.
                     Ratio of how much the first of two subdivisions takes of the beat.
                     e.g., 0.666 (2/3) for triplet feel means first 8th is 2/3, second is 1/3 of the quarter note.
        This is a simplified model and might need refinement for complex meters or 16th note swing.
        """
        if not (0.5 <= swing_ratio <= 0.8) or swing_ratio == 0.5: # No swing or invalid ratio
            return offset_in_pattern

        # How many primary beats in the pattern's bar (e.g., 4 in 4/4, 2 in 6/8 if beat is dotted quarter)
        # beat_duration_ql is the qL of one such beat.
        eighth_note_pair_duration_ql = beat_duration_ql # The duration over which two 8ths would occur
        
        # Calculate offset within the beat pair
        offset_mod_beat_pair = offset_in_pattern % eighth_note_pair_duration_ql
        
        # Determine if this offset falls on the 'late' part of a typical 8th note pair
        # For an 8th note pair, the "straight" second 8th is at 0.5 * eighth_note_pair_duration_ql
        # We only swing the second 8th of a pair.
        # This simplified check assumes 8th note swing.
        # A more robust check would look at the exact subdivision (e.g. time_signature_obj.getBeatSubdivision())
        # Epsilon for float comparison, relative to beat duration
        epsilon = beat_duration_ql * 0.05 # o3-san Item 4: Make epsilon relative

        if abs(offset_mod_beat_pair - (0.5 * eighth_note_pair_duration_ql)) < epsilon: # Is it the second 8th?
            # Calculate the shift for the second 8th note
            # If swing_ratio = 2/3, first 8th is 2/3, second starts at 2/3. Shift = (2/3 - 1/2) * pair_duration
            shift_amount = (swing_ratio - 0.5) * eighth_note_pair_duration_ql
            new_offset = offset_in_pattern + shift_amount
            # logger.debug(f"Swing applied: orig_offset={offset_in_pattern:.3f}, swung_offset={new_offset:.3f}, ratio={swing_ratio}, beat_dur={beat_duration_ql}")
            return new_offset
            
        return offset_in_pattern


    def _apply_drum_pattern_to_measure(
        self, target_part: stream.Part, pattern_events: List[Dict[str, Any]],
        measure_abs_start_offset: float, measure_duration_ql: float, base_velocity: int,
        humanize_params_for_hit: Optional[Dict[str, Any]] = None,
        swing_ratio: Optional[float] = None,
        pattern_time_signature_obj: Optional[meter.TimeSignature] = None
    ):
        if not pattern_events: return
        if pattern_time_signature_obj is None: # Should always be passed
            pattern_time_signature_obj = self.global_time_signature_obj

        for event_def in pattern_events:
            probability = event_def.get("probability", 1.0)
            if isinstance(probability, (int, float)) and self.rng.random() >= probability:
                continue
            
            instrument_name = event_def.get("instrument")
            if not instrument_name: continue

            event_offset_in_pattern = float(event_def.get("offset", 0.0))
            
            if swing_ratio is not None and pattern_time_signature_obj:
                beat_ql = pattern_time_signature_obj.beatDuration.quarterLength
                event_offset_in_pattern = self._apply_swing_to_offset(event_offset_in_pattern, swing_ratio, beat_ql, pattern_time_signature_obj)

            event_duration_ql = float(event_def.get("duration", 0.125))
            event_velocity_val = event_def.get("velocity")
            event_velocity_factor = event_def.get("velocity_factor")

            final_velocity: int
            if event_velocity_val is not None: final_velocity = int(event_velocity_val)
            elif event_velocity_factor is not None: final_velocity = int(base_velocity * float(event_velocity_factor))
            else: final_velocity = base_velocity
            final_velocity = max(1, min(127, final_velocity))

            if event_offset_in_pattern < measure_duration_ql:
                actual_hit_duration_ql = min(event_duration_ql, measure_duration_ql - event_offset_in_pattern)
                if actual_hit_duration_ql < MIN_NOTE_DURATION_QL / 8.0: continue # Avoid excessively short notes

                drum_hit = self._create_drum_hit(instrument_name, final_velocity, actual_hit_duration_ql)
                if drum_hit: # drum_hit.offset is initially 0.0
                    humanize_this_hit = humanize_params_for_hit and humanize_params_for_hit.get("humanize_opt", True)
                    if humanize_this_hit:
                        template_name = humanize_params_for_hit.get("template_name", "drum_tight")
                        custom_h_params = humanize_params_for_hit.get("custom_params", {})
                        # apply_humanization_to_element returns a *copy* with offset modified to be the *shift*
                        humanized_drum_hit = cast(note.Note, apply_humanization_to_element(drum_hit, template_name=template_name, custom_params=custom_h_params))
                        # The .offset of humanized_drum_hit now contains the timing delta.
                        time_delta_from_humanizer = humanized_drum_hit.offset
                        # Use the other properties (pitch, velocity, duration) from the humanized_drum_hit
                        drum_hit = humanized_drum_hit 
                    else:
                        time_delta_from_humanizer = 0.0
                    
                    # Calculate final insertion offset
                    final_insert_offset = measure_abs_start_offset + event_offset_in_pattern + time_delta_from_humanizer
                    drum_hit.offset = 0.0 # Reset to 0.0 as we are inserting at an absolute position in the part.
                    
                    target_part.insert(final_insert_offset, drum_hit)
            else:
                logger.debug(f"DrumGen: Event offset {event_offset_in_pattern:.2f} for '{instrument_name}' is outside current measure iter duration {measure_duration_ql:.2f}. Skipping.")

    def compose(self, processed_chord_stream: List[Dict[str, Any]]) -> stream.Part:
        drum_part = stream.Part(id="Drums")
        inst = self.default_instrument.clone() if hasattr(self.default_instrument, 'clone') else m21instrument.Percussion() # type: ignore
        if hasattr(inst, 'midiChannel'): inst.midiChannel = 9
        drum_part.insert(0, inst)
        drum_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        
        ts_to_insert = self.global_time_signature_obj.clone() if self.global_time_signature_obj and hasattr(self.global_time_signature_obj, 'clone') \
                       else get_time_signature_object(self.global_time_signature_str) # Fallback if clone fails or obj is None
        if not ts_to_insert: ts_to_insert = meter.TimeSignature("4/4") # Final fallback for TS
        drum_part.insert(0, ts_to_insert)

        if not processed_chord_stream:
            logger.warning("DrumGen compose: processed_chord_stream is empty. Returning empty drum part.")
            return drum_part
        
        logger.info(f"DrumGen (Compose): Starting dynamic style selection for {len(processed_chord_stream)} blocks.")
        for blk_idx, blk_data in enumerate(processed_chord_stream):
            blk_data.setdefault("part_params", {}).setdefault("drums", {})
            chosen_style_key = self._choose_style_for_block(blk_data)
            blk_data["part_params"]["drums"]["drum_style_key"] = chosen_style_key
            logger.debug(f"DrumGen Blk {blk_idx+1} ({blk_data.get('section_name', 'N/A')} {blk_data.get('chord_label', 'N/A')}): Set style_key to '{chosen_style_key}'")
        
        return self._compose_core(processed_chord_stream, drum_part)

    def _compose_core(self, processed_chord_stream: List[Dict[str, Any]], drum_part: stream.Part) -> stream.Part:
        if not self.global_time_signature_obj:
            logger.error("DrumGen _compose_core: global_time_signature_obj is None. Cannot proceed.")
            return drum_part

        logger.info(f"DrumGen _compose_core: Processing {len(processed_chord_stream)} blocks with dynamically set styles.")
        measures_since_last_fill = 0

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            
            drum_params = blk_data.get("part_params", {}).get("drums", {})
            style_key = drum_params.get("drum_style_key", "default_drum_pattern") 
            base_velocity = int(drum_params.get("drum_base_velocity", 80))
            
            # Intensity-based velocity adjustment (o3-san suggestion for "グルーブ強度係数")
            intensity_str = blk_data.get("musical_intent", {}).get("intensity", "medium").lower()
            if intensity_str == "high" or intensity_str == "medium_high": base_velocity = min(127, base_velocity + 8)
            elif intensity_str == "low" or intensity_str == "medium_low": base_velocity = max(20, base_velocity - 6)

            fill_interval_bars = drum_params.get("drum_fill_interval_bars", 0)
            fill_options_from_params = drum_params.get("drum_fill_keys", [])
            block_specific_fill_key = drum_params.get("drum_fill_key_override")

            humanize_this_block = drum_params.get("humanize_opt", True)
            humanize_params_for_hits: Optional[Dict[str, Any]] = None
            if humanize_this_block:
                h_template = drum_params.get("template_name", "drum_loose_fbm")
                h_custom = drum_params.get("custom_params", {})
                humanize_params_for_hits = {"humanize_opt": True, "template_name": h_template, "custom_params": h_custom}

            style_def = self.drum_pattern_library.get(style_key)
            if not style_def or "pattern" not in style_def:
                logger.warning(f"DrumGen _compose_core: Style key '{style_key}' for blk {blk_idx+1} invalid. Using 'default_drum_pattern'.")
                style_def = self.drum_pattern_library.get("default_drum_pattern", DEFAULT_DRUM_PATTERNS_LIB["default_drum_pattern"])

            main_pattern_events = style_def.get("pattern", [])
            pattern_ts_str = style_def.get("time_signature", self.global_time_signature_str)
            pattern_ts_obj = get_time_signature_object(pattern_ts_str)
            if not pattern_ts_obj: pattern_ts_obj = self.global_time_signature_obj
            
            pattern_bar_duration_ql = pattern_ts_obj.barDuration.quarterLength if pattern_ts_obj else 4.0
            if pattern_bar_duration_ql <= 0:
                logger.error(f"DrumGen: Style '{style_key}' has non-positive bar duration ({pattern_bar_duration_ql}). Skipping block.")
                continue
            
            swing_ratio_for_pattern = style_def.get("swing") # Get swing from style_def

            current_pos_in_block_ql = 0.0
            if blk_data.get("is_first_in_section", False): measures_since_last_fill = 0

            while current_pos_in_block_ql < block_duration_ql - (MIN_NOTE_DURATION_QL / 4.0):
                measure_start_abs_offset = block_offset_ql + current_pos_in_block_ql
                current_iteration_duration = min(pattern_bar_duration_ql, block_duration_ql - current_pos_in_block_ql)
                if current_iteration_duration < MIN_NOTE_DURATION_QL / 2.0: break # Avoid tiny iterations

                pattern_events_to_apply = main_pattern_events
                applied_fill_this_iteration = False
                is_last_iteration_in_block = (current_pos_in_block_ql + current_iteration_duration >= block_duration_ql - (MIN_NOTE_DURATION_QL / 8.0))
                
                available_fills_for_style = style_def.get("fill_ins", {})

                if block_specific_fill_key and is_last_iteration_in_block:
                    fill_pattern_list = available_fills_for_style.get(block_specific_fill_key)
                    if fill_pattern_list:
                        pattern_events_to_apply = fill_pattern_list
                        applied_fill_this_iteration = True
                        logger.debug(f"DrumGen _cc: Applying override fill '{block_specific_fill_key}' for style '{style_key}' at {measure_start_abs_offset:.2f}")
                    else: # Log if specific key not in this style's fills
                        logger.warning(f"DrumGen _cc: Override fill_key '{block_specific_fill_key}' NOT FOUND in fill_ins for style '{style_key}'. Main pattern used.")
                
                elif not applied_fill_this_iteration and fill_interval_bars > 0 and fill_options_from_params and \
                     available_fills_for_style and \
                     (current_iteration_duration >= pattern_bar_duration_ql - (MIN_NOTE_DURATION_QL / 8.0)) and \
                     (measures_since_last_fill + 1 >= fill_interval_bars) and \
                     is_last_iteration_in_block:
                    
                    possible_fills_for_current_style = [f_key for f_key in fill_options_from_params if f_key in available_fills_for_style]
                    if possible_fills_for_current_style:
                        chosen_fill_key = self.rng.choice(possible_fills_for_current_style)
                        fill_pattern_list = available_fills_for_style.get(chosen_fill_key) # Should exist
                        if fill_pattern_list: # Redundant check, but safe
                            pattern_events_to_apply = fill_pattern_list
                            applied_fill_this_iteration = True
                            logger.debug(f"DrumGen _cc: Applying scheduled fill '{chosen_fill_key}' for style '{style_key}' at {measure_start_abs_offset:.2f}")
                    else:
                        logger.debug(f"DrumGen _cc: No suitable fills from 'drum_fill_keys' parameter are defined in 'fill_ins' for current style '{style_key}'. No scheduled fill.")

                self._apply_drum_pattern_to_measure(
                    drum_part, pattern_events_to_apply, measure_start_abs_offset,
                    current_iteration_duration, base_velocity, humanize_params_for_hits,
                    swing_ratio=swing_ratio_for_pattern, pattern_time_signature_obj=pattern_ts_obj
                )

                if applied_fill_this_iteration: measures_since_last_fill = 0
                if current_iteration_duration >= pattern_bar_duration_ql - (MIN_NOTE_DURATION_QL / 8.0):
                    measures_since_last_fill += 1
                
                current_pos_in_block_ql += current_iteration_duration
        
        logger.info(f"DrumGen _compose_core: Finished. Drum part has {len(list(drum_part.flatten().notesAndRests))} elements.")
        return drum_part

# --- END OF FILE generator/drum_generator.py ---
