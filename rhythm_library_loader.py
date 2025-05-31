# -*- coding: utf-8 -*-
"""rhythm_library_loader.py
=================================
汎用リズムライブラリ・ローダー & バリデータ
"""
from __future__ import annotations

import json
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Final, List, Literal, Optional, Union

import yaml  # type: ignore
import tomli  # type: ignore
from pydantic import BaseModel, Field, ValidationError

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic Models ------------------------------------------------------------
# ---------------------------------------------------------------------------

class PatternEvent(BaseModel):
    """基本的なリズムイベントの定義"""
    offset: float = Field(..., description="Offset from the start of the pattern unit (in quarter lengths).", ge=0)
    duration: float = Field(..., description="Duration of the event (in quarter lengths).", gt=0)
    velocity_factor: Optional[float | int] = Field(None, description="Velocity multiplier (0.0 to N).", ge=0)
    instrument: Optional[str] = Field(None, description="Specific drum instrument (for drum patterns).")
    type: Optional[str] = Field(None, description="Note type hint (e.g., 'root', 'fifth' for bass/piano LH).")
    strum_direction: Optional[Literal["down", "up", "none"]] = Field(None, description="Strum direction for guitar.")
    scale_degree: Optional[Union[int, str]] = Field(None, description="Scale degree for melodic/bass patterns (e.g., 1, 'b3', 5).")
    octave: Optional[int] = Field(None, description="Specific octave for a note in the event.")
    glide_to_next: Optional[bool] = Field(None, description="Indicates if this note should glide to the next (for synths/bass).")
    accent: Optional[bool] = Field(None, description="Indicates if this event should be accented.")
    probability: Optional[float] = Field(None, description="Probability of this event occurring (0.0 to 1.0).", ge=0.0, le=1.0)

    model_config = {"extra": "allow"}


class BasePattern(BaseModel):
    """全楽器パターン共通のベースモデル"""
    description: Optional[str] = Field(None, description="Human-readable description of the pattern.")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorizing or searching patterns.")
    time_signature: Optional[str] = Field("4/4", description="Time signature this pattern is primarily designed for (e.g., '4/4', '3/4').")
    length_beats: Optional[float] = Field(4.0, description="Reference length of the pattern in beats (quarter notes). Used for scaling if pattern is applied to a block of different length.", gt=0)
    pattern_type: Optional[str] = Field(None, description="Type of pattern (e.g., 'fixed_pattern', 'algorithmic_...', 'arpeggio_indices'). Determines how 'pattern' or other fields are interpreted.")
    velocity_base: Optional[int] = Field(None, description="Base MIDI velocity for this pattern (1-127).", ge=1, le=127)
    options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional options for algorithmic patterns or specific behaviors.")
    # `pattern`フィールドは、具体的なイベントリスト、数値リスト（インデックス用）、またはアルゴリズムの場合は空でも可
    pattern: Optional[Union[List[PatternEvent], List[int], List[float]]] = Field(None, description="Core pattern data. Structure depends on pattern_type.")

    model_config = {"extra": "allow"}


class PianoPattern(BasePattern):
    """ピアノ特有のパターン定義"""
    arpeggio_type: Optional[Literal["up", "down", "up_down", "down_up", "random"]] = Field(None, description="Type of arpeggio if pattern_type is arpeggio-related.")
    note_duration_ql: Optional[float] = Field(None, description="Default duration for notes in arpeggios or algorithmic patterns (in quarter lengths).", gt=0)
    # voicing_style_rh: Optional[str] = None # These might be better handled by chordmap/overrides
    # voicing_style_lh: Optional[str] = None


class DrumPattern(BasePattern):
    """ドラム特有のパターン定義"""
    pattern: Optional[List[PatternEvent]] = Field(None, description="List of drum hit events.") # DrumPatternではPatternEventのリストを期待
    swing: Optional[Union[float, Dict[str, Any]]] = Field(None, description="Swing setting. Float for ratio (0.5=straight) or dict for detailed control (e.g., {'type': 'eighth', 'ratio': 0.6}).")
    fill_ins: Optional[Dict[str, List[PatternEvent]]] = Field(default_factory=dict, description="Named fill-in patterns associated with this main pattern.")
    inherit: Optional[str] = Field(None, description="Key of another drum pattern to inherit properties from.")


