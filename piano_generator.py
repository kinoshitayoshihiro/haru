# --- START OF FILE generators/piano_generator.py ---
import music21

from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key,
                     chord as m21chord, expressions, volume) # volume をインポート
import random
import logging

try:
    from .core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object
except ImportError:
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: # Optional を追加
        if not ts_str: ts_str = "4/4"
        try: return meter.TimeSignature(ts_str)
        except meter.MeterException:
            logging.getLogger(__name__).warning(f"Fallback get_time_signature_object: Invalid TS '{ts_str}'. Defaulting to 4/4.")
            return meter.TimeSignature("4/4")
        except Exception as e_ts_fb:
            logging.getLogger(__name__).error(f"Fallback get_time_signature_object: Error for TS '{ts_str}': {e_ts_fb}. Defaulting to 4/4.")
            return meter.TimeSignature("4/4")
    logging.warning("PianoGen: Could not import from .core_music_utils. Using fallbacks.")

logger = logging.getLogger(__name__)

# --- PianoGenerator 専用の定数 ---
PIANO_STYLE_BLOCK_CHORDS = "block_chords"
PIANO_STYLE_ARPEGGIO_RH_LH_BASS = "arpeggio_rh_lh_bass"
PIANO_STYLE_LH_BASS_RH_CHORD = "lh_bass_rh_chord"
PIANO_STYLE_ALBERTI_BASS_RH_CHORD = "alberti_bass_rh_chord"
PIANO_STYLE_RHYTHMIC_COMPING = "rhythmic_comping"

DEFAULT_PIANO_LH_OCTAVE: int = 2
DEFAULT_PIANO_RH_OCTAVE: int = 4

class PianoGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 chord_voicer_instance: Optional[Any] = None,
                 default_instrument_rh=m21instrument.Piano(),
                 default_instrument_lh=m21instrument.Piano(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.rhythm_library = rhythm_library if rhythm_library is not None else {}
        default_piano_key = "default_piano_quarters"
        if default_piano_key not in self.rhythm_library:
             self.rhythm_library[default_piano_key] = {
                 "pattern": [
                     {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.8},
                     {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.75},
                     {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.8},
                     {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.75}
                 ], "description": "Default quarter notes (auto-added)"}
             logger.info(f"PianoGen: Added '{default_piano_key}' to rhythm_library.")
        fallback_key = "piano_fallback_block"
        if fallback_key not in self.rhythm_library:
            self.rhythm_library[fallback_key] = {
                "pattern": [{"offset":0.0, "duration":get_time_signature_object(global_time_signature).barDuration.quarterLength, "velocity_factor":0.7}],
                "description": "Fallback single block chord (auto-added)"}
            logger.info(f"PianoGen: Added '{fallback_key}' to rhythm_library.")

        self.chord_voicer = chord_voicer_instance
        if not self.chord_voicer:
            logger.warning("PianoGen: No ChordVoicer instance provided. Voicing will use basic internal logic.")

        self.instrument_rh = default_instrument_rh
        self.instrument_lh = default_instrument_lh
        self.global_tempo = global_tempo
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _get_piano_chord_pitches(
            self, m21_cs: harmony.ChordSymbol, num_voices: Optional[int],
            target_octave_bottom: int, voicing_style_name: str
    ) -> List[pitch.Pitch]:
        final_num_voices = num_voices if num_voices is not None and num_voices > 0 else 4 # デフォルト4声

        if self.chord_voicer and hasattr(self.chord_voicer, '_apply_voicing_style'):
            try:
                return self.chord_voicer._apply_voicing_style(
                    m21_cs,
                    voicing_style_name,
                    target_octave_for_bottom_note=target_octave_bottom, # ChordVoicer側の引数名に合わせる
                    num_voices_target=final_num_voices                 # ChordVoicer側の引数名に合わせる
                )
            except TypeError as te:
                logger.error(f"PianoGen: TypeError calling ChordVoicer for '{m21_cs.figure if m21_cs else 'N/A'}': {te}. "
                             f"Ensure ChordVoicer._apply_voicing_style args match. Using simple voicing.", exc_info=True)
            except Exception as e_cv:
                 logger.warning(f"PianoGen: Error using ChordVoicer for '{m21_cs.figure if m21_cs else 'N/A'}': {e_cv}. Simple voicing.", exc_info=True)
        
        logger.debug(f"PianoGen: Using simple internal voicing for '{m21_cs.figure if m21_cs else 'N/A'}'.")
        if not m21_cs or not m21_cs.pitches: return []
        try:
            temp_chord = m21_cs.closedPosition(inPlace=False)
            if not temp_chord.pitches: return []
            
            current_bottom = min(temp_chord.pitches, key=lambda p: p.ps)
            root_name = m21_cs.root().name if m21_cs.root() else 'C'
            target_bottom_ps = pitch.Pitch(f"{root_name}{target_octave_bottom}").ps
            oct_shift = round((target_bottom_ps - current_bottom.ps) / 12.0)
            voiced_pitches = sorted([p.transpose(oct_shift * 12) for p in temp_chord.pitches], key=lambda p: p.ps)
            
            if len(voiced_pitches) > final_num_voices:
                # ピアノの場合、トップノートを残しつつ下から削るか、単純に下から取るかなど
                # ここでは簡易的に下から final_num_voices を取る
                return voiced_pitches[:final_num_voices]
            return voiced_pitches
        except Exception as e_simple:
            logger.warning(f"PianoGen: Simple voicing failed for '{m21_cs.figure if m21_cs else 'N/A'}': {e_simple}. Returning raw.", exc_info=True)
            raw_p_list = sorted(list(m21_cs.pitches), key=lambda p_sort: p_sort.ps)
            return raw_p_list[:final_num_voices] if raw_p_list else []

    def _apply_pedal_to_part(self, part_to_apply_pedal: stream.Part, block_offset: float, block_duration: float):
        if block_duration > 0.25:
            pedal_on_expr = expressions.TextExpression("Ped.")
            pedal_off_expr = expressions.TextExpression("*")
            pedal_on_time = block_offset + 0.01
            pedal_off_time = block_offset + block_duration - 0.05
            if pedal_off_time > pedal_on_time:
                part_to_apply_pedal.insert(pedal_on_time, pedal_on_expr)
                part_to_apply_pedal.insert(pedal_off_time, pedal_off_expr)

    def _generate_piano_hand_part_for_block(
            self, hand_LR: str,
            m21_cs: harmony.ChordSymbol,
            block_offset_ql: float,
            block_duration_ql: float,
            hand_specific_params: Dict[str, Any]
    ) -> List[Tuple[float, music21.Music21Object]]:
        # (このメソッドのロジックは、前回の「修正案」をベースに、
        #  リズムキーが見つからない場合のフォールバックを強化し、
        #  ベロシティ設定で music21.volume.Volume を使うようにします。)
        # (長いので主要な修正ポイントのみ記載し、前回提示のコードをベースに修正してください)
        elements_with_offsets: List[Tuple[float, music21.Music21Object]] = []
        rhythm_key = hand_specific_params.get(f"piano_{hand_LR.lower()}_rhythm_key")
        velocity = int(hand_specific_params.get(f"piano_velocity_{hand_LR.lower()}", 64))
        # ... (他のパラメータ取得) ...
        perform_style = hand_specific_params.get(f"piano_{hand_LR.lower()}_style_keyword", "block_chord")

        rhythm_details = self.rhythm_library.get(rhythm_key) if rhythm_key else None
        if not rhythm_details or "pattern" not in rhythm_details:
            logger.warning(f"Piano{hand_LR}: Rhythm key '{rhythm_key}' invalid. Using fallback 'piano_fallback_block'.")
            rhythm_details = self.rhythm_library.get("piano_fallback_block") # より安全なフォールバック
        
        r_pattern_events = rhythm_details.get("pattern", [{"offset":0.0, "duration":block_duration_ql, "velocity_factor":1.0}])
        # ... (base_voiced_pitches_hand の取得) ...
        # ... (r_pattern_events のループ) ...
        #       n_arp.volume = volume.Volume(velocity=...)
        #       for n_hit in rh_chord_hit: n_hit.volume = volume.Volume(velocity=...)
        #       element_to_add.volume = volume.Volume(velocity=...)
        # (このメソッドの完全な実装は、前回の修正案を参照し、上記の注意点を適用してください)
        # (前回提示した _generate_piano_rh_part_for_block / _generate_piano_lh_part_for_block の内容を
        #  この1つのメソッドに統合し、hand_LR で分岐する形になります)
        # (以下、主要な構造を再掲・修正)
        voicing_style = hand_specific_params.get(f"piano_{hand_LR.lower()}_voicing_style", "closed")
        target_octave = int(hand_specific_params.get(f"piano_{hand_LR.lower()}_target_octave", DEFAULT_PIANO_RH_OCTAVE if hand_LR == "RH" else DEFAULT_PIANO_LH_OCTAVE))
        num_voices = int(hand_specific_params.get(f"piano_{hand_LR.lower()}_num_voices", 3 if hand_LR == "RH" else 1))
        arp_note_ql = float(hand_specific_params.get("piano_arp_note_ql", 0.5))

        base_voiced_pitches = self._get_piano_chord_pitches(m21_cs, num_voices, target_octave, voicing_style)
        if not base_voiced_pitches: return []

        for event_params in r_pattern_events:
            event_offset = float(event_params.get("offset", 0.0))
            event_dur = float(event_params.get("duration", self.global_time_signature_obj.beatDuration.quarterLength))
            event_vf = float(event_params.get("velocity_factor", 1.0))
            abs_start = block_offset_ql + event_offset
            actual_dur = min(event_dur, block_duration_ql - event_offset)
            if actual_dur < MIN_NOTE_DURATION_QL / 4.0: continue
            current_vel = int(velocity * event_vf)

            if "arpeggio" in perform_style.lower() and hand_LR == "RH":
                # (アルペジオ生成ロジック ... volume.Volume を使用)
                pass
            else: # ブロックコードまたはLH
                pitches_to_play = base_voiced_pitches
                if hand_LR == "LH":
                    lh_event_type = event_params.get("type", "root").lower()
                    lh_base_p_cand = min(base_voiced_pitches, key=lambda p:p.ps) if base_voiced_pitches else pitch.Pitch(f"C{DEFAULT_PIANO_LH_OCTAVE}")
                    # (LHのピッチ選択ロジック ...)
                    pitches_to_play = [lh_base_p_cand] # 仮
                
                if pitches_to_play:
                    obj: music21.Music21Object
                    if len(pitches_to_play) == 1:
                        obj = note.Note(pitches_to_play[0], quarterLength=actual_dur * 0.9)
                        obj.volume = volume.Volume(velocity=current_vel)
                    else:
                        obj = m21chord.Chord(pitches_to_play, quarterLength=actual_dur * 0.9)
                        for n_ in obj: n_.volume = volume.Volume(velocity=current_vel)
                    elements_with_offsets.append((abs_start, obj))
        return elements_with_offsets


    def compose(self, processed_chord_stream: List[Dict]) -> stream.Score:
        piano_score = stream.Score(id="PianoScore")
        piano_rh_part = stream.Part(id="PianoRH"); piano_rh_part.insert(0, self.instrument_rh)
        piano_lh_part = stream.Part(id="PianoLH"); piano_lh_part.insert(0, self.instrument_lh)
        piano_score.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        piano_score.insert(0, self.global_time_signature_obj)

        if not processed_chord_stream: logger.info("PianoGen: Empty stream."); piano_score.append([piano_rh_part, piano_lh_part]); return piano_score
        logger.info(f"PianoGen: Starting for {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset = float(blk_data.get("offset", 0.0))
            block_duration = float(blk_data.get("q_length", 4.0))
            chord_label = blk_data.get("chord_label", "C")
            piano_params = blk_data.get("piano_params", {}) # modular_composerから渡される
            logger.debug(f"PianoBlock {blk_idx+1}: '{chord_label}', Offset {block_offset:.2f}, Params: {piano_params}")
            try:
                cs = harmony.ChordSymbol(chord_label)
                if not cs.pitches: logger.warning(f"PianoGen: No pitches for {chord_label}."); continue
                
                rh_elements = self._generate_piano_hand_part_for_block("RH", cs, block_offset, block_duration, piano_params)
                for offset_val, el_val in rh_elements: piano_rh_part.insert(offset_val, el_val)

                lh_elements = self._generate_piano_hand_part_for_block("LH", cs, block_offset, block_duration, piano_params)
                for offset_val, el_val in lh_elements: piano_lh_part.insert(offset_val, el_val)
                
                if piano_params.get("piano_apply_pedal", True):
                    self._apply_pedal_to_part(piano_lh_part, block_offset, block_duration) # LHパートにペダルマーク
            except Exception as e:
                logger.error(f"PianoGen: Error in block {blk_idx+1} ('{chord_label}'): {e}", exc_info=True)

        piano_score.append(piano_rh_part); piano_score.append(piano_lh_part)
        logger.info(f"PianoGen: Finished. RH notes: {len(piano_rh_part.flatten().notes)}, LH notes: {len(piano_lh_part.flatten().notes)}")
        return piano_score

# --- END OF FILE generators/piano_generator.py ---