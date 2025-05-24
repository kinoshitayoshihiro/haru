# --- START OF FILE modular_composer.py  ---
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

# --- ユーティリティとジェネレータクラスのインポート ---
try:
    # utilities フォルダからのインポート
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES # HUMANIZATION_TEMPLATESも参照する場合

    # generator フォルダからのインポート
    from generator.piano_generator import PianoGenerator
    from generator.drum_generator import DrumGenerator
    from generator.guitar_generator import GuitarGenerator # ファイル名変更を反映
    from generator.chord_voicer import ChordVoicer
    from generator.melody_generator import MelodyGenerator
    from generator.bass_generator import BassGenerator
    from generator.vocal_generator import VocalGenerator
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import utility or generator modules. "
          f"Ensure 'utilities' and 'generator' directories are in the project root "
          f"and contain __init__.py files. Error: {e}")
    sys.exit(1)
except Exception as e_imp:
    print(f"An unexpected error occurred during module import: {e_imp}")
    sys.exit(1)

# --- ロガー設定 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - [%(levelname)s] - %(module)s.%(funcName)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("modular_composer")

# --- デフォルト設定 (前回提案から変更なし、ただしパスの扱いに注意) ---
DEFAULT_CONFIG = {
    "global_tempo": 100,
    "global_time_signature": "4/4",
    "global_key_tonic": "C",
    "global_key_mode": "major",
    "parts_to_generate": {
        "piano": True, "drums": True, "guitar": True, "bass": False,
        "chords": True, "melody": False, "vocal": True
    },
    "default_part_parameters": {
        "piano": {
            "emotion_to_rh_style_keyword": {"default": "simple_block_rh", "quiet_pain_and_nascent_strength": "piano_reflective_arpeggio_rh", "deep_regret_gratitude_and_realization": "piano_chordal_moving_rh", "acceptance_of_love_and_pain_hopeful_belief": "piano_powerful_block_8ths_rh", "self_reproach_regret_deep_sadness": "piano_reflective_arpeggio_rh", "supported_light_longing_for_rebirth": "piano_chordal_moving_rh", "reflective_transition_instrumental_passage": "piano_reflective_arpeggio_rh", "trial_cry_prayer_unbreakable_heart": "piano_powerful_block_8ths_rh", "memory_unresolved_feelings_silence": "piano_reflective_arpeggio_rh", "wavering_heart_gratitude_chosen_strength": "piano_chordal_moving_rh", "reaffirmed_strength_of_love_positive_determination": "piano_powerful_block_8ths_rh", "hope_dawn_light_gentle_guidance": "piano_reflective_arpeggio_rh", "nature_memory_floating_sensation_forgiveness": "piano_reflective_arpeggio_rh", "future_cooperation_our_path_final_resolve_and_liberation": "piano_powerful_block_8ths_rh"},
            "emotion_to_lh_style_keyword": {"default": "simple_root_lh", "quiet_pain_and_nascent_strength": "piano_sustained_root_lh", "deep_regret_gratitude_and_realization": "piano_walking_bass_like_lh", "acceptance_of_love_and_pain_hopeful_belief": "piano_active_octave_bass_lh", "self_reproach_regret_deep_sadness": "piano_sustained_root_lh", "supported_light_longing_for_rebirth": "piano_walking_bass_like_lh", "reflective_transition_instrumental_passage": "piano_sustained_root_lh", "trial_cry_prayer_unbreakable_heart": "piano_active_octave_bass_lh", "memory_unresolved_feelings_silence": "piano_sustained_root_lh", "wavering_heart_gratitude_chosen_strength": "piano_walking_bass_like_lh", "reaffirmed_strength_of_love_positive_determination": "piano_active_octave_bass_lh", "hope_dawn_light_gentle_guidance": "piano_sustained_root_lh", "nature_memory_floating_sensation_forgiveness": "piano_sustained_root_lh", "future_cooperation_our_path_final_resolve_and_liberation": "piano_active_octave_bass_lh"},
            "style_keyword_to_rhythm_key": {"piano_reflective_arpeggio_rh": "piano_flowing_arpeggio_eighths_rh", "piano_chordal_moving_rh": "piano_chordal_moving_rh_pattern", "piano_powerful_block_8ths_rh": "piano_powerful_block_8ths_rh", "simple_block_rh": "piano_block_quarters_simple", "piano_sustained_root_lh": "piano_sustained_root_lh", "piano_walking_bass_like_lh": "piano_walking_bass_like_lh", "piano_active_octave_bass_lh": "piano_active_octave_bass_lh", "simple_root_lh": "piano_lh_quarter_roots", "default_piano_rh_fallback_rhythm": "default_piano_quarters", "default_piano_lh_fallback_rhythm": "piano_lh_whole_notes"},
            "intensity_to_velocity_ranges": {"low": [50,60,55,65], "medium_low": [55,65,60,70], "medium": [60,70,65,75], "medium_high": [65,80,70,85], "high": [70,85,75,90], "high_to_very_high_then_fade": [75,95,80,100], "default": [60,70,65,75]},
            "default_apply_pedal": True, "default_arp_note_ql": 0.5, "default_rh_voicing_style": "closed", "default_lh_voicing_style": "closed", "default_rh_target_octave": 4, "default_lh_target_octave": 2, "default_rh_num_voices": 3, "default_lh_num_voices": 1,
            "default_piano_humanize": True, "default_piano_humanize_rh": True, "default_piano_humanize_lh": True, "default_piano_humanize_time_var": 0.01, "default_piano_humanize_dur_perc": 0.02, "default_piano_humanize_vel_var": 4, "default_piano_humanize_fbm_time": False, "default_piano_humanize_fbm_scale": 0.005, "default_piano_humanize_style_template": "piano_gentle_arpeggio"
        },
        "drums": {
            "emotion_to_style_key": {"default_style": "default_drum_pattern", "quiet_pain_and_nascent_strength": "no_drums", "deep_regret_gratitude_and_realization": "ballad_soft_kick_snare_8th_hat", "acceptance_of_love_and_pain_hopeful_belief": "anthem_rock_chorus_16th_hat", "self_reproach_regret_deep_sadness": "no_drums_or_sparse_cymbal", "supported_light_longing_for_rebirth": "rock_ballad_build_up_8th_hat", "reflective_transition_instrumental_passage": "no_drums_or_gentle_cymbal_swell", "trial_cry_prayer_unbreakable_heart": "rock_ballad_build_up_8th_hat", "memory_unresolved_feelings_silence": "no_drums", "wavering_heart_gratitude_chosen_strength": "ballad_soft_kick_snare_8th_hat", "reaffirmed_strength_of_love_positive_determination": "anthem_rock_chorus_16th_hat", "hope_dawn_light_gentle_guidance": "no_drums_or_gentle_cymbal_swell", "nature_memory_floating_sensation_forgiveness": "no_drums_or_sparse_chimes", "future_cooperation_our_path_final_resolve_and_liberation": "anthem_rock_chorus_16th_hat"},
            "intensity_to_base_velocity": {"default": [70,80], "low": [55,65], "medium_low": [60,70], "medium": [70,80], "medium_high": [75,85], "high": [85,95], "high_to_very_high_then_fade": [90,105]},
            "default_fill_interval_bars": 4, "default_fill_keys": ["simple_snare_roll_half_bar", "chorus_end_fill"],
            "humanize": True, "humanize_time_var": 0.015, "humanize_dur_perc": 0.03, "humanize_vel_var": 6
        },
        "guitar": {
            "instrument": "AcousticGuitar",
            "emotion_mode_to_style_map": {"default_default": {"style": "strum_basic", "voicing_style": "standard", "rhythm_key": "guitar_default_quarters"}, "ionian_希望": {"style": "strum_basic", "voicing_style": "open", "rhythm_key": "guitar_folk_strum_simple"}, "dorian_悲しみ": {"style": "arpeggio", "voicing_style": "standard", "arpeggio_type": "updown", "arpeggio_note_duration_ql": 0.5, "rhythm_key": "guitar_ballad_arpeggio"}, "aeolian_怒り": {"style": "muted_rhythm", "voicing_style": "power_chord_root_fifth", "rhythm_key": "guitar_rock_mute_16th"}},
            "default_style": "strum_basic", "default_rhythm_category": "guitar_patterns", "default_rhythm_key": "guitar_default_quarters", "default_voicing_style": "standard", "default_num_strings": 6, "default_target_octave": 3, "default_velocity": 70, "default_arpeggio_type": "up", "default_arpeggio_note_duration_ql": 0.5, "default_strum_delay_ql": 0.02, "default_mute_note_duration_ql": 0.1, "default_mute_interval_ql": 0.25,
            "default_humanize": True, "default_humanize_style_template": "default_guitar_subtle", "default_humanize_time_var": 0.015, "default_humanize_dur_perc": 0.04, "default_humanize_vel_var": 6, "default_humanize_fbm_time": False, "default_humanize_fbm_scale": 0.01
        },
        "vocal": {
            "instrument": "Vocalist",
            "data_paths": {
                "midivocal_data_path": "data/vocal_note_data_ore.json", # プロジェクトルートからの相対パス
                "lyrics_text_path": "data/kasi_rist.json",
                "lyrics_timeline_path": "data/lyrics_timeline.json"
            },
            "default_insert_breaths_opt": True, "default_breath_duration_ql_opt": 0.25,
            "default_humanize_opt": True, "default_humanize_template_name": "vocal_ballad_smooth",
            "default_humanize_time_var": 0.02, "default_humanize_dur_perc": 0.04, "default_humanize_vel_var": 5,
            "default_humanize_fbm_time": True, "default_humanize_fbm_scale": 0.01, "default_humanize_fbm_hurst": 0.65
        },
        "chords": {"instrument": "StringInstrument", "chord_voicing_style": "closed", "chord_target_octave": 3, "chord_num_voices": 4, "chord_velocity": 64},
        "melody": {"instrument": "Flute", "rhythm_key": "default_melody_rhythm", "octave_range": [4,5], "density": 0.7},
        "bass": {"instrument": "AcousticBass", "style": "simple_roots", "rhythm_key": "bass_quarter_notes"}
    },
    "output_filename_template": "output_{song_title}.mid"
}

