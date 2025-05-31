# --- START OF FILE generator/drum_generator.py (Harugoro-OTO KOTOBA Engine - Schema & Inherit & Override修正版) ---
from __future__ import annotations

import logging, random, math, copy
from typing import Any, Dict, List, Optional, Sequence, Union, Set # Set を追加

from music21 import (
    stream, note, pitch, volume as m21volume, duration as m21dur, tempo,
    meter, instrument as m21instrument,
)

# ▼▼▼ override_loader のインポートは残すが、トップレベルでの呼び出しは削除 ▼▼▼
try:
    from utilities.override_loader import load_overrides, get_part_override # get_part_override は compose 内で使用
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object
    from utilities.humanizer import apply_humanization_to_element
except ImportError:
    logger_fallback_utils_dg = logging.getLogger(__name__ + ".fallback_utils_dg")
    logger_fallback_utils_dg.warning("DrumGen: Could not import from utilities. Using fallbacks for core utils.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except Exception: return meter.TimeSignature("4/4")
    def apply_humanization_to_element(element, template_name=None, custom_params=None):
        return element
    # ダミーの get_part_override (インポート失敗時)
    class DummyPartOverride: model_config = {}; model_fields = {} # pydantic.BaseModelのダミー
    def get_part_override(overrides, section, part, cli_override=None) -> DummyPartOverride: return DummyPartOverride()


logger = logging.getLogger(__name__)

# ... (GM_DRUM_MAP, GHOST_ALIAS, EMOTION_TO_BUCKET, BUCKET_INTENSITY_TO_STYLE, _resolve_style は変更なし) ...
GM_DRUM_MAP: Dict[str, int] = {
    "kick": 36, "bd": 36, "acoustic_bass_drum": 35,
    "snare": 38, "sd": 38, "acoustic_snare": 38, "electric_snare": 40,
    "closed_hi_hat": 42, "chh": 42, "closed_hat": 42,
    "pedal_hi_hat": 44, "phh": 44,
    "open_hi_hat": 46, "ohh": 46, "open_hat": 46,
    "crash_cymbal_1": 49, "crash": 49, "crash_cymbal_2": 57,
    "ride_cymbal_1": 51, "ride": 51, "ride_cymbal_2": 59,
    "ride_bell": 53,
    "hand_clap": 39, "claps": 39,
    "side_stick": 37, "rim": 37, "rim_shot": 37,
    "low_floor_tom": 41,   "tom_floor_low": 41,
    "high_floor_tom": 43,  "tom_floor_high": 43,
    "low_tom": 45,         "tom_low": 45,
    "low_mid_tom": 47,     "tom_mid_low": 47, "tom_mid": 47,
    "high_mid_tom": 48,    "tom_mid_high": 48, "tom1": 48,
    "high_tom": 50,        "tom_hi": 50,
    "tom2": 47, "tom3": 45, "hat": 42, "stick": 31,
    "tambourine": 54, "splash": 55, "splash_cymbal": 55, "cowbell": 56,
    "china": 52, "china_cymbal": 52, "shaker": 82, "cabasa": 69, "triangle": 81,
    "wood_block_high": 76, "high_wood_block": 76, "wood_block_low": 77, "low_wood_block": 77,
    "guiro_short": 73, "short_guiro": 73, "guiro_long": 74, "long_guiro": 74,
    "claves": 75, "bongo_high": 60, "high_bongo": 60, "bongo_low": 61, "low_bongo": 61,
    "conga_open": 62, "mute_high_conga": 62, "conga_slap": 63, "open_high_conga": 63,
    "timbale_high": 65, "high_timbale": 65, "timbale_low": 66, "low_timbale": 66,
    "agogo_high": 67, "high_agogo": 67, "agogo_low": 68, "low_agogo": 68,
    "ghost_snare": 38,
}
GHOST_ALIAS: Dict[str, str] = {"ghost_snare": "snare", "gs": "snare"}

EMOTION_TO_BUCKET: Dict[str, str] = {
    "quiet_pain_and_nascent_strength": "ballad_soft", "self_reproach_regret_deep_sadness": "ballad_soft",
    "memory_unresolved_feelings_silence": "ballad_soft", "reflective_transition_instrumental_passage": "ballad_soft",
    "deep_regret_gratitude_and_realization": "groove_mid", "supported_light_longing_for_rebirth": "groove_mid",
    "wavering_heart_gratitude_chosen_strength": "groove_mid", "hope_dawn_light_gentle_guidance": "groove_mid",
    "nature_memory_floating_sensation_forgiveness": "groove_mid",
    "acceptance_of_love_and_pain_hopeful_belief": "anthem_high", "trial_cry_prayer_unbreakable_heart": "anthem_high",
    "reaffirmed_strength_of_love_positive_determination": "anthem_high",
    "future_cooperation_our_path_final_resolve_and_liberation": "anthem_high",
    "default": "groove_mid", "neutral": "groove_mid"
}
BUCKET_INTENSITY_TO_STYLE: Dict[str, Dict[str, str]] = {
    "ballad_soft": {"low": "no_drums_or_gentle_cymbal_swell", "medium_low": "ballad_soft_kick_snare_8th_hat", "medium": "ballad_soft_kick_snare_8th_hat", "medium_high": "rock_ballad_build_up_8th_hat", "high": "rock_ballad_build_up_8th_hat", "default": "ballad_soft_kick_snare_8th_hat"},
    "groove_mid": {"low": "ballad_soft_kick_snare_8th_hat", "medium_low": "rock_ballad_build_up_8th_hat", "medium": "rock_ballad_build_up_8th_hat", "medium_high": "anthem_rock_chorus_16th_hat", "high": "anthem_rock_chorus_16th_hat", "default": "rock_ballad_build_up_8th_hat"},
    "anthem_high": {"low": "rock_ballad_build_up_8th_hat", "medium_low": "anthem_rock_chorus_16th_hat", "medium": "anthem_rock_chorus_16th_hat", "medium_high": "anthem_rock_chorus_16th_hat", "high": "anthem_rock_chorus_16th_hat", "default": "anthem_rock_chorus_16th_hat"},
    "default_fallback_bucket": {"low": "no_drums", "medium_low": "default_drum_pattern", "medium": "default_drum_pattern", "medium_high": "default_drum_pattern", "high": "default_drum_pattern", "default": "default_drum_pattern"}
}

def _resolve_style(emotion:str, intensity:str, pattern_lib: Dict[str, Any]) -> str:
    bucket = EMOTION_TO_BUCKET.get(emotion.lower(), "default_fallback_bucket")
    style_map_for_bucket = BUCKET_INTENSITY_TO_STYLE.get(bucket)
    if not style_map_for_bucket:
        logger.error(f"DrumGen _resolve_style: CRITICAL - Bucket '{bucket}' is not defined. Using 'default_drum_pattern'.")
        return "default_drum_pattern"
    resolved_style = style_map_for_bucket.get(intensity.lower())
    if not resolved_style:
        resolved_style = style_map_for_bucket.get("default", "default_drum_pattern")
    if resolved_style not in pattern_lib:
        logger.warning(f"DrumGen _resolve_style: Resolved style '{resolved_style}' not in pattern_lib. Falling back to 'default_drum_pattern'.")
        # フォールバック先も存在するか確認 (念のため)
        if "default_drum_pattern" not in pattern_lib:
            logger.error(f"DrumGen _resolve_style: CRITICAL - Fallback 'default_drum_pattern' also not in pattern_lib. This should not happen.")
            # ここでさらに安全なフォールバックを考えるか、エラーを出すか
            # 例えば、空のパターンを返すなど
            return "no_drums" # より安全なフォールバック
        return "default_drum_pattern"
    return resolved_style

class DrumGenerator:
    def __init__(self, lib: Optional[Dict[str,Dict[str,Any]]] = None,
                 tempo_bpm:int = 120, time_sig:str="4/4"):
        self.raw_pattern_lib = copy.deepcopy(lib) if lib is not None else {}
        self.pattern_lib_cache: Dict[str, Dict[str, Any]] = {}
        self.rng = random.Random()
        logger.info(f"DrumGen __init__: Received raw_pattern_lib with {len(self.raw_pattern_lib)} keys.")

        core_defaults = {
            "default_drum_pattern":{"description": "Default fallback pattern", "pattern":[], "time_signature":"4/4", "swing": 0.5, "length_beats": 4.0, "fill_ins": {}},
            "no_drums":{"description": "Silence", "pattern":[],"time_signature":"4/4", "swing": 0.5, "length_beats": 4.0, "fill_ins": {}}
        }
        for k, v_def in core_defaults.items():
            if k not in self.raw_pattern_lib:
                self.raw_pattern_lib[k] = v_def
                logger.info(f"DrumGen __init__: Added core default '{k}' to raw pattern library.")

        all_referenced_styles_in_luts = set()
        for bucket_styles in BUCKET_INTENSITY_TO_STYLE.values():
            for style_key_in_lut in bucket_styles.values():
                all_referenced_styles_in_luts.add(style_key_in_lut)
        chordmap_common_styles = ["no_drums_or_sparse_cymbal", "no_drums_or_gentle_cymbal_swell", "no_drums_or_sparse_chimes", "ballad_soft_kick_snare_8th_hat", "rock_ballad_build_up_8th_hat", "anthem_rock_chorus_16th_hat"]
        all_referenced_styles_in_luts.update(chordmap_common_styles)

        for style_key in all_referenced_styles_in_luts:
            if style_key not in self.raw_pattern_lib:
                self.raw_pattern_lib[style_key] = {
                    "description": f"Placeholder for '{style_key}' (auto-added).",
                    "time_signature": "4/4", "swing": 0.5, "length_beats": 4.0,
                    "pattern": [], "fill_ins": {}
                }
                logger.info(f"DrumGen __init__: Added silent placeholder for undefined style '{style_key}' to raw_pattern_lib.")

        self.global_tempo = tempo_bpm
        self.global_time_signature_str = time_sig
        self.global_ts = get_time_signature_object(time_sig)
        if not self.global_ts:
            logger.warning(f"DrumGen __init__: Failed to parse time_sig '{time_sig}'. Defaulting to 4/4.")
            self.global_ts = meter.TimeSignature("4/4")
        self.instrument = m21instrument.Percussion()
        if hasattr(self.instrument, "midiChannel"):
            self.instrument.midiChannel = 9

    def _get_effective_pattern_def(self, style_key: str, visited: Optional[Set[str]] = None) -> Dict[str, Any]:
        if visited is None: visited = set()
        if style_key in visited:
            logger.error(f"DrumGen: Circular inheritance detected involving '{style_key}'. Returning base default.")
            return copy.deepcopy(self.raw_pattern_lib.get("default_drum_pattern", {}))
        visited.add(style_key)

        if style_key in self.pattern_lib_cache:
            return copy.deepcopy(self.pattern_lib_cache[style_key])

        pattern_def_original = self.raw_pattern_lib.get(style_key)
        if not pattern_def_original:
            logger.warning(f"DrumGen: Style key '{style_key}' not found in raw_pattern_lib. Returning default.")
            # default_drum_pattern が存在しない極端なケースも考慮
            default_pattern = self.raw_pattern_lib.get("default_drum_pattern")
            if not default_pattern:
                logger.error("DrumGen: CRITICAL - 'default_drum_pattern' is also missing. Returning minimal empty pattern.")
                return {"description": "Minimal Empty Pattern", "pattern":[], "time_signature":"4/4", "swing": 0.5, "length_beats": 4.0, "fill_ins": {}}
            return copy.deepcopy(default_pattern)
        pattern_def = copy.deepcopy(pattern_def_original)


        inherit_key = pattern_def.get("inherit")
        if inherit_key and isinstance(inherit_key, str):
            logger.debug(f"DrumGen: Pattern '{style_key}' inherits from '{inherit_key}'.")
            base_def = self._get_effective_pattern_def(inherit_key, visited)

            merged_def = base_def.copy()
            current_pattern_list = pattern_def.get("pattern")
            if current_pattern_list is not None:
                 merged_def["pattern"] = current_pattern_list

            base_fills = merged_def.get("fill_ins", {})
            current_fills = pattern_def.get("fill_ins", {})
            if isinstance(base_fills, dict) and isinstance(current_fills, dict):
                merged_fills = base_fills.copy()
                merged_fills.update(current_fills)
                merged_def["fill_ins"] = merged_fills
            elif current_fills is not None:
                 merged_def["fill_ins"] = current_fills

            for key, value in pattern_def.items():
                if key not in ["inherit", "pattern", "fill_ins"]:
                    merged_def[key] = value
            pattern_def = merged_def

        self.pattern_lib_cache[style_key] = copy.deepcopy(pattern_def)
        if style_key in visited: visited.remove(style_key) # 正常終了時にも削除
        return pattern_def

    # ▼▼▼ compose メソッドのシグネチャを修正 ▼▼▼
    def compose(self, blocks: List[Dict[str,Any]], overrides: Optional[Any] = None) -> stream.Part:
    # ▲▲▲ overrides の型を Optional[Any] に (Overridesモデルを受け取るため) ▲▲▲
        part = stream.Part(id="Drums")
        part.insert(0, self.instrument)
        part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        if self.global_ts and hasattr(self.global_ts, 'ratioString'):
            ts_to_insert = meter.TimeSignature(self.global_ts.ratioString)
        else:
            logger.warning("DrumGen compose: self.global_ts is invalid. Defaulting to 4/4.")
            ts_to_insert = meter.TimeSignature("4/4")
        part.insert(0, ts_to_insert)

        if not blocks: return part
        logger.info(f"DrumGen compose: Starting for {len(blocks)} blocks.")

        # ブロックごとのパラメータ解決を先に行う
        resolved_blocks = []
        for blk_idx, blk_data_original in enumerate(blocks):
            blk = copy.deepcopy(blk_data_original) # 元のデータを変更しないようにコピー
            current_section_name = blk.get("section_name", f"UnnamedSection_{blk_idx}")

            # get_part_override を呼び出し
            part_specific_overrides_model = get_part_override(
                overrides if overrides else {},
                current_section_name,
                "drums"
            )

            # chordmap からのパラメータと override からのパラメータをマージ
            # blk["part_params"]["drums"] が存在することを保証
            blk.setdefault("part_params", {}).setdefault("drums", {})
            drum_params_from_chordmap = blk["part_params"]["drums"]
            
            final_drum_params = drum_params_from_chordmap.copy()
            if part_specific_overrides_model:
                override_dict = part_specific_overrides_model.model_dump(exclude_unset=True)
                # ネストされた 'options' や他の特定のキーを適切にマージする必要があればここで行う
                # 例: final_drum_params.get("options", {}).update(override_dict.pop("options", {}))
                final_drum_params.update(override_dict)
            
            blk["part_params"]["drums"] = final_drum_params # マージ結果を格納

            emo = blk.get("musical_intent",{}).get("emotion","default").lower()
            inten = blk.get("musical_intent",{}).get("intensity","medium").lower()
            
            # スタイルキーの解決 (override -> chordmap -> emotion/intensity)
            # 1. Override からの rhythm_key
            style_key_from_override = final_drum_params.get("rhythm_key") # PartOverride に rhythm_key があれば
            if style_key_from_override and style_key_from_override in self.raw_pattern_lib:
                final_style_key = style_key_from_override
                logger.debug(f"DrumGen compose: Blk {blk_idx+1} using style '{final_style_key}' from arrangement_overrides.")
            else:
                # 2. Chordmap からの drum_style_key
                explicit_style_key_chordmap = final_drum_params.get("drum_style_key", final_drum_params.get("style_key"))
                if explicit_style_key_chordmap and explicit_style_key_chordmap in self.raw_pattern_lib:
                    final_style_key = explicit_style_key_chordmap
                    logger.debug(f"DrumGen compose: Blk {blk_idx+1} using explicit style '{final_style_key}' from chordmap.")
                else:
                    # 3. Emotion/Intensity からの解決
                    final_style_key = _resolve_style(emo, inten, self.raw_pattern_lib)
                    logger.debug(f"DrumGen compose: Blk {blk_idx+1} (E:'{emo}',I:'{inten}') using auto-resolved style '{final_style_key}'")

            blk["part_params"]["drums"]["final_style_key_for_render"] = final_style_key # 実際に使用するスタイルキーを格納
            resolved_blocks.append(blk)

        self._render(resolved_blocks, part) # 解決済みブロックリストを渡す
        logger.info(f"DrumGen compose: Finished. Part has {len(list(part.flatten().notesAndRests))} elements.")
        return part

    def _render(self, blocks:Sequence[Dict[str,Any]], part:stream.Part):
        ms_since_fill = 0
        for blk_idx, blk_data in enumerate(blocks):
            # drums_params には既に override がマージされているはず
            drums_params = blk_data.get("part_params", {}).get("drums", {})
            # final_style_key_for_render を使用
            style_key = drums_params.get("final_style_key_for_render", "default_drum_pattern")

            style_def = self._get_effective_pattern_def(style_key)
            if not style_def:
                logger.error(f"DrumGen _render: CRITICAL - _get_effective_pattern_def returned None for '{style_key}'. Skipping block.")
                continue

            pat_events: List[Dict[str,Any]] = style_def.get("pattern", [])
            pat_ts_str = style_def.get("time_signature", self.global_time_signature_str)
            pat_ts = get_time_signature_object(pat_ts_str)
            if not pat_ts: pat_ts = self.global_ts

            pattern_unit_length_ql = float(style_def.get("length_beats", pat_ts.barDuration.quarterLength if pat_ts else 4.0))
            if pattern_unit_length_ql <=0:
                 logger.warning(f"DrumGen _render: Pattern '{style_key}' has invalid length_beats/barDuration {pattern_unit_length_ql}. Defaulting to 4.0")
                 pattern_unit_length_ql = 4.0

            swing_setting = style_def.get("swing", 0.5)
            swing_type = "eighth"; swing_ratio_val = 0.5
            if isinstance(swing_setting, dict):
                swing_type = swing_setting.get("type", "eighth").lower()
                swing_ratio_val = float(swing_setting.get("ratio", 0.5))
            elif isinstance(swing_setting, (float, int)):
                swing_ratio_val = float(swing_setting)

            fills = style_def.get("fill_ins", {})
            # base_vel は drums_params から取得 (override 適用済みのはず)
            base_vel = int(drums_params.get("drum_base_velocity", drums_params.get("velocity", 80))) # "velocity" もフォールバックとして考慮
            intensity_str = blk_data.get("musical_intent", {}).get("intensity", "medium").lower()
            # 強度によるベロシティ調整は translate_keywords_to_params で行われている想定だが、念のためここでも考慮
            # ただし、overrideで直接velocityが指定されていればそちらを優先すべき
            if "velocity" not in drums_params and "drum_base_velocity" not in drums_params: # 明示的な指定がない場合のみ強度調整
                if intensity_str in ["high", "medium_high"]: base_vel = min(127, base_vel + 8)
                elif intensity_str in ["low", "medium_low"]: base_vel = max(20, base_vel - 6)


            offset_in_score = blk_data.get("offset", 0.0)
            remaining_ql_in_block = blk_data.get("q_length", pattern_unit_length_ql)

            if blk_data.get("is_first_in_section", False) and blk_idx > 0 :
                ms_since_fill = 0

            current_pos_within_block = 0.0
            while remaining_ql_in_block > MIN_NOTE_DURATION_QL / 8.0:
                current_pattern_iteration_ql = min(pattern_unit_length_ql, remaining_ql_in_block)
                if current_pattern_iteration_ql < MIN_NOTE_DURATION_QL / 4.0 : break

                is_last_pattern_iteration_in_block = (remaining_ql_in_block <= pattern_unit_length_ql + (MIN_NOTE_DURATION_QL / 8.0))

                pattern_to_use = pat_events
                fill_applied_this_iter = False

                # fill_override は drums_params から取得 (override 適用済みのはず)
                override_fill_key = drums_params.get("fill_override", drums_params.get("drum_fill_key_override"))
                if is_last_pattern_iteration_in_block and override_fill_key:
                    chosen_fill_pattern = fills.get(override_fill_key)
                    if chosen_fill_pattern is not None:
                        pattern_to_use = chosen_fill_pattern
                        fill_applied_this_iter = True
                        logger.debug(f"DrumGen _render: Applied override fill '{override_fill_key}' for style '{style_key}'")
                    else: logger.warning(f"DrumGen _render: Override fill key '{override_fill_key}' not in fills for '{style_key}'.")

                # fill_interval_bars, fill_keys も drums_params から取得
                fill_interval = drums_params.get("drum_fill_interval_bars", 0) # "fill_interval_bars" が正しいキー
                if not fill_applied_this_iter and is_last_pattern_iteration_in_block and fill_interval > 0:
                    num_pattern_units_for_interval = fill_interval
                    if (ms_since_fill + 1) >= num_pattern_units_for_interval :
                        fill_keys_list = drums_params.get("drum_fill_keys", []) # "fill_keys" が正しいキー
                        possible_fills = [fk for fk in fill_keys_list if fk in fills]
                        if possible_fills:
                            chosen_fill_key = self.rng.choice(possible_fills)
                            chosen_fill_pattern = fills.get(chosen_fill_key)
                            if chosen_fill_pattern is not None:
                                pattern_to_use = chosen_fill_pattern
                                fill_applied_this_iter = True
                                logger.debug(f"DrumGen _render: Applied scheduled fill '{chosen_fill_key}' for style '{style_key}'")

                self._apply_pattern(part, pattern_to_use, offset_in_score + current_pos_within_block,
                                    current_pattern_iteration_ql, base_vel,
                                    swing_type, swing_ratio_val, pat_ts if pat_ts else self.global_ts,
                                    drums_params) # ★★★ drums_params を渡してヒューマナイズ設定を取得できるようにする ★★★

                if fill_applied_this_iter: ms_since_fill = 0
                else: ms_since_fill += 1

                current_pos_within_block += current_pattern_iteration_ql
                remaining_ql_in_block -= current_pattern_iteration_ql

    # ▼▼▼ _apply_pattern のシグネチャを修正 ▼▼▼
    def _apply_pattern(self, part:stream.Part, events:List[Dict[str,Any]],
                       bar_start_abs:float, current_bar_len_ql:float, base_vel:int,
                       swing_type:str, swing_ratio:float, pattern_ts:meter.TimeSignature,
                       drum_block_params: Dict[str, Any]): # ★★★ drum_block_params を追加 ★★★
    # ▲▲▲ _apply_pattern のシグネチャを修正 ▲▲▲
        beat_len_ql = pattern_ts.beatDuration.quarterLength if pattern_ts else 1.0

        for ev_def in events:
            if self.rng.random() > ev_def.get("probability", 1.0): continue
            inst_name = ev_def.get("instrument")
            if not inst_name: continue
            rel_offset_in_pattern = float(ev_def.get("offset", 0.0))

            if swing_ratio != 0.5:
                rel_offset_in_pattern = self._swing(rel_offset_in_pattern, swing_ratio, beat_len_ql, swing_type)

            if rel_offset_in_pattern >= current_bar_len_ql - (MIN_NOTE_DURATION_QL / 16.0): continue

            hit_duration_ql = float(ev_def.get("duration", 0.125))
            clipped_duration_ql = min(hit_duration_ql, current_bar_len_ql - rel_offset_in_pattern)
            if clipped_duration_ql < MIN_NOTE_DURATION_QL / 8.0: continue

            vel_val = ev_def.get("velocity")
            vel_factor = ev_def.get("velocity_factor", 1.0)
            final_vel: int
            if vel_val is not None: final_vel = int(vel_val)
            else: final_vel = int(base_vel * float(vel_factor))
            final_vel = max(1, min(127, final_vel))

            drum_hit = self._make_hit(inst_name, final_vel, clipped_duration_ql)
            if not drum_hit: continue

            # ▼▼▼ ヒューマナイズ処理を drum_block_params から取得 ▼▼▼
            humanize_this_hit = False
            humanize_template_for_hit = "drum_tight" # デフォルト
            humanize_custom_for_hit = {}

            # イベント固有のヒューマナイズ設定 > ブロック全体のヒューマナイズ設定
            event_humanize_setting = ev_def.get("humanize")
            if isinstance(event_humanize_setting, bool):
                humanize_this_hit = event_humanize_setting
            elif isinstance(event_humanize_setting, str): # テンプレート名指定
                humanize_this_hit = True
                humanize_template_for_hit = event_humanize_setting
            elif isinstance(event_humanize_setting, dict): # カスタムパラメータ指定
                humanize_this_hit = True
                humanize_template_for_hit = event_humanize_setting.get("template_name", humanize_template_for_hit)
                humanize_custom_for_hit = event_humanize_setting.get("custom_params", {})
            else: # イベントに指定がなければブロック設定を見る
                if drum_block_params.get("humanize_opt", False): # humanize_opt は translate_keywords_to_params で解決済み
                    humanize_this_hit = True
                    humanize_template_for_hit = drum_block_params.get("template_name", "drum_tight")
                    humanize_custom_for_hit = drum_block_params.get("custom_params", {})
            # ▲▲▲ ヒューマナイズ処理を drum_block_params から取得 ▲▲▲

            time_delta_from_humanizer = 0.0
            if humanize_this_hit:
                original_hit_offset_before_humanize = drum_hit.offset # Should be 0.0
                drum_hit = apply_humanization_to_element(drum_hit, template_name=humanize_template_for_hit, custom_params=humanize_custom_for_hit)
                time_delta_from_humanizer = drum_hit.offset - original_hit_offset_before_humanize

            final_insert_offset = bar_start_abs + rel_offset_in_pattern + time_delta_from_humanizer
            drum_hit.offset = 0.0 # music21のinsertは要素のoffsetを無視するので、ここで0にしておくのが無難
            part.insert(final_insert_offset, drum_hit)


    def _swing(self, rel_offset:float, swing_ratio:float, beat_len_ql:float, swing_type:str = "eighth")->float:
        if abs(swing_ratio - 0.5) < 1e-3 or beat_len_ql <= 0:
            return rel_offset

        subdivision_duration_ql: float
        if swing_type == "eighth":
            subdivision_duration_ql = beat_len_ql / 2.0
        elif swing_type == "sixteenth":
            subdivision_duration_ql = beat_len_ql / 4.0
        else:
            logger.warning(f"DrumGen _swing: Unsupported swing_type '{swing_type}'. No swing applied.")
            return rel_offset
        if subdivision_duration_ql <= 0: return rel_offset # ゼロ除算防止

        effective_beat_for_swing_pair_ql = subdivision_duration_ql * 2.0

        beat_num_in_bar = math.floor(rel_offset / effective_beat_for_swing_pair_ql)
        offset_within_effective_beat = rel_offset - (beat_num_in_bar * effective_beat_for_swing_pair_ql)

        epsilon = subdivision_duration_ql * 0.1 # 許容誤差

        # 2番目のサブディビジョン（遅延される方）かどうかを判定
        # 例: 8分音符スウィングで、4分音符の真ん中（0.5拍目）に近いか
        if abs(offset_within_effective_beat - subdivision_duration_ql) < epsilon:
            new_offset_within_effective_beat = effective_beat_for_swing_pair_ql * swing_ratio
            swung_rel_offset = (beat_num_in_bar * effective_beat_for_swing_pair_ql) + new_offset_within_effective_beat
            return swung_rel_offset
        return rel_offset

    def _make_hit(self, name:str, vel:int, ql:float)->Optional[note.Note]:
        mapped_name = name.lower().replace(" ","_").replace("-","_")
        actual_name_for_midi = GHOST_ALIAS.get(mapped_name, mapped_name)
        midi = GM_DRUM_MAP.get(actual_name_for_midi)
        if midi is None:
            logger.warning(f"DrumGen _make_hit: Unknown drum sound '{name}' (mapped to '{actual_name_for_midi}'). MIDI mapping not found.")
            return None
        n = note.Note()
        n.pitch = pitch.Pitch(midi=midi)
        n.duration = m21dur.Duration(quarterLength=max(MIN_NOTE_DURATION_QL / 8.0, ql))
        n.volume = m21volume.Volume(velocity=max(1,min(127,vel)))
        n.offset = 0.0 # music21のinsertは要素のoffsetを無視するので、ここで0にしておく
        return n

# --- END OF FILE ---