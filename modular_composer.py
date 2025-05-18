# --- START OF FILE modular_composer.py (修正版) ---
import music21
import sys
import os # sys と os は load_json_file の sys.exit(1) のために残すか、例外処理を見直す
import json
import argparse
import logging
from music21 import stream, tempo, instrument as m21instrument, midi, meter, key
from pathlib import Path
from typing import List, Dict, Optional, Any, cast, Sequence # Sequence を追加
import random

# --- ジェネレータクラスのインポート (generatorフォルダから) ---
try:
    from generator.core_music_utils import get_time_signature_object # これを主に使う
    from generator.piano_generator import PianoGenerator
    from generator.drum_generator import DrumGenerator
    from generator.chord_voicer import ChordVoicer
    from generator.melody_generator import MelodyGenerator # 必要に応じてコメント解除
    from generator.bass_core_generator import BassCoreGenerator # 必要に応じてコメント解除
    # from generator.guitar_generator import GuitarGenerator
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import generator modules. Check file structure or PYTHONPATH: {e}")
    exit(1)
except Exception as e_imp: # インポート時の予期せぬエラーもキャッチ
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
            "emotion_to_rh_style_keyword": { # 感情 -> 右手スタイルキーワード
                "nostalgic_gentle": "gentle_block_chords_rh",
                "warm_recollection": "flowing_arpeggio_rh",
                "deep_regret_and_gratitude": "sparse_chords_rh",
                "love_pain_acceptance_and_belief": "powerful_block_rh",
                # ... (他の感情とRHスタイルキーワードのマッピング) ...
                "default": "simple_block_rh" # フォールバックのRHスタイルキーワード
            },
            "emotion_to_lh_style_keyword": { # 感情 -> 左手スタイルキーワード
                "nostalgic_gentle": "gentle_root_lh",
                "warm_recollection": "sustained_bass_lh",
                "deep_regret_and_gratitude": "walking_bass_like_lh",
                "love_pain_acceptance_and_belief": "active_octave_lh",
                # ... (他の感情とLHスタイルキーワードのマッピング) ...
                "default": "simple_root_lh" # フォールバックのLHスタイルキーワード
            },
            "style_keyword_to_rhythm_key": { # スタイルキーワード -> リズムライブラリのキー
                # 右手用
                "gentle_block_chords_rh": "piano_gentle_block_whole_rh",
                "flowing_arpeggio_rh": "piano_flowing_arpeggio_eighths_rh",
                "sparse_chords_rh": "piano_sparse_chords_quarters_rh", # 例
                "powerful_block_rh": "piano_powerful_block_8ths_rh",
                "simple_block_rh": "piano_block_quarters_simple",
                # 左手用
                "gentle_root_lh": "piano_gentle_sustained_root_lh",
                "sustained_bass_lh": "piano_lh_whole_notes", # 例
                "walking_bass_like_lh": "piano_gentle_walking_bass_quarters_lh",
                "active_octave_lh": "piano_active_octave_bass_lh",
                "simple_root_lh": "piano_lh_quarter_roots",
                # フォールバック用 (もし上記のキーワードが見つからない場合)
                "default_piano_rh_fallback_rhythm": "piano_block_quarters_simple",
                "default_piano_lh_fallback_rhythm": "piano_lh_whole_notes"
            },
            "intensity_to_velocity_ranges": { # (LH_min, LH_max, RH_min, RH_max)
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
            "default_rh_voicing_style": "closed",
            "default_lh_voicing_style": "closed", # 通常LHは単音だが、オプションとして
            "default_rh_target_octave": 4,
            "default_lh_target_octave": 2,
            "default_rh_num_voices": 3,
            "default_lh_num_voices": 1
        },
        "drums": {
            "emotion_to_style_key": { # 感情 -> ドラムスタイルキー (rhythm_library.jsonのキー)
                "struggle_with_underlying_strength": "ballad_soft_kick_snare_8th_hat",
                "deep_regret_and_gratitude": "rock_ballad_build_up_8th_hat",
                "love_pain_acceptance_and_belief": "anthem_rock_chorus_16th_hat",
                # ... (他のマッピング) ...
                "default_style": "basic_rock_4_4" # フォールバック、"no_drums" より具体的が良いかも
            },
            "intensity_to_base_velocity": {
                "very_low": 45, "low": 55, "medium_low": 65, "medium": 75,
                "medium_high": 85, "high": 95, "very_high": 105,
                "default": 75
            },
            "default_fill_interval_bars": 4,
            "default_fill_keys": ["simple_snare_roll_half_bar", "chorus_end_fill"]
        },
        "chords": {
            "instrument": "StringInstrument",
            "chord_voicing_style": "closed",
            "chord_target_octave": 3,
            "chord_num_voices": 4,
            "chord_velocity": 64
        }
    },
    "output_filename_template": "output_{song_title}.mid"
}

