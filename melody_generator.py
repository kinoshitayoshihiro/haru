# --- START OF FILE generators/melody_generator.py ---
import music21

from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key)
import random
import logging

# 共通ユーティリティと定数をインポート
from .core_music_utils import build_scale_object, MIN_NOTE_DURATION_QL, get_time_signature_object

logger = logging.getLogger(__name__)

# --- MelodyGenerator 専用の定数 ---
DEFAULT_MELODY_OCTAVE_RANGE: Tuple[int, int] = (4, 5)  # C4からB5あたり
GUIDE_TONE_DIATONIC_NUMS: Tuple[int, ...] = (1, 3, 5) # スケール度数 (1-indexed)
DEFAULT_MELODY_DENSITY: float = 0.75
DEFAULT_LEAP_ALLOW_PROBABILITY: float = 0.25
DEFAULT_APPROACH_PROBABILITY: float = 0.30
STRONG_BEAT_POSITIONS_4_4: Tuple[float, ...] = (0.0, 2.0) # 4/4拍子での強拍の位置
APPROACH_INTERVAL_SEMITONES: int = 2 # クロマチックアプローチ時の半音数

class MelodyGenerator:
    def __init__(self,
                 rhythm_library: Dict[str, Dict],
                 default_instrument=m21instrument.Flute(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4",
                 global_key_tonic: str = "C",
                 global_key_mode: str = "major"):

        self.rhythm_library = rhythm_library
        # rhythm_libraryに必須のデフォルトリズムパターンがあるか確認・追加
        if "default_melody_4_4" not in self.rhythm_library: # メロディ用のデフォルトキー名
            self.rhythm_library["default_melody_4_4"] = {
                "pattern": [0.0, 1.0, 2.0, 3.0],
                "durations": [1.0, 1.0, 1.0, 1.0], # 各4分音符
                "description": "Default quarter notes for melody (auto-added)"
            }
            logger.warning("MelodyGen: Added 'default_melody_4_4' to rhythm_library.")

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_obj = get_time_signature_object(global_time_signature) # ヘルパー関数使用
        self.global_key_tonic = global_key_tonic
        self.global_key_mode = global_key_mode

        # インスタンス固有の設定値
        self.octave_range = DEFAULT_MELODY_OCTAVE_RANGE
        self.guide_tone_diatonic_nums = GUIDE_TONE_DIATONIC_NUMS
        self.default_density = DEFAULT_MELODY_DENSITY
        self.default_leap_allow_prob = DEFAULT_LEAP_ALLOW_PROBABILITY
        self.default_approach_prob = DEFAULT_APPROACH_PROBABILITY

    def _get_valid_pitches_in_octave_range(
            self,
            pitches_to_filter: Sequence[pitch.Pitch],
            current_scale: Optional[scale.ConcreteScale] = None
    ) -> List[pitch.Pitch]:
        # (このメソッドは前回の「整形・修正案」のものをベースに、ログの調整など)
        valid_pitches: List[pitch.Pitch] = []
        min_oct, max_oct = self.octave_range

        if not pitches_to_filter:
            fallback_tonic = current_scale.tonic if current_scale and current_scale.tonic else pitch.Pitch("C")
            fallback_p = pitch.Pitch(fallback_tonic.name)
            fallback_p.octave = min_oct + (max_oct - min_oct) // 2
            logger.debug(f"MelodyGen._get_valid: Input empty, fallback to {fallback_p.nameWithOctave}")
            return [fallback_p]

        for p_orig in pitches_to_filter:
            if not isinstance(p_orig, pitch.Pitch) or p_orig.name is None:
                logger.warning(f"MelodyGen._get_valid: Invalid Pitch object: {p_orig}")
                continue
            try:
                p_new = pitch.Pitch(p_orig.name)
                if p_new.octave is None:
                    p_new.octave = self.octave_range[0] + (self.octave_range[1] - self.octave_range[0]) // 2
            except Exception as e_create:
                logger.warning(f"MelodyGen._get_valid: Could not create pitch from {p_orig.name}: {e_create}")
                continue
            
            current_oct_for_p = p_new.octave
            while current_oct_for_p < min_oct: current_oct_for_p += 1
            
            p_candidate = pitch.Pitch(p_new.name); p_candidate.octave = current_oct_for_p
            while p_candidate.octave <= max_oct:
                if p_candidate.name == p_new.name: # Ensure only octave changes for the same note name
                    valid_pitches.append(pitch.Pitch(p_candidate.nameWithOctave))
                p_candidate.octave += 1
        
        unique_valid = sorted(list(set(valid_pitches)), key=lambda p: p.ps)
        if not unique_valid:
            logger.warning(f"MelodyGen._get_valid: No valid pitches in range {self.octave_range}. Fallback logic engaged.")
            # Fallback to the closest pitch from the original list, or a default C
            if pitches_to_filter:
                valid_original_pitches = [p for p in pitches_to_filter if isinstance(p, pitch.Pitch) and p.octave is not None]
                if valid_original_pitches:
                    p_closest = min(valid_original_pitches, key=lambda p: abs(p.octave - min_oct))
                    p_adj = pitch.Pitch(p_closest.name)
                    p_adj.octave = max(min_oct, min(max_oct, p_closest.octave))
                    return [p_adj]
            
            fallback_tonic = current_scale.tonic if current_scale and current_scale.tonic else pitch.Pitch("C")
            p_default_fb = pitch.Pitch(fallback_tonic.name)
            p_default_fb.octave = min_oct + (max_oct - min_oct) // 2
            return [p_default_fb]
        return unique_valid

    def _select_pitch(
            self,
            pitch_pool: List[pitch.Pitch], current_chord_tones: List[pitch.Pitch],
            is_strong_beat: bool, previous_pitch: Optional[pitch.Pitch] = None,
            current_scale: Optional[scale.ConcreteScale] = None
    ) -> Optional[pitch.Pitch]:
        # (前回のロジックをベースに、より堅牢に)
        if not pitch_pool:
            logger.warning("MelodyGen._select_pitch: Input pitch_pool is empty. Cannot select pitch.")
            return None

        candidates: List[pitch.Pitch] = []
        if is_strong_beat:
            if current_scale and current_chord_tones:
                try:
                    guides = [p for p in current_chord_tones
                              if current_scale.getScaleDegreeFromPitch(p) in self.guide_tone_diatonic_nums]
                    if guides: candidates.extend(guides)
                except Exception as e_deg: # スケール外の音などが渡された場合
                    logger.debug(f"MelodyGen._select_pitch: Error getting degree for chord tone, likely out of scale: {e_deg}")
            if not candidates and current_chord_tones: # ガイドトーンなければコードトーン全体
                candidates.extend(current_chord_tones)
            if not candidates: # それもなければプール全体
                candidates.extend(pitch_pool)
        else: # 弱拍
            candidates.extend(pitch_pool) # 基本はスケール音

        if not candidates: # 本当に候補がなければフォールバック
            logger.warning("MelodyGen._select_pitch: No candidates found after filtering. Using first of original pool if available.")
            return pitch_pool[0] if pitch_pool else None

        selected_p: pitch.Pitch
        if previous_pitch and random.random() > self.default_leap_allow_prob: # 跳躍制限
            preferred = [p for p in candidates if abs(p.ps - previous_pitch.ps) <= 7] # 完全5度以内
            selected_p = random.choice(preferred) if preferred else random.choice(candidates)
        else: # 初音または跳躍許容
            selected_p = random.choice(candidates)
        
        logger.debug(f"MelodyGen._select_pitch: Selected {selected_p.nameWithOctave} from {len(candidates)} candidates.")
        return selected_p


    def _get_approach_note_pitch(
            self,
            target_pitch: pitch.Pitch, current_scale: scale.ConcreteScale,
            direction: str = "below"
    ) -> Optional[pitch.Pitch]:
        # (Gemini修正案 + 前回のロジック + 堅牢化)
        logger.debug(f"MelodyGen._get_approach: Target {target_pitch.nameWithOctave}, Dir {direction}")
        if not current_scale: logger.warning("MelodyGen._get_approach: No scale provided."); return None
        
        approach_cand: Optional[pitch.Pitch] = None
        try:
            comp_attr = 'name' # オクターブ無視でスケール内の音か判定するため
            if direction == "below":
                approach_cand = current_scale.previous(target_pitch, comparisonAttribute=comp_attr)
                if not approach_cand or approach_cand == target_pitch:
                    approach_cand = target_pitch.transpose(-APPROACH_INTERVAL_SEMITONES)
            elif direction == "above":
                approach_cand = current_scale.next(target_pitch, comparisonAttribute=comp_attr)
                if not approach_cand or approach_cand == target_pitch:
                    approach_cand = target_pitch.transpose(APPROACH_INTERVAL_SEMITONES)
            else: # mixed
                d = random.choice([-1, 1])
                try:
                    # スケールに沿った2度移調を試みる
                    interval_options = [interval.Interval('m2'), interval.Interval('M2')]
                    chosen_interval = random.choice(interval_options)
                    temp_app = current_scale.transposePitch(target_pitch, interval.Interval(d * chosen_interval.semitones))
                    if temp_app and temp_app != target_pitch: approach_cand = temp_app
                    else: approach_cand = target_pitch.transpose(d * APPROACH_INTERVAL_SEMITONES)
                except: # transposePitch が失敗したらクロマチック
                    approach_cand = target_pitch.transpose(d * APPROACH_INTERVAL_SEMITONES)

            if approach_cand:
                # オクターブ範囲調整
                valid_approaches = self._get_valid_pitches_in_octave_range([approach_cand], current_scale)
                if valid_approaches: return valid_approaches[0]
                logger.warning(f"MelodyGen._get_approach: {approach_cand.nameWithOctave} was out of octave range.")
        except Exception as e:
            logger.error(f"MelodyGen._get_approach: Major error for {target_pitch.nameWithOctave}, dir {direction}: {e}", exc_info=True)
        return None # フォールバック

    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        melody_part = stream.Part(id="GeneratedMelody")
        melody_part.insert(0, self.default_instrument)
        melody_part.append(tempo.MetronomeMark(number=self.global_tempo))
        melody_part.append(self.global_time_signature_obj)
        try:
            melody_part.append(key.Key(self.global_key_tonic, self.global_key_mode.lower()))
        except key.KeyException:
            logger.warning(f"MelodyGen: Invalid global key '{self.global_key_tonic} {self.global_key_mode}'. Default C major.")
            melody_part.append(key.Key("C"))
        except Exception as e_glob:
             logger.error(f"MelodyGen: Error setting global elements in part: {e_glob}")


        if not processed_chord_stream:
            logger.info("MelodyGen: Empty processed_chord_stream.")
            return melody_part

        logger.info(f"MelodyGen: Starting composition for {len(processed_chord_stream)} blocks.")
        previous_pitch_obj: Optional[pitch.Pitch] = None

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            offset_ql = blk_data.get("offset", 0.0)
            duration_ql = blk_data.get("q_length", 4.0)
            chord_label = blk_data.get("chord_label", "C")
            logger.debug(f"MelodyBlock {blk_idx+1}/{len(processed_chord_stream)}: {chord_label} @{offset_ql:.2f} for {duration_ql:.2f}qL")

            try:
                m21_cs = harmony.ChordSymbol(chord_label)
                if not m21_cs.pitches: logger.warning(f"Melody: No pitches for {chord_label} in block."); continue
                
                tonic = blk_data.get("tonic_of_section", m21_cs.root().name if m21_cs.root() else "C")
                mode = blk_data.get("mode", "major") # "major" or "ionian"
                current_scale = build_scale_object(mode, tonic)
                if not current_scale: logger.error(f"Melody: No scale for {tonic}{mode}. Skipping block."); continue

                scale_pitches = self._get_valid_pitches_in_octave_range(current_scale.getPitches(), current_scale)
                chord_pitches_from_cs = self._get_valid_pitches_in_octave_range(list(m21_cs.pitches), current_scale)

                if not scale_pitches: scale_pitches = chord_pitches_from_cs if chord_pitches_from_cs else self._get_valid_pitches_in_octave_range([pitch.Pitch("C4")], current_scale)
                if not chord_pitches_from_cs: chord_pitches_from_cs = scale_pitches
                
                rhythm_key_name = blk_data.get("melody_rhythm_key", "default_melody_4_4") # メロディ専用キーを参照
                r_details = self.rhythm_library.get(rhythm_key_name, self.rhythm_library.get("default_melody_4_4"))
                
                r_pattern = r_details.get("pattern", [0.0,1.0,2.0,3.0])
                r_durs = r_details.get("durations")
                r_tuplet_str = r_details.get("tuplet")
                density = blk_data.get("melody_density", self.default_density)

                if not r_pattern: logger.warning(f"Melody: Empty rhythm for key '{rhythm_key_name}'. Skipping block."); continue

                for i, beat_offset_in_pattern in enumerate(r_pattern):
                    note_start_absolute = offset_ql + beat_offset_in_pattern
                    
                    note_len_qtr: float
                    if r_durs and i < len(r_durs): note_len_qtr = r_durs[i]
                    elif i < len(r_pattern) -1: note_len_qtr = r_pattern[i+1] - beat_offset_in_pattern
                    else: # パターンの最後の音
                        bar_dur_ql = self.global_time_signature_obj.barDuration.quarterLength
                        # 小節内での残り、またはブロック全体の残り、の短い方
                        remaining_in_current_bar = bar_dur_ql - beat_offset_in_pattern
                        remaining_in_block = duration_ql - beat_offset_in_pattern
                        note_len_qtr = min(remaining_in_current_bar, remaining_in_block)
                    
                    if note_len_qtr < MIN_NOTE_DURATION_QL / 2.0: continue # 短すぎる音価
                    note_len_qtr = max(MIN_NOTE_DURATION_QL, note_len_qtr) # 最小音価を保証

                    if random.random() > density:
                        melody_part.insert(note_start_absolute, note.Rest(quarterLength=note_len_qtr))
                        continue
                    
                    # 強拍判定 (小節内の位置で)
                    is_strong_beat_val = any(abs(beat_offset_in_pattern - strong_pos) < 0.01 for strong_pos in STRONG_BEAT_POSITIONS_4_4)
                    
                    target_p = self._select_pitch(scale_pitches, chord_pitches_from_cs, is_strong_beat_val, previous_pitch_obj, current_scale)
                    if not target_p: melody_part.insert(note_start_absolute, note.Rest(quarterLength=note_len_qtr)); continue
                    
                    # アプローチノート処理
                    if not is_strong_beat_val and random.random() < self.default_approach_prob and note_len_qtr >= MIN_NOTE_DURATION_QL * 2:
                        app_dir = random.choice(["below", "above"])
                        app_p = self._get_approach_note_pitch(target_p, current_scale, app_dir)
                        if app_p and app_p != target_p:
                            app_q_len = note_len_qtr * 0.33 # 例: アプローチを1/3
                            main_q_len = note_len_qtr - app_q_len
                            app_q_len = max(MIN_NOTE_DURATION_QL/2, app_q_len) # 最小保証
                            main_q_len = max(MIN_NOTE_DURATION_QL/2, main_q_len)

                            note_approach = note.Note(app_p, quarterLength=app_q_len * 0.95) # ややスタッカート
                            note_target = note.Note(target_p, quarterLength=main_q_len * 0.95)
                            
                            melody_part.insert(note_start_absolute, note_approach)
                            melody_part.insert(note_start_absolute + app_q_len, note_target)
                            previous_pitch_obj = target_p
                            logger.debug(f"Melody: Approach {app_p.name} -> {target_p.name} at {note_start_absolute:.2f}")
                            continue
                    
                    # 通常ノート
                    final_melody_note = note.Note(target_p, quarterLength=note_len_qtr * 0.95)
                    if r_tuplet_str:
                        try:
                            act, norm = map(int, r_tuplet_str.split(':'))
                            final_melody_note.duration.appendTuplet(duration.Tuplet(act,norm))
                        except ValueError: logger.warning(f"Melody: Invalid tuplet '{r_tuplet_str}'")
                    
                    melody_part.insert(note_start_absolute, final_melody_note)
                    previous_pitch_obj = target_p
                    logger.debug(f"Melody: Note {target_p.nameWithOctave} at {note_start_absolute:.2f} for {final_melody_note.duration.quarterLength:.2f}qL")

            except Exception as e_block_mel:
                logger.error(f"MelodyGen: Unhandled error in block {blk_idx+1} for chord '{chord_label}': {e_block_mel}", exc_info=True)
        
        logger.info(f"MelodyGen: Composition finished. Melody part has {len(melody_part.flatten().notesAndRests)} elements.")
        return melody_part

# --- END OF FILE generators/melody_generator.py ---