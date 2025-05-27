# --- START OF FILE modular_composer.py (bass_paramsデフォルト設定追加版) ---
# ... (ファイル冒頭のimportや定義はそのまま) ...

def prepare_processed_stream(chordmap_data: Dict, main_config: Dict, rhythm_lib_all: Dict,
                             parsed_vocal_track: List[Dict]) -> List[Dict]:
    processed_stream: List[Dict] = []
    current_abs_offset: float = 0.0
    g_settings = chordmap_data.get("global_settings", {})
    ts_str = g_settings.get("time_signature", main_config["global_time_signature"])
    ts_obj = get_time_signature_object(ts_str)
    if ts_obj is None:
        logger.error("Failed to get TimeSignature object. Defaulting to 4/4 time.")
        ts_obj = music21.meter.TimeSignature("4/4") 
    beats_per_measure = ts_obj.barDuration.quarterLength # o3さん指摘: beatCountの方が良い場合もあるが、現状のduration_beatsが拍数なので、これで小節長を計算

    g_key_t, g_key_m = g_settings.get("key_tonic", main_config["global_key_tonic"]), g_settings.get("key_mode", main_config["global_key_mode"])

    sections_items = chordmap_data.get("sections", {}).items()
    sorted_sections = sorted(sections_items, key=lambda item: item[1].get("order", float('inf')) if isinstance(item[1], dict) else float('inf'))

    for sec_name, sec_info_any in sorted_sections:
        if not isinstance(sec_info_any, dict):
            logger.warning(f"Section '{sec_name}' data is not a dictionary. Skipping.")
            continue
        sec_info: Dict[str, Any] = sec_info_any

        logger.info(f"Preparing section: {sec_name}")
        sec_intent = sec_info.get("musical_intent", {})
        sec_part_settings_for_all_instruments = sec_info.get("part_settings", {})
        sec_t, sec_m = sec_info.get("tonic", g_key_t), sec_info.get("mode", g_key_m)
        sec_len_meas = sec_info.get("length_in_measures")
        chord_prog = sec_info.get("chord_progression", [])
        if not chord_prog:
            logger.warning(f"Section '{sec_name}' has no chord_progression. Skipping.")
            continue

        default_beats_per_chord_block: Optional[float] = None
        if sec_len_meas and len(chord_prog) > 0:
            try:
                default_beats_per_chord_block = (float(sec_len_meas) * beats_per_measure) / len(chord_prog)
            except (ValueError, TypeError):
                logger.warning(f"Could not calculate default_beats_per_chord_block for section {sec_name}.")

        for c_idx, c_def_any in enumerate(chord_prog):
            if not isinstance(c_def_any, dict):
                logger.warning(f"Chord definition at index {c_idx} in section '{sec_name}' is not a dictionary. Skipping.")
                continue
            c_def: Dict[str, Any] = c_def_any

            original_chord_label = c_def.get("label", "C")
            # sanitize_chord_label は bass_generator 側でも呼ばれるが、ここでもログ取りや早期判定のために行う
            sanitized_chord_label_for_block : Optional[str] = sanitize_chord_label(original_chord_label)
            
            if not sanitized_chord_label_for_block:
                logger.error(f"Section '{sec_name}', Chord {c_idx+1}: Label '{original_chord_label}' could not be sanitized nor root extracted. Will be treated as 'C'. Please review chordmap.json.")
                c_lbl_for_block = "C" # フォールバック
            elif sanitized_chord_label_for_block.lower() == "rest":
                c_lbl_for_block = "Rest"
            else:
                c_lbl_for_block = sanitized_chord_label_for_block


            dur_b_val = c_def.get("duration_beats")
            if dur_b_val is not None:
                try: dur_b = float(dur_b_val)
                except (ValueError, TypeError):
                    dur_b = default_beats_per_chord_block if default_beats_per_chord_block is not None else beats_per_measure
            elif default_beats_per_chord_block is not None: dur_b = default_beats_per_chord_block
            else: dur_b = beats_per_measure

            blk_intent = sec_intent.copy();
            if "emotion" in c_def: blk_intent["emotion"] = c_def["emotion"]
            if "intensity" in c_def: blk_intent["intensity"] = c_def["intensity"]
            blk_hints_for_translate = {"part_settings": sec_part_settings_for_all_instruments.copy()}
            current_block_mode = c_def.get("mode", sec_m)
            blk_hints_for_translate["mode_of_block"] = current_block_mode
            reserved_keys = {"label", "duration_beats", "order", "musical_intent", "part_settings", "tensions_to_add", "emotion", "intensity", "mode"}
            for k_hint, v_hint in c_def.items():
                if k_hint not in reserved_keys: blk_hints_for_translate[k_hint] = v_hint

            vocal_notes_in_this_block = [] # (vocal関連の処理は変更なし)
            # ... (vocal_notes_in_this_block の設定ロジック) ...

            blk_data = {
                "offset": current_abs_offset, "q_length": dur_b, "chord_label": c_lbl_for_block, # ここでサニタイズ後のラベルを使用
                "section_name": sec_name, "tonic_of_section": sec_t, "mode": current_block_mode,
                "is_first_in_section":(c_idx==0), "is_last_in_section":(c_idx==len(chord_prog)-1),
                "vocal_notes_in_block": vocal_notes_in_this_block,
                "part_params":{}
            }
            for p_key_name, generate_flag in main_config.get("parts_to_generate", {}).items():
                if generate_flag:
                    default_params_for_instrument = main_config["default_part_parameters"].get(p_key_name, {})
                    chord_specific_settings_for_part = c_def.get("part_specific_hints", {}).get(p_key_name, {})
                    final_hints_for_translate = blk_hints_for_translate.copy()
                    final_hints_for_translate.update(chord_specific_settings_for_part)
                    
                    # translate_keywords_to_params を呼び出す前に、part_params[p_key_name] を初期化しておく
                    blk_data["part_params"][p_key_name] = {} 
                    
                    translated_params = translate_keywords_to_params(
                        blk_intent, final_hints_for_translate, default_params_for_instrument,
                        p_key_name, rhythm_lib_all
                    )
                    blk_data["part_params"][p_key_name].update(translated_params) # updateでマージ

                    # --- o3さん提案#3: bass_params を必ずセット ---
                    if p_key_name == "bass":
                        # translate_keywords_to_params の結果に必要なキーがなければデフォルトを設定
                        if "rhythm_key" not in blk_data["part_params"]["bass"] and "style" not in blk_data["part_params"]["bass"]:
                            blk_data["part_params"]["bass"]["rhythm_key"] = "basic_chord_tone_quarters"
                            logger.debug(f"Block {sec_name}-{c_idx+1}: No bass rhythm/style in chordmap, setting default 'basic_chord_tone_quarters'.")
                        if "velocity" not in blk_data["part_params"]["bass"]:
                            blk_data["part_params"]["bass"]["velocity"] = main_config["default_part_parameters"].get("bass",{}).get("default_velocity", 70)
                        if "octave" not in blk_data["part_params"]["bass"]:
                             blk_data["part_params"]["bass"]["octave"] = main_config["default_part_parameters"].get("bass",{}).get("default_octave", 2)
                    # --- 修正ここまで ---

            processed_stream.append(blk_data)
            current_abs_offset += dur_b
    logger.info(f"Prepared {len(processed_stream)} blocks. Total duration: {current_abs_offset:.2f} beats.")
    return processed_stream

# ... (ファイル内の他の関数やクラス定義はそのまま) ...
