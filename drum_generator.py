# --- START OF FILE generator/drum_generator.py (Harugoro-OTO KOTOBA Engine vX.X - fills & swing edition + fixes) ---
from __future__ import annotations

import logging, random, math
from typing import Any, Dict, List, Optional, Sequence # Sequence を追加 (o3-san feedback)

from music21 import (
    stream, note, pitch, volume as m21volume, duration as m21dur, tempo,
    meter, instrument as m21instrument,
)

try: # ユーティリティのインポート
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object
    from utilities.humanizer import apply_humanization_to_element
except ImportError: # フォールバック
    logger_fallback_utils_dg = logging.getLogger(__name__ + ".fallback_utils_dg")
    logger_fallback_utils_dg.warning("DrumGen: Could not import from utilities. Using fallbacks for core utils.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except Exception: return meter.TimeSignature("4/4")
    def apply_humanization_to_element(element, template_name=None, custom_params=None): # custom_params追加
        return element # Fallback does nothing

logger = logging.getLogger(__name__)

# GM Drum Map (v2025‑05‑27 brush‑up 版から採用)
GM_DRUM_MAP: Dict[str, int] = {
    "kick": 36, "bd": 36,
    "snare": 38, "sd": 38,
    "chh": 42, "closed_hi_hat": 42, "closed_hat": 42,
    "phh": 44, "pedal_hi_hat": 44,
    "ohh": 46, "open_hi_hat": 46, "open_hat": 46,
    "crash": 49, "crash_cymbal_1": 49, "crash_cymbal_2": 57, # crash_cymbal_2 を追加
    "ride": 51, "ride_cymbal_1": 51, "ride_cymbal_2": 59, # ride_cymbal_2 を追加
    "ride_bell": 53,
    "claps": 39, "hand_clap": 39,
    "rim": 37, "rim_shot": 37, "side_stick": 37,
    "low_floor_tom": 41, "tom_floor_low": 41,
    "high_floor_tom": 43, "tom_floor_high": 43,
    "low_tom": 45, "tom_low": 45,
    "low_mid_tom": 47, "tom_mid_low": 47, "tom_mid": 47, # tom_mid を追加
    "high_mid_tom": 48, "tom_mid_high": 48, "tom1": 48, # tom1 をこちらに
    "high_tom": 50, "tom_hi": 50, # tom2, tom3 は別途マッピングするか、ここで定義
    "tom2": 47, # General MIDI Tom 2 (LowMidTom) - しばしばtom_midと一致
    "tom3": 45, # General MIDI Tom 3 (LowTom) - しばしばtom_lowと一致
    "hat": 42,
    "stick": 31,
    "tambourine": 54, "splash": 55, "splash_cymbal": 55, "cowbell": 56,
    "china": 52, "china_cymbal": 52, "shaker": 82, "cabasa": 69, "triangle": 81,
    "wood_block_high": 76, "high_wood_block": 76, "wood_block_low": 77, "low_wood_block": 77,
    "guiro_short": 73, "short_guiro": 73, "guiro_long": 74, "long_guiro": 74,
    "claves": 75, "bongo_high": 60, "high_bongo": 60, "bongo_low": 61, "low_bongo": 61,
    "conga_open": 62, "mute_high_conga": 62, "conga_slap": 63, "open_high_conga": 63,
    "timbale_high": 65, "high_timbale": 65, "timbale_low": 66, "low_timbale": 66,
    "agogo_high": 67, "high_agogo": 67, "agogo_low": 68, "low_agogo": 68,
    "ghost_snare": 38, # ghost_snare も snare と同じMIDI値だが、ベロシティで区別
}
GHOST_ALIAS: Dict[str, str] = {"ghost_snare": "snare", "gs": "snare"} # これは _apply_patternで活用

# --- Look-up tables (ご提供の "fills & swing edition" のものをそのまま使用) ---
EMOTION_TO_BUCKET: Dict[str, str] = {
    "quiet_pain_and_nascent_strength": "ballad_soft", "self_reproach_regret_deep_sadness": "ballad_soft",
    "memory_unresolved_feelings_silence": "ballad_soft", "reflective_transition_instrumental_passage": "ballad_soft",
    "deep_regret_gratitude_and_realization": "groove_mid", "supported_light_longing_for_rebirth": "groove_mid",
    "wavering_heart_gratitude_chosen_strength": "groove_mid", "hope_dawn_light_gentle_guidance": "groove_mid",
    "nature_memory_floating_sensation_forgiveness": "groove_mid",
    "acceptance_of_love_and_pain_hopeful_belief": "anthem_high", "trial_cry_prayer_unbreakable_heart": "anthem_high",
    "reaffirmed_strength_of_love_positive_determination": "anthem_high",
    "future_cooperation_our_path_final_resolve_and_liberation": "anthem_high",
    "default": "groove_mid", "neutral": "groove_mid" # neutral を追加
}

BUCKET_INTENSITY_TO_STYLE: Dict[str, Dict[str, str]] = {
    "ballad_soft": {
        "low": "no_drums_or_gentle_cymbal_swell", "medium_low": "ballad_soft_kick_snare_8th_hat",
        "medium": "ballad_soft_kick_snare_8th_hat", "medium_high": "rock_ballad_build_up_8th_hat",
        "high": "rock_ballad_build_up_8th_hat", "default": "ballad_soft_kick_snare_8th_hat"
    },
    "groove_mid": {
        "low": "ballad_soft_kick_snare_8th_hat", "medium_low": "rock_ballad_build_up_8th_hat",
        "medium": "rock_ballad_build_up_8th_hat", "medium_high": "anthem_rock_chorus_16th_hat",
        "high": "anthem_rock_chorus_16th_hat", "default": "rock_ballad_build_up_8th_hat"
    },
    "anthem_high": {
        "low": "rock_ballad_build_up_8th_hat", "medium_low": "anthem_rock_chorus_16th_hat",
        "medium": "anthem_rock_chorus_16th_hat", "medium_high": "anthem_rock_chorus_16th_hat",
        "high": "anthem_rock_chorus_16th_hat", "default": "anthem_rock_chorus_16th_hat"
    },
    "default_fallback_bucket": {
        "low": "no_drums", "medium_low": "default_drum_pattern", "medium": "default_drum_pattern",
        "medium_high": "default_drum_pattern", "high": "default_drum_pattern", "default": "default_drum_pattern"
    }
}
# --- End of Look-up Tables ---

def _resolve_style(emotion:str, intensity:str, pattern_lib: Dict[str, Any]) -> str: # pattern_lib を引数に追加
    bucket = EMOTION_TO_BUCKET.get(emotion.lower(), "default_fallback_bucket")
    style_map_for_bucket = BUCKET_INTENSITY_TO_STYLE.get(bucket)
    if not style_map_for_bucket: # Should not happen
        logger.error(f"DrumGen _resolve_style: CRITICAL - Bucket '{bucket}' is not defined. Using 'default_drum_pattern'.")
        return "default_drum_pattern"

    resolved_style = style_map_for_bucket.get(intensity.lower())
    if not resolved_style:
        resolved_style = style_map_for_bucket.get("default", "default_drum_pattern")
    
    # 解決されたスタイルが実際にライブラリに存在するか確認
    if resolved_style not in pattern_lib:
        logger.warning(f"DrumGen _resolve_style: Resolved style '{resolved_style}' (for E:'{emotion}', I:'{intensity}') "
                       f"not in provided pattern_lib. Falling back to 'default_drum_pattern'.")
        return "default_drum_pattern"
    return resolved_style


class DrumGenerator:
    def __init__(self, lib: Optional[Dict[str,Dict[str,Any]]] = None,
                 tempo_bpm:int = 120, time_sig:str="4/4"):
        self.pattern_lib = lib if lib is not None else {} # lib が None の場合も考慮
        self.rng = random.Random()
        logger.info(f"DrumGen __init__: Received pattern_lib with {len(self.pattern_lib)} keys.")

        # --- Fallback/Placeholder Pattern Logic (o3-san feedback 반영판 より再統合・強化) ---
        core_defaults = { # 必須のフォールバック
            "default_drum_pattern":{"pattern":[{"instrument": "kick", "offset": 0.0}, {"instrument": "snare", "offset": 1.0}, {"instrument": "kick", "offset": 2.0}, {"instrument": "snare", "offset": 3.0}],"time_signature":"4/4", "swing": 0.5, "fill_ins": {}},
            "no_drums":{"pattern":[],"time_signature":"4/4", "swing": 0.5, "fill_ins": {}}
        }
        for k, v_def in core_defaults.items():
            self.pattern_lib.setdefault(k, v_def)
            if k not in (lib or {}): # libがNoneの場合も考慮
                 logger.info(f"DrumGen __init__: Added core default '{k}' to pattern library.")
        
        all_referenced_styles_in_luts = set()
        for bucket_styles in BUCKET_INTENSITY_TO_STYLE.values():
            for style_key_in_lut in bucket_styles.values():
                all_referenced_styles_in_luts.add(style_key_in_lut)
        
        # chordmapでよく使われるがLUTにないかもしれないスタイルキー
        chordmap_common_styles = ["no_drums_or_sparse_cymbal", "no_drums_or_gentle_cymbal_swell", "no_drums_or_sparse_chimes", "ballad_soft_kick_snare_8th_hat", "rock_ballad_build_up_8th_hat", "anthem_rock_chorus_16th_hat"]
        all_referenced_styles_in_luts.update(chordmap_common_styles)

        for style_key in all_referenced_styles_in_luts:
            if style_key not in self.pattern_lib:
                self.pattern_lib[style_key] = {
                    "description": f"Placeholder for '{style_key}' (auto-added). Define in rhythm_library.json for actual sound.",
                    "time_signature": "4/4", "swing": 0.5, # デフォルトのswing値
                    "pattern": [], "fill_ins": {} # fill_ins も空で定義しておく
                }
                logger.info(f"DrumGen __init__: Added silent placeholder for undefined style '{style_key}'.")
        # --- End of Fallback/Placeholder Pattern Logic ---

        self.global_tempo = tempo_bpm # 引数名に合わせて変更
        self.global_time_signature_str = time_sig # 引数名に合わせて変更
        self.global_ts = get_time_signature_object(time_sig) # クラス属性名を self.global_ts に統一
        if not self.global_ts:
            logger.warning(f"DrumGen __init__: Failed to parse time signature '{time_sig}'. Defaulting to 4/4.")
            self.global_ts = meter.TimeSignature("4/4")
        
        # default_instrument は __init__ の引数から削除されたため、ここで固定的に設定
        self.instrument = m21instrument.Percussion()
        if hasattr(self.instrument, "midiChannel"):
            self.instrument.midiChannel = 9


    def compose(self, blocks: List[Dict[str,Any]]) -> stream.Part:
        part = stream.Part(id="Drums")
        part.insert(0, self.instrument) # __init__ で設定した self.instrument を使用
        part.insert(0, tempo.MetronomeMark(number=self.global_tempo)) # self.global_tempo を使用

        # TimeSignature のクローン問題を修正
        if self.global_ts and hasattr(self.global_ts, 'ratioString'):
            ts_to_insert = meter.TimeSignature(self.global_ts.ratioString)
        else:
            logger.warning("DrumGen compose: self.global_ts is invalid. Defaulting to 4/4 for the part.")
            ts_to_insert = meter.TimeSignature("4/4")
        part.insert(0, ts_to_insert)

        if not blocks:
            logger.warning("DrumGen compose: Received empty blocks list. Returning empty drum part.")
            return part
        
        logger.info(f"DrumGen compose: Starting for {len(blocks)} blocks.")

        for blk_idx, blk in enumerate(blocks):
            emo = blk.get("musical_intent",{}).get("emotion","default").lower()
            inten = blk.get("musical_intent",{}).get("intensity","medium").lower()
            # _resolve_style に self.pattern_lib を渡す
            style = _resolve_style(emo, inten, self.pattern_lib)
            
            # part_params と drums サブ辞書が存在することを保証
            blk.setdefault("part_params",{}).setdefault("drums",{})
            # style_key を格納 (drum_style_key から style_key に名称変更したことを反映)
            blk["part_params"]["drums"]["style_key"] = style
            logger.debug(f"DrumGen compose: Blk {blk_idx+1} set to style '{style}' for E:'{emo}', I:'{inten}'")


        self._render(blocks, part)
        logger.info(f"DrumGen compose: Finished. Part has {len(list(part.flatten().notesAndRests))} elements.")
        return part

    # _render, _apply_pattern, _swing, _make_hit メソッドはご提供の
    # "dynamic-pattern + fills & swing edition" のものを基本的に使用。
    # ただし、GM_DRUM_MAP の参照先や humanizer の呼び出し方を微調整。

    def _render(self, blocks:Sequence[Dict[str,Any]], part:stream.Part):
        ms_since_fill = 0
        for blk_idx, blk_data in enumerate(blocks): # blk_data の方が他のジェネレータと一貫性がある
            drums_params = blk_data.get("part_params", {}).get("drums", {}) # blk_data から取得
            style_key = drums_params.get("style_key", "default_drum_pattern") # composeで設定されたキー
            style_def = self.pattern_lib.get(style_key)
            if not style_def: # style_keyがpattern_libにない場合の最終フォールバック
                logger.error(f"DrumGen _render: CRITICAL - Style key '{style_key}' not found in pattern_lib even after __init__ checks. Using absolute default.")
                style_def = self.pattern_lib.get("default_drum_pattern") # これは __init__ で保証されているはず

            pat_events: List[Dict[str,Any]] = style_def.get("pattern", []) # patternがない場合も考慮
            pat_ts_str = style_def.get("time_signature", self.global_time_signature_str)
            pat_ts = get_time_signature_object(pat_ts_str)
            if not pat_ts: pat_ts = self.global_ts # pat_tsが取れなければグローバルTS

            bar_len = pat_ts.barDuration.quarterLength if pat_ts else 4.0
            swing = style_def.get("swing", 0.5)
            fills = style_def.get("fill_ins", {})

            base_vel = int(drums_params.get("drum_base_velocity", 80))
            # グルーブ強度係数 (o3-san)
            intensity_str = blk_data.get("musical_intent", {}).get("intensity", "medium").lower()
            if intensity_str in ["high", "medium_high"]: base_vel = min(127, base_vel + 8)
            elif intensity_str in ["low", "medium_low"]: base_vel = max(20, base_vel - 6)

            offset = blk_data.get("offset", 0.0)
            remain = blk_data.get("q_length", bar_len)

            # リセットタイミングの調整 is_first_in_section
            if blk_data.get("is_first_in_section", False) and blk_idx > 0 : # 最初のブロック以外でセクションが変わったら
                ms_since_fill = 0
                logger.debug(f"DrumGen _render: Resetting measures_since_last_fill for new section: {blk_data.get('section_name', 'Unknown Section')}")


            while remain > MIN_NOTE_DURATION_QL / 8.0: # 小さすぎる残り時間は処理しない
                current_iter_dur = min(bar_len, remain)
                if current_iter_dur < MIN_NOTE_DURATION_QL / 4.0 : break # 処理単位が短すぎる場合も抜ける

                is_last_bar_of_block = (remain <= bar_len + (MIN_NOTE_DURATION_QL / 8.0)) # ブロック内の実質最後のバーか

                pattern_to_use = pat_events
                fill_applied_this_iter = False

                # Fill logic
                # a) block-explicit key (fill_override)
                override_fill_key = drums_params.get("fill_override") # 旧: drums.get("fill_override")
                if is_last_bar_of_block and override_fill_key:
                    chosen_fill_pattern = fills.get(override_fill_key)
                    if chosen_fill_pattern is not None: # パターンがNoneでないことを確認
                        pattern_to_use = chosen_fill_pattern
                        fill_applied_this_iter = True
                        logger.debug(f"DrumGen _render: Applied override fill '{override_fill_key}' for style '{style_key}'")
                    else:
                        logger.warning(f"DrumGen _render: Override fill key '{override_fill_key}' not found in fills for style '{style_key}'. Using main pattern.")
                
                # b) interval-scheduled fill
                fill_interval = drums_params.get("fill_interval_bars", 0)
                if not fill_applied_this_iter and is_last_bar_of_block and fill_interval > 0:
                    # インターバルは小節単位でカウント
                    if (ms_since_fill + 1) >= fill_interval : # 次がフィルタイミング
                        fill_keys_list = drums_params.get("fill_keys", [])
                        
                        # 現在のスタイルのfillsから、fill_keys_listにあるものを候補とする
                        possible_fills_for_style = [fk for fk in fill_keys_list if fk in fills]
                        if possible_fills_for_style:
                            chosen_fill_key = self.rng.choice(possible_fills_for_style)
                            chosen_fill_pattern = fills.get(chosen_fill_key) # fills から取得
                            if chosen_fill_pattern is not None:
                                pattern_to_use = chosen_fill_pattern
                                fill_applied_this_iter = True
                                logger.debug(f"DrumGen _render: Applied scheduled fill '{chosen_fill_key}' for style '{style_key}' (interval {fill_interval})")
                            # else: chosen_fill_key が fills にない場合は上でフィルタされているはず
                        else:
                            logger.debug(f"DrumGen _render: No suitable scheduled fills for style '{style_key}' from fill_keys list: {fill_keys_list}. Using main pattern.")
                        # ms_since_fill = -1 # _apply_pattern の後でインクリメントされるので実質0になる

                self._apply_pattern(part, pattern_to_use, offset, current_iter_dur, base_vel,
                                    swing, pat_ts if pat_ts else self.global_ts) # pat_tsがNoneの場合のフォールバック

                if fill_applied_this_iter:
                    ms_since_fill = 0 # フィルを適用したらカウンターリセット
                elif current_iter_dur >= bar_len - (MIN_NOTE_DURATION_QL / 8.0) : # ほぼ1小節分処理した場合
                    ms_since_fill += 1
                
                offset += current_iter_dur
                remain -= current_iter_dur

    def _apply_pattern(self, part:stream.Part, events:List[Dict[str,Any]],
                       bar_start_abs:float, current_bar_len_ql:float, base_vel:int, # 引数名変更 bar_start, bar_len -> bar_start_abs, current_bar_len_ql
                       swing_ratio:float, pattern_ts:meter.TimeSignature): # 引数名変更 swing, ts -> swing_ratio, pattern_ts
        
        beat_len_ql = pattern_ts.beatDuration.quarterLength if pattern_ts else 1.0

        for ev_def in events: # ev -> ev_def
            if self.rng.random() > ev_def.get("probability", 1.0):
                continue
            
            inst_name = ev_def.get("instrument")
            if not inst_name:
                logger.warning("DrumGen _apply_pattern: Event missing 'instrument'. Skipping.")
                continue

            rel_offset_in_pattern = float(ev_def.get("offset", 0.0))
            
            # Swing application
            if swing_ratio != 0.5: # self._swing は swing_ratio を期待
                rel_offset_in_pattern = self._swing(rel_offset_in_pattern, swing_ratio, beat_len_ql)
            
            # パターン内のオフセットが現在の処理単位の長さを超える場合はスキップ
            if rel_offset_in_pattern >= current_bar_len_ql - (MIN_NOTE_DURATION_QL / 16.0): # 少しマージン
                continue
            
            hit_duration_ql = float(ev_def.get("duration", 0.125))
            # ヒットの終了が現在の処理単位の長さを超えないようにデュレーションをクリップ
            clipped_duration_ql = min(hit_duration_ql, current_bar_len_ql - rel_offset_in_pattern)
            if clipped_duration_ql < MIN_NOTE_DURATION_QL / 8.0: continue


            vel_val = ev_def.get("velocity")
            vel_factor = ev_def.get("velocity_factor", 1.0) # デフォルト1.0
            final_vel: int
            if vel_val is not None: final_vel = int(vel_val)
            else: final_vel = int(base_vel * float(vel_factor)) # vel_factorはfloatであるべき
            final_vel = max(1, min(127, final_vel))

            drum_hit = self._make_hit(inst_name, final_vel, clipped_duration_ql)
            if not drum_hit: continue

            # Humanization: DSL で ev_def["humanize"] が True/False またはテンプレート名文字列
            humanize_setting = ev_def.get("humanize") # Could be bool or str
            if humanize_setting is not None: # Noneでない場合のみ処理
                if isinstance(humanize_setting, bool) and humanize_setting:
                    # True の場合はデフォルトテンプレート (例: "drum_tight") を使うか、より詳細な設定が必要
                    drum_hit = apply_humanization_to_element(drum_hit, template_name="drum_tight") # フォールバックテンプレート
                elif isinstance(humanize_setting, str): # テンプレート名が指定されている場合
                    drum_hit = apply_humanization_to_element(drum_hit, template_name=humanize_setting)
                # humanize_setting が False の場合は何もしない (apply_humanization_to_element が呼ばれない)

            # `apply_humanization_to_element` はコピーを返し、その offset は「ズレ」を示す
            time_delta_from_humanizer = drum_hit.offset if hasattr(drum_hit, 'offset') else 0.0
            
            final_insert_offset = bar_start_abs + rel_offset_in_pattern + time_delta_from_humanizer
            drum_hit.offset = 0.0 # music21.stream.Stream.insert は要素のオフセットを無視するためリセット
            
            part.insert(final_insert_offset, drum_hit)

    def _swing(self, rel_offset:float, swing_ratio:float, beat_len_ql:float)->float: # rel, ratio, beat -> rel_offset, swing_ratio, beat_len_ql
        if abs(swing_ratio - 0.5) < 1e-3 or beat_len_ql <= 0: # スイングなし、または beat_len が不正
            return rel_offset
        
        eighth_note_dur = beat_len_ql / 2.0
        
        # 何番目のビートか (0-indexed)
        beat_num_in_bar = math.floor(rel_offset / beat_len_ql)
        # ビート内のオフセット
        offset_within_beat = rel_offset - (beat_num_in_bar * beat_len_ql)
        
        # オフビートの8分音符（ビートのちょうど中間）であるかどうかの判定
        # epsilon は比較のための許容誤差
        epsilon = beat_len_ql * 0.02 # 以前は0.01固定だったが、beat_len_qlに比例するように（o3-san指摘）
                                      # ただし、8分音符の判定なので eighth_note_dur の方が適切かも
        epsilon_for_eighth = eighth_note_dur * 0.1 # 8分音符の10%程度の誤差を許容

        if abs(offset_within_beat - eighth_note_dur) < epsilon_for_eighth:  # オフビートの8分音符の場合
            # スウィング後のオフビート8分音符の位置は、ビート長 * スウィング比率
            # 例: beat_len_ql=1.0, swing_ratio=0.66 (2/3) -> オフビートは0.66の位置へ
            # ストレート(0.5)からのずれは (swing_ratio - 0.5) * beat_len_ql
            new_offset_within_beat = beat_len_ql * swing_ratio
            swung_rel_offset = (beat_num_in_bar * beat_len_ql) + new_offset_within_beat
            # logger.debug(f"Swing: rel {rel_offset:.3f} -> {swung_rel_offset:.3f} (ratio {swing_ratio}, beat_len {beat_len_ql})")
            return swung_rel_offset
        return rel_offset

    def _make_hit(self, name:str, vel:int, ql:float)->Optional[note.Note]:
        # GHOST_ALIAS を使ってゴーストノートの楽器名を解決
        mapped_name = name.lower().replace(" ","_").replace("-","_")
        actual_name_for_midi = GHOST_ALIAS.get(mapped_name, mapped_name)

        midi = GM_DRUM_MAP.get(actual_name_for_midi) # 修正：GM_DRUM_MAP を使用
        if midi is None:
            logger.warning(f"DrumGen _make_hit: Unknown drum sound '{name}' (mapped to '{actual_name_for_midi}'). MIDI mapping not found. Skipping.")
            return None
        n = note.Note()
        n.pitch = pitch.Pitch(midi=midi)
        # MIN_NOTE_DURATION_QL / 8.0 は非常に短い。ドラムは通常短いのでこれで良い場合もあるが、意図を確認。
        n.duration = m21dur.Duration(quarterLength=max(MIN_NOTE_DURATION_QL / 8.0, ql))
        n.volume = m21volume.Volume(velocity=max(1,min(127,vel)))
        n.offset = 0.0 # ヒューマナイズで変更される前の初期オフセット
        return n

# --- END OF FILE ---
