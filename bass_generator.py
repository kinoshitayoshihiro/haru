# --- START OF FILE generator/bass_generator.py (Algorithm‑Hook + PrettyMIDI Ready v2.0 - Clone Fix) ---
"""bass_generator.py – Phase 2

Highlights
~~~~~~~~~~
* **Algorithmic hooks** – Rhythm‑library entries whose ``pattern_type`` starts with
  ``algorithmic_`` (e.g. ``algorithmic_walking``) are recognised.  The suffix
  (``walking``, ``root_fifth`` …) is mapped to a style handled by
  :pyfunc:`generator.bass_utils.generate_bass_measure`.
* **Static patterns** – Non‑algorithmic library items continue to work (offset &
  duration are copied verbatim).
* **PrettyMIDI bridge (optional)** – If *return_pretty_midi=True* the part is
  converted to a :class:`pretty_midi.PrettyMIDI` object.  Full CC / bend work is
  left for future phases but the scaffold is here.

The class remains a drop‑in replacement for *modular_composer.py* (no changes
required on that side).
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
import music21.key

# ── optional pretty_midi ─────────────────────────────────────────────────────
try:
    import pretty_midi  # type: ignore
    _PRETTY_OK = True
except ImportError:
    pretty_midi = None  # type: ignore
    _PRETTY_OK = False

# ── project utils ────────────────────────────────────────────────────────────
try:
    from .bass_utils import generate_bass_measure
    from utilities.core_music_utils import (
        get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL
    )
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:  # graceful degradation on import failure
    logging.getLogger(__name__+".fallback").error(f"BassGen imports failed: {e}")
    def generate_bass_measure(*_a, **_k) -> List[note.Note]: return []  # type: ignore
    def apply_humanization_to_part(p, *_a, **_k) -> stream.Part: # type: ignore
        if isinstance(p, stream.Part): return p
        return stream.Part()
    def get_time_signature_object(_s: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature("4/4")  # type: ignore
    def sanitize_chord_label(l: Optional[str]) -> Optional[str]: # type: ignore
        if not l or l.strip().lower() in ["rest", "r", "n.c.", "nc", "none"]: return None
        return l.strip()
    MIN_NOTE_DURATION_QL = 0.125
    HUMANIZATION_TEMPLATES: Dict[str, Dict[str, Any]] = {}

logger = logging.getLogger(__name__)

# ── mapping from algorithmic suffix → bass_utils style key ───────────────────
_ALG_TO_STYLE: Dict[str, str] = {
    "root_only":  "root_only",
    "root_fifth": "root_fifth",
    "walking":    "walking",
}

DEFAULT_BASS_VEL = 70
DEFAULT_BASS_OCTAVE = 2

class BassGenerator:
    """Generate *music21* (and optionally PrettyMIDI) bass parts."""

    def __init__(self,
                 rhythm_library: Optional[Dict[str, Any]] = None,
                 default_instrument: m21instrument.Instrument = m21instrument.AcousticBass(),
                 global_tempo: int = 100,
                 global_time_signature: str = "4/4",
                 global_key_tonic: str = "C",
                 global_key_mode: str = "major",
                 rng: Optional[random.Random] = None) -> None:

        self.rhythm_lib = rhythm_library.get("bass_lines", {}) if rhythm_library else {}
        if not self.rhythm_lib:
             logger.warning("BassGen: 'bass_lines' section not found in rhythm_library or library is empty.")

        if "root_only" not in self.rhythm_lib:
            self.rhythm_lib["root_only"] = {
                "description": "Fallback: Whole‑bar root hold (auto-added)",
                "pattern_type": "algorithmic_root_only",
                "pattern": [{"offset": 0.0, "duration": 4.0, "velocity_factor": 0.7, "type": "root"}],
                "reference_duration_ql": 4.0
            }
            logger.warning("BassGen: Inserted fallback 'root_only' pattern into internal rhythm library.")
        elif "pattern" not in self.rhythm_lib["root_only"] and "algorithmic_root_only" == self.rhythm_lib["root_only"].get("pattern_type"):
             self.rhythm_lib["root_only"]["pattern"] = [{"offset": 0.0, "duration": 4.0, "velocity_factor": 0.7, "type": "root"}]
             self.rhythm_lib["root_only"]["reference_duration_ql"] = 4.0
             logger.info("BassGen: Added skeleton 'pattern' to algorithmic 'root_only' for rhythmic mapping.")

        self.inst      = default_instrument
        self.tempo_val = global_tempo
        self.ts_obj    = get_time_signature_object(global_time_signature)
        self.key_tonic = global_key_tonic
        self.key_mode  = global_key_mode
        self.rng       = rng or random.Random()

    def _choose_style_for_bass_utils(self, pattern_definition: Dict[str, Any]) -> str:
        pattern_type_str: Optional[str] = pattern_definition.get("pattern_type")
        
        if pattern_type_str and pattern_type_str.startswith("algorithmic_"):
            algo_key_suffix = pattern_type_str.split("algorithmic_")[-1]
            if algo_key_suffix in _ALG_TO_STYLE:
                return _ALG_TO_STYLE[algo_key_suffix]
            logger.warning(f"BassGen: Algorithmic suffix '{algo_key_suffix}' not found in _ALG_TO_STYLE. Defaulting to 'root_only' for bass_utils.")
            return "root_only"
        return pattern_definition.get("bass_utils_style", "root_only")

    def compose(self, processed_chord_stream: Sequence[Dict[str, Any]],
                return_pretty_midi: bool = False) -> Union[stream.Part, "pretty_midi.PrettyMIDI", None]:
        part = stream.Part(id="Bass")
        part.insert(0, self.inst)
        part.insert(0, tempo.MetronomeMark(number=self.tempo_val))
        
        ts_to_clone = self.ts_obj if self.ts_obj else get_time_signature_object("4/4")
        part.insert(0, meter.TimeSignature(ts_to_clone.ratioString)) # Corrected

        try:
            initial_key = key.Key(self.key_tonic, self.key_mode)
            part.insert(0, initial_key)
        except Exception as e_key_init:
            logger.warning(f"BassGen: Could not set initial part key to {self.key_tonic} {self.key_mode}: {e_key_init}. Using C major.")
            part.insert(0, key.Key("C", "major"))

        current_block_abs_offset = 0.0

        for blk_idx, blk in enumerate(processed_chord_stream):
            current_block_abs_offset = float(blk.get("offset", current_block_abs_offset))
            block_q_length = float(blk.get("q_length", self.ts_obj.barDuration.quarterLength if self.ts_obj else 4.0))
            cs_label_raw = blk.get("chord_label", "C")
            bass_params = blk.get("part_params", {}).get("bass", {})
            pattern_key = bass_params.get("bass_rhythm_key", "root_only")
            pattern_def = self.rhythm_lib.get(pattern_key)

            if not pattern_def:
                logger.warning(f"BassGen: Pattern key '{pattern_key}' not found. Using 'root_only' fallback definition.")
                pattern_def = self.rhythm_lib.get("root_only")
                if not pattern_def:
                    logger.error("BassGen: Critical! Fallback 'root_only' definition is missing. Skipping block.")
                    current_block_abs_offset += block_q_length
                    continue

            cs_obj: Optional[harmony.ChordSymbol] = None
            sanitized_cs_label = sanitize_chord_label(cs_label_raw)

            if sanitized_cs_label is None:
                cs_obj = None
                logger.info(f"BassGen Blk {blk_idx+1}: Rest or N.C. ('{cs_label_raw}').")
            else:
                try:
                    cs_obj = harmony.ChordSymbol(sanitized_cs_label)
                    if not cs_obj.pitches:
                        cs_obj = None
                        logger.info(f"BassGen Blk {blk_idx+1}: Chord '{sanitized_cs_label}' has no pitches. Treating as rest.")
                except Exception as e_cs_parse:
                    logger.error(f"BassGen Blk {blk_idx+1}: Failed to parse chord '{sanitized_cs_label}': {e_cs_parse}. Treating as rest.")
                    cs_obj = None
            
            block_octave = int(bass_params.get("bass_octave", pattern_def.get("options",{}).get("target_octave",DEFAULT_BASS_OCTAVE)))
            block_base_velocity = int(bass_params.get("bass_velocity", pattern_def.get("velocity_base", DEFAULT_BASS_VEL)))

            is_algorithmic = pattern_def.get("pattern_type", "").startswith("algorithmic_")

            if is_algorithmic:
                if cs_obj is None:
                    logger.info(f"BassGen Blk {blk_idx+1}: Algorithmic pattern '{pattern_key}' specified, but current chord is Rest/N.C. Skipping notes for this block.")
                    current_block_abs_offset += block_q_length
                    continue

                bass_utils_style = self._choose_style_for_bass_utils(pattern_def)
                logger.debug(f"BassGen Blk {blk_idx+1}: Algorithmic type '{pattern_def['pattern_type']}' -> bass_utils style '{bass_utils_style}' for chord '{sanitized_cs_label}'.")

                next_cs_obj: Optional[harmony.ChordSymbol] = cs_obj
                if blk_idx + 1 < len(processed_chord_stream):
                    next_blk_data = processed_chord_stream[blk_idx+1]
                    next_cs_label_raw = next_blk_data.get("chord_label")
                    sanitized_next_cs_label = sanitize_chord_label(next_cs_label_raw)
                    if sanitized_next_cs_label:
                        try:
                            parsed_next_cs = harmony.ChordSymbol(sanitized_next_cs_label)
                            if parsed_next_cs.pitches: next_cs_obj = parsed_next_cs
                        except Exception:
                            pass

                vocal_notes_in_block = blk.get("vocal_notes_in_block", [])
                generated_pitch_material: List[note.Note] = generate_bass_measure(
                    style=bass_utils_style,
                    cs_now=cs_obj,
                    cs_next=next_cs_obj,
                    tonic=blk.get("tonic_of_section", self.key_tonic),
                    mode=blk.get("mode", self.key_mode),
                    octave=block_octave,
                    vocal_notes_in_block=vocal_notes_in_block
                )

                if not generated_pitch_material:
                    logger.warning(f"BassGen Blk {blk_idx+1}: bass_utils.generate_bass_measure returned no material for style '{bass_utils_style}'. Using simple root.")
                    n_root_fallback = note.Note(cs_obj.root(), quarterLength=block_q_length)
                    n_root_fallback.octave = block_octave
                    generated_pitch_material = [n_root_fallback]

                rhythmic_skeleton = pattern_def.get("pattern")
                if not rhythmic_skeleton:
                    logger.error(f"BassGen Blk {blk_idx+1}: Algorithmic pattern '{pattern_key}' is missing its 'pattern' (rhythmic skeleton). Skipping.")
                    current_block_abs_offset += block_q_length
                    continue
                
                pattern_ref_duration = float(pattern_def.get("reference_duration_ql", self.ts_obj.barDuration.quarterLength if self.ts_obj else 4.0))

                for skeleton_idx, skeleton_event_data in enumerate(rhythmic_skeleton):
                    if not generated_pitch_material: break
                    pitch_to_use = generated_pitch_material[skeleton_idx % len(generated_pitch_material)].pitch
                    event_offset_in_pattern = float(skeleton_event_data.get("offset", 0.0))
                    event_duration_from_pattern = float(skeleton_event_data.get("duration", 1.0))
                    scale_factor = block_q_length / pattern_ref_duration if pattern_ref_duration > 0 else 1.0
                    abs_event_offset_in_block = event_offset_in_pattern # Assuming direct mapping for now
                    actual_event_duration = event_duration_from_pattern # Assuming direct mapping

                    if abs_event_offset_in_block >= block_q_length - MIN_NOTE_DURATION_QL / 8:
                        continue
                    actual_event_duration = min(actual_event_duration, block_q_length - abs_event_offset_in_block)
                    if actual_event_duration < MIN_NOTE_DURATION_QL / 2:
                        continue

                    n = note.Note(pitch_to_use)
                    n.quarterLength = actual_event_duration
                    vel_factor = float(skeleton_event_data.get("velocity_factor", 1.0))
                    n.volume = m21volume.Volume(velocity=max(1, min(127, int(block_base_velocity * vel_factor))))
                    part.insert(current_block_abs_offset + abs_event_offset_in_block, n)
            else: # Static pattern
                logger.debug(f"BassGen Blk {blk_idx+1}: Static pattern '{pattern_key}' for chord '{sanitized_cs_label}'.")
                static_pattern_events = pattern_def.get("pattern")
                if not static_pattern_events:
                    logger.error(f"BassGen Blk {blk_idx+1}: Static pattern '{pattern_key}' is missing 'pattern' events. Skipping.")
                    current_block_abs_offset += block_q_length
                    continue

                pattern_ref_duration_static = float(pattern_def.get("reference_duration_ql", self.ts_obj.barDuration.quarterLength if self.ts_obj else 4.0))

                for event_data in static_pattern_events:
                    event_offset_in_pattern = float(event_data.get("offset", 0.0))
                    event_duration_from_pattern = float(event_data.get("duration", 1.0))
                    scale_factor_static = block_q_length / pattern_ref_duration_static if pattern_ref_duration_static > 0 else 1.0
                    abs_event_offset_in_block = event_offset_in_pattern * scale_factor_static
                    actual_event_duration = event_duration_from_pattern * scale_factor_static

                    if abs_event_offset_in_block >= block_q_length - MIN_NOTE_DURATION_QL / 8:
                        continue
                    actual_event_duration = min(actual_event_duration, block_q_length - abs_event_offset_in_block)
                    if actual_event_duration < MIN_NOTE_DURATION_QL / 2:
                        continue
                    
                    if cs_obj is None:
                        r = note.Rest(quarterLength=actual_event_duration)
                        part.insert(current_block_abs_offset + abs_event_offset_in_block, r)
                    else:
                        note_type = event_data.get("type", "root")
                        p = cs_obj.root()
                        if note_type == "fifth":
                            p_fifth = cs_obj.fifth
                            if p_fifth: p = p_fifth
                        elif note_type == "third":
                            p_third = cs_obj.third
                            if p_third: p = p_third
                        
                        n_static = note.Note(p)
                        n_static.octave = block_octave
                        n_static.quarterLength = actual_event_duration
                        vel_factor = float(event_data.get("velocity_factor", 1.0))
                        n_static.volume = m21volume.Volume(velocity=max(1, min(127, int(block_base_velocity * vel_factor))))
                        part.insert(current_block_abs_offset + abs_event_offset_in_block, n_static)
            
            current_block_abs_offset = current_block_abs_offset + block_q_length

        humanize_params_source = processed_chord_stream[0].get("part_params", {}).get("bass", {}) if processed_chord_stream else {}
        
        if humanize_params_source.get("bass_humanize", True):
            template_name = humanize_params_source.get("bass_humanize_template", "default_subtle")
            if template_name not in HUMANIZATION_TEMPLATES and template_name != "default_subtle":
                 logger.warning(f"BassGen: Humanization template '{template_name}' not found in HUMANIZATION_TEMPLATES. Humanizer will use its own default.")

            logger.info(f"BassGen: Applying humanization with template '{template_name}'.")
            part = apply_humanization_to_part(part, template_name=template_name)
            part.id = "Bass"
            if not part.getElementsByClass(m21instrument.Instrument): part.insert(0, self.inst)
            if not part.getElementsByClass(tempo.MetronomeMark): part.insert(0, tempo.MetronomeMark(number=self.tempo_val))
            if not part.getElementsByClass(meter.TimeSignature):
                ts_reinsert = self.ts_obj if self.ts_obj else get_time_signature_object("4/4")
                part.insert(0, meter.TimeSignature(ts_reinsert.ratioString)) # Corrected
            if not part.getElementsByClass(key.Key):
                try: part.insert(0, key.Key(self.key_tonic, self.key_mode))
                except: part.insert(0, key.Key("C", "major"))

        if return_pretty_midi:
            if not _PRETTY_OK:
                logger.warning("BassGen: PrettyMIDI requested but library not found. Returning music21 Part.")
                return part
            
            logger.info("BassGen: Converting to PrettyMIDI object.")
            try:
                pm = pretty_midi.PrettyMIDI(initial_tempo=float(self.tempo_val))
                pm_instrument_program = self.inst.midiProgram if hasattr(self.inst, 'midiProgram') and self.inst.midiProgram is not None else 33
                bass_instrument_pm = pretty_midi.Instrument(program=int(pm_instrument_program), is_drum=False, name=self.inst.instrumentName or "Bass")

                part_tempo = self.tempo_val
                mm_marks = part.getElementsByClass(tempo.MetronomeMark)
                if mm_marks:
                    part_tempo = mm_marks[0].number

                for n_or_r in part.recurse().notesAndRests:
                    if isinstance(n_or_r, note.Note):
                        start_time_sec = n_or_r.getOffsetInHierarchy(part) * (60.0 / part_tempo)
                        duration_sec = n_or_r.duration.quarterLength * (60.0 / part_tempo)
                        end_time_sec = start_time_sec + duration_sec
                        note_velocity = n_or_r.volume.velocity if n_or_r.volume and n_or_r.volume.velocity is not None else DEFAULT_BASS_VEL
                        note_pitch_midi = n_or_r.pitch.midi
                        
                        pm_note = pretty_midi.Note(
                            velocity=int(note_velocity),
                            pitch=int(note_pitch_midi),
                            start=start_time_sec,
                            end=end_time_sec
                        )
                        bass_instrument_pm.notes.append(pm_note)
                pm.instruments.append(bass_instrument_pm)
                return pm
            except Exception as e_pm:
                logger.error(f"BassGen: Error during PrettyMIDI conversion: {e_pm}", exc_info=True)
                return part # Fallback to returning music21 part
        
        return part

# --- END OF FILE generator/bass_generator.py ---
