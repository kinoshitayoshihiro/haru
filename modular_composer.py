# --- START OF FILE modular_composer.py (修正版) ---
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

try:
    from generator.core_music_utils import get_time_signature_object
    from generator.piano_generator import PianoGenerator
    from generator.drum_generator import DrumGenerator
    from generator.chord_voicer import ChordVoicer
    from generator.melody_generator import MelodyGenerator
    from generator.bass_core_generator import BassCoreGenerator # 仮にこちらを使用
    # from generator.guitar_generator import GuitarGenerator
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import generator modules from 'generator' package. Error: {e}")
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
            "emotion_to_rh_style_keyword": {
                "struggle_with_underlying_strength": "reflective_arpeggio_rh",
                "deep_regret_and_gratitude": "chordal_moving_rh",
                "love_pain_acceptance_and_belief": "powerful_block_rh",
                "default": "simple_block_rh"
            },
            "emotion_to_lh_style_keyword": {
                "struggle_with_underlying_strength": "gentle_root_lh",
                "deep_regret_and_gratitude": "walking_bass_like_lh",
                "love_pain_acceptance_and_belief": "active_octave_lh",
                "default": "simple_root_lh"
            },
            "style_keyword_to_rhythm_key": {
                "reflective_arpeggio_rh": "piano_flowing_arpeggio_eighths_rh",
                "chordal_moving_rh": "piano_chordal_moving_rh_pattern",
                "powerful_block_rh": "piano_powerful_block_8ths_rh",
                "simple_block_rh": "piano_block_quarters_simple",
                "gentle_root_lh": "piano_gentle_sustained_root_lh",
                "walking_bass_like_lh": "piano_gentle_walking_bass_quarters_lh",
                "active_octave_lh": "piano_active_octave_bass_lh",
                "simple_root_lh": "piano_lh_quarter_roots",
                "default_piano_rh_fallback_rhythm": "default_piano_quarters",
                "default_piano_lh_fallback_rhythm": "piano_lh_whole_notes"
            },
            "intensity_to_velocity_ranges": {
                "very_low":     (35, 45, 40, 50), "low":          (45, 55, 50, 60),
                "medium_low":   (55, 65, 60, 70), "medium":       (65, 75, 70, 80),
                "medium_high":  (75, 85, 80, 90), "high":         (85, 95, 90, 100),
                "very_high":    (95, 110, 100, 115), "default":      (60, 70, 65, 75)
            },
            "default_apply_pedal": True, "default_arp_note_ql": 0.5,
            "default_rh_voicing_style": "closed", # ★★★ 修正: 文字列リテラル ★★★
            "default_lh_voicing_style": "closed", # ★★★ 修正: 文字列リテラル ★★★
            "default_rh_target_octave": 4, "default_lh_target_octave": 2,
            "default_rh_num_voices": 3, "default_lh_num_voices": 1
        },
        "drums": {
            "emotion_to_style_key": {
                "struggle_with_underlying_strength": "ballad_soft_kick_snare_8th_hat",
                "deep_regret_and_gratitude": "rock_ballad_build_up_8th_hat",
                "love_pain_acceptance_and_belief": "anthem_rock_chorus_16th_hat",
                "default_style": "basic_rock_4_4"
            },
            "intensity_to_base_velocity": { "default": 75, "low": 60, "medium": 75, "high": 90 },
            "default_fill_interval_bars": 4,
            "default_fill_keys": ["simple_snare_roll_half_bar"]
        },
        "chords": {
            "instrument": "StringInstrument",
            "chord_voicing_style": "closed", # ★★★ 修正: 文字列リテラル ★★★
            "chord_target_octave": 3,
            "chord_num_voices": 4,
            "chord_velocity": 64
        },
        "melody": {
            "instrument": "Violin", "rhythm_key_map": { "default": "default_melody_rhythm" },
            "octave_range": [4, 6], "density": 0.7
        },
        "bass": {
            "instrument": "AcousticBass", "style_map": { "default": "simple_roots" },
            "rhythm_key_map": { "default": "bass_quarter_notes" }
        }
    },
    "output_filename_template": "output_{song_title}.mid"
}

