# --- START OF FILE generator/drum_generator.py (dynamic-pattern & roadmap phase1 edition) ---
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
# import music21.chord      as m21chord # 現状このファイルでは直接使われていない

import random
import logging
import math # スウィング計算で使用する可能性

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
    def apply_humanization_to_element(element, template_name=None, custom_params=None): return element
    HUMANIZATION_TEMPLATES = {}


logger = logging.getLogger(__name__)

# General MIDI Drum Map (チャンネル10)
GM_DRUM_MAP = {
    "kick": 36, "bd": 36, "acoustic_bass_drum": 35, # 35 or 36
    "snare": 38, "sd": 38, "acoustic_snare": 38, "electric_snare": 40,
    "chh": 42, "closed_hi_hat": 42,
    "phh": 44, "pedal_hi_hat": 44,
    "ohh": 46, "open_hi_hat": 46,
    "crash": 49, "crash_cymbal_1": 49, "crash_cymbal_2": 57,
    "ride": 51, "ride_cymbal_1": 51, "ride_cymbal_2": 59, "ride_bell": 53,
    "claps": 39, "hand_clap": 39,
    "rim": 37, "side_stick": 37,
    "lt": 41, "low_floor_tom": 41,
    "lmt": 43, "high_floor_tom":43, # Low-Mid Tom
    "mt": 45, "low_tom": 45,
    "tom_low": 45, # Alias
    "mht": 47, "low_mid_tom": 47, # Mid-High Tom
    "tom_mid": 47, # Alias
    "ht": 50, "high_mid_tom":48, "high_tom":50, # High Tom
    "tom_hi": 50, # Alias
    "tambourine": 54, "cowbell": 56, "vibraslap": 58,
    "shaker": 70, "agogo": 67, "cabasa": 69
}
# デフォルトフォールバックパターン
DEFAULT_DRUM_PATTERNS_LIB = {
    "default_drum_pattern": {
        "description": "Default simple kick/snare",
        "time_signature": "4/4",
        "pattern": [
            {"instrument": "kick", "offset": 0.0, "velocity": 90, "duration": 0.1},
            {"instrument": "snare", "offset": 1.0, "velocity": 90, "duration": 0.1},
            {"instrument": "kick", "offset": 2.0, "velocity": 90, "duration": 0.1},
            {"instrument": "snare", "offset": 3.0, "velocity": 90, "duration": 0.1}
        ]
    },
    "no_drums": {"description": "Silence", "time_signature": "4/4", "pattern": []}
}

# --- Dynamic Style Selection Look-up Tables (from dynamic-pattern edition) ---
EMOTION_TO_BUCKET: Dict[str, str] = {
    # soft / sad
    "quiet_pain_and_nascent_strength": "ballad_soft",
    "self_reproach_regret_deep_sadness": "ballad_soft",
    "memory_unresolved_feelings_silence": "ballad_soft",
    "reflective_transition_instrumental_passage": "ballad_soft", # Added for interludes etc.
    # mid energy storytelling
    "deep_regret_gratitude_and_realization": "groove_mid",
    "supported_light_longing_for_rebirth": "groove_mid",
    "wavering_heart_gratitude_chosen_strength": "groove_mid",
    "hope_dawn_light_gentle_guidance": "groove_mid",
    "nature_memory_floating_sensation_forgiveness": "groove_mid",
    # high-energy anthemic sections (pre-chorus / chorus)
    "acceptance_of_love_and_pain_hopeful_belief": "anthem_high",
    "trial_cry_prayer_unbreakable_heart": "anthem_high",
    "reaffirmed_strength_of_love_positive_determination": "anthem_high",
    "future_cooperation_our_path_final_resolve_and_liberation": "anthem_high",
    "default": "groove_mid" # General default
}

