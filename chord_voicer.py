# --- START OF FILE generators/chord_voicer.py (修正版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, interval, tempo, key,
                     chord as m21chord, volume as m21volume)
import random
import logging

# ★★★ core_music_utils から sanitize_chord_label をインポート ★★★
try:
    from .core_music_utils import get_time_signature_object, sanitize_chord_label
except ImportError:
    logger_cv_fallback = logging.getLogger(__name__) # フォールバック用ロガー
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except meter.MeterException:
            logger_cv_fallback.warning(f"CV Fallback GTSO: Invalid TS '{ts_str}'. Default 4/4.")
            return meter.TimeSignature("4/4")
    # ★★★ フォールバック用の sanitize_chord_label (簡易版) ★★★
    def sanitize_chord_label(label: str) -> str:
        logger_cv_fallback.warning(f"CV Fallback sanitize_chord_label used for '{label}'.")
        label = label.replace('maj7', 'M7').replace('mi7', 'm7')
        if label.count('(') > label.count(')') and label.endswith('('):
            label = label[:-1]
        return label
    logger_cv_fallback.warning("ChordVoicer: Could not import from .core_music_utils. Using fallbacks.")


logger = logging.getLogger(__name__)

DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM: int = 3
VOICING_STYLE_CLOSED = "closed"
VOICING_STYLE_OPEN = "open"
VOICING_STYLE_SEMI_CLOSED = "semi_closed"
VOICING_STYLE_DROP2 = "drop2"
VOICING_STYLE_FOUR_WAY_CLOSE = "four_way_close"

