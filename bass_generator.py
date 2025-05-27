# --- START OF FILE generator/bass_generator.py (アルゴリズム生成フック統合版) ---
from __future__ import annotations
"""bass_generator.py – streamlined rewrite with vocal context awareness and algorithmic generation
Generates a **bass part** for the modular composer pipeline.
Supports both fixed rhythm patterns applied to generated pitches (via bass_utils)
and fully algorithmic pattern generation.
"""
from typing import Sequence, Dict, Any, Optional, List, Union, cast, Tuple

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
import music21.scale # build_scale_object のために必要
import music21.interval as interval # _generic_bass_note のために必要

# ユーティリティのインポート
try:
    from .bass_utils import generate_bass_measure # 既存のピッチ生成ロジック
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL, build_scale_object
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.error(f"BassGenerator: Failed to import required modules: {e}")
    # Fallback minimal definitions
    MIN_NOTE_DURATION_QL = 0.125
    HUMANIZATION_TEMPLATES = {}
    def generate_bass_measure(*args, **kwargs) -> List[note.Note]: return [] # type: ignore
    def apply_humanization_to_part(part, *args, **kwargs) -> stream.Part: # type: ignore
        if isinstance(part, stream.Part): return part
        return stream.Part()
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: # type: ignore
        return meter.TimeSignature(ts_str or "4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: # type: ignore
        if not label or label.strip().lower() in ["rest", "r", "n.c.", "nc", "none"]: return None
        return label.strip()
    def build_scale_object(mode: str, tonic_name: str) -> Optional[music21.scale.ConcreteScale]: # type: ignore
        try:
            # 簡易的なフォールバック実装
            if mode.lower() == "major":
                return music21.scale.MajorScale(tonic_name)
            elif mode.lower() == "minor": # Natural minor
                return music21.scale.MinorScale(tonic_name)
            # 他のモードも必要に応じて追加
            return music21.scale.DiatonicScale(tonic_name) # Generic fallback
        except Exception:
            return None


logger = logging.getLogger(__name__)

################################################################################
# Algorithmic pattern generation helpers (New)                                 #
################################################################################

def _voice_note_into_register(p: pitch.Pitch, target_octave: int = 2) -> pitch.Pitch:
    """Move *p* into an octave close to *target_octave* (for bass ~E2)."""
    new_p = pitch.Pitch(p.name)
    new_p.octave = target_octave
    # keep transposing by 12 until inside ±6 semitones of target octave root
    # More robust octave adjustment
    target_midi = pitch.Pitch(f"C{target_octave}").ps
    while new_p.ps < target_midi - 6: # Check below the typical bass range start (e.g. E1 is 28, C2 is 36)
        new_p.octave += 1
    while new_p.ps > target_midi + 18: # Check above typical bass range end (e.g. G3 is 55, C4 is 60)
        new_p.octave -= 1
    # Final check to ensure it's not too high or too low for typical bass
    if new_p.octave < 1: new_p.octave = 1
    if new_p.octave > 4: new_p.octave = 4 # Avoid excessively high bass notes
    return new_p


def _generic_bass_note(p_root: pitch.Pitch, quality: str = "root") -> pitch.Pitch:
    """Return a pitch appropriate for the *quality* (root / fifth / octave)."""
    p_root_voiced = _voice_note_into_register(p_root) # Ensure root is in a sensible octave first
    if quality == "root":
        return p_root_voiced
    if quality == "fifth":
        return _voice_note_into_register(p_root_voiced.transpose(interval.PerfectFifth()))
    if quality == "octave":
        return _voice_note_into_register(p_root_voiced.transpose(interval.PerfectOctave()))
    # default
    return p_root_voiced


def generate_algorithmic_bass_line(
    algorithm_type: str,
    chord_symbol: harmony.ChordSymbol,
    block_q_length: float,
    block_offset: float, # Absolute offset for the block
    *,
    base_velocity: int = 70,
    ts_obj: Optional[meter.TimeSignature] = None,
    scale_obj: Optional[music21.scale.ConcreteScale] = None,
    algo_params: Optional[Dict[str, Any]] = None # For future params like density, range
) -> List[note.Note]: # Returns notes with absolute offsets
    """Return list of Notes for *block* following *algorithm_type*.

    Currently supports:
    - ``algorithm_walk``      : straight 8‑note walking within scale
    - ``algorithm_syncopated``: root–fifth syncopated pop pattern
    """
    ts_obj = ts_obj or get_time_signature_object("4/4")
    beat_q = ts_obj.beatDuration.quarterLength
    output_notes: List[note.Note] = []

    if not chord_symbol or not chord_symbol.root():
        logger.warning(f"BassGenAlgo: Invalid chord_symbol '{chord_symbol}' for algorithmic generation. Skipping.")
        return []
        
    p_root_orig = chord_symbol.root()
    p_root_voiced = _voice_note_into_register(p_root_orig, target_octave=algo_params.get("range",[2,4])[0] if algo_params and "range" in algo_params else 2)


    if algorithm_type == "algorithm_walk":
        step_ql = beat_q / 2  # 8th notes (density can be a param later)
        current_rel_offset = 0.0
        
        # Build a list of pitches to walk through
        pitches_to_walk = []
        if scale_obj:
            # Get pitches from the scale around the current root
            scale_pitches_raw = scale_obj.getPitches(p_root_voiced.transpose(-7), p_root_voiced.transpose(7))
            pitches_to_walk = [_voice_note_into_register(p, p_root_voiced.octave) for p in scale_pitches_raw]
            # Ensure root is in the list and sort
            if p_root_voiced not in pitches_to_walk:
                pitches_to_walk.append(p_root_voiced)
            pitches_to_walk.sort(key=lambda p: p.ps)
            # Try to start walk from the root if possible
            try:
                start_idx = pitches_to_walk.index(p_root_voiced)
            except ValueError:
                start_idx = len(pitches_to_walk) // 2 # Fallback to middle
        else: # Fallback if no scale object
            pitches_to_walk = [
                p_root_voiced,
                _generic_bass_note(p_root_orig, "fifth"),
                _generic_bass_note(p_root_orig, "octave")
            ]
            start_idx = 0
        
        if not pitches_to_walk: # Ultimate fallback
             pitches_to_walk = [p_root_voiced]
             start_idx = 0

        current_pitch_idx = start_idx
        direction_up = True # Initial direction

        num_steps = 0
        max_steps = int(block_q_length / step_ql) if step_ql > 0 else 0

        while current_rel_offset < block_q_length - MIN_NOTE_DURATION_QL / 4 and num_steps < max_steps:
            if not pitches_to_walk: break # Safety break
            tgt_pitch = pitches_to_walk[current_pitch_idx % len(pitches_to_walk)]
            
            n = note.Note(tgt_pitch)
            n.duration.quarterLength = step_ql * 0.95 # Slight staccato
            n.volume = m21volume.Volume(velocity=base_velocity)
            n.offset = block_offset + current_rel_offset # Absolute offset
            output_notes.append(n)
            
            current_rel_offset += step_ql
            num_steps += 1

            # Determine next pitch index for walking
            if direction_up:
                current_pitch_idx += 1
                if current_pitch_idx >= len(pitches_to_walk):
                    current_pitch_idx = len(pitches_to_walk) - 2 # Turn around
                    direction_up = False
            else: # Moving down
                current_pitch_idx -= 1
                if current_pitch_idx < 0:
                    current_pitch_idx = 1 # Turn around
                    direction_up = True
            current_pitch_idx = max(0, min(current_pitch_idx, len(pitches_to_walk) -1)) # Ensure in bounds


    elif algorithm_type == "algorithm_syncopated":
        # Example: hits on 1, '&' of 2 (1.5), 3, 'a' of 4 (3.75 relative to beat_q=1)
        # Durations are also exemplary
        pattern_elements = [
            {"rel_offset_beats": 0.0, "duration_beats": 0.9, "pitch_quality": "root"},
            {"rel_offset_beats": 1.5, "duration_beats": 0.4, "pitch_quality": "octave"},
            {"rel_offset_beats": 2.0, "duration_beats": 0.9, "pitch_quality": "fifth"},
            {"rel_offset_beats": 3.75, "duration_beats": 0.2, "pitch_quality": "root"},
        ]
        for item in pattern_elements:
            rel_offset_ql = item["rel_offset_beats"] * beat_q
            if rel_offset_ql >= block_q_length - MIN_NOTE_DURATION_QL / 8:
                continue
            
            pitch_to_play = _generic_bass_note(p_root_orig, item["pitch_quality"])
            n = note.Note(pitch_to_play)
            n.duration.quarterLength = min(item["duration_beats"] * beat_q, block_q_length - rel_offset_ql) * 0.95
            n.volume = m21volume.Volume(velocity=base_velocity)
            n.offset = block_offset + rel_offset_ql # Absolute offset
            output_notes.append(n)

    else:
        logger.warning(f"BassGenAlgo: Unknown algorithm_type '{algorithm_type}'. Falling back to root whole note.")
        n = note.Note(p_root_voiced, quarterLength=block_q_length * 0.95)
        n.volume = m21volume.Volume(velocity=base_velocity)
        n.offset = block_offset # Absolute offset
        output_notes.append(n)

    return output_notes


################################################################################
# Main BassGenerator class                                                    #
################################################################################

class BassGenerator:
    def __init__(
        self,
        rhythm_library: Optional[Dict[str, Dict]] = None,
        default_instrument = m21instrument.AcousticBass(), # Changed to AcousticBass as per original
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        global_key_tonic: str = "C", # Added from original
        global_key_mode: str = "major", # Added from original
        rng: Optional[random.Random] = None, # Added from original
    ) -> None:
        self.rhythm_library = rhythm_library if rhythm_library is not None else {}
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        self.global_key_tonic = global_key_tonic
        self.global_key_mode = global_key_mode
        self.rng = rng or random.Random()

        # Ensure default fallback rhythm pattern exists
        if "bass_quarter_notes" not in self.rhythm_library:
            self.rhythm_library["bass_quarter_notes"] = {
                "description": "Default quarter note roots for bass (fallback).",
                "pattern": [ # Original fallback pattern structure
                    {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"},
                    {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}
                ],
                 "reference_duration_ql": 4.0 # Added for consistency
            }
            logger.info("BassGenerator: Added 'bass_quarter_notes' to rhythm_library as fallback.")


    # _select_style is removed as rhythm_key directly determines the style or algorithm

    def compose(self, processed_blocks: Sequence[Dict[str, Any]]) -> stream.Part:
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        ts_copy_init = meter.TimeSignature(self.global_time_signature_obj.ratioString) # Use ratioString for safety
        bass_part.insert(0, ts_copy_init)

        first_block_tonic = processed_blocks[0].get("tonic_of_section", self.global_key_tonic) if processed_blocks else self.global_key_tonic
        first_block_mode = processed_blocks[0].get("mode", self.global_key_mode) if processed_blocks else self.global_key_mode
        try:
            bass_part.insert(0, key.Key(first_block_tonic, first_block_mode))
        except Exception as e_key:
            logger.warning(f"BassGenerator: Could not set initial key {first_block_tonic} {first_block_mode}: {e_key}. Using C Major.")
            bass_part.insert(0, key.Key("C", "major"))

        current_total_offset = 0.0 # Tracks the start offset of the current block in the entire piece

        for i, blk_data in enumerate(processed_blocks):
            bass_params = blk_data.get("part_params", {}).get("bass", {})
            block_q_length = float(blk_data.get("q_length", self.global_time_signature_obj.barDuration.quarterLength))

            if not bass_params:
                logger.debug(f"BassGenerator: No bass parameters for block {i+1}. Skipping bass for this block.")
                current_total_offset += block_q_length
                continue

            chord_label_str = blk_data.get("chord_label", "C")
            sanitized_label = sanitize_chord_label(chord_label_str)

            if sanitized_label is None: # Rest or N.C.
                logger.info(f"BassGenerator: Block {i+1} ('{chord_label_str}') is a Rest/N.C. Skipping bass notes.")
                current_total_offset += block_q_length
                continue

            cs_now_obj: Optional[harmony.ChordSymbol] = None
            try:
                cs_now_obj = harmony.ChordSymbol(sanitized_label)
                if not cs_now_obj.pitches: cs_now_obj = None
            except Exception as e_parse:
                logger.warning(f"BassGenerator: Error parsing chord '{chord_label_str}' (sanitized: '{sanitized_label}') for block {i+1}: {e_parse}.")
                cs_now_obj = None

            if cs_now_obj is None:
                logger.warning(f"BassGenerator: Could not create valid ChordSymbol for '{chord_label_str}' in block {i+1}. Skipping notes.")
                current_total_offset += block_q_length
                continue
            
            # Determine key and scale for the current block (for algorithmic generation)
            tonic = blk_data.get("tonic_of_section", self.global_key_tonic)
            mode = blk_data.get("mode", self.global_key_mode)
            scale_obj_for_block = build_scale_object(mode, tonic)
            if not scale_obj_for_block:
                logger.debug(f"BassGenerator: Could not build scale for {tonic} {mode} in block {i+1}. Algorithmic patterns might be simpler.")


            rhythm_key = bass_params.get("rhythm_key", "bass_quarter_notes")
            style_def = self.rhythm_library.get(rhythm_key)

            if not style_def:
                logger.warning(f"BassGenerator: Rhythm key '{rhythm_key}' not found. Falling back to 'bass_quarter_notes'.")
                style_def = self.rhythm_library.get("bass_quarter_notes")
                if not style_def: # Should not happen if __init__ ensures fallback
                    logger.error("BassGenerator: Critical! Fallback 'bass_quarter_notes' also missing.")
                    current_total_offset += block_q_length
                    continue
            
            base_velocity = int(bass_params.get("velocity", bass_params.get("bass_velocity", 70)))
            target_octave = int(bass_params.get("octave", bass_params.get("bass_target_octave", 2)))


            # --- Algorithmic or Fixed Pattern Path ---
            if "algorithmic_type" in style_def:
                algo_type = style_def["algorithmic_type"]
                algo_params_from_lib = style_def.get("params", {}) # Get params from rhythm_library
                logger.debug(f"BassGenerator: Block {i+1} using ALGORITHMIC style '{algo_type}' for chord '{sanitized_label}'.")
                
                # Override octave from algo_params if present
                if "range" in algo_params_from_lib and isinstance(algo_params_from_lib["range"], list) and len(algo_params_from_lib["range"]) > 0:
                    target_octave = algo_params_from_lib["range"][0] # Use the lower bound of the range as target

                generated_notes = generate_algorithmic_bass_line(
                    algorithm_type=algo_type,
                    chord_symbol=cs_now_obj,
                    block_q_length=block_q_length,
                    block_offset=current_total_offset, # Pass absolute offset of the block
                    base_velocity=base_velocity,
                    ts_obj=self.global_time_signature_obj,
                    scale_obj=scale_obj_for_block,
                    algo_params=algo_params_from_lib
                )
                for n_algo in generated_notes:
                    # Ensure note's offset is absolute before inserting
                    # generate_algorithmic_bass_line now returns notes with absolute offsets
                    bass_part.insert(n_algo.offset, n_algo)

            else: # Fixed pattern (existing logic path)
                logger.debug(f"BassGenerator: Block {i+1} using FIXED pattern '{rhythm_key}' for chord '{sanitized_label}'.")
                # Get next chord for context (for bass_utils.generate_bass_measure)
                cs_next_obj: Optional[harmony.ChordSymbol] = None
                if i + 1 < len(processed_blocks):
                    next_blk_data = processed_blocks[i+1]
                    next_label_str = next_blk_data.get("chord_label")
                    sanitized_next_label = sanitize_chord_label(next_label_str)
                    if sanitized_next_label:
                        try: cs_next_obj = harmony.ChordSymbol(sanitized_next_label)
                        except: pass
                if cs_next_obj is None: cs_next_obj = cs_now_obj # Fallback to current

                vocal_notes_in_block = blk_data.get("vocal_notes_in_block", [])
                
                measure_pitches_template: List[pitch.Pitch] = []
                try:
                    # The 'style' for generate_bass_measure could be the rhythm_key itself if it matches
                    # what generate_bass_measure expects (e.g., "walking", "root_fifth").
                    # Or, rhythm_library entries for fixed patterns could specify a 'bass_utils_style'.
                    # For now, let's assume rhythm_key might be a valid style for generate_bass_measure.
                    # If not, generate_bass_measure should have a fallback.
                    # A more robust way would be to have a mapping or specific key in rhythm_library.
                    style_for_bass_utils = style_def.get("bass_utils_style", rhythm_key) # Example

                    temp_notes = generate_bass_measure(
                        style=style_for_bass_utils, # Use the rhythm_key or a dedicated mapping
                        cs_now=cs_now_obj,
                        cs_next=cs_next_obj,
                        tonic=tonic,
                        mode=mode,
                        octave=target_octave,
                        vocal_notes_in_block=vocal_notes_in_block
                    )
                    measure_pitches_template = [n.pitch for n in temp_notes if isinstance(n, note.Note) and n.pitch is not None]
                except Exception as e_gbm:
                    logger.error(f"BassGenerator: Error in generate_bass_measure for style '{rhythm_key}', chord '{sanitized_label}': {e_gbm}. Using root note.", exc_info=True)
                
                if not measure_pitches_template: # Fallback if generate_bass_measure fails or returns empty
                    default_root_fallback = _generic_bass_note(cs_now_obj.root(), "root") # Use _generic_bass_note for octave voicing
                    measure_pitches_template = [default_root_fallback] * 4 # Assume 4 beats for fallback

                pattern_events = style_def.get("pattern", [])
                pattern_ref_duration = float(style_def.get("reference_duration_ql", self.global_time_signature_obj.barDuration.quarterLength))

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

                    current_pitch_obj = measure_pitches_template[pitch_idx % len(measure_pitches_template)]
                    pitch_idx += 1
                    
                    # Ensure pitch is voiced correctly for bass using the 'type' from pattern or default to root
                    quality_from_pattern = event_data.get("type", event_data.get("quality", "root")) # 'type' or 'quality'
                    final_pitch = _generic_bass_note(current_pitch_obj, quality_from_pattern)
                    # _generic_bass_note already voices, but ensure target_octave is respected if not root
                    if quality_from_pattern != "root":
                         final_pitch = _voice_note_into_register(final_pitch, target_octave)
                    else: # if root, ensure it's from the original chord's root, voiced
                         final_pitch = _voice_note_into_register(cs_now_obj.root(), target_octave)


                    n_bass = note.Note(final_pitch)
                    n_bass.quarterLength = actual_event_duration * 0.95 # slight staccato
                    vel_factor = float(event_data.get("velocity_factor", 1.0))
                    n_bass.volume = m21volume.Volume(velocity=int(base_velocity * vel_factor))
                    bass_part.insert(current_total_offset + abs_event_offset_in_block, n_bass)

            current_total_offset += block_q_length

        # Apply humanization (existing logic)
        # Humanization settings might be per-block or global. Assuming global for now from first block.
        if processed_blocks:
            global_bass_params_for_humanize = processed_blocks[0].get("part_params", {}).get("bass", {})
            humanize_cfg = global_bass_params_for_humanize.get("humanization_settings", {})
            if isinstance(humanize_cfg, dict) and humanize_cfg.get("humanize_opt", False): # Check type and flag
                h_template = humanize_cfg.get("template_name", "default_subtle")
                h_custom = humanize_cfg.get("custom_params", {})
                logger.info(f"BassGenerator: Applying humanization with template '{h_template}' and params {h_custom}")
                bass_part = apply_humanization_to_part(bass_part, template_name=h_template, custom_params=h_custom)
                bass_part.id = "Bass"
                if not bass_part.getElementsByClass(m21instrument.Instrument): bass_part.insert(0, self.default_instrument)
                if not bass_part.getElementsByClass(tempo.MetronomeMark): bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
                if not bass_part.getElementsByClass(meter.TimeSignature):
                    ts_copy_humanize = meter.TimeSignature(self.global_time_signature_obj.ratioString)
                    bass_part.insert(0, ts_copy_humanize)
                if not bass_part.getElementsByClass(key.Key):
                    try: bass_part.insert(0, key.Key(first_block_tonic, first_block_mode))
                    except: bass_part.insert(0, key.Key("C", "major"))
            elif global_bass_params_for_humanize.get("humanize", False) and not humanize_cfg: # Legacy humanize flag
                 logger.info(f"BassGenerator: Applying humanization with legacy 'humanize=True' flag (default_subtle).")
                 bass_part = apply_humanization_to_part(bass_part, template_name="default_subtle")
                 # ... (re-insert elements as above)


        logger.info(f"BassGenerator: Generated {len(list(bass_part.flatten().notes))} bass notes.")
        return bass_part

# --- END OF FILE generator/bass_generator.py (アルゴリズム生成フック統合版) ---
