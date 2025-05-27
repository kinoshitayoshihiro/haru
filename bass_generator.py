# --- START OF FILE generator/bass_generator.py (Integrated Algorithm-Hook + Vocal-Aware + PrettyMIDI v2.1) ---
"""bass_generator.py – Phase 2.1 (Integrated)

Highlights
~~~~~~~~~~
* **Algorithmic hooks & Static patterns** – Supports both algorithmic pitch generation
  with skeleton rhythms, and static patterns with pitch generation via bass_utils.
* **Vocal Context Awareness** – Passes vocal notes to bass_utils for consideration.
* **PrettyMIDI bridge (optional)** – Can return PrettyMIDI objects.
* **Humanization** – Applies humanization templates.
"""
from __future__ import annotations

from typing import Dict, Any, Optional, List, Sequence, Union, cast
import random
import logging

# ── music21 imports ──────────────────────────────────────────────────────────
import music21.stream   as stream
import music21.harmony  as harmony
import music21.note     as note
import music21.tempo    as tempo
import music21.meter    as meter
import music21.instrument as m21instrument
import music21.pitch    as pitch
import music21.volume   as m21volume
import music21.key      as m21key # Explicit import for key.Key
import music21.scale    # For build_scale_object
import music21.interval # For _generic_bass_note (if used more broadly)


# ── optional pretty_midi ─────────────────────────────────────────────────────
try:
    import pretty_midi
    _PRETTY_OK = True
except ImportError:
    pretty_midi = None # type: ignore
    _PRETTY_OK = False

