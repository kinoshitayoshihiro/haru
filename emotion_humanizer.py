# --- START OF FILE emotion_humanizer.py (Haruさんのガイドライン準拠強化版) ---
# -*- coding: utf-8 -*-
"""
emotion_humanizer.py
===================================================
chordmap.yaml を読み込み、セクションごとの感情や音楽的意図に基づいて、
コードの解釈、推奨テンションの考慮、感情表現パラメータの適用を行い、
詳細な演奏指示をYAML形式で出力する。
ボイシング自体は行わず、ChordVoicerや各楽器ジェネレータへの情報を提供する。
"""

import yaml
import random
from pathlib import Path
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field, ValidationError
from music21 import harmony, pitch # stream, note, chord, meter, tempo, volume, articulations は直接は使わない
import re
import logging

# core_music_utilsから sanitize_chord_label をインポートすることを期待
# これがコードラベルの一次的な正規化（フラット記号の変換など）を行う
try:
    from utilities.core_music_utils import sanitize_chord_label
except ImportError:
    logging.warning("emotion_humanizer: Could not import sanitize_chord_label from utilities.core_music_utils. Using a basic internal fallback.")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: # 基本的なフォールバック
        if label is None or not str(label).strip(): return "Rest"
        s = str(label).strip().replace(' ', '')
        if s.upper() in ['NC', 'N.C.', 'NOCHORD', 'SILENCE', '-', 'REST']: return "Rest"
        # music21は 'b' より '-' を好むので、ルート音の 'b' を '-' に置換する処理を想定
        # (このフォールバックでは簡易的に主要なものだけ)
        s = s.replace('Bb', 'B-').replace('Eb', 'E-').replace('Ab', 'A-')
        s = s.replace('Db', 'D-').replace('Gb', 'G-')
        s = s.replace('△', 'maj').replace('M', 'maj')
        if 'majaj' in s: s = s.replace('majaj', 'maj')
        s = s.replace('ø', 'm7b5').replace('Φ', 'm7b5')
        s = s.replace('(', '').replace(')', '')
        return s

logger = logging.getLogger(__name__)

# --- 1. Pydanticモデル定義 (chordmap.yaml の構造に合わせて) ---
class MusicalIntent(BaseModel):
    emotion: str
    intensity: str

class ExpressionDetails(BaseModel):
    section_tonic: str
    section_mode: str
    recommended_tensions: List[str] = Field(default_factory=list)
    target_rhythm_category: Optional[str] = None
    approach_style: Optional[str] = None
    articulation_profile: Optional[str] = None
    humanize_profile: Optional[str] = None
    # ボイシングに関する指示もここに追加可能
    voicing_style_piano_rh: Optional[str] = None
    voicing_style_piano_lh: Optional[str] = None
    voicing_style_guitar: Optional[str] = None
    # target_octave_for_voicing: Optional[int] = None # 楽器ごとにpart_settingsで指定する方が柔軟か

class ChordItem(BaseModel):
    label: str
    duration_beats: float
    nuance: Optional[str] = None

class Section(BaseModel):
    order: int
    length_in_measures: int
    musical_intent: MusicalIntent
    expression_details: ExpressionDetails
    part_settings: Optional[Dict[str, Any]] = Field(default_factory=dict)
    part_specific_hints: Optional[Dict[str, Any]] = Field(default_factory=dict)
    chord_progression: List[ChordItem]
    adjusted_start_beat: Optional[float] = None

class GlobalSettings(BaseModel):
    tempo: int
    time_signature: str
    key_tonic: str
    key_mode: str

class ChordMapInput(BaseModel):
    project_title: Optional[str] = None
    global_settings: GlobalSettings
    sections: Dict[str, Section]

# --- 2. 感情表現プロファイル定義 ---
class EmotionExpressionProfile(BaseModel):
    onset_shift_ms: float = 0.0
    sustain_factor: float = 1.0
    velocity_bias: int = 0
    articulation: Optional[Literal["legato", "staccato", "tenuto", "accented", "normal"]] = "normal"