def load_json_file(file_path: Path, name: str) -> Any:
    if not file_path.exists():
        logger.error(f"{name} ファイルが見つかりません: {file_path}")
        sys.exit(1) # クリティカルなエラーなので終了
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Successfully loaded {name} from: {file_path}")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"{name} のJSONパースに失敗しました (line {e.lineno} col {e.colno}: {e.msg}): {file_path}")
        sys.exit(1) # クリティカルなエラー
    except Exception as e_load:
        logger.error(f"予期せぬエラーで {name} の読み込みに失敗: {e_load} ({file_path})", exc_info=True)
        sys.exit(1) # クリティカルなエラー

def translate_keywords_to_params(
        musical_intent: Dict[str, Any],
        chord_block_specific_hints: Dict[str, Any],
        default_instrument_params: Dict[str, Any], # DEFAULT_CONFIG["default_part_parameters"][instr_key]
        instrument_name_key: str,
        rhythm_library: Dict # ★★★ rhythm_library を引数に追加 ★★★
) -> Dict[str, Any]:
    params: Dict[str, Any] = default_instrument_params.copy() # まず楽器のデフォルトパラメータ群をコピー
    emotion_key = musical_intent.get("emotion", "neutral").lower()
    intensity_key = musical_intent.get("intensity", "medium").lower()

    logger.debug(
        f"Translating for {instrument_name_key}: Emo='{emotion_key}', Int='{intensity_key}', "
        f"BlockHints='{chord_block_specific_hints}'"
    )

    # セクション全体の楽器設定 (chordmap.json の part_settings から来る)
    section_instrument_settings = chord_block_specific_hints.get("part_settings", {}).get(instrument_name_key, {})
    # params にセクションレベルの設定をマージ (セクション設定がデフォルトを上書き)
    params.update(section_instrument_settings)


    if instrument_name_key == "piano":
        # 感情 -> スタイルキーワード (paramsに既にあればそれを使う、なければ感情マップ -> デフォルトのデフォルト)
        rh_style_kw = params.get("piano_rh_style_keyword", # セクション指定を優先
                        default_instrument_params.get("emotion_to_rh_style_keyword", {}).get(emotion_key,
                                        default_instrument_params.get("emotion_to_rh_style_keyword", {}).get("default")))
        params["piano_rh_style_keyword"] = rh_style_kw # 最終的なスタイルキーワードを格納

        lh_style_kw = params.get("piano_lh_style_keyword",
                        default_instrument_params.get("emotion_to_lh_style_keyword", {}).get(emotion_key,
                                        default_instrument_params.get("emotion_to_lh_style_keyword", {}).get("default")))
        params["piano_lh_style_keyword"] = lh_style_kw

        # スタイルキーワード -> リズムキー
        style_to_rhythm_map = default_instrument_params.get("style_keyword_to_rhythm_key", {})
        params["piano_rh_rhythm_key"] = style_to_rhythm_map.get(rh_style_kw)
        if not params["piano_rh_rhythm_key"] or params.get("piano_rh_rhythm_key") not in rhythm_library.get("piano_patterns", {}):
             logger.warning(f"Piano RH rhythm key '{params.get('piano_rh_rhythm_key')}' for style '{rh_style_kw}' not found. Using fallback.")
             params["piano_rh_rhythm_key"] = style_to_rhythm_map.get("default_piano_rh_fallback_rhythm", "default_piano_quarters")

        params["piano_lh_rhythm_key"] = style_to_rhythm_map.get(lh_style_kw)
        if not params["piano_lh_rhythm_key"] or params.get("piano_lh_rhythm_key") not in rhythm_library.get("piano_patterns", {}):
             logger.warning(f"Piano LH rhythm key '{params.get('piano_lh_rhythm_key')}' for style '{lh_style_kw}' not found. Using fallback.")
             params["piano_lh_rhythm_key"] = style_to_rhythm_map.get("default_piano_lh_fallback_rhythm", "piano_lh_whole_notes")

        # ベロシティ
        vel_map = default_instrument_params.get("intensity_to_velocity_ranges", {})
        default_vel_tuple = vel_map.get("default", (60, 70, 65, 75))
        lh_min_cfg, lh_max_cfg, rh_min_cfg, rh_max_cfg = vel_map.get(intensity_key, default_vel_tuple)
        params["piano_velocity_lh"] = random.randint(lh_min_cfg, lh_max_cfg)
        params["piano_velocity_rh"] = random.randint(rh_min_cfg, rh_max_cfg)

        # その他ピアノパラメータ (セクション指定があればそれを使い、なければデフォルトのデフォルト値)
        # (params に既に section_instrument_settings がマージされているので、.get で取得すればよい)
        params["piano_apply_pedal"] = params.get("piano_apply_pedal", default_instrument_params.get("default_apply_pedal"))
        params["piano_arp_note_ql"] = params.get("piano_arp_note_ql", default_instrument_params.get("default_arp_note_ql"))
        params["piano_rh_voicing_style"] = params.get("piano_rh_voicing_style", default_instrument_params.get("default_rh_voicing_style"))
        params["piano_lh_voicing_style"] = params.get("piano_lh_voicing_style", default_instrument_params.get("default_lh_voicing_style"))
        params["piano_rh_target_octave"] = params.get("piano_rh_target_octave", default_instrument_params.get("default_rh_target_octave"))
        params["piano_lh_target_octave"] = params.get("piano_lh_target_octave", default_instrument_params.get("default_lh_target_octave"))
        params["piano_rh_num_voices"] = params.get("piano_rh_num_voices", default_instrument_params.get("default_rh_num_voices"))
        params["piano_lh_num_voices"] = params.get("piano_lh_num_voices", default_instrument_params.get("default_lh_num_voices"))

    elif instrument_name_key == "drums":
        style_key_from_emotion = default_instrument_params.get("emotion_to_style_key", {}).get(emotion_key,
                                   default_instrument_params.get("emotion_to_style_key", {}).get("default_style"))
        params["drum_style_key"] = params.get("drum_style_key", style_key_from_emotion) # セクション指定優先
        
        # ドラムスタイルキーの存在チェックとフォールバック
        if not params["drum_style_key"] or params.get("drum_style_key") not in rhythm_library.get("drum_patterns", {}):
            logger.warning(f"Drum style key '{params.get('drum_style_key')}' not found. Using default drum pattern.")
            params["drum_style_key"] = "default_drum_pattern" # 確実に存在するキーにフォールバック

        vel_map = default_instrument_params.get("intensity_to_base_velocity", {})
        default_drum_vel = vel_map.get("default", 75)
        vel_base_val = params.get("drum_base_velocity", vel_map.get(intensity_key, default_drum_vel)) # セクション指定優先

        if isinstance(vel_base_val, tuple) and len(vel_base_val) == 2:
            params["drum_base_velocity"] = random.randint(vel_base_val[0], vel_base_val[1])
        else:
            params["drum_base_velocity"] = int(vel_base_val)

        params["drum_fill_interval_bars"] = params.get("drum_fill_interval_bars", default_instrument_params.get("default_fill_interval_bars"))
        params["drum_fill_keys"] = params.get("drum_fill_keys", default_instrument_params.get("default_fill_keys"))

    # コードブロック固有のヒントで最終上書き (part_specific_hints の中の、さらに楽器名キーの中)
    block_instrument_hints = chord_block_specific_hints.get("part_specific_hints", {}).get(instrument_name_key, {})
    params.update(block_instrument_hints)

    # drum_fill は chord_block_specific_hints 直下から取得 (特別扱い)
    if instrument_name_key == "drums" and "drum_fill" in chord_block_specific_hints:
        params["drum_fill_key_override"] = chord_block_specific_hints["drum_fill"]

    logger.info(f"Translated params for [{instrument_name_key}] (Emo: {emotion_key}, Int: {intensity_key}) -> {params}")
    return params

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_library: Dict) -> List[Dict]: # rhythm_library を追加
    processed_stream: List[Dict] = []
    current_abs_offset: float = 0.0

    global_settings = chordmap_data.get("global_settings", {})
    time_sig_str = global_settings.get("time_signature", main_config["global_time_signature"])
    ts_obj = get_time_signature_object(time_sig_str)
    beats_per_measure = ts_obj.barDuration.quarterLength

    global_key_tonic = global_settings.get("key_tonic", main_config["global_key_tonic"])
    global_key_mode = global_settings.get("key_mode", main_config["global_key_mode"])

    sorted_sections = sorted(chordmap_data.get("sections", {}).items(), key=lambda item: item[1].get("order", float('inf')))

    for section_name, sec_info in sorted_sections:
        logger.info(f"Preparing blocks for section: {section_name}")
        sec_musical_intent = sec_info.get("musical_intent", {})
        sec_part_settings = sec_info.get("part_settings", {})
        sec_tonic = sec_info.get("tonic", global_key_tonic)
        sec_mode = sec_info.get("mode", global_key_mode)
        sec_len_measures = sec_info.get("length_in_measures")

        chord_progression = sec_info.get("chord_progression", [])
        if not chord_progression:
            logger.warning(f"Section '{section_name}' has no chord_progression. Skipping section.")
            continue

        for chord_idx, chord_block_def in enumerate(chord_progression):
            chord_label = chord_block_def.get("label", "C")
            duration_b: float
            if "duration_beats" in chord_block_def:
                duration_b = float(chord_block_def["duration_beats"])
            elif sec_len_measures:
                duration_b = (float(sec_len_measures) * beats_per_measure) / len(chord_progression)
            else:
                duration_b = beats_per_measure

            block_intent_final = sec_musical_intent.copy()
            if "emotion" in chord_block_def: block_intent_final["emotion"] = chord_block_def["emotion"]
            if "intensity" in chord_block_def: block_intent_final["intensity"] = chord_block_def["intensity"]

            # chord_block_def のうち、予約語以外を block_specific_hints に含める
            # さらに、セクション全体のpart_settingsも "part_settings" キーでマージ
            block_hints_for_translate = {
                k: v for k, v in chord_block_def.items()
                if k not in ["label", "duration_beats", "order", "musical_intent", "part_settings", "tensions_to_add"]
            }
            block_hints_for_translate["part_settings"] = sec_part_settings # セクション全体の楽器設定を渡す

            block_data = {
                "offset": current_abs_offset, "q_length": duration_b, "chord_label": chord_label,
                "section_name": section_name, "tonic_of_section": sec_tonic, "mode": sec_mode,
                "tensions_to_add": chord_block_def.get("tensions_to_add", []),
                "is_first_in_section": (chord_idx == 0),
                "is_last_in_section": (chord_idx == len(chord_progression) - 1),
                "part_params": {}
            }

            for part_name_key in main_config["parts_to_generate"].keys():
                default_params_for_part = main_config["default_part_parameters"].get(part_name_key, {})
                block_data["part_params"][part_name_key] = translate_keywords_to_params(
                    block_intent_final,
                    block_hints_for_translate, # 整理したヒント
                    default_params_for_part,
                    part_name_key,
                    rhythm_library # ★★★ translate_keywords_to_params に渡す ★★★
                )
            processed_stream.append(block_data)
            current_abs_offset += duration_b

    logger.info(f"Prepared {len(processed_stream)} processing blocks. Total duration: {current_abs_offset:.2f} beats.")
    return processed_stream

