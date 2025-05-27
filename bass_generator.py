# --- START OF FILE generator/bass_generator.py (Integrated v2.1 - Algorithmic, Vocal-Aware, PrettyMIDI) ---
from __future__ import annotations
"""bass_generator.py – Integrated version
Combines algorithmic hooks, vocal context awareness, static pattern support,
and optional PrettyMIDI output.
"""
from typing import Sequence, Dict, Any, Optional, List, Union, cast
import random
import logging

# music21 のサブモジュールを正しい形式でインポート
import music21.stream as stream
import music21.harmony as harmony
import music21.note as note
import music21.tempo as tempo
import music21.meter as meter
import music21.instrument as m21instrument
import music21.key as key
import music21.pitch as pitch
import music21.volume as m21volume

# ── optional pretty_midi ─────────────────────────────────────────────────────
try:
    import pretty_midi
    _PRETTY_OK = True
except ImportError:
    pretty_midi = None # type: ignore
    _PRETTY_OK = False

# ユーティリティのインポート
try:
    from .bass_utils import generate_bass_measure
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.error(f"BassGenerator: Failed to import required modules: {e}")
    # Define fallback functions to allow the class to be instantiated
    def generate_bass_measure(*args, **kwargs) -> List[note.Note]: return [] # type: ignore
    def apply_humanization_to_part(part, *args, **kwargs) -> stream.Part: # type: ignore
        if isinstance(part, stream.Part): return part
        return stream.Part()
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature("4/4") # type: ignore
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: # type: ignore
        if not label or label.strip().lower() in ["rest", "r", "n.c.", "nc", "none"]: return None
        return label.strip()
    MIN_NOTE_DURATION_QL = 0.125
    HUMANIZATION_TEMPLATES = {}

logger = logging.getLogger(__name__)

# ── mapping from algorithmic suffix → bass_utils style key ───────────────────
_ALG_TO_STYLE = {
    "root_only": "root_only",
    "root_fifth": "root_fifth",
    "walking": "walking",
    # Add more mappings as new algorithms are implemented in bass_utils
}

DEFAULT_BASS_VELOCITY = 70
DEFAULT_BASS_OCTAVE = 2 # music21 octave (C3 is middle C's octave for bass usually)
DEFAULT_RHYTHM_KEY = "bass_quarter_notes" # More descriptive than "root_only" as a general default

