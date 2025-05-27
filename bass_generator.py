# --- START OF FILE modular_composer.py (bass_generator v2.0 組み込み修正案) ---
import music21
import sys
import os
import json
import argparse
import logging
from music21 import stream, tempo, instrument as m21instrument, midi, meter, key
from pathlib import Path
from typing import List, Dict, Optional, Any, cast, Sequence
import random

# --- ジェネレータクラスのインポート (generatorフォルダから) ---
try:
    from generator.core_music_utils import get_time_signature_object # 既存のものを引き続き使用
    from generator.piano_generator import PianoGenerator
    from generator.drum_generator import DrumGenerator
    from generator.chord_voicer import ChordVoicer
    from generator.melody_generator import MelodyGenerator
    # ★★★ 新しい BassGenerator をインポート ★★★
    from generator.bass_generator import BassGenerator # 新しい bass_generator.py を指す
    # from generator.guitar_generator import GuitarGenerator # 必要に応じて
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import generator modules from 'generator' package. "
          f"Ensure 'generator' directory is in the project root and contains __init__.py. Error: {e}")
    # ★★★ エラーの詳細を表示するために traceback を追加すると良いかもしれません ★★★
    import traceback
    traceback.print_exc()
    exit(1)
except Exception as e_imp:
    print(f"An unexpected error occurred during module import: {e_imp}")
    import traceback
    traceback.print_exc()
    exit(1)

# --- ロガー設定 (変更なし) ---
# ... (既存のロガー設定) ...
logger = logging.getLogger("modular_composer")


# --- デフォルト設定 (変更なし、ただし bass の rhythm_key のデフォルト値に注意) ---
DEFAULT_CONFIG = {
    # ... (既存のDEFAULT_CONFIG) ...
    "default_part_parameters": {
        # ... (piano, drums, chords, melody の設定) ...
        "bass": {
            "instrument": "AcousticBass",
            # ★★★ 新しい bass_generator.py が期待するリズムキーの例 ★★★
            # "bass_rhythm_key": "root_only", # rhythm_library.json に "root_only" の定義が必要
            "bass_rhythm_key": "bass_quarter_notes", # 既存のデフォルト、または rhythm_library.json に合わせて変更
            "bass_octave": 2, # 新しい BassGenerator が参照する可能性のあるキー
            "bass_velocity": 70, # 新しい BassGenerator が参照する可能性のあるキー
            "bass_humanize": True, # 新しい BassGenerator のヒューマナイズ機能
            "bass_humanize_template": "default_subtle"
            # "style": "simple_roots", # 古いBassGeneratorのパラメータ、新しい方ではrhythm_keyで制御
        }
    },
    # ... (残りのDEFAULT_CONFIG) ...
}

# --- load_json_file (変更なし) ---
# ... (既存の load_json_file 関数) ...

# --- translate_keywords_to_params (bass 部分の修正) ---
def translate_keywords_to_params(
        musical_intent: Dict[str, Any], chord_block_specific_hints: Dict[str, Any],
        default_instrument_params: Dict[str, Any], instrument_name_key: str,
        rhythm_library_all_categories: Dict
) -> Dict[str, Any]:
    params: Dict[str, Any] = default_instrument_params.copy()
    emotion_key = musical_intent.get("emotion", "neutral").lower()
    intensity_key = musical_intent.get("intensity", "medium").lower()
    section_instrument_settings = chord_block_specific_hints.get("part_settings", {}).get(instrument_name_key, {})
    params.update(section_instrument_settings)

    logger.debug(f"Translating for {instrument_name_key}: Emo='{emotion_key}', Int='{intensity_key}', InitialParams='{params}'")

    if instrument_name_key == "piano":
        # ... (既存のpianoパラメータ処理) ...
        pass # 簡略化のため省略
    elif instrument_name_key == "drums":
        # ... (既存のdrumsパラメータ処理) ...
        pass # 簡略化のため省略
    elif instrument_name_key == "melody":
        # ... (既存のmelodyパラメータ処理) ...
        pass # 簡略化のため省略
    elif instrument_name_key == "bass":
        cfg_bass = default_instrument_params # DEFAULT_CONFIG["default_part_parameters"]["bass"]
        
        # 新しいBassGeneratorは主に "bass_rhythm_key" を参照する
        # 感情やインテンシティからリズムキーを選択するロジックがあればここに記述
        # 例:
        # emotion_to_bass_rhythm = {"happy": "algorithmic_walking", "sad": "algorithmic_root_only", "default": "root_only"}
        # selected_rhythm_key = emotion_to_bass_rhythm.get(emotion_key, emotion_to_bass_rhythm["default"])
        # params["bass_rhythm_key"] = params.get("bass_rhythm_key", selected_rhythm_key)
        
        # もし chordmap 側で直接 bass_rhythm_key が指定されていればそれが優先される
        # 指定がなければ DEFAULT_CONFIG の値が使われる
        params["bass_rhythm_key"] = params.get("bass_rhythm_key", cfg_bass.get("bass_rhythm_key"))

        # 新しいBassGeneratorが使用する可能性のある他のパラメータも設定
        params["bass_octave"] = params.get("bass_octave", cfg_bass.get("bass_octave"))
        params["bass_velocity"] = params.get("bass_velocity", cfg_bass.get("bass_velocity"))
        params["bass_humanize"] = params.get("bass_humanize", cfg_bass.get("bass_humanize"))
        params["bass_humanize_template"] = params.get("bass_humanize_template", cfg_bass.get("bass_humanize_template"))

        # rhythm_library.json の "bass_patterns" カテゴリを参照する
        bass_patterns_lib = rhythm_library_all_categories.get("bass_patterns", {})
        if not params["bass_rhythm_key"] or params.get("bass_rhythm_key") not in bass_patterns_lib:
            fallback_bass_key = "root_only" # 新しいBassGeneratorのフォールバック
            logger.warning(f"Bass rhythm key '{params.get('bass_rhythm_key')}' not in bass_patterns. Using fallback '{fallback_bass_key}'.")
            params["bass_rhythm_key"] = fallback_bass_key
            if fallback_bass_key not in bass_patterns_lib:
                 logger.error(f"CRITICAL: Fallback bass key '{fallback_bass_key}' also not in bass_patterns library!")


    block_instrument_hints = chord_block_specific_hints.get("part_specific_hints", {}).get(instrument_name_key, {})
    params.update(block_instrument_hints)
    # ... (残りのパラメータ処理、drum_fillなど) ...
    logger.info(f"Final params for [{instrument_name_key}] (Emo: {emotion_key}, Int: {intensity_key}) -> {params}")
    return params