# ── project utils ────────────────────────────────────────────────────────────
try:
    from .bass_utils import generate_bass_measure
    from utilities.core_music_utils import (
        get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL, build_scale_object
    )
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:  # graceful degradation on import failure
    logger_fallback = logging.getLogger(__name__+".fallback_bass")
    logger_fallback.error(f"BassGenerator: Critical imports failed: {e}. Using fallbacks.")
    def generate_bass_measure(*_a, **_k) -> List[note.Note]: return []
    def apply_humanization_to_part(p, *_a, **_k) -> stream.Part: return cast(stream.Part, p)
    def get_time_signature_object(_s: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature(_s or "4/4")
    def sanitize_chord_label(l: Optional[str]) -> Optional[str]: return None if not l or l.strip().lower() in ["rest", "r", "n.c.", "nc", "none"] else l.strip()
    def build_scale_object(mode: str, tonic_name: str) -> Optional[music21.scale.ConcreteScale]: # type: ignore
        try:
            if mode.lower() == "major": return music21.scale.MajorScale(tonic_name)
            elif mode.lower() == "minor": return music21.scale.MinorScale(tonic_name)
            return music21.scale.DiatonicScale(tonic_name) # Generic fallback
        except Exception: return None
    MIN_NOTE_DURATION_QL = 0.125
    HUMANIZATION_TEMPLATES: Dict[str, Dict[str, Any]] = {}

logger = logging.getLogger(__name__)

# ── mapping from algorithmic suffix → bass_utils style key ───────────────────
# These are styles that bass_utils.generate_bass_measure is expected to understand
_ALG_TO_STYLE = {
    "root_only":  "root_only",    # Simple root notes
    "root_fifth": "root_fifth",  # Root and fifth alternation
    "walking":    "walking",     # Walking bass lines
    # Add more mappings here as new algorithmic styles are implemented in bass_utils
    # e.g., "chromatic_walk": "chromatic_walk", "reggae": "reggae_style"
}

DEFAULT_BASS_VEL = 70
DEFAULT_BASS_OCTAVE = 2 # Consistent with original vocal-aware version

class BassGenerator:
    """Generate *music21* (and optionally PrettyMIDI) bass parts."""

    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None, # Entire rhythm library
                 default_instrument: m21instrument.Instrument = m21instrument.AcousticBass(),
                 global_tempo: int = 100,
                 global_time_signature: str = "4/4",
                 global_key_tonic: str = "C",
                 global_key_mode: str = "major",
                 rng: Optional[random.Random] = None) -> None:

        # Expects rhythm_library to contain a "bass_lines" key as per user's JSON structure
        self.rhythm_lib = rhythm_library.get("bass_lines", {}) if rhythm_library else {}
        
        # Ensure a minimal fallback pattern exists if "root_only" or a default is missing
        # The new script used "algorithmic_root_only" as a fallback type.
        # Let's use a simple fixed pattern as a robust fallback.
        if "bass_quarter_notes" not in self.rhythm_lib:
            self.rhythm_lib["bass_quarter_notes"] = {
                "description": "Default quarter note roots (auto-added fallback).",
                "pattern": [
                    {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"},
                    {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}
                ],
                "reference_duration_ql": 4.0
            }
            logger.warning("BassGenerator: Added 'bass_quarter_notes' to internal rhythm_lib as fallback.")
        # Fallback for "root_only" if specifically requested and missing
        if "root_only" not in self.rhythm_lib:
             self.rhythm_lib["root_only"] = self.rhythm_lib["bass_quarter_notes"] # Alias to quarter notes
             logger.warning("BassGenerator: Aliased missing 'root_only' to 'bass_quarter_notes'.")


        self.inst      = default_instrument
        self.tempo_val = global_tempo
        self.ts_obj    = get_time_signature_object(global_time_signature)
        self.key_tonic = global_key_tonic # Retained from vocal-aware
        self.key_mode  = global_key_mode  # Retained from vocal-aware
        self.rng       = rng or random.Random() # Retained from vocal-aware

    def _get_bass_utils_style_for_algo(self, pattern_def: Dict[str, Any]) -> str:
        """Maps algorithmic_type suffix to a style for bass_utils.generate_bass_measure."""
        ptype: str = pattern_def.get("pattern_type", "")
        if ptype.startswith("algorithmic_"):
            algo_key_suffix = ptype.split("algorithmic_", 1)[-1] # Get "walking", "root_fifth" etc.
            return _ALG_TO_STYLE.get(algo_key_suffix, "root_only") # Default to "root_only" if suffix not in map
        return "root_only" # Should not be called if not algorithmic, but a safe default

    def _voice_pitch_to_octave(self, pitch_obj: pitch.Pitch, target_octave: int) -> pitch.Pitch:
        """Helper to voice a given pitch into the target octave."""
        new_pitch = pitch_obj.clone()
        new_pitch.octave = target_octave
        # Adjust if still too far, common for bass
        while new_pitch.ps < pitch.Pitch(f"C{target_octave-1}").ps : new_pitch.octave +=1
        while new_pitch.ps > pitch.Pitch(f"B{target_octave+1}").ps : new_pitch.octave -=1
        return new_pitch

    def compose(self, processed_chord_stream: Sequence[Dict[str, Any]],
                return_pretty_midi: bool = False) -> Union[stream.Part, "pretty_midi.PrettyMIDI", None]:
        
        if not processed_chord_stream:
            logger.warning("BassGenerator: processed_chord_stream is empty. Returning None.")
            return None

        part = stream.Part(id="Bass")
        part.insert(0, self.inst)
        part.insert(0, tempo.MetronomeMark(number=self.tempo_val))
        if self.ts_obj: # Ensure ts_obj is not None
            part.insert(0, self.ts_obj.clone())
        else: # Fallback if ts_obj is somehow None
            logger.error("BassGenerator: self.ts_obj is None. Defaulting to 4/4 for Part.")
            part.insert(0, meter.TimeSignature("4/4"))

        # Set initial key for the part
        first_block_tonic = processed_chord_stream[0].get("tonic_of_section", self.key_tonic)
        first_block_mode = processed_chord_stream[0].get("mode", self.key_mode)
        try:
            part.insert(0, m21key.Key(first_block_tonic, first_block_mode))
        except Exception as e_key_init:
            logger.warning(f"BassGenerator: Could not set initial key {first_block_tonic} {first_block_mode}: {e_key_init}. Using C Major.")
            part.insert(0, m21key.Key("C", "major"))


        # current_total_offset is managed by blk.get("offset")
        # prev_cs: Optional[harmony.ChordSymbol] = None # For context if needed beyond next_cs

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_abs_offset = float(blk_data.get("offset", 0.0))
            block_q_length = float(blk_data.get("q_length", self.ts_obj.barDuration.quarterLength if self.ts_obj else 4.0))
            
            bass_params = blk_data.get("part_params", {}).get("bass", {})
            if not bass_params:
                logger.debug(f"BassGenerator: No bass_params for block {blk_idx+1}. Skipping.")
                continue

            chord_label_raw = blk_data.get("chord_label", "C") # Default to C if missing
            sanitized_label = sanitize_chord_label(chord_label_raw)

            if sanitized_label is None: # Is a Rest or N.C.
                # If pattern definition expects rests, it might have specific rest events.
                # For simplicity here, if chord is None, we skip adding notes for this block from bass gen,
                # relying on chordmap to have defined rests if silence is intended for the whole block.
                # Or, a pattern could explicitly define rests.
                logger.info(f"BassGenerator: Block {blk_idx+1} ('{chord_label_raw}') is Rest/N.C. No bass notes generated by default.")
                continue

            cs_now_obj: Optional[harmony.ChordSymbol] = None
            try:
                cs_now_obj = harmony.ChordSymbol(sanitized_label)
                if not cs_now_obj.pitches: cs_now_obj = None # Treat N.C. effectively as None here
            except Exception as e_parse_cs:
                logger.error(f"BassGenerator: Failed to parse chord '{sanitized_label}' for block {blk_idx+1}: {e_parse_cs}. Skipping block.")
                cs_now_obj = None
            
            if cs_now_obj is None:
                continue # Skip if chord is unparsable or N.C.

            # --- Get contextual info for bass_utils ---
            tonic_for_block = blk_data.get("tonic_of_section", self.key_tonic)
            mode_for_block = blk_data.get("mode", self.key_mode)
            target_octave_for_block = int(bass_params.get("bass_octave", bass_params.get("octave", DEFAULT_BASS_OCTAVE)))
            base_vel_for_block = int(bass_params.get("bass_velocity", bass_params.get("velocity", DEFAULT_BASS_VEL)))
            vocal_notes_in_block = blk_data.get("vocal_notes_in_block", [])


            # --- Determine Next Chord for bass_utils context ---
            cs_next_obj: Optional[harmony.ChordSymbol] = cs_now_obj # Default next to current
            if blk_idx + 1 < len(processed_chord_stream):
                next_blk = processed_chord_stream[blk_idx+1]
                next_label_raw = next_blk.get("chord_label")
                sanitized_next_label = sanitize_chord_label(next_label_raw)
                if sanitized_next_label:
                    try: 
                        cs_next_obj_temp = harmony.ChordSymbol(sanitized_next_label)
                        if cs_next_obj_temp.pitches: cs_next_obj = cs_next_obj_temp
                    except Exception: pass # cs_next_obj remains cs_now_obj

            # --- Get Rhythm Pattern Definition ---
            rhythm_key = bass_params.get("bass_rhythm_key", bass_params.get("rhythm_key", "bass_quarter_notes"))
            pattern_def = self.rhythm_lib.get(rhythm_key)
            if not pattern_def:
                logger.warning(f"BassGenerator: Rhythm key '{rhythm_key}' not found. Using 'bass_quarter_notes'.")
                pattern_def = self.rhythm_lib.get("bass_quarter_notes") # Should exist due to __init__
                if not pattern_def: # Should be extremely rare
                     logger.error("BassGenerator: CRITICAL - Default 'bass_quarter_notes' also missing. Skipping block.")
                     continue


            # --- Decide Path: Algorithmic (Pitches from bass_utils, Rhythm from skeleton) or Static (Pitches from bass_utils, Rhythm from pattern) ---
            is_algorithmic = pattern_def.get("pattern_type", "").startswith("algorithmic_")
            
            generated_pitches_from_bass_utils: List[pitch.Pitch] = []

            if is_algorithmic:
                style_for_bass_utils = self._get_bass_utils_style_for_algo(pattern_def)
                logger.debug(f"BassGenerator: Block {blk_idx+1} (Algo): style '{style_for_bass_utils}', chord '{sanitized_label}'.")
            else: # Static pattern, but still use bass_utils for potentially richer pitches
                style_for_bass_utils = pattern_def.get("bass_utils_style", rhythm_key) # Use specific key or rhythm_key itself
                logger.debug(f"BassGenerator: Block {blk_idx+1} (Static): style '{style_for_bass_utils}', chord '{sanitized_label}'.")

            try:
                temp_notes_from_utils = generate_bass_measure(
                    style=style_for_bass_utils,
                    cs_now=cs_now_obj,
                    cs_next=cs_next_obj, # type: ignore # cs_next_obj is harmonoy.ChordSymbol here
                    tonic=tonic_for_block,
                    mode=mode_for_block,
                    octave=target_octave_for_block,
                    vocal_notes_in_block=vocal_notes_in_block
                )
                generated_pitches_from_bass_utils = [n.pitch for n in temp_notes_from_utils if isinstance(n, note.Note) and n.pitch is not None]
            except Exception as e_gbm_call:
                logger.error(f"BassGenerator: Error calling generate_bass_measure for style '{style_for_bass_utils}', chord '{sanitized_label}': {e_gbm_call}", exc_info=True)

            if not generated_pitches_from_bass_utils: # Fallback if bass_utils fails or returns empty
                logger.warning(f"BassGenerator: No pitches from bass_utils for '{sanitized_label}'. Using voiced root.")
                if cs_now_obj.root():
                    generated_pitches_from_bass_utils = [self._voice_pitch_to_octave(cs_now_obj.root(), target_octave_for_block)]
                else: # Should not happen if cs_now_obj is valid
                    logger.error(f"BassGenerator: cs_now_obj.root() is None for '{sanitized_label}'. Skipping notes for this event.")
                    continue


            # --- Apply Rhythm from Pattern Definition ---
            pattern_events = pattern_def.get("pattern", [])
            if not pattern_events:
                logger.warning(f"BassGenerator: No 'pattern' events in rhythm_key '{rhythm_key}' for chord '{sanitized_label}'. Using single whole note root.")
                # Create a single note for the block duration if no pattern events
                if generated_pitches_from_bass_utils:
                    n_fallback = note.Note(generated_pitches_from_bass_utils[0])
                    n_fallback.quarterLength = block_q_length
                    n_fallback.volume = m21volume.Volume(velocity=base_vel_for_block)
                    part.insert(block_abs_offset, n_fallback)
                continue # Move to next block

            pattern_ref_duration = float(pattern_def.get("reference_duration_ql", self.ts_obj.barDuration.quarterLength if self.ts_obj else 4.0))
            
            pitch_idx = 0
            for event_data in pattern_events:
                event_offset_in_pattern = float(event_data.get("offset", 0.0))
                event_duration_from_pattern = float(event_data.get("duration", 1.0))

                scale_factor = block_q_length / pattern_ref_duration if pattern_ref_duration > 0 else 1.0
                abs_event_offset_in_block = event_offset_in_pattern * scale_factor
                actual_event_duration = event_duration_from_pattern * scale_factor

                if abs_event_offset_in_block >= block_q_length - MIN_NOTE_DURATION_QL / 8: continue
                actual_event_duration = min(actual_event_duration, block_q_length - abs_event_offset_in_block)
                if actual_event_duration < MIN_NOTE_DURATION_QL / 2: continue

                # Select pitch
                current_pitch_base: pitch.Pitch
                if generated_pitches_from_bass_utils:
                    current_pitch_base = generated_pitches_from_bass_utils[pitch_idx % len(generated_pitches_from_bass_utils)]
                else: # Should have been caught earlier, but as a safeguard
                    if cs_now_obj.root(): current_pitch_base = cs_now_obj.root()
                    else: continue 
                pitch_idx += 1
                
                # For fixed patterns, "type" can modify the pitch (e.g. "root", "fifth" of current chord)
                # For algorithmic, the pitch from bass_utils is usually what we want.
                final_pitch_obj = current_pitch_base # Default to the pitch from bass_utils
                
                if not is_algorithmic: # Only apply "type" modification for non-algorithmic (static) patterns
                    quality_from_pattern = event_data.get("type", event_data.get("quality", "auto")).lower()
                    if quality_from_pattern == "root":
                        if cs_now_obj.root(): final_pitch_obj = cs_now_obj.root()
                    elif quality_from_pattern == "fifth":
                        if cs_now_obj.fifth: final_pitch_obj = cs_now_obj.fifth
                        elif cs_now_obj.root(): final_pitch_obj = cs_now_obj.root().transpose(7)
                    elif quality_from_pattern in ["octave_root", "octave"]:
                        if cs_now_obj.root(): final_pitch_obj = cs_now_obj.root().transpose(12)
                    # "auto" or other types will use current_pitch_base from bass_utils

                # Ensure final pitch is in the target octave
                final_pitch_obj_voiced = self._voice_pitch_to_octave(final_pitch_obj, target_octave_for_block)

                n_bass = note.Note(final_pitch_obj_voiced)
                n_bass.quarterLength = actual_event_duration * 0.95 # Slight staccato
                vel_factor = float(event_data.get("velocity_factor", 1.0))
                current_vel = int(base_vel_for_block * vel_factor)
                n_bass.volume = m21volume.Volume(velocity=max(1, min(127, current_vel)))
                
                part.insert(block_abs_offset + abs_event_offset_in_block, n_bass)

        # --- Humanization (applied to the whole part) ---
        # Use bass_params from the first block for global humanization settings, or make it configurable
        final_bass_params = processed_chord_stream[0].get("part_params", {}).get("bass", {}) if processed_chord_stream else {}
        
        # New humanization keys from "v2.0" proposal
        apply_h = final_bass_params.get("bass_humanize", final_bass_params.get("humanize", True)) # Check both new and old key
        if apply_h:
            h_template_name = final_bass_params.get("bass_humanize_template", 
                                                final_bass_params.get("template_name", "default_subtle"))
            # Allow custom params from chordmap if specified under humanization_settings
            h_custom_params = final_bass_params.get("humanization_settings", {}).get("custom_params", {})

            logger.info(f"BassGenerator: Applying humanization template '{h_template_name}' with custom: {h_custom_params if h_custom_params else 'None'}")
            part = apply_humanization_to_part(part, template_name=h_template_name, custom_params=h_custom_params)
            
            # Ensure essential elements are re-inserted if apply_humanization_to_part recreates the Part object
            part.id = "Bass" # Reset ID
            if not part.getElementsByClass(m21instrument.Instrument): part.insert(0, self.inst)
            if not part.getElementsByClass(tempo.MetronomeMark): part.insert(0, tempo.MetronomeMark(number=self.tempo_val))
            if not part.getElementsByClass(meter.TimeSignature) and self.ts_obj: part.insert(0, self.ts_obj.clone())
            if not part.getElementsByClass(m21key.Key):
                try: part.insert(0, m21key.Key(first_block_tonic, first_block_mode))
                except: part.insert(0, m21key.Key("C", "major"))


        # --- PrettyMIDI Conversion (Optional) ---
        if return_pretty_midi:
            if not _PRETTY_OK:
                logger.warning("BassGenerator: PrettyMIDI output requested but library not found. Returning music21 Part.")
                return part
            
            pm = pretty_midi.PrettyMIDI(initial_tempo=self.tempo_val) # Set initial tempo
            # Add time signature changes (if any, though typically one global for now)
            # For simplicity, assuming one global time signature for the PrettyMIDI object
            if self.ts_obj:
                 pm.time_signature_changes.append(
                     pretty_midi.TimeSignature(self.ts_obj.numerator, self.ts_obj.denominator, 0)
                 )
            else: # Fallback if self.ts_obj is None
                 pm.time_signature_changes.append(pretty_midi.TimeSignature(4,4,0))


            # Instrument mapping (Acoustic Bass = 32, Electric Bass (finger) = 33)
            # self.inst.midiProgram seems to be the most reliable way if set.
            program_num = 33 # Default to Electric Bass (finger)
            if hasattr(self.inst, 'midiProgram') and self.inst.midiProgram is not None:
                program_num = self.inst.midiProgram
            elif isinstance(self.inst, m21instrument.AcousticBass):
                program_num = 32
            elif isinstance(self.inst, m21instrument.ElectricBass): # General Electric Bass
                program_num = 33 
            
            inst_pm = pretty_midi.Instrument(program=program_num, is_drum=False, name=part.id or "Bass")

            # Get tempo changes from the music21 part to inform note timings if dynamic
            # For now, assuming global_tempo is constant for PrettyMIDI conversion simplicity
            # More complex: iterate through tempo.MetronomeMark objects in part.
            tempo_for_conversion = self.tempo_val 
            # If there are tempo changes in the part, this needs to be handled more dynamically.
            # For now, use the initial global tempo.
            # seconds_per_ql = 60.0 / tempo_for_conversion

            for n in part.recurse().notes:
                if isinstance(n, note.Note) and n.pitch is not None and n.duration is not None:
                    # music21 offset is in quarter lengths from the start of its container.
                    # We need absolute offset in the part.
                    abs_offset_ql = n.getOffsetInHierarchy(part)
                    start_time_sec = (abs_offset_ql * 60.0) / tempo_for_conversion # Convert QL offset to seconds
                    duration_sec = (n.duration.quarterLength * 60.0) / tempo_for_conversion # Convert QL duration to seconds
                    end_time_sec = start_time_sec + duration_sec
                    
                    note_velocity = n.volume.velocity if n.volume and n.volume.velocity is not None else DEFAULT_BASS_VEL
                    
                    pm_note = pretty_midi.Note(
                        velocity=max(1, min(127, note_velocity)),
                        pitch=n.pitch.midi,
                        start=start_time_sec,
                        end=end_time_sec
                    )
                    inst_pm.notes.append(pm_note)
            
            pm.instruments.append(inst_pm)
            return pm
            
        return part

# --- END OF FILE generator/bass_generator.py (Integrated Algorithm-Hook + Vocal-Aware + PrettyMIDI v2.1) ---
