# --- START OF FILE modular_composer.py (RhythmPatternRepository 参照削除) ---

import json
import argparse
import logging
from pathlib import Path
from music21 import stream, tempo, instrument as m21instrument, midi, meter, key
from typing import List, Dict, Optional, Any, cast

# --- ジェネレータクラスのインポート (generatorフォルダから) ---
try:
    from generator.piano_generator import PianoGenerator
    from generator.drum_generator import DrumGenerator
    from generator.chord_voicer import ChordVoicer # ChordVoicerをPianoGeneratorに渡す
    from generator.melody_generator import MelodyGenerator
    from generator.bass_core_generator import BassCoreGenerator
    #from generator.guitar_generator import GuitarGenerator # GuitarGenerator もインポート
    from generator.core_music_utils import get_time_signature_object
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import generator modules. Check file structure or PYTHONPATH: {e}")
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
        "piano": True, "drums": True, "melody": False, "bass": False, "chords": True, "guitar": False # "chords": True を追加
    },
    "default_part_parameters": {
        "piano": {
            # (以前の例と同様ですが、"style_to_rhythm_key" は整理)
            "emotion_to_style": { # 感情キーワード -> 演奏スタイル名
                "nostalgic_gentle": "gentle_block_chords",
                "warm_recollection": "flowing_eighth_arpeggio", # "arpeggio_flowing_eighth" など
                "deep_regret_and_gratitude": "sparse_chords_with_pedal",
                "love_pain_acceptance_and_belief": "powerful_block_chords",
                "self_reproach_regret_deep_sadness": "dark_arpeggio",
                "supported_light_longing_for_rebirth": "gentle_broken_chords",
                "reflective_transition_instrumental_passage": "sparse_chords_with_sustained_bass",
                "memory_unresolved_feelings_silence": "slow_arpeggio_with_pedal",
                "wavering_heart_gratitude_chosen_strength": "sparse_moving_chords",
                "reaffirmed_strength_of_love_positive_determination": "powerful_octave_chords",
                "hope_dawn_light_gentle_guidance": "dreamy_arpeggio",
                "nature_memory_floating_sensation_forgiveness": "lyrical_arpeggio",
                "future_cooperation_our_path_final_resolve_and_liberation": "grand_block_chords",
                "default_style": "simple_piano"
            },
            "intensity_to_velocity": {
                "very_low": (30, 40), "low": (40, 55), "medium_low": (55, 65),
                "medium": (65, 75), "medium_high": (75, 85), "high": (85, 95), "very_high": (95, 110), "high_to_very_high_then_fade": (80,100),
                "default_velocity": 65
            },
             "style_to_rhythm_key_rh": { # PianoGenerator側でこのマッピングを直接使うか、あるいは params に具体的なリズムキー名を入れるか。
                "gentle_block_chords": "piano_gentle_block_whole_rh",
                "flowing_eighth_arpeggio": "piano_flowing_arpeggio_eighths_rh",
                "sparse_chords_with_pedal": "piano_sparse_chords_with_pedal", # rhythm_library に定義
                "powerful_block_chords": "piano_powerful_block_8ths_rh",
                "dark_arpeggio": "piano_dark_arpeggio_rh", # rhythm_library に定義
                "gentle_broken_chords": "piano_gentle_broken_chords",
                "sparse_chords_with_sustained_bass": "piano_sparse_chords_with_sustained_bass",
                "slow_arpeggio_with_pedal": "piano_slow_arpeggio_with_pedal_rh",
                "sparse_moving_chords": "piano_sparse_moving_chords",
                "powerful_octave_chords": "piano_powerful_octave_chords",
                "dreamy_arpeggio": "piano_dreamy_arpeggio", # rhythm_library に定義
                "lyrical_arpeggio": "piano_lyrical_arpeggio_rh", # rhythm_library に定義
                "grand_block_chords": "piano_grand_block_chords",
                "simple_piano": "piano_block_quarters_simple"
            },
            "style_to_rhythm_key_lh": { # PianoGenerator側でこのマッピングを使うか、あるいは params に具体的なリズムキー名を入れるか。
                "gentle_root_lh": "piano_gentle_sustained_root_lh",
                "walking_bass_like_lh": "piano_gentle_walking_bass_quarters_lh",
                "active_octave_bass_lh": "piano_active_octave_bass_lh",
                "simple_root_lh": "piano_lh_quarter_roots", # 4分音符ルート
                "default": "piano_lh_whole_notes"
            },
            "default_apply_pedal": True,
            "default_arp_note_ql": 0.5,
            "default_rh_voicing_style": "closed",
            "default_lh_voicing_style": "closed",
            "default_rh_target_octave": 4,
            "default_lh_target_octave": 2,
            "default_rh_num_voices": 3, "default_lh_num_voices": 1
        },
        "drums": {
            "emotion_to_style_key": {
                "struggle_with_underlying_strength": "ballad_soft_kick_snare_8th_hat",
                "deep_regret_and_gratitude": "rock_ballad_build_up_8th_hat",
                "love_pain_acceptance_and_belief": "anthem_rock_chorus_16th_hat",
                "self_reproach_regret_deep_sadness": "ballad_brushes_4_4", # "verse_2_brushes"
                "supported_light_longing_for_rebirth": "rock_ballad_build_up_8th_hat",
                "reflective_transition_instrumental_passage": "no_drums_or_gentle_cymbal_swell",
                "memory_unresolved_feelings_silence": "ballad_sparse_drums_with_cymbal", # 新規追加想定
                "wavering_heart_gratitude_chosen_strength": "driving_rock_beat_with_tom_fills", # 新規追加想定
                "reaffirmed_strength_of_love_positive_determination": "anthem_rock_main_4_4",
                "hope_dawn_light_gentle_guidance": "dreamy_pad_with_sparse_percussion", # 新規追加想定
                "nature_memory_floating_sensation_forgiveness": "no_drums_or_sparse_chimes",
                "future_cooperation_our_path_final_resolve_and_liberation": "epic_rock_drums_with_cymbal_crashes", # 新規追加想定
                "default_style": "basic_rock_4_4_light" # フォールバック
            },
            "intensity_to_base_velocity": {
                "very_low": 40, "low": 50, "medium_low": 60, "medium": 70,
                "medium_high": 80, "high": 90, "very_high": 100,
                "high_to_very_high_then_fade": (80,110) # (開始, 終了) のタプル
            },
            "default_fill_interval_bars": 4,
            "default_fill_keys": ["simple_snare_roll_half_bar", "chorus_end_fill", "crescendo_roll"] # 候補を増やす
        }
    },
    "output_filename_template": "output_{song_title}.mid"
}