EMOTION_EXPRESSIONS: Dict[str, EmotionExpressionProfile] = {
    "default": EmotionExpressionProfile(),
    "quiet_pain_and_nascent_strength": EmotionExpressionProfile(onset_shift_ms=15, sustain_factor=1.1, velocity_bias=-8, articulation="legato"),
    "emotional_realization_and_gratitude": EmotionExpressionProfile(onset_shift_ms=5, sustain_factor=1.0, velocity_bias=2, articulation="tenuto"),
    "love_and_resolution": EmotionExpressionProfile(onset_shift_ms=-5, sustain_factor=0.95, velocity_bias=5, articulation="accented"),
    "regret_and_internal_conflict": EmotionExpressionProfile(onset_shift_ms=10, sustain_factor=0.85, velocity_bias=-5, articulation="staccato"),
    "emotional_confession": EmotionExpressionProfile(onset_shift_ms=8, sustain_factor=1.05, velocity_bias=3, articulation="legato"),
    "reflection_in_absence": EmotionExpressionProfile(onset_shift_ms=20, sustain_factor=1.15, velocity_bias=-10, articulation="tenuto"),
    "emotional_storm_and_need": EmotionExpressionProfile(onset_shift_ms=-10, sustain_factor=0.75, velocity_bias=8, articulation="staccato"),
    "frozen_emotion_and_memory": EmotionExpressionProfile(onset_shift_ms=25, sustain_factor=1.2, velocity_bias=-12, articulation="legato"),
    "bittersweet_reconciliation": EmotionExpressionProfile(onset_shift_ms=10, sustain_factor=0.9, velocity_bias=0, articulation="tenuto"),
    "need_and_fragility": EmotionExpressionProfile(onset_shift_ms=15, sustain_factor=1.0, velocity_bias=-2, articulation="legato"),
    "dawn_and_support": EmotionExpressionProfile(onset_shift_ms=5, sustain_factor=1.1, velocity_bias=4, articulation="legato"),
    "light_and_nostalgia": EmotionExpressionProfile(onset_shift_ms=18, sustain_factor=1.1, velocity_bias=-6, articulation="tenuto"),
    "coexistence_and_future": EmotionExpressionProfile(onset_shift_ms=0, sustain_factor=1.0, velocity_bias=7, articulation="accented"),
    "hope": EmotionExpressionProfile(onset_shift_ms=12, sustain_factor=0.95, velocity_bias=6, articulation="legato"),
    "prayer": EmotionExpressionProfile(onset_shift_ms=20, sustain_factor=1.10, velocity_bias=-4, articulation="tenuto"),
    "conflict": EmotionExpressionProfile(onset_shift_ms=-8, sustain_factor=0.80, velocity_bias=4, articulation="staccato"),
    "sorrow": EmotionExpressionProfile(onset_shift_ms=10, sustain_factor=1.0, velocity_bias=-2, articulation="normal"),
    "urgency": EmotionExpressionProfile(onset_shift_ms=-15, sustain_factor=0.70, velocity_bias=7, articulation="staccato"),
}

# --- 3. コード解釈と感情表現適用の関数 ---

def get_bpm_from_chordmap(chordmap: ChordMapInput) -> float:
    return float(chordmap.global_settings.tempo)

