# --- START OF FILE modular_composer.py (2023-05-22 修正案) ---
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
    from generator.bass_generator import BassGenerator
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import generator modules from 'generator' package. "
          f"Ensure 'generator' directory is in the project root and contains __init__.py. Error: {e}")
    sys.exit(1) # sys.exit() の方が適切
except Exception as e_imp:
    print(f"An unexpected error occurred during module import: {e_imp}")
    sys.exit(1) # sys.exit() の方が適切

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
                "quiet_pain_and_nascent_strength": "piano_reflective_arpeggio_rh",
                "deep_regret_gratitude_and_realization": "piano_chordal_moving_rh",
                "acceptance_of_love_and_pain_hopeful_belief": "piano_powerful_block_8ths_rh", # 統一
                "self_reproach_regret_deep_sadness": "piano_reflective_arpeggio_rh",
                "supported_light_longing_for_rebirth": "piano_chordal_moving_rh",
                "reflective_transition_instrumental_passage": "piano_reflective_arpeggio_rh",
                "trial_cry_prayer_unbreakable_heart": "piano_powerful_block_8ths_rh", # 統一
                "memory_unresolved_feelings_silence": "piano_reflective_arpeggio_rh",
                "wavering_heart_gratitude_chosen_strength": "piano_chordal_moving_rh",
                "reaffirmed_strength_of_love_positive_determination": "piano_powerful_block_8ths_rh", # 統一
                "hope_dawn_light_gentle_guidance": "piano_reflective_arpeggio_rh",
                "nature_memory_floating_sensation_forgiveness": "piano_reflective_arpeggio_rh",
                "future_cooperation_our_path_final_resolve_and_liberation": "piano_powerful_block_8ths_rh", # 統一
                "default": "simple_block_rh" # フォールバック
            },
            "emotion_to_lh_style_keyword": {
                "quiet_pain_and_nascent_strength": "piano_sustained_root_lh",
                "deep_regret_gratitude_and_realization": "piano_walking_bass_like_lh",
                "acceptance_of_love_and_pain_hopeful_belief": "piano_active_octave_bass_lh",
                "self_reproach_regret_deep_sadness": "piano_sustained_root_lh",
                "supported_light_longing_for_rebirth": "piano_walking_bass_like_lh",
                "reflective_transition_instrumental_passage": "piano_sustained_root_lh",
                "trial_cry_prayer_unbreakable_heart": "piano_active_octave_bass_lh",
                "memory_unresolved_feelings_silence": "piano_sustained_root_lh",
                "wavering_heart_gratitude_chosen_strength": "piano_walking_bass_like_lh",
                "reaffirmed_strength_of_love_positive_determination": "piano_active_octave_bass_lh",
                "hope_dawn_light_gentle_guidance": "piano_sustained_root_lh",
                "nature_memory_floating_sensation_forgiveness": "piano_sustained_root_lh",
                "future_cooperation_our_path_final_resolve_and_liberation": "piano_active_octave_bass_lh",
                "default": "simple_root_lh" # フォールバック
            },
            "style_keyword_to_rhythm_key": {
                "piano_reflective_arpeggio_rh": "piano_flowing_arpeggio_eighths_rh",
                "piano_chordal_moving_rh": "piano_chordal_moving_rh_pattern",
                "piano_powerful_block_8ths_rh": "piano_powerful_block_8ths_rh", # 以前は powerful_block_rh
                "simple_block_rh": "piano_block_quarters_simple",
                "piano_sustained_root_lh": "piano_sustained_root_lh", # 以前は gentle_sustained_root_lh
                "piano_walking_bass_like_lh": "piano_walking_bass_like_lh",
                "piano_active_octave_bass_lh": "piano_active_octave_bass_lh",
                "simple_root_lh": "piano_lh_quarter_roots",
                "default_piano_rh_fallback_rhythm": "default_piano_quarters",
                "default_piano_lh_fallback_rhythm": "piano_lh_whole_notes"
            },
            "intensity_to_velocity_ranges": { # (LH_min, LH_max, RH_min, RH_max)
                "low": [50, 60, 55, 65], # リストに変更
                "medium_low": [55, 65, 60, 70], # リストに変更
                "medium": [60, 70, 65, 75], # リストに変更
                "medium_high": [65, 80, 70, 85], # リストに変更
                "high": [70, 85, 75, 90], # リストに変更
                "high_to_very_high_then_fade": [75, 95, 80, 100], # 例: 特殊なintensityにも対応
                "default": [60, 70, 65, 75] # リストに変更
            },
            "default_apply_pedal": True, "default_arp_note_ql": 0.5,
            "default_rh_voicing_style": "closed", "default_lh_voicing_style": "closed",
            "default_rh_target_octave": 4, "default_lh_target_octave": 2,
            "default_rh_num_voices": 3, "default_lh_num_voices": 1
        },
        "drums": {
            "emotion_to_style_key": {
                "quiet_pain_and_nascent_strength": "no_drums", # chordmapに合わせる
                "deep_regret_gratitude_and_realization": "ballad_soft_kick_snare_8th_hat",
                "acceptance_of_love_and_pain_hopeful_belief": "anthem_rock_chorus_16th_hat",
                "self_reproach_regret_deep_sadness": "no_drums_or_sparse_cymbal", # chordmapに合わせる
                "supported_light_longing_for_rebirth": "rock_ballad_build_up_8th_hat",
                "reflective_transition_instrumental_passage": "no_drums_or_gentle_cymbal_swell", # chordmapに合わせる
                "trial_cry_prayer_unbreakable_heart": "rock_ballad_build_up_8th_hat",
                "memory_unresolved_feelings_silence": "no_drums", # chordmapに合わせる
                "wavering_heart_gratitude_chosen_strength": "ballad_soft_kick_snare_8th_hat",
                "reaffirmed_strength_of_love_positive_determination": "anthem_rock_chorus_16th_hat",
                "hope_dawn_light_gentle_guidance": "no_drums_or_gentle_cymbal_swell", # chordmapに合わせる
                "nature_memory_floating_sensation_forgiveness": "no_drums_or_sparse_chimes", # chordmapに合わせる
                "future_cooperation_our_path_final_resolve_and_liberation": "anthem_rock_chorus_16th_hat",
                "default_style": "default_drum_pattern"
            },
            "intensity_to_base_velocity": { # [min, max] のリストに変更
                "default": [70, 80],
                "low": [55, 65],
                "medium_low": [60, 70],
                "medium": [70, 80],
                "medium_high": [75, 85],
                "high": [85, 95],
                "high_to_very_high_then_fade": [90, 105] # 例
            },
            "default_fill_interval_bars": 4,
            "default_fill_keys": ["simple_snare_roll_half_bar", "chorus_end_fill"]
        },
        "chords": {
            "instrument": "StringInstrument", "chord_voicing_style": "closed",
            "chord_target_octave": 3, "chord_num_voices": 4, "chord_velocity": 64
        },
        "melody": {
            "instrument": "Flute", "rhythm_key": "default_melody_rhythm",
            "octave_range": [4, 5], "density": 0.7
        },
        "bass": {
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
    return None # Should not be reached if sys.exit is called

def translate_keywords_to_params(
        musical_intent: Dict[str, Any], chord_block_specific_hints: Dict[str, Any],
        default_instrument_params: Dict[str, Any], instrument_name_key: str,
        rhythm_library_all_categories: Dict
) -> Dict[str, Any]:
    params: Dict[str, Any] = default_instrument_params.copy() # Start with instrument defaults
    
    # Get emotion and intensity from musical_intent, with fallbacks
    emotion_key = musical_intent.get("emotion", "default").lower() # Use "default" if emotion not specified
    intensity_key = musical_intent.get("intensity", "default").lower() # Use "default" if intensity not specified

    # Override with section-level part_settings first
    section_instrument_settings = chord_block_specific_hints.get("part_settings", {}).get(instrument_name_key, {})
    params.update(section_instrument_settings)

    logger.debug(f"Translating for {instrument_name_key}: Emo='{emotion_key}', Int='{intensity_key}', InitialParams (after section merge)='{params}'")

    if instrument_name_key == "piano":
        cfg_piano = DEFAULT_CONFIG["default_part_parameters"]["piano"] # Use the global default for piano

        # Determine style keywords: chordmap's part_settings > emotion_map > default_emotion_map
        # piano_rh_style_keyword is already in params if set by part_settings
        if "piano_rh_style_keyword" not in params: # Only if not set by chordmap's part_settings
            params["piano_rh_style_keyword"] = cfg_piano.get("emotion_to_rh_style_keyword", {}).get(emotion_key, 
                                                                                                 cfg_piano.get("emotion_to_rh_style_keyword", {}).get("default"))
        if "piano_lh_style_keyword" not in params: # Only if not set by chordmap's part_settings
            params["piano_lh_style_keyword"] = cfg_piano.get("emotion_to_lh_style_keyword", {}).get(emotion_key, 
                                                                                                 cfg_piano.get("emotion_to_lh_style_keyword", {}).get("default"))
        
        rh_style_kw = params.get("piano_rh_style_keyword") # This should now have a value
        lh_style_kw = params.get("piano_lh_style_keyword") # This should now have a value

        style_to_rhythm_map = cfg_piano.get("style_keyword_to_rhythm_key", {})
        piano_patterns_from_lib = rhythm_library_all_categories.get("piano_patterns", {})

        # Determine rhythm keys based on style keywords
        params["piano_rh_rhythm_key"] = style_to_rhythm_map.get(rh_style_kw)
        if not params.get("piano_rh_rhythm_key") or params.get("piano_rh_rhythm_key") not in piano_patterns_from_lib:
             fallback_rh_key = style_to_rhythm_map.get("default_piano_rh_fallback_rhythm", "default_piano_quarters")
             logger.warning(f"Piano RH rhythm key for style '{rh_style_kw}' (derived from emotion '{emotion_key}') resulted in '{params.get('piano_rh_rhythm_key')}', which is not in rhythm_library. Using fallback '{fallback_rh_key}'.")
             params["piano_rh_rhythm_key"] = fallback_rh_key

        params["piano_lh_rhythm_key"] = style_to_rhythm_map.get(lh_style_kw)
        if not params.get("piano_lh_rhythm_key") or params.get("piano_lh_rhythm_key") not in piano_patterns_from_lib:
             fallback_lh_key = style_to_rhythm_map.get("default_piano_lh_fallback_rhythm", "piano_lh_whole_notes")
             logger.warning(f"Piano LH rhythm key for style '{lh_style_kw}' (derived from emotion '{emotion_key}') resulted in '{params.get('piano_lh_rhythm_key')}', which is not in rhythm_library. Using fallback '{fallback_lh_key}'.")
             params["piano_lh_rhythm_key"] = fallback_lh_key
        
        # Determine velocities: chordmap's part_settings > intensity_map > default_intensity_map
        vel_map_piano = cfg_piano.get("intensity_to_velocity_ranges", {})
        default_vel_tuple_piano = vel_map_piano.get("default", [60, 70, 65, 75]) # Ensure default is a list
        
        # If velocities are not directly set in chordmap's part_settings for piano
        if "piano_velocity_lh" not in params or "piano_velocity_rh" not in params:
            current_vel_tuple_piano = vel_map_piano.get(intensity_key, default_vel_tuple_piano)
            if isinstance(current_vel_tuple_piano, Sequence) and len(current_vel_tuple_piano) == 4:
                if "piano_velocity_lh" not in params:
                    params["piano_velocity_lh"] = random.randint(current_vel_tuple_piano[0], current_vel_tuple_piano[1])
                if "piano_velocity_rh" not in params:
                    params["piano_velocity_rh"] = random.randint(current_vel_tuple_piano[2], current_vel_tuple_piano[3])
            else:
                logger.warning(f"Piano velocity range for intensity '{intensity_key}' ('{current_vel_tuple_piano}') is not a 4-element sequence. Using defaults.")
                if "piano_velocity_lh" not in params:
                    params["piano_velocity_lh"] = random.randint(default_vel_tuple_piano[0], default_vel_tuple_piano[1])
                if "piano_velocity_rh" not in params:
                    params["piano_velocity_rh"] = random.randint(default_vel_tuple_piano[2], default_vel_tuple_piano[3])
        
        # Apply other default piano params if not set by chordmap
        for p_key_suffix_piano in ["apply_pedal", "arp_note_ql", "rh_voicing_style", "lh_voicing_style", "rh_target_octave", "lh_target_octave", "rh_num_voices", "lh_num_voices"]:
            param_name_full_piano = f"piano_{p_key_suffix_piano}"
            if param_name_full_piano not in params: # Only if not set by chordmap
                default_param_key_in_cfg_piano = f"default_{p_key_suffix_piano}"
                params[param_name_full_piano] = cfg_piano.get(default_param_key_in_cfg_piano)

    elif instrument_name_key == "drums":
        cfg_drums = DEFAULT_CONFIG["default_part_parameters"]["drums"]
        
        if "drum_style_key" not in params: # Only if not set by chordmap's part_settings
            params["drum_style_key"] = cfg_drums.get("emotion_to_style_key", {}).get(emotion_key, 
                                                                                  cfg_drums.get("emotion_to_style_key", {}).get("default_style"))
        
        drum_patterns_from_lib = rhythm_library_all_categories.get("drum_patterns", {})
        if not params.get("drum_style_key") or params.get("drum_style_key") not in drum_patterns_from_lib:
            logger.warning(f"Drum style key '{params.get('drum_style_key')}' (from emotion '{emotion_key}') not in drum_patterns. Using 'default_drum_pattern'.")
            params["drum_style_key"] = "default_drum_pattern"

        if "drum_base_velocity" not in params: # Only if not set by chordmap's part_settings
            vel_map_drums = cfg_drums.get("intensity_to_base_velocity", {})
            default_drum_vel_range = vel_map_drums.get("default", [70, 80]) # Ensure default is a list
            current_drum_vel_range = vel_map_drums.get(intensity_key, default_drum_vel_range)
            
            if isinstance(current_drum_vel_range, Sequence) and len(current_drum_vel_range) == 2:
                params["drum_base_velocity"] = random.randint(current_drum_vel_range[0], current_drum_vel_range[1])
            else: # If it's a single number (old format) or invalid
                logger.warning(f"Drum base velocity for intensity '{intensity_key}' ('{current_drum_vel_range}') is not a 2-element sequence. Using default range.")
                params["drum_base_velocity"] = random.randint(default_drum_vel_range[0], default_drum_vel_range[1])
        
        if "drum_fill_interval_bars" not in params:
            params["drum_fill_interval_bars"] = cfg_drums.get("default_fill_interval_bars")
        if "drum_fill_keys" not in params:
            params["drum_fill_keys"] = cfg_drums.get("default_fill_keys")
    
    elif instrument_name_key == "melody":
        cfg_melody = DEFAULT_CONFIG["default_part_parameters"]["melody"]
        melody_rhythms_lib = rhythm_library_all_categories.get("melody_rhythms", {})
        
        if "rhythm_key" not in params:
            rhythm_key_map_melody = cfg_melody.get("rhythm_key_map", {}) # Assuming this map exists in config
            params["rhythm_key"] = rhythm_key_map_melody.get(emotion_key, rhythm_key_map_melody.get("default", "default_melody_rhythm"))
        
        if not params.get("rhythm_key") or params.get("rhythm_key") not in melody_rhythms_lib:
            logger.warning(f"Melody rhythm key '{params.get('rhythm_key')}' not in melody_rhythms. Using 'default_melody_rhythm'.")
            params["rhythm_key"] = "default_melody_rhythm"

        if "octave_range" not in params: params["octave_range"] = cfg_melody.get("octave_range")
        if "density" not in params: params["density"] = cfg_melody.get("density")

    elif instrument_name_key == "bass":
        cfg_bass = DEFAULT_CONFIG["default_part_parameters"]["bass"]
        bass_lines_lib = rhythm_library_all_categories.get("bass_lines", {})

        if "style" not in params: # Bass style (e.g., "simple_roots", "walking")
            params["style"] = cfg_bass.get("style_map",{}).get(emotion_key, cfg_bass.get("style_map",{}).get("default", "simple_roots"))
        
        if "rhythm_key" not in params:
            rhythm_key_map_bass = cfg_bass.get("rhythm_key_map", {}) # Assuming this map exists
            params["rhythm_key"] = rhythm_key_map_bass.get(emotion_key, rhythm_key_map_bass.get("default", "bass_quarter_notes"))

        if not params.get("rhythm_key") or params.get("rhythm_key") not in bass_lines_lib:
            logger.warning(f"Bass rhythm key '{params.get('rhythm_key')}' not in bass_lines. Using 'bass_quarter_notes'.")
            params["rhythm_key"] = "bass_quarter_notes"

    # Apply block-specific overrides (e.g., from "part_specific_hints" in chordmap)
    # This was done by `params.update(section_instrument_settings)` earlier if part_settings was used.
    # If chord_block_specific_hints contains direct overrides for this instrument, apply them.
    block_instrument_hints = chord_block_specific_hints.get(instrument_name_key, {}) # Direct hints for the instrument
    params.update(block_instrument_hints)
    
    # Special handling for drum_fill from chord_block_specific_hints (if it's not under part_settings)
    if instrument_name_key == "drums" and "drum_fill" in chord_block_specific_hints: # Check top-level of hints
        params["drum_fill_key_override"] = chord_block_specific_hints["drum_fill"]
        
    logger.info(f"Final params for [{instrument_name_key}] (Emo: {emotion_key}, Int: {intensity_key}) -> {params}")
    return params

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_lib_all: Dict) -> List[Dict]:
    processed_stream: List[Dict] = []
    current_abs_offset: float = 0.0
    g_settings = chordmap_data.get("global_settings", {})
    ts_str = g_settings.get("time_signature", main_config["global_time_signature"])
    ts_obj = get_time_signature_object(ts_str)
    beats_per_measure = ts_obj.barDuration.quarterLength
    g_key_t, g_key_m = g_settings.get("key_tonic", main_config["global_key_tonic"]), g_settings.get("key_mode", main_config["global_key_mode"])

    # Ensure sections are processed in their defined "order"
    sorted_sections = sorted(chordmap_data.get("sections", {}).items(), key=lambda item: item[1].get("order", float('inf')))
    
    for sec_name, sec_info in sorted_sections:
        logger.info(f"Preparing section: {sec_name}")
        sec_intent = sec_info.get("musical_intent", {})
        # part_settings at section level are passed via chord_block_specific_hints in translate_keywords_to_params
        sec_part_settings_for_all_instruments = sec_info.get("part_settings", {}) 
        
        sec_t, sec_m = sec_info.get("tonic", g_key_t), sec_info.get("mode", g_key_m)
        sec_len_meas = sec_info.get("length_in_measures")
        chord_prog = sec_info.get("chord_progression", [])
        
        if not chord_prog: 
            logger.warning(f"Section '{sec_name}' has no chord_progression. Skipping section.")
            continue

        for c_idx, c_def in enumerate(chord_prog):
            c_lbl = c_def.get("label", "C") # Default to C if no label
            
            # Calculate duration: explicit duration_beats > calculated from section length > default one measure
            if "duration_beats" in c_def:
                dur_b = float(c_def["duration_beats"])
            elif sec_len_meas and chord_prog: # If section length and progression exist, distribute beats
                dur_b = (float(sec_len_meas) * beats_per_measure) / len(chord_prog)
            else: # Default to one measure if not specified
                dur_b = beats_per_measure
                logger.debug(f"Block {c_idx+1} in {sec_name} using default duration of one measure ({beats_per_measure} beats).")

            # Combine section intent with block-specific overrides for emotion/intensity
            blk_intent = sec_intent.copy() 
            if "emotion" in c_def: blk_intent["emotion"] = c_def["emotion"]
            if "intensity" in c_def: blk_intent["intensity"] = c_def["intensity"]
            
            # chord_block_specific_hints should contain section-level part_settings and block-level hints
            blk_hints_for_translate = {"part_settings": sec_part_settings_for_all_instruments.copy()}
            # Add other block-specific hints (like "drum_fill") that are not under "part_settings"
            for k_hint, v_hint in c_def.items():
                if k_hint not in ["label", "duration_beats", "order", "musical_intent", "part_settings", "tensions_to_add", "emotion", "intensity"]:
                    blk_hints_for_translate[k_hint] = v_hint
            
            blk_data = {
                "offset": current_abs_offset, 
                "q_length": dur_b, 
                "chord_label": c_lbl, 
                "section_name": sec_name,
                "tonic_of_section": sec_t, 
                "mode": sec_m, 
                "tensions_to_add": c_def.get("tensions_to_add", []),
                "is_first_in_section": (c_idx == 0), 
                "is_last_in_section": (c_idx == len(chord_prog) - 1),
                "part_params": {} # This will be populated by translate_keywords_to_params
            }

            for p_key_name in main_config["parts_to_generate"].keys():
                if main_config["parts_to_generate"].get(p_key_name): # Only if part is set to generate
                    default_params_for_instrument = main_config["default_part_parameters"].get(p_key_name, {})
                    blk_data["part_params"][p_key_name] = translate_keywords_to_params(
                        blk_intent, 
                        blk_hints_for_translate, # Pass combined hints
                        default_params_for_instrument, 
                        p_key_name, 
                        rhythm_lib_all
                    )
            processed_stream.append(blk_data)
            current_abs_offset += dur_b
            
    logger.info(f"Prepared {len(processed_stream)} blocks. Total duration: {current_abs_offset:.2f} beats.")
    return processed_stream

