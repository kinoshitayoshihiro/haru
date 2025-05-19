# --- START OF FILE modular_composer.py (2023-05-20 時点の包括的修正案) ---
import music21
import sys
import os
import json
import argparse
import logging
from music21 import stream, tempo, instrument as m21instrument, midi, meter, key
from pathlib import Path
from typing import List, Dict, Optional, Any, cast, Sequence # Sequence をインポート
import random

# --- ジェネレータクラスのインポート (generatorフォルダから) ---
try:
    from generator.core_music_utils import get_time_signature_object
    from generator.piano_generator import PianoGenerator
    from generator.drum_generator import DrumGenerator
    from generator.chord_voicer import ChordVoicer
    from generator.melody_generator import MelodyGenerator
    from generator.bass_generator import BassGenerator # ★ BassGenerator をインポート
    # from generator.guitar_generator import GuitarGenerator # 必要に応じて
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import generator modules from 'generator' package. "
          f"Ensure 'generator' directory is in the project root and contains __init__.py. Error: {e}")
    exit(1)
except Exception as e_imp:
    print(f"An unexpected error occurred during module import: {e_imp}")
    exit(1)

# --- ロガー設定 ---
logging.basicConfig(
    level=logging.INFO, # デバッグ時は logging.DEBUG に変更するとより詳細なログが出ます
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
        "piano": True, "drums": True, "melody": False, "bass": False, "chords": True, "guitar": False
    },
    "default_part_parameters": {
        "piano": {
            "emotion_to_rh_style_keyword": {
                "struggle_with_underlying_strength": "reflective_arpeggio_rh",
                "deep_regret_and_gratitude": "chordal_moving_rh",
                "love_pain_acceptance_and_belief": "powerful_block_rh",
                "default": "simple_block_rh"
            },
            "emotion_to_lh_style_keyword": {
                "struggle_with_underlying_strength": "gentle_sustained_root_lh", # ★キー名変更の可能性
                "deep_regret_and_gratitude": "walking_bass_like_lh",
                "love_pain_acceptance_and_belief": "active_octave_bass_lh", # ★キー名変更の可能性
                "default": "simple_root_lh"
            },
            "style_keyword_to_rhythm_key": {
                # ★★★これらの値が rhythm_library.json の piano_patterns のキーと一致していること★★★
                "reflective_arpeggio_rh": "piano_flowing_arpeggio_eighths_rh",
                "chordal_moving_rh": "piano_chordal_moving_rh_pattern",
                "powerful_block_rh": "piano_powerful_block_8ths_rh",
                "simple_block_rh": "piano_block_quarters_simple",
                "gentle_sustained_root_lh": "piano_sustained_root_lh", # ★ rhythm_library.json側のキーに合わせる
                "walking_bass_like_lh": "piano_walking_bass_like_lh",
                "active_octave_bass_lh": "piano_active_octave_bass_lh",
                "simple_root_lh": "piano_lh_quarter_roots",
                "default_piano_rh_fallback_rhythm": "default_piano_quarters",
                "default_piano_lh_fallback_rhythm": "piano_lh_whole_notes"
            },
            "intensity_to_velocity_ranges": { # (LH_min, LH_max, RH_min, RH_max)
                "low": (50, 60, 55, 65), "medium_low": (55, 65, 60, 70),
                "medium": (60, 70, 65, 75), "medium_high": (65, 80, 70, 85),
                "high": (70, 85, 75, 90), "default": (60, 70, 65, 75)
            },
            "default_apply_pedal": True, "default_arp_note_ql": 0.5,
            "default_rh_voicing_style": "closed", "default_lh_voicing_style": "closed",
            "default_rh_target_octave": 4, "default_lh_target_octave": 2,
            "default_rh_num_voices": 3, "default_lh_num_voices": 1
        },
        "drums": {
            "emotion_to_style_key": {
                # ★★★これらの値が rhythm_library.json の drum_patterns のキーと一致していること★★★
                "struggle_with_underlying_strength": "ballad_soft_kick_snare_8th_hat",
                "deep_regret_and_gratitude": "rock_ballad_build_up_8th_hat",
                "love_pain_acceptance_and_belief": "anthem_rock_chorus_16th_hat",
                "default_style": "default_drum_pattern" # ★ rhythm_library.json にこのキーが存在することを確認 ★
            },
            "intensity_to_base_velocity": {"default": 75, "low": 60, "medium": 75, "high": 90},
            "default_fill_interval_bars": 4,
            "default_fill_keys": ["simple_snare_roll_half_bar", "chorus_end_fill"]
        },
        "chords": {
            "instrument": "StringInstrument", "chord_voicing_style": "closed",
            "chord_target_octave": 3, "chord_num_voices": 4, "chord_velocity": 64
        },
        "melody": { # メロディ用のデフォルト（rhythm_libraryにも対応定義が必要）
            "instrument": "Flute", "rhythm_key": "default_melody_rhythm",
            "octave_range": [4, 5], "density": 0.7
        },
        "bass": { # ベース用のデフォルト（rhythm_libraryにも対応定義が必要）
            "instrument": "AcousticBass", "style": "simple_roots",
            "rhythm_key": "bass_quarter_notes"
        }
    },
    "output_filename_template": "output_{song_title}.mid"
}

