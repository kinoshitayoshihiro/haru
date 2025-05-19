# --- START OF FILE modular_composer.py (包括的修正案) ---
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
    from generator.core_music_utils import get_time_signature_object
    from generator.piano_generator import PianoGenerator
    from generator.drum_generator import DrumGenerator
    from generator.chord_voicer import ChordVoicer
    from generator.melody_generator import MelodyGenerator
    # from generator.bass_core_generator import BassCoreGenerator # ★一旦コメントアウト (ImportErrorの原因の可能性)
    from generator.bass_generator import BassGenerator # ★こちらを試す (bass_generator.pyにBassGeneratorクラスがあると仮定)
    # from generator.guitar_generator import GuitarGenerator
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
        "piano": True, "drums": True, "melody": False, "bass": False, "chords": True, "guitar": False
    },
    "default_part_parameters": {
        "piano": {
            "emotion_to_rh_style_keyword": {"default": "simple_block_rh"}, # マッピングは例
            "emotion_to_lh_style_keyword": {"default": "simple_root_lh"},  # マッピングは例
            "style_keyword_to_rhythm_key": {
                "simple_block_rh": "piano_block_quarters_simple",
                "simple_root_lh": "piano_lh_quarter_roots",
                "default_piano_rh_fallback_rhythm": "default_piano_quarters",
                "default_piano_lh_fallback_rhythm": "piano_lh_whole_notes",
                # ★GitHubのrhythm_library.jsonとDEFAULT_CONFIGのキー名を一致させること★
                "reflective_arpeggio_rh": "piano_flowing_arpeggio_eighths_rh", # 例
                "chordal_moving_rh": "piano_chordal_moving_rh_pattern",    # 例
                "powerful_block_rh": "piano_powerful_block_8ths_rh",    # 例
                "gentle_root_lh": "piano_gentle_sustained_root_lh",        # 例
                "walking_bass_like_lh": "piano_gentle_walking_bass_quarters_lh", # 例
                "active_octave_lh": "piano_active_octave_bass_lh"        # 例
            },
            "intensity_to_velocity_ranges": { # (LH_min, LH_max, RH_min, RH_max)
                "low": (50, 60, 55, 65), "medium_low": (55, 65, 60, 70),
                "medium": (60, 70, 65, 75), "medium_high": (65, 80, 70, 85),
                "high": (70, 85, 75, 90), "default": (60, 70, 65, 75)
            },
            "default_apply_pedal": True, "default_arp_note_ql": 0.5,
            "default_rh_voicing_style": "closed", # ★文字列リテラル★
            "default_lh_voicing_style": "closed", # ★文字列リテラル★
            "default_rh_target_octave": 4, "default_lh_target_octave": 2,
            "default_rh_num_voices": 3, "default_lh_num_voices": 1
        },
        "drums": {
            "emotion_to_style_key": {
                "default_style": "basic_rock_4_4" # ★実際にrhythm_library.jsonに存在するキー名★
            },
            "intensity_to_base_velocity": {"default": 75, "low": 60, "medium": 75, "high": 90},
            "default_fill_interval_bars": 4,
            "default_fill_keys": ["simple_snare_roll_half_bar"]
        },
        "chords": {
            "instrument": "StringInstrument", "chord_voicing_style": "closed", # ★文字列リテラル★
            "chord_target_octave": 3, "chord_num_voices": 4, "chord_velocity": 64
        },
        "melody": {
            "instrument": "Flute", "rhythm_key": "default_melody_rhythm", # rhythm_libraryに定義要
            "octave_range": [4, 5], "density": 0.7
        },
        "bass": {
            "instrument": "AcousticBass", "style": "simple_roots", # BassGeneratorが解釈するスタイル
            "rhythm_key": "bass_quarter_notes" # rhythm_libraryに定義要
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
        rhythm_library: Dict # ★ 全体のrhythm_library_dataを渡す ★
) -> Dict[str, Any]:
    params: Dict[str, Any] = default_instrument_params.copy()
    emotion_key = musical_intent.get("emotion", "neutral").lower()
    intensity_key = musical_intent.get("intensity", "medium").lower()
    section_instrument_settings = chord_block_specific_hints.get("part_settings", {}).get(instrument_name_key, {})
    params.update(section_instrument_settings)

    logger.debug(f"Translating for {instrument_name_key}: Emo='{emotion_key}', Int='{intensity_key}', SectionSet='{section_instrument_settings}', BlkHints='{chord_block_specific_hints}'")

    if instrument_name_key == "piano":
        cfg_piano = default_instrument_params
        rh_style_kw = params.get("piano_rh_style_keyword", cfg_piano.get("emotion_to_rh_style_keyword", {}).get(emotion_key, cfg_piano.get("emotion_to_rh_style_keyword", {}).get("default")))
        params["piano_rh_style_keyword"] = rh_style_kw
        lh_style_kw = params.get("piano_lh_style_keyword", cfg_piano.get("emotion_to_lh_style_keyword", {}).get(emotion_key, cfg_piano.get("emotion_to_lh_style_keyword", {}).get("default")))
        params["piano_lh_style_keyword"] = lh_style_kw

        style_to_rhythm_map = cfg_piano.get("style_keyword_to_rhythm_key", {})
        piano_patterns_in_lib = rhythm_library.get("piano_patterns", {}) # ★ piano_patternsカテゴリを参照 ★

        params["piano_rh_rhythm_key"] = style_to_rhythm_map.get(rh_style_kw)
        if not params["piano_rh_rhythm_key"] or params.get("piano_rh_rhythm_key") not in piano_patterns_in_lib:
             fallback_rh_key = style_to_rhythm_map.get("default_piano_rh_fallback_rhythm", "default_piano_quarters")
             logger.warning(f"Piano RH rhythm key '{params.get('piano_rh_rhythm_key')}' for style '{rh_style_kw}' not found in lib. Using fallback '{fallback_rh_key}'.")
             params["piano_rh_rhythm_key"] = fallback_rh_key

        params["piano_lh_rhythm_key"] = style_to_rhythm_map.get(lh_style_kw)
        if not params["piano_lh_rhythm_key"] or params.get("piano_lh_rhythm_key") not in piano_patterns_in_lib:
             fallback_lh_key = style_to_rhythm_map.get("default_piano_lh_fallback_rhythm", "piano_lh_whole_notes")
             logger.warning(f"Piano LH rhythm key '{params.get('piano_lh_rhythm_key')}' for style '{lh_style_kw}' not in lib. Using fallback '{fallback_lh_key}'.")
             params["piano_lh_rhythm_key"] = fallback_lh_key

        vel_map = cfg_piano.get("intensity_to_velocity_ranges", {})
        default_vel_tuple = vel_map.get("default", (60, 70, 65, 75))
        current_vel_tuple = vel_map.get(intensity_key, default_vel_tuple) # ★ intensity_key で取得 ★
        if isinstance(current_vel_tuple, Sequence) and len(current_vel_tuple) == 4: # ★ 正しいタプル長をチェック ★
            params["piano_velocity_lh"] = random.randint(current_vel_tuple[0], current_vel_tuple[1])
            params["piano_velocity_rh"] = random.randint(current_vel_tuple[2], current_vel_tuple[3])
        else:
            logger.warning(f"Piano velocity range for intensity '{intensity_key}' is not a 4-element tuple. Using defaults from tuple.")
            params["piano_velocity_lh"] = random.randint(default_vel_tuple[0], default_vel_tuple[1])
            params["piano_velocity_rh"] = random.randint(default_vel_tuple[2], default_vel_tuple[3])

        for p_key_suffix in ["apply_pedal", "arp_note_ql", "rh_voicing_style", "lh_voicing_style", "rh_target_octave", "lh_target_octave", "rh_num_voices", "lh_num_voices"]:
            param_name_full = f"piano_{p_key_suffix}"
            default_param_key_in_cfg = f"default_{p_key_suffix}"
            params[param_name_full] = params.get(param_name_full, cfg_piano.get(default_param_key_in_cfg))

    elif instrument_name_key == "drums":
        cfg_drums = default_instrument_params
        style_key_from_emotion = cfg_drums.get("emotion_to_style_key", {}).get(emotion_key, cfg_drums.get("emotion_to_style_key", {}).get("default_style"))
        params["drum_style_key"] = params.get("drum_style_key", style_key_from_emotion)
        
        drum_patterns_from_lib = rhythm_library.get("drum_patterns", {}) # ★ drum_patternsカテゴリを参照 ★
        if not params["drum_style_key"] or params.get("drum_style_key") not in drum_patterns_from_lib:
            logger.warning(f"Drum style key '{params.get('drum_style_key')}' not in drum_patterns. Using 'default_drum_pattern'.")
            params["drum_style_key"] = "default_drum_pattern"

        vel_map_drums = cfg_drums.get("intensity_to_base_velocity", {})
        default_drum_vel = vel_map_drums.get("default", 75) # ★ 設定からのデフォルトベロシティ ★
        vel_base_val = params.get("drum_base_velocity", vel_map_drums.get(intensity_key, default_drum_vel))
        params["drum_base_velocity"] = int(random.randint(vel_base_val[0],vel_base_val[1])) if isinstance(vel_base_val,tuple) and len(vel_base_val)==2 else int(vel_base_val)
        
        params["drum_fill_interval_bars"] = params.get("drum_fill_interval_bars", cfg_drums.get("default_fill_interval_bars"))
        params["drum_fill_keys"] = params.get("drum_fill_keys", cfg_drums.get("default_fill_keys"))

    # 他の楽器のパラメータ変換ロジックもここに追加 (melody, bassなど)
    elif instrument_name_key == "melody":
        cfg_melody = default_instrument_params
        params["rhythm_key"] = params.get("rhythm_key", cfg_melody.get("rhythm_key_map",{}).get(emotion_key, cfg_melody.get("rhythm_key_map",{}).get("default")))
        params["octave_range"] = params.get("octave_range", cfg_melody.get("octave_range"))
        params["density"] = params.get("density", cfg_melody.get("density"))
        # ... その他メロディ固有パラメータ

    elif instrument_name_key == "bass":
        cfg_bass = default_instrument_params
        params["style"] = params.get("style", cfg_bass.get("style_map",{}).get(emotion_key, cfg_bass.get("style_map",{}).get("default")))
        params["rhythm_key"] = params.get("rhythm_key", cfg_bass.get("rhythm_key_map",{}).get(emotion_key, cfg_bass.get("rhythm_key_map",{}).get("default")))
        # ... その他ベース固有パラメータ

    block_instrument_hints = chord_block_specific_hints.get("part_specific_hints", {}).get(instrument_name_key, {})
    params.update(block_instrument_hints)
    if instrument_name_key == "drums" and "drum_fill" in chord_block_specific_hints:
        params["drum_fill_key_override"] = chord_block_specific_hints["drum_fill"]
    logger.info(f"Final params for [{instrument_name_key}] (Emo: {emotion_key}, Int: {intensity_key}) -> {params}")
    return params

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_lib: Dict) -> List[Dict]:
    # (この関数は前回提示した修正を適用済みと仮定 - translate_keywords_to_params へ rhythm_lib を渡す)
    processed_stream: List[Dict] = []
    current_abs_offset: float = 0.0
    global_settings = chordmap_data.get("global_settings", {})
    time_sig_str = global_settings.get("time_signature", main_config["global_time_signature"])
    ts_obj = get_time_signature_object(time_sig_str)
    beats_per_measure = ts_obj.barDuration.quarterLength
    global_key_tonic = global_settings.get("key_tonic", main_config["global_key_tonic"])
    global_key_mode = global_settings.get("key_mode", main_config["global_key_mode"])

    sorted_sections = sorted(chordmap_data.get("sections", {}).items(), key=lambda item: item[1].get("order", float('inf')))
    for sec_name, sec_info in sorted_sections:
        logger.info(f"Preparing section: {sec_name}")
        sec_musical_intent = sec_info.get("musical_intent", {})
        sec_part_settings = sec_info.get("part_settings", {})
        sec_tonic = sec_info.get("tonic", global_key_tonic); sec_mode = sec_info.get("mode", global_key_mode)
        sec_len_measures = sec_info.get("length_in_measures")
        chord_prog = sec_info.get("chord_progression", [])
        if not chord_prog: logger.warning(f"Section '{sec_name}' no chords. Skip."); continue

        for chord_idx, chord_def in enumerate(chord_prog):
            chord_lbl = chord_def.get("label", "C")
            dur_b = float(chord_def["duration_beats"]) if "duration_beats" in chord_def else (float(sec_len_measures) * beats_per_measure) / len(chord_prog) if sec_len_measures and chord_prog else beats_per_measure
            blk_intent = sec_musical_intent.copy()
            if "emotion" in chord_def: blk_intent["emotion"] = chord_def["emotion"]
            if "intensity" in chord_def: blk_intent["intensity"] = chord_def["intensity"]
            blk_hints = {k:v for k,v in chord_def.items() if k not in ["label","duration_beats","order","musical_intent","part_settings","tensions_to_add"]}
            blk_hints["part_settings"] = sec_part_settings
            blk_data = {"offset":current_abs_offset, "q_length":dur_b, "chord_label":chord_lbl, "section_name":sec_name,
                        "tonic_of_section":sec_tonic, "mode":sec_m, "tensions_to_add":chord_def.get("tensions_to_add",[]),
                        "is_first_in_section":(chord_idx==0), "is_last_in_section":(chord_idx==len(chord_prog)-1), "part_params":{}}
            for p_key_name in main_config["parts_to_generate"].keys():
                def_p = main_config["default_part_parameters"].get(p_key_name, {})
                # ★★★ 各楽器に対応するリズムライブラリのサブカテゴリを渡すように修正 ★★★
                rhythm_category_for_instrument = rhythm_lib.get(f"{p_key_name}_patterns", # piano_patterns, drum_patterns
                                                rhythm_lib.get(f"{p_key_name}_rhythms",    # melody_rhythms
                                                rhythm_lib.get(f"{p_key_name}_lines", {}))) # bass_lines など
                blk_data["part_params"][p_key_name] = translate_keywords_to_params(blk_intent, blk_hints, def_p, p_key_name, rhythm_category_for_instrument)
            processed_stream.append(blk_data)
            current_abs_offset += dur_b
    logger.info(f"Prepared {len(processed_stream)} blocks. Duration: {current_abs_offset:.2f} beats.")
    return processed_stream