# (load_json_file 関数は変更なし)


def translate_keywords_to_params(
        musical_intent: Dict[str, Any], chord_block_specific_hints: Dict[str, Any],
        instrument_cfg_defaults: Dict[str, Any], instrument_name_key: str
) -> Dict[str, Any]:
    """
    音楽的指示キーワード (emotion, intensity, nuance, part_specific_hintsなど) を、
    各楽器ジェネレータが使用する具体的なパラメータに変換する。

    (この関数は今後の開発で最も重要。AIとの対話の中心となる部分)
    """
    params: Dict[str, Any] = {} # 返り値となるパラメータ辞書
    emotion_key = musical_intent.get("emotion", "neutral").lower()
    intensity_key = musical_intent.get("intensity", "medium").lower()

    logger.debug(f"translate_keywords: instrument='{instrument_name_key}', emotion='{emotion_key}', intensity='{intensity_key}', block_hints={chord_block_specific_hints}")

    if instrument_name_key == "piano": # ピアノパラメータ変換
        cfg = instrument_cfg_defaults # 短縮名

        # 1. セクションの part_settings を取得 (chordmap.json から渡される想定)
        #    これは prepare_processed_stream で musical_intent にマージされるか、
        #    あるいは chord_block_specific_hints の一部として渡されるべき。
        #    ここでは chord_block_specific_hints に part_settings が含まれると仮定。
        part_settings = chord_block_specific_hints.get("part_settings", {}).get("piano", {})

        # 2. スタイルキーワードを決定 (セクション指定 -> 感情マップ -> デフォルト)
        rh_style_kw = part_settings.get("piano_rh_style_keyword",
                        cfg.get("emotion_to_rh_style_keyword", {}).get(emotion_key,
                                                                    cfg.get("default_rh_style_keyword", "simple_block_rh")))
        lh_style_kw = part_settings.get("piano_lh_style_keyword",
                        cfg.get("emotion_to_lh_style_keyword", {}).get(emotion_key,
                                                                    cfg.get("default_lh_style_keyword", "simple_root_lh")))

        # 3. スタイルキーワードを実際のリズムライブラリのキーに変換
        params["piano_rh_rhythm_key"] = cfg.get("style_keyword_to_rhythm_key", {}).get(rh_style_kw)
        # もしリズムキーが rhythm_library に存在しない場合はフォールバック
        if params.get("piano_rh_rhythm_key") not in rhythm_library.get("piano_patterns", {}):
             logger.warning(f"translate_keywords: piano_rh_rhythm_key '{params['piano_rh_rhythm_key']}' not found in rhythm_library.")
             params["piano_rh_rhythm_key"] = "default_piano_quarters" # フォールバックキーを rhythm_library に合わせて調整

        params["piano_lh_rhythm_key"] = cfg.get("style_keyword_to_rhythm_key", {}).get(lh_style_kw)
        if params.get("piano_lh_rhythm_key") not in rhythm_library.get("piano_patterns", {}): # 左手も同様
             logger.warning(f"translate_keywords: piano_lh_rhythm_key '{params['piano_lh_rhythm_key']}' not found in rhythm_library.")
             params["piano_lh_rhythm_key"] = "piano_lh_whole_notes" # フォールバック

        # 4. ベロシティ (強度マップ -> デフォルト)
        vel_ranges = cfg.get("intensity_to_velocity_ranges", {}).get(intensity_key, cfg.get("intensity_to_velocity_ranges", {}).get("default", (65,75)))
        params["piano_velocity_rh"] = random.randint(vel_ranges[0], vel_ranges[1]) if isinstance(vel_ranges, Sequence) and len(vel_ranges)==2 else 64 # デフォルト
        
        lh_vel_ranges = cfg.get("intensity_to_velocity_lh", {}).get(intensity_key, cfg.get("intensity_to_velocity_lh", {}).get("default", (55,65)))
        params["piano_velocity_lh"] = random.randint(lh_vel_ranges[0], lh_vel_ranges[1]) if isinstance(lh_vel_ranges, Sequence) and len(lh_vel_ranges) == 2 else 60

        # 5. その他ピアノパラメータ
        params["piano_apply_pedal"] = section_piano_settings.get("piano_apply_pedal", cfg.get("default_apply_pedal", True))
        params["piano_arp_note_ql"] = section_piano_settings.get("piano_arp_note_ql", cfg.get("default_arp_note_ql", 0.5))
        params["piano_rh_voicing_style"] = section_piano_settings.get("piano_rh_voicing_style", cfg.get("default_rh_voicing_style", "closed"))
        params["piano_lh_voicing_style"] = section_piano_settings.get("piano_lh_voicing_style", cfg.get("default_lh_voicing_style", "closed"))
        params["piano_rh_target_octave"] = section_piano_settings.get("piano_rh_target_octave", cfg.get("default_rh_target_octave", DEFAULT_PIANO_RH_OCTAVE))
        params["piano_lh_target_octave"] = section_piano_settings.get("piano_lh_target_octave", cfg.get("default_lh_target_octave", DEFAULT_PIANO_LH_OCTAVE))
        params["piano_rh_num_voices"] = section_piano_settings.get("piano_rh_num_voices", cfg.get("default_rh_num_voices", 3))
        params["piano_lh_num_voices"] = section_piano_settings.get("piano_lh_num_voices", cfg.get("default_lh_num_voices", 1))

        # コードブロック固有のヒントで上書き
        piano_hints = chord_block_specific_hints.get("part_specific_hints", {}).get("piano", {})
        params.update(piano_hints)


    elif instrument_name_key == "drums": # ドラムパラメータ変換
        cfg = instrument_cfg_defaults
        sec_drum_settings = chord_block_specific_hints.get("part_settings", {}).get("drums", {})

        params["drum_style_key"] = sec_drum_settings.get("drum_style_key",
                                   cfg.get("emotion_to_style_key", {}).get(emotion_key,
                                                                           cfg.get("default_style", "no_drums")))
        if not params["drum_style_key"] or params["drum_style_key"] not in rhythm_library.get("drum_patterns", {}): # 存在チェック
            params["drum_style_key"] = "default_drum_pattern" # 強制フォールバック

        intensity_velocity_map = cfg.get("intensity_to_base_velocity", {})
        vel_base = intensity_velocity_map.get(intensity_key, DEFAULT_VELOCITY) if intensity_key in intensity_velocity_map else \
                   intensity_velocity_map.get("default", DEFAULT_VELOCITY)
        # velocity_map が (min, max) のタプルの場合を考慮
        if isinstance(vel_base, tuple) and len(vel_base) == 2 :
             params["drum_base_velocity"] = random.randint(vel_base[0], vel_base[1])
        else: params["drum_base_velocity"] = vel_base
        
        params["drum_fill_interval_bars"] = sec_drum_settings.get("drum_fill_interval_bars", cfg.get("default_fill_interval_bars", 0))
        params["drum_fill_keys"] = sec_drum_settings.get("drum_fill_keys", cfg.get("default_fill_keys", []))
        
        if "drum_fill" in chord_block_specific_hints: params["drum_fill_key_override"] = chord_block_specific_hints["drum_fill"]
        # if "nuance" in chord_block_specific_hints : pass # 必要なら nuance も処理

    else:
        logger.warning(f"No parameter translation logic defined for instrument: {instrument_name_key}")

    logger.info(f"Translated params for [{instrument_name_key}] (Emo: {emotion}, Int: {intensity}): {params}")
    return params

# ... (prepare_processed_stream, run_composition, main_cli はほぼ変更なし)

# --- END OF FILE generator/modular_composer.py ---
