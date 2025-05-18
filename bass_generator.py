# --- START OF FILE bass_generator.py (Gemini修正案 + 整理版) ---
import music21

from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key)
import random
import logging

logger = logging.getLogger(__name__)
# (メインスクリプトでロガー設定想定)

# --- 定数 ---
DEFAULT_BASS_OCTAVE: int = 2
BASS_STYLE_ROOT_ONLY_WHOLE = "root_only_whole"
BASS_STYLE_ROOT_FIFTH_HALF = "root_fifth_half"
BASS_STYLE_RHYTHMIC_ROOT = "rhythmic_root"
BASS_STYLE_WALKING_QUARTER = "walking_quarter"

# --- ヘルパー関数: スケールオブジェクト構築 (melody_generator_final.py からコピーまたは共通化) ---
def build_scale_object_for_bass(mode_str: str, tonic_str: str) -> Optional[scale.ConcreteScale]:
    if not tonic_str: tonic_str = "C"
    try:
        tonic_p = pitch.Pitch(tonic_str)
        mode_map: Dict[str, Any] = {
            "ionian": scale.MajorScale, "major": scale.MajorScale, "dorian": scale.DorianScale,
            "phrygian": scale.PhrygianScale, "lydian": scale.LydianScale,
            "mixolydian": scale.MixolydianScale, "aeolian": scale.MinorScale,
            "minor": scale.MinorScale, "locrian": scale.LocrianScale,
        }
        scale_class = mode_map.get(mode_str.lower())
        if scale_class: return scale_class(tonic_p)
        logger.warning(f"Bass Scale: Mode '{mode_str}' unknown for '{tonic_str}'. Defaulting to Major.")
        return scale.MajorScale(tonic_p)
    except Exception as e:
        logger.error(f"Bass Scale build error for '{mode_str}' on '{tonic_str}': {e}. Default C Major.", exc_info=True)
        return scale.MajorScale(pitch.Pitch("C"))

class BassGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 default_instrument=m21instrument.AcousticBass(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.rhythm_library = rhythm_library if rhythm_library else {}
        if rhythm_library and "default_4_4_bass_quarter" not in self.rhythm_library :
             self.rhythm_library["default_4_4_bass_quarter"] = {"pattern": [0.0,1.0,2.0,3.0], "durations": [1.0]*4}
             logger.warning("BassGen: Added 'default_4_4_bass_quarter' to rhythm_library.")

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        try:
            self.global_time_signature_obj = meter.TimeSignature(self.global_time_signature_str)
        except meter.MeterException:
            logger.error(f"BassGen: Invalid global TS '{self.global_time_signature_str}'. Defaulting.")
            self.global_time_signature_obj = meter.TimeSignature("4/4")
        self.current_block_scale: Optional[scale.ConcreteScale] = None

    def _get_bass_pitch(self, m21_cs: harmony.ChordSymbol, target_octave: int = DEFAULT_BASS_OCTAVE) -> pitch.Pitch:
        # (Gemini修正案と前回のロジックをベースに整理)
        p_cand = m21_cs.bass() or m21_cs.root()
        if not p_cand:
            logger.warning(f"Bass _get_pitch: No bass/root for {m21_cs.figure}. Default C{target_octave}.")
            return pitch.Pitch(f"C{target_octave}")
        
        p_final = pitch.Pitch(p_cand.name)
        p_final.octave = target_octave
        # 簡単な音域調整
        min_ps = pitch.Pitch(f"E{target_octave-1}").ps
        max_ps = pitch.Pitch(f"A{target_octave+1}").ps # 少し広めに
        while p_final.ps < min_ps and p_final.octave < 4: p_final.octave += 1
        while p_final.ps > max_ps and p_final.octave > 0: p_final.octave -= 1
        return p_final

    def _create_walking_bass_measure(
            self,
            m21_cs_current: harmony.ChordSymbol,
            m21_cs_next: Optional[harmony.ChordSymbol],
            scale_obj: scale.ConcreteScale,
            measure_offset: float,
            # measure_duration: float, # 拍子オブジェクトから取得
            previous_bass_pitch: Optional[pitch.Pitch] = None
    ) -> List[note.Note]:
        notes_in_measure: List[note.Note] = []
        num_beats_in_measure = self.global_time_signature_obj.numerator
        beat_duration_ql = self.global_time_signature_obj.beatDuration.quarterLength

        # 1拍目 (Gemini修正案と前回のロジックをベースに整理)
        p1 = self._get_bass_pitch(m21_cs_current)
        if previous_bass_pitch and abs(p1.ps - previous_bass_pitch.ps) > 7: # 5度以上離れていたら調整
            p1.octave = previous_bass_pitch.octave + (1 if p1.ps < previous_bass_pitch.ps else -1)
            # 再度音域内に収める
            p1 = self._get_bass_pitch(harmony.ChordSymbol(p1.nameWithOctave))


        notes_in_measure.append(note.Note(p1, quarterLength=beat_duration_ql))
        current_p = p1

        # 2,3拍目 (Gemini修正案と前回のロジックをベースに整理)
        for beat_idx in range(1, num_beats_in_measure - 1):
            candidates = []
            # コードトーン (オクターブ調整済み)
            for ct_p_raw in m21_cs_current.pitches:
                ct_p = pitch.Pitch(ct_p_raw.name)
                ct_p.octave = current_p.octave # 近いオクターブに
                if abs(ct_p.ps - current_p.ps) > 6 : ct_p.octave += (1 if ct_p.ps < current_p.ps else -1)
                candidates.append(self._get_bass_pitch(harmony.ChordSymbol(ct_p.nameWithOctave))) # 再度ベース音域に

            # スケール音 (コードトーン以外)
            for sc_p_raw in scale_obj.getPitches(current_p.transpose(-5), current_p.transpose(5)):
                sc_p = self._get_bass_pitch(harmony.ChordSymbol(sc_p_raw.nameWithOctave)) # ベース音域に
                if sc_p not in candidates and sc_p.name not in [p.name for p in candidates]: candidates.append(sc_p)
            
            if not candidates: next_p = current_p
            else:
                smooth_cand = [p_ for p_ in candidates if abs(p_.ps - current_p.ps) <= 4 and p_ != current_p] # 3度以内
                next_p = random.choice(smooth_cand) if smooth_cand else random.choice(candidates)
            
            notes_in_measure.append(note.Note(next_p, quarterLength=beat_duration_ql))
            current_p = next_p

        # 4拍目 (Gemini修正案を適用)
        p_last: pitch.Pitch
        if m21_cs_next and m21_cs_next.root():
            next_root = self._get_bass_pitch(m21_cs_next)
            approach_options = []
            for semitones_from_next_root in [-2, -1, 1, 2]:
                p_app = next_root.transpose(semitones_from_next_root * -1) # 次の音から逆算
                # getScaleDegreeAndAccidentalFromPitch は None を返す可能性があるのでチェック
                degree_info = scale_obj.getScaleDegreeAndAccidentalFromPitch(p_app)
                if degree_info is not None: # スケールに含まれる
                    approach_options.append(p_app)
            if not approach_options: # クロマチックフォールバック
                 approach_options = [next_root.transpose(-1), next_root.transpose(1)]
            p_last = min(approach_options, key=lambda ap: abs(ap.ps - current_p.ps)) if approach_options else p1
        else:
            p_last = p1 # 解決音として1拍目の音
            
        notes_in_measure.append(note.Note(p_last, quarterLength=beat_duration_ql))

        for idx, n_obj in enumerate(notes_in_measure):
            n_obj.offset = measure_offset + (idx * beat_duration_ql)
            n_obj.volume.velocity = 70 + random.randint(-5, 5)
        return notes_in_measure

    def compose(self, processed_chord_stream: List[Dict], style: str = BASS_STYLE_ROOT_FIFTH_HALF) -> stream.Part:
        # (主要なループ構造は維持しつつ、ログ、エラーハンドリング、ウォーキングベース呼び出しを整理)
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        bass_part.append(tempo.MetronomeMark(number=self.global_tempo))
        bass_part.append(self.global_time_signature_obj)

        if not processed_chord_stream:
            logger.info("BassGen.compose: Empty processed_chord_stream. Returning empty part.")
            return bass_part
        logger.info(f"BassGen.compose: Processing {len(processed_chord_stream)} blocks, style: {style}.")
        
        previous_pitch_for_walk: Optional[pitch.Pitch] = None

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            offset_ql = blk_data.get("offset", 0.0)
            duration_ql = blk_data.get("q_length", 4.0)
            chord_label = blk_data.get("chord_label", "C")
            logger.debug(f"Bass Block {blk_idx+1}: {chord_label}, Style:{style}")

            try:
                m21_cs = harmony.ChordSymbol(chord_label)
                if not m21_cs.pitches: logger.warning(f"No pitches for {chord_label}."); continue
                base_p = self._get_bass_pitch(m21_cs)

                if style == BASS_STYLE_WALKING_QUARTER:
                    tonic = blk_data.get("tonic_of_section", m21_cs.root().name if m21_cs.root() else "C")
                    mode = blk_data.get("mode", "ionian")
                    current_scale = build_scale_object_for_bass(mode, tonic)
                    if not current_scale:
                        logger.error(f"BassWalk: No scale for {tonic}{mode}. Fallback to root notes.")
                        for i in range(int(duration_ql)): bass_part.insert(offset_ql + i, note.Note(base_p, quarterLength=1.0))
                        previous_pitch_for_walk = base_p
                        continue

                    num_measures = int(round(duration_ql / self.global_time_signature_obj.barDuration.quarterLength))
                    if num_measures == 0: num_measures = 1

                    for meas_idx in range(num_measures):
                        meas_offset = offset_ql + (meas_idx * self.global_time_signature_obj.barDuration.quarterLength)
                        cs_next: Optional[harmony.ChordSymbol] = None
                        if meas_idx < num_measures -1: cs_next = m21_cs # 同じコード
                        elif blk_idx + 1 < len(processed_chord_stream):
                            try: cs_next = harmony.ChordSymbol(processed_chord_stream[blk_idx+1].get("chord_label","C"))
                            except: pass
                        
                        meas_notes = self._create_walking_bass_measure(
                            m21_cs, cs_next, current_scale, meas_offset, previous_bass_pitch=previous_pitch_for_walk
                        )
                        for n_obj in meas_notes: bass_part.insert(n_obj.offset, n_obj)
                        if meas_notes: previous_pitch_for_walk = meas_notes[-1].pitch
                
                # 他のスタイル (elif で追加)
                # elif style == BASS_STYLE_ROOT_ONLY_WHOLE: ...
                # elif style == BASS_STYLE_ROOT_FIFTH_HALF: ...
                # elif style == BASS_STYLE_RHYTHMIC_ROOT: ...

                else: # デフォルトはルート全音符
                    bass_part.insert(offset_ql, note.Note(base_p, quarterLength=duration_ql))
                    previous_pitch_for_walk = base_p # 次のウォーキングのために設定

            except Exception as e_blk:
                logger.error(f"BassGen: Error in block {blk_idx+1} ('{chord_label}'): {e_blk}", exc_info=True)
        
        logger.info(f"BassGen.compose: Finished. Part has {len(bass_part.flatten().notesAndRests)} elements.")
        return bass_part

# --- END OF FILE bass_generator.py (Gemini修正案 + 整理版) ---