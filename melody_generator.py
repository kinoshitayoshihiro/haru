from __future__ import annotations
"""melody_generator.py – *lightweight rewrite*

Generates a single *melody* :class:`music21.stream.Part` from processed blocks
produced by *modular_composer.prepare_processed_stream*.

Key features compared to legacy version
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* 依存ファイルを一掃 – 基本ロジックは **melody_utils.generate_melodic_pitches**
  に委譲。
* ``rhythm_library`` エントリは **beat‑offset テンプレート** のみ保持。
  例::
      "syncopated_8ths" : [0.0, 0.5, 1.0, 1.5],
      "lyric_triplet"   : [0.0, 0.33, 0.66, 1.0],
* 強拍はコード・トーン、弱拍はテンション／経過音を自動的に混在。
* テストしやすい stateless 設計 – グローバル乱数は ``random.Random``
  を DI で受け取れる。
"""

from typing import Dict, List, Sequence, Any, Tuple, Optional
import random
import logging

from music21 import stream, note, harmony

from generator.utils.melody_utils import generate_melodic_pitches

logger = logging.getLogger(__name__)


class MelodyGenerator:
    """Compose a melody part using mode‑aware pitch generator."""

    def __init__(
        self,
        rhythm_library: Dict[str, List[float]],
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        global_key_signature_tonic: str = "C",
        global_key_signature_mode: str = "major",
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rhythm_library = rhythm_library
        self.tempo = global_tempo
        self.ts_str = global_time_signature
        self.g_tonic = global_key_signature_tonic
        self.g_mode = global_key_signature_mode
        self.rng = rng or random.Random()

    # ------------------------------------------------------------------
    # Public API called by modular_composer
    # ------------------------------------------------------------------
    def compose(self, processed_blocks: Sequence[Dict[str, Any]]) -> stream.Part:
        part = stream.Part(id="Melody")
        current_offset = 0.0

        for blk in processed_blocks:
            if blk.get("part_params", {}).get("melody", {}).get("skip", False):
                current_offset += blk["q_length"]
                continue

            cs = harmony.ChordSymbol(blk["chord_label"])
            tonic = blk.get("tonic_of_section", self.g_tonic)
            mode = blk.get("mode", self.g_mode)
            rhythm_key = blk.get("part_params", {}).get("melody", {}).get("rhythm_key", "default_melody_rhythm")
            beat_template = self._get_beat_offsets(rhythm_key)

            # stretch template to block length (assume template within 1 bar 4/4)
            mul = blk["q_length"] / 4.0  # 4 beats base
            beat_offsets = [b * mul for b in beat_template]

            pitches = generate_melodic_pitches(
                cs,
                tonic,
                mode,
                beat_offsets,
                octave_range=tuple(blk.get("part_params", {}).get("melody", {}).get("octave_range", [4, 5])),
                rnd=self.rng,
            )

            # apply density (probability to keep a note)
            density = blk.get("part_params", {}).get("melody", {}).get("density", 0.7)
            for rel_off, n in zip(beat_offsets, pitches):
                if self.rng.random() <= density:
                    n.quarterLength = 0.5 * mul  # simple: eighth of stretched bar
                    part.insert(current_offset + rel_off, n)

            current_offset += blk["q_length"]

        return part

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _get_beat_offsets(self, rhythm_key: str) -> List[float]:
        """Return beat offset template for a given rhythm key (1‑bar)."""
        if rhythm_key in self.rhythm_library:
            return self.rhythm_library[rhythm_key]
        logger.warning("Rhythm key '%s' not found; using fallback quarter grid.", rhythm_key)
        return [0.0, 1.0, 2.0, 3.0]
