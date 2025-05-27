# --- START OF FILE generator/bass_generator.py (o3さん致命的バグ修正v1) ---
import music21
import logging
from music21 import stream, note, chord as m21chord, harmony, pitch, tempo, meter, instrument as m21instrument, key, interval, scale # scale を追加
import random
from typing import List, Dict, Optional, Any, Tuple, Union, cast, Sequence # Sequence を追加
# ユーティリティ関数や定数のインポート (プロジェクト構成に合わせて調整)
try:
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
    from utilities.scale_registry import ScaleRegistry
except ImportError as e:
    print(f"BassGenerator: Warning - could not import all utilities: {e}")
    MIN_NOTE_DURATION_QL = 0.125 # o3さん指摘: 定数化の検討
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature(ts_str or "4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: return label
    def apply_humanization_to_part(part, template_name=None, custom_params=None): return part
    HUMANIZATION_TEMPLATES = {}
    class ScaleRegistry: # Dummy
        @staticmethod
        def get(tonic_str: Optional[str], mode_str: Optional[str]) -> music21.scale.ConcreteScale: # music21.scale.ConcreteScale を使用
            return music21.scale.MajorScale(tonic_str or "C")


class BassGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 default_instrument: m21instrument.Instrument = m21instrument.AcousticBass(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4",
                 global_key_tonic: str = "C",
                 global_key_mode: str = "major",
                 rng_seed: Optional[int] = None): # o3さん指摘: rng_seed追加
        """
        BassGeneratorのコンストラクタ。ベースパート生成に必要な設定を初期化します。
        (Docstring Google形式に準拠検討)
        """
        self.logger = logging.getLogger(__name__)
        
        self.bass_rhythm_library = rhythm_library if rhythm_library else {}
        if not self.bass_rhythm_library:
            self.logger.warning("BassGenerator: No bass rhythm patterns provided in the rhythm library. Using internal defaults only.")

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        try:
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except Exception as e_ts_init:
            self.logger.error(f"BassGenerator init: Error initializing time signature from '{global_time_signature}': {e_ts_init}. Defaulting to 4/4.", exc_info=True)
            self.global_time_signature_obj = meter.TimeSignature("4/4")

        self.global_key_tonic = global_key_tonic
        self.global_key_mode = global_key_mode
        
        if rng_seed is not None: # o3さん指摘: rng_seed
            self.rng = random.Random(rng_seed)
        else:
            self.rng = random.Random()


        if "basic_chord_tone_quarters" not in self.bass_rhythm_library:
            self.bass_rhythm_library["basic_chord_tone_quarters"] = {
                "description": "Basic quarter note pattern emphasizing root and fifth/third on strong beats.",
                "tags": ["bass", "default", "quarter_notes", "chord_tones"],
                "pattern_type": "algorithmic_chord_tone_quarters", 
                "options": {
                    "base_velocity": 85,
                    "strong_beat_velocity_boost": 15, 
                    "off_beat_velocity_reduction": 5,  
                    "target_octave": 2 
                }
            }
            self.logger.info("BassGenerator: Added 'basic_chord_tone_quarters' algorithmic pattern to internal library.")
        
        if "bass_quarter_notes" not in self.bass_rhythm_library:
            self.bass_rhythm_library["bass_quarter_notes"] = {
                "description": "Default bass line - simple quarter notes on root.",
                "tags": ["bass", "default", "quarter_notes", "root"],
                "pattern": [
                    {"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"},
                    {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"},
                    {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}
                ]
            }
        if "root_only" not in self.bass_rhythm_library:
             self.bass_rhythm_library["root_only"] = {
                "description": "Fallback whole-note roots only.",
                "tags": ["bass", "fallback", "long_notes", "root"],
                "pattern_type": "algorithmic_root_only",
                "pattern": [{"offset": 0.0, "duration": 4.0, "velocity_factor": 0.6}]
            }

    def _get_rhythm_pattern_details(self, rhythm_key: str) -> Dict[str, Any]:
        default_rhythm = self.bass_rhythm_library.get("basic_chord_tone_quarters")
        details = self.bass_rhythm_library.get(rhythm_key)

        if not details:
            self.logger.warning(f"Bass rhythm key '{rhythm_key}' not found. Using 'basic_chord_tone_quarters' as fallback.")
            return default_rhythm if default_rhythm else {}

        if "pattern_type" in details and isinstance(details["pattern_type"], str):
            if "pattern" not in details: 
                details["pattern"] = [] 
        elif "pattern" not in details or not isinstance(details["pattern"], list):
            self.logger.warning(f"Bass rhythm key '{rhythm_key}' has no 'pattern_type' and invalid or missing 'pattern'. Using fallback 'basic_chord_tone_quarters'.")
            return default_rhythm if default_rhythm else {}
        return details

    def _get_bass_pitch_in_octave(self, base_pitch_obj: Optional[pitch.Pitch], target_octave: int) -> int:
        """
        o3さん指摘#3対応: music21内部状態破損の恐れ -> 新しいPitchオブジェクトを返すように変更
        """
        if not base_pitch_obj:
            # フォールバックとしてC音のMIDIノート番号を返す
            return pitch.Pitch(f"C{target_octave}").midi 

        # 新しいPitchオブジェクトを作成して操作する
        p_new = pitch.Pitch(base_pitch_obj.name) 
        p_new.octave = target_octave

        min_bass_midi = 28 # E1
        max_bass_midi = 60 # C4

        current_midi = p_new.midi
        while current_midi < min_bass_midi:
            current_midi += 12
        while current_midi > max_bass_midi:
            if current_midi - 12 >= min_bass_midi:
                current_midi -= 12
            else:
                break 
        
        # 最終的なMIDI値を範囲内にクリップ
        final_midi_pitch = max(min_bass_midi, min(current_midi, max_bass_midi))
        return final_midi_pitch


    def _generate_notes_from_fixed_pattern(
        self,
        pattern: List[Dict[str, Any]],
        m21_cs: harmony.ChordSymbol,
        base_velocity: int,
        target_octave: int,
        block_offset: float,
        block_duration: float, 
        current_scale: Optional[music21.scale.ConcreteScale] = None
    ) -> List[Tuple[float, music21.note.Note]]:
        notes: List[Tuple[float, music21.note.Note]] = []
        if not m21_cs or not m21_cs.pitches:
            return notes

        root_pitch_obj = m21_cs.root()
        third_pitch_obj = m21_cs.third
        fifth_pitch_obj = m21_cs.fifth
        chord_tones = [p for p in [root_pitch_obj, third_pitch_obj, fifth_pitch_obj] if p]

        for p_event in pattern:
            offset_in_block = p_event.get("offset", 0.0)
            duration_ql = p_event.get("duration", 1.0)
            vel_factor = p_event.get("velocity_factor", 1.0)
            note_type = p_event.get("type", "root").lower()

            final_velocity = int(base_velocity * vel_factor)
            final_velocity = max(1, min(127, final_velocity))
            chosen_pitch_base: Optional[pitch.Pitch] = None

            if note_type == "root" and root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "fifth" and fifth_pitch_obj: chosen_pitch_base = fifth_pitch_obj
            # ... (他のnote_typeの処理は変更なし) ...
            elif note_type == "third" and third_pitch_obj: chosen_pitch_base = third_pitch_obj
            elif note_type == "octave_root" and root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "random_chord_tone" and chord_tones: chosen_pitch_base = self.rng.choice(chord_tones)
            elif note_type == "scale_tone" and current_scale:
                try:
                    scale_degree = self.rng.choice([1,2,3,4,5,6,7])
                    p_s = current_scale.pitchFromDegree(scale_degree)
                    if p_s: chosen_pitch_base = p_s
                except Exception:
                     if root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "approach" and root_pitch_obj: chosen_pitch_base = root_pitch_obj.transpose(-1)
            if not chosen_pitch_base and root_pitch_obj: chosen_pitch_base = root_pitch_obj

            if chosen_pitch_base:
                midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave)
                n = music21.note.Note()
                n.pitch.midi = midi_pitch
                n.duration = music21.duration.Duration(duration_ql)
                n.volume.velocity = final_velocity
                if p_event.get("glide_to_next", False): n.tie = music21.tie.Tie("start")
                notes.append((block_offset + offset_in_block, n))
        return notes

    def _generate_algorithmic_pattern(
        self,
        pattern_type: str,
        m21_cs: harmony.ChordSymbol,
        options: Dict[str, Any],
        base_velocity: int,
        target_octave: int,
        block_offset: float,
        block_duration: float,
        current_scale: music21.scale.ConcreteScale
    ) -> List[Tuple[float, music21.note.Note]]:
        notes: List[Tuple[float, music21.note.Note]] = []
        if not m21_cs or not m21_cs.pitches: return notes
        root_note_obj = m21_cs.root()
        if not root_note_obj: return notes

        if pattern_type == "algorithmic_chord_tone_quarters":
            strong_beat_vel_boost = options.get("strong_beat_velocity_boost", 15)
            off_beat_vel_reduction = options.get("off_beat_velocity_reduction", 5)
            
            # o3さん指摘#2.1: 拍子取り扱いの改善
            # beats_per_measure_in_block = int(self.global_time_signature_obj.numerator / self.global_time_signature_obj.denominator * 4)
            beats_per_measure_in_block = self.global_time_signature_obj.beatCount 
            
            num_beats_to_generate = int(block_duration)
            for beat_idx in range(num_beats_to_generate):
                current_beat_offset = beat_idx * 1.0
                if current_beat_offset >= block_duration - MIN_NOTE_DURATION_QL / 2 : break
                chosen_pitch_base: Optional[pitch.Pitch] = None
                current_velocity = base_velocity
                
                # 小節内の拍インデックス (0始まり)
                beat_in_measure = beat_idx % beats_per_measure_in_block

                if beat_in_measure == 0 : # 1拍目 (小節の頭)
                    chosen_pitch_base = root_note_obj
                    current_velocity = min(127, base_velocity + strong_beat_vel_boost)
                # 3拍目の処理を拍子に合わせて調整
                elif beats_per_measure_in_block >= 4 and beat_in_measure == (beats_per_measure_in_block // 2) : # 4/4なら3拍目, 6/8なら4拍目など
                    if m21_cs.fifth: chosen_pitch_base = m21_cs.fifth
                    elif m21_cs.third: chosen_pitch_base = m21_cs.third
                    else: chosen_pitch_base = root_note_obj
                    current_velocity = min(127, base_velocity + (strong_beat_vel_boost // 2))
                else: 
                    chosen_pitch_base = root_note_obj
                    current_velocity = max(1, base_velocity - off_beat_vel_reduction)

                if chosen_pitch_base:
                    midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave)
                    n = music21.note.Note()
                    n.pitch.midi = midi_pitch
                    note_duration_ql = min(1.0, block_duration - current_beat_offset)
                    if note_duration_ql < MIN_NOTE_DURATION_QL: continue
                    n.duration.quarterLength = note_duration_ql
                    n.volume.velocity = current_velocity
                    notes.append((block_offset + current_beat_offset, n))
        
        # ... (algorithmic_root_only, algorithmic_root_fifth は変更なし) ...
        elif pattern_type == "algorithmic_root_only":
            note_duration_ql = options.get("note_duration_ql", block_duration)
            if note_duration_ql <= 0: note_duration_ql = block_duration
            num_notes = int(block_duration / note_duration_ql) if note_duration_ql > 0 else 0
            for i in range(num_notes):
                midi_pitch = self._get_bass_pitch_in_octave(root_note_obj, target_octave)
                n = music21.note.Note(); n.pitch.midi = midi_pitch
                n.duration.quarterLength = note_duration_ql
                n.volume.velocity = base_velocity
                notes.append((block_offset + (i * note_duration_ql), n))

        elif pattern_type == "algorithmic_root_fifth":
            alt_dur_ql = options.get("alternation_duration_ql", block_duration / 2)
            if alt_dur_ql <=0: alt_dur_ql = block_duration / 2
            fifth_pitch_obj = m21_cs.fifth
            current_rel_offset = 0.0; idx = 0
            while current_rel_offset < block_duration - MIN_NOTE_DURATION_QL / 2 :
                note_to_play_base = root_note_obj if idx % 2 == 0 else fifth_pitch_obj
                if not note_to_play_base: note_to_play_base = root_note_obj
                midi_pitch = self._get_bass_pitch_in_octave(note_to_play_base, target_octave)
                n = music21.note.Note(); n.pitch.midi = midi_pitch
                actual_duration = min(alt_dur_ql, block_duration - current_rel_offset)
                if actual_duration < MIN_NOTE_DURATION_QL: break
                n.duration.quarterLength = actual_duration
                n.volume.velocity = base_velocity - (idx % 2) * 5
                notes.append((block_offset + current_rel_offset, n))
                current_rel_offset += actual_duration; idx +=1
        
        elif pattern_type == "algorithmic_walking":
            # ... (このアルゴリズムは複雑なので、o3さんの他の指摘と合わせて後日詳細に見直すのが良いかもしれません) ...
            # 現状は大きな変更なし
            step_ql = options.get("step_duration_ql", 1.0)
            if step_ql <= 0 : step_ql = 1.0
            num_steps = int(block_duration / step_ql) if step_ql > 0 else 0
            last_played_midi_pitch: Optional[int] = None
            scale_pitches_in_octave_range: List[pitch.Pitch] = []
            if current_scale:
                lower_bound_p = pitch.Pitch(f"{current_scale.tonic.name}{target_octave-1}")
                upper_bound_p = pitch.Pitch(f"{current_scale.tonic.name}{target_octave+2}")
                scale_pitches_in_octave_range = current_scale.getPitches(lower_bound_p, upper_bound_p)
            if not scale_pitches_in_octave_range and root_note_obj:
                scale_pitches_in_octave_range = [root_note_obj.transpose(i) for i in [-2,-1,0,1,2,3,4,5]]

            for i in range(num_steps):
                current_rel_offset = i * step_ql
                target_pitch_obj_for_step: Optional[pitch.Pitch] = None
                if i == 0: target_pitch_obj_for_step = root_note_obj
                elif i % 2 == 0:
                    potential_targets = [t for t in [m21_cs.root(), m21_cs.third, m21_cs.fifth] if t]
                    if potential_targets: target_pitch_obj_for_step = self.rng.choice(potential_targets)
                    else: target_pitch_obj_for_step = root_note_obj
                else:
                    if last_played_midi_pitch is not None and scale_pitches_in_octave_range:
                        current_pitch_obj_from_midi = pitch.Pitch(); current_pitch_obj_from_midi.midi = last_played_midi_pitch
                        sorted_scale_pitches = sorted(scale_pitches_in_octave_range, key=lambda p_s: abs(p_s.ps - current_pitch_obj_from_midi.ps))
                        if len(sorted_scale_pitches) > 1: target_pitch_obj_for_step = self.rng.choice(sorted_scale_pitches[:min(3, len(sorted_scale_pitches))])
                        elif sorted_scale_pitches: target_pitch_obj_for_step = sorted_scale_pitches[0]
                        else: target_pitch_obj_for_step = root_note_obj
                    else:
                        if scale_pitches_in_octave_range: target_pitch_obj_for_step = self.rng.choice(scale_pitches_in_octave_range)
                        else: target_pitch_obj_for_step = root_note_obj
                if not target_pitch_obj_for_step: target_pitch_obj_for_step = root_note_obj
                midi_pitch = self._get_bass_pitch_in_octave(target_pitch_obj_for_step, target_octave)
                last_played_midi_pitch = midi_pitch
                n = music21.note.Note(); n.pitch.midi = midi_pitch
                n.duration.quarterLength = step_ql
                n.volume.velocity = base_velocity - self.rng.randint(0, 5)
                notes.append((block_offset + current_rel_offset, n))

        elif pattern_type == "walking_8ths":
            # o3さん指摘#2.2: walking_8ths のスウィング処理とオーバーラン
            swing_ratio = options.get("swing_ratio", 0.0)
            approach_prob = options.get("approach_note_prob", 0.4)
            step_ql = 0.5 # 8分音符
            current_rel_offset = 0.0
            idx = 0
            scale_pitches_objs: List[pitch.Pitch] = []
            if current_scale and current_scale.tonic:
                lower_bound = pitch.Pitch(f"{current_scale.tonic.name}{target_octave-1}")
                upper_bound = pitch.Pitch(f"{current_scale.tonic.name}{target_octave+2}")
                scale_pitches_objs = current_scale.getPitches(lower_bound, upper_bound)
            if not scale_pitches_objs and root_note_obj:
                scale_pitches_objs = [root_note_obj.transpose(i) for i in [-2,-1,0,1,2,3,4,5]]
            if block_duration < step_ql : return notes
            max_iterations = int(block_duration / step_ql) * 2 + 1; loop_count = 0

            # 修正: while current_rel_offset + step_ql <= block_duration ... (ほぼ同じだが、最後のノートがはみ出ないように)
            while current_rel_offset + step_ql <= block_duration + (MIN_NOTE_DURATION_QL / 4) and loop_count < max_iterations:
                note_obj_to_add_pitch: Optional[pitch.Pitch] = None
                vel = base_velocity
                is_approach_note = False
                actual_step_ql = step_ql # スウィングで変動する可能性

                if idx % 2 == 0: 
                    potential_chord_tones = [ct for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth] if ct]
                    if potential_chord_tones: note_obj_to_add_pitch = self.rng.choice(potential_chord_tones)
                    elif root_note_obj: note_obj_to_add_pitch = root_note_obj
                else: 
                    if self.rng.random() < approach_prob and root_note_obj :
                        root_pc = root_note_obj.pitchClass
                        approach_pc_int = (root_pc + self.rng.choice([-1, 1])) % 12
                        note_obj_to_add_pitch = pitch.Pitch(); note_obj_to_add_pitch.pitchClass = approach_pc_int
                        vel = base_velocity - 10; is_approach_note = True
                    else: 
                        if scale_pitches_objs:
                            chord_tone_pcs = [ct.pitchClass for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth, m21_cs.seventh] if ct]
                            non_chord_tones_in_scale = [p_s for p_s in scale_pitches_objs if p_s.pitchClass not in chord_tone_pcs]
                            if non_chord_tones_in_scale: note_obj_to_add_pitch = self.rng.choice(non_chord_tones_in_scale)
                            elif root_note_obj : note_obj_to_add_pitch = root_note_obj
                        elif root_note_obj: note_obj_to_add_pitch = root_note_obj
                        vel = base_velocity - 5
                
                if note_obj_to_add_pitch:
                    midi_pitch = self._get_bass_pitch_in_octave(note_obj_to_add_pitch, target_octave)
                    n = music21.note.Note(); n.pitch.midi = midi_pitch
                    
                    # スウィング適用: 1拍目(idxが偶数)の音価を長く、2拍目(idxが奇数)を短く
                    if swing_ratio > 0 and not is_approach_note:
                        if idx % 2 == 0: # 表拍
                            actual_step_ql = step_ql * (1 + swing_ratio)
                        else: # 裏拍
                            actual_step_ql = step_ql * (1 - swing_ratio)
                    
                    # ブロックの終わりを超えないように音価を調整
                    n.duration.quarterLength = min(actual_step_ql, block_duration - current_rel_offset)
                    if n.duration.quarterLength < MIN_NOTE_DURATION_QL / 2: # 短すぎる場合はスキップ
                        loop_count +=1; continue

                    n.volume.velocity = vel
                    notes.append((block_offset + current_rel_offset, n))
                
                current_rel_offset += actual_step_ql # 実際の音価分進める
                idx += 1; loop_count += 1
            if loop_count >= max_iterations: self.logger.warning(f"BassGen (walking_8ths): Max iterations reached.")

        elif pattern_type == "half_time_pop":
            main_note_duration = block_duration
            p_root = root_note_obj
            midi_p_root = self._get_bass_pitch_in_octave(p_root, target_octave)
            n_main = music21.note.Note(); n_main.pitch.midi = midi_p_root
            n_main.duration.quarterLength = main_note_duration
            n_main.volume.velocity = base_velocity
            notes.append((block_offset, n_main))

            if options.get("ghost_on_beat_2_and_a_half", False) and block_duration >= 2.5: 
                ghost_note_rel_offset = 1.5 
                # o3さん指摘#1: block_abs_offset -> block_offset
                if block_offset + ghost_note_rel_offset < block_offset + block_duration - MIN_NOTE_DURATION_QL / 2 :
                    p_ghost = root_note_obj 
                    midi_p_ghost = self._get_bass_pitch_in_octave(p_ghost, target_octave)
                    n_ghost = music21.note.Note(); n_ghost.pitch.midi = midi_p_ghost
                    n_ghost.duration.quarterLength = 0.25 
                    n_ghost.volume.velocity = int(base_velocity * 0.6)
                    notes.append((block_offset + ghost_note_rel_offset, n_ghost))
        
        # ... (syncopated_rnb, scale_walk, octave_jump, descending_fifths, pedal_tone は大きな変更なし。ただし、scale_walkの初期インデックスは注意) ...
        elif pattern_type == "syncopated_rnb":
            base_offsets_16th = options.get("pattern_16th_offsets", [0, 3, 6, 10, 13])
            ghost_ratio = options.get("ghost_velocity_ratio", 0.5); note_dur_ql = 0.25
            for sixteenth_offset_idx in base_offsets_16th:
                rel_offset_ql = sixteenth_offset_idx * 0.25
                if rel_offset_ql >= block_duration - MIN_NOTE_DURATION_QL / 2: continue
                potential_tones = [ct for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth, m21_cs.seventh] if ct]
                chosen_tone_base = self.rng.choice(potential_tones) if potential_tones else root_note_obj
                midi_pitch = self._get_bass_pitch_in_octave(chosen_tone_base, target_octave)
                n = music21.note.Note(); n.pitch.midi = midi_pitch; n.duration.quarterLength = note_dur_ql
                is_ghost = self.rng.random() < 0.3
                n.volume.velocity = int(base_velocity * ghost_ratio) if is_ghost else base_velocity
                notes.append((block_offset + rel_offset_ql, n))

        elif pattern_type == "scale_walk":
            # o3さん指摘#2.3: scale_walk 初期インデックス
            current_pitch_idx = 0 # デフォルトを与える
            resolution_ql = options.get("note_resolution_ql", 0.5)
            if resolution_ql <= 0: resolution_ql = 0.5
            direction = options.get("direction", "up_down"); max_range_octs = options.get("max_range_octaves", 1)
            num_steps = int(block_duration / resolution_ql) if resolution_ql > 0 else 0
            scale_pitches_objs_for_walk: List[pitch.Pitch] = []
            if current_scale and current_scale.tonic:
                lower_oct = target_octave - (max_range_octs // 2)
                upper_oct = target_octave + (max_range_octs - max_range_octs // 2) +1
                scale_pitches_objs_for_walk = current_scale.getPitches(pitch.Pitch(f"{current_scale.tonic.name}{lower_oct}"), pitch.Pitch(f"{current_scale.tonic.name}{upper_oct}"))
            if not scale_pitches_objs_for_walk and root_note_obj:
                scale_pitches_objs_for_walk = [root_note_obj.transpose(i) for i in [-2,-1,0,1,2]]
            if not scale_pitches_objs_for_walk:
                 if root_note_obj: scale_pitches_objs_for_walk = [root_note_obj]
                 else: return notes
            current_p_resolved = root_note_obj
            try:
                initial_pitch_candidates = [p_s for p_s in scale_pitches_objs_for_walk if p_s.pitchClass == current_p_resolved.pitchClass]
                if initial_pitch_candidates:
                    # ここで current_pitch_idx を設定
                    current_pitch_idx_in_candidates = min(range(len(initial_pitch_candidates)), key=lambda i: abs(initial_pitch_candidates[i].ps - self._get_bass_pitch_in_octave(current_p_resolved, target_octave)))
                    # scale_pitches_objs_for_walk全体でのインデックスを見つける
                    current_p_resolved = initial_pitch_candidates[current_pitch_idx_in_candidates]
                    current_pitch_idx = scale_pitches_objs_for_walk.index(current_p_resolved)

                else: 
                    current_pitch_idx = min(range(len(scale_pitches_objs_for_walk)), key=lambda i: abs(scale_pitches_objs_for_walk[i].ps - self._get_bass_pitch_in_octave(current_p_resolved, target_octave)))
            except (ValueError, IndexError): # .indexが見つからない場合や空リストの場合
                current_pitch_idx = 0 # 安全なフォールバック
            
            dir_modifier = 1
            for i in range(num_steps):
                if not (0 <= current_pitch_idx < len(scale_pitches_objs_for_walk)): # インデックス範囲チェック
                    self.logger.warning(f"scale_walk: current_pitch_idx {current_pitch_idx} out of bounds for scale_pitches_objs_for_walk (len {len(scale_pitches_objs_for_walk)}). Resetting to 0.")
                    current_pitch_idx = 0 # 安全な値にリセット
                    if not scale_pitches_objs_for_walk: break # スケール音がないならループ終了

                selected_pitch_obj = scale_pitches_objs_for_walk[current_pitch_idx]
                midi_pitch = self._get_bass_pitch_in_octave(selected_pitch_obj, target_octave)
                n = music21.note.Note(); n.pitch.midi = midi_pitch; n.duration.quarterLength = resolution_ql
                n.volume.velocity = base_velocity - self.rng.randint(0,3)
                notes.append((block_offset + i * resolution_ql, n))
                if direction == "up": current_pitch_idx = (current_pitch_idx + 1) % len(scale_pitches_objs_for_walk)
                elif direction == "down": current_pitch_idx = (current_pitch_idx - 1 + len(scale_pitches_objs_for_walk)) % len(scale_pitches_objs_for_walk)
                elif direction == "up_down":
                    if dir_modifier == 1 and current_pitch_idx >= len(scale_pitches_objs_for_walk) -1 : dir_modifier = -1
                    elif dir_modifier == -1 and current_pitch_idx <= 0 : dir_modifier = 1
                    current_pitch_idx = (current_pitch_idx + dir_modifier + len(scale_pitches_objs_for_walk)) % len(scale_pitches_objs_for_walk)
        
        elif pattern_type == "octave_jump":
            jump_offsets = options.get("pattern_offsets_ql", [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5])
            accent_boost = options.get("accent_velocity_boost", 10); note_dur_ql = options.get("note_duration_ql", 0.5)
            if note_dur_ql <=0: note_dur_ql = 0.5
            for i, rel_offset_ql in enumerate(jump_offsets):
                if rel_offset_ql >= block_duration - MIN_NOTE_DURATION_QL / 2: continue
                target_oct_for_jump = target_octave if i % 2 == 0 else target_octave + 1
                midi_pitch = self._get_bass_pitch_in_octave(root_note_obj, target_oct_for_jump)
                n = music21.note.Note(); n.pitch.midi = midi_pitch; n.duration.quarterLength = note_dur_ql
                n.volume.velocity = base_velocity if i % 2 == 0 else base_velocity - accent_boost // 2
                notes.append((block_offset + rel_offset_ql, n))

        elif pattern_type == "descending_fifths":
            resolution_ql = options.get("note_resolution_ql", 1.0)
            if resolution_ql <=0: resolution_ql = 1.0
            num_steps = int(min(block_duration, options.get("length_beats", 4)) / resolution_ql) if resolution_ql > 0 else 0
            current_p_obj = root_note_obj
            for i in range(num_steps):
                midi_pitch = self._get_bass_pitch_in_octave(current_p_obj, target_octave)
                n = music21.note.Note(); n.pitch.midi = midi_pitch; n.duration.quarterLength = resolution_ql
                n.volume.velocity = base_velocity
                notes.append((block_offset + i * resolution_ql, n))
                current_p_obj = current_p_obj.transpose(interval.Interval('-P5')) # 5度下げる (P4ではなく)

        elif pattern_type == "pedal_tone":
            pedal_type = options.get("pedal_choice", "tonic").lower(); pedal_note_p: Optional[pitch.Pitch] = None
            if pedal_type == "tonic" and current_scale and current_scale.tonic: pedal_note_p = current_scale.tonic
            elif pedal_type == "dominant" and current_scale:
                dom_p = current_scale.pitchFromDegree(5)
                if dom_p : pedal_note_p = dom_p
            if pedal_note_p:
                midi_pitch = self._get_bass_pitch_in_octave(pedal_note_p, target_octave)
                n = music21.note.Note(); n.pitch.midi = midi_pitch; n.duration.quarterLength = block_duration
                n.volume.velocity = base_velocity
                notes.append((block_offset, n))
            else: 
                default_algo_options = self.bass_rhythm_library["basic_chord_tone_quarters"]["options"]
                notes.extend(self._generate_algorithmic_pattern("algorithmic_chord_tone_quarters", m21_cs, default_algo_options, base_velocity, target_octave, block_offset, block_duration, current_scale))
        else:
            default_algo_options = self.bass_rhythm_library["basic_chord_tone_quarters"]["options"]
            notes.extend(self._generate_algorithmic_pattern("algorithmic_chord_tone_quarters", m21_cs, default_algo_options, base_velocity, target_octave, block_offset, block_duration, current_scale))
        return notes

    def compose(self, processed_blocks: Sequence[Dict[str, Any]], return_pretty_midi: bool = False) -> Union[stream.Part, Any]:
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        # o3さん指摘#2: 二重挿入の可能性 -> humanize後にチェックするが、そもそも最初に一度だけ入れる
        # MetronomeMark と TimeSignature は Stream の先頭に一度だけ挿入するのが一般的
        if self.global_tempo:
             bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        if self.global_time_signature_obj:
             ts_clone = meter.TimeSignature(self.global_time_signature_obj.ratioString)
             bass_part.insert(0, ts_clone)
        else:
             bass_part.insert(0, meter.TimeSignature("4/4")) # フォールバック

        if processed_blocks:
            first_block_tonic = processed_blocks[0].get("tonic_of_section", self.global_key_tonic)
            first_block_mode = processed_blocks[0].get("mode", self.global_key_mode)
            try:
                # KeySignatureも一度だけ先頭に
                if not bass_part.getElementsByClass(key.Key).first():
                    bass_part.insert(0, key.Key(first_block_tonic, first_block_mode.lower()))
            except Exception as e_key_insert:
                 self.logger.error(f"BassGen compose: Failed to insert key {first_block_tonic} {first_block_mode}: {e_key_insert}. Using global default.", exc_info=True)
                 if not bass_part.getElementsByClass(key.Key).first(): # 再度チェック
                    bass_part.insert(0, key.Key(self.global_key_tonic, self.global_key_mode.lower()))
        
        part_overall_humanize_params = None
        for blk_idx, blk_data in enumerate(processed_blocks):
            bass_params_for_block = blk_data.get("part_params", {}).get("bass", {})
            if not bass_params_for_block: continue
            if blk_idx == 0: 
                part_overall_humanize_params = {
                    "humanize_opt": bass_params_for_block.get("humanize_opt", True),
                    "template_name": bass_params_for_block.get("template_name", "default_subtle"),
                    "custom_params": bass_params_for_block.get("custom_params", {})
                }
            chord_label_str = blk_data.get("chord_label", "C")
            block_q_length = blk_data.get("q_length", 4.0)
            block_abs_offset = blk_data.get("offset", 0.0)
            m21_cs_obj: Optional[harmony.ChordSymbol] = None
            sanitized_label : Optional[str] = None
            try:
                sanitized_label = sanitize_chord_label(chord_label_str)
                if sanitized_label and sanitized_label.lower() != "rest":
                    m21_cs_obj = harmony.ChordSymbol(sanitized_label) # o3さん指摘: LRUキャッシュ検討箇所
                    if not m21_cs_obj.pitches: m21_cs_obj = None
            except Exception: m21_cs_obj = None # パースエラーはまとめてここでキャッチ
            
            if not m21_cs_obj and (not sanitized_label or sanitized_label.lower() != "rest"): continue
            if m21_cs_obj is None and sanitized_label and sanitized_label.lower() == "rest": continue

            rhythm_key_from_params = bass_params_for_block.get("rhythm_key", bass_params_for_block.get("bass_rhythm_key"))
            if not rhythm_key_from_params:
                rhythm_key_from_params = bass_params_for_block.get("style", "basic_chord_tone_quarters") 
            pattern_details = self._get_rhythm_pattern_details(rhythm_key_from_params)
            if not pattern_details: continue

            base_vel = bass_params_for_block.get("velocity", 70) # chordmapからの値
            target_oct = bass_params_for_block.get("octave", 2)  # chordmapからの値
            
            section_tonic = blk_data.get("tonic_of_section", self.global_key_tonic)
            section_mode = blk_data.get("mode", self.global_key_mode)
            current_m21_scale = ScaleRegistry.get(section_tonic, section_mode)
            if not current_m21_scale: current_m21_scale = music21.scale.MajorScale("C")

            generated_notes_for_block: List[Tuple[float, music21.note.Note]] = []
            if m21_cs_obj:
                if "pattern_type" in pattern_details and isinstance(pattern_details["pattern_type"], str):
                    algo_options = pattern_details.get("options", {})
                    # chordmapからの値をアルゴリズムオプションに優先的に反映
                    algo_options["base_velocity"] = base_vel
                    algo_options["target_octave"] = target_oct
                    
                    generated_notes_for_block = self._generate_algorithmic_pattern(
                        pattern_details["pattern_type"], m21_cs_obj, algo_options,
                        base_vel, target_oct, block_abs_offset, block_q_length, current_m21_scale
                    )
                elif "pattern" in pattern_details and isinstance(pattern_details["pattern"], list):
                    generated_notes_for_block = self._generate_notes_from_fixed_pattern(
                        pattern_details["pattern"], m21_cs_obj, base_vel, target_oct,
                        block_abs_offset, block_q_length, current_m21_scale
                    )
            for abs_note_offset, note_obj in generated_notes_for_block:
                if abs_note_offset < block_abs_offset: abs_note_offset = block_abs_offset
                end_of_note = abs_note_offset + note_obj.duration.quarterLength
                end_of_block = block_abs_offset + block_q_length
                if end_of_note > end_of_block + 0.001: 
                    new_dur = end_of_block - abs_note_offset
                    if new_dur > MIN_NOTE_DURATION_QL / 2: note_obj.duration.quarterLength = new_dur
                    else: continue

                                    # === Haruさん確認用ログ追加 START ===
                    if m21_cs_obj: # m21_cs_objがNoneでないことを確認
                        self.logger.info(f"DEBUG Bass Insert: Chord='{m21_cs_obj.figure}', BlockOffset={block_abs_offset:.2f}, NoteAbsOffset={abs_note_offset:.2f}, Pitch={note_obj.pitch.nameWithOctave if note_obj.pitch else 'N/A'}, Duration={note_obj.duration.quarterLength:.2f}")
                    else:
                        self.logger.info(f"DEBUG Bass Insert (No Chord): BlockOffset={block_abs_offset:.2f}, NoteAbsOffset={abs_note_offset:.2f}, Pitch={note_obj.pitch.nameWithOctave if note_obj.pitch else 'N/A'}, Duration={note_obj.duration.quarterLength:.2f}")
                    # === Haruさん確認用ログ追加 END ===
                if note_obj.duration.quarterLength >= MIN_NOTE_DURATION_QL / 2:
                     bass_part.insert(abs_note_offset, note_obj)

        if part_overall_humanize_params and part_overall_humanize_params.get("humanize_opt", False):
            try:
                bass_part_humanized = apply_humanization_to_part(
                    bass_part, # 元のパートを渡す
                    template_name=part_overall_humanize_params.get("template_name"),
                    custom_params=part_overall_humanize_params.get("custom_params")
                )
                # humanize関数が新しいStreamを返す場合、IDや楽器情報を再設定
                if isinstance(bass_part_humanized, stream.Part):
                    bass_part_humanized.id = "Bass" # ID再設定
                    # 重要な要素が欠けていないか確認し、必要なら追加
                    if not bass_part_humanized.getElementsByClass(m21instrument.Instrument).first():
                        bass_part_humanized.insert(0, self.default_instrument)
                    # o3さん指摘#2: MetronomeMark/TimeSignature/Key はhumanize後には追加しない方針
                    # (humanize関数がこれらを保持/複製することを期待。もしクリアされるならhumanize側の修正が必要)
                    bass_part = bass_part_humanized
                else:
                    self.logger.warning("Humanization did not return a music21.stream.Part. Using original.")
            except Exception as e_hum:
                self.logger.error(f"BassGen: Error during bass part humanization: {e_hum}", exc_info=True)

        if return_pretty_midi: return None # 未実装
        return bass_part

# --- END OF FILE generator/bass_generator.py ---
