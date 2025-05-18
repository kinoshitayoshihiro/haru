# --- START OF FILE modular_composer.py (2023-05-18 14:00 JST 時点のGitHubの内容ベースで修正) ---

import json
import argparse
import logging
import random
import sys
from pathlib import Path
from music21 import stream, tempo, instrument as m21instrument, midi, meter, key
from typing import List, Dict, Optional, Any, cast, Sequence # Sequence を追加

# --- ジェネレータクラスのインポート (generatorフォルダから) ---
try:
    from generator.core_music_utils import get_time_signature_object # ★★★ これは modular_composer.py から使う ★★★
    from generator.piano_generator import PianoGenerator
    from generator.drum_generator import DrumGenerator
    from generator.chord_voicer import ChordVoicer
    from generator.melody_generator import MelodyGenerator
    # from generator.bass_core_generator.py か bass_generator.py かを明確にする必要あり ★★★
    # GitHubには両方あるので、どちらを使うかによります。ここでは仮に bass_core_generator を使います。
    from generator.bass_generator import BassGenerator
    # from generator.guitar_generator import GuitarGenerator # 必要に応じてコメント解除
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import generator modules from 'generator' package. "
          f"Ensure 'generator' directory is in the project root and contains __init__.py. Error: {e}")
    exit(1)
except Exception as e_imp:
    print(f"An unexpected error occurred during module import: {e_imp}")
    exit(1)

# --- ロガー設定 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("modular_composer")

# --- デフォルト設定 ---
DEFAULT_CONFIG = {
    "global_tempo": 100,
    "global_time_signature": "4/4",
    "global_key_tonic": "C",
    "global_key_mode": "major",
    "parts_to_generate": {
        "piano": True, "drums": True, "melody": True, "bass": True, "chords": True, "guitar": False
    },
    "default_part_parameters": {
        "piano": {
            "emotion_to_rh_style_keyword": { # 感情 -> 右手スタイルキーワード
                "struggle_with_underlying_strength": "reflective_arpeggio_rh",
                "deep_regret_and_gratitude": "chordal_moving_rh",
                "love_pain_acceptance_and_belief": "powerful_block_rh", # _chords_rh から変更例
                "default": "simple_block_rh"
            },
            "emotion_to_lh_style_keyword": { # 感情 -> 左手スタイルキーワード
                "struggle_with_underlying_strength": "gentle_root_lh",
                "deep_regret_and_gratitude": "walking_bass_like_lh",
                "love_pain_acceptance_and_belief": "active_octave_lh", # _bass_lh から変更例
                "default": "simple_root_lh"
            },
            "style_keyword_to_rhythm_key": { # スタイルキーワード -> リズムライブラリのキー
                "reflective_arpeggio_rh": "piano_flowing_arpeggio_eighths_rh",
                "chordal_moving_rh": "piano_chordal_moving_rh_pattern",
                "powerful_block_rh": "piano_powerful_block_8ths_rh",
                "simple_block_rh": "piano_block_quarters_simple",
                "gentle_root_lh": "piano_gentle_sustained_root_lh",
                "walking_bass_like_lh": "piano_gentle_walking_bass_quarters_lh",
                "active_octave_lh": "piano_active_octave_bass_lh",
                "simple_root_lh": "piano_lh_quarter_roots",
                "default_piano_rh_fallback_rhythm": "default_piano_quarters", # 以前のコードから。rhythm_libraryに定義要
                "default_piano_lh_fallback_rhythm": "piano_lh_whole_notes"    # 以前のコードから。rhythm_libraryに定義要
            },
            "intensity_to_velocity_ranges": { # ★★★ 構造変更 (LH_min, LH_max, RH_min, RH_max) ★★★
                "very_low":     (35, 45, 40, 50),
                "low":          (45, 55, 50, 60),
                "medium_low":   (55, 65, 60, 70),
                "medium":       (65, 75, 70, 80),
                "medium_high":  (75, 85, 80, 90),
                "high":         (85, 95, 90, 100),
                "very_high":    (95, 110, 100, 115),
                "default":      (60, 70, 65, 75) # フォールバックレンジ
            },
            "default_apply_pedal": True,
            "default_arp_note_ql": 0.5,
            "default_rh_voicing_style": "closed", # ★ 文字列リテラル ★
            "default_lh_voicing_style": "closed", # ★ 文字列リテラル ★
            "default_rh_target_octave": 4,
            "default_lh_target_octave": 2,
            "default_rh_num_voices": 3,
            "default_lh_num_voices": 1
        },
        "drums": {
            "emotion_to_style_key": {
                "struggle_with_underlying_strength": "ballad_soft_kick_snare_8th_hat",
                "deep_regret_and_gratitude": "rock_ballad_build_up_8th_hat",
                "love_pain_acceptance_and_belief": "anthem_rock_chorus_16th_hat",
                "default_style": "basic_rock_4_4" # ★ "no_drums" から変更 (存在しないキーになる可能性を避ける) ★
            },
            "intensity_to_base_velocity": { # ★★★ 単一の数値、または(min,max)タプルを想定 ★★★
                "very_low": 45, "low": 55, "medium_low": 65, "medium": 75,
                "medium_high": 85, "high": 95, "very_high": 105,
                "high_to_very_high_then_fade": (80,110), # 例: (start_vel, end_vel) これはカスタム処理が必要
                "default": 75
            },
            "default_fill_interval_bars": 4,
            "default_fill_keys": ["simple_snare_roll_half_bar", "chorus_end_fill"]
        },
        "chords": {
            "instrument": "StringInstrument",
            "chord_voicing_style": "closed", # ★ 文字列リテラル ★
            "chord_target_octave": 3,
            "chord_num_voices": 4,
            "chord_velocity": 64
        }
    },
    "output_filename_template": "output_{song_title}.mid"
}