def run_composition(cli_args: argparse.Namespace, main_cfg: Dict, chordmap: Dict, rhythm_lib_all: Dict):
    logger.info("=== Running Main Composition Workflow ===")
    final_score = stream.Score()
    
    # Global settings for the score
    final_score.insert(0, tempo.MetronomeMark(number=main_cfg["global_tempo"]))
    try:
        ts_obj_score = get_time_signature_object(main_cfg["global_time_signature"])
        final_score.insert(0, ts_obj_score)
        
        key_t, key_m = main_cfg["global_key_tonic"], main_cfg["global_key_mode"]
        # Try to get key from the first section if available
        if chordmap.get("sections"):
            try:
                # Sort sections by 'order' to find the actual first section
                first_sec_name = sorted(
                    chordmap.get("sections", {}).items(), 
                    key=lambda item: item[1].get("order", float('inf'))
                )[0][0]
                first_sec_info = chordmap.get("sections", {})[first_sec_name]
                key_t = first_sec_info.get("tonic", key_t)
                key_m = first_sec_info.get("mode", key_m)
            except IndexError: 
                logger.warning("No sections found or 'order' not defined for initial key; using global key.")
        final_score.insert(0, key.Key(key_t, key_m.lower()))
    except Exception as e: 
        logger.error(f"Error setting score globals (tempo/ts/key): {e}. Using defaults.", exc_info=True)
        if not final_score.getElementsByClass(meter.TimeSignature):
            final_score.insert(0, meter.TimeSignature("4/4"))
        if not final_score.getElementsByClass(key.Key):
            final_score.insert(0, key.Key("C"))

    proc_blocks = prepare_processed_stream(chordmap, main_cfg, rhythm_lib_all)
    if not proc_blocks: 
        logger.error("No processed blocks to compose from. Aborting composition.")
        return

    # Initialize ChordVoicer (used by Piano and Chords parts)
    cv_inst = ChordVoicer(
        global_tempo=main_cfg["global_tempo"], 
        global_time_signature=main_cfg["global_time_signature"]
    )
    
    gens: Dict[str, Any] = {} # Dictionary to hold generator instances

    # Instantiate generators for parts to be generated
    if main_cfg["parts_to_generate"].get("piano"):
        gens["piano"] = PianoGenerator(
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("piano_patterns", {})),
            chord_voicer_instance=cv_inst,
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"]
        )
    if main_cfg["parts_to_generate"].get("drums"):
        gens["drums"] = DrumGenerator(
            drum_pattern_library=cast(Dict[str,Dict[str,Any]], rhythm_lib_all.get("drum_patterns", {})),
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"]
        )
    if main_cfg["parts_to_generate"].get("chords"):
        gens["chords"] = cv_inst # ChordVoicer itself acts as the chords generator
        
    if main_cfg["parts_to_generate"].get("melody"):
        gens["melody"] = MelodyGenerator(
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("melody_rhythms", {})),
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"],
            global_key_signature_tonic=main_cfg["global_key_tonic"],
            global_key_signature_mode=main_cfg["global_key_mode"]
        )
    if main_cfg["parts_to_generate"].get("bass"):
        gens["bass"] = BassGenerator(
            rhythm_library=cast(Dict[str,Dict], rhythm_lib_all.get("bass_lines", {})),
            global_tempo=main_cfg["global_tempo"],
            global_time_signature=main_cfg["global_time_signature"]
            # Add key info if BassGenerator needs it:
            # global_key_signature_tonic=main_cfg["global_key_tonic"],
            # global_key_signature_mode=main_cfg["global_key_mode"]
        )

    # Compose each part
    for part_name, generator_instance in gens.items():
        if generator_instance:
            logger.info(f"Generating {part_name} part...")
            try:
                # The compose method of each generator should return a music21.stream.Part or music21.stream.Score
                composed_part_or_score = generator_instance.compose(proc_blocks)
                
                if isinstance(composed_part_or_score, stream.Score):
                    for sub_part in composed_part_or_score.parts:
                        if sub_part.flatten().notesAndRests: # Add only if it has content
                            final_score.insert(0, sub_part) # Insert at beginning to maintain order
                elif isinstance(composed_part_or_score, stream.Part):
                    if composed_part_or_score.flatten().notesAndRests: # Add only if it has content
                        final_score.insert(0, composed_part_or_score)
                else:
                    logger.warning(f"{part_name} generator did not return a Part or Score object.")
                logger.info(f"{part_name} part generated.")
            except Exception as e_gen:
                logger.error(f"Error during {part_name} part generation: {e_gen}", exc_info=True)

    # Prepare output filename and directory
    title = chordmap.get("project_title", "untitled_song").replace(" ", "_").lower()
    out_fname_template = main_cfg.get("output_filename_template", "output_{song_title}.mid")
    actual_out_fname = cli_args.output_filename if cli_args.output_filename else out_fname_template.format(song_title=title)
    out_fpath = cli_args.output_dir / actual_out_fname
    
    out_fpath.parent.mkdir(parents=True, exist_ok=True) # Ensure output directory exists
    
    # Write MIDI file
    try:
        if final_score.flatten().notesAndRests: # Only write if there's something to write
            final_score.write('midi', fp=str(out_fpath))
            logger.info(f"🎉 Successfully wrote MIDI file to: {out_fpath}")
        else:
            logger.warning(f"Final score is empty. No MIDI file written to {out_fpath}.")
    except Exception as e_write_midi:
        logger.error(f"Error writing MIDI file to {out_fpath}: {e_write_midi}", exc_info=True)