def load_json_file(file_path: Path, description: str) -> Optional[Dict | List]:
    # (変更なし)
    if not file_path.exists(): logger.error(f"{description} not found: {file_path}"); sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        logger.info(f"Loaded {description} from: {file_path}"); return data
    except Exception as e: logger.error(f"Error loading {description} from {file_path}: {e}", exc_info=True); sys.exit(1)
    return None

def translate_keywords_to_params(
        musical_intent: Dict[str, Any],
        chord_block_specific_hints: Dict[str, Any], # Contains "part_settings", "mode_of_block", etc.
        default_instrument_params: Dict[str, Any],
        instrument_name_key: str,
        rhythm_library_all_categories: Dict
) -> Dict[str, Any]:
    # (前回の提案から大きな変更なし、ギターとボーカルの分岐は前回通り)
    params: Dict[str, Any] = default_instrument_params.copy()
    emotion_key = musical_intent.get("emotion", "default").lower()
    intensity_key = musical_intent.get("intensity", "default").lower()
    mode_of_block = chord_block_specific_hints.get("mode_of_block", "major").lower()

    section_instrument_settings = chord_block_specific_hints.get("part_settings", {}).get(instrument_name_key, {})
    params.update(section_instrument_settings)
    logger.debug(f"Translating for {instrument_name_key}: Emo='{emotion_key}', Int='{intensity_key}', Mode='{mode_of_block}', InitialParams='{params}'")

    # --- ピアノ ---
    if instrument_name_key == "piano":
        cfg_piano = DEFAULT_CONFIG["default_part_parameters"]["piano"]
        if "piano_rh_style_keyword" not in params: params["piano_rh_style_keyword"] = cfg_piano.get("emotion_to_rh_style_keyword", {}).get(emotion_key, cfg_piano.get("emotion_to_rh_style_keyword", {}).get("default"))
        if "piano_lh_style_keyword" not in params: params["piano_lh_style_keyword"] = cfg_piano.get("emotion_to_lh_style_keyword", {}).get(emotion_key, cfg_piano.get("emotion_to_lh_style_keyword", {}).get("default"))
        rh_style_kw, lh_style_kw = params.get("piano_rh_style_keyword"), params.get("piano_lh_style_keyword")
        style_to_rhythm_map = cfg_piano.get("style_keyword_to_rhythm_key", {})
        piano_patterns_lib = rhythm_library_all_categories.get("piano_patterns", {})
        params["piano_rh_rhythm_key"] = style_to_rhythm_map.get(rh_style_kw)
        if not params.get("piano_rh_rhythm_key") or params.get("piano_rh_rhythm_key") not in piano_patterns_lib:
             fallback_rh = style_to_rhythm_map.get("default_piano_rh_fallback_rhythm", "default_piano_quarters"); params["piano_rh_rhythm_key"] = fallback_rh
        params["piano_lh_rhythm_key"] = style_to_rhythm_map.get(lh_style_kw)
        if not params.get("piano_lh_rhythm_key") or params.get("piano_lh_rhythm_key") not in piano_patterns_lib:
             fallback_lh = style_to_rhythm_map.get("default_piano_lh_fallback_rhythm", "piano_lh_whole_notes"); params["piano_lh_rhythm_key"] = fallback_lh
        vel_map, def_vel_tuple = cfg_piano.get("intensity_to_velocity_ranges",{}), cfg_piano.get("intensity_to_velocity_ranges",{}).get("default", [60,70,65,75])
        if "piano_velocity_lh" not in params or "piano_velocity_rh" not in params:
            cur_vel_tuple = vel_map.get(intensity_key, def_vel_tuple)
            if isinstance(cur_vel_tuple, Sequence) and len(cur_vel_tuple) == 4:
                if "piano_velocity_lh" not in params: params["piano_velocity_lh"] = random.randint(cur_vel_tuple[0], cur_vel_tuple[1])
                if "piano_velocity_rh" not in params: params["piano_velocity_rh"] = random.randint(cur_vel_tuple[2], cur_vel_tuple[3])
            else:
                if "piano_velocity_lh" not in params: params["piano_velocity_lh"] = random.randint(def_vel_tuple[0], def_vel_tuple[1])
                if "piano_velocity_rh" not in params: params["piano_velocity_rh"] = random.randint(def_vel_tuple[2], def_vel_tuple[3])
        for suffix in ["apply_pedal", "arp_note_ql", "rh_voicing_style", "lh_voicing_style", "rh_target_octave", "lh_target_octave", "rh_num_voices", "lh_num_voices", "piano_humanize", "piano_humanize_rh", "piano_humanize_lh", "piano_humanize_time_var", "piano_humanize_dur_perc", "piano_humanize_vel_var", "piano_humanize_fbm_time", "piano_humanize_fbm_scale", "piano_humanize_style_template"]:
            if f"piano_{suffix}" not in params: params[f"piano_{suffix}"] = cfg_piano.get(f"default_{suffix}")
    # --- ドラム ---
    elif instrument_name_key == "drums":
        cfg_drums = DEFAULT_CONFIG["default_part_parameters"]["drums"]
        if "drum_style_key" not in params: params["drum_style_key"] = cfg_drums.get("emotion_to_style_key", {}).get(emotion_key, cfg_drums.get("emotion_to_style_key", {}).get("default_style"))
        drum_patterns_lib = rhythm_library_all_categories.get("drum_patterns", {})
        if not params.get("drum_style_key") or params.get("drum_style_key") not in drum_patterns_lib: params["drum_style_key"] = "default_drum_pattern"
        if "drum_base_velocity" not in params:
            vel_map_drums, def_drum_vel_range = cfg_drums.get("intensity_to_base_velocity",{}), cfg_drums.get("intensity_to_base_velocity",{}).get("default", [70,80])
            cur_drum_vel_range = vel_map_drums.get(intensity_key, def_drum_vel_range)
            if isinstance(cur_drum_vel_range, Sequence) and len(cur_drum_vel_range) == 2: params["drum_base_velocity"] = random.randint(cur_drum_vel_range[0], cur_drum_vel_range[1])
            else: params["drum_base_velocity"] = random.randint(def_drum_vel_range[0], def_drum_vel_range[1])
        if "drum_fill_interval_bars" not in params: params["drum_fill_interval_bars"] = cfg_drums.get("default_fill_interval_bars")
        if "drum_fill_keys" not in params: params["drum_fill_keys"] = cfg_drums.get("default_fill_keys")
        for h_key in ["humanize", "humanize_time_var", "humanize_dur_perc", "humanize_vel_var"]:
             if h_key not in params: params[h_key] = cfg_drums.get(h_key, False if h_key == "humanize" else 0.01)
    # --- ギター ---
    elif instrument_name_key == "guitar":
        cfg_guitar = DEFAULT_CONFIG["default_part_parameters"]["guitar"]
        emotion_mode_key = f"{mode_of_block}_{emotion_key}"
        style_map = cfg_guitar.get("emotion_mode_to_style_map", {})
        specific_style_config = style_map.get(emotion_mode_key, style_map.get(emotion_key, style_map.get(f"default_{mode_of_block}", style_map.get("default_default", {}))))
        param_keys_guitar = ["guitar_style", "guitar_rhythm_key", "guitar_voicing_style", "guitar_num_strings", "guitar_target_octave", "guitar_velocity", "arpeggio_type", "arpeggio_note_duration_ql", "strum_delay_ql", "mute_note_duration_ql", "mute_interval_ql", "guitar_humanize", "guitar_humanize_style_template", "guitar_humanize_time_var", "guitar_humanize_dur_perc", "guitar_humanize_vel_var", "guitar_humanize_fbm_time", "guitar_humanize_fbm_scale"]
        for p_key in param_keys_guitar:
            if p_key not in params:
                specific_key = p_key.replace("guitar_", "")
                params[p_key] = specific_style_config.get(specific_key, cfg_guitar.get(f"default_{specific_key}"))
        guitar_rhythm_cat = cfg_guitar.get("default_rhythm_category", "guitar_patterns")
        guitar_rhythm_patterns_lib = rhythm_library_all_categories.get(guitar_rhythm_cat, {})
        if not params.get("guitar_rhythm_key") or params.get("guitar_rhythm_key") not in guitar_rhythm_patterns_lib:
            params["guitar_rhythm_key"] = cfg_guitar.get("default_rhythm_key", "guitar_default_quarters")
    # --- ボーカル ---
    elif instrument_name_key == "vocal":
        cfg_vocal = DEFAULT_CONFIG["default_part_parameters"]["vocal"]
        vocal_param_keys = ["insert_breaths_opt", "breath_duration_ql_opt", "humanize_opt", "humanize_template_name", "humanize_time_var", "humanize_dur_perc", "humanize_vel_var", "humanize_fbm_time", "humanize_fbm_scale", "humanize_fbm_hurst"]
        for p_key_vocal in vocal_param_keys:
            if p_key_vocal not in params:
                params[p_key_vocal] = cfg_vocal.get(f"default_{p_key_vocal}")
    # --- メロディ ---
    elif instrument_name_key == "melody":
        cfg_melody = DEFAULT_CONFIG["default_part_parameters"]["melody"]
        melody_rhythms_lib = rhythm_library_all_categories.get("melody_rhythms", {})
        if "rhythm_key" not in params: params["rhythm_key"] = cfg_melody.get("rhythm_key_map", {}).get(emotion_key, cfg_melody.get("rhythm_key_map", {}).get("default", "default_melody_rhythm"))
        if not params.get("rhythm_key") or params.get("rhythm_key") not in melody_rhythms_lib: params["rhythm_key"] = "default_melody_rhythm"
        if "octave_range" not in params: params["octave_range"] = cfg_melody.get("octave_range")
        if "density" not in params: params["density"] = cfg_melody.get("density")
    # --- ベース ---
    elif instrument_name_key == "bass":
        cfg_bass = DEFAULT_CONFIG["default_part_parameters"]["bass"]
        bass_lines_lib = rhythm_library_all_categories.get("bass_lines", {})
        if "style" not in params: params["style"] = cfg_bass.get("style_map",{}).get(emotion_key, cfg_bass.get("style_map",{}).get("default", "simple_roots"))
        if "rhythm_key" not in params: params["rhythm_key"] = cfg_bass.get("rhythm_key_map", {}).get(emotion_key, cfg_bass.get("rhythm_key_map", {}).get("default", "bass_quarter_notes"))
        if not params.get("rhythm_key") or params.get("rhythm_key") not in bass_lines_lib: params["rhythm_key"] = "bass_quarter_notes"

    # ブロック固有ヒントで最終上書き
    block_instrument_specific_hints = chord_block_specific_hints.get(instrument_name_key, {})
    if isinstance(block_instrument_specific_hints, dict): params.update(block_instrument_specific_hints)
    if instrument_name_key == "drums" and "drum_fill" in chord_block_specific_hints:
        params["drum_fill_key_override"] = chord_block_specific_hints["drum_fill"]
        
    logger.info(f"Final params for [{instrument_name_key}] (Emo: {emotion_key}, Int: {intensity_key}, Mode: {mode_of_block}) -> {params}")
    return params

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_lib_all: Dict) -> List[Dict]:
    # (変更なし、mode_of_block の設定は前回通り)
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
        sec_part_settings_for_all_instruments = sec_info.get("part_settings", {}) 
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
            blk_hints_for_translate = {"part_settings": sec_part_settings_for_all_instruments.copy()}
            current_block_mode = c_def.get("mode", sec_m)
            blk_hints_for_translate["mode_of_block"] = current_block_mode
            for k_hint, v_hint in c_def.items():
                if k_hint not in ["label","duration_beats","order","musical_intent","part_settings","tensions_to_add", "emotion", "intensity", "mode"]:
                    blk_hints_for_translate[k_hint] = v_hint
            blk_data = {"offset": current_abs_offset, "q_length": dur_b, "chord_label": c_lbl, "section_name": sec_name, "tonic_of_section": sec_t, "mode": current_block_mode, "tensions_to_add": c_def.get("tensions_to_add",[]), "is_first_in_section":(c_idx==0), "is_last_in_section":(c_idx==len(chord_prog)-1), "part_params":{}}
            for p_key_name, generate_flag in main_config.get("parts_to_generate", {}).items():
                if generate_flag:
                    default_params_for_instrument = main_config["default_part_parameters"].get(p_key_name, {})
                    blk_data["part_params"][p_key_name] = translate_keywords_to_params(blk_intent, blk_hints_for_translate, default_params_for_instrument, p_key_name, rhythm_lib_all)
            processed_stream.append(blk_data)
            current_abs_offset += dur_b
    logger.info(f"Prepared {len(processed_stream)} blocks. Total duration: {current_abs_offset:.2f} beats.")
    return processed_stream