# --- prepare_processed_stream (大きな変更なし、translate_keywords_to_params の呼び出しはそのまま) ---
# ... (既存の prepare_processed_stream 関数) ...

# --- run_composition (BassGeneratorのインスタンス化部分を修正) ---
def run_composition(cli_args: argparse.Namespace, main_cfg: Dict, chordmap: Dict, rhythm_lib_all: Dict):
    logger.info("=== Running Main Composition Workflow ===")
    final_score = stream.Score()
    # ... (スコアのグローバル設定) ...

    proc_blocks = prepare_processed_stream(chordmap, main_cfg, rhythm_lib_all)
    if not proc_blocks: logger.error("No blocks to process. Abort."); return

    cv_inst = ChordVoicer(global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    gens: Dict[str, Any] = {}

    if main_cfg["parts_to_generate"].get("piano"):
        # ... (PianoGeneratorのインスタンス化) ...
        pass
    if main_cfg["parts_to_generate"].get("drums"):
        # ... (DrumGeneratorのインスタンス化) ...
        pass
    if main_cfg["parts_to_generate"].get("chords"):
        gens["chords"] = cv_inst
    if main_cfg["parts_to_generate"].get("melody"):
        # ... (MelodyGeneratorのインスタンス化) ...
        pass
    if main_cfg["parts_to_generate"].get("bass"):
        logger.info(f"Initializing new BassGenerator with rhythm_library: {rhythm_lib_all.get('bass_patterns', {}).keys()}")
        gens["bass"] = BassGenerator(
            # ★★★ 新しい BassGenerator の __init__ に合わせて引数を渡す ★★★
            # rhythm_library は rhythm_lib_all 全体を渡すか、
            # "bass_patterns" セクションだけを渡すか、BassGeneratorの実装による。
            # 新しいBassGeneratorは __init__ で .get("bass_patterns", {}) しているので全体でOK。
            rhythm_library=rhythm_lib_all,
            default_instrument=m21instrument.AcousticBass(), # または main_cfg から取得
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"],
            global_key_tonic=main_cfg["global_key_tonic"],
            global_key_mode=main_cfg["global_key_mode"]
            # rng はオプションなので、必要なら random.Random() インスタンスを渡す
        )

    for p_n, p_g_inst in gens.items():
        if p_g_inst:
            logger.info(f"Generating {p_n} part...")
            try:
                # ★★★ 新しい BassGenerator は return_pretty_midi オプションを持つ可能性がある ★★★
                # ここでは music21.stream.Part を期待する
                if p_n == "bass" and hasattr(p_g_inst, 'compose') and 'return_pretty_midi' in p_g_inst.compose.__code__.co_varnames:
                    part_obj = p_g_inst.compose(proc_blocks, return_pretty_midi=False)
                else:
                    part_obj = p_g_inst.compose(proc_blocks)

                if isinstance(part_obj, stream.Score) and part_obj.parts:
                    # ... (既存の処理) ...
                elif isinstance(part_obj, stream.Part) and part_obj.flatten().notesAndRests:
                    final_score.insert(0, part_obj)
                logger.info(f"{p_n} part generated.")
            except Exception as e_gen: logger.error(f"Error in {p_n} generation: {e_gen}", exc_info=True)

    # ... (MIDIファイル書き出し処理) ...

# --- main_cli (大きな変更なし) ---
# ... (既存の main_cli 関数) ...

if __name__ == "__main__":
    main_cli()
# --- END OF FILE modular_composer.py (bass_generator v2.0 組み込み修正案) ---