def main_cli():
    parser = argparse.ArgumentParser(description="Modular Music Composer (Keyword-Driven)")
    parser.add_argument("chordmap_file", type=Path, help="Path to the chordmap JSON file.")
    parser.add_argument("rhythm_library_file", type=Path, help="Path to the rhythm library JSON file.")
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Directory to save the output MIDI file.")
    parser.add_argument("--output-filename", type=str, help="Custom filename for the output MIDI (optional).")
    parser.add_argument("--settings-file", type=Path, help="Path to a custom settings JSON file to override defaults (optional).")
    parser.add_argument("--tempo", type=int, help="Override the global tempo defined in settings or chordmap.")
    
    # Dynamically add arguments for enabling/disabling parts based on DEFAULT_CONFIG
    default_parts_to_generate = DEFAULT_CONFIG.get("parts_to_generate", {})
    for part_key, default_state in default_parts_to_generate.items():
        arg_name_for_part = f"generate_{part_key}"
        if default_state: # If default is True, add a --no-{part} flag
            parser.add_argument(f"--no-{part_key}", action="store_false", dest=arg_name_for_part, help=f"Disable generation of the {part_key} part.")
        else: # If default is False, add an --include-{part} flag
            parser.add_argument(f"--include-{part_key}", action="store_true", dest=arg_name_for_part, help=f"Enable generation of the {part_key} part.")
    # Set defaults for these dynamic arguments
    parser.set_defaults(**{f"generate_{k}": v for k, v in default_parts_to_generate.items()})

    args = parser.parse_args()
    
    # Start with a copy of DEFAULT_CONFIG
    effective_config = json.loads(json.dumps(DEFAULT_CONFIG)) # Deep copy

    # Override with custom settings file if provided
    if args.settings_file and args.settings_file.exists():
        custom_settings_data = load_json_file(args.settings_file, "Custom settings")
        if custom_settings_data and isinstance(custom_settings_data, dict):
            # Simple merge: custom_settings_data overrides DEFAULT_CONFIG keys
            # For nested dicts, a deep merge might be needed, but for now, this is simple.
            def _deep_update(target_dict, source_dict):
                for key, value in source_dict.items():
                    if isinstance(value, dict) and key in target_dict and isinstance(target_dict[key], dict):
                        _deep_update(target_dict[key], value)
                    else:
                        target_dict[key] = value
            _deep_update(effective_config, custom_settings_data)
            logger.info(f"Loaded custom settings from: {args.settings_file}")

    # Override parts_to_generate based on command-line flags
    for part_key in default_parts_to_generate.keys():
        arg_name_for_part = f"generate_{part_key}"
        if hasattr(args, arg_name_for_part):
            effective_config["parts_to_generate"][part_key] = getattr(args, arg_name_for_part)

    # Load main data files
    chordmap_data = load_json_file(args.chordmap_file, "Chordmap")
    rhythm_library_data = load_json_file(args.rhythm_library_file, "Rhythm Library")
    if not chordmap_data or not rhythm_library_data:
        logger.critical("Essential data files (chordmap or rhythm library) could not be loaded. Exiting.")
        sys.exit(1)

    # Override global settings from chordmap if they exist
    chordmap_global_settings = chordmap_data.get("global_settings", {})
    effective_config["global_tempo"] = chordmap_global_settings.get("tempo", effective_config["global_tempo"])
    effective_config["global_time_signature"] = chordmap_global_settings.get("time_signature", effective_config["global_time_signature"])
    effective_config["global_key_tonic"] = chordmap_global_settings.get("key_tonic", effective_config["global_key_tonic"])
    effective_config["global_key_mode"] = chordmap_global_settings.get("key_mode", effective_config["global_key_mode"])

    # Override tempo from command-line if provided (highest precedence)
    if args.tempo is not None:
        effective_config["global_tempo"] = args.tempo
        logger.info(f"Global tempo overridden by command line: {args.tempo}")
    
    logger.info(f"Final Effective Configuration: {json.dumps(effective_config, indent=2, ensure_ascii=False)}")
    
    try:
        run_composition(args, effective_config, cast(Dict, chordmap_data), cast(Dict, rhythm_library_data))
    except SystemExit: # Allow sys.exit to propagate
        raise
    except Exception as e_main_run:
        logger.critical(f"A critical error occurred during the composition process: {e_main_run}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main_cli()
# --- END OF FILE modular_composer.py ---
