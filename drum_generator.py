"""generator/drum_generator.py – v2025‑05‑27 brush‑up"""
from __future__ import annotations

import logging
import random
import copy
from typing import Any, Dict, List, Optional

import music21
from music21 import instrument as m21instrument
from music21 import note
from music21 import pitch
from music21 import stream
from music21 import tempo
from music21 import duration
from music21 import meter
from music21 import volume

# --- utilities ------------------------------------------------------------
try:
    from utilities.core_music_utils import get_time_signature_object, MIN_NOTE_DURATION_QL
    # ★ drum ユーティリティ類を utilities.humanizer 内の汎用関数へ移動した…
    # generate_fractional_noise は humanizer からインポートされる想定ですが、
    # ひとまずランダムな値を返すダミー関数を定義しておきます。
    # 実際の utilities.humanizer モジュールに実装がある場合はそちらが使用されます。
    try:
        from utilities.humanizer import generate_fractional_noise
    except ImportError:
        logger_fallback_humanizer = logging.getLogger(__name__ + ".fallback_humanizer")
        logger_fallback_humanizer.warning(
            "DrumGen: Could not import generate_fractional_noise from utilities.humanizer. "
            "Using fallback random.uniform for FBM noise."
        )
        def generate_fractional_noise(count: int, hurst: float, scale_factor: float) -> List[float]:
            return [random.uniform(-scale_factor, scale_factor) for _ in range(count)]

