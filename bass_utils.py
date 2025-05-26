# --- START OF FILE generator/bass_utils.py (ボーカル協調フェーズ1対応) ---
from __future__ import annotations
"""bass_utils.py
Low-level helpers for *bass line generation*, now with vocal context awareness (Phase 1).
Generates pitch templates for bass lines, considering current and next chords,
section tonality, and vocal notes within the current block for basic collision avoidance.
"""

from typing import List, Sequence, Optional, Any, Dict
import random as _rand
import logging

from music21 import note, pitch, harmony, interval, scale as m21_scale # Explicitly import m21_scale

try:
    from utilities.scale_registry import ScaleRegistry as SR
except ImportError:
    logger_fallback_sr_bass = logging.getLogger(__name__ + ".fallback_sr_bass")
    logger_fallback_sr_bass.error("BassUtils: Could not import ScaleRegistry from utilities. Scale-aware functions might fail.")
    class SR: # Dummy ScaleRegistry
        @staticmethod
        def get(tonic_str: Optional[str], mode_str: Optional[str]) -> m21_scale.ConcreteScale:
            logger_fallback_sr_bass.warning("BassUtils: Using dummy ScaleRegistry.get(). This may not produce correct scales.")
            # Ensure tonic_str is not None before passing to Pitch
            effective_tonic = tonic_str if tonic_str else "C"
            try:
                return m21_scale.MajorScale(pitch.Pitch(effective_tonic))
            except Exception as e_pitch:
                logger_fallback_sr_bass.error(f"Error creating pitch for dummy SR: {e_pitch}. Defaulting to C Major.")
                return m21_scale.MajorScale(pitch.Pitch("C"))


logger = logging.getLogger(__name__)

def approach_note(cur_note_pitch: pitch.Pitch, next_target_pitch: pitch.Pitch, direction: Optional[int] = None) -> pitch.Pitch:
    """
    Generates a pitch that approaches next_target_pitch from cur_note_pitch.
    Simple chromatic or diatonic step.
    """
    if direction is None:
        direction = 1 if next_target_pitch.midi > cur_note_pitch.midi else -1
    # Simple chromatic step for now
    return cur_note_pitch.transpose(direction)


def walking_quarters(
    cs_now: harmony.ChordSymbol,
    cs_next: harmony.ChordSymbol,
    tonic: str,
    mode: str,
    octave: int = 3,
    vocal_notes_in_block: Optional[List[Dict]] = None # Added for consistency, not used in this specific style's logic yet
) -> List[pitch.Pitch]:
    """
    Generates four pitches for a walking bass line over one measure (4 beats).
    Args are passed from generate_bass_measure.
    """
    if vocal_notes_in_block:
        logger.debug(f"walking_quarters for {cs_now.figure if cs_now else 'N/A'}: Received {len(vocal_notes_in_block)} vocal notes (content logged in generate_bass_measure).")

    scl = SR.get(tonic, mode)
    
    if not cs_now or not cs_now.root():
        logger.warning(f"walking_quarters: cs_now or its root is None. Defaulting to C{octave}.")
        return [pitch.Pitch(f"C{octave}")] * 4
        
    root_now_init = cs_now.root()
    root_now = root_now_init.transpose((octave - root_now_init.octave) * 12)

    effective_cs_next_root = cs_next.root() if cs_next and cs_next.root() else root_now_init
    root_next = effective_cs_next_root.transpose((octave - effective_cs_next_root.octave) * 12)

    beat1 = root_now
    
    # Beat 2: Chord tone (3rd or 5th preferably)
    options_b2_pitches = []
    if cs_now.third: options_b2_pitches.append(cs_now.third)
    if cs_now.fifth: options_b2_pitches.append(cs_now.fifth)
    if not options_b2_pitches: options_b2_pitches.append(root_now_init) # Fallback to root

    beat2_candidate_pitch = _rand.choice(options_b2_pitches)
    beat2 = beat2_candidate_pitch.transpose((octave - beat2_candidate_pitch.octave) * 12)

    # Beat 3: Approaching beat 4 (which approaches next chord's root)
    # For simplicity, step towards beat 2, or use a scale tone
    beat3_candidate_pitch = beat2.transpose(_rand.choice([-2, -1, 1, 2])) # Small interval from beat2
    if not scl.contains(beat3_candidate_pitch): # If not in scale, try another chord tone or beat2 itself
        beat3_candidate_pitch = _rand.choice(options_b2_pitches).transpose((octave - _rand.choice(options_b2_pitches).octave) * 12)
        if beat3_candidate_pitch == beat2: # Avoid same note if possible
             beat3_candidate_pitch = root_now
    beat3 = beat3_candidate_pitch


    # Beat 4: Approach note to the root of the *next* chord (root_next)
    beat4 = approach_note(beat3, root_next)
    if not scl.contains(beat4): # If approach is out of scale, try to land on root_next directly or a closer scale tone
        beat4_alt1 = root_next
        beat4_alt2 = scl.nextρή(beat3, direction=pitch.Direction.ASCENDING if root_next.ps > beat3.ps else pitch.Direction.DESCENDING)
        if isinstance(beat4_alt2, pitch.Pitch) and scl.contains(beat4_alt2):
            beat4 = beat4_alt2
        else:
            beat4 = beat4_alt1


    return [beat1, beat2, beat3, beat4]