class BassPattern(BasePattern):
    """ベース特有のパターン定義"""
    target_octave: Optional[int] = Field(None, description="Preferred MIDI octave for the bassline (e.g., 1, 2).")
    note_duration_ql: Optional[float] = Field(None, description="Default duration for notes if not specified in events (e.g., for pedal tones).", gt=0)
    # weak_beat_style, approach_on_4th_beat etc. are often in 'options' for algorithmic patterns
    # or handled by overrides, but could be here if a pattern *always* has a certain style.


class GuitarPattern(BasePattern):
    """ギター特有のパターン定義"""
    arpeggio_indices: Optional[List[int]] = Field(None, description="Indices of chord tones for arpeggio patterns (0=root, 1=next, etc.).")
    strum_width_sec: Optional[float] = Field(None, description="Duration of a simulated strum in seconds.", ge=0)
    note_duration_ql: Optional[float] = Field(None, description="Default duration for notes in arpeggios or fixed step patterns.", gt=0)
    step_duration_ql: Optional[float] = Field(None, description="Duration of each step in 'mute_fixed_step' patterns.", gt=0)
    note_articulation_factor: Optional[float] = Field(None, description="Multiplier for note duration to create staccato/legato (0.0 to 1.0).", ge=0, le=1)
    strum_direction_cycle: Optional[List[Literal["down", "up"]]] = Field(None, description="Cycle of strum directions for rhythmic strumming patterns.")
    tremolo_rate_hz: Optional[float] = Field(None, description="Rate of tremolo picking in Hz for 'tremolo_crescendo'.", gt=0)
    crescendo_curve: Optional[Literal["linear", "exponential", "logarithmic"]] = Field(None, description="Shape of the crescendo for 'tremolo_crescendo'.")
    duration_beats: Optional[float] = Field(None, description="Total duration of a swell or effect in beats.", gt=0)
    velocity_start: Optional[int] = Field(None, description="Starting velocity for swells (1-127).", ge=1, le=127)
    velocity_end: Optional[int] = Field(None, description="Ending velocity for swells (1-127).", ge=1, le=127)
    palm_mute_level_recommended: Optional[float] = Field(None, description="Recommended palm mute level (0.0 to 1.0), interpreted by generator.", ge=0, le=1)


class RhythmLibrary(BaseModel):
    """リズムライブラリ全体の構造"""
    piano_patterns: Optional[Dict[str, PianoPattern]] = Field(default_factory=dict)
    drum_patterns: Optional[Dict[str, DrumPattern]] = Field(default_factory=dict)
    bass_patterns: Optional[Dict[str, BassPattern]] = Field(default_factory=dict)
    guitar_patterns: Optional[Dict[str, GuitarPattern]] = Field(default_factory=dict)
    # 他の楽器カテゴリも将来的には具体的な型モデルで定義することを推奨
    extra: Dict[str, Any] = Field(default_factory=dict, description="For other instrument categories or miscellaneous data.")

    model_config = {
        "extra": "allow", # 未知のトップレベルキーも許容 (ただし通常は上記カテゴリに収める)
    }

# ---------------------------------------------------------------------------
# Public API ----------------------------------------------------------------
# ---------------------------------------------------------------------------
LIB_PATH_ENV: Final[str] = "RHYTHM_LIBRARY_PATH"
EXTRA_DIR_ENV: Final[str] = "RHYTHM_EXTRA_DIR"

@lru_cache(maxsize=None)
def load_rhythm_library(path: str | os.PathLike[str] | None = None,
                        *,
                        extra_dir: str | os.PathLike[str] | None = None,
                        force_reload: bool = False) -> RhythmLibrary:
    if force_reload:
        load_rhythm_library.cache_clear()
        LOGGER.info("Rhythm library cache cleared due to force_reload=True.")

    src_path = _resolve_main_path(path)
    raw_data = _parse_file(src_path) # _parse_file は Dict[str, Any] を返す

    extra_dir_resolved = _resolve_extra_dir(extra_dir)
    if extra_dir_resolved:
        raw_data = _merge_extra_patterns(raw_data, extra_dir_resolved)

    try:
        # Pydanticモデルでバリデーション
        lib = RhythmLibrary.model_validate(raw_data)
    except ValidationError as exc:
        error_details = _format_pydantic_errors(exc)
        LOGGER.error(f"Rhythm library validation failed for {src_path}:\n{error_details}")
        # エラー時は例外を発生させる
        raise ValueError(f"Rhythm library validation failed for {src_path}:\n{error_details}")

    num_extra_files = 0
    if extra_dir_resolved:
        try:
            num_extra_files = len([f for f in extra_dir_resolved.rglob('*.*') if f.is_file() and f.suffix.lower() in {".json", ".yaml", ".yml", ".toml"}])
        except Exception as e_glob:
            LOGGER.warning(f"Could not count files in extra_dir {extra_dir_resolved}: {e_glob}")

    LOGGER.info("Rhythm library loaded: %s (+%s extra files merged)", src_path.name, num_extra_files)
    return lib