def run_composition(cli_args: argparse.Namespace, main_cfg: Dict, chordmap: Dict, rhythm_lib_all: Dict):
    # (ボーカルデータロードとVocalGenerator呼び出し部分は前回提案通り)
    logger.info("=== Running Main Composition Workflow ===")
    final_score = stream.Score()
    final_score.insert(0, tempo.MetronomeMark(number=main_cfg["global_tempo"]))
    try:
        ts_obj_score = get_time_signature_object(main_cfg["global_time_signature"])
        final_score.insert(0, ts_obj_score)
        key_t, key_m = main_cfg["global_key_tonic"], main_cfg["global_key_mode"]
        if chordmap.get("sections"):
            try:
                first_sec_name = sorted(chordmap.get("sections", {}).items(), key=lambda item: item[1].get("order",float('inf')))[0][0]
                first_sec_info = chordmap.get("sections",{})[first_sec_name]
                key_t = first_sec_info.get("tonic", key_t); key_m = first_sec_info.get("mode", key_m)
            except IndexError: logger.warning("No sections for initial key.")
        final_score.insert(0, key.Key(key_t, key_m.lower()))
    except Exception as e: 
        logger.error(f"Error setting score globals: {e}. Defaults.", exc_info=True)
        if not final_score.getElementsByClass(meter.TimeSignature): final_score.insert(0,meter.TimeSignature("4/4"))
        if not final_score.getElementsByClass(key.Key): final_score.insert(0,key.Key("C"))
    proc_blocks = prepare_processed_stream(chordmap, main_cfg, rhythm_lib_all)
    if not proc_blocks: logger.error("No blocks to process. Abort."); return
    cv_inst = ChordVoicer(global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    gens: Dict[str, Any] = {}

    # Instantiate generators
    if main_cfg["parts_to_generate"].get("piano"): gens["piano"] = PianoGenerator(rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("piano_patterns", {})), chord_voicer_instance=cv_inst, global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    if main_cfg["parts_to_generate"].get("drums"): gens["drums"] = DrumGenerator(drum_pattern_library=cast(Dict[str,Dict[str,Any]], rhythm_lib_all.get("drum_patterns", {})), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    if main_cfg["parts_to_generate"].get("guitar"):
        guitar_cfg = main_cfg["default_part_parameters"].get("guitar", {})
        gens["guitar"] = GuitarGenerator(rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get(guitar_cfg.get("default_rhythm_category","guitar_patterns"), {})), default_instrument=m21instrument.fromString(guitar_cfg.get("instrument", "AcousticGuitar")), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    if main_cfg["parts_to_generate"].get("vocal"):
        vocal_cfg = main_cfg["default_part_parameters"].get("vocal", {})
        vocal_data_paths = vocal_cfg.get("data_paths", {})
        midivocal_path_str = cli_args.vocal_mididata_path if cli_args.vocal_mididata_path else chordmap.get("global_settings", {}).get("vocal_mididata_path", vocal_data_paths.get("midivocal_data_path"))
        lyrics_path_str = cli_args.vocal_lyrics_path if cli_args.vocal_lyrics_path else chordmap.get("global_settings", {}).get("vocal_lyrics_path", vocal_data_paths.get("lyrics_text_path"))
        timeline_path_str = chordmap.get("global_settings", {}).get("vocal_timeline_path", vocal_data_paths.get("lyrics_timeline_path")) # Currently unused by VocalGenerator
        midivocal_data = load_json_file(Path(midivocal_path_str), "Vocal MIDI Data") if midivocal_path_str else None
        kasi_rist_data = load_json_file(Path(lyrics_path_str), "Lyrics List Data") if lyrics_path_str else None
        lyrics_timeline_data = load_json_file(Path(timeline_path_str), "Lyrics Timeline Data") if timeline_path_str else None
        if midivocal_data and kasi_rist_data:
            gens["vocal"] = VocalGenerator(default_instrument=m21instrument.fromString(vocal_cfg.get("instrument", "Vocalist")), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
        else: logger.error("Vocal generation skipped: Missing MIDI or lyrics data."); main_cfg["parts_to_generate"]["vocal"] = False
    if main_cfg["parts_to_generate"].get("chords"): gens["chords"] = cv_inst
    if main_cfg["parts_to_generate"].get("melody"): gens["melody"] = MelodyGenerator(rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("melody_rhythms", {})), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"], global_key_signature_tonic=main_cfg["global_key_tonic"], global_key_signature_mode=main_cfg["global_key_mode"])
    if main_cfg["parts_to_generate"].get("bass"): gens["bass"] = BassGenerator(rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("bass_lines", {})), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])

    # パート生成ループ
    for p_n, p_g_inst in gens.items():
        if p_g_inst and main_cfg["parts_to_generate"].get(p_n):
            logger.info(f"Generating {p_n} part...")
            try:
                if p_n == "vocal":
                    # VocalGeneratorのcomposeに必要なパラメータを構築
                    vocal_params_for_compose = proc_blocks[0]["part_params"].get("vocal", main_cfg["default_part_parameters"].get("vocal", {})) # ★ ブロックパラメータを参照
                    part_obj = p_g_inst.compose(
                        midivocal_data=cast(List[Dict], midivocal_data),
                        kasi_rist_data=cast(Dict[str, List[str]], kasi_rist_data),
                        processed_chord_stream=proc_blocks,
                        insert_breaths_opt=vocal_params_for_compose.get("insert_breaths_opt", True),
                        breath_duration_ql_opt=vocal_params_for_compose.get("breath_duration_ql_opt", 0.25),
                        humanize_opt=vocal_params_for_compose.get("humanize_opt", True),
                        humanize_template_name=vocal_params_for_compose.get("humanize_template_name"),
                        humanize_custom_params={k.replace("humanize_", ""):v for k,v in vocal_params_for_compose.items() if k.startswith("humanize_") and not k.endswith("_template_name") and not k.endswith("_opt")}
                    )
                else:
                    part_obj = p_g_inst.compose(proc_blocks)
                
                if isinstance(part_obj, stream.Score) and part_obj.parts:
                    for sub_part in part_obj.parts: 
                        if sub_part.flatten().notesAndRests: final_score.insert(0, sub_part)
                elif isinstance(part_obj, stream.Part) and part_obj.flatten().notesAndRests:
                    final_score.insert(0, sub_part) # ここがバグでした。part_obj を使うべき
                logger.info(f"{p_n} part generated.")
            except Exception as e_gen: logger.error(f"Error in {p_n} generation: {e_gen}", exc_info=True)

    title = chordmap.get("project_title","untitled").replace(" ","_").lower()
    out_fname_template = main_cfg.get("output_filename_template", "output_{song_title}.mid")
    actual_out_fname = cli_args.output_filename if cli_args.output_filename else out_fname_template.format(song_title=title)
    out_fpath = cli_args.output_dir / actual_out_fname
    out_fpath.parent.mkdir(parents=True,exist_ok=True)
    try:
        if final_score.flatten().notesAndRests: final_score.write('midi',fp=str(out_fpath)); logger.info(f"🎉 MIDI: {out_fpath}")
        else: logger.warning(f"Score empty. No MIDI to {out_fpath}.")
    except Exception as e_w: logger.error(f"MIDI write error: {e_w}", exc_info=True)

def main_cli():
    # (コマンドライン引数処理は前回提案から変更なし、ボーカルデータパス引数は有効)
    parser = argparse.ArgumentParser(description="Modular Music Composer (Keyword-Driven)")
    parser.add_argument("chordmap_file", type=Path, help="Path to the chordmap JSON file.")
    parser.add_argument("rhythm_library_file", type=Path, help="Path to the rhythm library JSON file.")
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Directory to save the output MIDI file.")
    parser.add_argument("--output-filename", type=str, help="Custom filename for the output MIDI (optional).")
    parser.add_argument("--settings-file", type=Path, help="Path to a custom settings JSON file to override defaults (optional).")
    parser.add_argument("--tempo", type=int, help="Override the global tempo defined in settings or chordmap.")
    parser.add_argument("--vocal-mididata-path", type=Path, help="Path to vocal MIDI data JSON.")
    parser.add_argument("--vocal-lyrics-path", type=Path, help="Path to lyrics list JSON.")
    default_parts_to_generate = DEFAULT_CONFIG.get("parts_to_generate", {})
    for part_key, default_state in default_parts_to_generate.items():
        arg_name_for_part = f"generate_{part_key}"
        if default_state: parser.add_argument(f"--no-{part_key}", action="store_false", dest=arg_name_for_part, help=f"Disable generation of the {part_key} part.")
        else: parser.add_argument(f"--include-{part_key}", action="store_true", dest=arg_name_for_part, help=f"Enable generation of the {part_key} part.")
    parser.set_defaults(**{f"generate_{k}": v for k, v in default_parts_to_generate.items()})
    args = parser.parse_args()
    effective_config = json.loads(json.dumps(DEFAULT_CONFIG))
    if args.settings_file and args.settings_file.exists():
        custom_settings_data = load_json_file(args.settings_file, "Custom settings")
        if custom_settings_data and isinstance(custom_settings_data, dict):
            def _deep_update(target_dict, source_dict):
                for key, value in source_dict.items():
                    if isinstance(value, dict) and key in target_dict and isinstance(target_dict[key], dict): _deep_update(target_dict[key], value)
                    else: target_dict[key] = value
            _deep_update(effective_config, custom_settings_data)
    for part_key in default_parts_to_generate.keys():
        arg_name_for_part = f"generate_{part_key}"
        if hasattr(args, arg_name_for_part): effective_config["parts_to_generate"][part_key] = getattr(args, arg_name_for_part)
    if args.vocal_mididata_path: effective_config["default_part_parameters"]["vocal"]["data_paths"]["midivocal_data_path"] = str(args.vocal_mididata_path)
    if args.vocal_lyrics_path: effective_config["default_part_parameters"]["vocal"]["data_paths"]["lyrics_text_path"] = str(args.vocal_lyrics_path)
    chordmap_data = load_json_file(args.chordmap_file, "Chordmap")
    rhythm_library_data = load_json_file(args.rhythm_library_file, "Rhythm Library")
    if not chordmap_data or not rhythm_library_data: logger.critical("Data files missing. Exit."); sys.exit(1)
    cm_globals = chordmap_data.get("global_settings", {})
    effective_config["global_tempo"] = cm_globals.get("tempo", effective_config["global_tempo"])
    effective_config["global_time_signature"] = cm_globals.get("time_signature", effective_config["global_time_signature"])
    effective_config["global_key_tonic"] = cm_globals.get("key_tonic", effective_config["global_key_tonic"])
    effective_config["global_key_mode"] = cm_globals.get("key_mode", effective_config["global_key_mode"])
    if args.tempo is not None: effective_config["global_tempo"] = args.tempo
    logger.info(f"Final Effective Config: {json.dumps(effective_config, indent=2, ensure_ascii=False)}")
    try: run_composition(args, effective_config, cast(Dict,chordmap_data), cast(Dict,rhythm_library_data))
    except SystemExit: raise
    except Exception as e_run: logger.critical(f"Critical error in main run: {e_run}", exc_info=True); sys.exit(1)

if __name__ == "__main__":
    main_cli()
# --- END OF FILE modular_composer.py ---