def root_fifth_half(
    cs_now: harmony.ChordSymbol,
    cs_next: harmony.ChordSymbol, # Added for signature consistency
    tonic: str,                   # Added for signature consistency
    mode: str,                    # Added for signature consistency
    octave: int = 3,
    vocal_notes_in_block: Optional[List[Dict]] = None # Added for consistency
) -> List[pitch.Pitch]:
    """
    Generates four pitches, alternating root and fifth, for a measure.
    Args are passed from generate_bass_measure.
    """
    if vocal_notes_in_block:
        logger.debug(f"root_fifth_half for {cs_now.figure if cs_now else 'N/A'}: Received {len(vocal_notes_in_block)} vocal notes.")

    if not cs_now or not cs_now.root():
        logger.warning(f"root_fifth_half: cs_now or its root is None. Defaulting to C{octave}.")
        return [pitch.Pitch(f"C{octave}")] * 4

    root_init = cs_now.root()
    root = root_init.transpose((octave - root_init.octave) * 12)
    
    fifth_init = cs_now.fifth
    if fifth_init is None:
        logger.warning(f"root_fifth_half: Chord {cs_now.figure} has no fifth. Using octave root as substitute.")
        fifth_init = root_init.transpose(12) # Octave above root
    
    fifth = fifth_init.transpose((octave - fifth_init.octave) * 12)
    
    return [root, fifth, root, fifth]

STYLE_DISPATCH: Dict[str, Any] = {
    "root_only": lambda cs_now, cs_next, tonic, mode, octave, vocal_notes_in_block, **k: (
        (logger.debug(f"root_only for {cs_now.figure if cs_now else 'N/A'}: Vocals: {len(vocal_notes_in_block) if vocal_notes_in_block else 0}") if vocal_notes_in_block else None) or \
        ([cs_now.root().transpose((octave - cs_now.root().octave) * 12)] * 4 if cs_now and cs_now.root() else [pitch.Pitch(f"C{octave}")]*4)
    ),
    "root_fifth": root_fifth_half,
    "walking": walking_quarters,
}

