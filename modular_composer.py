# --- START OF FILE modular_composer.py (2023-05-25 最終調整案) ---
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
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label
    # HUMANIZATION_TEMPLATES は humanizer.py から直接参照せず、各ジェネレータが内部で持つか、
    # あるいは humanizer.py の apply_humanization_to_part にテンプレート名を渡すだけで良い。
    # from utilities.humanizer import HUMANIZATION_TEMPLATES # 直接は使わない想定

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
    "global_tempo": 100, "global_time_signature": "4/4", "global_key_tonic": "C", "global_key_mode": "major",
    "parts_to_generate": {
        "piano": True, "drums": True, "guitar": True, "bass": True, # bassもTrueに
        "chords": True, "melody": False, "vocal": True
    },
    "default_part_parameters": {
        "piano": {
            "instrument": "Piano", # 楽器名を指定できるように
            "emotion_to_rh_style_keyword": {"default": "simple_block_rh", "quiet_pain_and_nascent_strength": "piano_reflective_arpeggio_rh", "deep_regret_gratitude_and_realization": "piano_chordal_moving_rh", "acceptance_of_love_and_pain_hopeful_belief": "piano_powerful_block_8ths_rh", "self_reproach_regret_deep_sadness": "piano_reflective_arpeggio_rh", "supported_light_longing_for_rebirth": "piano_chordal_moving_rh", "reflective_transition_instrumental_passage": "piano_reflective_arpeggio_rh", "trial_cry_prayer_unbreakable_heart": "piano_powerful_block_8ths_rh", "memory_unresolved_feelings_silence": "piano_reflective_arpeggio_rh", "wavering_heart_gratitude_chosen_strength": "piano_chordal_moving_rh", "reaffirmed_strength_of_love_positive_determination": "piano_powerful_block_8ths_rh", "hope_dawn_light_gentle_guidance": "piano_reflective_arpeggio_rh", "nature_memory_floating_sensation_forgiveness": "piano_reflective_arpeggio_rh", "future_cooperation_our_path_final_resolve_and_liberation": "piano_powerful_block_8ths_rh"},
            "emotion_to_lh_style_keyword": {"default": "simple_root_lh", "quiet_pain_and_nascent_strength": "piano_sustained_root_lh", "deep_regret_gratitude_and_realization": "piano_walking_bass_like_lh", "acceptance_of_love_and_pain_hopeful_belief": "piano_active_octave_bass_lh", "self_reproach_regret_deep_sadness": "piano_sustained_root_lh", "supported_light_longing_for_rebirth": "piano_walking_bass_like_lh", "reflective_transition_instrumental_passage": "piano_sustained_root_lh", "trial_cry_prayer_unbreakable_heart": "piano_active_octave_bass_lh", "memory_unresolved_feelings_silence": "piano_sustained_root_lh", "wavering_heart_gratitude_chosen_strength": "piano_walking_bass_like_lh", "reaffirmed_strength_of_love_positive_determination": "piano_active_octave_bass_lh", "hope_dawn_light_gentle_guidance": "piano_sustained_root_lh", "nature_memory_floating_sensation_forgiveness": "piano_sustained_root_lh", "future_cooperation_our_path_final_resolve_and_liberation": "piano_active_octave_bass_lh"},
            "style_keyword_to_rhythm_key": {"piano_reflective_arpeggio_rh": "piano_flowing_arpeggio_eighths_rh", "piano_chordal_moving_rh": "piano_chordal_moving_rh_pattern", "piano_powerful_block_8ths_rh": "piano_powerful_block_8ths_rh", "simple_block_rh": "piano_block_quarters_simple", "piano_sustained_root_lh": "piano_sustained_root_lh", "piano_walking_bass_like_lh": "piano_walking_bass_like_lh", "piano_active_octave_bass_lh": "piano_active_octave_bass_lh", "simple_root_lh": "piano_lh_quarter_roots", "default_piano_rh_fallback_rhythm": "default_piano_quarters", "default_piano_lh_fallback_rhythm": "piano_lh_whole_notes"},
            "intensity_to_velocity_ranges": {"low": [50,60,55,65], "medium_low": [55,65,60,70], "medium": [60,70,65,75], "medium_high": [65,80,70,85], "high": [70,85,75,90], "high_to_very_high_then_fade": [75,95,80,100], "default": [60,70,65,75]},
            "default_apply_pedal": True, "default_arp_note_ql": 0.5, "default_rh_voicing_style": "closed", "default_lh_voicing_style": "closed", "default_rh_target_octave": 4, "default_lh_target_octave": 2, "default_rh_num_voices": 3, "default_lh_num_voices": 1,
            "default_humanize": True, "default_humanize_rh": True, "default_humanize_lh": True, # ★ プレフィックスなしの humanize も追加
            "default_humanize_style_template": "piano_gentle_arpeggio", # ★ 共通のテンプレートキー
            "default_humanize_time_var": 0.01, "default_humanize_dur_perc": 0.02, "default_humanize_vel_var": 4,
            "default_humanize_fbm_time": False, "default_humanize_fbm_scale": 0.005, "default_humanize_fbm_hurst": 0.7
        },
        "drums": {
            "instrument": "Percussion",
            "emotion_to_style_key": {"default_style": "default_drum_pattern", "quiet_pain_and_nascent_strength": "no_drums", "deep_regret_gratitude_and_realization": "ballad_soft_kick_snare_8th_hat", "acceptance_of_love_and_pain_hopeful_belief": "anthem_rock_chorus_16th_hat", "self_reproach_regret_deep_sadness": "no_drums_or_sparse_cymbal", "supported_light_longing_for_rebirth": "rock_ballad_build_up_8th_hat", "reflective_transition_instrumental_passage": "no_drums_or_gentle_cymbal_swell", "trial_cry_prayer_unbreakable_heart": "rock_ballad_build_up_8th_hat", "memory_unresolved_feelings_silence": "no_drums", "wavering_heart_gratitude_chosen_strength": "ballad_soft_kick_snare_8th_hat", "reaffirmed_strength_of_love_positive_determination": "anthem_rock_chorus_16th_hat", "hope_dawn_light_gentle_guidance": "no_drums_or_gentle_cymbal_swell", "nature_memory_floating_sensation_forgiveness": "no_drums_or_sparse_chimes", "future_cooperation_our_path_final_resolve_and_liberation": "anthem_rock_chorus_16th_hat"},
            "intensity_to_base_velocity": {"default": [70,80], "low": [55,65], "medium_low": [60,70], "medium": [70,80], "medium_high": [75,85], "high": [85,95], "high_to_very_high_then_fade": [90,105]},
            "default_fill_interval_bars": 4, "default_fill_keys": ["simple_snare_roll_half_bar", "chorus_end_fill"],
            "default_humanize": True, "default_humanize_style_template": "drum_loose_fbm", # ★ 共通キー
            "default_humanize_time_var": 0.015, "default_humanize_dur_perc": 0.03, "default_humanize_vel_var": 6,
            "default_humanize_fbm_time": True, "default_humanize_fbm_scale": 0.01, "default_humanize_fbm_hurst": 0.6
        },
        "guitar": {
            "instrument": "AcousticGuitar",
            "emotion_mode_to_style_map": {"default_default": {"style": "strum_basic", "voicing_style": "standard", "rhythm_key": "guitar_default_quarters"}, "ionian_希望": {"style": "strum_basic", "voicing_style": "open", "rhythm_key": "guitar_folk_strum_simple"}, "dorian_悲しみ": {"style": "arpeggio", "voicing_style": "standard", "arpeggio_type": "updown", "arpeggio_note_duration_ql": 0.5, "rhythm_key": "guitar_ballad_arpeggio"}, "aeolian_怒り": {"style": "muted_rhythm", "voicing_style": "power_chord_root_fifth", "rhythm_key": "guitar_rock_mute_16th"}},
            "default_style": "strum_basic", "default_rhythm_category": "guitar_patterns", "default_rhythm_key": "guitar_default_quarters", "default_voicing_style": "standard", "default_num_strings": 6, "default_target_octave": 3, "default_velocity": 70, "default_arpeggio_type": "up", "default_arpeggio_note_duration_ql": 0.5, "default_strum_delay_ql": 0.02, "default_mute_note_duration_ql": 0.1, "default_mute_interval_ql": 0.25,
            "default_humanize": True, "default_humanize_style_template": "default_guitar_subtle", # ★ 共通キー
            "default_humanize_time_var": 0.015, "default_humanize_dur_perc": 0.04, "default_humanize_vel_var": 6,
            "default_humanize_fbm_time": False, "default_humanize_fbm_scale": 0.01, "default_humanize_fbm_hurst": 0.7
        },
        "vocal": {
            "instrument": "Vocalist",
            "data_paths": {"midivocal_data_path": "data/vocal_note_data_ore.json", "lyrics_text_path": "data/kasi_rist.json", "lyrics_timeline_path": "data/lyrics_timeline.json"},
            "default_insert_breaths_opt": True, "default_breath_duration_ql_opt": 0.25,
            "default_humanize_opt": True, "default_humanize_template_name": "vocal_ballad_smooth", # ★ 共通キー (humanize_opt は残す)
            "default_humanize_time_var": 0.02, "default_humanize_dur_perc": 0.04, "default_humanize_vel_var": 5,
            "default_humanize_fbm_time": True, "default_humanize_fbm_scale": 0.01, "default_humanize_fbm_hurst": 0.65
        },
        "bass": {
            "instrument": "AcousticBass", "default_style": "simple_roots", "default_rhythm_key": "bass_quarter_notes",
            "default_octave": 2, "default_velocity": 70,
            "default_humanize": True, "default_humanize_style_template": "default_subtle", # ★ 共通キー
            "default_humanize_time_var": 0.01, "default_humanize_dur_perc": 0.03, "default_humanize_vel_var": 5
        },
        "melody": {
            "instrument": "Flute", "default_rhythm_key": "default_melody_rhythm", "default_octave_range": [4,5], "default_density": 0.7, "default_velocity": 75,
            "default_humanize": True, "default_humanize_style_template": "default_subtle", # ★ 共通キー
            "default_humanize_time_var": 0.01, "default_humanize_dur_perc": 0.02, "default_humanize_vel_var": 4
        },
        "chords": {"instrument": "StringInstrument", "chord_voicing_style": "closed", "chord_target_octave": 3, "chord_num_voices": 4, "chord_velocity": 64}
    },
    "output_filename_template": "output_{song_title}.mid"
}

