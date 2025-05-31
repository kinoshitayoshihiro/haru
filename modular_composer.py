# --- START OF FILE modular_composer.py (emotion_humanizer連携版 - prepare_stream_for_generators 実装) ---
import music21
from music21 import stream, tempo, meter, key, instrument as m21instrument, exceptions21

import sys
import os
import json
import yaml
import argparse
import logging
import inspect
import random
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, cast, Sequence

# --- ユーティリティとジェネレータのインポート ---
try:
    from utilities.rhythm_library_loader import load_rhythm_library as load_rhythm_lib_main_func
    from utilities.override_loader import load_overrides, Overrides as OverrideModelType, PartOverride as PartOverrideModelType
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label
    from generator import (
        PianoGenerator, DrumGenerator, GuitarGenerator, ChordVoicer,
        MelodyGenerator, BassGenerator, VocalGenerator
    )
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import modules: {e}")
    sys.exit(1)
except Exception as e_imp:
    print(f"An unexpected error occurred during module import: {e_imp}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger("modular_composer")

DEFAULT_CONFIG = {
    # ... (DEFAULT_CONFIGの内容は変更なし) ...
    "global_tempo": 120,
    "global_time_signature": "4/4",
    "global_key_tonic": "C",
    "global_key_mode": "major",
    "output_filename_template": "generated_song_{song_title}.mid",
    "parts_to_generate": {
        "piano": True, "drums": True, "bass": True, "guitar": True,
        "melody": False, "vocal": False, "chords": False
    },
    "default_part_parameters": {
        "piano": {
            "instrument": "Piano",
            "default_humanize": False, # emotion_humanizer.py が優先するため基本Falseに
            "default_humanize_style_template": "piano_gentle_arpeggio",
            "default_rh_voicing_style": "spread_upper", "default_lh_voicing_style": "closed_low",
            "default_rh_target_octave": 4, "default_lh_target_octave": 2,
            "default_rh_num_voices": 4, "default_lh_num_voices": 2,
            "default_piano_rh_rhythm_key": "piano_fallback_block", # フォールバックリズムキー
            "default_piano_lh_rhythm_key": "piano_lh_whole_notes",
            "default_velocity": 64, # emotion_humanizerで調整される基本値
        },
        "drums": {
            "instrument": "DrumSet", "default_humanize": False,
            "default_humanize_style_template": "drum_tight",
            "default_drum_style_key": "rock_beat_A_8th_hat",
            "default_drum_base_velocity": 80,
            "default_fill_interval_bars": 4, "default_fill_keys": ["rock_fill_1"]
        },
        "guitar": {
            "instrument": "AcousticGuitar", "default_humanize": False,
            "default_humanize_style_template": "guitar_strum_loose",
            "default_style": "strum_basic", "default_guitar_rhythm_key": "guitar_folk_strum_simple",
            "default_voicing_style": "standard_drop2", "default_num_strings": 6,
            "default_target_octave": 3, "default_velocity": 70,
        },
        "bass": {
            "instrument": "AcousticBass", "default_humanize": False,
            "default_humanize_style_template": "default_subtle",
            "default_rhythm_key": "bass_quarter_notes", "default_velocity": 80, "default_octave": 2,
            "default_weak_beat_style": "root",
            "default_options": { "approach_on_4th_beat": True, "approach_style_on_4th": "chromatic_or_diatonic"}
        },
        "melody": { "instrument": "Violin", "default_humanize": False, "default_rhythm_key": "melody_simple_quarters", "default_velocity": 70},
        "vocal": { "instrument": "Voice", "default_humanize": False, "data_paths": {}}, # humanizeはvocal_generator内で処理
        "chords": {"instrument": "ElectricPiano", "default_humanize": False, "default_velocity": 60} # ChordVoicer用
    },
    "rng_seed": None
}

def load_yaml_file(file_path: Path, description: str) -> Optional[Dict]:
    if not file_path.exists():
        logger.error(f"{description} not found: {file_path}")
        sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        logger.info(f"Loaded {description} from: {file_path}")
        return data
    except yaml.YAMLError as e_yaml:
        logger.error(f"Error decoding YAML from {description} at {file_path}: {e_yaml}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading {description} from {file_path}: {e}", exc_info=True)
        sys.exit(1)

def _get_humanize_params_for_final_touch( # 汎用ヒューマナイザ用のパラメータ取得（役割変更）
    instrument_final_params: Dict[str, Any], # 既に感情などが反映されたパラメータ
    default_cfg_instrument: Dict[str, Any] # DEFAULT_CONFIGの楽器設定
) -> Dict[str, Any]:
    """
    最終的な微調整のための汎用ヒューマナイズパラメータを取得する。
    emotion_humanizer.py で主要な表現は行われた後、さらに「楽器の癖」のような
    ランダムな揺らぎを加えたい場合に使う。
    """
    humanize_settings = {}
    # DEFAULT_CONFIG に "final_touch_humanize" のようなキーで設定を定義することを想定
    final_touch_cfg = default_cfg_instrument.get("final_touch_humanize", {})
    
    humanize_settings["humanize_opt"] = final_touch_cfg.get("enable", False) # デフォルトはオフ
    if humanize_settings["humanize_opt"]:
        humanize_settings["template_name"] = final_touch_cfg.get("template_name", "default_subtle")
        humanize_settings["custom_params"] = final_touch_cfg.get("custom_params", {})
    return humanize_settings


def translate_and_merge_params_from_emotion_data(
    processed_event_data: Dict[str, Any], # emotion_humanizer.py からの1イベント分のデータ
    section_part_settings: Dict[str, Any], # chordmap のセクション全体の part_settings
    instrument_default_params_from_config: Dict[str, Any],
    instrument_name_key: str,
    rhythm_library_for_instrument: Dict[str, Any], # その楽器専用のリズムライブラリ辞書
    arrangement_override_for_part: Optional[PartOverrideModelType] # このパート・セクションのOverrideモデル
) -> Dict[str, Any]:
    """
    emotion_humanizer.py の出力、chordmap の part_settings、DEFAULT_CONFIG、
    arrangement_overrides をマージし、最終的な楽器パラメータを決定する。
    """
    # 1. DEFAULT_CONFIG の楽器デフォルトをベースにする
    final_params = instrument_default_params_from_config.copy()

    # 2. chordmap.yaml のセクション全体の part_settings で上書き
    final_params.update(section_part_settings)

    # 3. arrangement_overrides.json の設定で上書き (これが最も優先度が高い)
    if arrangement_override_for_part:
        override_dict = arrangement_override_for_part.model_dump(exclude_unset=True)
        # ネストされた 'options' は特別にマージ
        if "options" in override_dict and "options" in final_params and isinstance(final_params["options"], dict) and isinstance(override_dict["options"], dict):
            final_params["options"].update(override_dict.pop("options"))
        final_params.update(override_dict)

    # 4. emotion_humanizer.py からの直接的な演奏指示を適用
    emotion_params = processed_event_data.get("emotion_params", {}) # emotion_profile_applied の内容
    
    # ベロシティ: emotion_params にあればそれを使い、なければ既存の final_params["velocity"] を使う
    final_params["velocity"] = emotion_params.get("velocity", final_params.get("velocity"))
    # アーティキュレーション: emotion_params から取得
    final_params["articulation_from_emotion"] = emotion_params.get("articulation")
    # オンセットシフトとサステインファクターはオフセットとデュレーションに反映済みなので、ここでは直接使わない

    # 5. リズムキーの決定
    # 優先順位: arrangement_override -> part_settings -> expression_details.target_rhythm_category -> DEFAULT_CONFIG
    # (各ジェネレータが自身のロジックでリズムキーを選択する方が柔軟かもしれない)
    # ここでは、final_params に既に存在するリズムキー指定 (例: drum_style_key) を尊重する形とする。
    # もし expression_details.target_rhythm_category を使いたい場合は、
    # 各ジェネレータがそれを解釈して具体的なリズムキーに変換するロジックが必要。
    # 例:
    # if instrument_name_key == "drums" and "drum_style_key" not in final_params:
    #     rhythm_cat = processed_event_data.get("expression_details", {}).get("target_rhythm_category")
    #     if rhythm_cat == "ballad_feel": final_params["drum_style_key"] = "ballad_soft_kick_snare_8th_hat" # マッピングが必要

    # 6. 最終的な微調整用ヒューマナイズパラメータ (オプション)
    # final_touch_humanize_params = _get_humanize_params_for_final_touch(final_params, instrument_default_params_from_config)
    # final_params.update(final_touch_humanize_params) # 必要ならマージ

    return final_params


def prepare_stream_for_generators(
    processed_chordmap_data: Dict, # 感情ヒューマナイズ済みYAMLの内容
    main_config: Dict,
    rhythm_lib_all: Dict, # 全楽器のカテゴリ別リズムパターン辞書
    arrangement_overrides: OverrideModelType # 全体のOverridesモデル
) -> List[Dict]:
    logger.info("Preparing stream for generators from processed emotion chordmap...")
    stream_for_generators: List[Dict] = []
    
    global_settings = processed_chordmap_data.get("global_settings", {})
    
    sorted_sections = sorted(processed_chordmap_data.get("sections", {}).items(), key=lambda item: item[1].get("order", float('inf')))

    for sec_name, sec_data in sorted_sections:
        sec_musical_intent = sec_data.get("musical_intent", {})
        sec_expression_details = sec_data.get("expression_details", {})
        sec_part_settings_overall = sec_data.get("part_settings", {})
        
        for event_idx, event_from_humanizer in enumerate(sec_data.get("processed_chord_events", [])):
            blk_data = {
                "absolute_offset": event_from_humanizer.get("absolute_offset_beats"),
                "q_length": event_from_humanizer.get("humanized_duration_beats"),
                "original_chord_label": event_from_humanizer.get("original_chord_label"),
                "chord_symbol_for_voicing": event_from_humanizer.get("chord_symbol_for_voicing"),
                "specified_bass_for_voicing": event_from_humanizer.get("specified_bass_for_voicing"),
                "section_name": sec_name,
                "tonic_of_section": sec_expression_details.get("section_tonic"),
                "mode": sec_expression_details.get("section_mode"),
                "is_first_in_section": (event_idx == 0),
                "is_last_in_section": (event_idx == len(sec_data.get("processed_chord_events", [])) - 1),
                "musical_intent": sec_musical_intent,
                "expression_details": sec_expression_details,
                "emotion_params": event_from_humanizer.get("emotion_profile_applied", {}),
                "part_params": {}
            }

            for part_name, generate_flag in main_config.get("parts_to_generate", {}).items():
                if generate_flag:
                    instrument_default_cfg = main_config["default_part_parameters"].get(part_name, {})
                    # カテゴリキーを生成 (例: "piano_patterns")
                    rhythm_category_key = f"{part_name}_patterns" if part_name not in ["chords", "vocal", "melody"] else None
                    rhythm_lib_for_instrument = rhythm_lib_all.get(rhythm_category_key, {}) if rhythm_category_key else {}

                    # このセクション・パートの arrangement_override を取得
                    part_override_model = load_overrides.get_part_override(arrangement_overrides, sec_name, part_name) if arrangement_overrides else None


                    final_instrument_params = translate_and_merge_params_from_emotion_data(
                        processed_event_data=event_from_humanizer,
                        section_part_settings=sec_part_settings_overall.get(part_name, {}),
                        instrument_default_params_from_config=instrument_default_cfg,
                        instrument_name_key=part_name,
                        rhythm_library_for_instrument=rhythm_lib_for_instrument,
                        arrangement_override_for_part=part_override_model
                    )
                    blk_data["part_params"][part_name] = final_instrument_params
            
            stream_for_generators.append(blk_data)
            
    logger.info(f"Prepared {len(stream_for_generators)} blocks for generators.")
    return stream_for_generators

# ... (run_composition と main_cli は前回提案のものをベースに、
#      chordmap_data を processed_chordmap_data に置き換え、
#      prepare_stream_for_generators を呼び出すようにする) ...

def run_composition(cli_args: argparse.Namespace, main_cfg: Dict,
                    processed_chordmap_data: Dict, 
                    rhythm_lib_data: Dict):
    logger.info("=== Running Main Composition Workflow (with Emotion Humanizer data) ===")
    arrangement_overrides: OverrideModelType = OverrideModelType(root={}) # 空のOverridesモデルで初期化
    override_file_path_to_load: Optional[Path] = None

    if cli_args.overrides_file:
        override_file_path_to_load = cli_args.overrides_file
    elif Path("data/arrangement_overrides.json").exists(): # デフォルトパスもチェック
            override_file_path_to_load = Path("data/arrangement_overrides.json")
    elif Path("data/arrangement_overrides.yaml").exists():
            override_file_path_to_load = Path("data/arrangement_overrides.yaml")
    elif Path("data/arrangement_overrides.yml").exists():
            override_file_path_to_load = Path("data/arrangement_overrides.yml")

    if override_file_path_to_load:
        logger.info(f"Attempting to load overrides from: {override_file_path_to_load}")
        try:
            arrangement_overrides = load_overrides(str(override_file_path_to_load))
            logger.info(f"Successfully loaded arrangement overrides from: {override_file_path_to_load}")
        except Exception as e_load_ov:
            logger.error(f"Error loading overrides file {override_file_path_to_load}: {e_load_ov}. Proceeding without overrides.")
    else:
        logger.info("No overrides file specified or found at default locations. Proceeding without overrides.")

    g_settings_proc = processed_chordmap_data.get("global_settings", {})
    global_tempo_val = g_settings_proc.get("tempo", main_cfg["global_tempo"])
    global_ts_str = g_settings_proc.get("time_signature", main_cfg["global_time_signature"])
    global_key_tonic_val = g_settings_proc.get("key_tonic", main_cfg["global_key_tonic"])
    global_key_mode_val = g_settings_proc.get("key_mode", main_cfg["global_key_mode"])

    final_score = stream.Score()
    final_score.insert(0, tempo.MetronomeMark(number=global_tempo_val))
    ts_obj_score = get_time_signature_object(global_ts_str)
    final_score.insert(0, ts_obj_score if ts_obj_score else meter.TimeSignature("4/4"))
    final_score.insert(0, key.Key(global_key_tonic_val, global_key_mode_val.lower()))

    proc_blocks = prepare_stream_for_generators(processed_chordmap_data, main_cfg, rhythm_lib_data, arrangement_overrides)
    if not proc_blocks: logger.error("No blocks to process from processed_chordmap_data. Aborting."); return

    cv_inst = ChordVoicer(global_tempo=global_tempo_val, global_time_signature=global_ts_str)
    gens: Dict[str, Any] = {}

    for part_name, generate_flag in main_cfg.get("parts_to_generate", {}).items():
        if not generate_flag: continue
        part_default_cfg = main_cfg["default_part_parameters"].get(part_name, {})
        instrument_str = part_default_cfg.get("instrument", "Piano")
        rhythm_category_key: Optional[str] = None
        if part_name == "drums": rhythm_category_key = "drum_patterns"
        elif part_name == "bass": rhythm_category_key = "bass_patterns"
        elif part_name == "piano": rhythm_category_key = "piano_patterns"
        elif part_name == "guitar": rhythm_category_key = "guitar_patterns"
        elif part_name == "melody": rhythm_category_key = "melody_rhythms"
        
        rhythm_lib_for_instrument: Dict[str, Any] = rhythm_lib_data.get(rhythm_category_key, {}) if rhythm_category_key else {}
        
        instrument_obj = None
        try: instrument_obj = m21instrument.fromString(instrument_str)
        except: instrument_obj = m21instrument.Piano()

        if part_name == "piano": gens[part_name] = PianoGenerator(rhythm_library=rhythm_lib_for_instrument, chord_voicer_instance=cv_inst, default_instrument_rh=instrument_obj, default_instrument_lh=instrument_obj, global_tempo=global_tempo_val, global_time_signature=global_ts_str)
        elif part_name == "drums": gens[part_name] = DrumGenerator(lib=rhythm_lib_for_instrument, tempo_bpm=global_tempo_val, time_sig=global_ts_str)
        elif part_name == "guitar": gens[part_name] = GuitarGenerator(rhythm_library=rhythm_lib_for_instrument, default_instrument=instrument_obj, global_tempo=global_tempo_val, global_time_signature=global_ts_str)
        elif part_name == "bass": gens[part_name] = BassGenerator(rhythm_library=rhythm_lib_for_instrument, default_instrument=instrument_obj, global_tempo=global_tempo_val, global_time_signature=global_ts_str, global_key_tonic=global_key_tonic_val, global_key_mode=global_key_mode_val, rng_seed=main_cfg.get("rng_seed"))
        elif part_name == "melody": gens[part_name] = MelodyGenerator(rhythm_library=rhythm_lib_for_instrument, default_instrument=instrument_obj, global_tempo=global_tempo_val, global_time_signature=global_ts_str, global_key_signature_tonic=global_key_tonic_val, global_key_signature_mode=global_key_mode_val)
        elif part_name == "vocal":
            if main_cfg["parts_to_generate"].get("vocal"): gens[part_name] = VocalGenerator(default_instrument=instrument_obj, global_tempo=global_tempo_val, global_time_signature=global_ts_str)
        elif part_name == "chords":
            gens[part_name] = cv_inst
            if instrument_obj : cv_inst.default_instrument = instrument_obj
    
    for p_n, p_g_inst in gens.items():
        if p_g_inst and main_cfg["parts_to_generate"].get(p_n):
            logger.info(f"Generating {p_n} part using processed chord events...")
            try:
                part_obj: Optional[stream.Stream] = None
                if p_n == "vocal":
                    vocal_params_for_compose = proc_blocks[0]["part_params"].get("vocal") if proc_blocks else main_cfg["default_part_parameters"].get("vocal", {})
                    midivocal_data_for_compose_list : Optional[List[Dict]] = None; loaded_data = None
                    vocal_data_paths_call = main_cfg["default_part_parameters"].get("vocal", {}).get("data_paths", {})
                    midivocal_p_str_call = cli_args.vocal_mididata_path or vocal_data_paths_call.get("midivocal_data_path") # chordmap_dataはもうない
                    if midivocal_p_str_call:
                        loaded_data = load_json_file(Path(str(midivocal_p_str_call)), "Vocal MIDI Data for VocalGenerator.compose")
                    if isinstance(loaded_data, list): midivocal_data_for_compose_list = loaded_data

                    if midivocal_data_for_compose_list:
                        part_obj = p_g_inst.compose(
                            midivocal_data=midivocal_data_for_compose_list,
                            processed_chord_stream=proc_blocks,
                            humanize_opt=vocal_params_for_compose.get("humanize_opt", True),
                            humanize_template_name=vocal_params_for_compose.get("template_name"),
                            humanize_custom_params=vocal_params_for_compose.get("custom_params")
                        )
                    else: logger.warning(f"Vocal generation skipped: No MIDI data from '{midivocal_p_str_call}'."); continue
                else:
                    if hasattr(p_g_inst, "compose"):
                        sig = inspect.signature(p_g_inst.compose)
                        compose_args = [proc_blocks]
                        compose_kwargs = {}
                        if 'overrides' in sig.parameters: # arrangement_overrides を渡す
                             compose_kwargs['overrides'] = arrangement_overrides
                        if p_n == "guitar" and 'cli_guitar_style_override' in sig.parameters:
                            cli_guitar_style = getattr(cli_args, "guitar_style", None)
                            compose_kwargs['cli_guitar_style_override'] = cli_guitar_style
                        part_obj = p_g_inst.compose(*compose_args, **compose_kwargs)
                    else: logger.error(f"Generator for {p_n} does not have a compose method."); continue
                
                if isinstance(part_obj, stream.Score) and part_obj.parts:
                    for sub_part in part_obj.parts:
                        if sub_part.flatten().notesAndRests: final_score.insert(0, sub_part)
                elif isinstance(part_obj, stream.Part) and part_obj.flatten().notesAndRests: final_score.insert(0, part_obj)
            except Exception as e_gen: logger.error(f"Error in {p_n} generation: {e_gen}", exc_info=True)

    title = processed_chordmap_data.get("project_title","untitled").replace(" ","_").lower()
    out_fname_template = main_cfg.get("output_filename_template", "output_{song_title}.mid")
    actual_out_fname = cli_args.output_filename if cli_args.output_filename else out_fname_template.format(song_title=title)
    out_fpath = cli_args.output_dir / actual_out_fname; out_fpath.parent.mkdir(parents=True,exist_ok=True)
    try:
        if final_score.flatten().notesAndRests: final_score.write('midi',fp=str(out_fpath)); logger.info(f"🎉 MIDI exported to {out_fpath}")
        else: logger.warning(f"Score is empty. No MIDI file generated at {out_fpath}.")
    except Exception as e_w: logger.error(f"General MIDI write error to {out_fpath}: {e_w}", exc_info=True)


def main_cli():
    parser = argparse.ArgumentParser(description="Modular Music Composer with Emotion Humanizer")
    parser.add_argument("processed_chordmap_file", type=Path, help="Path to the processed_chordmap_with_emotion.yaml file.")
    parser.add_argument("rhythm_library_file", type=Path, help="Path to the rhythm library (JSON/YAML/TOML) file.")
    # ... (他の引数は変更なし) ...
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Directory to save the output MIDI file.")
    parser.add_argument("--output-filename", type=str, help="Custom filename for the output MIDI file.")
    parser.add_argument("--settings-file", type=Path, help="Path to a custom settings JSON file to override defaults.")
    parser.add_argument("--tempo", type=int, help="Override global tempo defined in processed chordmap or DEFAULT_CONFIG.")
    parser.add_argument("--vocal-mididata-path", type=str, help="Path to vocal MIDI data JSON (overrides config).")
    parser.add_argument("--rng-seed", type=int, help="Seed for random number generator for reproducibility.")
    parser.add_argument("--overrides-file", type=Path, help="Path to the arrangement overrides JSON file.")
    parser.add_argument("--guitar-style", type=str, help="Override guitar style/rhythm key for the entire song.")

    default_parts_cfg = DEFAULT_CONFIG.get("parts_to_generate", {})
    for part_key, default_enabled_status in default_parts_cfg.items():
        arg_name_for_part = f"generate_{part_key}"
        if default_enabled_status: parser.add_argument(f"--no-{part_key}", action="store_false", dest=arg_name_for_part, help=f"Disable {part_key} generation.")
        else: parser.add_argument(f"--include-{part_key}", action="store_true", dest=arg_name_for_part, help=f"Enable {part_key} generation.")
    arg_defaults = {f"generate_{k}": v for k, v in default_parts_cfg.items()}
    parser.set_defaults(**arg_defaults)
    args = parser.parse_args()
    effective_cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if args.settings_file and args.settings_file.exists():
        custom_settings_data = load_json_file(args.settings_file, "Custom settings") # settingsはJSONのまま
        if custom_settings_data and isinstance(custom_settings_data, dict):
            def _deep_update(target_dict, source_dict): # (変更なし)
                for key_item, value_item in source_dict.items():
                    if isinstance(value_item, dict) and key_item in target_dict and isinstance(target_dict[key_item], dict): _deep_update(target_dict[key_item], value_item)
                    else: target_dict[key_item] = value_item
            _deep_update(effective_cfg, custom_settings_data)

    for pk_name in default_parts_cfg.keys(): # (変更なし)
        arg_name_cli = f"generate_{pk_name}"
        if hasattr(args, arg_name_cli) and getattr(args, arg_name_cli) is not None:
            effective_cfg["parts_to_generate"][pk_name] = getattr(args, arg_name_cli)
    if args.vocal_mididata_path: # (変更なし)
        if "vocal" in effective_cfg["default_part_parameters"] and "data_paths" in effective_cfg["default_part_parameters"]["vocal"]:
            effective_cfg["default_part_parameters"]["vocal"]["data_paths"]["midivocal_data_path"] = str(args.vocal_mididata_path)
    if args.rng_seed is not None: # (変更なし)
        effective_cfg["rng_seed"] = args.rng_seed; random.seed(args.rng_seed)

    processed_chordmap_data_loaded = load_yaml_file(args.processed_chordmap_file, "Processed Chordmap with Emotion")
    
    logger.info(f"Loading rhythm library from: {args.rhythm_library_file}")
    try:
        rhythm_library_model = load_rhythm_lib_main_func(args.rhythm_library_file)
        if not rhythm_library_model or not rhythm_library_model.root:
            logger.critical("Rhythm library could not be loaded or is empty. Exit."); sys.exit(1)
        rhythm_library_data_loaded = rhythm_library_model.model_dump()
    except FileNotFoundError:
        logger.critical(f"Rhythm library file not found: {args.rhythm_library_file}. Exit."); sys.exit(1)
    except Exception as e_rhythm_load:
        logger.critical(f"Error loading rhythm library {args.rhythm_library_file}: {e_rhythm_load}. Exit.", exc_info=True); sys.exit(1)

    if not processed_chordmap_data_loaded or not rhythm_library_data_loaded:
        logger.critical("Data files (processed chordmap or rhythm library) missing or invalid after loading. Exit."); sys.exit(1)

    # グローバル設定は processed_chordmap_data から取得
    cm_globals_loaded = processed_chordmap_data_loaded.get("global_settings", {})
    effective_cfg["global_tempo"]=cm_globals_loaded.get("tempo",effective_cfg["global_tempo"])
    effective_cfg["global_time_signature"]=cm_globals_loaded.get("time_signature",effective_cfg["global_time_signature"])
    effective_cfg["global_key_tonic"]=cm_globals_loaded.get("key_tonic",effective_cfg["global_key_tonic"])
    effective_cfg["global_key_mode"]=cm_globals_loaded.get("key_mode",effective_cfg["global_key_mode"])
    if args.tempo is not None: effective_cfg["global_tempo"] = args.tempo
    
    logger.info(f"Final Effective Config (using processed chordmap): {json.dumps(effective_cfg, indent=2, ensure_ascii=False)}")
    try:
        run_composition(args, effective_cfg, processed_chordmap_data_loaded, rhythm_library_data_loaded)
    except SystemExit:
        raise
    except Exception as e_main_run:
        logger.critical(f"Critical error in main run: {e_main_run}", exc_info=True); sys.exit(1)

if __name__ == "__main__":
    main_cli()
# --- END OF FILE modular_composer.py ---