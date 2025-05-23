# --- START OF FILE generators/drum_generator.py (2023-05-22 統合・強化版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence, Union # Union を追加
from music21 import stream, note, tempo, meter, instrument as m21instrument, volume, duration, pitch
import random
import logging
import numpy as np # f分の1ゆらぎ生成に必要
import copy # deepcopyのため

try:
    from .core_music_utils import get_time_signature_object, MIN_NOTE_DURATION_QL, sanitize_chord_label
except ImportError:
    # --- Fallback definitions ---
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("DrumGen: Could not import from .core_music_utils. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except meter.MeterException:
             logger_fallback.warning(f"Fallback GTSO: Invalid TS '{ts_str}'. Default 4/4.")
             return meter.TimeSignature("4/4")
        except Exception as e_gts_fb:
            logger_fallback.error(f"Fallback GTSO: Error for TS '{ts_str}': {e_gts_fb}. Default 4/4.")
            return meter.TimeSignature("4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: # Dummy fallback
        if not label or label.strip().lower() in ["rest", "n.c.", "nc", "none"]: return None
        return label.strip()
    # --- End of Fallback definitions ---

logger = logging.getLogger(__name__)

GM_DRUM_MAP: Dict[str, int] = {
    "kick": 36, "acoustic_bass_drum": 35, "bass_drum_1": 36, "bd": 36,
    "snare": 38, "acoustic_snare": 38, "sd": 38,
    "electric_snare": 40, "hand_clap": 39, "claps": 39,
    "closed_hi_hat": 42, "chh": 42, "closed_hat": 42,
    "pedal_hi_hat": 44, "phh": 44, "pedal_hat": 44,
    "open_hi_hat": 46, "ohh": 46, "open_hat": 46,
    "low_tom": 41, "lt": 41, "low_floor_tom": 41,
    "low_mid_tom": 47, "lmt": 47,
    "high_mid_tom": 48, "hmt": 48,
    "high_tom": 50, "ht": 50, "high_floor_tom": 43, # Note: GM high floor tom is 43
    "crash_cymbal_1": 49, "crash": 49, "crash1": 49,
    "crash_cymbal_2": 57, "crash2": 57,
    "ride_cymbal_1": 51, "ride": 51, "ride1": 51,
    "ride_cymbal_2": 59, "ride2": 59,
    "ride_bell": 53,
    "tambourine": 54, "splash_cymbal": 55, "cowbell": 56,
    "vibraslap": 58, "chinese_cymbal": 52,
    "rim_shot": 37, "rim": 37, "side_stick": 37,
    # Aliases from music_generators.py
    "hat": 42, # Default hat to closed hi-hat
}

# グローバルなデフォルトパターンライブラリ（外部JSONからロードするのが理想）
DEFAULT_DRUM_PATTERNS_LIB: Dict[str, Dict[str, Any]] = {
    "default_drum_pattern": {
        "description": "Default simple kick and snare (Global Fallback).",
        "time_signature": "4/4",
        "pattern": [ # リストオブディクト形式を推奨
            {"instrument": "kick", "offset": 0.0, "velocity": 90, "duration": 0.1},
            {"instrument": "snare", "offset": 1.0, "velocity": 90, "duration": 0.1},
            {"instrument": "kick", "offset": 2.0, "velocity": 90, "duration": 0.1},
            {"instrument": "snare", "offset": 3.0, "velocity": 90, "duration": 0.1}
        ]
    },
    "no_drums": {"description": "Silence.", "time_signature": "4/4", "pattern": []}
    # 他のパターンはrhythm_library.jsonからロードされることを期待
}

# --- Humanization functions (from music_generators.py, adapted) ---
def generate_fractional_noise(length: int, hurst: float = 0.7, scale_factor: float = 1.0) -> List[float]: # Renamed scale to scale_factor
    if length <= 0: return []
    white_noise = np.random.randn(length)
    fft_white = np.fft.fft(white_noise)
    freqs = np.fft.fftfreq(length)
    # Avoid division by zero for freqs[0]
    freqs[0] = 1e-6 if freqs.size > 0 and freqs[0] == 0 else freqs[0]
    
    filter_amplitude = np.abs(freqs) ** (-hurst)
    if freqs.size > 0: filter_amplitude[0] = 0 # Ensure DC component is zero after power law
    
    fft_fbm = fft_white * filter_amplitude
    fbm_noise = np.fft.ifft(fft_fbm).real
    
    std_dev = np.std(fbm_noise)
    if std_dev != 0:
        fbm_norm = scale_factor * (fbm_noise - np.mean(fbm_noise)) / std_dev
    else:
        fbm_norm = np.zeros(length)
    return fbm_norm.tolist()

def apply_drum_hit_humanization(
    drum_hit: note.Note,
    time_variation: float = 0.01,      # Max timing deviation in quarter lengths
    duration_percentage: float = 0.05, # Max duration change as a percentage
    velocity_variation: int = 5,       # Max velocity change (absolute)
    use_fbm_time: bool = False,        # Use fractional brownian motion for timing
    fbm_time_scale: float = 0.01,
    fbm_hurst: float = 0.6
) -> note.Note:
    
    n_copy = copy.deepcopy(drum_hit) # Work on a copy

    # Timing variation
    if use_fbm_time: # Using a single value from fbm for this one note
        time_shift = generate_fractional_noise(1, hurst=fbm_hurst, scale_factor=fbm_time_scale)[0]
    else:
        time_shift = random.uniform(-time_variation, time_variation)
    n_copy.offset += time_shift
    if n_copy.offset < 0: n_copy.offset = 0 # Ensure offset doesn't become negative

    # Duration variation (less critical for drums, but can add subtle realism)
    if n_copy.duration: # Check if duration object exists
        original_ql = n_copy.duration.quarterLength
        duration_change = original_ql * random.uniform(-duration_percentage, duration_percentage)
        new_ql = max(MIN_NOTE_DURATION_QL / 8, original_ql + duration_change) # Ensure minimum duration
        n_copy.duration.quarterLength = new_ql

    # Velocity variation
    if hasattr(n_copy, 'volume') and n_copy.volume is not None and hasattr(n_copy.volume, 'velocity'):
        base_vel = n_copy.volume.velocity if n_copy.volume.velocity is not None else 80 # Default if None
        vel_change = random.randint(-velocity_variation, velocity_variation)
        n_copy.volume.velocity = max(1, min(127, base_vel + vel_change))
    else: # If no volume object, create one
        base_vel = 80
        vel_change = random.randint(-velocity_variation, velocity_variation)
        n_copy.volume = volume.Volume(velocity=max(1, min(127, base_vel + vel_change)))
        
    return n_copy

class DrumGenerator:
    def __init__(self,
                 drum_pattern_library: Optional[Dict[str, Dict[str, Any]]] = None,
                 default_instrument=m21instrument.Percussion(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.drum_pattern_library = drum_pattern_library if drum_pattern_library is not None else {}
        if "default_drum_pattern" not in self.drum_pattern_library:
            self.drum_pattern_library["default_drum_pattern"] = DEFAULT_DRUM_PATTERNS_LIB["default_drum_pattern"]
            logger.info("DrumGen: Added 'default_drum_pattern' from internal defaults.")
        if "no_drums" not in self.drum_pattern_library:
             self.drum_pattern_library["no_drums"] = DEFAULT_DRUM_PATTERNS_LIB["no_drums"]
             logger.info("DrumGen: Added 'no_drums' pattern from internal defaults.")
        # Ensure other custom patterns from chordmap (like "no_drums_or_sparse_cymbal") are also in the library
        # This should ideally be handled by modular_composer loading rhythm_library.json fully.
        # For robustness, we can add known custom ones if not present.
        custom_drum_styles_from_chordmap = [
            "no_drums_or_sparse_cymbal", "no_drums_or_gentle_cymbal_swell", "no_drums_or_sparse_chimes"
        ]
        for cds in custom_drum_styles_from_chordmap:
            if cds not in self.drum_pattern_library:
                self.drum_pattern_library[cds] = {"description": f"{cds} (auto-added, empty pattern).", "time_signature": "4/4", "pattern": []}
                logger.info(f"DrumGen: Added placeholder for custom style '{cds}'. Ensure it's defined in rhythm_library.json for actual content.")


        self.default_instrument = default_instrument
        if hasattr(self.default_instrument, 'midiChannel'):
            self.default_instrument.midiChannel = 9 # Standard MIDI drum channel
            
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _create_drum_hit(self, drum_sound_name: str, velocity_val: int, duration_ql_val: float = 0.125) -> Optional[note.Note]:
        midi_val = GM_DRUM_MAP.get(drum_sound_name.lower().replace(" ", "_").replace("-","_")) # Normalize name
        if midi_val is None:
            logger.warning(f"DrumGen: Drum sound '{drum_sound_name}' not found in GM_DRUM_MAP. Skipping this hit.")
            return None
        try:
            hit = note.Note()
            hit.pitch = pitch.Pitch() # Create pitch object
            hit.pitch.midi = midi_val
            hit.duration = duration.Duration(quarterLength=max(MIN_NOTE_DURATION_QL / 4, duration_ql_val)) # Ensure minimum sensible duration
            hit.volume = volume.Volume(velocity=max(1, min(127, velocity_val))) # Clamp velocity
            return hit
        except Exception as e:
            logger.error(f"DrumGen: Error creating drum hit for '{drum_sound_name}' with MIDI {midi_val}: {e}", exc_info=True)
            return None

    def _apply_drum_pattern_to_measure(
        self,
        target_part: stream.Part,
        pattern_events: List[Dict[str, Any]], # Expecting list of dicts
        measure_abs_start_offset: float,
        measure_duration_ql: float,
        base_velocity: int, # The target average velocity for this measure
        humanize_settings: Optional[Dict[str, Any]] = None # Optional humanization parameters
    ):
        if not pattern_events:
            return

        for event_def in pattern_events:
            instrument_name = event_def.get("instrument")
            event_offset_in_pattern = float(event_def.get("offset", 0.0))
            event_duration_ql = float(event_def.get("duration", 0.125)) # Default duration for a drum hit
            # Velocity in pattern can be absolute or a factor
            event_velocity = event_def.get("velocity") 
            event_velocity_factor = event_def.get("velocity_factor")

            if not instrument_name:
                logger.warning(f"DrumGen: Pattern event missing 'instrument': {event_def}")
                continue

            # Calculate final velocity for this hit
            final_velocity: int
            if event_velocity is not None:
                final_velocity = int(event_velocity)
            elif event_velocity_factor is not None:
                final_velocity = int(base_velocity * float(event_velocity_factor))
            else: # Default to base_velocity if neither is specified
                final_velocity = base_velocity
            
            final_velocity = max(1, min(127, final_velocity)) # Clamp

            # Ensure the hit is within the current measure's bounds
            if event_offset_in_pattern < measure_duration_ql:
                # Actual duration of the hit, ensuring it doesn't spill past the measure end from its start
                actual_hit_duration_ql = min(event_duration_ql, measure_duration_ql - event_offset_in_pattern)
                if actual_hit_duration_ql < MIN_NOTE_DURATION_QL / 8: # Too short
                    continue

                drum_hit = self._create_drum_hit(instrument_name, final_velocity, actual_hit_duration_ql)
                if drum_hit:
                    drum_hit.offset = measure_abs_start_offset + event_offset_in_pattern # Set absolute offset
                    if humanize_settings:
                        drum_hit = apply_drum_hit_humanization(drum_hit, **humanize_settings)
                    target_part.insert(drum_hit.offset, drum_hit) # music21 handles sorting by offset
            else:
                logger.debug(f"DrumGen: Hit '{instrument_name}' at pattern offset {event_offset_in_pattern} is outside measure duration {measure_duration_ql}. Skipping.")


    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        drum_part = stream.Part(id="Drums")
        drum_part.insert(0, self.default_instrument)
        drum_part.insert(0, tempo.MetronomeMark(number=self.global_tempo)) # Tempo at the start of the part
        drum_part.insert(0, self.global_time_signature_obj.clone()) # Time signature at the start

        if not processed_chord_stream:
            logger.info("DrumGen: Empty processed_chord_stream. Returning empty drum part.")
            return drum_part
            
        logger.info(f"DrumGen: Starting drum composition for {len(processed_chord_stream)} blocks.")
        
        measures_since_last_fill = 0 # Counter for interval-based fills

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            
            drum_params_for_block = blk_data.get("part_params", {}).get("drums", {})
            style_key = drum_params_for_block.get("drum_style_key", "default_drum_pattern")
            base_velocity_for_block = int(drum_params_for_block.get("drum_base_velocity", 80))
            
            fill_interval_bars = drum_params_for_block.get("drum_fill_interval_bars", 0) # 0 means no interval fills
            available_fill_keys = drum_params_for_block.get("drum_fill_keys", [])
            # Check for a fill explicitly requested for this block (e.g., at section end)
            block_specific_fill_key = drum_params_for_block.get("drum_fill_key_override") 
            
            # Humanization settings (can be made configurable per block/section later)
            humanize_this_block = drum_params_for_block.get("humanize", True) # Default to true
            humanize_settings = {
                "time_variation": drum_params_for_block.get("humanize_time_var", 0.015),
                "duration_percentage": drum_params_for_block.get("humanize_dur_perc", 0.03),
                "velocity_variation": drum_params_for_block.get("humanize_vel_var", 6),
                "use_fbm_time": drum_params_for_block.get("humanize_fbm_time", False),
                "fbm_time_scale": drum_params_for_block.get("humanize_fbm_scale", 0.01),
            } if humanize_this_block else None

            logger.debug(f"Drum Blk {blk_idx+1}: Style='{style_key}', Offset={block_offset_ql:.2f}, Len={block_duration_ql:.2f}, BaseVel={base_velocity_for_block}")

            style_definition = self.drum_pattern_library.get(style_key)
            if not style_definition or "pattern" not in style_definition:
                logger.warning(f"DrumGen: Style '{style_key}' or its pattern not found in library. Using 'default_drum_pattern'.")
                style_definition = self.drum_pattern_library.get("default_drum_pattern", DEFAULT_DRUM_PATTERNS_LIB["default_drum_pattern"])
                if not style_definition or "pattern" not in style_definition:
                    logger.error("DrumGen: Critical - Default drum pattern is also invalid or missing. Skipping block.")
                    continue
            
            main_pattern_events = style_definition.get("pattern", [])
            pattern_time_signature_str = style_definition.get("time_signature", self.global_time_signature_str)
            pattern_ts_obj = get_time_signature_object(pattern_time_signature_str)
            pattern_bar_duration_ql = pattern_ts_obj.barDuration.quarterLength

            if pattern_bar_duration_ql <= 0:
                logger.error(f"DrumGen: Invalid bar duration ({pattern_bar_duration_ql}) for pattern '{style_key}'. Skipping block.")
                continue

            # Iterate through measures within the block
            current_block_time_ql = 0.0
            measure_index_in_block = 0
            
            if blk_data.get("is_first_in_section", False): # Reset fill counter at new section
                measures_since_last_fill = 0

            while current_block_time_ql < block_duration_ql - MIN_NOTE_DURATION_QL / 4:
                measure_start_abs_offset = block_offset_ql + current_block_time_ql
                # Duration of this specific measure iteration (can be shorter than pattern_bar_duration_ql if at block end)
                current_measure_iteration_duration_ql = min(pattern_bar_duration_ql, block_duration_ql - current_block_time_ql)
                
                if current_measure_iteration_duration_ql < MIN_NOTE_DURATION_QL: # Too short to process
                    break

                pattern_to_apply_this_measure = main_pattern_events
                applied_fill_this_measure = False

                # Check for block-specific fill override (highest priority)
                # Apply if this is the last measure iteration that fully fits or mostly fits the pattern's bar duration
                is_effectively_last_measure_of_block = (current_block_time_ql + pattern_bar_duration_ql >= block_duration_ql - MIN_NOTE_DURATION_QL)

                if block_specific_fill_key and is_effectively_last_measure_of_block:
                    fill_def = style_definition.get("fill_ins", {}).get(block_specific_fill_key)
                    if fill_def:
                        pattern_to_apply_this_measure = fill_def
                        applied_fill_this_measure = True
                        logger.info(f"DrumGen: Applying block-specific fill '{block_specific_fill_key}' at offset {measure_start_abs_offset:.2f}")
                    else:
                        logger.warning(f"DrumGen: Block-specific fill key '{block_specific_fill_key}' not found in style '{style_key}'.")
                
                # Check for interval-based fill if no block-specific fill was applied
                # And if this iteration represents a full (or nearly full) bar of the pattern
                if not applied_fill_this_measure and \
                   fill_interval_bars > 0 and \
                   available_fill_keys and \
                   (measures_since_last_fill + 1) % fill_interval_bars == 0 and \
                   (current_measure_iteration_duration_ql >= pattern_bar_duration_ql - MIN_NOTE_DURATION_QL / 2): # Is a full bar
                    
                    chosen_fill_key = random.choice(available_fill_keys)
                    fill_def = style_definition.get("fill_ins", {}).get(chosen_fill_key)
                    if fill_def:
                        pattern_to_apply_this_measure = fill_def
                        applied_fill_this_measure = True
                        logger.info(f"DrumGen: Applying interval fill '{chosen_fill_key}' at offset {measure_start_abs_offset:.2f}")
                    else:
                        logger.warning(f"DrumGen: Interval fill key '{chosen_fill_key}' not found in style '{style_key}'.")
                
                # Apply the chosen pattern (main or fill) to the current measure iteration
                self._apply_drum_pattern_to_measure(
                    drum_part,
                    pattern_to_apply_this_measure,
                    measure_start_abs_offset,
                    current_measure_iteration_duration_ql,
                    base_velocity_for_block,
                    humanize_settings
                )

                if applied_fill_this_measure:
                    measures_since_last_fill = 0
                elif current_measure_iteration_duration_ql >= pattern_bar_duration_ql - MIN_NOTE_DURATION_QL / 2: # Count as a full measure passed
                    measures_since_last_fill += 1
                
                current_block_time_ql += current_measure_iteration_duration_ql
                measure_index_in_block += 1
        
        # Final cleanup (optional, music21 often handles this)
        # drum_part.makeNotation(inPlace=True)
        
        logger.info(f"DrumGen: Finished drum composition. Part contains {len(drum_part.flatten().notesAndRests)} elements.")
        return drum_part

# --- END OF FILE generators/drum_generator.py ---