def load_json_file(file_path: Path, description: str) -> Optional[Dict | List]:
    if not file_path.exists():
        logger.error(f"{description} file not found at: {file_path}")
        sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
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
        musical_intent: Dict[str, Any], chord_block_specific_hints: Dict[str, Any],
        default_instrument_params: Dict[str, Any], instrument_name_key: str,
        rhythm_library_all_categories: Dict # ★ 全体のrhythm_libraryを渡す ★
) -> Dict[str, Any]:
    params: Dict[str, Any] = default_instrument_params.copy()
    emotion_key = musical_intent.get("emotion", "neutral").lower()
    intensity_key = musical_intent.get("intensity", "medium").lower()
    section_instrument_settings = chord_block_specific_hints.get("part_settings", {}).get(instrument_name_key, {})
    params.update(section_instrument_settings) # セクション設定でまず上書き

    logger.debug(f"Translating for {instrument_name_key}: Emo='{emotion_key}', Int='{intensity_key}', InitialParams='{params}'")

    if instrument_name_key == "piano":
        cfg_piano = default_instrument_params
        # emotion/intensity からスタイルキーワード等を選択 (paramsがセクション設定で上書きされている可能性あり)
        rh_style_kw = params.get("piano_rh_style_keyword", cfg_piano.get("emotion_to_rh_style_keyword", {}).get(emotion_key, cfg_piano.get("emotion_to_rh_style_keyword", {}).get("default")))
        params["piano_rh_style_keyword"] = rh_style_kw # 確定値を格納
        lh_style_kw = params.get("piano_lh_style_keyword", cfg_piano.get("emotion_to_lh_style_keyword", {}).get(emotion_key, cfg_piano.get("emotion_to_lh_style_keyword", {}).get("default")))
        params["piano_lh_style_keyword"] = lh_style_kw

        style_to_rhythm_map = cfg_piano.get("style_keyword_to_rhythm_key", {})
        piano_patterns_from_lib = rhythm_library_all_categories.get("piano_patterns", {}) # ★ piano_patternsカテゴリを参照 ★

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

        vel_map_piano = cfg_piano.get("intensity_to_velocity_ranges", {}) # ★ キー名修正 ★
        default_vel_tuple_piano = vel_map_piano.get("default", (60, 70, 65, 75))
        current_vel_tuple_piano = vel_map_piano.get(intensity_key, default_vel_tuple_piano)
        if isinstance(current_vel_tuple_piano, Sequence) and len(current_vel_tuple_piano) == 4:
            params["piano_velocity_lh"] = random.randint(current_vel_tuple_piano[0], current_vel_tuple_piano[1])
            params["piano_velocity_rh"] = random.randint(current_vel_tuple_piano[2], current_vel_tuple_piano[3])
        else:
            logger.warning(f"Piano velocity range for intensity '{intensity_key}' is not a 4-element tuple. Using defaults from tuple.")
            params["piano_velocity_lh"] = random.randint(default_vel_tuple_piano[0], default_vel_tuple_piano[1])
            params["piano_velocity_rh"] = random.randint(default_vel_tuple_piano[2], default_vel_tuple_piano[3])

        for p_key_suffix_piano in ["apply_pedal", "arp_note_ql", "rh_voicing_style", "lh_voicing_style", "rh_target_octave", "lh_target_octave", "rh_num_voices", "lh_num_voices"]:
            param_name_full_piano = f"piano_{p_key_suffix_piano}"
            default_param_key_in_cfg_piano = f"default_{p_key_suffix_piano}"
            params[param_name_full_piano] = params.get(param_name_full_piano, cfg_piano.get(default_param_key_in_cfg_piano))

    elif instrument_name_key == "drums":
        cfg_drums = default_instrument_params
        style_key_from_emotion = cfg_drums.get("emotion_to_style_key", {}).get(emotion_key, cfg_drums.get("emotion_to_style_key", {}).get("default_style"))
        params["drum_style_key"] = params.get("drum_style_key", style_key_from_emotion)
        
        drum_patterns_from_lib = rhythm_library_all_categories.get("drum_patterns", {}) # ★ drum_patternsカテゴリを参照 ★
        if not params["drum_style_key"] or params.get("drum_style_key") not in drum_patterns_from_lib:
            logger.warning(f"Drum style key '{params.get('drum_style_key')}' not in drum_patterns. Using 'default_drum_pattern'.")
            params["drum_style_key"] = "default_drum_pattern"

        vel_map_drums = cfg_drums.get("intensity_to_base_velocity", {})
        default_drum_vel = vel_map_drums.get("default", 75)
        vel_base_val_drums = params.get("drum_base_velocity", vel_map_drums.get(intensity_key, default_drum_vel))
        params["drum_base_velocity"] = int(random.randint(vel_base_val_drums[0],vel_base_val_drums[1])) if isinstance(vel_base_val_drums,tuple) and len(vel_base_val_drums)==2 else int(vel_base_val_drums)
        
        params["drum_fill_interval_bars"] = params.get("drum_fill_interval_bars", cfg_drums.get("default_fill_interval_bars"))
        params["drum_fill_keys"] = params.get("drum_fill_keys", cfg_drums.get("default_fill_keys"))
    
    # 他の楽器のパラメータ変換 (melody, bass)
    elif instrument_name_key == "melody":
        cfg_melody = default_instrument_params
        # ★ melody_rhythms カテゴリを参照 ★
        melody_rhythms_lib = rhythm_library_all_categories.get("melody_rhythms", {})
        # 例: 感情からリズムキーを選択
        rhythm_key_map_melody = cfg_melody.get("rhythm_key_map", {})
        params["rhythm_key"] = params.get("rhythm_key", rhythm_key_map_melody.get(emotion_key, rhythm_key_map_melody.get("default")))
        if not params["rhythm_key"] or params.get("rhythm_key") not in melody_rhythms_lib:
            logger.warning(f"Melody rhythm key '{params.get('rhythm_key')}' not in melody_rhythms. Using default.")
            params["rhythm_key"] = "default_melody_rhythm" # rhythm_library.jsonに定義が必要

        params["octave_range"] = params.get("octave_range", cfg_melody.get("octave_range"))
        params["density"] = params.get("density", cfg_melody.get("density"))

    elif instrument_name_key == "bass":
        cfg_bass = default_instrument_params
        # ★ bass_lines カテゴリを参照 ★
        bass_lines_lib = rhythm_library_all_categories.get("bass_lines", {})
        params["style"] = params.get("style", cfg_bass.get("style_map",{}).get(emotion_key, cfg_bass.get("style_map",{}).get("default"))) # これはBassGenerator内部で解釈
        rhythm_key_map_bass = cfg_bass.get("rhythm_key_map", {})
        params["rhythm_key"] = params.get("rhythm_key", rhythm_key_map_bass.get(emotion_key, rhythm_key_map_bass.get("default")))
        if not params["rhythm_key"] or params.get("rhythm_key") not in bass_lines_lib:
            logger.warning(f"Bass rhythm key '{params.get('rhythm_key')}' not in bass_lines. Using default.")
            params["rhythm_key"] = "bass_quarter_notes" # rhythm_library.jsonに定義が必要


    block_instrument_hints = chord_block_specific_hints.get("part_specific_hints", {}).get(instrument_name_key, {})
    params.update(block_instrument_hints)
    if instrument_name_key == "drums" and "drum_fill" in chord_block_specific_hints:
        params["drum_fill_key_override"] = chord_block_specific_hints["drum_fill"]
    logger.info(f"Final params for [{instrument_name_key}] (Emo: {emotion_key}, Int: {intensity_key}) -> {params}")
    return params

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_lib_all: Dict) -> List[Dict]: # ★ 引数名変更
    processed_stream: List[Dict] = []
    current_abs_offset: float = 0.0
    g_settings = chordmap_data.get("global_settings", {})
    ts_str = g_settings.get("time_signature", main_config["global_time_signature"])
    ts_obj = get_time_signature_object(ts_str)
    beats_per_measure = ts_obj.barDuration.quarterLength
    g_key_t, g_key_m = g_settings.get("key_tonic", main_config["global_key_tonic"]), g_settings.get("key_mode", main_config["global_key_mode"])

    sorted_sections = sorted(chordmap_data.get("sections", {}).items(), key=lambda item: item[1].get("order", float('inf')))
    for sec_name, sec_info in sorted_sections:
        logger.info(f"Preparing section: {sec_name}")
        sec_intent = sec_info.get("musical_intent", {})
        sec_part_set = sec_info.get("part_settings", {})
        sec_t, sec_m = sec_info.get("tonic", g_key_t), sec_info.get("mode", g_key_m)
        sec_len_meas = sec_info.get("length_in_measures")
        chord_prog = sec_info.get("chord_progression", [])
        if not chord_prog: logger.warning(f"Section '{sec_name}' no chords. Skip."); continue

        for c_idx, c_def in enumerate(chord_prog):
            c_lbl = c_def.get("label", "C")
            dur_b = float(c_def["duration_beats"]) if "duration_beats" in c_def else (float(sec_len_meas) * beats_per_measure) / len(chord_prog) if sec_len_meas and chord_prog else beats_per_measure
            blk_intent = sec_intent.copy()
            if "emotion" in c_def: blk_intent["emotion"] = c_def["emotion"]
            if "intensity" in c_def: blk_intent["intensity"] = c_def["intensity"]
            blk_hints = {k:v for k,v in c_def.items() if k not in ["label","duration_beats","order","musical_intent","part_settings","tensions_to_add"]}
            blk_hints["part_settings"] = sec_part_set
            blk_data = {"offset":current_abs_offset, "q_length":dur_b, "chord_label":c_lbl, "section_name":sec_name,
                        "tonic_of_section":sec_t, "mode":sec_m, "tensions_to_add":c_def.get("tensions_to_add",[]),
                        "is_first_in_section":(c_idx==0), "is_last_in_section":(c_idx==len(chord_prog)-1), "part_params":{}}
            for p_key_name in main_config["parts_to_generate"].keys():
                def_p = main_config["default_part_parameters"].get(p_key_name, {})
                # ★ translate_keywords_to_params に rhythm_lib_all を渡す ★
                blk_data["part_params"][p_key_name] = translate_keywords_to_params(blk_intent, blk_hints, def_p, p_key_name, rhythm_lib_all)
            processed_stream.append(blk_data)
            current_abs_offset += dur_b
    logger.info(f"Prepared {len(processed_stream)} blocks. Duration: {current_abs_offset:.2f} beats.")
    return processed_stream