def generate_bass_measure(
    style: str,
    cs_now: harmony.ChordSymbol,
    cs_next: harmony.ChordSymbol,
    tonic: str,
    mode: str,
    octave: int = 3,
    vocal_notes_in_block: Optional[List[Dict]] = None
) -> List[note.Note]:
    """
    Generates a list of bass Note objects for a measure, considering style, chords, and vocal context.
    Vocal context is used for basic collision avoidance. Output notes are 1 beat each by default.

    Args:
        style (str): The bass style (e.g., "walking", "root_only").
        cs_now (harmony.ChordSymbol): The current chord symbol.
        cs_next (harmony.ChordSymbol): The next chord symbol for context.
        tonic (str): The tonic of the current section/scale.
        mode (str): The mode of the current section/scale.
        octave (int): The target octave for the bass notes.
        vocal_notes_in_block (Optional[List[Dict]]): List of vocal notes in the current block.
            Each dict should have 'pitch_str', 'block_relative_offset'.

    Returns:
        List[music21.note.Note]: A list of four bass notes for the measure.
    """
    func = STYLE_DISPATCH.get(style)
    if not func:
        logger.warning(f"BassUtils: Unknown style '{style}'. Defaulting to 'root_only'.")
        func = STYLE_DISPATCH["root_only"]

    # Ensure cs_now is valid, provide a default if not.
    if cs_now is None or not cs_now.root():
        logger.warning(f"BassUtils (generate_bass_measure): cs_now is None or has no root for style '{style}'. Using default C chord.")
        cs_now = harmony.ChordSymbol("C") # Default to C major if problematic
        # If cs_now was None, cs_next might also need defaulting if it relied on cs_now
        if cs_next is None or (cs_next.figure == cs_now.figure and not cs_next.root()): # Check if cs_next was also problematic or same as a bad cs_now
            cs_next = cs_now


    initial_pitches: List[pitch.Pitch]
    try:
        initial_pitches = func(
            cs_now=cs_now, cs_next=cs_next, tonic=tonic, mode=mode, octave=octave, vocal_notes_in_block=vocal_notes_in_block
        )
    except Exception as e_dispatch:
        logger.error(f"BassUtils (generate_bass_measure): Error in dispatched style function '{style}' for chord '{cs_now.figure}': {e_dispatch}. Using root notes.", exc_info=True)
        root_p_obj = cs_now.root() # cs_now is guaranteed to be valid here
        initial_pitches = [root_p_obj.transpose((octave - root_p_obj.octave) * 12)] * 4
            
    # Ensure initial_pitches has 4 elements
    if not initial_pitches or len(initial_pitches) != 4:
        logger.warning(f"Style function '{style}' for chord '{cs_now.figure}' did not return 4 pitches (returned {len(initial_pitches)}). Using root notes as fallback template.")
        root_p_obj = cs_now.root()
        fill_pitch = root_p_obj.transpose((octave - root_p_obj.octave) * 12) if root_p_obj else pitch.Pitch(f"C{octave}")
        
        if not initial_pitches: # Completely empty
            initial_pitches = [fill_pitch] * 4
        elif len(initial_pitches) < 4: # Pad if too short
            initial_pitches.extend([fill_pitch] * (4 - len(initial_pitches)))
        else: # Truncate if too long
            initial_pitches = initial_pitches[:4]

    # --- Vocal Collision Avoidance (Phase 1) ---
    final_adjusted_pitches: List[pitch.Pitch] = []
    scl_obj = SR.get(tonic, mode)

    for beat_idx, p_bass_initial in enumerate(initial_pitches):
        adjusted_pitch_current_beat = p_bass_initial
        
        vocal_notes_on_this_beat = [
            vn for vn in (vocal_notes_in_block or [])
            # Check if vocal note's relative offset falls within the current beat
            # e.g., for beat_idx 0, offset is [0.0, 1.0)
            if beat_idx <= vn.get("block_relative_offset", -999.0) < (beat_idx + 1.0)
        ]

        if vocal_notes_on_this_beat and cs_now.root(): # cs_now.root() check for safety
            log_msg_vocals = [f"{vn.get('pitch_str')}@~{vn.get('block_relative_offset', 0.0):.2f}" for vn in vocal_notes_on_this_beat]
            logger.info(
                f"BassUtils: Chord {cs_now.figure}, Beat {beat_idx}, Initial Bass: {p_bass_initial.nameWithOctave}, Vocals on this beat: {log_msg_vocals}"
            )
            
            root_pc = cs_now.root().pitchClass
            fifth_pc = cs_now.fifth.pitchClass if cs_now.fifth else (root_pc + 7) % 12
            # Consider third_pc if more complex rules are needed later
            # third_pc = cs_now.third.pitchClass if cs_now.third else (root_pc + (3 if cs_now.quality == 'minor' else 4)) % 12


            collided_with_vocal_on_beat = False
            for vn_data in vocal_notes_on_this_beat:
                try:
                    vocal_pitch_obj = pitch.Pitch(vn_data["pitch_str"])
                    if vocal_pitch_obj.pitchClass == adjusted_pitch_current_beat.pitchClass:
                        collided_with_vocal_on_beat = True
                        logger.info(f"  -> Collision: Bass PC {adjusted_pitch_current_beat.pitchClass} & Vocal PC {vocal_pitch_obj.pitchClass} (Vocal note: {vocal_pitch_obj.nameWithOctave}). Attempting adjustment.")
                        
                        current_bass_is_root = (adjusted_pitch_current_beat.pitchClass == root_pc)
                        current_bass_is_fifth = (adjusted_pitch_current_beat.pitchClass == fifth_pc)

                        candidate_pitch: Optional[pitch.Pitch] = None

                        if current_bass_is_root and cs_now.fifth: # Bass is Root, try 5th
                            candidate_pitch = cs_now.fifth.transpose((octave - cs_now.fifth.octave) * 12)
                            if scl_obj.contains(candidate_pitch):
                                adjusted_pitch_current_beat = candidate_pitch
                                logger.info(f"  Adjusted bass to 5th: {adjusted_pitch_current_beat.nameWithOctave}")
                            else: # 5th out of scale, try 3rd
                                if cs_now.third:
                                    candidate_pitch = cs_now.third.transpose((octave - cs_now.third.octave) * 12)
                                    if scl_obj.contains(candidate_pitch):
                                        adjusted_pitch_current_beat = candidate_pitch
                                        logger.info(f"  5th out of scale. Adjusted bass to 3rd: {adjusted_pitch_current_beat.nameWithOctave}")
                                    else:
                                        logger.info(f"  5th & 3rd for {cs_now.figure} out of scale {tonic} {mode}. Bass remains {p_bass_initial.nameWithOctave}.")
                                else:
                                     logger.info(f"  5th for {cs_now.figure} out of scale and no 3rd. Bass remains {p_bass_initial.nameWithOctave}.")
                        elif current_bass_is_fifth: # Bass is 5th, try Root
                            candidate_pitch = cs_now.root().transpose((octave - cs_now.root().octave) * 12)
                            # Root is generally assumed to be in scale, but good practice to check if scl_obj is strict
                            adjusted_pitch_current_beat = candidate_pitch
                            logger.info(f"  Adjusted bass to Root: {adjusted_pitch_current_beat.nameWithOctave}")
                        else: # Collision on another tone (e.g., 3rd) or no simple alternative
                            logger.info(f"  Collision on non-Root/Fifth, or no simple alternative available. Bass for beat {beat_idx} remains {adjusted_pitch_current_beat.nameWithOctave}.")
                        break # Processed first collision for this beat
                except Exception as e_vp_parse:
                    logger.warning(f"Could not parse vocal pitch '{vn_data.get('pitch_str')}' for collision check: {e_vp_parse}")
            
            if not collided_with_vocal_on_beat and vocal_notes_on_this_beat: # Log if vocals were present but no collision
                 logger.debug(f"  No direct pitch class collision with vocals on beat {beat_idx} for bass {p_bass_initial.nameWithOctave}.")

        final_adjusted_pitches.append(adjusted_pitch_current_beat)

    notes_out: List[note.Note] = []
    for p_obj_final in final_adjusted_pitches:
        n = note.Note(p_obj_final)
        n.quarterLength = 1.0 # Default duration for the template; actual duration set by BassGenerator
        notes_out.append(n)
        
    return notes_out
# --- END OF FILE generator/bass_utils.py (ボーカル協調フェーズ1対応) ---