BUCKET_INTENSITY_TO_STYLE: Dict[str, Dict[str, str]] = {
    "ballad_soft": {
        "low": "no_drums_or_gentle_cymbal_swell", # chordmapのキーと合わせる
        "medium_low": "ballad_soft_kick_snare_8th_hat",
        "medium": "ballad_soft_kick_snare_8th_hat",
        "medium_high": "rock_ballad_build_up_8th_hat", # 少し盛り上げる
        "high": "rock_ballad_build_up_8th_hat",
        "default": "ballad_soft_kick_snare_8th_hat"
    },
    "groove_mid": {
        "low": "ballad_soft_kick_snare_8th_hat", # 静かめから
        "medium_low": "rock_ballad_build_up_8th_hat",
        "medium": "rock_ballad_build_up_8th_hat", # rhythm_library.json に合わせる
        "medium_high": "anthem_rock_chorus_16th_hat", # 強め
        "high": "anthem_rock_chorus_16th_hat", # さらに強く
        "default": "rock_ballad_build_up_8th_hat"
    },
    "anthem_high": {
        "low": "rock_ballad_build_up_8th_hat", # 導入
        "medium_low": "anthem_rock_chorus_16th_hat",
        "medium": "anthem_rock_chorus_16th_hat",
        "medium_high": "anthem_rock_chorus_16th_hat", # rhythm_library.jsonに 'anthem_double_time_hat' があればそれも可
        "high": "anthem_rock_chorus_16th_hat", # rhythm_library.jsonに 'anthem_double_time_hat' があればそれも可
        "default": "anthem_rock_chorus_16th_hat"
    },
    "default_fallback_bucket": { # Emotionがマッピングできなかった場合の最終手段
        "low": "no_drums",
        "medium_low": "default_drum_pattern",
        "medium": "default_drum_pattern",
        "medium_high": "default_drum_pattern", # よりエネルギッシュなデフォルトパターンがあれば指定
        "high": "default_drum_pattern", # 同上
        "default": "default_drum_pattern"
    }
}
# --- End of Dynamic Style Selection Look-up Tables ---

