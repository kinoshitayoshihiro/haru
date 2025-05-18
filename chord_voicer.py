# --- START OF FILE generators/chord_voicer.py ---

import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, interval, tempo, key,
                     chord as m21chord, volume as m21volume, expressions)
import random
import logging

logger = logging.getLogger(__name__)

# --- ChordVoicer 専用の定数 ---
# DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM: int = 3 # デフォルト設定はmodular_composer.pyに移動
VOICING_STYLE_CLOSED = "closed"
VOICING_STYLE_OPEN = "open"
VOICING_STYLE_SEMI_CLOSED = "semi_closed"
VOICING_STYLE_DROP2 = "drop2"
VOICING_STYLE_FOUR_WAY_CLOSE = "four_way_close"


# generator/chord_voicer.py

# 他のimport文など

# 以下の行を追加:
DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM = 3 # もしくは、和音の最低オクターブとして適切な値を指定


class ChordVoicer:
    def __init__(self,
                 default_instrument=m21instrument.Piano(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        try: self.global_time_signature_obj = meter.TimeSignature(global_time_signature)
        except meter.MeterException:
            logger.warning(f"ChordVoicer: Invalid global TS '{global_time_signature}'. Using 4/4.")
            self.global_time_signature_obj = meter.TimeSignature("4/4")
        except Exception as e_ts:
            logger.error(f"ChordVoicer: Error setting TS '{global_time_signature}': {e_ts}. Using 4/4.")
            self.global_time_signature_obj = meter.TimeSignature("4/4")


    def _apply_voicing_style(
            self,
            m21_cs: harmony.ChordSymbol,
            style_name: str,
            target_octave_for_bottom_note: Optional[int] = 3, # コードの最低音の目標オクターブ (C3あたり)
            num_voices_target: Optional[int] = None
    ) -> List[pitch.Pitch]:
        if not m21_cs or not m21_cs.pitches:
            logger.warning(f"CV._apply_style: No pitches for chord '{m21_cs.figure if m21_cs else 'N/A'}'.")
            return []
        
        voiced_pitches: List[pitch.Pitch] = []
        original_pitches = sorted(list(m21_cs.pitches), key=lambda p: p.ps)

        try:
            # ChordSymbolのコピーを操作
            cs_copy = harmony.ChordSymbol(m21_cs.figure)
            if not cs_copy.pitches: cs_copy.pitches = m21_cs.pitches
            
            if style_name == VOICING_STYLE_OPEN:
                voiced_pitches = list(cs_copy.openPosition(inPlace=False).pitches)
            elif style_name == VOICING_STYLE_SEMI_CLOSED:
                # 簡易的なセミクローズドボイシング
                closed_pitches = sorted(list(cs_copy.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
                if len(closed_pitches) >= 3 and cs_copy.bass() and closed_pitches[0].name == cs_copy.bass().name :
                    new_bass = closed_pitches[0].transpose(-12)
                    voiced_pitches = sorted([new_bass] + closed_pitches[1:], key=lambda p:p.ps)
                else: voiced_pitches = closed_pitches
            elif style_name == VOICING_STYLE_DROP2:
                closed_for_drop2 = sorted(list(cs_copy.closedPosition(inPlace=False).pitches), key=lambda p:p.ps)
                if len(closed_for_drop2) >= 2:
                    if len(closed_for_drop2) >= 4: i_to_drop = -2
                    elif len(closed_for_drop2) == 3: i_to_drop = 1
                    else: voiced_pitches = closed_for_drop2; raise StopIteration
                    p_copy = list(closed_for_drop2); p_dropped = p_copy.pop(i_to_drop).transpose(-12); voiced_pitches = sorted(p_copy+[p_dropped], key=lambda p:p.ps)
                else: voiced_pitches = closed_for_drop2

            elif style_name == VOICING_STYLE_FOUR_WAY_CLOSE:
                temp_chord = m21chord.Chord(cs_copy.pitches)
                if len(temp_chord.pitches) >= 4:
                    try: temp_chord.fourWayClose(inPlace=True); voiced_pitches = list(temp_chord.pitches)
                    except: voiced_pitches = list(cs_copy.closedPosition(inPlace=False).pitches)
                else: voiced_pitches = list(cs_copy.closedPosition(inPlace=False).pitches)

            else: # Default (closed)
                if style_name and style_name != VOICING_STYLE_CLOSED: logger.warning(f"CV._apply_style: Unknown style '{style_name}'. Defaulting.")
                voiced_pitches = list(cs_copy.closedPosition(inPlace=False).pitches if cs_copy.pitches else [])

        except StopIteration: pass # Drop2の調整が不要だった場合
        except Exception as e_apply:
            logger.error(f"ChordVoicer: Error applying voicing style '{style_name}' to '{m21_cs.figure if m21_cs else 'N/A'}': {e_apply}. Using sorted original pitches.", exc_info=True)
            voiced_pitches = original_pitches

        if not voiced_pitches: # ボイシング結果が空なら元に戻す
             voiced_pitches = original_pitches
        
        # 声部数調整
        if num_voices_target is not None and voiced_pitches:
            current_num_voices = len(voiced_pitches)
            if current_num_voices > num_voices_target:
                # 重要な音を残して減らすロジック (ルート、3rd、7th など) をここに実装
                # ここでは仮に下から num_voices_target 個だけ取る
                voiced_pitches = voiced_pitches[:num_voices_target]
                logger.debug(f"ChordVoicer: Reduced num of voices from {current_num_voices} to {num_voices_target} for '{m21_cs.figure}'.")

        # target_octave_for_bottom_note があれば、ボイシング結果の音域を調整
        if voiced_pitches and target_octave_for_bottom_note is not None:
            current_bottom_pitch = min(voiced_pitches, key=lambda p: p.ps)
            target_bottom_ps = pitch.Pitch(f"C{target_octave_for_bottom_note}").ps # C音基準にする
            octave_diff = round((target_bottom_ps - current_bottom_pitch.ps) / 12)
            if octave_diff != 0:
                logger.debug(f"ChordVoicer: Shifting voicing by {octave_diff} octaves (semitones={octave_diff*12}) to target bottom octave {target_octave_for_bottom_note}.")
                try:
                    voiced_pitches = [p.transpose(octave_diff*12) for p in voiced_pitches]
                except Exception as e_transpose:
                    logger.error(f"ChordVoicer: Error transposing pitches for octave adjustment: {e_transpose}", exc_info=True)

        return voiced_pitches

    def compose(self,
                processed_chord_stream: List[Dict],
                default_voicing_style: str = VOICING_STYLE_CLOSED, # 文字列で指定
                default_target_octave_bottom: int = DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM # int
                ) -> stream.Part:
        chord_part = stream.Part(id="ChordVoicerPart")
        chord_part.insert(0, self.default_instrument)
        chord_part.append(tempo.MetronomeMark(number=self.global_tempo))
        chord_part.append(self.global_time_signature_obj)

        if not processed_chord_stream:
            logger.info("ChordVoicer.compose: processed_chord_stream is empty. Returning empty part.")
            return chord_part

        logger.info(f"ChordVoicer.compose: Starting for {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            offset_ql = blk_data.get("offset", 0.0)
            duration_ql = blk_data.get("q_length", 4.0)
            chord_label = blk_data.get("chord_label", "C")
            chord_params = blk_data.get("chord_params", {}) # パラメータ

            # パラメータからボイシングスタイル、ターゲットオクターブ、声部数を取得
            # なければモジュールのデフォルト値を使用
            voicing_style_name = chord_params.get("chord_voicing_style", default_voicing_style)
            target_oct_for_block = chord_params.get("chord_target_octave", default_target_octave_bottom)
            num_voices_for_block = chord_params.get("chord_num_voices") # Optional
            chord_vel = chord_params.get("chord_velocity", 64)

            logger.debug(f"ChordVoicer Block {blk_idx+1}: '{chord_label}', Style '{voicing_style_name}', TargetOct '{target_oct_for_block}'")

            try:
                cs = harmony.ChordSymbol(chord_label)
                tensions = blk_data.get("tensions_to_add", [])
                if tensions:
                    logger.debug(f"ChordVoicer: Adding tensions {tensions} to {cs.figure}")
                    for tension_str in tensions:
                        try: # tensions_to_add の内容は addChordStepModification が解釈できる文字列を想定
                            modified_t_str = tension_str[3:] if tension_str.lower().startswith("add") else tension_str
                            if modified_t_str: cs.addChordStepModification(modified_t_str) # ここで追加
                            else: logger.warning(f"ChordVoicer: Invalid tension string '{tension_str}'.")
                        except Exception as e_add_tens:
                            logger.warning(f"ChordVoicer: Could not add tension '{tension_str}' via addChordStepModification: {e_add_tens}")

                if not cs.pitches: logger.warning(f"ChordVoicer: Chord '{chord_label}' has no pitches after init/tensions. Skipping."); continue

                final_voiced_pitches = self._apply_voicing_style(
                    cs, voicing_style_name, target_oct_for_block, num_voices_for_block # 引数名修正済み
                )

                if not final_voiced_pitches: logger.warning(f"ChordVoicer: Voicing returned no pitches for '{chord_label}'."); continue

                # final_register_shift_octaves は _apply_voicing_style の target_octave_for_bottom_note で吸収される想定
                # 必要なら最終的な移調を行う
                # addtional_shift = int(part_params.get("chord_final_register_shift_octaves", 0))
                # if additional_shift != 0: ...

                chord_obj_to_insert = m21chord.Chord(final_voiced_pitches, quarterLength=duration_ql)
                for n in chord_object_to_insert: n.volume = volume.Volume(velocity=chord_vel)
                chord_part.insert(offset_ql, chord_object_to_insert)

            except harmony.HarmonyException as he: # ChordSymbol生成時のエラー
                logger.error(f"ChordVoicer: HarmonyException for chord '{chord_label}' in block {blk_idx+1}: {he}")
            except Exception as e:
                logger.error(f"ChordVoicer.compose: Error in block {blk_idx+1} ('{chord_label}'): {e}", exc_info=True)

        logger.info(f"ChordVoicer.compose: Finished. Part contains {len(chord_part.flatten().notesAndRests)} elements.")
        return chord_part

# --- END OF FILE generators/chord_voicer.py ---