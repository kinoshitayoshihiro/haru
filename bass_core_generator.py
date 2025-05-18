# --- START OF FILE generators/bass_core_generator.py ---
import music21

from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key)
import random
import logging

# 共通ユーティリティと定数をインポート
from .core_music_utils import build_scale_object, MIN_NOTE_DURATION_QL, get_time_signature_object

logger = logging.getLogger(__name__)

# --- BassGenerator 専用の定数 ---
DEFAULT_BASS_OCTAVE: int = 2 # ベースのデフォルトオクターブ (C2あたり)
BASS_STYLE_ROOT_ONLY_WHOLE = "root_only_whole"
BASS_STYLE_ROOT_FIFTH_HALF = "root_fifth_half"
BASS_STYLE_RHYTHMIC_ROOT = "rhythmic_root"
BASS_STYLE_WALKING_QUARTER = "walking_quarter"

class BassCoreGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 default_instrument = m21instrument.AcousticBass(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.rhythm_library = rhythm_library if rhythm_library else {}
        if rhythm_library and "default_bass_quarters" not in self.rhythm_library: # ベース用のデフォルトキー名
             self.rhythm_library["default_bass_quarters"] = {
                 "pattern": [0.0, 1.0, 2.0, 3.0],
                 "durations": [1.0, 1.0, 1.0, 1.0],
                 "description": "Default quarter notes for bass (auto-added)"
             }
             logger.warning("BassCoreGen: Added 'default_bass_quarters' to rhythm_library.")

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        # self.current_block_scale は _create_walking_bass_measure 内で都度生成

    def _get_bass_pitch(self, m21_cs: harmony.ChordSymbol, target_octave: int = DEFAULT_BASS_OCTAVE) -> pitch.Pitch:
        p_cand = m21_cs.bass() or m21_cs.root()
        if not p_cand:
            logger.warning(f"BassCoreGen._get_bass_pitch: No bass/root for {m21_cs.figure}. Defaulting to C{target_octave}.")
            return pitch.Pitch(f"C{target_octave}")
        
        p_final = pitch.Pitch(p_cand.name)
        p_final.octave = target_octave
        
        # ベースとして自然な音域に収める (例: E1 ～ C4 程度)
        min_bass_ps = pitch.Pitch(f"E{target_octave -1}").ps # E1
        max_bass_ps = pitch.Pitch(f"C{target_octave + 2}").ps # C4
        
        while p_final.ps < min_bass_ps and p_final.octave < 3: # 上げすぎない
            p_final.octave += 1
        while p_final.ps > max_bass_ps and p_final.octave > 0: # 下げすぎない
            p_final.octave -= 1
            
        # それでも範囲外ならクリップ (あまり起こらないはずだが念のため)
        if p_final.ps < min_bass_ps : p_final.midi = min_bass_ps
        if p_final.ps > max_bass_ps : p_final.midi = max_bass_ps
        
        return p_final

    def _create_walking_bass_measure(
            self,
            m21_cs_current: harmony.ChordSymbol,
            m21_cs_next: Optional[harmony.ChordSymbol],
            scale_obj: scale.ConcreteScale,
            measure_start_offset: float, # この小節の絶対開始オフセット
            previous_bass_pitch: Optional[pitch.Pitch] = None
    ) -> List[note.Note]:
        notes_in_measure: List[note.Note] = []
        num_beats = self.global_time_signature_obj.numerator # 4/4なら4
        beat_ql = self.global_time_signature_obj.beatDuration.quarterLength # 4/4なら1.0

        if not scale_obj: # スケールがない場合はルート音連打などにフォールバック
            logger.warning("WalkingBass: No scale object provided. Falling back to root notes for the measure.")
            p_root_fallback = self._get_bass_pitch(m21_cs_current)
            for i in range(num_beats):
                n = note.Note(p_root_fallback, quarterLength=beat_ql)
                n.offset = measure_start_offset + (i * beat_ql)
                n.volume.velocity = 70
                notes_in_measure.append(n)
            return notes_in_measure

        # 1拍目: ルート音 (前の音から離れすぎていれば調整)
        p1 = self._get_bass_pitch(m21_cs_current)
        if previous_bass_pitch and abs(p1.ps - previous_bass_pitch.ps) > 9: # 短7度以上離れていたら
            if p1.ps > previous_bass_pitch.ps: p1.octave = previous_bass_pitch.octave + 1 if p1.ps - previous_bass_pitch.ps > 12 else previous_bass_pitch.octave
            else: p1.octave = previous_bass_pitch.octave - 1 if previous_bass_pitch.ps - p1.ps > 12 else previous_bass_pitch.octave
            p1 = self._get_bass_pitch(harmony.ChordSymbol(p1.nameWithOctave)) # 再度音域調整

        notes_in_measure.append(note.Note(p1, quarterLength=beat_ql))
        current_p = p1

        # 2拍目、3拍目 (4/4拍子の場合)
        for beat_num in range(1, num_beats - 1):
            candidates: List[pitch.Pitch] = []
            # コードトーンを候補に (オクターブ調整済み)
            for ct_raw in m21_cs_current.pitches:
                ct = self._get_bass_pitch(harmony.ChordSymbol(ct_raw.nameWithOctave), target_octave=current_p.octave)
                if ct not in candidates: candidates.append(ct)
            # スケール音を候補に (コードトーン以外、近い音域)
            search_range_low = current_p.transpose(-7) # 完全5度下
            search_range_high = current_p.transpose(7) # 完全5度上
            for sc_raw in scale_obj.getPitches(search_range_low, search_range_high):
                sc = self._get_bass_pitch(harmony.ChordSymbol(sc_raw.nameWithOctave), target_octave=current_p.octave)
                if sc.name not in [c.name for c in candidates]: candidates.append(sc) # 音名で重複チェック

            if not candidates: next_p_choice = current_p # 候補なければ前の音
            else:
                # 前の音からスムーズに繋がる音 (3度以内、同じ音は除く)
                smooth_options = [c for c in candidates if abs(c.ps - current_p.ps) <= 4 and c.ps != current_p.ps]
                if smooth_options: next_p_choice = random.choice(smooth_options)
                else: next_p_choice = random.choice([c for c in candidates if c.ps != current_p.ps] or [current_p]) # 同じ音以外、それもなければ今の音
            
            notes_in_measure.append(note.Note(next_p_choice, quarterLength=beat_ql))
            current_p = next_p_choice

        # 最終拍 (4拍目など): 次のコードへのアプローチ
        p_last: pitch.Pitch
        if m21_cs_next and m21_cs_next.root():
            next_root_target = self._get_bass_pitch(m21_cs_next, target_octave=current_p.octave) # 次のルートも今の音域で
            approach_options = []
            for semitones_to_next in [-2, -1, 1, 2]: # 半音または全音でアプローチ
                p_approach_cand = next_root_target.transpose(semitones_to_next * -1) # 次の音から逆算
                degree_info = scale_obj.getScaleDegreeAndAccidentalFromPitch(p_approach_cand)
                if degree_info and degree_info[0] is not None: # スケール内
                    approach_options.append(p_approach_cand)
            
            if not approach_options: # スケール内に良いアプローチがなければクロマチック
                 approach_options = [next_root_target.transpose(-1), next_root_target.transpose(1)]
            
            # 現在の音に最も近いアプローチ音を選択
            if approach_options:
                p_last = min(approach_options, key=lambda ap: abs(ap.ps - current_p.ps))
            else: # アプローチが見つからなければ現在のコードのルートに戻る
                p_last = p1
        else: # 次のコードが不明なら現在のコードのルート
            p_last = p1
            
        notes_in_measure.append(note.Note(p_last, quarterLength=beat_ql))

        # オフセットとベロシティを設定
        for idx, n_obj in enumerate(notes_in_measure):
            n_obj.offset = measure_start_offset + (idx * beat_ql)
            n_obj.volume.velocity = random.randint(65, 80) # ウォーキングベースはやや均一な強さで
        
        logger.debug(f"Walking bass measure at {measure_start_offset:.2f}: {[n.nameWithOctave for n in notes_in_measure]}")
        return notes_in_measure

    def compose(self, processed_chord_stream: List[Dict], style: str = BASS_STYLE_ROOT_FIFTH_HALF) -> stream.Part:
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        bass_part.append(tempo.MetronomeMark(number=self.global_tempo))
        bass_part.append(self.global_time_signature_obj)
        # (キー設定はオプション)

        if not processed_chord_stream:
            logger.info("BassCoreGen: Empty processed_chord_stream.")
            return bass_part
        logger.info(f"BassCoreGen: Starting for {len(processed_chord_stream)} blocks, style: {style}.")
        
        previous_note_final_pitch: Optional[pitch.Pitch] = None

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            offset_ql = blk_data.get("offset", 0.0)
            duration_ql = blk_data.get("q_length", 4.0)
            chord_label = blk_data.get("chord_label", "C")
            block_style = blk_data.get("bass_style", style) # ブロック固有のスタイル指定を優先
            logger.debug(f"BassBlock {blk_idx+1}: {chord_label}, Style: {block_style}")

            try:
                m21_cs = harmony.ChordSymbol(chord_label)
                if not m21_cs.pitches: logger.warning(f"Bass: No pitches for {chord_label}."); continue
                
                base_p_for_block = self._get_bass_pitch(m21_cs)

                if block_style == BASS_STYLE_WALKING_QUARTER:
                    tonic = blk_data.get("tonic_of_section", m21_cs.root().name if m21_cs.root() else "C")
                    mode = blk_data.get("mode", "major")
                    current_scale = build_scale_object(mode, tonic)
                    if not current_scale:
                        logger.error(f"BassWalk: No scale for {tonic}{mode}. Fallback to root notes.")
                        for i in range(int(round(duration_ql / self.global_time_signature_obj.beatDuration.quarterLength))):
                            bass_part.insert(offset_ql + i * self.global_time_signature_obj.beatDuration.quarterLength,
                                             note.Note(base_p_for_block, quarterLength=self.global_time_signature_obj.beatDuration.quarterLength))
                        previous_note_final_pitch = base_p_for_block
                        continue

                    num_measures = int(round(duration_ql / self.global_time_signature_obj.barDuration.quarterLength))
                    num_measures = max(1, num_measures)

                    for meas_idx in range(num_measures):
                        meas_offset = offset_ql + (meas_idx * self.global_time_signature_obj.barDuration.quarterLength)
                        cs_next_cand: Optional[harmony.ChordSymbol] = None
                        # 次の「コードブロック」のコードを見る (小節単位ではなく)
                        if blk_idx + 1 < len(processed_chord_stream):
                            try: cs_next_cand = harmony.ChordSymbol(processed_chord_stream[blk_idx+1].get("chord_label","C"))
                            except: pass
                        elif meas_idx < num_measures -1 : # 同じブロック内で次の小節があるなら、現在のコードが続くとみなす
                            cs_next_cand = m21_cs
                        
                        meas_notes = self._create_walking_bass_measure(
                            m21_cs, cs_next_cand, current_scale, meas_offset,
                            previous_bass_pitch=previous_note_final_pitch
                        )
                        for n_obj in meas_notes: bass_part.insert(n_obj.offset, n_obj)
                        if meas_notes: previous_note_final_pitch = meas_notes[-1].pitch
                
                elif block_style == BASS_STYLE_ROOT_ONLY_WHOLE:
                    bass_part.insert(offset_ql, note.Note(base_p_for_block, quarterLength=duration_ql))
                    previous_note_final_pitch = base_p_for_block
                
                elif block_style == BASS_STYLE_ROOT_FIFTH_HALF and duration_ql >= 1.0:
                    d1 = duration_ql / 2.0; d2 = duration_ql - d1
                    bass_part.insert(offset_ql, note.Note(base_p_for_block, quarterLength=d1))
                    last_p = base_p_for_block
                    if d2 > 0:
                        p5_cand = m21_cs.getChordStep(5) or (m21_cs.root().transpose(interval.PerfectFifth()) if m21_cs.root() else None)
                        if p5_cand:
                            p5 = self._get_bass_pitch(harmony.ChordSymbol(p5_cand.nameWithOctave), target_octave=base_p_for_block.octave)
                            bass_part.insert(offset_ql + d1, note.Note(p5, quarterLength=d2)); last_p = p5
                        else: bass_part.insert(offset_ql + d1, note.Note(base_p_for_block, quarterLength=d2))
                    previous_note_final_pitch = last_p

                elif block_style == BASS_STYLE_RHYTHMIC_ROOT and self.rhythm_library:
                    r_key = blk_data.get("bass_rhythm_key", "default_bass_quarters")
                    r_dets = self.rhythm_library.get(r_key, self.rhythm_library.get("default_bass_quarters"))
                    r_patt = r_dets.get("pattern", [0.0,1.0,2.0,3.0]); r_durs = r_dets.get("durations")
                    
                    last_note_in_pattern_obj: Optional[note.Note] = None
                    for i, b_off in enumerate(r_patt):
                        n_s = offset_ql + b_off; n_ql: float
                        if r_durs and i < len(r_durs): n_ql = r_durs[i]
                        elif i < len(r_patt) - 1: n_ql = r_patt[i+1] - b_off
                        else: n_ql = min(self.global_time_signature_obj.barDuration.quarterLength - b_off, duration_ql - b_off)
                        if n_ql < MIN_NOTE_DURATION_QL / 2.0: continue
                        n_ql = max(MIN_NOTE_DURATION_QL, n_ql)
                        
                        last_note_in_pattern_obj = note.Note(base_p_for_block, quarterLength=n_ql * 0.95) # Slight staccato
                        bass_part.insert(n_s, last_note_in_pattern_obj)
                    previous_note_final_pitch = last_note_in_pattern_obj.pitch if last_note_in_pattern_obj else base_p_for_block
                else: # Default
                    bass_part.insert(offset_ql, note.Note(base_p_for_block, quarterLength=duration_ql))
                    previous_note_final_pitch = base_p_for_block

            except Exception as e_blk_bass:
                logger.error(f"BassCoreGen: Error in block {blk_idx+1} ('{chord_label}'): {e_blk_bass}", exc_info=True)
        
        logger.info(f"BassCoreGen: Finished. Part has {len(bass_part.flatten().notesAndRests)} elements.")
        return bass_part

# --- END OF FILE generators/bass_core_generator.py ---