def load_json_file(file_path: Path, description: str) -> Optional[Dict | List]:
    if not file_path.exists(): logger.error(f"{description} not found: {file_path}"); sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        logger.info(f"Loaded {description} from: {file_path}"); return data
    except Exception as e: logger.error(f"Error loading {description} from {file_path}: {e}", exc_info=True); sys.exit(1)
    return None

def _get_humanize_params(params_from_chordmap: Dict[str, Any], default_cfg_instrument: Dict[str, Any], instrument_prefix: str) -> Dict[str, Any]:
    """ヒューマナイズ関連のパラメータを解決するヘルパー関数"""
    humanize_final_params = {}
    # humanize_opt (または {instrument_prefix}_humanize)
    humanize_flag = params_from_chordmap.get(f"{instrument_prefix}_humanize", params_from_chordmap.get("humanize", default_cfg_instrument.get(f"default_humanize", False)))
    humanize_final_params["humanize_opt"] = bool(humanize_flag) # boolにキャスト

    if humanize_final_params["humanize_opt"]:
        humanize_final_params["template_name"] = params_from_chordmap.get(f"{instrument_prefix}_humanize_style_template", default_cfg_instrument.get("default_humanize_style_template"))
        
        # 個別パラメータ (time_var, dur_perc, vel_var, fbm_time, fbm_scale, fbm_hurst)
        individual_h_keys = ["time_var", "dur_perc", "vel_var", "fbm_time", "fbm_scale", "fbm_hurst"]
        custom_overrides = {}
        for h_key_suffix in individual_h_keys:
            # params_from_chordmap から "guitar_humanize_time_var" のようなキーで探す
            # または、プレフィックスなしの "humanize_time_var" も見る (drumsのような場合)
            val_from_map = params_from_chordmap.get(f"{instrument_prefix}_humanize_{h_key_suffix}", params_from_chordmap.get(f"humanize_{h_key_suffix}"))
            if val_from_map is not None:
                custom_overrides[h_key_suffix] = val_from_map
            else: # なければ DEFAULT_CONFIG から
                custom_overrides[h_key_suffix] = default_cfg_instrument.get(f"default_humanize_{h_key_suffix}")
        humanize_final_params["custom_params"] = custom_overrides
    return humanize_final_params