def run_composition(cli_args: argparse.Namespace, main_config: Dict,
                    chordmap_data: Dict, rhythm_library_data: Dict):
    logger.info("=== Running Main Composition ===")

    final_score = stream.Score()
    final_score.insert(0, tempo.MetronomeMark(number=main_config["global_tempo"]))
    try:
        ts_object = get_time_signature_object(main_config["global_time_signature"])
        final_score.insert(0, ts_object)
        key_tonic_to_set = main_config["global_key_tonic"]
        key_mode_to_set = main_config["global_key_mode"]
        if chordmap_data.get("sections"):
            try:
                first_sec_name = sorted(chordmap_data["sections"].keys(), key=lambda k_s: chordmap_data["sections"][k_s].get("order", float('inf')))[0]
                first_sec_info = chordmap_data["sections"][first_sec_name]
                key_tonic_to_set = first_sec_info.get("tonic", key_tonic_to_set)
                key_mode_to_set = first_sec_info.get("mode", key_mode_to_set)
            except IndexError: # sections が空の場合など
                logger.warning("No sections found in chordmap to determine initial key, using global.")
        final_score.insert(0, key.Key(key_tonic_to_set, key_mode_to_set.lower()))
    except Exception as e_score_glob:
        logger.error(f"Error setting global elements on final_score: {e_score_glob}. Using defaults.", exc_info=True)
        final_score.insert(0, meter.TimeSignature("4/4"))
        final_score.insert(0, key.Key("C", "major"))

    processed_blocks = prepare_processed_stream(chordmap_data, main_config, rhythm_library_data) # rhythm_library_data を渡す
    if not processed_blocks:
        logger.error("No processable blocks. Aborting part composition.")
        return

    active_chord_voicer = ChordVoicer(
        global_tempo=main_config["global_tempo"],
        global_time_signature=main_config["global_time_signature"]
    )
    generator_instances: Dict[str, Any] = {}

    # ジェネレータのインスタンス化 (設定に基づいて)
    if main_config["parts_to_generate"].get("piano", False):
        generator_instances["piano"] = PianoGenerator(
            rhythm_library=cast(Dict[str, Dict], rhythm_library_data.get("piano_patterns", {})),
            chord_voicer_instance=active_chord_voicer,
            global_tempo=main_config["global_tempo"],
            global_time_signature=main_config["global_time_signature"]
        )
    if main_config["parts_to_generate"].get("drums", False):
        generator_instances["drums"] = DrumGenerator(
            drum_pattern_library=cast(Dict[str, Dict[str, Any]], rhythm_library_data.get("drum_patterns", {})),
            global_tempo=main_config["global_tempo"],
            global_time_signature=main_config["global_time_signature"]
        )
    if main_config["parts_to_generate"].get("chords", False):
         generator_instances["chords"] = active_chord_voicer # ChordVoicerを独立パートとして使用

    # ... (他のジェネレータのインスタンス化も同様に追加)

    # パート生成ループ
    for part_name, gen_instance in generator_instances.items():
        if gen_instance:
            logger.info(f"Generating {part_name} part...")
            try:
                if part_name == "piano" and isinstance(gen_instance, PianoGenerator):
                    piano_s = gen_instance.compose(processed_blocks)
                    if piano_s and piano_s.parts:
                        for p_part in piano_s.parts: final_score.insert(0, p_part)
                elif part_name == "chords" and isinstance(gen_instance, ChordVoicer):
                    # ChordVoicer の compose にはデフォルトスタイルとオクターブを渡す
                    # これらのデフォルトは main_config の default_part_parameters から取得
                    cv_defaults = main_config["default_part_parameters"].get("chords", {})
                    default_cv_style = cv_defaults.get("chord_voicing_style", "closed")
                    default_cv_octave = cv_defaults.get("chord_target_octave", 3)
                    # ChordVoicerのcomposeメソッドのシグネチャを再確認
                    # def compose(self, processed_chord_stream: List[Dict]) -> stream.Part;
                    # のように、デフォルトスタイルは processed_stream 内の part_params から取得させる方が良いかもしれない。
                    # ここでは、一時的に古い呼び出し方を模倣するが、ChordVoicer.composeの修正を推奨。
                    chord_stream_part = gen_instance.compose(processed_blocks) # processed_blocksだけ渡す形に修正
                    if chord_stream_part and chord_stream_part.flatten().notesAndRests:
                        final_score.insert(0, chord_stream_part)
                elif hasattr(gen_instance, "compose"):
                    part_obj = gen_instance.compose(processed_blocks)
                    if part_obj and part_obj.flatten().notesAndRests:
                        final_score.insert(0, part_obj)
                logger.info(f"{part_name} part generated.")
            except Exception as e_gen_part:
                logger.error(f"Error during {part_name} part generation: {e_gen_part}", exc_info=True)

    project_title = chordmap_data.get("project_title", "untitled_song").replace(" ", "_").lower()
    output_filename_to_use = cli_args.output_filename if cli_args.output_filename else main_config["output_filename_template"].format(song_title=project_title)
    output_path = cli_args.output_dir / output_filename_to_use
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if final_score.flatten().notesAndRests:
            final_score.write('midi', fp=str(output_path))
            logger.info(f"🎉🎉🎉 MIDI file successfully generated: {output_path}")
        else:
            logger.warning(f"Final score is empty. No MIDI file written to {output_path}.")
    except Exception as e_write_midi:
        logger.error(f"Failed to write MIDI to {output_path}: {e_write_midi}", exc_info=True)