def run_composition(cli_args: argparse.Namespace, main_cfg: Dict, chordmap: Dict, rhythm_lib_all: Dict):
    # (run_composition の前半のスコア初期化は変更なし)
    logger.info("=== Running Main Composition Workflow ===")
    final_score = stream.Score()
    final_score.insert(0, tempo.MetronomeMark(number=main_cfg["global_tempo"]))
    try:
        ts_obj_score = get_time_signature_object(main_cfg["global_time_signature"])
        final_score.insert(0, ts_obj_score)
        key_t, key_m = main_cfg["global_key_tonic"], main_cfg["global_key_mode"]
        if chordmap.get("sections"):
            try:
                first_sec_name = sorted(chordmap["sections"].keys(), key=lambda k_s: chordmap["sections"][k_s].get("order",float('inf')))[0]
                first_sec_info = chordmap["sections"][first_sec_name]
                key_t, key_m = first_sec_info.get("tonic",key_t), first_sec_info.get("mode",key_m)
            except IndexError: logger.warning("No sections for initial key.")
        final_score.insert(0, key.Key(key_t, key_m.lower()))
    except Exception as e: logger.error(f"Error setting score globals: {e}. Defaults.", exc_info=True); final_score.insert(0,meter.TimeSignature("4/4")); final_score.insert(0,key.Key("C"))


    proc_blocks = prepare_processed_stream(chordmap, main_cfg, rhythm_lib_all) # ★ rhythm_lib_all を渡す ★
    if not proc_blocks: logger.error("No blocks to process. Abort."); return

    cv_inst = ChordVoicer(global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    gens: Dict[str, Any] = {}

    if main_cfg["parts_to_generate"].get("piano"):
        gens["piano"] = PianoGenerator(
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("piano_patterns", {})), # ★ piano_patterns を渡す
            chord_voicer_instance=cv_inst,
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"]
        )
    if main_cfg["parts_to_generate"].get("drums"):
        gens["drums"] = DrumGenerator(
            drum_pattern_library=cast(Dict[str,Dict[str,Any]], rhythm_lib_all.get("drum_patterns", {})), # ★ drum_patterns を渡す
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"]
        )
    if main_cfg["parts_to_generate"].get("chords"):
        gens["chords"] = cv_inst # ChordVoicerインスタンスをそのまま使う

    if main_cfg["parts_to_generate"].get("melody"):
        gens["melody"] = MelodyGenerator(
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("melody_rhythms", {})), # ★ melody_rhythms を渡す
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"],
            global_key_signature_tonic=main_cfg["global_key_tonic"], # ★ MelodyGeneratorの__init__に合わせる
            global_key_signature_mode=main_cfg["global_key_mode"]   # ★ MelodyGeneratorの__init__に合わせる
        )
    if main_cfg["parts_to_generate"].get("bass"):
        gens["bass"] = BassGenerator( # ★ BassGenerator (または BassCoreGenerator) を使用 ★
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("bass_lines", {})), # ★ bass_lines を渡す
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"]
            # BassGenerator/BassCoreGenerator がキー情報を必要とする場合はここに追加
        )

    for p_n, p_g_inst in gens.items():
        if p_g_inst:
            logger.info(f"Generating {p_n} part...")
            try:
                # 全てのジェネレータのcomposeはprocessed_blocksのみ受け取るように統一するのが理想
                part_obj = p_g_inst.compose(proc_blocks)
                if isinstance(part_obj, stream.Score) and part_obj.parts: # PianoGeneratorの場合
                    for sub_part in part_obj.parts: final_score.insert(0, sub_part)
                elif isinstance(part_obj, stream.Part) and part_obj.flatten().notesAndRests:
                    final_score.insert(0, part_obj)
                logger.info(f"{p_n} part generated.")
            except Exception as e_gen: logger.error(f"Error in {p_n} generation: {e_gen}", exc_info=True)

    title = chordmap.get("project_title","untitled").replace(" ","_").lower()
    out_fname_from_template = main_cfg["output_filename_template"].format(song_title=title)
    actual_out_fname = cli_args.output_filename if cli_args.output_filename else out_fname_from_template
    out_p = cli_args.output_dir / actual_out_fname
    out_p.parent.mkdir(parents=True,exist_ok=True)
    try:
        if final_score.flatten().notesAndRests: final_score.write('midi',fp=str(out_p)); logger.info(f"🎉 MIDI: {out_p}")
        else: logger.warning(f"Score empty. No MIDI to {out_p}.")
    except Exception as e_write: logger.error(f"MIDI write error: {e_write}", exc_info=True)