def load_json_file(file_path: Path, description: str) -> Optional[Dict | List]:
    # (変更なし)
    if not file_path.exists(): logger.error(f"{description} not found: {file_path}"); sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        logger.info(f"Loaded {description} from: {file_path}"); return data
    except json.JSONDecodeError as e: logger.error(f"JSON decode error in {description} ({e.msg} L{e.lineno} C{e.colno}): {file_path}"); sys.exit(1)
    except Exception as e: logger.error(f"Error loading {description} from {file_path}: {e}", exc_info=True); sys.exit(1)
    return None


def translate_keywords_to_params(
        musical_intent: Dict[str, Any], chord_block_hints: Dict[str, Any],
        instrument_defaults: Dict[str, Any], instrument_key: str,
        rhythm_library_for_instrument_category: Dict[str, Any] # その楽器用のリズムライブラリカテゴリ
) -> Dict[str, Any]:
    params = instrument_defaults.copy() # デフォルトで初期化
    emotion = musical_intent.get("emotion", "neutral").lower()
    intensity = musical_intent.get("intensity", "medium").lower()
    # セクションレベルのパート設定をまず適用
    section_part_cfg = chord_block_hints.get("part_settings", {}).get(instrument_key, {})
    params.update(section_part_cfg)

    logger.debug(f"Translating for {instrument_key}: Emo='{emotion}', Int='{intensity}', SecCfg='{section_part_cfg}', BlkHints='{chord_block_hints}'")

    if instrument_key == "piano":
        # emotion/intensity からスタイルキーワード等を選択 (paramsがセクション設定で上書きされている可能性あり)
        rh_style_kw = params.get("piano_rh_style_keyword", instrument_defaults.get("emotion_to_rh_style_keyword", {}).get(emotion, instrument_defaults.get("emotion_to_rh_style_keyword", {}).get("default")))
        lh_style_kw = params.get("piano_lh_style_keyword", instrument_defaults.get("emotion_to_lh_style_keyword", {}).get(emotion, instrument_defaults.get("emotion_to_lh_style_keyword", {}).get("default")))
        params["piano_rh_style_keyword"] = rh_style_kw # 確定値を格納
        params["piano_lh_style_keyword"] = lh_style_kw

        style_to_rhythm_map = instrument_defaults.get("style_keyword_to_rhythm_key", {})
        params["piano_rh_rhythm_key"] = style_to_rhythm_map.get(rh_style_kw)
        if not params["piano_rh_rhythm_key"] or params.get("piano_rh_rhythm_key") not in rhythm_library_for_instrument_category:
             params["piano_rh_rhythm_key"] = style_to_rhythm_map.get("default_piano_rh_fallback_rhythm", "default_piano_quarters")
        params["piano_lh_rhythm_key"] = style_to_rhythm_map.get(lh_style_kw)
        if not params["piano_lh_rhythm_key"] or params.get("piano_lh_rhythm_key") not in rhythm_library_for_instrument_category:
             params["piano_lh_rhythm_key"] = style_to_rhythm_map.get("default_piano_lh_fallback_rhythm", "piano_lh_whole_notes")

        vel_map = instrument_defaults.get("intensity_to_velocity_ranges", {})
        def_vel_range = vel_map.get("default", (60,70,65,75))
        lh_m, lh_x, rh_m, rh_x = vel_map.get(intensity, def_vel_range)
        params["piano_velocity_lh"] = random.randint(lh_m, lh_x)
        params["piano_velocity_rh"] = random.randint(rh_m, rh_x)

        # 他のピアノ固有パラメータも同様にセクション設定を優先し、なければデフォルトのデフォルト
        for k_suffix in ["apply_pedal", "arp_note_ql", "rh_voicing_style", "lh_voicing_style", "rh_target_octave", "lh_target_octave", "rh_num_voices", "lh_num_voices"]:
            param_k = f"piano_{k_suffix}"
            default_k_in_cfg = f"default_{k_suffix}"
            params[param_k] = params.get(param_k, instrument_defaults.get(default_k_in_cfg))

    elif instrument_key == "drums":
        style_key_emo = instrument_defaults.get("emotion_to_style_key", {}).get(emotion, instrument_defaults.get("emotion_to_style_key", {}).get("default_style"))
        params["drum_style_key"] = params.get("drum_style_key", style_key_emo)
        if not params["drum_style_key"] or params.get("drum_style_key") not in rhythm_library_for_instrument_category:
            params["drum_style_key"] = "default_drum_pattern"

        vel_map_drum = instrument_defaults.get("intensity_to_base_velocity", {})
        def_drum_vel = vel_map_drum.get("default", 75)
        vel_base = params.get("drum_base_velocity", vel_map_drum.get(intensity, def_drum_vel))
        params["drum_base_velocity"] = int(random.randint(vel_base[0], vel_base[1])) if isinstance(vel_base, tuple) and len(vel_base) == 2 else int(vel_base)

        params["drum_fill_interval_bars"] = params.get("drum_fill_interval_bars", instrument_defaults.get("default_fill_interval_bars"))
        params["drum_fill_keys"] = params.get("drum_fill_keys", instrument_defaults.get("default_fill_keys"))

    # コードブロック固有の part_specific_hints で最終上書き
    block_inst_hints = chord_block_hints.get("part_specific_hints", {}).get(instrument_key, {})
    params.update(block_inst_hints)
    if instrument_key == "drums" and "drum_fill" in chord_block_hints: # drum_fillは特別扱い
        params["drum_fill_key_override"] = chord_block_hints["drum_fill"]

    logger.info(f"Final params for [{instrument_key}] (Emo: {emotion}, Int: {intensity}): {params}")
    return params

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_lib: Dict) -> List[Dict]:
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
        if not chord_prog: logger.warning(f"Sec '{sec_name}' no chords. Skip."); continue

        for c_idx, c_def in enumerate(chord_prog):
            c_lbl = c_def.get("label", "C")
            dur_b = float(c_def["duration_beats"]) if "duration_beats" in c_def else (float(sec_len_meas) * beats_per_measure) / len(chord_prog) if sec_len_meas and chord_prog else beats_per_measure
            
            blk_int = sec_intent.copy() # セクションの意図をコピー
            if "emotion" in c_def: blk_int["emotion"] = c_def["emotion"]
            if "intensity" in c_def: blk_int["intensity"] = c_def["intensity"]
            
            blk_hints = {k:v for k,v in c_def.items() if k not in ["label","duration_beats","order","musical_intent","part_settings","tensions_to_add"]}
            blk_hints["part_settings"] = sec_part_set # セクション全体の楽器設定をヒントに含める

            blk_data = {"offset":current_abs_offset, "q_length":dur_b, "chord_label":c_lbl, "section_name":sec_name,
                        "tonic_of_section":sec_t, "mode":sec_m, "tensions_to_add":c_def.get("tensions_to_add",[]),
                        "is_first_in_section":(c_idx==0), "is_last_in_section":(c_idx==len(chord_prog)-1), "part_params":{}}
            
            for p_key_name in main_config["parts_to_generate"].keys():
                def_p = main_config["default_part_parameters"].get(p_key_name, {})
                rhythm_cat_for_instrument = rhythm_lib.get(f"{p_key_name}_patterns", rhythm_lib.get(f"{p_key_name}_rhythms", rhythm_lib.get(f"{p_key_name}_lines", {}))) # カテゴリ名を探す
                blk_data["part_params"][p_key_name] = translate_keywords_to_params(blk_int, blk_hints, def_p, p_key_name, rhythm_cat_for_instrument)
            processed_stream.append(blk_data)
            current_abs_offset += dur_b
    logger.info(f"Prepared {len(processed_stream)} blocks. Duration: {current_abs_offset:.2f} beats.")
    return processed_stream