def run_composition(cli_args: argparse.Namespace, main_cfg: Dict, chordmap: Dict, rhythm_lib_all: Dict):
    logger.info("=== Running Main Composition Workflow ===")
    final_score = stream.Score()
    final_score.insert(0, tempo.MetronomeMark(number=main_cfg["global_tempo"]))
    try:
        ts_obj_score = get_time_signature_object(main_cfg["global_time_signature"])
        final_score.insert(0, ts_obj_score)
        key_t, key_m = main_cfg["global_key_tonic"], main_cfg["global_key_mode"]
        if chordmap.get("sections"):
            try:
                first_sec_name = sorted(chordmap.get("sections", {}).keys(), key=lambda k_s: chordmap["sections"][k_s].get("order",float('inf')))[0]
                first_sec_info = chordmap.get("sections",{})[first_sec_name]
                key_t = first_sec_info.get("tonic",key_t)
                key_m = first_sec_info.get("mode",key_m)
            except IndexError: logger.warning("No sections for initial key.")
        final_score.insert(0, key.Key(key_t, key_m.lower()))
    except Exception as e: logger.error(f"Error setting score globals: {e}. Defaults.", exc_info=True); final_score.insert(0,meter.TimeSignature("4/4")); final_score.insert(0,key.Key("C"))

    proc_blocks = prepare_processed_stream(chordmap, main_cfg, rhythm_lib_all)
    if not proc_blocks: logger.error("No blocks to process. Abort."); return

    cv_inst = ChordVoicer(global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    gens: Dict[str, Any] = {}

    if main_cfg["parts_to_generate"].get("piano"):
        gens["piano"] = PianoGenerator(
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("piano_patterns", {})),
            chord_voicer_instance=cv_inst,
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"])
    if main_cfg["parts_to_generate"].get("drums"):
        gens["drums"] = DrumGenerator(
            drum_pattern_library=cast(Dict[str,Dict[str,Any]], rhythm_lib_all.get("drum_patterns", {})),
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"])
    if main_cfg["parts_to_generate"].get("chords"):
        gens["chords"] = cv_inst
    if main_cfg["parts_to_generate"].get("melody"):
        # ★ MelodyGeneratorの__init__で期待されるキー関連の引数名に合わせる ★
        # (MelodyGeneratorの__init__定義を確認して、適切な引数名を指定)
        gens["melody"] = MelodyGenerator(
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("melody_rhythms", {})),
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"],
            global_key_signature_tonic=main_cfg["global_key_tonic"], # または global_key_tonic など
            global_key_signature_mode=main_cfg["global_key_mode"]   # または global_key_mode など
        )
    if main_cfg["parts_to_generate"].get("bass"):
        gens["bass"] = BassGenerator( # ★ BassGenerator を使用 (ファイル名とクラス名を一致させる) ★
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("bass_lines", {})),
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"]
            # ★ BassGeneratorがキー情報を必要とする場合は、上記MelodyGeneratorのように引数を追加 ★
        )

    for p_n, p_g_inst in gens.items():
        if p_g_inst:
            logger.info(f"Generating {p_n} part...")
            try:
                part_obj = p_g_inst.compose(proc_blocks)
                if isinstance(part_obj, stream.Score) and part_obj.parts:
                    for sub_part in part_obj.parts: final_score.insert(0, sub_part)
                elif isinstance(part_obj, stream.Part) and part_obj.flatten().notesAndRests:
                    final_score.insert(0, part_obj)
                logger.info(f"{p_n} part generated.")
            except Exception as e_gen: logger.error(f"Error in {p_n} generation: {e_gen}", exc_info=True)

    title = chordmap.get("project_title","untitled").replace(" ","_").lower()
    out_fname_template = main_cfg["output_filename_template"]
    actual_out_fname = cli_args.output_filename if cli_args.output_filename else out_fname_template.format(song_title=title)
    out_fpath = cli_args.output_dir / actual_out_fname
    out_fpath.parent.mkdir(parents=True,exist_ok=True)
    try:
        if final_score.flatten().notesAndRests: final_score.write('midi',fp=str(out_fpath)); logger.info(f"🎉 MIDI: {out_fpath}")
        else: logger.warning(f"Score empty. No MIDI to {out_fpath}.")
    except Exception as e_w: logger.error(f"MIDI write error: {e_w}", exc_info=True)