except ImportError:
    logger_fallback_utils = logging.getLogger(__name__ + ".fallback_utils_dg")
    logger_fallback_utils.warning("DrumGen: Could not import from utilities. Using fallbacks for core utils.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try:
            return meter.TimeSignature(ts_str)
        except Exception:
            return meter.TimeSignature("4/4")

logger = logging.getLogger(__name__)

# =========================================================================
# 0. GM マップとメタ定義
# =========================================================================
GM_DRUM_MAP: Dict[str, int] = {
    "kick": 36, "bd": 36,
    "snare": 38, "sd": 38,
    "chh": 42, "closed_hi_hat": 42, "closed_hat": 42,
    "phh": 44, "pedal_hi_hat": 44,
    "ohh": 46, "open_hi_hat": 46, "open_hat": 46,
    "crash": 49, "crash_cymbal_1": 49,
    "ride": 51, "ride_cymbal_1": 51,
    "claps": 39, "hand_clap": 39,
    "rim": 37, "rim_shot": 37,
    "lt": 41, "low_tom": 41, "low_floor_tom": 41,
    "mt": 45, "mid_tom": 45, "low_mid_tom": 45, # music21.instrument.TomTom L/M (45/47)
    "ht": 50, "high_tom": 50,                  # music21.instrument.TomTom H (50)
    "tom1": 48, "high_mid_tom": 48, # General MIDI Tom 1 (HighMidTom)
    "tom2": 47, "tom_mid": 47,      # General MIDI Tom 2 (LowMidTom)
    "tom3": 45, "tom_low": 45,      # General MIDI Tom 3 (LowTom)
    "hat": 42, # Generic hat, defaults to closed
    # 追加の一般的なマッピング
    "stick": 31, "side_stick": 37, # Side Stick is often preferred over Stick clicks
    "tambourine": 54,
    "splash": 55, "splash_cymbal": 55,
    "cowbell": 56,
    "ride_bell": 53,
    "china": 52, "china_cymbal": 52,
    "shaker": 82, # Usually mapped to Shaker in GM2/XG, but sometimes found in Percussion kits
    "cabasa": 69,
    "triangle": 81,
    "wood_block_high": 76, "high_wood_block": 76,
    "wood_block_low": 77, "low_wood_block": 77,
    "guiro_short": 73, "short_guiro": 73,
    "guiro_long": 74, "long_guiro": 74,
    "claves": 75,
    "bongo_high": 60, "high_bongo": 60,
    "bongo_low": 61, "low_bongo": 61,
    "conga_open": 62, "mute_high_conga": 62, # Often Open Hi Conga, or Mute Hi Conga
    "conga_slap": 63, "open_high_conga": 63, # Often Slap Conga, or Open Hi Conga
    "timbale_high": 65, "high_timbale": 65,
    "timbale_low": 66, "low_timbale": 66,
    "agogo_high": 67, "high_agogo": 67,
    "agogo_low": 68, "low_agogo": 68,
}

# Ghost note グループを一元管理
GHOST_ALIAS: Dict[str, str] = {"ghost_snare": "snare", "gs": "snare"}

# =========================================================================
# 1. 人間味付け（共通関数を utilities.humanizer に寄せた実装）
# =========================================================================

def _apply_hit_humanization(
    base_hit: note.Note,
    *,
    timing_jitter: float = 0.012,
    vel_jitter: int = 5,
    use_fbm: bool = False,
) -> note.Note:
    """単一のドラム Note に微乱数を与える。返り値は deepcopy 済み。"""
    hit = copy.deepcopy(base_hit)

    # ------ Timing ------
    current_offset = hit.offset if hasattr(hit, 'offset') else 0.0
    if use_fbm:
        # generate_fractional_noise はリストを返すので、最初の要素を使用
        jitter_value = generate_fractional_noise(1, hurst=0.6, scale_factor=timing_jitter)[0]
    else:
        jitter_value = random.uniform(-timing_jitter, timing_jitter)
    
    # music21 の Note オブジェクトは直接 offset を持たない場合がある (Streamに追加されるときに決定される)
    # ここでは、Stream に挿入する際のオフセット調整値として jitter を扱うことを想定
    # もし Note が既に Stream 内にあるなら、hit.setOffsetBySite(hit.activeSite, current_offset + jitter_value) のような操作が必要
    # 今回は新規作成される Note を想定し、挿入時にこの jitter を考慮する。
    # ただし、提案コードでは hit.offset を直接変更しているので、それに従う。
    hit.offset = max(current_offset + jitter_value, 0.0)


    # ------ Velocity ------
    if hit.volume and hit.volume.velocity is not None:
        hit.volume.velocity = max(1, min(127, hit.volume.velocity + random.randint(-vel_jitter, vel_jitter)))
    elif not hit.volume: # volume オブジェクトがない場合
        # デフォルトのベロシティを仮定してジッターを適用 (例: 64)
        # ただし、この関数が呼ばれる時点でベロシティは設定されているはず
        logger.debug("DrumGen: Note for humanization had no volume object. Velocity jitter not applied effectively.")
        pass


    return hit

# =========================================================================
# 2. DrumGenerator クラス
# =========================================================================
class DrumGenerator:
    """1 ブロック = 1 measure 基準でパターン適用する簡易 Drum arranger"""

    DEFAULT_HUMANIZE: Dict[str, Any] = dict(timing_jitter=0.012, vel_jitter=5, use_fbm=False)

    def __init__(
        self,
        drum_pattern_library: Dict[str, Dict[str, Any]] | None = None,
        *,
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        default_instrument: m21instrument.Instrument = m21instrument.Percussion(),
    ) -> None:
        self.pattern_lib = drum_pattern_library or {}
        self._ensure_core_patterns() # 必須パターンをここで保証
        logger.info(f"DrumGen __init__: Pattern library initialized. Keys: {list(self.pattern_lib.keys())}")

        self.tempo = global_tempo
        self.ts_str = global_time_signature
        self.ts = get_time_signature_object(global_time_signature)
        if not self.ts:
            logger.warning(f"DrumGen __init__: Failed to parse time signature '{global_time_signature}'. Defaulting to 4/4.")
            self.ts = meter.TimeSignature("4/4")

        self.instrument = default_instrument
        if hasattr(self.instrument, "midiChannel"):
            self.instrument.midiChannel = 9  # Drums on ch‑10 (0‑based 9)
        else:
            logger.warning("DrumGen __init__: Default instrument does not have midiChannel attribute.")


    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def compose(self, blocks: List[Dict[str, Any]]) -> stream.Part:
        part = stream.Part(id="Drums")
        part.insert(0, self.instrument)
        part.insert(0, tempo.MetronomeMark(number=self.tempo))
        
        ts_clone = self.ts.clone() if self.ts else meter.TimeSignature("4/4").clone()
        part.insert(0, ts_clone)

        if not blocks:
            logger.warning("DrumGen compose: Received empty blocks list. Returning empty drum part.")
            return part
        
        logger.info(f"DrumGen compose: Starting for {len(blocks)} blocks.")

        # bar_len = self.ts.barDuration.quarterLength # ブロックごとに可変長を許容するためここでは未使用

        for blk_idx, blk in enumerate(blocks):
            block_params = blk.get("part_params", {}).get("drums", {})
            style_key = block_params.get("drum_style_key", "default_drum_pattern")
            base_vel = int(block_params.get("drum_base_velocity", 80))
            
            # humanize 設定はブロックごとに取得、なければクラスデフォルト
            humanize_block = block_params.get("humanize", True) # ブロック単位のON/OFF
            # 詳細なhumanizeパラメータは現時点ではクラスデフォルトのみ使用
            # 将来的にブロックごとに上書きする場合はここにロジック追加
            current_humanize_params = self.DEFAULT_HUMANIZE.copy()
            # 例: block_params から "timing_jitter" など個別パラメータを読み取り current_humanize_params を更新

            pattern_def = self.pattern_lib.get(style_key)
            if not pattern_def or "pattern" not in pattern_def:
                logger.warning(
                    f"DrumGen Blk {blk_idx+1}: Style key '{style_key}' not found or invalid. "
                    f"Using 'default_drum_pattern'."
                )
                pattern_def = self.pattern_lib.get("default_drum_pattern") # _ensure_core_patterns で存在保証

            pattern_events = pattern_def.get("pattern", [])
            abs_block_offset = float(blk.get("offset", 0.0))
            block_q_length = float(blk.get("q_length", self.ts.barDuration.quarterLength if self.ts else 4.0))
            
            # パターン適用 (フィルインロジックは改修案では省略されているため、ここではメインパターンのみ適用)
            # 将来的にフィルインを復活させる場合は、このあたりで条件分岐やパターン選択ロジックが必要
            self._apply_pattern(
                tgt_part=part,
                events=pattern_events,
                abs_offset=abs_block_offset,
                block_len=block_q_length,
                base_vel=base_vel,
                humanize=humanize_block,
                humanize_params=current_humanize_params # 渡す
            )
            logger.debug(f"DrumGen Blk {blk_idx+1}: Applied pattern '{style_key}' at offset {abs_block_offset:.2f} for {block_q_length:.2f} QL. Humanize: {humanize_block}")

        logger.info(f"DrumGen compose: Finished. Part has {len(list(part.flatten().notesAndRests))} elements.")
        return part

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _apply_pattern(
        self,
        tgt_part: stream.Part,
        events: List[Dict[str, Any]],
        abs_offset: float,
        block_len: float,
        base_vel: int,
        humanize: bool,
        humanize_params: Dict[str, Any] # 受ける
    ) -> None:
        if not events:
            return

        for ev_idx, ev in enumerate(events):
            event_offset_in_pattern = float(ev.get("offset", 0.0))
            
            # パターン内のオフセットがブロック長を超える場合はスキップ
            if event_offset_in_pattern >= block_len:
                logger.debug(f"DrumGen _apply_pattern: Event {ev_idx} offset {event_offset_in_pattern:.2f} exceeds block_len {block_len:.2f}. Skipping.")
                continue

            # デュレーションの計算: パターンで指定されたデュレーションを使いつつ、ブロックの終端を超えないように調整
            default_hit_duration = 0.1 # ごく短い音価をデフォルトに
            event_duration_ql = float(ev.get("duration", default_hit_duration))
            
            # ヒットの終了がブロックの長さを超えないようにデュレーションをクリップ
            clipped_duration_ql = min(event_duration_ql, block_len - event_offset_in_pattern)

            if clipped_duration_ql < MIN_NOTE_DURATION_QL / 8: # あまりに短い音符はスキップ
                logger.debug(f"DrumGen _apply_pattern: Event {ev_idx} duration {clipped_duration_ql:.3f} too short. Skipping.")
                continue
            
            inst_name_original = ev.get("instrument")
            if not inst_name_original:
                logger.warning(f"DrumGen _apply_pattern: Event {ev_idx} has no instrument. Skipping.")
                continue
            
            # Ghost note のエイリアス解決
            inst_key = GHOST_ALIAS.get(inst_name_original.lower(), inst_name_original.lower())
            
            midi_num = GM_DRUM_MAP.get(inst_key)
            if midi_num is None:
                logger.warning(f"DrumGen _apply_pattern: Unknown drum token '{inst_name_original}' (mapped to '{inst_key}'). Skipping.")
                continue
            
            # ノートオブジェクトの作成
            n = note.Note()
            n.pitch = pitch.Pitch(midi=midi_num)
            
            # オフセットの設定 (絶対オフセット + パターン内オフセット)
            # humanize でオフセットが変更される可能性があるので、humanize 前のオフセットを保持
            current_hit_offset_in_stream = abs_offset + event_offset_in_pattern
            n.offset = current_hit_offset_in_stream # 初期オフセット

            n.duration = duration.Duration(quarterLength=clipped_duration_ql)
            
            # ベロシティの設定 (パターンで絶対値指定 or ベースベロシティに対する係数)
            event_velocity = ev.get("velocity")
            event_velocity_factor = ev.get("velocity_factor")

            final_velocity: int
            if event_velocity is not None:
                final_velocity = int(event_velocity)
            elif event_velocity_factor is not None:
                final_velocity = int(base_vel * float(event_velocity_factor))
            else: # velocity も velocity_factor もない場合は base_vel をそのまま使う
                final_velocity = base_vel
            
            final_velocity = max(1, min(127, final_velocity)) # 1-127 の範囲に収める
            n.volume = volume.Volume(velocity=final_velocity)
            
            if humanize:
                # _apply_hit_humanization は n の deepcopy を返すので、それで n を置き換える
                # また、humanize_params を渡す
                n_before_humanize_offset = n.offset # humanize前のオフセットを記録
                n = _apply_hit_humanization(n, **humanize_params)
                # _apply_hit_humanization が n.offset を変更するので、その変更されたオフセットで挿入
                insert_at_offset = n.offset
                n.offset = 0 # insert メソッドは要素のオフセットを無視し、指定された位置に挿入するためリセット
            else:
                insert_at_offset = current_hit_offset_in_stream
                n.offset = 0 # 同上

            tgt_part.insert(insert_at_offset, n)
            logger.debug(f"DrumGen _apply_pattern: Inserted {inst_name_original} (MIDI {midi_num}) at {insert_at_offset:.3f} (orig_offset_in_pattern: {event_offset_in_pattern:.2f}) with vel {final_velocity}, dur {clipped_duration_ql:.3f}")


    def _ensure_core_patterns(self) -> None:
        """必須のドラムパターンがライブラリに存在することを保証する"""
        if "default_drum_pattern" not in self.pattern_lib:
            self.pattern_lib["default_drum_pattern"] = {
                "description": "Default simple kick and snare (Auto-added if missing).",
                "time_signature": "4/4", # このTSはパターン固有のものだが、ジェネレータのグローバルTSで解釈される
                "pattern": [
                    {"instrument": "kick", "offset": 0.0, "duration": 0.1, "velocity": 90},
                    {"instrument": "snare", "offset": 1.0, "duration": 0.1, "velocity": 90},
                    {"instrument": "kick", "offset": 2.0, "duration": 0.1, "velocity": 90},
                    {"instrument": "snare", "offset": 3.0, "duration": 0.1, "velocity": 90},
                ],
            }
            logger.info("DrumGen _ensure_core_patterns: Added 'default_drum_pattern' to pattern library.")

        # 改修案では no_drums やその他のプレースホルダーの自動追加は省略されているため、ここでは追加しない。
        # 必要であれば、元のコードのように追加ロジックをここに記述。
        # 例:
        # if "no_drums" not in self.pattern_lib:
        #     self.pattern_lib["no_drums"] = {"description": "Silence for drums (Auto-added).", "time_signature": "4/4", "pattern": []}
        #     logger.info("DrumGen _ensure_core_patterns: Added 'no_drums' placeholder to pattern library.")