# ---------------------------------------------------------------------------
# Helpers -------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _resolve_main_path(path: str | os.PathLike[str] | None) -> Path:
    if path is None:
        path_str = os.getenv(LIB_PATH_ENV)
        if not path_str:
            # デフォルトパスを data/rhythm_library.yml に変更 (YAML優先の想定)
            # 存在しなければ .json も試すなどのロジックも考えられる
            default_paths_to_try = ["data/rhythm_library.yml", "data/rhythm_library.yaml", "data/rhythm_library.json"]
            for p_try_str in default_paths_to_try:
                p_try = Path(p_try_str)
                if p_try.exists():
                    path_str = p_try_str
                    LOGGER.info(f"Rhythm library path not specified, using found default: {path_str}")
                    break
            if not path_str: # それでも見つからなければエラー
                 raise FileNotFoundError(f"Default rhythm library file not found in {default_paths_to_try}")
        path = path_str
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Rhythm library not found: {p}")
    return p


def _resolve_extra_dir(extra_dir: str | os.PathLike[str] | None) -> Path | None:
    if extra_dir is None:
        extra_dir_str = os.getenv(EXTRA_DIR_ENV)
        if not extra_dir_str:
            extra_dir_str = "extra_patterns" # デフォルトのディレクトリ名
            # このデフォルトディレクトリが存在するかどうかはここではチェックしない
            # LOGGER.info(f"Rhythm extra directory not specified, using default name: {extra_dir_str}")
        extra_dir = extra_dir_str

    p = Path(extra_dir).expanduser().resolve()
    if p.exists() and p.is_dir():
        LOGGER.info(f"Using extra patterns directory: {p}")
        return p
    else:
        # 環境変数や引数で指定されたが存在しない場合は警告、デフォルト名で存在しない場合はinfo
        if os.getenv(EXTRA_DIR_ENV) == str(extra_dir) or extra_dir != "extra_patterns":
             LOGGER.warning(f"Specified rhythm extra directory not found or not a directory: {p}")
        else:
             LOGGER.info(f"Default rhythm extra directory '{extra_dir}' not found. No extra patterns will be loaded.")
        return None


def _parse_file(path: Path) -> Dict[str, Any]:
    LOGGER.debug(f"Parsing rhythm library file: {path}")
    try:
        with path.open('r', encoding='utf-8') as f:
            content = f.read()
            if not content.strip():
                LOGGER.warning(f"Rhythm library file is empty: {path}")
                return {}

            if path.suffix.lower() == ".json":
                return json.loads(content)
            elif path.suffix.lower() in {".yaml", ".yml"}:
                return yaml.safe_load(content)
            elif path.suffix.lower() == ".toml":
                return tomli.loads(content)
            else:
                # このエラーは load_rhythm_library でキャッチされる
                raise ValueError(f"Unsupported file format: {path.suffix}")
    except Exception as e:
        LOGGER.error(f"Error parsing file {path}: {e}", exc_info=True)
        raise # エラーを再発生


def _merge_extra_patterns(base: Dict[str, Any], extra_dir: Path) -> Dict[str, Any]:
    merged = base.copy()
    file_count = 0
    for file_path in extra_dir.rglob('*.*'):
        if file_path.suffix.lower() not in {".json", ".yaml", ".yml", ".toml"}:
            continue
        if file_path.is_file():
            file_count += 1
            try:
                LOGGER.debug(f"Merging extra patterns from: {file_path}")
                extra_data = _parse_file(file_path)
                for top_key, category_data in extra_data.items():
                    if top_key in merged and isinstance(merged[top_key], dict) and isinstance(category_data, dict):
                        # ディープマージ的な挙動（ネストした辞書もマージ）をしたい場合はより複雑なロジックが必要
                        # ここでは単純に update する（同じキーがあれば上書き）
                        merged[top_key].update(category_data)
                    elif isinstance(category_data, dict):
                        merged[top_key] = category_data
                    else:
                        LOGGER.warning(f"Cannot merge data for key '{top_key}' from {file_path}, as its value is not a dictionary.")
            except Exception as exc:
                LOGGER.warning(f"Skipping extra pattern file {file_path.name} due to error: {exc}")
                continue
    if file_count == 0:
        LOGGER.info(f"No valid pattern files found in extra directory: {extra_dir}")
    return merged


