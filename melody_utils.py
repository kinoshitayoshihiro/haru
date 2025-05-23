from __future__ import annotations
"""melody_utils.py
Helper functions for **melodic line generation** – designed to be imported by
`generator.melody_generator.MelodyGenerator` (or any future generator) without
pulling in heavy state.

Highlights
----------
*   Uses :pyclass:`generator.utils.scale_registry.ScaleRegistry` for all
    mode/scale queries (zero duplicate instantiation).
*   Simple beat‑strength heuristic so that **strong beats favour chord‑tones**,
    weak beats favour tensions / passing tones.
*   Contour templates and a tiny *first‑order* Markov table to give phrases a
    more natural directional flow.
*   No direct dependency on rhythm – you feed it a list of *beat offsets* and
    it returns a list of :class:`music21.note.Note` objects of the same length.

This module purposely stays stateless; all randomness comes from the caller
passing in a ``random.Random`` instance (default: module‑level RNG).
"""

from typing import List, Sequence, Tuple, Optional
import random as _rand
import logging

from music21 import note, harmony, interval, pitch

from generator.utils.scale_registry import ScaleRegistry as SR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / Config
# ---------------------------------------------------------------------------
BEAT_STRENGTH_4_4 = {0.0: 1.0, 1.0: 0.6, 2.0: 0.9, 3.0: 0.4}  # quarter grid

# simple first‑order Markov (interval in semitones) – tweaks welcome
_MARKOV_TABLE = {
    0:  {0: 0.2, +2: 0.4, -2: 0.4},   # hold or step
    +2: {+2: 0.3, 0: 0.2, -1: 0.3, -2: 0.2},
    -2: {-2: 0.3, 0: 0.2, +1: 0.3, +2: 0.2},
    +1: {+2: 0.4, 0: 0.2, -1: 0.4},
    -1: {-2: 0.4, 0: 0.2, +1: 0.4},
}

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _weighted_choice(items_with_weight):
    total = sum(w for _, w in items_with_weight)
    r = _rand.random() * total
    upto = 0.0
    for item, w in items_with_weight:
        upto += w
        if upto >= r:
            return item
    return items_with_weight[-1][0]


def _next_interval(prev_int: int) -> int:
    """Choose next interval via tiny Markov table."""
    table = _MARKOV_TABLE.get(prev_int, _MARKOV_TABLE[0])
    return _weighted_choice(list(table.items()))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_melodic_pitches(
    chord: harmony.ChordSymbol,
    tonic: str,
    mode: str,
    beat_offsets: Sequence[float],
    octave_range: Tuple[int, int] = (4, 5),
    rnd: Optional[random.Random] = None,
) -> List[note.Note]:
    """Return a list of :class:`music21.note.Note` of equal length to ``beat_offsets``.

    The algorithm ensures:
    * Strong beats (per ``BEAT_STRENGTH_4_4``) prefer **chord‑tones**.
    * Weak beats may choose mode tensions or chromatic approaches.
    * Interval movement follows a coarse Markov chain for contour.
    """
    rnd = rnd or _rand

    scale_obj = SR.get(tonic, mode)
    tensions_deg = SR.mode_tensions(mode)
    avoid_deg = SR.avoid_degrees(mode)

    chord_pcs = {p.pitchClass for p in chord.pitches}
    tension_pcs = {
        scale_obj.pitchFromDegree(d).pitchClass for d in tensions_deg if d not in avoid_deg
    }

    notes: List[note.Note] = []
    prev_pitch: Optional[pitch.Pitch] = None
    prev_int = 0

    for beat in beat_offsets:
        strength = BEAT_STRENGTH_4_4.get(beat % 4, 0.5)
        pool: List[pitch.Pitch] = []

        # build candidate pool ------------------------------------------------
        for p in chord.pitches:
            for octv in range(octave_range[0], octave_range[1] + 1):
                pool.append(p.transpose(12 * (octv - p.octave)))
        for pc in tension_pcs:
            base = pitch.Pitch()
            base.midi = pc
            for octv in range(octave_range[0], octave_range[1] + 1):
                pool.append(pitch.Pitch(pc + octv * 12))

        # weight pool ---------------------------------------------------------
        weighted_pool: List[Tuple[pitch.Pitch, float]] = []
        for p in pool:
            w = 1.0
            if p.pitchClass in chord_pcs:
                w *= 4.0  # strongly prefer chord‑tone
            elif p.pitchClass in tension_pcs:
                w *= 2.0
            # distance penalty (keep within a 6th)
            if prev_pitch is not None:
                ival = abs(p.midi - prev_pitch.midi)
                w *= max(0.1, 1.5 - ival / 8.0)
            # beat strength influence
            w *= strength
            weighted_pool.append((p, w))

        chosen_pitch = _weighted_choice(weighted_pool)
        # apply Markov contour tweak ------------------------------------------
        if prev_pitch is not None:
            desired_int = _next_interval(prev_int)
            candidate = prev_pitch.transpose(desired_int)
            # if candidate within range and pool
            if octave_range[0] <= candidate.octave <= octave_range[1]:
                chosen_pitch = candidate
                prev_int = desired_int
            else:
                prev_int = chosen_pitch.midi - prev_pitch.midi
        else:
            prev_int = 0

        prev_pitch = chosen_pitch
        n = note.Note(chosen_pitch)
        n.quarterLength = MIN_NOTE_DURATION_QL  # caller may override
        notes.append(n)

    return notes