def get_interpreted_chord_details(
    original_chord_label: str,
    recommended_tensions: List[str]
) -> Dict[str, Optional[str]]:
    """
    コードラベルと推奨テンションから、music21で解釈可能なコードシンボル文字列とベース音を返す。
    Haruさんの「music21 コードシンボル完全ガイド」のルールを適用。
    """
    if not original_chord_label or original_chord_label.strip().lower() in ["rest", "n.c.", "nc", "none", "-"]:
        return {"interpreted_symbol": "Rest", "specified_bass": None}

    # sanitize_chord_label で一次正規化 (フラット記号の '-' への統一など)
    # この sanitize_chord_label は core_music_utils.py のものを想定
    sanitized_label = sanitize_chord_label(original_chord_label)
    if not sanitized_label or sanitized_label == "Rest":
        return {"interpreted_symbol": "Rest", "specified_bass": None}

    # ここで「完全ガイド」に基づいたさらに詳細な表記ゆれ修正やテンションの整形を行う
    # (例: Am(add9) -> Amadd9, C7(b9,#11) -> C7b9#11)
    # この部分はHaruさんのガイドのルールを正規表現などで実装していく
    
    current_label = sanitized_label # sanitize_chord_label の結果をベースにする

    # スラッシュコードの分離
    base_chord_part = current_label
    bass_note_part = None
    if '/' in current_label:
        parts = current_label.split('/', 1)
        base_chord_part = parts[0]
        if len(parts) > 1:
            bass_note_part = parts[1]
            # ベース音も sanitize (例: Bb -> B-)
            bass_note_part = sanitize_chord_label(bass_note_part) # Rest になることはない想定

    # 推奨テンションをコードラベルに付加するロジック
    # Haruさんのガイド「11. ベストプラクティス 3. add と alter の混在時は alter → add の順」
    # を参考に、テンションをソートして結合するなどの処理を検討。
    # ここでは、まず基本コード部とテンションを結合するシンプルな形を目指す。
    # music21のChordSymbolはかなり賢いので、ある程度の表記ゆれは吸収してくれる。
    
    final_symbol_str = base_chord_part # 基本コード部分
    
    # recommended_tensions を整形して付加
    # (例: ["m7", "add9"] を "m7add9" のように)
    # ただし、元のコードラベルに既に含まれているテンションとの重複を避ける工夫が必要
    
    # 現時点では、recommended_tensions は主にボイシングの際のヒントとし、
    # chord_label 自体が music21 で解釈可能な完成形であることを期待する。
    # もし recommended_tensions を積極的にコードシンボルに組み込むなら、
    # より高度なマージロジックが必要。
    # (例: "C" + ["maj7", "add9"] -> "Cmaj7add9")

    # 最終的なコードシンボル文字列を生成
    # (この段階では、まだ recommended_tensions を直接結合していない)
    # 必要であれば、ここで recommended_tensions を考慮して final_symbol_str を加工する
    # 例:
    # if recommended_tensions:
    #     for ten in recommended_tensions:
    #         if ten not in final_symbol_str: # 単純な重複チェック
    #             final_symbol_str += ten


    # music21で一度パースしてみて、妥当性を確認（オプション）
    try:
        cs_test = harmony.ChordSymbol(final_symbol_str)
        if bass_note_part:
            cs_test.bass(bass_note_part) # ベース音も設定してテスト
        # logger.debug(f"  Interpreted as: {cs_test.figure} (Bass: {cs_test.bass()})")
    except Exception as e:
        logger.warning(f"  Could not fully validate interpreted symbol '{final_symbol_str}' with bass '{bass_note_part}' using music21: {e}")
        # パースに失敗しても、文字列はそのまま返す（後段のChordVoicerで再試行）

    return {"interpreted_symbol": final_symbol_str, "specified_bass": bass_note_part}


def apply_emotional_expression_to_event(
    base_duration_beats: float,
    base_offset_beats: float,
    emotion_profile: EmotionExpressionProfile,
    bpm: float,
    base_velocity: int = 64
) -> Dict[str, Any]:
    # ... (この関数は変更なし) ...
    onset_shift_beats = (emotion_profile.onset_shift_ms * bpm) / 60000.0
    actual_offset_beats = base_offset_beats + onset_shift_beats
    actual_duration_beats = base_duration_beats * emotion_profile.sustain_factor
    actual_velocity = min(127, max(1, base_velocity + emotion_profile.velocity_bias))
    return {
        "original_duration_beats": round(base_duration_beats, 4),
        "original_offset_beats": round(base_offset_beats, 4),
        "humanized_duration_beats": round(actual_duration_beats, 4),
        "humanized_offset_beats": round(actual_offset_beats, 4),
        "humanized_velocity": actual_velocity,
        "humanized_articulation": emotion_profile.articulation,
        "emotion_profile_applied": emotion_profile.model_dump()
    }

