# -*- coding: utf-8 -*-
"""
Refactored GuitarGenerator module for Harusan's 言葉と歌の文芸プロジェクト
==========================================================================

Goals
-----
* **Expressive realism** – simulate down/up‑stroke timing, fret noise, palm‑mute,
  and velocity curves that reflect human guitar performance.
* **Pattern‑driven workflow** – read declarative patterns from `rhythm_library.json`.
  Support both **fixed** and **algorithmic** patterns (arpeggio, mute‑chug, random
  funk scratching, etc.).
* **Style keyword routing** – each section can reference a `guitar_style_keyword`
  that resolves to a pattern key plus generation **options** (strum spread, swing
  ratio, articulation presets).
* **Playability‑aware voicing** – leverage the existing `chord_voicer.get_guitar_voicing()`
  to map chord symbols into fret‑valid shapes favouring minimal movement.
* **Humanization** – micro‑timing & velocity fluctuations (via
  `humanizer.apply_timing_humanization()` / `humanizer.apply_velocity_curve()`).

This file is **self‑contained** except for lightweight hooks to:
* `chord_voicer`  – fretboard‑aware voicing search
* `humanizer`     – timing / velocity jitter utilities
* `core_music_utils` – common helpers (tempo → seconds, note utilities)

Typical usage
-------------
```python
from guitar_generator_refactor import GuitarGenerator
from rhythm_library import GUITAR_PATTERNS   # Load JSON beforehand

section_cfg = song_sections["Verse 1"]["part_settings"]
chords = section["chord_progression"]

gtr_gen = GuitarGenerator(
    rhythm_library=GUITAR_PATTERNS,
    tuning="standard_6",           # or "drop_d", "7_string", ...
    default_velocity=80,
    global_tempo=88,
)
part = gtr_gen.generate_section(section_cfg, chords)
part.write("midi", fp="guitar_verse1.mid")
```
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

from music21 import chord, note, stream, instrument, volume, articulations

# ‑‑ optional heavy deps (import lazily to avoid hard crash during CLI listing) --
try:
    import chord_voicer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – placeholder stubs during lint
    chord_voicer = None  # noqa: N816

try:
    import humanizer  # type: ignore
except ModuleNotFoundError:
    humanizer = None  # noqa: N816

################################################################################
# Helper dataclasses
################################################################################

@dataclass
class PatternEvent:
    offset_ql: float
    duration_ql: float
    velocity_factor: float = 1.0
    strum_direction: str = "down"  # "down" | "up" | "rake_up" | "arp"
    articulation: str = "normal"   # maps to music21 articulations
    string_subset: Optional[Tuple[int, int]] = None  # (lowest, highest) strings

@dataclass
class PatternDefinition:
    description: str
    pattern_type: str  # "fixed", "arpeggio_standard", "mute_fixed_step", ...
    events: List[PatternEvent] = field(default_factory=list)
    # algorithmic parameters – optional, vary by type
    step_duration_ql: float | None = None
    note_duration_ql: float | None = None
    options: Dict[str, Any] = field(default_factory=dict)

################################################################################
# GuitarGenerator class
################################################################################

class GuitarGenerator:
    """Create guitar *Part* objects based on rhythm‑library patterns."""

    def __init__(
        self,
        rhythm_library: Dict[str, Any],
        tuning: str = "standard_6",
        default_velocity: int = 80,
        global_tempo: int = 120,
        strum_spread_ms: int = 25,
    ) -> None:
        self.rhythm_library = rhythm_library["guitar_patterns"]
        self.tuning = tuning
        self.default_velocity = default_velocity
        self.global_tempo = global_tempo
        self.strum_spread_ql = self._ms_to_quarter_length(strum_spread_ms)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def generate_section(
        self,
        part_settings: Dict[str, Any],
        chord_progression: List[Dict[str, Any]],
        part_name: str = "Guitar",
    ) -> stream.Part:
        """Generate a *music21.stream.Part* for the given section."""
        style_key = part_settings.get("guitar_style_keyword", "guitar_default_quarters")
        pattern_def = self._resolve_pattern(style_key)

        part = stream.Part(id_=part_name)
        part.append(instrument.ElectricGuitar())

        current_offset = 0.0
        for chord_dict in chord_progression:
            duration_beats = chord_dict["duration_beats"]
            symbol = chord_dict["label"]
            voicing = self._voice_chord(symbol)

            if pattern_def.pattern_type.startswith("arpeggio"):
                self._render_arpeggio(part, voicing, current_offset, duration_beats, pattern_def)
            elif pattern_def.pattern_type in {"mute_fixed_step", "fixed"}:
                self._render_fixed(part, voicing, current_offset, pattern_def)
            else:  # algorithmic / TODO: more types
                self._render_fixed(part, voicing, current_offset, pattern_def)

            current_offset += duration_beats

        # humanize after all events inserted
        if humanizer:
            humanizer.apply_timing_humanization(part, timing_range_sec=0.02)
            humanizer.apply_velocity_curve(part, curve_fn="ease_in_out")

        return part

    # ------------------------------------------------------------------
    # Pattern rendering helpers
    # ------------------------------------------------------------------

    def _render_fixed(
        self,
        part: stream.Part,
        voicing: chord.Chord,
        start_offset: float,
        pattern_def: PatternDefinition,
    ) -> None:
        for ev in pattern_def.events:
            ev_offset = start_offset + ev.offset_ql
            n = voicing.clone(True)  # deep copy
            n.duration.quarterLength = ev.duration_ql
            n.volume = volume.Volume(velocity=int(self.default_velocity * ev.velocity_factor))

            # simple strum simulation: offset each note in voicing
            if ev.strum_direction in {"down", "up"}:
                strum_sign = 1 if ev.strum_direction == "down" else -1
                for i, pitch in enumerate(n.pitches[::strum_sign]):
                    p_note = note.Note(pitch)
                    p_note.offset = ev_offset + i * self.strum_spread_ql
                    p_note.duration.quarterLength = ev.duration_ql
                    p_note.volume = n.volume
                    if ev.articulation == "staccato":
                        p_note.articulations.append(articulations.Staccato())
                    part.insert(p_note)
            else:
                # block chord (no spread)
                n.offset = ev_offset
                part.insert(n)

    def _render_arpeggio(
        self,
        part: stream.Part,
        voicing: chord.Chord,
        start_offset: float,
        duration_beats: float,
        pattern_def: PatternDefinition,
    ) -> None:
        step = pattern_def.note_duration_ql or 0.5
        current = start_offset
        pitches = voicing.pitches
        idx = 0
        while current < start_offset + duration_beats:
            p = note.Note(pitches[idx % len(pitches)])
            p.offset = current
            p.duration.quarterLength = step
            p.volume = volume.Volume(velocity=self.default_velocity)
            part.insert(p)
            current += step
            idx += 1

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------

    def _resolve_pattern(self, style_key: str) -> PatternDefinition:
        """Turn a style keyword into a *PatternDefinition* dataclass."""
        raw = self.rhythm_library.get(style_key)
        if raw is None:
            raise KeyError(f"Guitar pattern '{style_key}' not found in rhythm library.")

        # fixed pattern → materialise events list
        events: List[PatternEvent] = []
        if "pattern" in raw:
            for ev in raw["pattern"]:
                events.append(
                    PatternEvent(
                        offset_ql=ev["offset"],
                        duration_ql=ev["duration"],
                        velocity_factor=ev.get("velocity_factor", 1.0),
                        strum_direction=ev.get("strum_direction", "down"),
                        articulation=ev.get("articulation", "normal"),
                    )
                )

        return PatternDefinition(
            description=raw.get("description", ""),
            pattern_type=raw.get("pattern_type", "fixed"),
            events=events,
            step_duration_ql=raw.get("step_duration_ql"),
            note_duration_ql=raw.get("note_duration_ql"),
            options=raw.get("options", {}),
        )

    def _voice_chord(self, symbol: str) -> chord.Chord:
        if chord_voicer:
            return chord_voicer.get_guitar_voicing(symbol, tuning=self.tuning)
        # Fallback: naive closed position triad
        return chord.Chord(symbol)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @staticmethod
    def _ms_to_quarter_length(ms: float, tempo_bpm: float | int = 120) -> float:
        """Convert milliseconds to *music21* quarterLength at given tempo."""
        sec_per_beat = 60.0 / float(tempo_bpm)
        return (ms / 1000.0) / sec_per_beat


# --------------------------------------------------------------------------
# CLI entry for quick testing (e.g. python guitar_generator_refactor.py demo)
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import json, sys, pathlib

    if len(sys.argv) < 4:
        print("Usage: python guitar_generator_refactor.py <rhythm_library.json> <chordmap.json> <output.mid>")
        sys.exit(1)

    rhythm_lib = json.loads(pathlib.Path(sys.argv[1]).read_text())
    chordmap = json.loads(pathlib.Path(sys.argv[2]).read_text())

    section = chordmap["sections"]["Verse 1"]
    gtr_gen = GuitarGenerator(rhythm_library=rhythm_lib, global_tempo=chordmap["global_settings"]["tempo"])

    part = gtr_gen.generate_section(section["part_settings"], section["chord_progression"])
    midi_file = sys.argv[3]
    s = stream.Stream()
    s.append(part)
    s.write("midi", fp=midi_file)
    print(f"✓ Wrote {midi_file}")