def load_json_file(file_path: Path, description: str) -> Optional[Dict | List]:
    if not file_path.exists():
        logger.error(f"File not found: {description} at {file_path}")
        sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Successfully loaded {description} from: {file_path}")
        return data
    except json.JSONDecodeError as e_json:
        logger.error(f"Error decoding JSON from {description} at {file_path} (line {e_json.lineno} col {e_json.colno}): {e_json.msg}")
        sys.exit(1)
    except Exception as e_load:
        logger.error(f"Unexpected error loading {description} from {file_path}: {e_load}", exc_info=True)
        sys.exit(1)
    return None

def translate_keywords_to_params(
        musical_intent: Dict[str, Any],
        chord_block_specific_hints: Dict[str, Any],
        default_instrument_params: Dict[str, Any],
        instrument_name_key: str,
        rhythm_library: Dict # ★★★ rhythm_library を引数として受け取る ★★★
) -> Dict[str, Any]:
    params: Dict[str, Any] = default_instrument_params.copy()
    emotion_key = musical_intent.get("emotion", "neutral").lower()
    intensity_key = musical_intent.get("intensity", "medium").lower()
    section_instrument_settings = chord_block_specific_hints.get("part_settings", {}).get(instrument_name_key, {})
    params.update(section_instrument_settings)

    logger.debug(
        f"Translating for {instrument_name_key}: Emo='{emotion_key}', Int='{intensity_key}', "
        f"SectionSet='{section_instrument_settings}', BlkHints='{chord_block_specific_hints}'"
    )

    if instrument_name_key == "piano":
        cfg_piano = default_instrument_params

        rh_style_kw = params.get("piano_rh_style_keyword",
                        cfg_piano.get("emotion_to_rh_style_keyword", {}).get(emotion_key,
                                        cfg_piano.get("emotion_to_rh_style_keyword", {}).get("default")))
        params["piano_rh_style_keyword"] = rh_style_kw

        lh_style_kw = params.get("piano_lh_style_keyword",
                        cfg_piano.get("emotion_to_lh_style_keyword", {}).get(emotion_key,
                                        cfg_piano.get("emotion_to_lh_style_keyword", {}).get("default")))
        params["piano_lh_style_keyword"] = lh_style_kw

        style_to_rhythm_map = cfg_piano.get("style_keyword_to_rhythm_key", {})
        piano_patterns_from_lib = rhythm_library.get("piano_patterns", {}) # ★★★ rhythm_library を使用 ★★★

        params["piano_rh_rhythm_key"] = style_to_rhythm_map.get(rh_style_kw)
        if not params["piano_rh_rhythm_key"] or params.get("piano_rh_rhythm_key") not in piano_patterns_from_lib:
             fallback_rh_key = style_to_rhythm_map.get("default_piano_rh_fallback_rhythm", "default_piano_quarters")
             logger.warning(f"Piano RH rhythm key '{params.get('piano_rh_rhythm_key')}' for style '{rh_style_kw}' not in lib. Using fallback '{fallback_rh_key}'.")
             params["piano_rh_rhythm_key"] = fallback_rh_key

        params["piano_lh_rhythm_key"] = style_to_rhythm_map.get(lh_style_kw)
        if not params["piano_lh_rhythm_key"] or params.get("piano_lh_rhythm_key") not in piano_patterns_from_lib:
             fallback_lh_key = style_to_rhythm_map.get("default_piano_lh_fallback_rhythm", "piano_lh_whole_notes")
             logger.warning(f"Piano LH rhythm key '{params.get('piano_lh_rhythm_key')}' for style '{lh_style_kw}' not in lib. Using fallback '{fallback_lh_key}'.")
             params["piano_lh_rhythm_key"] = fallback_lh_key

        vel_map = cfg_piano.get("intensity_to_velocity_ranges", {}) # ★★★ このキー名に統一 ★★★
        default_vel_tuple = vel_map.get("default", (60, 70, 65, 75)) # (lh_min, lh_max, rh_min, rh_max)
        # ★★★ ベロシティ取得ロジック修正 ★★★
        try:
            lh_min_cfg, lh_max_cfg, rh_min_cfg, rh_max_cfg = vel_map.get(intensity_key, default_vel_tuple)
            params["piano_velocity_lh"] = random.randint(lh_min_cfg, lh_max_cfg)
            params["piano_velocity_rh"] = random.randint(rh_min_cfg, rh_max_cfg)
        except (TypeError, ValueError, IndexError): # タプルの形式が不正な場合などのフォールバック
            logger.warning(f"Invalid velocity range format for piano intensity '{intensity_key}'. Using defaults.")
            params["piano_velocity_lh"] = random.randint(default_vel_tuple[0], default_vel_tuple[1])
            params["piano_velocity_rh"] = random.randint(default_vel_tuple[2], default_vel_tuple[3])


        for p_key_suffix in ["apply_pedal", "arp_note_ql", "rh_voicing_style", "lh_voicing_style", "rh_target_octave", "lh_target_octave", "rh_num_voices", "lh_num_voices"]:
            param_name_full = f"piano_{p_key_suffix}"
            default_param_key_in_cfg = f"default_{p_key_suffix}"
            params[param_name_full] = params.get(param_name_full, cfg_piano.get(default_param_key_in_cfg))

    elif instrument_name_key == "drums":
        cfg_drums = default_instrument_params
        style_key_from_emotion = cfg_drums.get("emotion_to_style_key", {}).get(emotion_key,
                                   cfg_drums.get("emotion_to_style_key", {}).get("default_style"))
        params["drum_style_key"] = params.get("drum_style_key", style_key_from_emotion)
        
        drum_patterns_from_lib = rhythm_library.get("drum_patterns", {}) # ★★★ rhythm_library を使用 ★★★
        if not params["drum_style_key"] or params.get("drum_style_key") not in drum_patterns_from_lib:
            logger.warning(f"Drum style key '{params.get('drum_style_key')}' not found in drum_patterns. Using 'default_drum_pattern'.")
            params["drum_style_key"] = "default_drum_pattern" # 確実に存在する想定のキー

        vel_map_drums = cfg_drums.get("intensity_to_base_velocity", {})
        default_drum_vel = vel_map_drums.get("default", 75) # ★★★ 設定からのデフォルトベロシティ取得 ★★★
        vel_base_val = params.get("drum_base_velocity", vel_map_drums.get(intensity_key, default_drum_vel))

        if isinstance(vel_base_val, tuple) and len(vel_base_val) == 2:
            params["drum_base_velocity"] = random.randint(vel_base_val[0], vel_base_val[1])
        else:
            params["drum_base_velocity"] = int(vel_base_val)
        
        params["drum_fill_interval_bars"] = params.get("drum_fill_interval_bars", cfg_drums.get("default_fill_interval_bars"))
        params["drum_fill_keys"] = params.get("drum_fill_keys", cfg_drums.get("default_fill_keys"))

    block_instrument_hints = chord_block_specific_hints.get("part_specific_hints", {}).get(instrument_name_key, {})
    params.update(block_instrument_hints)
    if instrument_name_key == "drums" and "drum_fill" in chord_block_specific_hints:
        params["drum_fill_key_override"] = chord_block_specific_hints["drum_fill"]
    logger.info(f"Translated params for [{instrument_name_key}] (Emo: {emotion_key}, Int: {intensity_key}) -> {params}")
    return params

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_lib: Dict) -> List[Dict]:
    processed_stream: List[Dict] = []
    current_abs_offset: float = 0.0
    global_settings = chordmap_data.get("global_settings", {})
    time_sig_str = global_settings.get("time_signature", main_config["global_time_signature"])
    ts_obj = get_time_signature_object(time_sig_str) # ★★★ get_time_signature_object を使用 ★★★
    beats_per_measure = ts_obj.barDuration.quarterLength
    global_key_tonic = global_settings.get("key_tonic", main_config["global_key_tonic"])
    global_key_mode = global_settings.get("key_mode", main_config["global_key_mode"])

    sorted_sections = sorted(chordmap_data.get("sections", {}).items(), key=lambda item: item[1].get("order", float('inf')))

    for section_name, sec_info in sorted_sections:
        logger.info(f"Preparing blocks for section: {section_name}")
        sec_musical_intent = sec_info.get("musical_intent", {})
        sec_part_settings = sec_info.get("part_settings", {})
        sec_tonic = sec_info.get("tonic", global_key_tonic); sec_mode = sec_info.get("mode", global_key_mode)
        sec_len_measures = sec_info.get("length_in_measures")
        chord_prog = sec_info.get("chord_progression", [])
        if not chord_prog: logger.warning(f"Section '{section_name}' no chords. Skip."); continue

        for chord_idx, chord_def in enumerate(chord_prog):
            chord_lbl = chord_def.get("label", "C")
            dur_b = float(chord_def["duration_beats"]) if "duration_beats" in chord_def else (float(sec_len_measures) * beats_per_measure) / len(chord_prog) if sec_len_measures and chord_prog else beats_per_measure
            blk_intent = sec_musical_intent.copy()
            if "emotion" in chord_def: blk_intent["emotion"] = chord_def["emotion"]
            if "intensity" in chord_def: blk_intent["intensity"] = chord_def["intensity"]
            blk_hints = {k:v for k,v in chord_def.items() if k not in ["label","duration_beats","order","musical_intent","part_settings","tensions_to_add"]}
            blk_hints["part_settings"] = sec_part_settings
            blk_data = {"offset":current_abs_offset, "q_length":dur_b, "chord_label":chord_lbl, "section_name":section_name,
                        "tonic_of_section":sec_tonic, "mode":sec_mode, "tensions_to_add":chord_def.get("tensions_to_add",[]),
                        "is_first_in_section":(chord_idx==0), "is_last_in_section":(chord_idx==len(chord_prog)-1), "part_params":{}}
            for p_name_key in main_config["parts_to_generate"].keys(): # enabled/disabledに関わらずパラメータは準備
                def_params = main_config["default_part_parameters"].get(p_name_key, {})
                blk_data["part_params"][p_name_key] = translate_keywords_to_params(
                    blk_intent, blk_hints, def_params, p_name_key,
                    rhythm_lib # ★★★ rhythm_lib を渡す ★★★
                )
            processed_stream.append(blk_data)
            current_abs_offset += dur_b
    logger.info(f"Prepared {len(processed_stream)} blocks. Total duration: {current_abs_offset:.2f} beats.")
    return processed_stream