def _format_pydantic_errors(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        loc_str = " -> ".join(str(loc_item) for loc_item in error["loc"])
        lines.append(f"  - Location: {loc_str}")
        lines.append(f"    Message: {error['msg']}")
        lines.append(f"    Type: {error['type']}")
        input_value = error.get('input')
        # 入力値が長すぎる場合は省略
        input_str = str(input_value)
        if len(input_str) > 200:
            input_str = input_str[:200] + "..."
        lines.append(f"    Input: {input_str}")
        if "ctx" in error and error["ctx"]:
            lines.append(f"    Context: {error['ctx']}")
        lines.append("-" * 20) # エラーごとの区切り線
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# CLI -----------------------------------------------------------------------
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import pprint

    # CLI実行時のみ詳細なログレベルを設定
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(module)s.%(funcName)s: %(message)s')

    parser = argparse.ArgumentParser(description="Validate and inspect rhythm_library file.")
    parser.add_argument("library_file", nargs="?", help="Path to rhythm_library file (JSON, YAML, or TOML). Uses RHYTHM_LIBRARY_PATH or default (data/rhythm_library.yml) if not given.")
    parser.add_argument("--extra-dir", help="Directory containing extra pattern files. Uses RHYTHM_EXTRA_DIR or default (extra_patterns/) if not given.")
    parser.add_argument("--list", choices=["piano", "drums", "bass", "guitar"], help="List pattern keys of a specific category.")
    parser.add_argument("--show", metavar="PATH.TO.KEY", help="Show pattern detail (dot‑separated path, e.g., guitar_patterns.guitar_ballad_arpeggio).")
    parser.add_argument("--force-reload", action="store_true", help="Force reload the library, bypassing cache.")
    args = parser.parse_args()

    try:
        lib_model = load_rhythm_library(args.library_file, extra_dir=args.extra_dir, force_reload=args.force_reload)
        print("\nRhythm library loaded and validated successfully! 🎉")

        if args.list:
            category_name = f"{args.list}_patterns"
            category_data = getattr(lib_model, category_name, None)
            if category_data and isinstance(category_data, dict): # 辞書であることを確認
                print(f"\nPatterns in '{category_name}':")
                pprint.pprint(list(category_data.keys()))
            elif category_data is not None: # 存在はするが辞書ではない場合
                 print(f"Category '{category_name}' exists but is not a dictionary of patterns. Value: {category_data}")
            else:
                print(f"Category '{category_name}' not found or is empty in the library.")

        elif args.show:
            path_parts = args.show.split(".")
            current_node: Any = lib_model
            valid_path = True
            for i, part_name in enumerate(path_parts):
                if isinstance(current_node, BaseModel):
                    if hasattr(current_node, part_name):
                        current_node = getattr(current_node, part_name)
                    else: # フィールドがない場合、model_dumpして辞書としてアクセス試行
                        try:
                            dumped_node = current_node.model_dump()
                            if isinstance(dumped_node, dict) and part_name in dumped_node:
                                current_node = dumped_node[part_name]
                            else:
                                valid_path = False; break
                        except Exception: # model_dump失敗など
                            valid_path = False; break
                elif isinstance(current_node, dict):
                    if part_name in current_node:
                        current_node = current_node[part_name]
                    else:
                        valid_path = False; break
                else: # リストやプリミティブ型の場合
                    # もしパスの最後で、それが求める値ならOK
                    if i == len(path_parts) -1:
                        pass
                    else: #途中でプリミティブになったらパス不正
                        valid_path = False; break
            
            if valid_path:
                print(f"\nDetails for '{args.show}':")
                if isinstance(current_node, BaseModel):
                    pprint.pprint(current_node.model_dump(exclude_unset=True))
                else:
                    pprint.pprint(current_node)
            else:
                print(f"Path '{args.show}' not found or invalid in the library model.")
        
        # デバッグ用にフルダンプを見たい場合は以下のコメントを解除
        # print("\nFull library model (dump):")
        # pprint.pprint(lib_model.model_dump(exclude_unset=True, exclude_none=True))


    except FileNotFoundError as e:
        LOGGER.error(f"File not found: {e}")
        sys.exit(1)
    except ValueError as e: 
        LOGGER.error(f"Error processing rhythm library: {e}")
        # 詳細なPydanticエラーは既にload_rhythm_library内でログ出力されているはず
        sys.exit(1)
    except Exception as e:
        LOGGER.error(f"An unexpected error occurred during CLI execution: {e}", exc_info=True)
        sys.exit(1)