# --- START OF FILE generator/bass_generator.py (ユーザー指摘反映版) ---
import music21
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
    MIN_NOTE_DURATION_QL = 0.125
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
                 rng: Optional[random.Random] = None):
        self.logger = logging.getLogger(__name__)
        self.rhythm_library_all = rhythm_library if rhythm_library else {}
        self.bass_rhythm_library = self.rhythm_library_all.get("bass_lines",
                                                            self.rhythm_library_all.get("bass_patterns", {}))
        if not self.bass_rhythm_library:
            self.logger.warning("BassGenerator: 'bass_lines' or 'bass_patterns' not found in rhythm_library. Using empty.")

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
        self.rng = rng if rng else random.Random()

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
            self.logger.info("BassGenerator: Added 'bass_quarter_notes' to internal bass_rhythm_library.")
        if "root_only" not in self.bass_rhythm_library:
             self.bass_rhythm_library["root_only"] = {
                "description": "Fallback whole-note roots only.",
                "tags": ["bass", "fallback", "long_notes", "root"],
                "pattern_type": "algorithmic_root_only",
                "pattern": [{"offset": 0.0, "duration": 4.0, "velocity_factor": 0.6}]
            }
             self.logger.info("BassGenerator: Added 'root_only' fallback to internal bass_rhythm_library.")

    def _get_rhythm_pattern_details(self, rhythm_key: str) -> Dict[str, Any]:
        default_rhythm = self.bass_rhythm_library.get("bass_quarter_notes")
        details = self.bass_rhythm_library.get(rhythm_key)

        if not details:
            self.logger.warning(f"Bass rhythm key '{rhythm_key}' not found. Using 'bass_quarter_notes' as fallback.")
            return default_rhythm if default_rhythm else {}

        if "pattern_type" in details and isinstance(details["pattern_type"], str):
            if "pattern" not in details:
                details["pattern"] = []
        elif "pattern" not in details or not isinstance(details["pattern"], list):
            self.logger.warning(f"Bass rhythm key '{rhythm_key}' has no 'pattern_type' and invalid or missing 'pattern'. Using fallback 'bass_quarter_notes'.")
            return default_rhythm if default_rhythm else {}
        return details

    def _generate_notes_from_fixed_pattern(
        self,
        pattern: List[Dict[str, Any]],
        m21_cs: harmony.ChordSymbol,
        base_velocity: int,
        target_octave: int,
        block_offset: float,
        block_duration: float, # block_duration はこの関数内では直接使用しないが、整合性のため残す
        current_scale: Optional[music21.scale.ConcreteScale] = None
    ) -> List[Tuple[float, music21.note.Note]]:
        notes: List[Tuple[float, music21.note.Note]] = []
        if not m21_cs or not m21_cs.pitches:
            self.logger.warning(f"BassGen (FixedPattern): ChordSymbol '{m21_cs.figure if m21_cs else 'None'}' is invalid or has no pitches. Skipping.")
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

            chosen_pitch_base: Optional[pitch.Pitch] = None # オクターブ未調整のピッチ

            if note_type == "root" and root_pitch_obj:
                chosen_pitch_base = root_pitch_obj
            elif note_type == "fifth" and fifth_pitch_obj:
                chosen_pitch_base = fifth_pitch_obj
            elif note_type == "third" and third_pitch_obj:
                chosen_pitch_base = third_pitch_obj
            elif note_type == "octave_root" and root_pitch_obj:
                chosen_pitch_base = root_pitch_obj # オクターブ調整は後段
            elif note_type == "random_chord_tone" and chord_tones:
                chosen_pitch_base = self.rng.choice(chord_tones)
            elif note_type == "scale_tone" and current_scale:
                try:
                    scale_degree = self.rng.choice([1,2,3,4,5,6,7])
                    p = current_scale.pitchFromDegree(scale_degree)
                    if p: chosen_pitch_base = p
                except Exception as e_sf_scale:
                     self.logger.warning(f"BassGen (FixedPattern): Error getting scale tone for {note_type}: {e_sf_scale}. Fallback to root.")
                     if root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "approach" and root_pitch_obj:
                chosen_pitch_base = root_pitch_obj.transpose(-1) # 半音下

            if not chosen_pitch_base and root_pitch_obj:
                chosen_pitch_base = root_pitch_obj
                self.logger.debug(f"BassGen (FixedPattern): Could not determine pitch for type '{note_type}', using root.")

            if chosen_pitch_base:
                # ピッチオブジェクトを作成し、ターゲットオクターブに調整
                final_pitch_obj = pitch.Pitch(chosen_pitch_base.name) # オクターブ情報なしで名前だけ取得
                final_pitch_obj.octave = target_octave
                if note_type == "octave_root": # octave_root の場合のみ1オクターブ上げる
                    final_pitch_obj = final_pitch_obj.transpose(12)


                n = music21.note.Note(final_pitch_obj) # ここでPitchオブジェクトを渡す
                n.duration = music21.duration.Duration(duration_ql)
                n.volume.velocity = final_velocity
                if p_event.get("glide_to_next", False):
                    n.tie = music21.tie.Tie("start")
                notes.append((block_offset + offset_in_block, n))
            else:
                self.logger.warning(f"BassGen (FixedPattern): Could not create note for event {p_event} (chord: {m21_cs.figure}).")
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
        if not m21_cs or not m21_cs.pitches:
            self.logger.warning(f"BassGen (Algo): ChordSymbol '{m21_cs.figure if m21_cs else 'None'}' is invalid or has no pitches. Skipping for {pattern_type}.")
            return notes

        root_note_obj = m21_cs.root()
        if not root_note_obj:
            self.logger.warning(f"BassGen (Algo): Could not get root for chord '{m21_cs.figure}'. Skipping for {pattern_type}.")
            return notes
        # root_pitch_class は使わずに root_note_obj (Pitchオブジェクト) を主体に扱う

        self.logger.info(f"BassGen (Algo): Generating '{pattern_type}' for chord '{m21_cs.figure}', scale: {current_scale.name if current_scale else 'N/A'}, opts: {options}")

        if pattern_type == "algorithmic_root_only":
            note_duration_ql = options.get("note_duration_ql", block_duration)
            if note_duration_ql <= 0: note_duration_ql = block_duration # 安全策
            num_notes = int(block_duration / note_duration_ql) if note_duration_ql > 0 else 0

            for i in range(num_notes):
                p = pitch.Pitch(root_note_obj.name) # NameからPitchオブジェクト作成
                p.octave = target_octave
                n = music21.note.Note(p)
                n.duration.quarterLength = note_duration_ql
                n.volume.velocity = base_velocity
                notes.append((block_offset + (i * note_duration_ql), n))

        elif pattern_type == "algorithmic_root_fifth":
            alt_dur_ql = options.get("alternation_duration_ql", block_duration / 2)
            if alt_dur_ql <=0: alt_dur_ql = block_duration / 2 # 安全策
            fifth_pitch_obj = m21_cs.fifth
            current_rel_offset = 0.0
            idx = 0
            while current_rel_offset < block_duration - MIN_NOTE_DURATION_QL / 2 : # 終了条件微調整
                note_to_play_base = root_note_obj if idx % 2 == 0 else fifth_pitch_obj
                if not note_to_play_base: note_to_play_base = root_note_obj

                p = pitch.Pitch(note_to_play_base.name)
                p.octave = target_octave
                n = music21.note.Note(p)

                actual_duration = min(alt_dur_ql, block_duration - current_rel_offset)
                if actual_duration < MIN_NOTE_DURATION_QL: break
                n.duration.quarterLength = actual_duration
                n.volume.velocity = base_velocity - (idx % 2) * 5
                notes.append((block_offset + current_rel_offset, n))
                current_rel_offset += actual_duration
                idx +=1

        elif pattern_type == "algorithmic_walking":
            step_ql = options.get("step_duration_ql", 1.0)
            if step_ql <= 0 : step_ql = 1.0 # 安全策
            approach_type = options.get("approach_type", "diatonic").lower()
            num_steps = int(block_duration / step_ql) if step_ql > 0 else 0
            last_played_pitch_obj: Optional[pitch.Pitch] = None

            scale_pitches_in_octave_range = current_scale.getPitches(
                pitch.Pitch(f"{current_scale.tonic.name}{target_octave-1}"),
                pitch.Pitch(f"{current_scale.tonic.name}{target_octave+1}")
            ) if current_scale else []


            for i in range(num_steps):
                current_rel_offset = i * step_ql
                target_pitch_for_step: Optional[pitch.Pitch] = None

                if i == 0:
                    target_pitch_for_step = root_note_obj
                elif i % 2 == 0: # 強拍 (ここでは簡易的に偶数番目)
                    potential_targets = [t for t in [m21_cs.root(), m21_cs.third, m21_cs.fifth] if t]
                    if potential_targets: target_pitch_for_step = self.rng.choice(potential_targets)
                else: # 弱拍
                    if scale_pitches_in_octave_range:
                        # 前の音からの距離が近いスケール音を選ぶなどのロジック
                        if last_played_pitch_obj:
                            # last_played_pitch_objに近いスケール音を探す (簡易版)
                            # 実際はより洗練された選択ロジックが必要
                            distances = [(abs(p.ps - last_played_pitch_obj.ps), p) for p in scale_pitches_in_octave_range]
                            distances.sort(key=lambda x: x[0])
                            if distances : target_pitch_for_step = distances[0][1] # 最も近い音 (インターバル考慮なし)
                        else:
                            target_pitch_for_step = self.rng.choice(scale_pitches_in_octave_range)

                if not target_pitch_for_step: target_pitch_for_step = root_note_obj

                p = pitch.Pitch(target_pitch_for_step.name) # Pitchオブジェクトを作成
                p.octave = target_octave # target_octaveに合わせる
                # ターゲットピッチがtarget_octaveから遠い場合、近づける
                while p.ps < pitch.Pitch(f"C{target_octave}").ps - 6: p.transpose(12, inPlace=True)
                while p.ps > pitch.Pitch(f"C{target_octave+1}").ps + 6: p.transpose(-12, inPlace=True)


                n = music21.note.Note(p)
                n.duration.quarterLength = step_ql
                n.volume.velocity = base_velocity - self.rng.randint(0, 5)
                notes.append((block_offset + current_rel_offset, n))
                last_played_pitch_obj = p

        elif pattern_type == "walking_8ths":
            swing_ratio = options.get("swing_ratio", 0.0)
            approach_prob = options.get("approach_note_prob", 0.4)
            step_ql = 0.5
            current_rel_offset = 0.0
            idx = 0

            # スケール音を取得 (オクターブ範囲を指定)
            scale_pitches_objs: List[pitch.Pitch] = []
            if current_scale and current_scale.tonic: # スケールが存在し、トニックもある場合
                # ベースに適したオクターブ範囲のスケール音を取得
                # 例えば、target_octaveとその上下の音を含むように
                # これはScaleRegistry側でより便利なメソッドを用意するのも手
                lower_bound = pitch.Pitch(f"{current_scale.tonic.name}{target_octave-1}")
                upper_bound = pitch.Pitch(f"{current_scale.tonic.name}{target_octave+2}") # 少し広めに
                scale_pitches_objs = current_scale.getPitches(lower_bound, upper_bound)
            if not scale_pitches_objs and root_note_obj: # フォールバック
                scale_pitches_objs = [root_note_obj.transpose(i) for i in [-2,-1,0,1,2]]


            # 無限ループ防止: block_duration が非常に小さい場合
            if block_duration < step_ql :
                self.logger.warning(f"BassGen (walking_8ths): block_duration {block_duration} is too short for step_ql {step_ql}. Skipping.")
                return notes
            
            max_iterations = int(block_duration / step_ql) * 2 # 念のため
            loop_count = 0


            while current_rel_offset < block_duration - (step_ql / 2.0) and loop_count < max_iterations:
                note_obj_to_add_pitch: Optional[pitch.Pitch] = None
                vel = base_velocity
                is_approach_note = False

                if idx % 2 == 0: # ダウンビート相当
                    potential_chord_tones = [ct for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth] if ct]
                    if potential_chord_tones:
                        chosen_tone_base = self.rng.choice(potential_chord_tones)
                        note_obj_to_add_pitch = pitch.Pitch(chosen_tone_base.name) # Nameから
                        note_obj_to_add_pitch.octave = target_octave
                    elif root_note_obj: # フォールバック
                        note_obj_to_add_pitch = pitch.Pitch(root_note_obj.name)
                        note_obj_to_add_pitch.octave = target_octave
                else: # オフビート相当
                    if self.rng.random() < approach_prob and root_note_obj : # ルート音がある場合のみアプローチ試行
                        # 半音下/上からのクロマチックアプローチ
                        # ルート音のピッチクラスに対してアプローチ
                        root_pc = root_note_obj.pitchClass
                        approach_pc_int = (root_pc + self.rng.choice([-1, 1])) % 12
                        
                        note_obj_to_add_pitch = pitch.Pitch(approach_pc_int) # 整数ピッチクラスからPitchオブジェクト生成
                        note_obj_to_add_pitch.octave = target_octave
                        # アプローチノートのオクターブがルートから離れすぎないように調整
                        if abs(note_obj_to_add_pitch.ps - root_note_obj.transpose(12*(target_octave - root_note_obj.octave)).ps) > 6:
                             # ルートと同じオクターブか、近いオクターブに
                             dist_to_target_oct_root = note_obj_to_add_pitch.ps - pitch.Pitch(f"{root_note_obj.name}{target_octave}").ps
                             note_obj_to_add_pitch.transpose(-12 * round(dist_to_target_oct_root/12.0), inPlace=True)

                        vel = base_velocity - 10
                        is_approach_note = True
                    else: # スケール音
                        if scale_pitches_objs:
                            # コードトーン以外のスケール音を選択
                            chord_tone_pcs = [ct.pitchClass for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth, m21_cs.seventh] if ct]
                            non_chord_tones_in_scale = [p for p in scale_pitches_objs if p.pitchClass not in chord_tone_pcs]
                            if non_chord_tones_in_scale:
                                note_obj_to_add_pitch = self.rng.choice(non_chord_tones_in_scale)
                                # オクターブは target_octave に近いものを scale_pitches_objs から選んでいるはず
                            elif root_note_obj : # フォールバック
                                note_obj_to_add_pitch = pitch.Pitch(root_note_obj.name) # Nameから
                                note_obj_to_add_pitch.octave = target_octave
                        elif root_note_obj: # スケール音も取れない場合の最終フォールバック
                            note_obj_to_add_pitch = pitch.Pitch(root_note_obj.name) # Nameから
                            note_obj_to_add_pitch.octave = target_octave
                        vel = base_velocity - 5

                if note_obj_to_add_pitch:
                    n = music21.note.Note(note_obj_to_add_pitch) # Pitchオブジェクトを渡す
                    n.duration.quarterLength = step_ql
                    n.volume.velocity = vel
                    notes.append((block_offset + current_rel_offset, n))

                current_rel_offset += step_ql
                if swing_ratio > 0 and not is_approach_note and idx % 2 == 0 :
                     delay = step_ql * swing_ratio
                     current_rel_offset += delay
                idx += 1
                loop_count += 1
            if loop_count >= max_iterations:
                self.logger.warning(f"BassGen (walking_8ths): Max iterations reached for block. Check loop conditions.")


        elif pattern_type == "half_time_pop":
            main_note_duration = block_duration
            ghost_added = False
            if options.get("ghost_on_beat_2_and_a_half", False) and block_duration > 2.5: # 2.5拍以上ないとゴーストは入れにくい
                 main_note_duration = block_duration - 0.5 # ゴーストの分を考慮 (厳密にはタイミングによる)

            p_root = pitch.Pitch(root_note_obj.name)
            p_root.octave = target_octave
            n_main = music21.note.Note(p_root)
            n_main.duration.quarterLength = main_note_duration
            n_main.volume.velocity = base_velocity
            notes.append((block_offset, n_main))

            if options.get("ghost_on_beat_2_and_a_half", False) and block_duration > 2.5:
                ghost_note_rel_offset = 1.5 # 4/4拍子の2拍目の裏 (0-indexedで1.5拍目)
                # 拍子によって調整
                if self.global_time_signature_obj.beatCount == 3 and ghost_note_rel_offset >= block_duration - 0.25:
                     ghost_note_rel_offset = 1.0 # 3/4なら2拍目頭

                if block_offset + ghost_note_rel_offset < block_offset + block_duration - 0.25: # ブロック内に収まるか
                    p_ghost = pitch.Pitch(root_note_obj.name)
                    p_ghost.octave = target_octave
                    n_ghost = music21.note.Note(p_ghost)
                    n_ghost.duration.quarterLength = 0.25 # 16分など短い音
                    n_ghost.volume.velocity = int(base_velocity * 0.6)
                    notes.append((block_offset + ghost_note_rel_offset, n_ghost))

        # ... (他のアルゴリズムパターンの実装も同様に root_note_obj のチェックと pitch.Pitch() を使うように修正) ...
        elif pattern_type == "syncopated_rnb":
            base_offsets_16th = options.get("pattern_16th_offsets", [0, 3, 6, 10, 13])
            ghost_ratio = options.get("ghost_velocity_ratio", 0.5)
            note_dur_ql = 0.25

            for sixteenth_offset_idx in base_offsets_16th:
                rel_offset_ql = sixteenth_offset_idx * 0.25
                if rel_offset_ql >= block_duration: continue

                potential_tones = [ct for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth, m21_cs.seventh] if ct]
                chosen_tone_base = self.rng.choice(potential_tones) if potential_tones else root_note_obj
                
                p = pitch.Pitch(chosen_tone_base.name)
                p.octave = target_octave
                n = music21.note.Note(p)
                n.duration.quarterLength = note_dur_ql
                is_ghost = self.rng.random() < 0.3
                n.volume.velocity = int(base_velocity * ghost_ratio) if is_ghost else base_velocity
                notes.append((block_offset + rel_offset_ql, n))

        elif pattern_type == "scale_walk":
            resolution_ql = options.get("note_resolution_ql", 0.5)
            if resolution_ql <= 0: resolution_ql = 0.5
            direction = options.get("direction", "up_down")
            max_range_octs = options.get("max_range_octaves", 1)
            num_steps = int(block_duration / resolution_ql) if resolution_ql > 0 else 0
            
            # scale_pitches_in_octave = [p.pitchClass for p in current_scale.getPitches(target_octave*12, (target_octave+max_range_octs)*12 -1)]
            # より安全にスケール音を取得
            scale_pitches_objs_for_walk: List[pitch.Pitch] = []
            if current_scale and current_scale.tonic:
                lower_oct = target_octave - (max_range_octs // 2)
                upper_oct = target_octave + (max_range_octs - max_range_octs // 2) +1 # +1 for range end
                scale_pitches_objs_for_walk = current_scale.getPitches(
                    pitch.Pitch(f"{current_scale.tonic.name}{lower_oct}"),
                    pitch.Pitch(f"{current_scale.tonic.name}{upper_oct}")
                )
            if not scale_pitches_objs_for_walk and root_note_obj: # フォールバック
                scale_pitches_objs_for_walk = [root_note_obj.transpose(i * 12 + j) for i in range(-(max_range_octs//2), max_range_octs - (max_range_octs//2) +1) for j in [0,2,4,5,7,9,11]]


            if not scale_pitches_objs_for_walk: # それでも空ならルートだけ
                 if root_note_obj:
                     p_root_target_oct = pitch.Pitch(root_note_obj.name)
                     p_root_target_oct.octave = target_octave
                     scale_pitches_objs_for_walk = [p_root_target_oct]
                 else: return notes # ルートもないなら終了

            # 現在のピッチをスケール内で探す
            current_p_resolved = pitch.Pitch(root_note_obj.name) # Nameから
            current_p_resolved.octave = target_octave

            # scale_pitches_objs_for_walk の中から current_p_resolved に最も近いものを見つける
            try:
                current_pitch_idx = min(range(len(scale_pitches_objs_for_walk)), key=lambda i: abs(scale_pitches_objs_for_walk[i].ps - current_p_resolved.ps))
            except ValueError: # scale_pitches_objs_for_walk が空の場合
                return notes


            dir_modifier = 1

            for i in range(num_steps):
                selected_pitch = scale_pitches_objs_for_walk[current_pitch_idx]
                n = music21.note.Note(selected_pitch) # Pitchオブジェクトを渡す
                # オクターブは selected_pitch に含まれているはず
                n.duration.quarterLength = resolution_ql
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
            accent_boost = options.get("accent_velocity_boost", 10)
            note_dur_ql = options.get("note_duration_ql", 0.5)
            if note_dur_ql <=0: note_dur_ql = 0.5

            for i, rel_offset_ql in enumerate(jump_offsets):
                if rel_offset_ql >= block_duration: continue
                
                p = pitch.Pitch(root_note_obj.name) # Nameから
                p.octave = target_octave if i % 2 == 0 else target_octave + 1
                n = music21.note.Note(p)
                n.duration.quarterLength = note_dur_ql
                n.volume.velocity = base_velocity if i % 2 == 0 else base_velocity - accent_boost // 2
                notes.append((block_offset + rel_offset_ql, n))

        elif pattern_type == "descending_fifths":
            resolution_ql = options.get("note_resolution_ql", 1.0)
            if resolution_ql <=0: resolution_ql = 1.0
            num_steps = int(min(block_duration, options.get("length_beats", 4)) / resolution_ql) if resolution_ql > 0 else 0
            current_p = pitch.Pitch(root_note_obj.name) # Nameから
            current_p.octave = target_octave

            for i in range(num_steps):
                n = music21.note.Note(current_p) # Pitchオブジェクトを渡す
                n.duration.quarterLength = resolution_ql
                n.volume.velocity = base_velocity
                notes.append((block_offset + i * resolution_ql, n))
                current_p.transpose(interval.Interval('-P4'), inPlace=True)


        elif pattern_type == "pedal_tone":
            pedal_type = options.get("pedal_choice", "tonic").lower()
            pedal_note_p: Optional[pitch.Pitch] = None
            if pedal_type == "tonic" and current_scale and current_scale.tonic:
                pedal_note_p = pitch.Pitch(current_scale.tonic.name) # Nameから
                pedal_note_p.octave = target_octave
            elif pedal_type == "dominant" and current_scale:
                dom_p = current_scale.pitchFromDegree(5)
                if dom_p :
                    pedal_note_p = pitch.Pitch(dom_p.name) # Nameから
                    pedal_note_p.octave = target_octave
            
            if pedal_note_p:
                n = music21.note.Note(pedal_note_p) # Pitchオブジェクトを渡す
                n.duration.quarterLength = block_duration
                n.volume.velocity = base_velocity
                notes.append((block_offset, n))
            else: # フォールバック
                self.logger.warning(f"BassGen (Algo): Could not determine pedal note for type '{pedal_type}'. Using root only.")
                notes.extend(self._generate_algorithmic_pattern("algorithmic_root_only", m21_cs, {}, base_velocity, target_octave, block_offset, block_duration, current_scale))
        else:
            self.logger.warning(f"BassGenerator: Unknown algorithmic pattern_type '{pattern_type}'. Using root_only fallback.")
            notes.extend(self._generate_algorithmic_pattern("algorithmic_root_only", m21_cs, {}, base_velocity, target_octave, block_offset, block_duration, current_scale))

        return notes


    def compose(self, processed_blocks: Sequence[Dict[str, Any]], return_pretty_midi: bool = False) -> Union[stream.Part, Any]:
        bass_part = stream.Part(id="Bass")
        bass_part.insert(0, self.default_instrument)
        bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        if self.global_time_signature_obj:
             ts_clone = meter.TimeSignature(self.global_time_signature_obj.ratioString)
             bass_part.insert(0, ts_clone)
        else:
             bass_part.insert(0, meter.TimeSignature("4/4"))

        if processed_blocks:
            first_block_tonic = processed_blocks[0].get("tonic_of_section", self.global_key_tonic)
            first_block_mode = processed_blocks[0].get("mode", self.global_key_mode)
            try:
                bass_part.insert(0, key.Key(first_block_tonic, first_block_mode.lower()))
            except Exception as e_key_insert:
                 self.logger.error(f"BassGen compose: Failed to insert key {first_block_tonic} {first_block_mode}: {e_key_insert}. Using global default.", exc_info=True)
                 bass_part.insert(0, key.Key(self.global_key_tonic, self.global_key_mode.lower()))

        current_total_offset = 0.0 # これはループ内で使用されず、ブロックの絶対オフセットはblk_dataから取得するため、冗長かもしれない
        part_overall_humanize_params = None

        for blk_idx, blk_data in enumerate(processed_blocks):
            bass_params_for_block = blk_data.get("part_params", {}).get("bass", {})
            if not bass_params_for_block:
                self.logger.debug(f"BassGenerator: No bass params for block {blk_idx+1} (Offset: {blk_data.get('offset', 0.0):.2f}). Skipping bass for this block.")
                # current_total_offset += blk_data.get("q_length", 0.0) # オフセットは block_data から取得するため、ここでの加算は不要
                continue

            if blk_idx == 0:
                part_overall_humanize_params = {
                    "humanize_opt": bass_params_for_block.get("humanize_opt", True),
                    "template_name": bass_params_for_block.get("template_name", "default_subtle"),
                    "custom_params": bass_params_for_block.get("custom_params", {})
                }

            chord_label_str = blk_data.get("chord_label", "C")
            block_q_length = blk_data.get("q_length", 4.0)
            block_abs_offset = blk_data.get("offset", 0.0) # processed_stream の offset を使用

            m21_cs_obj: Optional[harmony.ChordSymbol] = None
            sanitized_label : Optional[str] = None
            try:
                sanitized_label = sanitize_chord_label(chord_label_str)
                if sanitized_label and sanitized_label.lower() != "rest":
                    m21_cs_obj = harmony.ChordSymbol(sanitized_label)
                    if not m21_cs_obj.pitches:
                        self.logger.warning(f"BassGen: Chord '{sanitized_label}' parsed but has no pitches for block {blk_idx+1}. Skipping notes.")
                        m21_cs_obj = None
                elif sanitized_label and sanitized_label.lower() == "rest":
                     self.logger.info(f"BassGen: Block {blk_idx+1} is a Rest. No bass notes will be generated.")
                # else: # sanitize_chord_label が None を返した場合 (この場合はRestとして扱われる想定)
                #     self.logger.warning(f"BassGen: Chord label '{chord_label_str}' sanitized to None for block {blk_idx+1}. Assuming Rest.")

            except harmony.HarmonyException as e_harm:
                self.logger.warning(f"BassGen: Could not parse chord '{chord_label_str}' (sanitized: '{sanitized_label}') for block {blk_idx+1}: {e_harm}. Skipping notes.")
            except Exception as e_chord_parse:
                self.logger.error(f"BassGen: Unexpected error parsing chord '{chord_label_str}' (sanitized: '{sanitized_label}') for block {blk_idx+1}: {e_chord_parse}. Skipping notes.", exc_info=True)


            if not m21_cs_obj and (not sanitized_label or sanitized_label.lower() != "rest"):
                self.logger.info(f"BassGen: No valid chord for block {blk_idx+1} (Label: '{chord_label_str}'). No bass notes generated.")
                continue # 次のブロックへ
            
            if m21_cs_obj is None and sanitized_label and sanitized_label.lower() == "rest":
                continue # Restなので次のブロックへ


            rhythm_key_from_params = bass_params_for_block.get("rhythm_key", bass_params_for_block.get("bass_rhythm_key"))
            if not rhythm_key_from_params:
                rhythm_key_from_params = bass_params_for_block.get("style", "bass_quarter_notes")
                self.logger.debug(f"BassGen: No 'rhythm_key' or 'bass_rhythm_key' in params, using 'style': '{rhythm_key_from_params}'")

            pattern_details = self._get_rhythm_pattern_details(rhythm_key_from_params)
            if not pattern_details:
                self.logger.error(f"BassGen: CRITICAL - Could not get any rhythm pattern details for key '{rhythm_key_from_params}'. Skipping block.")
                continue

            base_vel = bass_params_for_block.get("velocity", bass_params_for_block.get("bass_velocity", 70))
            target_oct = bass_params_for_block.get("octave", bass_params_for_block.get("bass_octave", 2))
            
            section_tonic = blk_data.get("tonic_of_section", self.global_key_tonic)
            section_mode = blk_data.get("mode", self.global_key_mode)
            try:
                current_m21_scale = ScaleRegistry.get(section_tonic, section_mode)
            except NameError:
                self.logger.warning(f"BassGen: ScaleRegistry not available. Using basic MajorScale for {section_tonic} {section_mode}.")
                current_m21_scale = music21.scale.MajorScale(section_tonic)
            except Exception as e_scale_get:
                self.logger.error(f"BassGen: Error getting scale {section_tonic} {section_mode}: {e_scale_get}. Fallback to C Major.", exc_info=True)
                current_m21_scale = music21.scale.MajorScale("C")


            generated_notes_for_block: List[Tuple[float, music21.note.Note]] = []

            # m21_cs_obj が None (Restの場合など) でないことを確認してから生成関数を呼ぶ
            if m21_cs_obj:
                if "pattern_type" in pattern_details and isinstance(pattern_details["pattern_type"], str):
                    algo_options = pattern_details.get("options", {})
                    algo_base_velocity = pattern_details.get("velocity_base", base_vel)
                    algo_target_octave = algo_options.get("target_octave", target_oct)

                    generated_notes_for_block = self._generate_algorithmic_pattern(
                        pattern_type=pattern_details["pattern_type"],
                        m21_cs=m21_cs_obj,
                        options=algo_options,
                        base_velocity=algo_base_velocity,
                        target_octave=algo_target_octave,
                        block_offset=block_abs_offset,
                        block_duration=block_q_length,
                        current_scale=current_m21_scale
                    )
                elif "pattern" in pattern_details and isinstance(pattern_details["pattern"], list):
                    generated_notes_for_block = self._generate_notes_from_fixed_pattern(
                        pattern=pattern_details["pattern"],
                        m21_cs=m21_cs_obj,
                        base_velocity=base_vel,
                        target_octave=target_oct,
                        block_offset=block_abs_offset,
                        block_duration=block_q_length,
                        current_scale=current_m21_scale
                    )

            for abs_note_offset, note_obj in generated_notes_for_block:
                if abs_note_offset < block_abs_offset:
                    self.logger.warning(f"BassGen: Note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} starts before block {block_abs_offset:.2f}. Adjusting.")
                    abs_note_offset = block_abs_offset
                
                end_of_note = abs_note_offset + note_obj.duration.quarterLength
                end_of_block = block_abs_offset + block_q_length
                
                if end_of_note > end_of_block + 0.001:
                    new_dur = end_of_block - abs_note_offset
                    if new_dur > MIN_NOTE_DURATION_QL / 2:
                        self.logger.debug(f"BassGen: Note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} (dur {note_obj.duration.quarterLength:.2f}) exceeds block end {end_of_block:.2f}. Truncating to {new_dur:.2f}.")
                        note_obj.duration.quarterLength = new_dur
                    else:
                        self.logger.debug(f"BassGen: Note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} would be too short. Skipping.")
                        continue
                
                if note_obj.duration.quarterLength >= MIN_NOTE_DURATION_QL / 2:
                     bass_part.insert(abs_note_offset, note_obj)
                else:
                     self.logger.debug(f"BassGen: Final note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} is too short. Skipping.")

            # current_total_offset は prepare_processed_stream で計算されたオフセットを使うので、ここでは不要

        if part_overall_humanize_params and part_overall_humanize_params.get("humanize_opt", False):
            self.logger.info(f"BassGenerator: Applying humanization with template '{part_overall_humanize_params.get('template_name')}' and params {part_overall_humanize_params.get('custom_params')}")
            try:
                bass_part_humanized = apply_humanization_to_part(
                    bass_part,
                    template_name=part_overall_humanize_params.get("template_name"),
                    custom_params=part_overall_humanize_params.get("custom_params")
                )
                bass_part_humanized.id = "Bass"
                if not bass_part_humanized.getElementsByClass(m21instrument.Instrument).first():
                    bass_part_humanized.insert(0, self.default_instrument)
                if not bass_part_humanized.getElementsByClass(tempo.MetronomeMark).first() and self.global_tempo:
                     bass_part_humanized.insert(0, tempo.MetronomeMark(number=self.global_tempo))
                if not bass_part_humanized.getElementsByClass(meter.TimeSignature).first() and self.global_time_signature_obj:
                     bass_part_humanized.insert(0, meter.TimeSignature(self.global_time_signature_obj.ratioString))
                first_key_obj = bass_part.getElementsByClass(key.Key).first()
                if not bass_part_humanized.getElementsByClass(key.Key).first() and first_key_obj:
                    bass_part_humanized.insert(0, first_key_obj)
                bass_part = bass_part_humanized
            except NameError:
                self.logger.warning("BassGen: apply_humanization_to_part not available. Skipping humanization.")
            except Exception as e_hum:
                self.logger.error(f"BassGen: Error during bass part humanization: {e_hum}", exc_info=True)

        if return_pretty_midi:
            self.logger.warning("BassGenerator: pretty_midi output is not fully implemented yet.")
            return None
        return bass_part

# --- END OF FILE generator/bass_generator.py ---
