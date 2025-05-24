# --- START OF FILE generator/melody_generator.py (修正・ブラッシュアップ版) ---
from __future__ import annotations
"""melody_generator.py – *lightweight rewrite*
... (docstringは変更なし) ...
"""
from typing import Dict, List, Sequence, Any, Tuple, Optional, Union # Union を追加
import random
import logging

from music21 import stream, note, harmony, tempo, meter, instrument as m21instrument, key # key を追加

# melody_utils と humanizer をインポート
try:
    from .melody_utils import generate_melodic_pitches # 同じディレクトリなので相対インポート
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object # utilitiesから
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:
    logger.error(f"MelodyGenerator: Failed to import required modules (melody_utils or humanizer or core_music_utils): {e}")
    def generate_melodic_pitches(*args, **kwargs): return [] # Dummy
    def apply_humanization_to_part(part, *args, **kwargs): return part # Dummy
    MIN_NOTE_DURATION_QL = 0.125 # Dummy
    def get_time_signature_object(ts_str): return meter.TimeSignature("4/4") # Dummy


logger = logging.getLogger(__name__)

class MelodyGenerator:
    def __init__(
        self,
        rhythm_library: Optional[Dict[str, Dict]] = None, # パターンは { "pattern": [0.0, 0.5, ...], "note_duration_ql": 0.5 } のような形式を想定
        default_instrument = m21instrument.Flute(), # デフォルト楽器
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        global_key_signature_tonic: str = "C", # グローバルキー情報
        global_key_signature_mode: str = "major",
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rhythm_library = rhythm_library if rhythm_library else {}
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        self.global_key_tonic = global_key_signature_tonic
        self.global_key_mode = global_key_signature_mode
        self.rng = rng or random.Random()

    def _get_rhythm_details(self, rhythm_key: str) -> Dict[str, Any]:
        """
        rhythm_libraryからリズムキーに対応する詳細を取得する。
        beat_offsets (旧 template) と note_duration_ql を含むことを期待。
        """
        default_rhythm = {
            "description": "Default melody rhythm - quarter notes",
            "pattern": [0.0, 1.0, 2.0, 3.0], # オフセットのリスト
            "note_duration_ql": 1.0 # 各音符の基本長
        }
        if rhythm_key in self.rhythm_library:
            details = self.rhythm_library[rhythm_key]
            if "pattern" not in details: # "pattern" がオフセットリストを指すように
                logger.warning(f"MelodyGen: Rhythm key '{rhythm_key}' missing 'pattern' (offsets list). Using default.")
                return default_rhythm
            return details
        logger.warning(f"MelodyGen: Rhythm key '{rhythm_key}' not found. Using default quarter grid.")
        return default_rhythm

    def compose(self, processed_blocks: Sequence[Dict[str, Any]]) -> stream.Part:
        melody_part = stream.Part(id="Melody")
        melody_part.insert(0, self.default_instrument)
        melody_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        melody_part.insert(0, self.global_time_signature_obj.clone())
        # グローバルキーをパートの最初に設定
        melody_part.insert(0, key.Key(self.global_key_tonic, self.global_key_mode))


        current_total_offset = 0.0

        for blk_idx, blk_data in enumerate(processed_blocks):
            melody_params = blk_data.get("part_params", {}).get("melody", {})
            if melody_params.get("skip", False): # スキップフラグ
                logger.debug(f"MelodyGenerator: Skipping melody for block {blk_idx+1} due to 'skip' flag.")
                current_total_offset += blk_data.get("q_length", 0.0)
                continue
            
            chord_label_str = blk_data.get("chord_label", "C")
            block_q_length = blk_data.get("q_length", 4.0)
            
            try:
                from utilities.core_music_utils import get_music21_chord_object
                cs_current_block = get_music21_chord_object(chord_label_str)
                if cs_current_block is None:
                    logger.warning(f"MelodyGenerator: Could not parse chord '{chord_label_str}' for block {blk_idx+1}. Skipping melody notes for this block.")
                    current_total_offset += block_q_length
                    continue
            except ImportError:
                cs_current_block = harmony.ChordSymbol(chord_label_str)


            tonic_for_block = blk_data.get("tonic_of_section", self.global_key_tonic)
            mode_for_block = blk_data.get("mode", self.global_key_mode)
            
            rhythm_key_for_block = melody_params.get("rhythm_key", "default_melody_rhythm")
            rhythm_details = self._get_rhythm_details(rhythm_key_for_block)
            
            beat_offsets_template = rhythm_details.get("pattern", [0.0, 1.0, 2.0, 3.0])
            # メロディノートの基本デュレーション (リズムライブラリから取得、なければデフォルト)
            base_note_duration_ql = rhythm_details.get("note_duration_ql", 
                                                     melody_params.get("note_duration_ql", 0.5)) # 8分音符がデフォルト

            # テンプレートの基準長 (通常4拍=1小節)
            template_reference_duration = rhythm_details.get("reference_duration_ql", 4.0)
            
            # beat_offsets をブロック長に合わせて伸縮・繰り返し
            stretched_beat_offsets: List[float] = []
            current_template_offset = 0.0
            while current_template_offset < block_q_length:
                for template_beat in beat_offsets_template:
                    # 伸縮率を計算
                    stretch_factor = block_q_length / template_reference_duration if template_reference_duration > 0 else 1.0
                    # 実際には、ブロック長がテンプレート長の整数倍でない場合、最後の繰り返しは途中で切れる
                    # ここでは、テンプレートをブロック長に収まるように繰り返す
                    # テンプレートの1サイクル分の長さを計算
                    cycle_len_in_template = max(beat_offsets_template) if beat_offsets_template else template_reference_duration
                    
                    # このロジックは、テンプレートがブロック長に収まるように繰り返すのではなく、
                    # テンプレート内の各オフセットをブロック長に合わせて伸縮させる方が適切
                    # 例: 4拍テンプレートを8拍ブロックに適用 -> 各オフセットとデュレーションを2倍
                    # 例: 4拍テンプレートを2拍ブロックに適用 -> 各オフセットとデュレーションを0.5倍
                    # melody_utils.generate_melodic_pitches に渡す beat_offsets は、
                    # ブロック内での絶対的なタイミング（ブロック開始からのオフセット）であるべき。
                    
                    # 修正: beat_offsets はブロック開始からの相対オフセットのリスト
                    #       リズムライブラリの "pattern" は1小節(4拍)内の相対オフセットとする
                    #       ブロック長が4拍でない場合は、このオフセットを伸縮させる
                    
                    # ブロック長が template_reference_duration の何倍か
                    num_template_repeats_fit = block_q_length / template_reference_duration
                    
                    # ここで生成する beat_offsets は、generate_melodic_pitches に渡すための
                    #「このブロック内でメロディノートを配置すべきタイミング」のリスト
                    # generate_melodic_pitches は、そのタイミングごとに1音を生成する。
                    break # このループは一旦単純化。generate_melodic_pitchesに渡すオフセットリストを直接作る。
                break # whileループも一旦抜ける。下のロジックでbeat_offsetsを生成。

            # generate_melodic_pitches に渡す beat_offsets を生成
            # リズムライブラリの "pattern" は、1単位（例: 1小節）内の相対オフセットとする
            final_beat_offsets_for_block: List[float] = []
            num_cycles = 0
            current_cycle_start_offset_in_block = 0.0
            while current_cycle_start_offset_in_block < block_q_length:
                for template_offset in beat_offsets_template:
                    # テンプレートのオフセットを現在のサイクルに合わせて調整し、ブロック長でスケール
                    # この方法は、テンプレートが常にブロックの先頭から始まると仮定している
                    # より柔軟なのは、テンプレートの長さを考慮して繰り返すこと
                    
                    # 修正案: テンプレートをブロック長に合わせて伸縮・繰り返し
                    # テンプレートの基準長 (例: 4拍)
                    # ブロック長が8拍なら、テンプレートは2回繰り返され、各オフセットはそのまま
                    # ブロック長が2拍なら、テンプレートは0.5回となり、オフセットは半分になるか、最初の部分だけ使う
                    
                    # ここでは、リズムライブラリの "pattern" が1小節(4拍)内のオフセットリストと仮定
                    # ブロック長が4拍ならそのまま、8拍なら2回、2拍なら0.5回（最初の2拍分）
                    
                    # 1サイクルのオフセットを生成
                    cycle_offsets = [(offset_in_template / template_reference_duration) * block_q_length 
                                     for offset_in_template in beat_offsets_template
                                     if (offset_in_template / template_reference_duration) * block_q_length < block_q_length]
                    # このやり方だと、ブロックの途中で終わるパターンが難しい
                    # MelodyGenerator の _get_beat_offsets のように、
                    # リズムライブラリの "pattern" が直接オフセットのリストを返すようにし、
                    # そのリストをブロック長に合わせて伸縮・配置する方がシンプル。
                    
                    # MelodyGeneratorの元々の _get_beat_offsets と generate_melodic_pitches の使い方に戻す
                    # beat_template は1小節(4拍)基準のオフセットリスト
                    # これをブロック長に合わせて伸縮
                    stretch_factor = block_q_length / template_reference_duration
                    final_beat_offsets_for_block = [tpl_off * stretch_factor for tpl_off in beat_offsets_template]
                    break # while ループを抜ける
                break # while ループを抜ける
            if not final_beat_offsets_for_block: # フォールバック
                final_beat_offsets_for_block = [i * (block_q_length / 4.0) for i in range(4)]


            octave_range_for_block = tuple(melody_params.get("octave_range", [4, 5]))
            
            # --- melody_utils を使ってピッチリストを生成 ---
            generated_notes = generate_melodic_pitches(
                chord=cs_current_block,
                tonic=tonic_for_block,
                mode=mode_for_block,
                beat_offsets=final_beat_offsets_for_block, # ブロック内での絶対タイミング
                octave_range=octave_range_for_block,
                rnd=self.rng,
                min_note_duration_ql=MIN_NOTE_DURATION_QL # 渡す
            )

            # --- 密度とデュレーションを適用 ---
            density_for_block = melody_params.get("density", 0.7)
            
            for idx, n_obj in enumerate(generated_notes):
                if self.rng.random() <= density_for_block:
                    # デュレーション設定: 次のノートの開始位置まで、または基本デュレーション
                    if idx < len(final_beat_offsets_for_block) - 1:
                        # 次のノートの開始位置までの長さをデュレーションとする
                        note_actual_duration = final_beat_offsets_for_block[idx+1] - final_beat_offsets_for_block[idx]
                    else:
                        # 最後のノートはブロックの終わりまで、または基本デュレーション
                        note_actual_duration = block_q_length - final_beat_offsets_for_block[idx]
                    
                    # MIN_NOTE_DURATION_QL より短くならないようにしつつ、基本デュレーションも考慮
                    n_obj.quarterLength = max(MIN_NOTE_DURATION_QL, min(note_actual_duration, base_note_duration_ql * stretch_factor if 'stretch_factor' in locals() else base_note_duration_ql))
                    
                    # ベロシティ設定 (オプション)
                    n_obj.volume = m21instrument.Volume(velocity=melody_params.get("velocity", 80))
                    
                    melody_part.insert(current_total_offset + final_beat_offsets_for_block[idx], n_obj)

            current_total_offset += block_q_length

        # --- パート全体にヒューマナイゼーションを適用 ---
        humanize_melody = processed_blocks[0]["part_params"].get("melody", {}).get("melody_humanize", False) if processed_blocks else False
        if humanize_melody:
            h_template_mel = processed_blocks[0]["part_params"]["melody"].get("melody_humanize_style_template", "default_subtle")
            h_custom_mel = {k.replace("melody_humanize_",""):v for k,v in processed_blocks[0]["part_params"]["melody"].items() if k.startswith("melody_humanize_") and not k.endswith("_template")}
            logger.info(f"MelodyGenerator: Applying humanization with template '{h_template_mel}' and params {h_custom_mel}")
            melody_part = apply_humanization_to_part(melody_part, template_name=h_template_mel, custom_params=h_custom_mel)
            
        return melody_part
# --- END OF FILE generator/melody_generator.py ---
