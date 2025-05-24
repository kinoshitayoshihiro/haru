# --- START OF FILE generator/bass_generator.py (ヒューマナイズ外部化・修正版) ---
from __future__ import annotations
"""bass_generator.py – streamlined rewrite
Generates a **bass part** for the modular composer pipeline.
The heavy lifting (walking line, root-fifth, etc.) is delegated to
generator.bass_utils.generate_bass_measure so that this class
mainly decides **which style to use when**.
"""
from typing import Sequence, Dict, Any, Optional, List, Union
import random
import logging

from music21 import stream, harmony, note, tempo, meter, instrument as m21instrument, key # keyを追加

# ユーティリティのインポート
try:
    from .bass_utils import generate_bass_measure # 同じディレクトリなので相対インポート
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError as e:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.error(f"BassGenerator: Failed to import required modules: {e}")
    # ダミー関数でフォールバック
    def generate_bass_measure(*args, **kwargs) -> List[note.Note]: return []
    def apply_humanization_to_part(part, *args, **kwargs) -> stream.Part: return part # type: ignore
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature("4/4")
    MIN_NOTE_DURATION_QL = 0.125
    HUMANIZATION_TEMPLATES = {}


logger = logging.getLogger(__name__)

class BassGenerator:
    def __init__(
        self,
        rhythm_library: Optional[Dict[str, Dict]] = None,
        default_instrument = m21instrument.AcousticBass(),
        global_tempo: int = 100,
        global_time_signature: str = "4/4",
        global_key_tonic: str = "C", # グローバルキー情報を追加
        global_key_mode: str = "major",
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rhythm_library = rhythm_library if rhythm_library else {}
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        self.global_key_tonic = global_key_tonic
        self.global_key_mode = global_key_mode
        self.rng = rng or random.Random()
        
        # リズムライブラリに基本的なベースパターンがない場合のフォールバック
        if "bass_quarter_notes" not in self.rhythm_library:
            self.rhythm_library["bass_quarter_notes"] = {
                "description": "Default quarter note roots for bass.",
                "pattern": [
                    {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"},
                    {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}
                ]
            }
            logger.info("BassGenerator: Added 'bass_quarter_notes' to rhythm_library.")


    def _select_style(self, bass_params: Dict[str, Any], blk_musical_intent: Dict[str, Any]) -> str:
        if "style" in bass_params and bass_params["style"]:
            return bass_params["style"]
        intensity = blk_musical_intent.get("intensity", "medium").lower()
        if intensity in {"low", "medium_low"}: return "root_only"
        if intensity in {"medium"}: return "root_fifth"
        return "walking"

    def compose(self, processed_blocks: Sequence[Dict[str, Any]]) -> stream.Part:
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        bass_part.insert(0, self.global_time_signature_obj.clone())
        # グローバルキーをパートの最初に設定 (または最初のブロックのキー)
        first_block_tonic = processed_blocks[0].get("tonic_of_section", self.global_key_tonic) if processed_blocks else self.global_key_tonic
        first_block_mode = processed_blocks[0].get("mode", self.global_key_mode) if processed_blocks else self.global_key_mode
        bass_part.insert(0, key.Key(first_block_tonic, first_block_mode))

        current_total_offset = 0.0

        for i, blk_data in enumerate(processed_blocks):
            bass_params = blk_data.get("part_params", {}).get("bass", {})
            if not bass_params:
                current_total_offset += blk_data.get("q_length", 0.0)
                continue

            chord_label_str = blk_data.get("chord_label", "C")
            block_q_length = blk_data.get("q_length", 4.0)
            musical_intent = blk_data.get("musical_intent", {})
            
            selected_style = self._select_style(bass_params, musical_intent)
            
            cs_now = get_music21_chord_object(chord_label_str) # sanitize_chord_label は内部で呼ばれる
            if cs_now is None:
                current_total_offset += block_q_length
                continue

            cs_next = None
            if i + 1 < len(processed_blocks):
                cs_next = get_music21_chord_object(processed_blocks[i+1].get("chord_label"))
            if cs_next is None: cs_next = cs_now

            tonic = blk_data.get("tonic_of_section", self.global_key_tonic)
            mode = blk_data.get("mode", self.global_key_mode)
            target_octave = bass_params.get("octave", bass_params.get("bass_target_octave", 2))
            base_velocity = bass_params.get("velocity", bass_params.get("bass_velocity", 70))

            # --- bass_utils を使って1小節分のベース音符ピッチリストを取得 ---
            # generate_bass_measure はピッチのリストを返すように bass_utils を修正した想定
            measure_pitches_template: List[pitch.Pitch] = []
            try:
                # generate_bass_measure が List[note.Note] を返す場合、ピッチだけ取り出す
                temp_notes = generate_bass_measure(style=selected_style, cs_now=cs_now, cs_next=cs_next, tonic=tonic, mode=mode, octave=target_octave)
                measure_pitches_template = [n.pitch for n in temp_notes if isinstance(n, note.Note)]
            except Exception as e_gbm:
                logger.error(f"BassGenerator: Error in generate_bass_measure for style '{selected_style}': {e_gbm}. Using root note.")
                measure_pitches_template = [cs_now.root().transpose((target_octave - cs_now.root().octave) * 12)] * 4


            # --- リズムパターンに基づいてノートを配置 ---
            rhythm_key = bass_params.get("rhythm_key", "bass_quarter_notes")
            rhythm_details = self.rhythm_library.get(rhythm_key, self.rhythm_library.get("bass_quarter_notes"))
            
            pattern_events = rhythm_details.get("pattern", [])
            pattern_ref_duration = rhythm_details.get("reference_duration_ql", 4.0) # パターンの基準長

            pitch_idx = 0
            for event_data in pattern_events:
                event_offset_ratio = event_data.get("offset", 0.0) / pattern_ref_duration
                event_duration_ratio = event_data.get("duration", 1.0) / pattern_ref_duration
                
                abs_event_offset = current_total_offset + (event_offset_ratio * block_q_length)
                actual_event_duration = event_duration_ratio * block_q_length
                
                if actual_event_duration < MIN_NOTE_DURATION_QL / 2: continue

                if measure_pitches_template:
                    current_pitch = measure_pitches_template[pitch_idx % len(measure_pitches_template)]
                    pitch_idx += 1
                else: # ピッチ候補がなければルート音
                    current_pitch = cs_now.root().transpose((target_octave - cs_now.root().octave) * 12)

                n = note.Note(current_pitch)
                n.quarterLength = actual_event_duration
                vel_factor = event_data.get("velocity_factor", 1.0)
                n.volume = m21instrument.Volume(velocity=int(base_velocity * vel_factor))
                bass_part.insert(abs_event_offset, n)

            current_total_offset += block_q_length

        # --- パート全体にヒューマナイゼーションを適用 ---
        # modular_composer から渡されるパラメータに基づいて適用
        # (最初のブロックのパラメータを代表として使うか、より詳細な制御を検討)
        global_bass_params = processed_blocks[0].get("part_params", {}).get("bass", {}) if processed_blocks else {}
        if global_bass_params.get("bass_humanize", global_bass_params.get("humanize", False)): # "bass_humanize" または汎用の "humanize"
            h_template = global_bass_params.get("bass_humanize_style_template", "default_subtle")
            h_custom = {
                k.replace("bass_humanize_", "").replace("humanize_", ""): v
                for k, v in global_bass_params.items()
                if (k.startswith("bass_humanize_") or k.startswith("humanize_")) and not k.endswith("_template") and not k.endswith("humanize")
            }
            logger.info(f"BassGenerator: Applying humanization with template '{h_template}' and params {h_custom}")
            bass_part = apply_humanization_to_part(bass_part, template_name=h_template, custom_params=h_custom)
            # IDやグローバル要素が失われる可能性があるので再設定
            bass_part.id = "Bass"
            if not bass_part.getElementsByClass(instrument.Instrument).first(): bass_part.insert(0, self.default_instrument)
            if not bass_part.getElementsByClass(tempo.MetronomeMark).first(): bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
            if not bass_part.getElementsByClass(meter.TimeSignature).first(): bass_part.insert(0, self.global_time_signature_obj.clone())
            if not bass_part.getElementsByClass(key.Key).first(): bass_part.insert(0, key.Key(first_block_tonic, first_block_mode))


        return bass_part
# --- END OF FILE generator/bass_generator.py ---