def run_composition(cli_args: argparse.Namespace, main_cfg: Dict, chordmap: Dict, rhythm_lib_all: Dict):
    logger.info("=== Running Main Composition Workflow ===")
    score = stream.Score()
    score.insert(0, tempo.MetronomeMark(number=main_cfg["global_tempo"]))
    try:
        ts = get_time_signature_object(main_cfg["global_time_signature"])
        score.insert(0, ts)
        kT, kM = main_cfg["global_key_tonic"], main_cfg["global_key_mode"]
        if chordmap.get("sections"):
            try:
                f_sec_n = sorted(chordmap["sections"].keys(), key=lambda k: chordmap["sections"][k].get("order",float('inf')))[0]
                f_sec_i = chordmap["sections"][f_sec_n]
                kT, kM = f_sec_i.get("tonic",kT), f_sec_i.get("mode",kM)
            except IndexError: logger.warning("No sections for initial key.")
        score.insert(0, key.Key(kT, kM.lower()))
    except Exception as e: logger.error(f"Error setting score globals: {e}. Defaults.", exc_info=True); score.insert(0,meter.TimeSignature("4/4")); score.insert(0,key.Key("C"))

    blocks = prepare_processed_stream(chordmap, main_cfg, rhythm_lib_all)
    if not blocks: logger.error("No blocks to process. Abort."); return

    cv_inst = ChordVoicer(global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    gen_map: Dict[str, Any] = {}
    if main_cfg["parts_to_generate"].get("piano"): gen_map["piano"] = PianoGenerator(cast(Dict[str,Dict],rhythm_lib_all.get("piano_patterns",{})), cv_inst, main_cfg["global_tempo"], main_cfg["global_time_signature"])
    if main_cfg["parts_to_generate"].get("drums"): gen_map["drums"] = DrumGenerator(cast(Dict[str,Dict[str,Any]],rhythm_lib_all.get("drum_patterns",{})), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    if main_cfg["parts_to_generate"].get("chords"): gen_map["chords"] = cv_inst
    if main_cfg["parts_to_generate"].get("melody"):
        gen_map["melody"] = MelodyGenerator(cast(Dict[str,Dict],rhythm_lib_all.get("melody_rhythms",{})), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"],
                                         global_key_signature_tonic=main_cfg["global_key_tonic"], global_key_signature_mode=main_cfg["global_key_mode"]) # ★ 引数名修正 ★
    if main_cfg["parts_to_generate"].get("bass"):
        gen_map["bass"] = BassCoreGenerator(cast(Dict[str,Dict],rhythm_lib_all.get("bass_lines",{})), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"],
                                            # ★ BassCoreGeneratorがキー情報を必要とするなら追加 ★
                                            # global_key_tonic=main_cfg["global_key_tonic"],
                                            # global_key_mode=main_cfg["global_key_mode"]
                                            )


    for p_n, p_g_inst in gen_map.items():
        if p_g_inst:
            logger.info(f"Generating {p_n} part...")
            try:
                part_obj = p_g_inst.compose(blocks) # 全ジェネレータのcomposeはblocksのみ受け取る想定に
                if isinstance(part_obj, stream.Score) and part_obj.parts: # PianoGeneratorの場合
                    for sub_part in part_obj.parts: score.insert(0, sub_part)
                elif isinstance(part_obj, stream.Part) and part_obj.flatten().notesAndRests:
                    score.insert(0, part_obj)
                logger.info(f"{p_n} part generated.")
            except Exception as e_g: logger.error(f"Error in {p_n} generation: {e_g}", exc_info=True)

    title = chordmap.get("project_title","untitled").replace(" ","_").lower()
    out_name = cli_args.output_filename if cli_args.output_filename else main_cfg["output_filename_template"].format(song_title=title)
    out_fpath = cli_args.output_dir / out_name
    out_fpath.parent.mkdir(parents=True,exist_ok=True)
    try:
        if score.flatten().notesAndRests: score.write('midi',fp=str(out_fpath)); logger.info(f"🎉 MIDI: {out_fpath}")
        else: logger.warning(f"Score empty. No MIDI to {out_fpath}.")
    except Exception as e_w: logger.error(f"MIDI write error: {e_w}", exc_info=True)

def main_cli():
    parser = argparse.ArgumentParser(description="Modular Music Composer vNext") # Version up
    parser.add_argument("chordmap_file", type=Path, help="Chordmap JSON path.")
    parser.add_argument("rhythm_library_file", type=Path, help="Rhythm library JSON path.")
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Output MIDI directory.")
    parser.add_argument("--output-filename", type=str, help="Output MIDI filename (optional, overrides template).")
    parser.add_argument("--settings-file", type=Path, help="Custom settings JSON path (optional).")
    parser.add_argument("--tempo", type=int, help="Override global tempo.")
    
    cfg_parts = DEFAULT_CONFIG.get("parts_to_generate",{})
    for p_key_main, p_state_main in cfg_parts.items():
        arg_d = f"generate_{p_key_main}"
        if p_state_main: parser.add_argument(f"--no-{p_key_main}", action="store_false", dest=arg_d, help=f"Disable {p_key_main}.")
        else: parser.add_argument(f"--include-{p_key_main}", action="store_true", dest=arg_d, help=f"Enable {p_key_main}.")
    parser.set_defaults(**{f"generate_{k_arg}": v_arg for k_arg, v_arg in cfg_parts.items()})

    args = parser.parse_args()
    a_cfg = DEFAULT_CONFIG.copy() # Use deepcopy for nested dicts if they are modified in place
    if args.settings_file and args.settings_file.exists():
        custom_s_cfg = load_json_file(args.settings_file, "Custom settings")
        if custom_s_cfg and isinstance(custom_s_cfg, dict):
            def _merge_configs(base, new):
                for k_merge, v_merge in new.items():
                    if isinstance(v_merge, dict) and k_merge in base and isinstance(base[k_merge], dict): _merge_configs(base[k_merge], v_merge)
                    else: base[k_merge] = v_merge
            _merge_configs(a_cfg, custom_s_cfg)

    if args.tempo is not None: a_cfg["global_tempo"] = args.tempo
    for p_key_cfg in a_cfg.get("parts_to_generate",{}).keys():
        arg_n = f"generate_{p_key_cfg}"
        if hasattr(args, arg_n): a_cfg["parts_to_generate"][p_key_cfg] = getattr(args, arg_n)

    cmap = load_json_file(args.chordmap_file, "Chordmap"); rlib = load_json_file(args.rhythm_library_file, "Rhythm Library")
    if not cmap or not rlib: logger.critical("Data files missing. Exit."); sys.exit(1)

    cm_g = cmap.get("global_settings", {})
    for g_k_cfg in ["tempo", "time_signature", "key_tonic", "key_mode"]:
        a_cfg[f"global_{g_k_cfg}"] = cm_g.get(g_k_cfg, a_cfg[f"global_{g_k_cfg}"]) # Use f-string for correct key
    
    logger.info(f"Final Config: {json.dumps(a_cfg, indent=2, ensure_ascii=False)}")
    try: run_composition(args, a_cfg, cast(Dict,cmap), cast(Dict,rlib))
    except SystemExit: raise # load_json_file などで明示的に終了した場合
    except Exception as e_main_run: logger.critical(f"Critical error in main run: {e_main_run}", exc_info=True); sys.exit(1)

if __name__ == "__main__":
    main_cli()

# --- END OF FILE modular_composer.py ---