class DrumGenerator:
    def __init__(self,
                 drum_pattern_library: Optional[Dict[str, Dict[str, Any]]] = None,
                 default_instrument=m21instrument.Percussion(), # type: ignore
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.drum_pattern_library = drum_pattern_library if drum_pattern_library is not None else {}
        logger.info(f"DrumGen __init__: Received drum_pattern_library with keys: {list(self.drum_pattern_library.keys())}")
        if not self.drum_pattern_library:
            logger.warning("DrumGen __init__: Received an EMPTY drum_pattern_library!")

        # Ensure default patterns exist
        if "default_drum_pattern" not in self.drum_pattern_library:
            self.drum_pattern_library["default_drum_pattern"] = DEFAULT_DRUM_PATTERNS_LIB["default_drum_pattern"]
            logger.info("DrumGen: Added 'default_drum_pattern' to internal library.")
        if "no_drums" not in self.drum_pattern_library:
            self.drum_pattern_library["no_drums"] = DEFAULT_DRUM_PATTERNS_LIB["no_drums"]
            logger.info("DrumGen: Added 'no_drums' to internal library.")

        # Placeholder for styles that might be in chordmap but not rhythm_library
        # (This ensures the generator doesn't crash if a style key is missing, it just plays silence)
        placeholder_styles = [
            "no_drums_or_sparse_cymbal", "no_drums_or_gentle_cymbal_swell",
            "no_drums_or_sparse_chimes", "ballad_soft_kick_snare_8th_hat", # Common ones
            "rock_ballad_build_up_8th_hat", "anthem_rock_chorus_16th_hat",
            "groove_push_16ths_hat", "anthem_double_time_hat" # From BUCKET_INTENSITY_TO_STYLE
        ]
        for style_key in placeholder_styles:
            if style_key not in self.drum_pattern_library:
                self.drum_pattern_library[style_key] = {
                    "description": f"Placeholder for '{style_key}' (auto-added). Define in rhythm_library.json for actual sound.",
                    "time_signature": "4/4", # Default, can be overridden by actual definition
                    "pattern": [] # Plays silence if not defined
                }
                logger.info(f"DrumGen: Added placeholder for undefined style '{style_key}'.")

        self.default_instrument = default_instrument
        if hasattr(self.default_instrument, 'midiChannel'):
            self.default_instrument.midiChannel = 9 # Standard MIDI drum channel
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        if not self.global_time_signature_obj: # Fallback if get_time_signature_object returns None
            logger.error("DrumGen __init__: Failed to get global time signature object! Defaulting to 4/4.")
            self.global_time_signature_obj = meter.TimeSignature("4/4")


    def _resolve_style_key(self, emotion: str, intensity: str) -> str:
        """Helper to get a style key from emotion and intensity using the new tables."""
        bucket = EMOTION_TO_BUCKET.get(emotion, "default_fallback_bucket") # Fallback to a generic bucket
        
        style_map_for_bucket = BUCKET_INTENSITY_TO_STYLE.get(bucket)
        if not style_map_for_bucket: # Should not happen if default_fallback_bucket is defined
            logger.warning(f"DrumDyn: Bucket '{bucket}' not found in BUCKET_INTENSITY_TO_STYLE. Critical error in definitions. Falling back to default_drum_pattern.")
            return "default_drum_pattern"
            
        style = style_map_for_bucket.get(intensity)
        if not style:
            logger.debug(f"DrumDyn: Intensity '{intensity}' in bucket '{bucket}' not mapped. Using bucket's default or global default.")
            style = style_map_for_bucket.get("default", "default_drum_pattern")
        
        # Ensure the resolved style key actually exists in the library, otherwise fallback.
        if style not in self.drum_pattern_library:
            logger.warning(f"DrumDyn: Resolved style_key '{style}' not found in drum_pattern_library. Falling back to 'default_drum_pattern'.")
            return "default_drum_pattern"
        return style

    def _choose_style_for_block(self, blk_data: Dict[str, Any]) -> str:
        """
        Return a rhythm_library key for this block based on various factors.
        Priority:
        1. Explicit "drum_style_key" from part_params (user override).
        2. Musical intent (emotion, intensity) mapped via lookup tables.
        3. Fallback to "default_drum_pattern".
        """
        # 1. Explicit user override from chordmap part_params or even block-specific hints
        drum_params_for_block = blk_data.get("part_params", {}).get("drums", {})
        explicit_style_key = drum_params_for_block.get("drum_style_key")

        if explicit_style_key and explicit_style_key != "default_style" and explicit_style_key in self.drum_pattern_library:
            logger.debug(f"DrumGen Blk {blk_data.get('section_name', 'N/A')}-{blk_data.get('chord_label', 'N/A')}: Using explicit style_key: {explicit_style_key}")
            return explicit_style_key
        elif explicit_style_key:
             logger.warning(f"DrumGen Blk {blk_data.get('section_name', 'N/A')}: Explicit style_key '{explicit_style_key}' not in library. Will try dynamic.")


        # 2. Musical intent from composer_intent (passed via blk_data by modular_composer)
        intent: Dict[str, str] = blk_data.get("musical_intent", {})
        emotion = intent.get("emotion", "default").lower()
        intensity = intent.get("intensity", "medium").lower() # Ensure intensity has a default

        resolved_style = self._resolve_style_key(emotion, intensity)
        logger.info(f"DrumGen Blk {blk_data.get('section_name', 'N/A')}-{blk_data.get('chord_label', 'N/A')}: Dynamic style for E:'{emotion}', I:'{intensity}' -> '{resolved_style}'")
        return resolved_style
        
        # Fallback (already handled by _resolve_style_key if mappings are complete)
        # logger.debug(f"DrumGen Blk {blk_data.get('section_name', 'N/A')}: No specific style found, using 'default_drum_pattern'.")
        # return "default_drum_pattern"


    def _create_drum_hit(self, drum_sound_name: str, velocity_val: int, duration_ql_val: float = 0.125) -> Optional[note.Note]:
        actual_sound_name = drum_sound_name.lower().replace(" ","_").replace("-","_")
        if actual_sound_name == "ghost_snare":
            actual_sound_name = "acoustic_snare" # Map ghost_snare to acoustic_snare (velocity difference)
            logger.debug(f"DrumGen: Treating 'ghost_snare' as 'acoustic_snare' for MIDI mapping.")
        
        # GM_DRUM_MAP already contains common tom names like lt, mt, ht.
        # If rhythm_library uses tom1, tom2, tom3, ensure they map to existing keys or add them.
        # For simplicity, we can map tom1->ht, tom2->mt, tom3->lt if needed, or use more specific GM numbers.
        tom_map = {"tom1": "ht", "tom2": "mt", "tom3": "lt"} # Example mapping
        if actual_sound_name in tom_map:
            actual_sound_name = tom_map[actual_sound_name]

        midi_val = GM_DRUM_MAP.get(actual_sound_name)
        if midi_val is None:
            logger.warning(f"DrumGen: Sound '{drum_sound_name}' (mapped to '{actual_sound_name}') not in GM_DRUM_MAP. Skipping hit.")
            return None
        try:
            hit = note.Note()
            # For drums, pitch is for mapping, not tonal sound.
            hit.pitch = pitch.Pitch()
            hit.pitch.midi = midi_val
            # Ensure duration is not too short, but drums are often short.
            hit.duration = duration.Duration(quarterLength=max(MIN_NOTE_DURATION_QL / 8, duration_ql_val)) # Very short minimum
            hit.volume = m21volume.Volume(velocity=max(1, min(127, velocity_val)))
            return hit
        except Exception as e:
            logger.error(f"DrumGen: Error creating hit for '{drum_sound_name}': {e}", exc_info=True)
            return None

    def _apply_swing_to_offset(self, offset_in_pattern: float, swing_ratio: float, beat_duration_ql: float, time_signature_obj: meter.TimeSignature) -> float:
        """
        Applies swing to an offset.
        swing_ratio: 0.5 = straight, >0.5 means delay for the off-beat.
                     e.g., 0.66 for 2:1 triplet feel.
        """
        if swing_ratio == 0.5: # No swing
            return offset_in_pattern

        # Determine if the note is on a subdivision that should be swung (typically 8th or 16th off-beats)
        # This is a simplified example for 8th note swing in a 4/4 like meter
        # A full implementation needs to consider the time signature's beat subdivision.
        
        # Assuming beat_duration_ql is the duration of one beat (e.g., 1.0 for quarter note in 4/4)
        eighth_note_duration_ql = beat_duration_ql / 2.0
        
        # Is the note on an "off-beat" 8th? (e.g., at 0.5, 1.5, 2.5, 3.5 relative to start of a beat)
        # We need the offset relative to the beat start.
        beat_number = math.floor(offset_in_pattern / beat_duration_ql)
        offset_within_beat = offset_in_pattern - (beat_number * beat_duration_ql)

        # Check if it's close to an off-beat 8th position
        # (e.g., if eighth_note_duration_ql is 0.5, check if offset_within_beat is close to 0.5)
        # This threshold handles floating point inaccuracies.
        epsilon = 0.01 
        if abs(offset_within_beat - eighth_note_duration_ql) < epsilon:
            # It's an off-beat 8th. Calculate the delay.
            # Straight 8th is at 0.5 * beat_duration_ql within the beat.
            # Swung 8th is at swing_ratio * beat_duration_ql within the beat.
            delay = (swing_ratio - 0.5) * beat_duration_ql
            swung_offset_within_beat = eighth_note_duration_ql + delay
            
            # Reconstruct the full offset
            return (beat_number * beat_duration_ql) + swung_offset_within_beat
            
        return offset_in_pattern


    def _apply_drum_pattern_to_measure(
        self, target_part: stream.Part, pattern_events: List[Dict[str, Any]],
        measure_abs_start_offset: float, measure_duration_ql: float, base_velocity: int,
        humanize_params_for_hit: Optional[Dict[str, Any]] = None,
        swing_ratio: Optional[float] = None, # Added for swing
        pattern_time_signature_obj: Optional[meter.TimeSignature] = None # Added for swing context
    ):
        if not pattern_events: return

        for event_def in pattern_events:
            # --- Probability (DSL Expansion) ---
            probability = event_def.get("probability", 1.0)
            if isinstance(probability, (int, float)) and self.rng.random() >= probability:
                logger.debug(f"DrumGen: Skipped event due to probability {probability}: {event_def.get('instrument')}")
                continue
            
            instrument_name = event_def.get("instrument")
            event_offset_in_pattern = float(event_def.get("offset", 0.0))
            event_duration_ql = float(event_def.get("duration", 0.125)) # Default duration for drum hits

            # --- Apply Swing (Roadmap item 2, DSL item 5) ---
            if swing_ratio is not None and swing_ratio != 0.5 and pattern_time_signature_obj:
                # Simple swing: affects 8th note offbeats if beat is quarter note.
                # More robust swing would analyze beat subdivision (e.g. 16ths if pattern_ts is x/8)
                beat_ql = pattern_time_signature_obj.beatDuration.quarterLength
                original_offset_for_swing_calc = event_offset_in_pattern
                event_offset_in_pattern = self._apply_swing_to_offset(original_offset_for_swing_calc, swing_ratio, beat_ql, pattern_time_signature_obj)
                if abs(event_offset_in_pattern - original_offset_for_swing_calc) > 0.01:
                     logger.debug(f"DrumGen: Applied swing {swing_ratio}. Offset {original_offset_for_swing_calc:.3f} -> {event_offset_in_pattern:.3f}")


            event_velocity_val = event_def.get("velocity")
            event_velocity_factor = event_def.get("velocity_factor")

            if not instrument_name:
                logger.debug(f"DrumGen: Event has no instrument name. Skipping. Event: {event_def}")
                continue

            final_velocity: int
            if event_velocity_val is not None:
                final_velocity = int(event_velocity_val)
            elif event_velocity_factor is not None:
                final_velocity = int(base_velocity * float(event_velocity_factor))
            else:
                final_velocity = base_velocity
            final_velocity = max(1, min(127, final_velocity)) # Ensure MIDI velocity is 1-127

            # Ensure the event offset is within the current measure's iteration duration
            if event_offset_in_pattern < measure_duration_ql:
                # Calculate the actual duration of the hit, ensuring it doesn't spill past the measure iteration
                actual_hit_duration_ql = min(event_duration_ql, measure_duration_ql - event_offset_in_pattern)
                if actual_hit_duration_ql < MIN_NOTE_DURATION_QL / 8: # Avoid extremely short notes
                    continue

                drum_hit = self._create_drum_hit(instrument_name, final_velocity, actual_hit_duration_ql)
                if drum_hit:
                    if humanize_params_for_hit and humanize_params_for_hit.get("humanize_opt", True): # Check humanize_opt
                        template_name = humanize_params_for_hit.get("template_name", "drum_tight")
                        custom_h_params = humanize_params_for_hit.get("custom_params", {})
                        drum_hit = cast(note.Note, apply_humanization_to_element(drum_hit, template_name=template_name, custom_params=custom_h_params))
                    
                    # Ensure the humanized element's offset (which is relative to its own start) is reset
                    # before inserting at the calculated absolute offset.
                    insert_at_offset = measure_abs_start_offset + event_offset_in_pattern
                    
                    # The offset from humanization is a shift, add it to insert_at_offset
                    # apply_humanization_to_element now modifies offset directly, which is fine if it's a small shift
                    # If humanization returns a large offset, it means the offset within the pattern.
                    # For now, assume humanizer applies a small delta, and we use the (potentially swung) event_offset_in_pattern.
                    # If drum_hit.offset was modified by humanizer to be non-zero *relative to its intended start*,
                    # it should be added. The current humanizer returns a copy with offset modified.

                    # The humanizer returns a copy; its .offset is the NEW offset.
                    # We need the delta if its .offset was non-zero before humanization.
                    # Let's assume humanizer applies shift and the returned .offset is the final desired local offset.
                    # The `event_offset_in_pattern` is the structural offset. Humanizer provides a micro-timing shift.
                    # A better way: `apply_humanization_to_element` should NOT change `drum_hit.offset` itself,
                    # but return the shift, or we apply the shift here based on its output.
                    # Given current `apply_humanization_to_element`, let's assume its internal offset is a relative shift.

                    # Let's clarify: apply_humanization_to_element *might* change element.offset.
                    # If it does, it's a shift.
                    time_shift_from_humanize = drum_hit.offset # If humanizer sets this as the *shift*
                    # If humanizer sets it as an *absolute* offset from 0, then this is wrong.
                    # Assuming `apply_humanization_to_element` sets `element.offset` to be the *new intended local offset*
                    # If the original was 0 and humanizer made it 0.01, then insert_at_offset should be measure_abs_start_offset + event_offset_in_pattern + 0.01
                    # For now, the `apply_humanization_to_element` should return an element with its `.offset` being the desired *shift* from original.
                    # Or, it modifies `drum_hit.offset` to be the new, slightly shifted offset for that hit.
                    # The current `humanizer.py` does: `element_copy.offset += time_shift`
                    # So, if `drum_hit` was created with offset 0, its .offset now contains the shift.
                    
                    final_insert_offset = measure_abs_start_offset + event_offset_in_pattern + drum_hit.offset
                    drum_hit.offset = 0.0 # Reset to 0 before inserting into part at absolute position

                    target_part.insert(final_insert_offset, drum_hit)
            else:
                logger.debug(f"DrumGen: Event offset {event_offset_in_pattern:.2f} for '{instrument_name}' is outside current measure duration {measure_duration_ql:.2f}. Skipping.")


    def compose(self, processed_chord_stream: List[Dict[str, Any]]) -> stream.Part:
        """
        Main composition method. Dynamically selects drum style for each block
        and then delegates to _compose_core for actual note generation.
        """
        drum_part = stream.Part(id="Drums")
        # Ensure instrument is set and on MIDI channel 10 for drums
        inst = self.default_instrument.clone() if hasattr(self.default_instrument, 'clone') else m21instrument.Percussion() # type: ignore
        if hasattr(inst, 'midiChannel'):
            inst.midiChannel = 9 # Music21 uses 0-indexed channels for Stream, MIDI is 1-indexed (ch 10 = index 9)
        drum_part.insert(0, inst)
        
        drum_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        
        # Clone time signature to avoid shared object issues if it's modified later
        ts_to_insert = self.global_time_signature_obj.clone() if self.global_time_signature_obj and hasattr(self.global_time_signature_obj, 'clone') \
                       else get_time_signature_object(self.global_time_signature_str)
        drum_part.insert(0, ts_to_insert)


        if not processed_chord_stream:
            logger.warning("DrumGen compose: processed_chord_stream is empty. Returning empty drum part.")
            return drum_part
        
        # Initialize RNG for this composition pass if not already using a shared one
        self.rng = getattr(self, 'rng', random.Random())


        logger.info(f"DrumGen (New Compose): Starting dynamic style selection for {len(processed_chord_stream)} blocks.")
        for blk_idx, blk_data in enumerate(processed_chord_stream):
            # Ensure 'part_params' and 'drums' sub-dictionary exist
            blk_data.setdefault("part_params", {}).setdefault("drums", {})
            
            # Determine and store the style key for this block
            chosen_style_key = self._choose_style_for_block(blk_data)
            blk_data["part_params"]["drums"]["drum_style_key"] = chosen_style_key
            logger.debug(f"DrumGen Blk {blk_idx+1} ({blk_data.get('section_name', 'N/A')} {blk_data.get('chord_label', 'N/A')}): Set style_key to '{chosen_style_key}'")

        # Delegate to the original core composition logic
        return self._compose_core(processed_chord_stream, drum_part)


    def _compose_core(self, processed_chord_stream: List[Dict[str, Any]], drum_part: stream.Part) -> stream.Part:
        """
        Core drum pattern application logic (adapted from the original compose method).
        Assumes drum_part is already created and global settings (tempo, ts) are inserted.
        Relies on 'drum_style_key' being present in blk_data["part_params"]["drums"].
        """
        if not self.global_time_signature_obj: # Should have been set in __init__
            logger.error("DrumGen _compose_core: global_time_signature_obj is None. Cannot proceed reliably.")
            return drum_part # Return empty or partially filled part

        logger.info(f"DrumGen _compose_core: Processing {len(processed_chord_stream)} blocks.")
        measures_since_last_fill = 0 # Tracks measures for fill scheduling

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            
            drum_params = blk_data.get("part_params", {}).get("drums", {})
            # style_key is now pre-determined by the new compose() method
            style_key = drum_params.get("drum_style_key", "default_drum_pattern") 
            
            base_velocity = int(drum_params.get("drum_base_velocity", 80))
            # Roadmap: グルーブ強度係数 (intensityに応じてvelocity微調整)
            # intensity = blk_data.get("musical_intent", {}).get("intensity", "medium").lower()
            # if intensity == "high": base_velocity = min(127, base_velocity + 8)
            # elif intensity == "low": base_velocity = max(20, base_velocity - 6)

            fill_interval_bars = drum_params.get("drum_fill_interval_bars", 0) # 0 means no scheduled fills based on interval
            fill_options_from_params = drum_params.get("drum_fill_keys", []) # List of fill keys
            block_specific_fill_key = drum_params.get("drum_fill_key_override") # Explicit fill for this block

            # Humanization parameters for hits within this block
            humanize_this_block = drum_params.get("humanize_opt", True) # Respect humanize_opt
            humanize_params_for_hits: Optional[Dict[str, Any]] = None
            if humanize_this_block:
                # Consolidate humanization param fetching
                default_h_cfg = {} # Could be from DEFAULT_CONFIG if available here
                h_template = drum_params.get("template_name", default_h_cfg.get("default_humanize_style_template", "drum_loose_fbm"))
                h_custom = drum_params.get("custom_params", {}) # Already resolved by translate_keywords
                humanize_params_for_hits = {"humanize_opt": True, "template_name": h_template, "custom_params": h_custom}


            style_def = self.drum_pattern_library.get(style_key)
            if not style_def or "pattern" not in style_def:
                logger.warning(f"DrumGen _compose_core: Style key '{style_key}' for blk {blk_idx+1} not found or invalid. Using 'default_drum_pattern'.")
                style_def = self.drum_pattern_library.get("default_drum_pattern", DEFAULT_DRUM_PATTERNS_LIB["default_drum_pattern"])

            main_pattern_events = style_def.get("pattern", [])
            pattern_ts_str = style_def.get("time_signature", self.global_time_signature_str)
            pattern_ts_obj = get_time_signature_object(pattern_ts_str)
            if not pattern_ts_obj: # Fallback for pattern_ts_obj
                logger.warning(f"DrumGen: Invalid time signature '{pattern_ts_str}' for style '{style_key}'. Using global TS.")
                pattern_ts_obj = self.global_time_signature_obj

            pattern_bar_duration_ql = pattern_ts_obj.barDuration.quarterLength if pattern_ts_obj else 4.0
            if pattern_bar_duration_ql <= 0:
                logger.error(f"DrumGen: Pattern time signature for '{style_key}' results in non-positive bar duration ({pattern_bar_duration_ql}). Skipping for this block.")
                continue
            
            # Roadmap: Pattern DSL - "swing"
            swing_ratio_for_pattern = style_def.get("swing") # e.g., 0.55


            # --- Roadmap: 手数アップロジック (Chorusで16分ハイハット版など) ---
            # This is a placeholder. A more robust solution would involve pattern transformation functions
            # or specific "16th-hat-version" patterns in the library.
            # current_section = blk_data.get("section_name", "").lower()
            # composer_intensity = blk_data.get("musical_intent", {}).get("intensity", "medium").lower()
            # if "chorus" in current_section and composer_intensity in ["high", "medium_high"]:
            #    if style_key == "anthem_rock_chorus_16th_hat": # Example
            #        # Attempt to find or generate a denser hi-hat version
            #        # main_pattern_events = self._get_denser_hihat_pattern(main_pattern_events)
            #        pass


            current_pos_in_block_ql = 0.0
            if blk_data.get("is_first_in_section", False): # Reset fill counter for new section
                measures_since_last_fill = 0

            # Loop through the block, applying the pattern measure by measure (or pattern_bar_duration_ql)
            while current_pos_in_block_ql < block_duration_ql - (MIN_NOTE_DURATION_QL / 4.0): # Loop while there's space
                measure_start_abs_offset = block_offset_ql + current_pos_in_block_ql
                # Duration for this iteration: either full pattern bar or remaining block duration
                current_iteration_duration = min(pattern_bar_duration_ql, block_duration_ql - current_pos_in_block_ql)

                if current_iteration_duration < MIN_NOTE_DURATION_QL: # Too short to process
                    break

                pattern_events_to_apply = main_pattern_events
                applied_fill_this_iteration = False
                
                # Determine if this is effectively the last measure/iteration within the current block
                is_last_iteration_in_block = (current_pos_in_block_ql + current_iteration_duration >= block_duration_ql - (MIN_NOTE_DURATION_QL / 8.0))

                # --- Fill Logic ---
                # 1. Explicit fill for the block (applies on the last iteration of the block)
                if block_specific_fill_key and is_last_iteration_in_block:
                    fill_pattern_list = style_def.get("fill_ins", {}).get(block_specific_fill_key)
                    if fill_pattern_list:
                        pattern_events_to_apply = fill_pattern_list
                        applied_fill_this_iteration = True
                        logger.debug(f"DrumGen _compose_core: Applying block override fill '{block_specific_fill_key}' at abs_offset {measure_start_abs_offset:.2f}")
                    else:
                        logger.warning(f"DrumGen _compose_core: block_specific_fill_key '{block_specific_fill_key}' not found in fill_ins for style '{style_key}'.")
                
                # 2. Scheduled fill based on interval (applies if not overridden and conditions met)
                #    Only apply if this iteration completes a bar and it's the last iteration in the block.
                elif not applied_fill_this_iteration and \
                     fill_interval_bars > 0 and \
                     fill_options_from_params and \
                     (current_iteration_duration >= pattern_bar_duration_ql - (MIN_NOTE_DURATION_QL / 8.0)) and \
                     (measures_since_last_fill + 1 >= fill_interval_bars) and \
                     is_last_iteration_in_block:
                    
                    chosen_fill_key = self.rng.choice(fill_options_from_params)
                    fill_pattern_list = style_def.get("fill_ins", {}).get(chosen_fill_key)
                    if fill_pattern_list:
                        pattern_events_to_apply = fill_pattern_list
                        applied_fill_this_iteration = True
                        logger.debug(f"DrumGen _compose_core: Applying scheduled fill '{chosen_fill_key}' (interval: {fill_interval_bars} bars) at abs_offset {measure_start_abs_offset:.2f}")
                    else:
                        logger.warning(f"DrumGen _compose_core: chosen_fill_key '{chosen_fill_key}' not found for style '{style_key}'.")

                # Apply the chosen pattern (main or fill)
                self._apply_drum_pattern_to_measure(
                    drum_part,
                    pattern_events_to_apply,
                    measure_start_abs_offset,
                    current_iteration_duration, # Pass the duration for this specific iteration
                    base_velocity,
                    humanize_params_for_hits,
                    swing_ratio=swing_ratio_for_pattern, # Pass swing ratio
                    pattern_time_signature_obj=pattern_ts_obj # Pass pattern's TS for swing context
                )

                if applied_fill_this_iteration:
                    measures_since_last_fill = 0 # Reset counter after a fill
                
                # Increment measure counter only if a full bar of the pattern was applied
                if current_iteration_duration >= pattern_bar_duration_ql - (MIN_NOTE_DURATION_QL / 8.0):
                    measures_since_last_fill += 1
                
                current_pos_in_block_ql += current_iteration_duration
            
            # --- Roadmap: 休符挿入 (セクション切れ目のシンバルなど) ---
            # if style_key.startswith("no_drums") and blk_data.get("is_last_in_section"):
            #    # Add a light cymbal hit at block_offset_ql + block_duration_ql - 0.5 or similar
            #    pass


        logger.info(f"DrumGen _compose_core: Finished. Drum part has {len(list(drum_part.flatten().notesAndRests))} elements.")
        return drum_part

# --- END OF FILE generator/drum_generator.py ---
