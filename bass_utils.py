from __future__ import annotations
"""bass_utils.py
Low‑level helpers for *bass line generation*.

Goal
----
Provide reusable building blocks so that :class:`generator.bass_generator.BassGenerator`
can focus on high‑level style selection while this module handles the **note‑by‑note
logic**.

Features
~~~~~~~~
* *Root‑only*, *Root–5th*, or *Walking* styles (quarter feel).
* Chromatic or diatonic **approach notes** automatically inserted on the last
  eighth/quarter before a new chord.
* Uses :pyclass:`generator.utils.scale_registry.ScaleRegistry` to stay mode‑aware.
"""

from typing import List, Sequence
import random as _rand
import logging

from music21 import note, pitch, harmony, interval

from generator.utils.scale_registry import ScaleRegistry as SR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: choose chromatic approach note toward target
# ---------------------------------------------------------------------------

def approach_note(cur_root: pitch.Pitch, next_root: pitch.Pitch, direction: int | None = None) -> pitch.Pitch:
    """Return a semitone approach toward *next_root*.

    Parameters
    ----------
    cur_root : music21.pitch.Pitch
        The pitch we are currently on.
    next_root : music21.pitch.Pitch
        The target pitch to approach.
    direction : int | None
        +1 (chromatic up) or -1 (chromatic down).  If *None* the shortest chromatic
        direction is chosen automatically.
    """
    if direction is None:
        direction = 1 if next_root.midi - cur_root.midi > 0 else -1
    return cur_root.transpose(direction)

# ---------------------------------------------------------------------------
# Walking line generator (4/4) – returns 4 quarter pitches
# ---------------------------------------------------------------------------

def walking_quarters(
    cs_now: harmony.ChordSymbol,
    cs_next: harmony.ChordSymbol,
    tonic: str,
    mode: str,
    octave: int = 3,
) -> List[pitch.Pitch]:
    """Generate a 1‑bar 4‑beat walking bass line from *cs_now* → *cs_next*.

    Strategy:  Root – Chord‑tone – diatonic/approach – Approach(rootNext)
    """
    scl = SR.get(tonic, mode)
    degrees = [cs_now.root().pitchClass,
               cs_now.third.pitchClass,
               cs_now.fifth.pitchClass]

    root_now = cs_now.root().transpose((octave - cs_now.root().octave) * 12)
    root_next = cs_next.root().transpose((octave - cs_next.root().octave) * 12)

    # Beat1: Root
    beat1 = root_now

    # Beat2: choose 3rd or 5th (direction toward next root)
    options_b2 = [p for p in cs_now.pitches if p.pitchClass in degrees[1:]]
    beat2_raw = _rand.choice(options_b2)
    beat2 = beat2_raw.transpose((octave - beat2_raw.octave) * 12)

    # Beat3: diatonic step (up/down) inside scale toward target
    step_int = +2 if root_next.midi - beat2.midi > 0 else -2
    beat3 = beat2.transpose(step_int)
    # diatonic safeguard
    if beat3.pitchClass not in [p.pitchClass for p in scl.getPitches()]:
        beat3 = beat2  # fallback hold

    # Beat4: chromatic approach into next root
    beat4 = approach_note(beat3, root_next)

    return [beat1, beat2, beat3, beat4]

# ---------------------------------------------------------------------------
# Root‑fifth pattern (ballad)
# ---------------------------------------------------------------------------

def root_fifth_half(
    cs: harmony.ChordSymbol,
    octave: int = 3,
) -> List[pitch.Pitch]:
    root = cs.root().transpose((octave - cs.root().octave) * 12)
    fifth = cs.fifth.transpose((octave - cs.fifth.octave) * 12)
    return [root, fifth, root, fifth]

# ---------------------------------------------------------------------------
# Dispatcher – returns list of 4 quarterLength notes
# ---------------------------------------------------------------------------

STYLE_DISPATCH = {
    "root_only": lambda cs_now, cs_next, **k: [cs_now.root().transpose((k["octave"] - cs_now.root().octave) * 12)] * 4,
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
) -> List[note.Note]:
    """Return a list of 4 :class:`music21.note.Note` quarter‑notes for a measure."""
    func = STYLE_DISPATCH.get(style, STYLE_DISPATCH["root_only"])
    pitches = func(cs_now=cs_now, cs_next=cs_next, tonic=tonic, mode=mode, octave=octave)
    notes = []
    for p in pitches:
        n = note.Note(p)
        n.quarterLength = 1.0
        notes.append(n)
    return notes