class BassGenerator:
    def __init__(
        self,
        rhythm_library: Optional[Dict[str, Dict]] = None, # Expects a dict like {"bass_patterns": {...}, "drum_patterns": ...}
        default_instrument = m21instrument.AcousticBass(),
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        global_key_tonic: str = "C",
        global_key_mode: str = "major",
        rng: Optional[random.Random] = None,
    ) -> None:
        # rhythm_library is expected to have a *bass_patterns* section
        self.rhythm_lib = rhythm_library.get("bass_patterns", {}) if rhythm_library else {}

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        self.global_key_tonic = global_key_tonic
        self.global_key_mode = global_key_mode
        self.rng = rng or random.Random()

        # Ensure a very basic fallback rhythm is present if nothing else
        if DEFAULT_RHYTHM_KEY not in self.rhythm_lib:
            self.rhythm_lib[DEFAULT_RHYTHM_KEY] = {
                "description": "Default quarter note roots for bass.",
                "pattern_type": "algorithmic_root_only", # Can be algorithmic
                "pattern": [ # This pattern is used if algorithmic fails or for static interpretation
                    {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75},
                    {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7},
                    {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75},
                    {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7}
                ],
                "reference_duration_ql": 4.0
            }
            logger.info(f"BassGenerator: Added '{DEFAULT_RHYTHM_KEY}' to bass_patterns as fallback.")

    def _get_rhythm_definition(self, rhythm_key_param: Optional[str]) -> Dict[str, Any]:
        """Safely retrieves a rhythm definition, falling back to default if needed."""
        if rhythm_key_param and rhythm_key_param in self.rhythm_lib:
            return self.rhythm_lib[rhythm_key_param]
        
        logger.warning(
            f"BassGenerator: Rhythm key '{rhythm_key_param}' not found. "
            f"Falling back to '{DEFAULT_RHYTHM_KEY}'."
        )
        return self.rhythm_lib.get(DEFAULT_RHYTHM_KEY, {}) # Final fallback to empty if default is somehow missing

    def _get_bass_utils_style(self, pattern_definition: Dict[str, Any], musical_intent: Dict[str, Any]) -> str:
        """Determines the style key for bass_utils based on algorithmic_type or musical_intent."""
        pattern_type: str = pattern_definition.get("pattern_type", "static")
        if pattern_type.startswith("algorithmic_"):
            algo_suffix = pattern_type.split("algorithmic_")[-1]
            if algo_suffix in _ALG_TO_STYLE:
                return _ALG_TO_STYLE[algo_suffix]
            else:
                logger.warning(f"BassGenerator: Unknown algorithmic suffix '{algo_suffix}'. Defaulting to 'root_only'.")
                return "root_only"
        
        # Fallback to v1-style musical_intent based selection if not algorithmic
        # This part can be expanded or made more sophisticated
        intensity = musical_intent.get("intensity", "medium").lower()
        if intensity in {"low", "medium_low"}: return "root_only"
        if intensity in {"medium"}: return "root_fifth"
        return "walking" # Default for higher intensities or static patterns needing a style

    def compose(self, processed_blocks: Sequence[Dict[str, Any]], return_pretty_midi: bool = False) -> Union[stream.Part, "pretty_midi.PrettyMIDI"]:
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        ts_init_clone = self.global_time_signature_obj.clone()
        bass_part.insert(0, ts_init_clone)

        # Set initial key signature
        first_block_tonic = processed_blocks[0].get("tonic_of_section", self.global_key_tonic) if processed_blocks else self.global_key_tonic
        first_block_mode = processed_blocks[0].get("mode", self.global_key_mode) if processed_blocks else self.global_key_mode
        try:
            initial_key = key.Key(first_block_tonic, first_block_mode)
            bass_part.insert(0, initial_key)
        except Exception as e_key:
            logger.warning(f"BassGenerator: Could not set initial key {first_block_tonic} {first_block_mode}: {e_key}. Using C Major.")
            bass_part.insert(0, key.Key("C", "major"))

        current_total_offset = 0.0

        for i, blk_data in enumerate(processed_blocks):
            bass_params = blk_data.get("part_params", {}).get("bass", {})
            block_q_length = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))
            chord_label_raw = blk_data.get("chord_label", "C") # Default to C if no chord label
            musical_intent = blk_data.get("musical_intent", {})
            vocal_notes_in_block = blk_data.get("vocal_notes_in_block", [])

            rhythm_key_from_params = bass_params.get("rhythm_key", bass_params.get("bass_rhythm_key")) # Accept both old and new param names
            rhythm_def = self._get_rhythm_definition(rhythm_key_from_params)
            
            if not rhythm_def: # Should not happen if default is always present
                logger.error(f"BassGenerator: CRITICAL - No rhythm definition found for block {i+1}. Skipping bass for this block.")
                current_total_offset += block_q_length
                continue

            # --- 1. Chord Symbol Processing ---
            cs_now_obj: Optional[harmony.ChordSymbol] = None
            sanitized_label = sanitize_chord_label(chord_label_raw)
            is_rest_block = (sanitized_label is None) # True if "rest", "N.C.", etc.

            if not is_rest_block:
                try:
                    cs_now_obj = harmony.ChordSymbol(sanitized_label)
                    if not cs_now_obj.pitches: cs_now_obj = None # Treat unpitched ChordSymbols (like N.C. after sanitization) as problematic
                except Exception as e_parse:
                    logger.warning(f"BassGenerator: Error parsing chord '{chord_label_raw}' (sanitized: '{sanitized_label}') for block {i+1}: {e_parse}. Treating as problematic.")
                    cs_now_obj = None
            
            if is_rest_block:
                 logger.info(f"BassGenerator: Block {i+1} ('{chord_label_raw}') is a Rest. Applying rest pattern or skipping notes.")
                 # For rests, we might still want rhythmic silence or a very sparse pattern from rhythm_def
                 # For now, if algorithmic, it might generate nothing. If static, it might insert rests.

            # --- 2. Determine Next Chord for Context ---
            cs_next_obj: Optional[harmony.ChordSymbol] = None
            if i + 1 < len(processed_blocks):
                next_blk_data = processed_blocks[i+1]
                next_label_str = next_blk_data.get("chord_label")
                sanitized_next_label = sanitize_chord_label(next_label_str)
                if sanitized_next_label:
                    try:
                        cs_next_obj = harmony.ChordSymbol(sanitized_next_label)
                        if not cs_next_obj.pitches: cs_next_obj = None
                    except Exception: cs_next_obj = None
            
            if cs_next_obj is None and cs_now_obj: # If no valid next, use current for stability
                cs_next_obj = cs_now_obj
            elif cs_now_obj is None and cs_next_obj is None and not is_rest_block: # Both current and next are problematic, but not a rest block
                logger.warning(f"BassGenerator: Both current and next chords unparsable for block {i+1} (current: '{chord_label_raw}'). Using default C for bass_utils.")
                cs_now_obj = harmony.ChordSymbol("C") # Provide a default for generation
                cs_next_obj = cs_now_obj


            # --- 3. Note Generation (Algorithmic or Static) ---
            target_octave = bass_params.get("octave", bass_params.get("bass_target_octave", DEFAULT_BASS_OCTAVE))
            base_velocity = bass_params.get("velocity", bass_params.get("bass_velocity", DEFAULT_BASS_VELOCITY))
            
            pattern_events = rhythm_def.get("pattern", [])
            pattern_ref_duration = float(rhythm_def.get("reference_duration_ql", self.global_time_signature_obj.barDuration.quarterLength))
            pattern_type = rhythm_def.get("pattern_type", "static")

            generated_notes_for_block: List[note.Note | note.Rest] = []

            if pattern_type.startswith("algorithmic_") and cs_now_obj and cs_next_obj and not is_rest_block:
                # Algorithmic generation
                bass_utils_style = self._get_bass_utils_style(rhythm_def, musical_intent)
                logger.debug(f"BassGenerator: Block {i+1}, Chord '{sanitized_label}', Algorithmic style: '{bass_utils_style}', Vocal notes: {len(vocal_notes_in_block)}")
                try:
                    algo_notes_template = generate_bass_measure(
                        style=bass_utils_style,
                        cs_now=cs_now_obj,
                        cs_next=cs_next_obj, # cs_next_obj is now guaranteed to be a ChordSymbol if cs_now_obj is
                        tonic=blk_data.get("tonic_of_section", self.global_key_tonic),
                        mode=blk_data.get("mode", self.global_key_mode),
                        octave=target_octave,
                        vocal_notes_in_block=vocal_notes_in_block
                    )
                    
                    # Map algorithmic notes onto the skeleton pattern (offsets, durations, velocities from rhythm_def.pattern)
                    pitch_template_idx = 0
                    for event_data in pattern_events:
                        if pitch_template_idx >= len(algo_notes_template):
                            logger.debug(f"BassGenerator: Ran out of algo_notes_template for pattern event in block {i+1}. Using last pitch or rest.")
                            if not algo_notes_template: break # No pitches generated at all
                            # Potentially use last generated pitch or insert a rest
                            # For now, we'll break, meaning fewer notes than pattern events if algo generates less
                            break 
                        
                        n_proto = algo_notes_template[pitch_template_idx].clone() # Clone the note (pitch and potentially other props)
                        pitch_template_idx += 1
                        
                        # Apply rhythm from pattern_events
                        event_offset_in_pattern = float(event_data.get("offset", 0.0))
                        event_duration_from_pattern = float(event_data.get("duration", 1.0))
                        scale_factor = block_q_length / pattern_ref_duration if pattern_ref_duration > 0 else 1.0
                        
                        abs_event_offset_in_block = event_offset_in_pattern * scale_factor
                        actual_event_duration = event_duration_from_pattern * scale_factor

                        if abs_event_offset_in_block >= block_q_length: continue
                        actual_event_duration = min(actual_event_duration, block_q_length - abs_event_offset_in_block)
                        if actual_event_duration < MIN_NOTE_DURATION_QL / 2: continue

                        n_proto.offset = 0 # Offset will be handled by bass_part.insert
                        n_proto.quarterLength = actual_event_duration
                        vel_factor = float(event_data.get("velocity_factor", 1.0))
                        n_proto.volume = m21volume.Volume(velocity=max(1, min(127, int(base_velocity * vel_factor))))
                        
                        generated_notes_for_block.append({
                            "element": n_proto,
                            "offset_in_block": abs_event_offset_in_block
                        })

                except Exception as e_gbm:
                    logger.error(f"BassGenerator: Error in generate_bass_measure for block {i+1}, style '{bass_utils_style}', chord '{sanitized_label}': {e_gbm}. Falling back to static root.", exc_info=True)
                    # Fallback to static root for this block if algorithmic generation fails
                    pattern_type = "static_error_fallback" # Force static handling below

            if pattern_type.startswith("static") or is_rest_block: # Handles static, rest, or algorithmic fallback
                # Static pattern application (or rest block)
                for event_data in pattern_events:
                    event_offset_in_pattern = float(event_data.get("offset", 0.0))
                    event_duration_from_pattern = float(event_data.get("duration", 1.0))
                    scale_factor = block_q_length / pattern_ref_duration if pattern_ref_duration > 0 else 1.0
                    
                    abs_event_offset_in_block = event_offset_in_pattern * scale_factor
                    actual_event_duration = event_duration_from_pattern * scale_factor

                    if abs_event_offset_in_block >= block_q_length: continue
                    actual_event_duration = min(actual_event_duration, block_q_length - abs_event_offset_in_block)
                    if actual_event_duration < MIN_NOTE_DURATION_QL / 2: continue

                    element_to_add: Union[note.Note, note.Rest]
                    if is_rest_block or cs_now_obj is None: # If it's a rest block or chord is unparsable
                        element_to_add = note.Rest(quarterLength=actual_event_duration)
                    else: # It's a valid chord, apply root note
                        n_root = note.Note(cs_now_obj.root())
                        n_root.octave = target_octave
                        n_root.quarterLength = actual_event_duration
                        vel_factor = float(event_data.get("velocity_factor", 1.0))
                        n_root.volume = m21volume.Volume(velocity=max(1, min(127, int(base_velocity * vel_factor))))
                        element_to_add = n_root
                    
                    generated_notes_for_block.append({
                        "element": element_to_add,
                        "offset_in_block": abs_event_offset_in_block
                    })
            
            # Insert all generated notes/rests for this block into the main part
            for item in generated_notes_for_block:
                bass_part.insert(current_total_offset + item["offset_in_block"], item["element"])

            current_total_offset += block_q_length

        # --- 4. Humanization (applied once to the whole part) ---
        # Try to get humanization settings from the first block's bass params as a global setting for the part
        global_bass_params = processed_blocks[0].get("part_params", {}).get("bass", {}) if processed_blocks else {}
        humanize_settings = global_bass_params.get("humanization_settings", {})
        
        # Allow simpler top-level flags from v2.0 as well
        should_humanize = humanize_settings.get("humanize_opt", global_bass_params.get("bass_humanize", False))

        if should_humanize:
            template_name = humanize_settings.get("template_name", global_bass_params.get("bass_humanize_template", "default_subtle"))
            custom_params = humanize_settings.get("custom_params", {})
            logger.info(f"BassGenerator: Applying humanization with template '{template_name}' and params {custom_params}")
            try:
                original_id = bass_part.id
                bass_part = apply_humanization_to_part(bass_part, template_name=template_name, custom_params=custom_params, rng=self.rng)
                bass_part.id = original_id # Restore ID

                # Ensure essential elements are present after humanization (as in v1)
                if not bass_part.getElementsByClass(m21instrument.Instrument): bass_part.insert(0, self.default_instrument.clone())
                if not bass_part.getElementsByClass(tempo.MetronomeMark): bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
                if not bass_part.getElementsByClass(meter.TimeSignature): bass_part.insert(0, self.global_time_signature_obj.clone())
                if not bass_part.getElementsByClass(key.Key):
                    try:
                        bass_part.insert(0, key.Key(first_block_tonic, first_block_mode)) # Use the determined initial key
                    except Exception as e_key_re:
                        logger.warning(f"BassGenerator: Could not re-insert key after humanization: {e_key_re}. Using C Major.")
                        bass_part.insert(0, key.Key("C", "major"))
            except Exception as e_hum:
                logger.error(f"BassGenerator: Error during humanization: {e_hum}", exc_info=True)


        # --- 5. Optional PrettyMIDI Conversion ---
        if return_pretty_midi:
            if not _PRETTY_OK:
                logger.warning("BassGenerator: PrettyMIDI library not found. Returning music21 part instead.")
                return bass_part
            
            pm = pretty_midi.PrettyMIDI(initial_tempo=self.global_tempo)
            # Add time signature changes from the music21 part
            for ts_event in bass_part.getTimeSignatures():
                pm_ts = pretty_midi.TimeSignature(ts_event.numerator, ts_event.denominator, ts_event.offset)
                pm.time_signature_changes.append(pm_ts)
            
            # Add key signature changes (more complex, PrettyMIDI handles this less directly)
            # For now, we'll assume a single key or handle it via MIDI meta messages if needed later.

            bass_instrument_pm = pretty_midi.Instrument(
                program=self.default_instrument.midiProgram if self.default_instrument.midiProgram is not None else 32, # 32 = Acoustic Bass
                is_drum=False,
                name=bass_part.id or "Bass"
            )

            for n in bass_part.recurse().notesAndRests: # Include rests for correct timing if needed by downstream
                if isinstance(n, note.Note):
                    # music21 offset is in quarter notes. Convert to seconds.
                    # Tempo might change, so get the tempo at the note's offset.
                    current_qpm_at_offset = self.global_tempo # Simplified: assumes constant tempo for now
                    # More robust: iterate through tempo.MetronomeMark objects in bass_part
                    tempo_marks = bass_part.getElementsByClass(tempo.MetronomeMark)
                    for tm_offset, tm_obj in tempo_marks.offsetMap().items():
                        if tm_offset <= n.getOffsetInHierarchy(bass_part):
                            current_qpm_at_offset = tm_obj.number
                        else:
                            break
                    
                    seconds_per_quarter = 60.0 / current_qpm_at_offset
                    
                    start_time_sec = n.getOffsetInHierarchy(bass_part) * seconds_per_quarter
                    duration_sec = n.quarterLength * seconds_per_quarter
                    
                    pm_note = pretty_midi.Note(
                        velocity=n.volume.velocity if n.volume and n.volume.velocity is not None else DEFAULT_BASS_VELOCITY,
                        pitch=n.pitch.midi,
                        start=start_time_sec,
                        end=start_time_sec + duration_sec
                    )
                    bass_instrument_pm.notes.append(pm_note)
                # Optionally handle rests if your PrettyMIDI consumer needs them explicitly
                # else: # It's a Rest
                #    pass # PrettyMIDI implicitly handles rests by gaps between notes

            pm.instruments.append(bass_instrument_pm)
            return pm

        return bass_part

# --- END OF FILE generator/bass_generator.py (Integrated v2.1) ---