def run_composition(cli_args: argparse.Namespace, main_config: Dict, chordmap_data: Dict, rhythm_library_data: Dict):
    logger.info("=== Running Main Composition Workflow ===")
    final_score = stream.Score()
    final_score.insert(0, tempo.MetronomeMark(number=main_config["global_tempo"]))
    try:
        ts_obj_score = get_time_signature_object(main_config["global_time_signature"]) # ★★★ get_time_signature_object を使用 ★★★
        final_score.insert(0, ts_obj_score)
        key_t, key_m = main_config["global_key_tonic"], main_config["global_key_mode"]
        if chordmap_data.get("sections"):
            try:
                first_sec_name = sorted(chordmap_data.get("sections", {}).keys(), key=lambda k_s: chordmap_data["sections"][k_s].get("order",float('inf')))[0]
                first_sec_info = chordmap_data.get("sections",{})[first_sec_name]
                key_t = first_sec_info.get("tonic",key_t)
                key_m = first_sec_info.get("mode",key_m)
            except IndexError: logger.warning("No sections for initial key, using global.")
        final_score.insert(0, key.Key(key_t, key_m.lower()))
    except Exception as e: logger.error(f"Error setting globals on score: {e}. Defaults used.", exc_info=True); final_score.insert(0,meter.TimeSignature("4/4")); final_score.insert(0,key.Key("C"))

    proc_blocks = prepare_processed_stream(chordmap_data, main_config, rhythm_library_data) # ★★★ rhythm_library_data を渡す ★★★
    if not proc_blocks: logger.error("No blocks to process. Aborting."); return

    active_cv = ChordVoicer(global_tempo=main_config["global_tempo"], global_time_signature=main_config["global_time_signature"])
    gens: Dict[str, Any] = {}
    if main_config["parts_to_generate"].get("piano"): gens["piano"] = PianoGenerator(cast(Dict[str,Dict],rhythm_library_data.get("piano_patterns", {})), active_cv, main_config["global_tempo"], main_config["global_time_signature"])
    if main_config["parts_to_generate"].get("drums"): gens["drums"] = DrumGenerator(cast(Dict[str,Dict[str,Any]],rhythm_library_data.get("drum_patterns")), global_tempo=main_config["global_tempo"], global_time_signature=main_config["global_time_signature"])
    if main_config["parts_to_generate"].get("chords"): gens["chords"] = active_cv
    if main_config["parts_to_generate"].get("melody"):
        gens["melody"] = MelodyGenerator(
            rhythm_library=cast(Dict[str,Dict], rhythm_library_data.get("melody_rhythms", {})), # メロディ用のリズムライブラリカテゴリキー
            global_tempo=main_config["global_tempo"],
            global_time_signature=main_config["global_time_signature"],
            global_key_signature_tonic=main_config["global_key_tonic"],
            global_key_signature_mode=main_config["global_key_mode"]
        )
    if main_config["parts_to_generate"].get("bass"):
        gens["bass"] = BassCoreGenerator( # または BassGenerator
            rhythm_library=cast(Dict[str,Dict], rhythm_library_data.get("bass_lines", {})), # ベース用のリズムライブラリカテゴリキー
            global_tempo=main_config["global_tempo"],
            global_time_signature=main_config["global_time_signature"]
        )


    for p_name, p_gen_inst in gens.items():
        if p_gen_inst:
            logger.info(f"Generating {p_name} part...")
            try:
                if p_name == "piano" and isinstance(p_gen_inst, PianoGenerator):
                    p_score = p_gen_inst.compose(proc_blocks)
                    if p_score and p_score.parts: [final_score.insert(0,pt) for pt in p_score.parts]
                elif p_name == "chords" and isinstance(p_gen_inst, ChordVoicer):
                    # ChordVoicerのcomposeはprocessed_blocksのみ受け取る想定に修正
                    cv_part = p_gen_inst.compose(proc_blocks)
                    if cv_part and cv_part.flatten().notesAndRests: final_score.insert(0, cv_part)
                elif hasattr(p_gen_inst, "compose"): # 他のジェネレータ
                    gen_part = p_gen_inst.compose(proc_blocks)
                    if gen_part and gen_part.flatten().notesAndRests: final_score.insert(0, gen_part)
                logger.info(f"{p_name} part generated.")
            except Exception as e_gen: logger.error(f"Error in {p_name} generation: {e_gen}", exc_info=True)

    title = chordmap_data.get("project_title", "untitled").replace(" ","_").lower()
    out_fname_from_template = main_config["output_filename_template"].format(song_title=title)
    # コマンドラインで指定されたファイル名を優先
    actual_out_fname = cli_args.output_filename if cli_args.output_filename else out_fname_from_template
    out_p = cli_args.output_dir / actual_out_fname

    out_p.parent.mkdir(parents=True, exist_ok=True)
    try:
        if final_score.flatten().notesAndRests: final_score.write('midi', fp=str(out_p)); logger.info(f"🎉 MIDI: {out_p}")
        else: logger.warning(f"Final score empty. No MIDI written to {out_p}.")
    except Exception as e_write: logger.error(f"MIDI write error: {e_write}", exc_info=True)