def main_cli():
    parser = argparse.ArgumentParser(description="Modular Music Composer (Keyword-Driven)")
    parser.add_argument("chordmap_file", type=Path, help="Path to chordmap JSON.")
    parser.add_argument("rhythm_library_file", type=Path, help="Path to rhythm_library JSON.")
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Output MIDI directory.")
    parser.add_argument("--output-filename", type=str, help="Output MIDI filename (optional).")
    parser.add_argument("--settings-file", type=Path, help="Custom settings JSON (optional).")
    parser.add_argument("--tempo", type=int, help="Override global tempo.")
    cfg_parts_main = DEFAULT_CONFIG.get("parts_to_generate",{}) # 変数名変更
    for p_key_main_cli, p_state_main_cli in cfg_parts_main.items(): # 変数名変更
        arg_d_main_cli = f"generate_{p_key_main_cli}" # 変数名変更
        if p_state_main_cli: parser.add_argument(f"--no-{p_key_main_cli}", action="store_false", dest=arg_d_main_cli, help=f"Disable {p_key_main_cli}.")
        else: parser.add_argument(f"--include-{p_key_main_cli}", action="store_true", dest=arg_d_main_cli, help=f"Enable {p_key_main_cli}.")
    parser.set_defaults(**{f"generate_{k_arg_main_cli}": v_arg_main_cli for k_arg_main_cli, v_arg_main_cli in cfg_parts_main.items()}) # 変数名変更

    args = parser.parse_args()
    active_cfg = DEFAULT_CONFIG.copy() # 変数名変更
    if args.settings_file and args.settings_file.exists():
        custom_s_cfg_main_cli = load_json_file(args.settings_file, "Custom settings") # 変数名変更
        if custom_s_cfg_main_cli and isinstance(custom_s_cfg_main_cli, dict):
            def _merge_configs_main_cli(base, new): # 関数名と内部変数名変更
                for k_merge_main_cli, v_merge_main_cli in new.items():
                    if isinstance(v_merge_main_cli, dict) and k_merge_main_cli in base and isinstance(base[k_merge_main_cli], dict): _merge_configs_main_cli(base[k_merge_main_cli], v_merge_main_cli)
                    else: base[k_merge_main_cli] = v_merge_main_cli
            _merge_configs_main_cli(active_cfg, custom_s_cfg_main_cli)

    if args.tempo is not None: active_cfg["global_tempo"] = args.tempo
    for pk_cfg_main_cli in active_cfg.get("parts_to_generate",{}).keys(): # 変数名変更
        arg_n_cfg_main_cli = f"generate_{pk_cfg_main_cli}" # 変数名変更
        if hasattr(args, arg_n_cfg_main_cli): active_cfg["parts_to_generate"][pk_cfg_main_cli] = getattr(args, arg_n_cfg_main_cli)

    chordmap_loaded_main_cli = load_json_file(args.chordmap_file, "Chordmap") # 変数名変更
    rhythm_lib_loaded_main_cli = load_json_file(args.rhythm_library_file, "Rhythm Library") # 変数名変更
    if not chordmap_loaded_main_cli or not rhythm_lib_loaded_main_cli: logger.critical("Data files missing. Exit."); sys.exit(1)

    cm_globals_main_cli = chordmap_loaded_main_cli.get("global_settings", {}) # 変数名変更
    # ★★★ グローバル設定キー名の修正 ★★★
    active_cfg["global_tempo"] = cm_globals_main_cli.get("tempo", active_cfg["global_tempo"])
    active_cfg["global_time_signature"] = cm_globals_main_cli.get("time_signature", active_cfg["global_time_signature"])
    active_cfg["global_key_tonic"] = cm_globals_main_cli.get("key_tonic", active_cfg["global_key_tonic"])
    active_cfg["global_key_mode"] = cm_globals_main_cli.get("key_mode", active_cfg["global_key_mode"])
    
    logger.info(f"Final Effective Config: {json.dumps(active_cfg, indent=2, ensure_ascii=False)}")
    try: run_composition(args, active_cfg, cast(Dict,chordmap_loaded_main_cli), cast(Dict,rhythm_lib_loaded_main_cli))
    except SystemExit: raise
    except Exception as e_run_main_cli: logger.critical(f"Critical error in main run: {e_run_main_cli}", exc_info=True); sys.exit(1)

if __name__ == "__main__":
    main_cli()
# --- END OF FILE modular_composer.py ---