def main_cli():
    parser = argparse.ArgumentParser(description="Modular Music Composer (Keyword-Driven v3)")
    parser.add_argument("chordmap_file", type=Path, help="Path to the chordmap JSON file.")
    parser.add_argument("rhythm_library_file", type=Path, help="Path to the rhythm library JSON file.")
    parser.add_argument("--output-dir", type=Path, default=Path("midi_output"), help="Directory for output MIDI files.")
    parser.add_argument("--output-filename", type=str, help="Filename for the output MIDI (e.g., my_song.mid). If not given, uses template.")
    parser.add_argument("--settings-file", type=Path, help="Path to custom settings JSON file.")
    parser.add_argument("--tempo", type=int, help="Override global tempo.")

    default_parts_config = DEFAULT_CONFIG.get("parts_to_generate", {})
    for part_key, default_state in default_parts_config.items():
        arg_name = f"generate_{part_key}"
        if default_state is True:
            parser.add_argument(f"--no-{part_key}", action="store_false", dest=arg_name, help=f"Do not generate {part_key} part.")
        else:
            parser.add_argument(f"--include-{part_key}", action="store_true", dest=arg_name, help=f"Generate {part_key} part.")
    parser.set_defaults(**{f"generate_{k}": v for k, v in default_parts_config.items()})

    args = parser.parse_args()
    active_config = DEFAULT_CONFIG.copy() # deepcopyがより安全な場合もある
    if args.settings_file and args.settings_file.exists():
        custom_settings = load_json_file(args.settings_file, "Custom settings")
        if custom_settings and isinstance(custom_settings, dict):
            def merge_configs(base, new): # ネストした辞書のマージ
                for k, v_new in new.items():
                    if isinstance(v_new, dict) and k in base and isinstance(base[k], dict):
                        merge_configs(base[k], v_new)
                    else:
                        base[k] = v_new
            merge_configs(active_config, custom_settings)

    if args.tempo is not None: active_config["global_tempo"] = args.tempo
    for part_key in active_config.get("parts_to_generate", {}).keys():
        arg_attr_name = f"generate_{part_key}"
        if hasattr(args, arg_attr_name):
             active_config["parts_to_generate"][part_key] = getattr(args, arg_attr_name)

    chordmap = load_json_file(args.chordmap_file, "Chordmap")
    rhythm_library = load_json_file(args.rhythm_library_file, "Rhythm Library")
    if not chordmap or not rhythm_library:
        logger.critical("Essential data files (chordmap or rhythm_library) could not be loaded. Exiting.")
        return

    cm_globals = chordmap.get("global_settings", {})
    active_config["global_tempo"] = cm_globals.get("tempo", active_config["global_tempo"])
    active_config["global_time_signature"] = cm_globals.get("time_signature", active_config["global_time_signature"])
    active_config["global_key_tonic"] = cm_globals.get("key_tonic", active_config["global_key_tonic"])
    active_config["global_key_mode"] = cm_globals.get("key_mode", active_config["global_key_mode"])

    logger.info(f"Final effective config for composition: {json.dumps(active_config, indent=2, ensure_ascii=False)}")
    run_composition(args, active_config, cast(Dict, chordmap), cast(Dict, rhythm_library))

if __name__ == "__main__":
    main_cli()

# --- END OF FILE modular_composer.py ---
