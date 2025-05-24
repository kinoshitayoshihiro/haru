# --- START OF FILE generator/bass_generator.py (修正・ブラッシュアップ版) ---
from __future__ import annotations
"""bass_generator.py – streamlined rewrite
... (docstringは変更なし) ...
"""
from typing import Sequence, Dict, Any, Optional, List, Union # List, Union を追加
import random
import logging

from music21 import stream, harmony, note, tempo, meter, instrument as m21instrument # noteなどを追加

# bass_utils と humanizer をインポート
try:
    from .bass_utils import generate_bass_measure # 同じディレクトリなので相対インポート
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES # utilitiesから
except ImportError as e:
    logger.error(f"BassGenerator: Failed to import required modules (bass_utils or humanizer): {e}")
    # 致命的なので、ここで例外を再発生させるか、ダミー関数で何もしないようにするか
    def generate_bass_measure(*args, **kwargs): return [] # Dummy
    def apply_humanization_to_part(part, *args, **kwargs): return part # Dummy

logger = logging.getLogger(__name__)

class BassGenerator:
    def __init__(
        self,
        rhythm_library: Optional[Dict[str, Dict]] = None, # bass_utilsが主なので、これは将来的な拡張用
        default_instrument = m21instrument.AcousticBass(), # デフォルト楽器を設定
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rhythm_library = rhythm_library if rhythm_library else {}
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        try:
            from utilities.core_music_utils import get_time_signature_object # ここでインポート
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except ImportError:
            logger.error("BassGenerator: Failed to import get_time_signature_object. Using basic 4/4.")
            self.global_time_signature_obj = meter.TimeSignature("4/4")
        self.rng = rng or random.Random()

    def _select_style(self, bass_params: Dict[str, Any], blk_musical_intent: Dict[str, Any]) -> str:
        """Decide which bass style to use for the block."""
        # 優先順位: bass_paramsで直接指定 > 強弱に基づくヒューリスティック > デフォルト
        if "style" in bass_params and bass_params["style"]: # 明示的なスタイル指定があればそれを優先
            return bass_params["style"]

        intensity = blk_musical_intent.get("intensity", "medium").lower()
        if intensity in {"low", "medium_low"}:
            return "root_only"
        if intensity in {"medium"}: # "medium_high" は walking にする
            return "root_fifth"
        return "walking"  # high, very_high, または指定なしの場合

    def compose(self, processed_blocks: Sequence[Dict[str, Any]]) -> stream.Part:
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        bass_part.insert(0, self.global_time_signature_obj.clone())
        # Key signature can be added from the first block's info if needed

        current_total_offset = 0.0

        for i, blk_data in enumerate(processed_blocks):
            # --- パラメータ取得 ---
            # part_params.bass が存在しない場合も考慮
            bass_params_for_block = blk_data.get("part_params", {}).get("bass", {})
            if not bass_params_for_block: # ベース用のパラメータがなければスキップ
                logger.debug(f"BassGenerator: No bass params for block {i+1}. Skipping bass for this block.")
                current_total_offset += blk_data.get("q_length", 0.0)
                continue

            chord_label_str = blk_data.get("chord_label", "C")
            block_q_length = blk_data.get("q_length", 4.0)
            musical_intent_for_block = blk_data.get("musical_intent", {}) # translate_keywordsで解決済みのはずだが念のため
            
            # スタイル選択
            selected_style = self._select_style(bass_params_for_block, musical_intent_for_block)
            
            # コードオブジェクト生成 (サニタイズは modular_composer で行われているはずだが、念のため)
            try:
                from utilities.core_music_utils import get_music21_chord_object # ここでインポート
                cs_now = get_music21_chord_object(chord_label_str)
                if cs_now is None: # パース失敗またはRest
                    logger.warning(f"BassGenerator: Could not parse chord '{chord_label_str}' for block {i+1}. Skipping.")
                    current_total_offset += block_q_length
                    continue
            except ImportError: # フォールバック
                cs_now = harmony.ChordSymbol(chord_label_str)


            # 次のコード (アプローチノート用)
            cs_next: Optional[harmony.ChordSymbol] = None
            if i + 1 < len(processed_blocks):
                next_blk_data = processed_blocks[i+1]
                next_chord_label = next_blk_data.get("chord_label")
                if next_chord_label:
                    try: cs_next = get_music21_chord_object(next_chord_label)
                    except: cs_next = harmony.ChordSymbol(next_chord_label) # フォールバック
            if cs_next is None: cs_next = cs_now # 最後は自分自身へアプローチ

            tonic_of_section = blk_data.get("tonic_of_section", "C")
            mode_of_section = blk_data.get("mode", "major")
            target_octave = bass_params_for_block.get("octave", 2) # デフォルトオクターブ
            base_velocity = bass_params_for_block.get("velocity", 70) # デフォルトベロシティ

            # --- bass_utils を使って1小節分のベース音符リストを取得 ---
            # generate_bass_measure は4/4の1小節分(4拍)の音符を返す想定
            measure_notes_template = generate_bass_measure(
                style=selected_style,
                cs_now=cs_now,
                cs_next=cs_next,
                tonic=tonic_of_section,
                mode=mode_of_section,
                octave=target_octave
            )

            # --- ブロック長に合わせて音符を配置・伸縮 ---
            # bass_utils が返すのは通常4つの1拍音符。これをブロック長に合わせる。
            # rhythm_library の bass_lines を参照して、より複雑なリズムを適用することも可能。
            # ここでは、generate_bass_measure が返す音符を均等に配置する。
            
            # リズムキーに基づいてリズムパターンを取得
            rhythm_key = bass_params_for_block.get("rhythm_key", "bass_quarter_notes") # デフォルト
            rhythm_pattern_detail = self.rhythm_library.get(rhythm_key, 
                                                           self.rhythm_library.get("bass_quarter_notes", {"pattern": [{"offset":0.0, "duration":1.0}, {"offset":1.0, "duration":1.0}, {"offset":2.0, "duration":1.0}, {"offset":3.0, "duration":1.0}]}))
            
            rhythm_events = rhythm_pattern_detail.get("pattern", [])
            
            # measure_notes_template のピッチをリズムイベントに割り当てる
            # (measure_notes_template の要素数と rhythm_events の要素数が一致するとは限らない)
            pitch_idx = 0
            for event_idx, event_data in enumerate(rhythm_events):
                event_offset_in_pattern = event_data.get("offset", 0.0)
                event_duration_in_pattern = event_data.get("duration", 1.0)
                event_velocity_factor = event_data.get("velocity_factor", 1.0)
                
                # ブロック長に対する相対的なオフセットとデュレーションに変換
                # (rhythm_libraryのパターンは通常1小節(4拍)を基準とする想定)
                pattern_total_duration = rhythm_pattern_detail.get("total_duration_ql", 4.0) # パターンの基準長
                
                abs_event_offset = current_total_offset + (event_offset_in_pattern / pattern_total_duration) * block_q_length
                actual_event_duration = (event_duration_in_pattern / pattern_total_duration) * block_q_length
                
                if actual_event_duration < MIN_NOTE_DURATION_QL / 2: continue # 短すぎる音はスキップ

                if pitch_idx < len(measure_notes_template):
                    current_pitch = measure_notes_template[pitch_idx].pitch # Noteオブジェクトからpitchを取得
                    pitch_idx = (pitch_idx + 1) % len(measure_notes_template) # ピッチを循環使用
                else: # ピッチ候補が尽きたらルート音など
                    current_pitch = cs_now.root().transpose((target_octave - cs_now.root().octave) * 12)

                n = note.Note(current_pitch)
                n.quarterLength = actual_event_duration
                n.volume = m21instrument.Volume(velocity=int(base_velocity * event_velocity_factor))
                bass_part.insert(abs_event_offset, n)

            current_total_offset += block_q_length

        # --- パート全体にヒューマナイゼーションを適用 ---
        humanize_bass = processed_blocks[0]["part_params"].get("bass", {}).get("bass_humanize", False) if processed_blocks else False
        if humanize_bass:
            h_template = processed_blocks[0]["part_params"]["bass"].get("bass_humanize_style_template", "default_subtle")
            h_custom = {k.replace("bass_humanize_",""):v for k,v in processed_blocks[0]["part_params"]["bass"].items() if k.startswith("bass_humanize_") and not k.endswith("_template")}
            logger.info(f"BassGenerator: Applying humanization with template '{h_template}' and params {h_custom}")
            bass_part = apply_humanization_to_part(bass_part, template_name=h_template, custom_params=h_custom)

        return bass_part
# --- END OF FILE generator/bass_generator.py ---