def main_cli():
    parser = argparse.ArgumentParser(description="Modular Music Composer (Keyword-Driven v3)")
    parser.add_argument("chordmap_file", type=Path, help="Path to chordmap JSON.")
    parser.add_argument("rhythm_library_file", type=Path, help="Path to rhythm_library JSON.")
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Output directory for MIDI.")
    parser.add_argument("--output-filename", type=str, help="Output MIDI filename (optional).") # 出力ファイル名をオプションに
    parser.add_argument("--settings-file", type=Path, help="Custom settings JSON (optional).")
    parser.add_argument("--tempo", type=int, help="Override global tempo.")
    
    default_parts = DEFAULT_CONFIG.get("parts_to_generate", {})
    for pk, state in default_parts.items():
        arg_dest = f"generate_{pk}"
        if state: parser.add_argument(f"--no-{pk}", action="store_false", dest=arg_dest, help=f"Disable {pk}.")
        else: parser.add_argument(f"--include-{pk}", action="store_true", dest=arg_dest, help=f"Enable {pk}.")
    # set_defaultsで引数が指定されなかった場合のデフォルト値を設定
    parser.set_defaults(**{f"generate_{k}": v for k,v in default_parts.items()})

    args = parser.parse_args()
    config = DEFAULT_CONFIG.copy() # deepcopy がより安全
    if args.settings_file and args.settings_file.exists():
        custom_cfg = load_json_file(args.settings_file, "Custom settings")
        if custom_cfg and isinstance(custom_cfg, dict):
            def merge_dicts(base, new):
                for k,v_n in new.items():
                    if isinstance(v_n,dict) and k in base and isinstance(base[k],dict): merge_dicts(base[k],v_n)
                    else: base[k] = v_n
            merge_dicts(config, custom_cfg)

    if args.tempo is not None: config["global_tempo"] = args.tempo
    for pk in config.get("parts_to_generate",{}).keys():
        arg_name = f"generate_{pk}" # ここは generate_{pk} のまま
        if hasattr(args, arg_name): # 引数が存在するか確認
             config["parts_to_generate"][pk] = getattr(args, arg_name)


    chordmap = load_json_file(args.chordmap_file, "Chordmap")
    rhythm_lib = load_json_file(args.rhythm_library_file, "Rhythm Library")
    if not chordmap or not rhythm_lib: logger.critical("Data files missing. Exit."); sys.exit(1) # ★ エラー終了

    cm_globals = chordmap.get("global_settings", {})
    # ★★★ グローバル設定キー名の修正 ★★★
    config["global_tempo"] = cm_globals.get("tempo", config["global_tempo"])
    config["global_time_signature"] = cm_globals.get("time_signature", config["global_time_signature"])
    config["global_key_tonic"] = cm_globals.get("key_tonic", config["global_key_tonic"])
    config["global_key_mode"] = cm_globals.get("key_mode", config["global_key_mode"])
    
    logger.info(f"Final effective config: {json.dumps(config, indent=2, ensure_ascii=False)}")
    try: run_composition(args, config, cast(Dict,chordmap), cast(Dict,rhythm_lib))
    except Exception as e_run: logger.critical(f"Critical error in run_composition: {e_run}", exc_info=True); sys.exit(1)

if __name__ == "__main__":
    main_cli()

# --- END OF FILE modular_composer.py ---