def main_cli():
    # (main_cli の argparse の部分は前回提示したもので概ね問題ないはずです)
    # (gs_key のループでのキー名修正は重要)
    parser = argparse.ArgumentParser(description="Modular Music Composer (Keyword-Driven v3)")
    parser.add_argument("chordmap_file", type=Path, help="Path to chordmap JSON.")
    parser.add_argument("rhythm_library_file", type=Path, help="Path to rhythm_library JSON.")
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Output directory for MIDI.")
    parser.add_argument("--output-filename", type=str, help="Output MIDI filename (optional).")
    parser.add_argument("--settings-file", type=Path, help="Custom settings JSON (optional).")
    parser.add_argument("--tempo", type=int, help="Override global tempo.")
    default_parts = DEFAULT_CONFIG.get("parts_to_generate",{})
    for pk, state in default_parts.items():
        arg_dest = f"generate_{pk}"
        if state: parser.add_argument(f"--no-{pk}", action="store_false", dest=arg_dest, help=f"Disable {pk}.")
        else: parser.add_argument(f"--include-{pk}", action="store_true", dest=arg_dest, help=f"Enable {pk}.")
    parser.set_defaults(**{f"generate_{k_arg}": v_arg for k_arg, v_arg in default_parts.items()})

    args = parser.parse_args()
    active_config = DEFAULT_CONFIG.copy()
    if args.settings_file and args.settings_file.exists():
        custom_s_cfg = load_json_file(args.settings_file, "Custom settings")
        if custom_s_cfg and isinstance(custom_s_cfg, dict):
            def _merge_configs(base, new):
                for k_merge, v_merge in new.items():
                    if isinstance(v_merge, dict) and k_merge in base and isinstance(base[k_merge], dict): _merge_configs(base[k_merge], v_merge)
                    else: base[k_merge] = v_merge
            _merge_configs(active_config, custom_s_cfg)

    if args.tempo is not None: active_config["global_tempo"] = args.tempo
    for pk_cfg in active_config.get("parts_to_generate",{}).keys(): # ループ変数を変更
        arg_n_cfg = f"generate_{pk_cfg}" # ループ変数を変更
        if hasattr(args, arg_n_cfg): active_config["parts_to_generate"][pk_cfg] = getattr(args, arg_n_cfg)

    chordmap_loaded = load_json_file(args.chordmap_file, "Chordmap") # 変数名変更
    rhythm_lib_loaded = load_json_file(args.rhythm_library_file, "Rhythm Library") # 変数名変更
    if not chordmap_loaded or not rhythm_lib_loaded: logger.critical("Data files missing. Exit."); sys.exit(1)

    cm_globals = chordmap_loaded.get("global_settings", {})
    # ★★★ グローバル設定キー名の修正 (f-string を使わない場合) ★★★
    active_config["global_tempo"] = cm_globals.get("tempo", active_config["global_tempo"])
    active_config["global_time_signature"] = cm_globals.get("time_signature", active_config["global_time_signature"])
    active_config["global_key_tonic"] = cm_globals.get("key_tonic", active_config["global_key_tonic"])
    active_config["global_key_mode"] = cm_globals.get("key_mode", active_config["global_key_mode"])
    
    logger.info(f"Final Config: {json.dumps(active_config, indent=2, ensure_ascii=False)}")
    try: run_composition(args, active_config, cast(Dict,chordmap_loaded), cast(Dict,rhythm_lib_loaded))
    except SystemExit: raise
    except Exception as e_run: logger.critical(f"Critical error in main run: {e_run}", exc_info=True); sys.exit(1)

if __name__ == "__main__":
    main_cli()
    
# --- END OF FILE modular_composer.py ---