class ChordVoicer:
    def __init__(self,
                 default_instrument=m21instrument.StringInstrument(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        # get_time_signature_object の呼び出しは try-except ブロックの外、または ImportError で定義後
        try:
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except NameError: # get_time_signature_object がフォールバックでも定義されていない最悪のケース
             logger.error("ChordVoicer: CRITICAL - get_time_signature_object is not defined. Using basic 4/4.")
             self.global_time_signature_obj = meter.TimeSignature("4/4")
        except Exception as e_ts_init: # その他の初期化時のエラー
            logger.error(f"ChordVoicer: Error initializing time signature '{global_time_signature}': {e_ts_init}. Defaulting to 4/4.")
            self.global_time_signature_obj = meter.TimeSignature("4/4")


    def _apply_voicing_style(
            self,
            m21_cs: Optional[harmony.ChordSymbol], # ★★★ ChordSymbolがNoneの可能性を許容 ★★★
            style_name: str,
            target_octave_for_bottom_note: Optional[int] = DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM,
            num_voices_target: Optional[int] = None
    ) -> List[pitch.Pitch]:
        # ★★★ m21_cs が None の場合は空リストを返す ★★★
        if m21_cs is None:
            return []
        if not m21_cs.pitches:
            logger.warning(f"ChordVoicer._apply_style: ChordSymbol '{m21_cs.figure}' has no pitches.")
            return []

        voiced_pitches_list: List[pitch.Pitch] = []
        original_pitches_sorted = sorted(list(m21_cs.pitches), key=lambda p: p.ps)
        # ★★★ ChordSymbolを直接操作せず、figureから都度生成するか、deepcopyする方が安全 ★★★
        # temp_cs_for_voicing = harmony.ChordSymbol(m21_cs.figure) # 毎回figureから生成

        try:
            # 各ボイシングスタイルで temp_cs_for_voicing を使う代わりに、m21_cs の情報を元に
            # music21のメソッドが返す新しいオブジェクトを使うか、メソッドが inPlace=False であることを確認
            if style_name == VOICING_STYLE_OPEN:
                voiced_pitches_list = list(m21_cs.openPosition(inPlace=False).pitches)
            elif style_name == VOICING_STYLE_SEMI_CLOSED:
                closed_p = sorted(list(m21_cs.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
                if len(closed_p) >= 2:
                    bass_of_cs = m21_cs.bass()
                    if bass_of_cs and closed_p[0].name == bass_of_cs.name:
                        new_bass_p = closed_p[0].transpose(-12)
                        voiced_pitches_list = sorted([new_bass_p] + closed_p[1:], key=lambda p: p.ps)
                    else: voiced_pitches_list = closed_p
                else: voiced_pitches_list = closed_p
            elif style_name == VOICING_STYLE_DROP2:
                closed_for_drop2 = sorted(list(m21_cs.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
                if len(closed_for_drop2) >= 2:
                    idx_to_drop = -1
                    if len(closed_for_drop2) >= 4: idx_to_drop = -2
                    elif len(closed_for_drop2) == 3: idx_to_drop = 1
                    if idx_to_drop != -1 :
                        pitches_copy = list(closed_for_drop2); pitch_to_drop_obj = pitches_copy.pop(idx_to_drop)
                        dropped_pitch_obj = pitch_to_drop_obj.transpose(-12)
                        voiced_pitches_list = sorted(pitches_copy + [dropped_pitch_obj], key=lambda p: p.ps)
                    else: voiced_pitches_list = closed_for_drop2
                else: voiced_pitches_list = closed_for_drop2
            elif style_name == VOICING_STYLE_FOUR_WAY_CLOSE:
                temp_m21_chord = m21chord.Chord(list(m21_cs.pitches)) # 新しいChordオブジェクトを作成
                if len(temp_m21_chord.pitches) >= 4 :
                    try: temp_m21_chord.fourWayClose(inPlace=True); voiced_pitches_list = list(temp_m21_chord.pitches)
                    except Exception as e_4way: logger.warning(f"CV: fourWayClose for {m21_cs.figure} failed: {e_4way}. Defaulting."); voiced_pitches_list = list(m21_cs.closedPosition(inPlace=False).pitches)
                else: logger.debug(f"CV: Not enough pitches for fourWayClose on {m21_cs.figure}. Using closed."); voiced_pitches_list = list(m21_cs.closedPosition(inPlace=False).pitches)
            else: # Default or unknown style
                if style_name != VOICING_STYLE_CLOSED: logger.debug(f"CV: Unknown style '{style_name}'. Defaulting to closed for {m21_cs.figure}.")
                voiced_pitches_list = list(m21_cs.closedPosition(inPlace=False).pitches)
        except Exception as e_style_app:
            logger.error(f"CV._apply_style: Error applying '{style_name}' to '{m21_cs.figure}': {e_style_app}. Defaulting.", exc_info=True)
            voiced_pitches_list = original_pitches_sorted

        if not voiced_pitches_list: voiced_pitches_list = original_pitches_sorted

        if num_voices_target is not None and voiced_pitches_list:
            if len(voiced_pitches_list) > num_voices_target:
                voiced_pitches_list = sorted(voiced_pitches_list, key=lambda p:p.ps)[:num_voices_target]
                logger.debug(f"CV: Reduced voices to {num_voices_target} for '{m21_cs.figure}'.")

        if voiced_pitches_list and target_octave_for_bottom_note is not None:
            # (オクターブ調整ロジックは変更なし)
            current_bottom_p = min(voiced_pitches_list, key=lambda p: p.ps)
            ref_p_name = m21_cs.root().name if m21_cs.root() else 'C'
            target_bottom_ps_val = pitch.Pitch(f"{ref_p_name}{target_octave_for_bottom_note}").ps
            oct_diff = round((target_bottom_ps_val - current_bottom_p.ps) / 12.0)
            shift_semitones = int(oct_diff * 12)
            if shift_semitones != 0:
                logger.debug(f"CV: Shifting '{m21_cs.figure}' by {shift_semitones} semitones for target bottom octave {target_octave_for_bottom_note}.")
                try: voiced_pitches_list = [p.transpose(shift_semitones) for p in voiced_pitches_list]
                except Exception as e_trans: logger.error(f"CV: Error transposing for octave adjustment: {e_trans}")
        return voiced_pitches_list

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        chord_part = stream.Part(id="ChordVoicerPart")
        chord_part.insert(0, self.default_instrument)
        chord_part.append(tempo.MetronomeMark(number=self.global_tempo))
        chord_part.append(self.global_time_signature_obj)

        if not processed_chord_stream: logger.info("CV.compose: Empty stream."); return chord_part
        logger.info(f"CV.compose: Processing {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            offset_ql = float(blk_data.get("offset", 0.0))
            duration_ql = float(blk_data.get("q_length", 4.0))
            chord_label_original = blk_data.get("chord_label", "C")
            
            part_params = blk_data.get("chords_params", blk_data.get("chord_params", {}))
            voicing_style = part_params.get("chord_voicing_style", VOICING_STYLE_CLOSED)
            target_octave = part_params.get("chord_target_octave", DEFAULT_CHORD_TARGET_OCTAVE_BOTTOM)
            num_voices = part_params.get("chord_num_voices")
            chord_velocity = int(part_params.get("chord_velocity", 64))

            logger.debug(f"CV Block {blk_idx+1}: OrigLabel='{chord_label_original}', Style:{voicing_style}, Oct:{target_octave}, Voices:{num_voices}")

            # ★★★ "Rest" の処理とラベル整形 ★★★
            cs_obj: Optional[harmony.ChordSymbol] = None
            is_rest_block = False
            if chord_label_original.lower() in ["rest", "n.c.", "nc", ""]: # 空白もRest扱い
                is_rest_block = True
                logger.info(f"CV Block {blk_idx+1} is a Rest.")
            else:
                sanitized_label = sanitize_chord_label(chord_label_original)
                try:
                    cs_obj = harmony.ChordSymbol(sanitized_label)
                    if not cs_obj.pitches:
                        logger.warning(f"CV: Chord '{sanitized_label}' (orig: '{chord_label_original}') has no pitches. Treating as Rest.")
                        is_rest_block = True
                except harmony.HarmonyException as he:
                    logger.error(f"CV: HarmonyException for chord '{sanitized_label}' (orig: '{chord_label_original}'): {he}. Treating as Rest.")
                    is_rest_block = True
                except Exception as e_cs_cv:
                    logger.error(f"CV: Error creating ChordSymbol for '{sanitized_label}' (orig: '{chord_label_original}'): {e_cs_cv}. Treating as Rest.", exc_info=True)
                    is_rest_block = True
            
            if is_rest_block:
                # ChordVoicer が Rest をどのように扱うか？
                # ここでは単純にこのブロックに何も追加しない、または明示的なRestを追加する
                # (PianoGeneratorのようにRestを生成するならそのロジックを追加)
                # 今回は何も追加しないことで、このブロックは無音になる
                logger.debug(f"CV: Skipping Rest block {blk_idx+1} for ChordVoicer part.")
                continue 

            # この時点で cs_obj は有効な ChordSymbol であるはず
            if not cs_obj : # 万が一のNoneチェック
                logger.error(f"CV: cs_obj is unexpectedly None for label '{chord_label_original}'. Skipping.")
                continue

            # テンション追加ロジックは cs_obj ができてから
            tensions = blk_data.get("tensions_to_add", [])
            if tensions and cs_obj: # cs_obj がNoneでないことを確認
                for t_str in tensions:
                    try: cs_obj.addCustomModification(t_str)
                    except Exception as e_add_tens: logger.warning(f"CV: Tension '{t_str}' to '{cs_obj.figure}' failed: {e_add_tens}")
            
            if not cs_obj.pitches: # テンション追加後にもピッチがあるか確認
                logger.warning(f"CV: No pitches for {cs_obj.figure} after tensions. Skip."); continue

            final_pitches = self._apply_voicing_style(
                cs_obj, voicing_style, # ★★★ cs_obj を渡す ★★★
                target_octave_for_bottom_note=target_octave,
                num_voices_target=num_voices
            )
            if not final_pitches: logger.warning(f"CV: No pitches after voicing for {cs_obj.figure}. Skip."); continue
            
            if final_pitches:
                chord_m21 = m21chord.Chord(final_pitches, quarterLength=duration_ql)
                for n_in_c in chord_m21: n_in_c.volume = m21volume.Volume(velocity=chord_velocity)
                chord_part.insert(offset_ql, chord_m21)
        
        logger.info(f"CV.compose: Finished. Part has {len(chord_part.flatten().notesAndRests)} elements.")
        return chord_part
# --- END OF FILE generators/chord_voicer.py ---