# --- 4. メイン処理関数 ---
def process_chordmap_for_emotion(input_yaml_path: str, output_yaml_path: str):
    try:
        with Path(input_yaml_path).open("r", encoding="utf-8") as f:
            raw_chordmap = yaml.safe_load(f)
        chordmap = ChordMapInput.model_validate(raw_chordmap)
    except Exception as e: # より広範な例外をキャッチ
        print(f"Error loading or validating chordmap.yaml at {input_yaml_path}: {e}")
        return

    bpm = get_bpm_from_chordmap(chordmap)
    output_data = {
        "project_title": chordmap.project_title,
        "global_settings": chordmap.global_settings.model_dump(),
        "sections": {}
    }
    current_absolute_offset_beats = 0.0
    sorted_sections = sorted(chordmap.sections.items(), key=lambda item: item[1].order)

    for section_name, section_data in sorted_sections:
        logger.info(f"Processing section: {section_name}...")
        section_output = {
            "order": section_data.order,
            "length_in_measures": section_data.length_in_measures,
            "musical_intent": section_data.musical_intent.model_dump(),
            "expression_details": section_data.expression_details.model_dump(),
            "part_settings": section_data.part_settings,
            "processed_chord_events": []
        }
        section_emotion = section_data.musical_intent.emotion
        emotion_profile_for_section = EMOTION_EXPRESSIONS.get(section_emotion, EMOTION_EXPRESSIONS["default"])
        logger.info(f"  Emotion: {section_emotion}, Profile: {emotion_profile_for_section.model_dump(exclude_none=True)}")

        if section_data.adjusted_start_beat is not None:
            current_absolute_offset_beats = section_data.adjusted_start_beat
            logger.info(f"  Adjusted start beat for section '{section_name}' to: {current_absolute_offset_beats}")

        section_relative_offset_beats = 0.0
        for chord_item in section_data.chord_progression:
            base_chord_label = chord_item.label
            base_duration = chord_item.duration_beats

            interpreted_details = get_interpreted_chord_details(
                base_chord_label,
                section_data.expression_details.recommended_tensions
            )
            final_chord_symbol_str = interpreted_details["interpreted_symbol"]
            specified_bass_str = interpreted_details["specified_bass"]

            if final_chord_symbol_str == "Rest":
                processed_event = {
                    "chord_symbol_for_voicing": "Rest", # ボイサーがRestを認識できるように
                    "specified_bass_for_voicing": None,
                    "original_duration_beats": base_duration,
                    "original_offset_beats": round(section_relative_offset_beats, 4),
                    "humanized_duration_beats": base_duration,
                    "humanized_offset_beats": round(section_relative_offset_beats, 4),
                    # Restの場合、他のヒューマナイズパラメータはあまり意味をなさない
                }
            else:
                humanized_params = apply_emotional_expression_to_event(
                    base_duration_beats=base_duration,
                    base_offset_beats=section_relative_offset_beats,
                    emotion_profile=emotion_profile_for_section,
                    bpm=bpm
                    # base_velocity は後段のジェネレータが決定する想定
                )
                processed_event = {
                    "chord_symbol_for_voicing": final_chord_symbol_str, # 解釈済みのコードシンボル文字列
                    "specified_bass_for_voicing": specified_bass_str, # 指定されたベース音
                    **humanized_params
                }
            
            processed_event["original_chord_label"] = base_chord_label # 元のラベルも記録
            processed_event["absolute_offset_beats"] = round(current_absolute_offset_beats + section_relative_offset_beats, 4)
            section_output["processed_chord_events"].append(processed_event)
            section_relative_offset_beats += base_duration
        
        output_data["sections"][section_name] = section_output
        if section_data.adjusted_start_beat is None:
             current_absolute_offset_beats += section_relative_offset_beats

    try:
        with Path(output_yaml_path).open("w", encoding="utf-8") as f:
            yaml.safe_dump(output_data, f, allow_unicode=True, sort_keys=False, indent=2)
        logger.info(f"\nSuccessfully processed chordmap and wrote to: {output_yaml_path}")
    except Exception as e:
        print(f"Error writing output YAML to {output_yaml_path}: {e}")

# --- 5. CLI実行部分 ---
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Process chordmap.yaml to apply emotional humanization and output detailed event YAML.")
    parser.add_argument("input_yaml", type=str, help="Path to the input chordmap.yaml file.")
    parser.add_argument("output_yaml", type=str, help="Path for the output processed_chord_events.yaml file.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
    process_chordmap_for_emotion(args.input_yaml, args.output_yaml)