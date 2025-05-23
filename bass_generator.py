from __future__ import annotations
"""bass_generator.py – streamlined rewrite

Generates a **bass part** for the modular composer pipeline.
The heavy lifting (walking line, root‑fifth, etc.) is delegated to
:pyfunc:`generator.utils.bass_utils.generate_bass_measure` so that this class
mainly decides **which style to use when**.
"""

from typing import Sequence, Dict, Any, Optional
import random
import logging

from music21 import stream, harmony

from generator.utils.bass_utils import generate_bass_measure

logger = logging.getLogger(__name__)


class BassGenerator:
    """Create a bass :class:`music21.stream.Part`."""

    def __init__(
        self,
        rhythm_library: Dict[str, Dict],  # retained for compatibility (not heavily used)
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rhythm_library = rhythm_library  # not strictly needed but kept
        self.tempo = global_tempo
        self.ts_str = global_time_signature
        self.rng = rng or random.Random()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def compose(self, processed_blocks: Sequence[Dict[str, Any]]) -> stream.Part:
        part = stream.Part(id="Bass")
        cur_offset = 0.0

        for i, blk in enumerate(processed_blocks):
            blk_params = blk["part_params"].get("bass", {})
            style = self._select_style(blk_params, blk)

            cs_now = harmony.ChordSymbol(blk["chord_label"])
            # next chord symbol for approach
            if i + 1 < len(processed_blocks):
                cs_next = harmony.ChordSymbol(processed_blocks[i + 1]["chord_label"])
            else:
                cs_next = cs_now  # last bar: approach root itself

            tonic = blk.get("tonic_of_section", "C")
            mode = blk.get("mode", "major")

            notes = generate_bass_measure(
                style,
                cs_now,
                cs_next,
                tonic,
                mode,
                octave=blk_params.get("octave", 2),
            )

            # distribute notes across the block's length (assume 4/4 template)
            stretch = blk["q_length"] / 4.0
            for beat_idx, n in enumerate(notes):
                n.quarterLength *= stretch  # stretch note value
                part.insert(cur_offset + beat_idx * stretch, n)

            cur_offset += blk["q_length"]

        return part

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _select_style(self, bass_params: Dict[str, Any], blk: Dict[str, Any]) -> str:
        """Decide which bass style to use for the block."""
        # explicit override > intensity heuristic > default
        if "style" in bass_params:
            return bass_params["style"]

        intensity = blk.get("musical_intent", {}).get("intensity", "medium").lower()
        if intensity in {"low", "medium_low"}:
            return "root_only"
        if intensity in {"medium", "medium_high"}:
            return "root_fifth"
        return "walking"  # high energy or unspecified