def translate_keywords_to_params(
        musical_intent: Dict[str, Any], chord_block_specific_hints: Dict[str, Any],
        default_instrument_params: Dict[str, Any], instrument_name_key: str,
        rhythm_library_all_categories: Dict
) -> Dict[str, Any]:
    params: Dict[str, Any] = default_instrument_params.copy()
    emotion_key = musical_intent.get("emotion", "default").lower()
    intensity_key = musical_intent.get("intensity", "default").lower()
    mode_of_block = chord_block_specific_hints.get("mode_of_block", "major").lower()

    section_instrument_settings = chord_block_specific_hints.get("part_settings", {}).get(instrument_name_key, {})
    params.update(section_instrument_settings) # セクション設定でまず上書き

    # --- 汎用的なヒューマナイズパラメータの解決 ---
    # 各楽器の分岐の前に、共通のヒューマナイズパラメータを解決しておく
    # params (chordmapからの値を含む) と default_instrument_params (DEFAULT_CONFIGの値) を渡す
    humanize_resolved_params = _get_humanize_params(params, default_instrument_params, instrument_name_key)
    params.update(humanize_resolved_params) # 解決済みのヒューマナイズパラメータを params にマージ

    logger.debug(f"Translating for {instrument_name_key}: Emo='{emotion_key}', Int='{intensity_key}', Mode='{mode_of_block}', InitialParams='{params}'")

    if instrument_name_key == "piano":
        cfg_piano = DEFAULT_CONFIG["default_part_parameters"]["piano"] # 参照用
        # スタイルとリズムキー (前回同様)
        if "piano_rh_style_keyword" not in params: params["piano_rh_style_keyword"] = cfg_piano.get("emotion_to_rh_style_keyword", {}).get(emotion_key, cfg_piano.get("emotion_to_rh_style_keyword", {}).get("default"))
        if "piano_lh_style_keyword" not in params: params["piano_lh_style_keyword"] = cfg_piano.get("emotion_to_lh_style_keyword", {}).get(emotion_key, cfg_piano.get("emotion_to_lh_style_keyword", {}).get("default"))
        # ... (リズムキー解決、ベロシティ解決は前回同様) ...
        # その他のピアノ固有パラメータ
        for suffix in ["apply_pedal", "arp_note_ql", "rh_voicing_style", "lh_voicing_style", "rh_target_octave", "lh_target_octave", "rh_num_voices", "lh_num_voices"]:
            param_name = f"piano_{suffix}"
            if param_name not in params: params[param_name] = cfg_piano.get(f"default_{suffix}")
        # ピアノ固有のヒューマナイズパラメータ (RH/LH別など) があればここでさらに解決
        params["humanize_rh_opt"] = params.get("piano_humanize_rh", params.get("humanize_opt", False))
        params["humanize_lh_opt"] = params.get("piano_humanize_lh", params.get("humanize_opt", False))


    elif instrument_name_key == "drums":
        cfg_drums = DEFAULT_CONFIG["default_part_parameters"]["drums"]
        if "drum_style_key" not in params: params["drum_style_key"] = cfg_drums.get("emotion_to_style_key", {}).get(emotion_key, cfg_drums.get("emotion_to_style_key", {}).get("default_style"))
        # ... (リズムキー解決、ベロシティ解決は前回同様) ...
        if "drum_fill_interval_bars" not in params: params["drum_fill_interval_bars"] = cfg_drums.get("default_fill_interval_bars")
        if "drum_fill_keys" not in params: params["drum_fill_keys"] = cfg_drums.get("default_fill_keys")

    elif instrument_name_key == "guitar":
        cfg_guitar = DEFAULT_CONFIG["default_part_parameters"]["guitar"]
        emotion_mode_key = f"{mode_of_block}_{emotion_key}"
        style_map = cfg_guitar.get("emotion_mode_to_style_map", {})
        specific_style_config = style_map.get(emotion_mode_key, style_map.get(emotion_key, style_map.get(f"default_{mode_of_block}", style_map.get("default_default", {}))))
        # ... (ギター固有パラメータの解決は前回同様) ...
        param_keys_guitar = ["guitar_style", "guitar_rhythm_key", "guitar_voicing_style", "guitar_num_strings", "guitar_target_octave", "guitar_velocity", "arpeggio_type", "arpeggio_note_duration_ql", "strum_delay_ql", "mute_note_duration_ql", "mute_interval_ql"]
        for p_key in param_keys_guitar:
            if p_key not in params:
                specific_key = p_key.replace("guitar_", "")
                params[p_key] = specific_style_config.get(specific_key, cfg_guitar.get(f"default_{specific_key}"))
        # ... (リズムキーのフォールバック) ...

    elif instrument_name_key == "vocal":
        cfg_vocal = DEFAULT_CONFIG["default_part_parameters"]["vocal"]
        # data_paths は run_composition で解決するのでここでは不要
        vocal_param_keys = ["insert_breaths_opt", "breath_duration_ql_opt"] # ヒューマナイズ以外
        for p_key_vocal in vocal_param_keys:
            if p_key_vocal not in params:
                params[p_key_vocal] = cfg_vocal.get(f"default_{p_key_vocal}")
    
    elif instrument_name_key == "bass":
        cfg_bass = DEFAULT_CONFIG["default_part_parameters"]["bass"]
        if "style" not in params: params["style"] = cfg_bass.get("style_map",{}).get(emotion_key, cfg_bass.get("style_map",{}).get("default", "simple_roots")) # style は bass_generator が解釈
        if "rhythm_key" not in params: params["rhythm_key"] = cfg_bass.get("rhythm_key_map", {}).get(emotion_key, cfg_bass.get("rhythm_key_map", {}).get("default", "bass_quarter_notes"))
        # ... (リズムキーフォールバック、その他のベース固有パラメータ) ...
        if "octave" not in params: params["octave"] = cfg_bass.get("default_octave")
        if "velocity" not in params: params["velocity"] = cfg_bass.get("default_velocity")


    elif instrument_name_key == "melody":
        cfg_melody = DEFAULT_CONFIG["default_part_parameters"]["melody"]
        if "rhythm_key" not in params: params["rhythm_key"] = cfg_melody.get("rhythm_key_map", {}).get(emotion_key, cfg_melody.get("rhythm_key_map", {}).get("default", "default_melody_rhythm"))
        # ... (リズムキーフォールバック、その他のメロディ固有パラメータ) ...
        if "octave_range" not in params: params["octave_range"] = cfg_melody.get("default_octave_range")
        if "density" not in params: params["density"] = cfg_melody.get("default_density")
        if "velocity" not in params: params["velocity"] = cfg_melody.get("default_velocity")


    # ブロック固有ヒントで最終上書き
    block_instrument_specific_hints = chord_block_specific_hints.get(instrument_name_key, {})
    if isinstance(block_instrument_specific_hints, dict): params.update(block_instrument_specific_hints)
    if instrument_name_key == "drums" and "drum_fill" in chord_block_specific_hints:
        params["drum_fill_key_override"] = chord_block_specific_hints["drum_fill"]
        
    logger.info(f"Final params for [{instrument_name_key}] (Emo: {emotion_key}, Int: {intensity_key}, Mode: {mode_of_block}) -> {params}")
    return params

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_lib_all: Dict) -> List[Dict]:
    # (変更なし)
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
            blk_intent = sec_intent.copy();
            if "emotion" in c_def: blk_intent["emotion"] = c_def["emotion"]
            if "intensity" in c_def: blk_intent["intensity"] = c_def["intensity"]
            blk_hints_for_translate = {"part_settings": sec_part_settings_for_all_instruments.copy()}
            current_block_mode = c_def.get("mode", sec_m)
            blk_hints_for_translate["mode_of_block"] = current_block_mode
            for k_hint, v_hint in c_def.items():
                if k_hint not in ["label","duration_beats","order","musical_intent","part_settings","tensions_to_add", "emotion", "intensity", "mode"]: blk_hints_for_translate[k_hint] = v_hint
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
    logger.info("=== Running Main Composition Workflow ===")
    final_score = stream.Score()
    # (グローバル設定は変更なし)
    final_score.insert(0, tempo.MetronomeMark(number=main_cfg["global_tempo"]))
    try:
        ts_obj_score = get_time_signature_object(main_cfg["global_time_signature"]); final_score.insert(0, ts_obj_score)
        key_t, key_m = main_cfg["global_key_tonic"], main_cfg["global_key_mode"]
        if chordmap.get("sections"):
            try:
                first_sec_name = sorted(chordmap.get("sections",{}).items(),key=lambda i:i[1].get("order",float('inf')))[0][0]
                first_sec_info = chordmap["sections"][first_sec_name]
                key_t,key_m = first_sec_info.get("tonic",key_t),first_sec_info.get("mode",key_m)
            except IndexError: logger.warning("No sections for initial key.")
        final_score.insert(0, key.Key(key_t, key_m.lower()))
    except Exception as e: logger.error(f"Error setting score globals: {e}. Defaults.", exc_info=True)

    proc_blocks = prepare_processed_stream(chordmap, main_cfg, rhythm_lib_all)
    if not proc_blocks: logger.error("No blocks to process. Abort."); return
    cv_inst = ChordVoicer(global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
    gens: Dict[str, Any] = {}

    # Instantiate generators (楽器設定の取得をより汎用的に)
    for part_name, generate_flag in main_cfg.get("parts_to_generate", {}).items():
        if not generate_flag: continue
        
        part_default_cfg = main_cfg["default_part_parameters"].get(part_name, {})
        instrument_str = part_default_cfg.get("instrument", "Piano") # デフォルト楽器名
        rhythm_category = part_default_cfg.get("default_rhythm_category", f"{part_name}_patterns") # 例: piano_patterns

        if part_name == "piano":
            gens[part_name] = PianoGenerator(rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get(rhythm_category, {})), chord_voicer_instance=cv_inst, global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
        elif part_name == "drums":
            gens[part_name] = DrumGenerator(drum_pattern_library=cast(Dict[str,Dict[str,Any]], rhythm_lib_all.get(rhythm_category, {})), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
        elif part_name == "guitar":
            gens[part_name] = GuitarGenerator(rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get(rhythm_category, {})), default_instrument=m21instrument.fromString(instrument_str), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
        elif part_name == "vocal":
            vocal_data_paths = part_default_cfg.get("data_paths", {})
            midivocal_p = cli_args.vocal_mididata_path or chordmap.get("global_settings",{}).get("vocal_mididata_path", vocal_data_paths.get("midivocal_data_path"))
            lyrics_p = cli_args.vocal_lyrics_path or chordmap.get("global_settings",{}).get("vocal_lyrics_path", vocal_data_paths.get("lyrics_text_path"))
            midivocal_d = load_json_file(Path(midivocal_p), "Vocal MIDI Data") if midivocal_p else None
            kasi_rist_d = load_json_file(Path(lyrics_p), "Lyrics List Data") if lyrics_p else None
            if midivocal_d and kasi_rist_d:
                gens[part_name] = VocalGenerator(default_instrument=m21instrument.fromString(instrument_str), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"])
            else: logger.error("Vocal generation skipped: Missing data."); main_cfg["parts_to_generate"][part_name] = False
        elif part_name == "bass":
            gens[part_name] = BassGenerator(rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get(rhythm_category, {})), default_instrument=m21instrument.fromString(instrument_str), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"], global_key_tonic=main_cfg["global_key_tonic"], global_key_mode=main_cfg["global_key_mode"])
        elif part_name == "melody":
            gens[part_name] = MelodyGenerator(rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get(rhythm_category, {})), default_instrument=m21instrument.fromString(instrument_str), global_tempo=main_cfg["global_tempo"], global_time_signature=main_cfg["global_time_signature"], global_key_signature_tonic=main_cfg["global_key_tonic"], global_key_signature_mode=main_cfg["global_key_mode"])
        elif part_name == "chords":
            gens[part_name] = cv_inst

    # パート生成ループ
    for p_n, p_g_inst in gens.items():
        if p_g_inst and main_cfg["parts_to_generate"].get(p_n):
            logger.info(f"Generating {p_n} part...")
            try:
                part_obj: Optional[stream.Stream] = None # stream.Part or stream.Score
                if p_n == "vocal":
                    # VocalGeneratorのcomposeに必要なパラメータを構築
                    # ★★★ translate_keywords_to_params で解決されたボーカルパラメータを使う ★★★
                    # proc_blocks の各ブロックの part_params["vocal"] に必要な情報が入っている想定
                    # ここでは、曲全体で一貫した設定を使うか、ブロックごとに変えるか設計による。
                    # 一旦、最初のブロックのパラメータを代表として使う（または main_cfg から直接）
                    vocal_params_for_compose = proc_blocks[0]["part_params"].get("vocal") if proc_blocks else main_cfg["default_part_parameters"].get("vocal", {})
                    
                    part_obj = p_g_inst.compose(
                        midivocal_data=cast(List[Dict], midivocal_data), # run_compositionスコープでロード済み
                        kasi_rist_data=cast(Dict[str, List[str]], kasi_rist_data),
                        processed_chord_stream=proc_blocks,
                        insert_breaths_opt=vocal_params_for_compose.get("insert_breaths_opt", True),
                        breath_duration_ql_opt=vocal_params_for_compose.get("breath_duration_ql_opt", 0.25),
                        humanize_opt=vocal_params_for_compose.get("humanize_opt", True),
                        humanize_template_name=vocal_params_for_compose.get("humanize_template_name"),
                        humanize_custom_params=vocal_params_for_compose.get("custom_params") # _get_humanize_params の戻り値に合わせる
                    )
                else:
                    part_obj = p_g_inst.compose(proc_blocks)
                
                if isinstance(part_obj, stream.Score) and part_obj.parts:
                    for sub_part in part_obj.parts: 
                        if sub_part.flatten().notesAndRests: final_score.insert(0, sub_part)
                elif isinstance(part_obj, stream.Part) and part_obj.flatten().notesAndRests:
                    final_score.insert(0, part_obj) # ★ バグ修正: part_obj を使う
                logger.info(f"{p_n} part generated.")
            except Exception as e_gen: logger.error(f"Error in {p_n} generation: {e_gen}", exc_info=True)

    # (MIDI書き出し部分は変更なし)
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
    # (コマンドライン引数処理は前回提案から変更なし)
    parser = argparse.ArgumentParser(description="Modular Music Composer")
    parser.add_argument("chordmap_file", type=Path, help="Chordmap JSON.")
    parser.add_argument("rhythm_library_file", type=Path, help="Rhythm library JSON.")
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Output dir.")
    parser.add_argument("--output-filename", type=str, help="Output filename.")
    parser.add_argument("--settings-file", type=Path, help="Custom settings JSON.")
    parser.add_argument("--tempo", type=int, help="Override global tempo.")
    parser.add_argument("--vocal-mididata-path", type=Path, help="Vocal MIDI data JSON path.")
    parser.add_argument("--vocal-lyrics-path", type=Path, help="Lyrics list JSON path.")
    default_parts = DEFAULT_CONFIG.get("parts_to_generate", {})
    for pk,ps in default_parts.items():
        arg_n = f"generate_{pk}"
        if ps: parser.add_argument(f"--no-{pk}",action="store_false",dest=arg_n,help=f"Disable {pk}.")
        else: parser.add_argument(f"--include-{pk}",action="store_true",dest=arg_n,help=f"Enable {pk}.")
    parser.set_defaults(**{f"generate_{k}":v for k,v in default_parts.items()})
    args = parser.parse_args()
    effective_cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if args.settings_file and args.settings_file.exists():
        custom_s = load_json_file(args.settings_file, "Custom settings")
        if custom_s and isinstance(custom_s, dict):
            def _deep_update(t,s):
                for k,v in s.items():
                    if isinstance(v,dict) and k in t and isinstance(t[k],dict): _deep_update(t[k],v)
                    else: t[k]=v
            _deep_update(effective_cfg, custom_s)
    for pk in default_parts.keys():
        arg_n = f"generate_{pk}"
        if hasattr(args, arg_n): effective_cfg["parts_to_generate"][pk] = getattr(args, arg_n)
    if args.vocal_mididata_path: effective_cfg["default_part_parameters"]["vocal"]["data_paths"]["midivocal_data_path"] = str(args.vocal_mididata_path)
    if args.vocal_lyrics_path: effective_cfg["default_part_parameters"]["vocal"]["data_paths"]["lyrics_text_path"] = str(args.vocal_lyrics_path)
    chordmap_d = load_json_file(args.chordmap_file, "Chordmap")
    rhythm_lib_d = load_json_file(args.rhythm_library_file, "Rhythm Library")
    if not chordmap_d or not rhythm_lib_d: logger.critical("Data files missing. Exit."); sys.exit(1)
    cm_globals = chordmap_d.get("global_settings", {})
    effective_cfg["global_tempo"]=cm_globals.get("tempo",effective_cfg["global_tempo"])
    effective_cfg["global_time_signature"]=cm_globals.get("time_signature",effective_cfg["global_time_signature"])
    effective_cfg["global_key_tonic"]=cm_globals.get("key_tonic",effective_cfg["global_key_tonic"])
    effective_cfg["global_key_mode"]=cm_globals.get("key_mode",effective_cfg["global_key_mode"])
    if args.tempo is not None: effective_cfg["global_tempo"] = args.tempo
    logger.info(f"Final Config: {json.dumps(effective_cfg, indent=2, ensure_ascii=False)}")
    try: run_composition(args, effective_cfg, cast(Dict,chordmap_d), cast(Dict,rhythm_lib_d))
    except SystemExit: raise
    except Exception as e: logger.critical(f"Critical error in main run: {e}", exc_info=True); sys.exit(1)

if __name__ == "__main__":
    main_cli()
# --- END OF FILE modular_composer.py ---
