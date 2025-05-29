# -*- coding: utf-8 -*-
"""
GuitarGenerator Refactor – Emotion‑Driven Style Selection
=======================================================
Harusan の「言葉と歌の文芸プロジェクト」向けギター生成モジュール。

この改訂では **歌詞感情 → スタイル自動マッピング** を実装します。

機能ハイライト
----------------
* **感情 ➜ バケット ➜ パターン**：`musical_intent.emotion` と `intensity` を解析し、
  `rhythm_library.json` の `guitar_patterns` キーへ自動的に紐付け。
* **CLI 優先**：`--guitar-style` が指定されていれば自動推定を上書き。
* **chordmap override**：セクション内に `part_settings.guitar_style_key` があればそれを採用。
* **拡張容易**：マッピングテーブルを JSON/TOML で外部定義可能（オプション）。

依存
----
* music21 ≥ 9.5
* rhythm_library_loader (ユーティリティ。JSON を dict へ)
* chordmap_loader      (ユーティリティ。セクション dict を取得)

例
--
```bash
python guitar_generator_refactor.py \
    --chordmap data/chordmap.json \
    --rhythm-library data/rhythm_library.json \
    --section "Chorus 1" \
    --outfile midi_output/gtr_ch1.mid
```

```bash
# 手動でスタイルを固定したい場合
python guitar_generator_refactor.py ... --guitar-style guitar_power_chord_8ths
```
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, Tuple

# === utils – these helpers are assumed to exist in the project ===
from rhythm_library_loader import load_rhythm_library  # type: ignore
from chordmap_loader import load_section_data         # type: ignore
from humanizer import PerformanceHumanizer  # type: ignore – existing module
from chord_voicer import GuitarVoicer                # type: ignore – existing module
from music21 import stream, instrument as m21inst, tempo

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1)  Emotion / Intensity → Guitar‑Pattern マッピング
# ---------------------------------------------------------------------------
# key = (emotion, intensity)  ;  value = guitar_pattern_key in rhythm_library.json
EMOTION_INTENSITY_MAP: Dict[Tuple[str, str], str] = {
    ("quiet_pain_and_nascent_strength", "low"): "guitar_ballad_arpeggio",
    ("deep_regret_gratitude_and_realization", "medium_low"): "guitar_ballad_arpeggio",
    ("acceptance_of_love_and_pain_hopeful_belief", "medium_high"): "guitar_folk_strum_simple",
    ("self_reproach_regret_deep_sadness", "medium_low"): "guitar_ballad_arpeggio",
    ("supported_light_longing_for_rebirth", "medium"): "guitar_folk_strum_simple",
    ("reflective_transition_instrumental_passage", "medium_low"): "guitar_ballad_arpeggio",
    ("trial_cry_prayer_unbreakable_heart", "medium_high"): "guitar_power_chord_8ths",
    ("memory_unresolved_feelings_silence", "low"): "guitar_ballad_arpeggio",
    ("wavering_heart_gratitude_chosen_strength", "medium"): "guitar_folk_strum_simple",
    ("reaffirmed_strength_of_love_positive_determination", "high"): "guitar_power_chord_8ths",
    ("hope_dawn_light_gentle_guidance", "medium"): "guitar_folk_strum_simple",
    ("nature_memory_floating_sensation_forgiveness", "medium_low"): "guitar_ballad_arpeggio",
    ("future_cooperation_our_path_final_resolve_and_liberation", "high_to_very_high_then_fade"): "guitar_power_chord_8ths",
}

DEFAULT_GUITAR_STYLE = "guitar_default_quarters"

# ---------------------------------------------------------------------------
# 2)  Pattern Selector
# ---------------------------------------------------------------------------
class GuitarStyleSelector:
    """Return guitar pattern key according to (emotion, intensity) with overrides."""

    def __init__(self, mapping: Dict[Tuple[str, str], str] | None = None):
        self.mapping = mapping or EMOTION_INTENSITY_MAP

    def select(self, *, emotion: str | None, intensity: str | None,
               cli_override: str | None = None,
               section_override: str | None = None) -> str:
        # 1. CLI has highest priority
        if cli_override:
            LOGGER.debug("CLI override for guitar style: %s", cli_override)
            return cli_override
        # 2. Section‑specific override in chordmap
        if section_override:
            LOGGER.debug("Chordmap override for guitar style: %s", section_override)
            return section_override
        # 3. Mapping table
        key = (emotion or "", intensity or "")
        style = self.mapping.get(key)
        if style is None:
            LOGGER.warning("No mapping for (%s, %s); falling back to %s", emotion, intensity, DEFAULT_GUITAR_STYLE)
            return DEFAULT_GUITAR_STYLE
        LOGGER.debug("Auto‑selected guitar style: %s", style)
        return style

# ---------------------------------------------------------------------------
# 3)  Core Generator
# ---------------------------------------------------------------------------
class GuitarGenerator:
    """Generate a music21.Stream for the guitar part of one section."""

    def __init__(self, rhythm_library: Dict[str, Any], *, tempo_bpm: int = 88,
                 humanize_opts: Dict[str, Any] | None = None):
        self.rhythm_lib = rhythm_library.get("guitar_patterns", {})
        self.tempo_bpm = tempo_bpm
        self.humanizer = PerformanceHumanizer(**(humanize_opts or {}))
        self.voicer = GuitarVoicer()
        self.selector = GuitarStyleSelector()

    # ---------------------------------------------------------------------
    def generate_section(self, section_cfg: Dict[str, Any], chords: list[Dict[str, Any]],
                         *, cli_guitar_style: str | None = None) -> stream.Part:
        """Return music21.Part ready for assembling into whole song."""
        intent = section_cfg.get("musical_intent", {})
        emotion = intent.get("emotion")
        intensity = intent.get("intensity")
        part_settings = section_cfg.get("part_settings", {})
        override_key = part_settings.get("guitar_style_key")  # optional field

        # 1. choose pattern key
        pattern_key = self.selector.select(emotion=emotion, intensity=intensity,
                                           cli_override=cli_guitar_style,
                                           section_override=override_key)
        pattern_def = self.rhythm_lib.get(pattern_key)
        if pattern_def is None:
            LOGGER.error("Pattern key %s not found; using default.", pattern_key)
            pattern_def = self.rhythm_lib.get(DEFAULT_GUITAR_STYLE, {})

        # 2. build music21 Part
        gtr_part = stream.Part(id="Guitar")
        gtr_part.insert(0, m21inst.ElectricGuitar())
        gtr_part.insert(0, tempo.MetronomeMark(number=self.tempo_bpm))

        # --- iterate over chords & pattern events ---
        length_beats = sum(c.get("duration_beats", 4) for c in chords)
        pattern_events = self._expand_pattern(pattern_def, length_beats)
        for event in pattern_events:
            n = self.voicer.voice_chord_event(chords, event)
            self.humanizer.apply(n, event)
            gtr_part.insert(event["offset"], n)  # type: ignore[arg-type]

        return gtr_part

    # ------------------------------------------------------------------
    def _expand_pattern(self, pattern_def: Dict[str, Any], section_length_beats: float):
        """Repeat / scale pattern across the whole section length."""
        pat = pattern_def.get("pattern", [])
        if not pat:
            LOGGER.warning("Empty pattern in definition %s", pattern_def.get("description", ""))
            return []
        # naive loop
        events = []
        cur = 0.0
        while cur < section_length_beats - 1e-6:
            for item in pat:
                evt = dict(item)  # shallow copy
                evt["offset"] = cur + item["offset"]
                events.append(evt)
            cur += pattern_def.get("length_beats", 4)
        return events

# ---------------------------------------------------------------------------
# 4)  CLI helper for one‑off generation / debug
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Emotion‑driven guitar part generator")
    p.add_argument("--chordmap", type=Path, required=True)
    p.add_argument("--section", type=str, required=True,
                   help="Section name to generate (e.g., 'Verse 1')")
    p.add_argument("--rhythm-library", type=Path, required=True)
    p.add_argument("--outfile", type=Path, required=True)
    p.add_argument("--tempo", type=int, default=88)
    p.add_argument("--guitar-style", type=str, default=None,
                   help="Override guitar style key (pattern) – overrides emotion mapping")
    return p


def main_cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    args = _build_arg_parser().parse_args()

    section_cfg, chords = load_section_data(args.section, args.chordmap)
    rhythm_lib = load_rhythm_library(args.rhythm_library)

    gen = GuitarGenerator(rhythm_lib, tempo_bpm=args.tempo)
    part = gen.generate_section(section_cfg, chords, cli_guitar_style=args.guitar_style)

    outfile = args.outfile
    outfile.parent.mkdir(parents=True, exist_ok=True)
    part.write("midi", fp=str(outfile))
    LOGGER.info("Wrote guitar part to %s", outfile)


if __name__ == "__main__":
    main_cli()
