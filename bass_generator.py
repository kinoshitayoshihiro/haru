# --- START OF FILE generator/bass_generator.py (警告解消版) ---
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
        """
        BassGeneratorのコンストラクタ。ベースパート生成に必要な設定を初期化します。

        Args:
            rhythm_library (Optional[Dict[str, Dict]]): リズムパターンライブラリ。
                                                         modular_composer.pyからは、
                                                         rhythm_library.jsonの"bass_lines"または"bass_patterns"
                                                         キーの中身が直接渡されることを想定しています。
            default_instrument (music21.instrument.Instrument): デフォルトで使用するmusic21の楽器オブジェクト。
            global_tempo (int): 曲のグローバルなテンポ（BPM）。
            global_time_signature (str): 曲のグローバルな拍子記号（例: "4/4"）。
            global_key_tonic (str): 曲のグローバルなキーのトニック（例: "C"）。
            global_key_mode (str): 曲のグローバルなキーのモード（例: "major"）。
            rng (Optional[random.Random]): 乱数ジェネレータのインスタンス。
        """
        self.logger = logging.getLogger(__name__)
        
        # --- ここを修正しました！ ---
        # modular_composer.py からは 'bass_lines' または 'bass_patterns' の中身が直接渡されるため、
        # 引数 rhythm_library が既にベースのリズムライブラリそのものになります。
        self.bass_rhythm_library = rhythm_library if rhythm_library else {}
        if not self.bass_rhythm_library:
            # 渡された辞書自体が空の場合にのみ警告を出す
            self.logger.warning("BassGenerator: No bass rhythm patterns provided in the rhythm library. Using internal defaults only.")
        # --- 修正ここまで ---

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

        # 新しいデフォルトのアルゴリズムパターンを追加（土台作り）
        # 既存の外部パターンよりも内部デフォルトを優先したい場合は、この追加ロジックを
        # self.bass_rhythm_library = rhythm_library if rhythm_library else {} の後に記述します。
        # すでに外部に存在していても、ここで上書きすることは避け、存在しない場合にのみ追加する形にします。
        if "basic_chord_tone_quarters" not in self.bass_rhythm_library:
            self.bass_rhythm_library["basic_chord_tone_quarters"] = {
                "description": "Basic quarter note pattern emphasizing root and fifth/third on strong beats.",
                "tags": ["bass", "default", "quarter_notes", "chord_tones"],
                "pattern_type": "algorithmic_chord_tone_quarters", # 新しいアルゴリズムタイプ
                "options": {
                    "base_velocity": 85,
                    "strong_beat_velocity_boost": 15, # 1拍目と3拍目に適用
                    "off_beat_velocity_reduction": 5,  # 2拍目と4拍目に適用
                    "target_octave": 2 # デフォルトオクターブをここに設定 (composeから渡される値で上書き可能)
                }
            }
            self.logger.info("BassGenerator: Added 'basic_chord_tone_quarters' algorithmic pattern to internal library.")
        
        # 既存のデフォルトパターンも維持しつつ、新しいパターンを優先
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
        """
        指定されたリズムキーに対応するパターン詳細を取得します。
        見つからない場合は、新しいデフォルトパターン 'basic_chord_tone_quarters' をフォールバックとして使用します。

        Args:
            rhythm_key (str): 参照するリズムパターンのキー。

        Returns:
            Dict[str, Any]: リズムパターンの詳細データ。
        """
        # 新しいデフォルトパターンを優先
        default_rhythm = self.bass_rhythm_library.get("basic_chord_tone_quarters")
        details = self.bass_rhythm_library.get(rhythm_key)

        if not details:
            self.logger.warning(f"Bass rhythm key '{rhythm_key}' not found. Using 'basic_chord_tone_quarters' as fallback.")
            return default_rhythm if default_rhythm else {}

        if "pattern_type" in details and isinstance(details["pattern_type"], str):
            if "pattern" not in details: # pattern_typeがあればpatternキーは必須ではない
                details["pattern"] = [] # ダミーとして空リスト
        elif "pattern" not in details or not isinstance(details["pattern"], list):
            self.logger.warning(f"Bass rhythm key '{rhythm_key}' has no 'pattern_type' and invalid or missing 'pattern'. Using fallback 'basic_chord_tone_quarters'.")
            return default_rhythm if default_rhythm else {}
        return details

    def _get_bass_pitch_in_octave(self, base_pitch_obj: Optional[pitch.Pitch], target_octave: int) -> int:
        """
        指定された基本ピッチ名とターゲットオクターブから、ベースに適したMIDIピッチ番号を返します。
        ベースの音域 (E1=28からC4=60) に収まるように調整します。

        Args:
            base_pitch_obj (Optional[music21.pitch.Pitch]): オクターブ調整前の基本的なピッチオブジェクト。
                                                              Noneの場合はC音をフォールバック。
            target_octave (int): 目標とするオクターブ（music21のオクターブ表記、C4が中央C）。

        Returns:
            int: ベースに適したMIDIノート番号。
        """
        if not base_pitch_obj:
            return pitch.Pitch(f"C{target_octave}").midi # フォールバック

        p = pitch.Pitch(base_pitch_obj.name) # ピッチ名だけを取得し、新しいピッチオブジェクトを作成
        p.octave = target_octave

        # ベースの典型的な音域: E1 (MIDI 28) から C4 (MIDI 60)
        min_bass_midi = 28 # E1
        max_bass_midi = 60 # C4

        # 指定オクターブが低すぎる場合は、範囲内に収まるまでオクターブを上げる
        while p.midi < min_bass_midi:
            p.transpose(12, inPlace=True)
        # 指定オクターブが高すぎる場合は、範囲内に収まるまでオクターブを下げる
        while p.midi > max_bass_midi:
            # ただし、下げると最低音域を割ってしまう場合は、下げない
            if p.midi - 12 >= min_bass_midi:
                p.transpose(-12, inPlace=True)
            else:
                break # これ以上下げると範囲外なのでやめる

        # 最終的に範囲外にある場合は、最も近い範囲の端に丸める
        if p.midi > max_bass_midi:
            p.midi = max_bass_midi
        elif p.midi < min_bass_midi:
            p.midi = min_bass_midi

        return p.midi


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
        """
        固定されたリズムパターン定義に基づいてベースノートを生成します。

        Args:
            pattern (List[Dict[str, Any]]): リズムパターン定義のリスト。
            m21_cs (music21.harmony.ChordSymbol): 現在のコードのmusic21オブジェクト。
            base_velocity (int): ベースノートの基本ベロシティ。
            target_octave (int): 目標とするベースのオクターブ。
            block_offset (float): 曲の先頭からの現在のブロックの開始オフセット。
            block_duration (float): 現在のブロックのクォーターレングスでのデュレーション。
            current_scale (Optional[music21.scale.ConcreteScale]): 現在のセクションのmusic21スケールオブジェクト。

        Returns:
            List[Tuple[float, music21.note.Note]]: 生成されたノートのリスト（オフセットとノートオブジェクトのタプル）。
        """
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
                # _get_bass_pitch_in_octave を使用して調整
                midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave)
                
                n = music21.note.Note()
                n.pitch.midi = midi_pitch # MIDIピッチを設定
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
        """
        アルゴリズムに基づいてベースノートを生成します。

        Args:
            pattern_type (str): 生成するアルゴリズムのタイプ。
            m21_cs (music21.harmony.ChordSymbol): 現在のコードのmusic21オブジェクト。
            options (Dict[str, Any]): アルゴリズム固有のオプション。
            base_velocity (int): ベースノートの基本ベロシティ。
            target_octave (int): 目標とするベースのオクターブ。
            block_offset (float): 曲の先頭からの現在のブロックの開始オフセット。
            block_duration (float): 現在のブロックのクォーターレングスでのデュレーション。
            current_scale (music21.scale.ConcreteScale): 現在のセクションのmusic21スケールオブジェクト。

        Returns:
            List[Tuple[float, music21.note.Note]]: 生成されたノートのリスト（オフセットとノートオブジェクトのタプル）。
        """
        notes: List[Tuple[float, music21.note.Note]] = []
        if not m21_cs or not m21_cs.pitches:
            self.logger.warning(f"BassGen (Algo): ChordSymbol '{m21_cs.figure if m21_cs else 'None'}' is invalid or has no pitches. Skipping for {pattern_type}.")
            return notes

        root_note_obj = m21_cs.root()
        if not root_note_obj:
            self.logger.warning(f"BassGen (Algo): Could not get root for chord '{m21_cs.figure}'. Skipping for {pattern_type}.")
            return notes

        self.logger.info(f"BassGen (Algo): Generating '{pattern_type}' for chord '{m21_cs.figure}', scale: {current_scale.name if current_scale else 'N/A'}, opts: {options}")

        # --- 新しいアルゴリズム: basic_chord_tone_quarters (コードトーン比率調整の土台) ---
        if pattern_type == "algorithmic_chord_tone_quarters":
            # options からパラメータ取得、なければデフォルトを使用
            strong_beat_vel_boost = options.get("strong_beat_velocity_boost", 15)
            off_beat_vel_reduction = options.get("off_beat_velocity_reduction", 5)
            # target_octave と base_velocity は `compose` から直接渡されたものが優先される
            # options の値はアルゴリズム固有のデフォルトとして機能

            # 4/4拍子を想定して4拍分を生成
            # block_duration はクォーターレングスなので、拍数に変換してループ回数を決定
            # 小節の始まりから終わりまでをカバーする拍数を計算
            # 最小でも1小節分の処理を行うが、durationがそれ未満ならdurationで制限
            beats_per_measure_in_block = int(self.global_time_signature_obj.numerator / self.global_time_signature_obj.denominator * 4)
            
            # ブロックの総クォーターレングスを現在の拍子での小節数に変換し、それを基に何拍生成するか決定
            # 例えば、4/4拍子で q_lengthが 6.0 (1.5小節) なら、6拍生成
            num_beats_to_generate = int(block_duration)
            
            for beat_idx in range(num_beats_to_generate):
                current_beat_offset = beat_idx * 1.0 # 1拍 = 1.0 quarterLength
                
                # ブロックの総クォーターレングスを超えないようにノート生成を停止
                if current_beat_offset >= block_duration - MIN_NOTE_DURATION_QL / 2 : 
                    break

                chosen_pitch_base: Optional[pitch.Pitch] = None
                current_velocity = base_velocity

                # 拍ごとのコードトーン選択ロジック
                if beat_idx % beats_per_measure_in_block == 0 : # 1拍目 (小節の頭)
                    chosen_pitch_base = root_note_obj
                    current_velocity = min(127, base_velocity + strong_beat_vel_boost)
                elif beat_idx % beats_per_measure_in_block == 2 and beats_per_measure_in_block >= 4 : # 3拍目 (4/4拍子の場合の中強拍)
                    # 優先度: 5度 -> 3度 -> ルート
                    if m21_cs.fifth:
                        chosen_pitch_base = m21_cs.fifth
                    elif m21_cs.third:
                        chosen_pitch_base = m21_cs.third
                    else:
                        chosen_pitch_base = root_note_obj
                    current_velocity = min(127, base_velocity + (strong_beat_vel_boost // 2)) # 3拍目は少し弱めに
                else: # その他の拍 (弱拍)
                    # まずはルート音を配置。将来的には経過音や休符なども考慮
                    chosen_pitch_base = root_note_obj
                    current_velocity = max(1, base_velocity - off_beat_vel_reduction)

                # ピッチが確定していればノートを生成
                if chosen_pitch_base:
                    midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave)
                    
                    n = music21.note.Note()
                    n.pitch.midi = midi_pitch
                    
                    # 音価は四分音符 (1.0 qL)。ただし、ブロックの終わりを超えないように調整
                    note_duration_ql = min(1.0, block_duration - current_beat_offset)
                    
                    if note_duration_ql < MIN_NOTE_DURATION_QL:
                        self.logger.debug(f"BassGen (algorithmic_chord_tone_quarters): Note at {current_beat_offset:.2f} too short ({note_duration_ql:.2f}). Skipping.")
                        continue # 短すぎる音符はスキップ

                    n.duration.quarterLength = note_duration_ql
                    n.volume.velocity = current_velocity
                    notes.append((block_offset + current_beat_offset, n))
                else:
                    self.logger.warning(f"BassGen (algorithmic_chord_tone_quarters): Could not determine pitch for beat {beat_idx} in chord {m21_cs.figure}. Skipping note.")

        elif pattern_type == "algorithmic_root_only":
            note_duration_ql = options.get("note_duration_ql", block_duration)
            if note_duration_ql <= 0: note_duration_ql = block_duration # 安全策
            num_notes = int(block_duration / note_duration_ql) if note_duration_ql > 0 else 0

            for i in range(num_notes):
                midi_pitch = self._get_bass_pitch_in_octave(root_note_obj, target_octave)
                n = music21.note.Note()
                n.pitch.midi = midi_pitch
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

                midi_pitch = self._get_bass_pitch_in_octave(note_to_play_base, target_octave)
                n = music21.note.Note()
                n.pitch.midi = midi_pitch

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
            last_played_midi_pitch: Optional[int] = None

            scale_pitches_in_octave_range: List[pitch.Pitch] = []
            if current_scale:
                # ベースに適した音域でスケール音を取得
                lower_bound_p = pitch.Pitch(f"{current_scale.tonic.name}{target_octave-1}") # 1オクターブ下から
                upper_bound_p = pitch.Pitch(f"{current_scale.tonic.name}{target_octave+2}") # 2オクターブ上まで
                scale_pitches_in_octave_range = current_scale.getPitches(lower_bound_p, upper_bound_p)
            
            if not scale_pitches_in_octave_range and root_note_obj: # フォールバック
                # スケールが取れない場合は、ルート音を中心に半音階的なアプローチも考慮
                scale_pitches_in_octave_range = [root_note_obj.transpose(i) for i in [-2,-1,0,1,2,3,4,5]]

            for i in range(num_steps):
                current_rel_offset = i * step_ql
                target_pitch_obj_for_step: Optional[pitch.Pitch] = None

                if i == 0: # 1拍目
                    target_pitch_obj_for_step = root_note_obj
                elif i % 2 == 0: # 強拍 (簡易的に偶数番目)
                    potential_targets = [t for t in [m21_cs.root(), m21_cs.third, m21_cs.fifth] if t]
                    if potential_targets: target_pitch_obj_for_step = self.rng.choice(potential_targets)
                    else: target_pitch_obj_for_step = root_note_obj
                else: # 弱拍 (簡易的に奇数番目)
                    if last_played_midi_pitch is not None and scale_pitches_in_octave_range:
                        # 前回鳴らした音と次の強拍の音（もしあれば）の間を埋めるようなスケール音を選ぶ
                        # 現状はシンプルに前回鳴らした音に近いスケール音から選択
                        current_pitch_obj_from_midi = pitch.Pitch()
                        current_pitch_obj_from_midi.midi = last_played_midi_pitch
                        
                        # スケール内で現在音に近い音を探す
                        sorted_scale_pitches = sorted(scale_pitches_in_octave_range, key=lambda p: abs(p.ps - current_pitch_obj_from_midi.ps))
                        
                        # ランダム性を持たせるため、近い数音から選択
                        if len(sorted_scale_pitches) > 1:
                            target_pitch_obj_for_step = self.rng.choice(sorted_scale_pitches[:min(3, len(sorted_scale_pitches))])
                        elif sorted_scale_pitches:
                            target_pitch_obj_for_step = sorted_scale_pitches[0]
                        else:
                            target_pitch_obj_for_step = root_note_obj # フォールバック
                    else:
                        if scale_pitches_in_octave_range: target_pitch_obj_for_step = self.rng.choice(scale_pitches_in_octave_range)
                        else: target_pitch_obj_for_step = root_note_obj


                if not target_pitch_obj_for_step: target_pitch_obj_for_step = root_note_obj # 最終フォールバック

                midi_pitch = self._get_bass_pitch_in_octave(target_pitch_obj_for_step, target_octave)
                last_played_midi_pitch = midi_pitch # 次のループのために更新

                n = music21.note.Note()
                n.pitch.midi = midi_pitch
                n.duration.quarterLength = step_ql
                n.volume.velocity = base_velocity - self.rng.randint(0, 5)
                notes.append((block_offset + current_rel_offset, n))
        
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
                lower_bound = pitch.Pitch(f"{current_scale.tonic.name}{target_octave-1}")
                upper_bound = pitch.Pitch(f"{current_scale.tonic.name}{target_octave+2}") # 少し広めに
                scale_pitches_objs = current_scale.getPitches(lower_bound, upper_bound)
            if not scale_pitches_objs and root_note_obj: # フォールバック
                scale_pitches_objs = [root_note_obj.transpose(i) for i in [-2,-1,0,1,2,3,4,5]] # 半音階的な音も候補に


            # 無限ループ防止: block_duration が非常に小さい場合
            if block_duration < step_ql :
                self.logger.warning(f"BassGen (walking_8ths): block_duration {block_duration} is too short for step_ql {step_ql}. Skipping.")
                return notes
            
            max_iterations = int(block_duration / step_ql) * 2 + 1 # 念のため
            loop_count = 0


            while current_rel_offset < block_duration - (MIN_NOTE_DURATION_QL / 2.0) and loop_count < max_iterations: # 終了条件微調整
                note_obj_to_add_pitch: Optional[pitch.Pitch] = None
                vel = base_velocity
                is_approach_note = False

                if idx % 2 == 0: # ダウンビート相当 (強拍)
                    potential_chord_tones = [ct for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth] if ct]
                    if potential_chord_tones:
                        chosen_tone_base = self.rng.choice(potential_chord_tones)
                        note_obj_to_add_pitch = chosen_tone_base # オクターブは後で調整
                    elif root_note_obj: # フォールバック
                        note_obj_to_add_pitch = root_note_obj
                else: # オフビート相当 (弱拍)
                    if self.rng.random() < approach_prob and root_note_obj : # ルート音がある場合のみアプローチ試行
                        # 半音下/上からのクロマチックアプローチ
                        root_pc = root_note_obj.pitchClass
                        approach_pc_int = (root_pc + self.rng.choice([-1, 1])) % 12
                        
                        note_obj_to_add_pitch = pitch.Pitch() # 空のPitchオブジェクトを作成
                        note_obj_to_add_pitch.pitchClass = approach_pc_int # ピッチクラスを設定
                        # note_obj_to_add_pitch.octave は_get_bass_pitch_in_octaveで調整
                        vel = base_velocity - 10
                        is_approach_note = True
                    else: # スケール音
                        if scale_pitches_objs:
                            # コードトーン以外のスケール音を選択
                            chord_tone_pcs = [ct.pitchClass for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth, m21_cs.seventh] if ct]
                            non_chord_tones_in_scale = [p for p in scale_pitches_objs if p.pitchClass not in chord_tone_pcs]
                            if non_chord_tones_in_scale:
                                note_obj_to_add_pitch = self.rng.choice(non_chord_tones_in_scale)
                            elif root_note_obj : # フォールバック
                                note_obj_to_add_pitch = root_note_obj
                        elif root_note_obj: # スケール音も取れない場合の最終フォールバック
                            note_obj_to_add_pitch = root_note_obj
                        vel = base_velocity - 5

                if note_obj_to_add_pitch:
                    midi_pitch = self._get_bass_pitch_in_octave(note_obj_to_add_pitch, target_octave)
                    n = music21.note.Note()
                    n.pitch.midi = midi_pitch
                    n.duration.quarterLength = step_ql
                    n.volume.velocity = vel
                    notes.append((block_offset + current_rel_offset, n))

                current_rel_offset += step_ql
                # スウィング適用 (後続ノートの開始オフセットを調整)
                if swing_ratio > 0 and not is_approach_note and idx % 2 == 0 :
                     delay = step_ql * swing_ratio
                     current_rel_offset += delay
                idx += 1
                loop_count += 1
            if loop_count >= max_iterations:
                self.logger.warning(f"BassGen (walking_8ths): Max iterations reached for block. Check loop conditions.")


        elif pattern_type == "half_time_pop":
            main_note_duration = block_duration
            
            p_root = root_note_obj
            midi_p_root = self._get_bass_pitch_in_octave(p_root, target_octave)

            # メインの音 (全音符またはそれに近い長さ)
            n_main = music21.note.Note()
            n_main.pitch.midi = midi_p_root
            n_main.duration.quarterLength = main_note_duration
            n_main.volume.velocity = base_velocity
            notes.append((block_offset, n_main))

            # ゴーストノート (オプション)
            if options.get("ghost_on_beat_2_and_a_half", False) and block_duration >= 2.5: # 2.5拍以上ないとゴーストは入れにくい
                ghost_note_rel_offset = 1.5 # 4/4拍子の2拍目の裏 (0-indexedで1.5拍目)
                
                # ゴーストノートの開始時間がブロックの終わりを超えないか確認
                if block_abs_offset + ghost_note_rel_offset < block_abs_offset + block_duration - MIN_NOTE_DURATION_QL / 2 :
                    p_ghost = root_note_obj # ゴーストノートもルート音から派生
                    midi_p_ghost = self._get_bass_pitch_in_octave(p_ghost, target_octave)
                    n_ghost = music21.note.Note()
                    n_ghost.pitch.midi = midi_p_ghost
                    n_ghost.duration.quarterLength = 0.25 # 16分など短い音
                    n_ghost.volume.velocity = int(base_velocity * 0.6)
                    notes.append((block_offset + ghost_note_rel_offset, n_ghost))

        elif pattern_type == "syncopated_rnb":
            base_offsets_16th = options.get("pattern_16th_offsets", [0, 3, 6, 10, 13])
            ghost_ratio = options.get("ghost_velocity_ratio", 0.5)
            note_dur_ql = 0.25

            for sixteenth_offset_idx in base_offsets_16th:
                rel_offset_ql = sixteenth_offset_idx * 0.25
                if rel_offset_ql >= block_duration - MIN_NOTE_DURATION_QL / 2: continue # ブロックの終わりを超えないように

                potential_tones = [ct for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth, m21_cs.seventh] if ct]
                chosen_tone_base = self.rng.choice(potential_tones) if potential_tones else root_note_obj
                
                midi_pitch = self._get_bass_pitch_in_octave(chosen_tone_base, target_octave)
                n = music21.note.Note()
                n.pitch.midi = midi_pitch
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
            
            # スケール音を取得 (オクターブ範囲を指定)
            scale_pitches_objs_for_walk: List[pitch.Pitch] = []
            if current_scale and current_scale.tonic:
                lower_oct = target_octave - (max_range_octs // 2)
                upper_oct = target_octave + (max_range_octs - max_range_octs // 2) +1 # +1 for range end
                
                # music21.scale.ConcreteScale.getPitchesはピッチオブジェクトを返す
                scale_pitches_objs_for_walk = current_scale.getPitches(
                    pitch.Pitch(f"{current_scale.tonic.name}{lower_oct}"),
                    pitch.Pitch(f"{current_scale.tonic.name}{upper_oct}")
                )
            if not scale_pitches_objs_for_walk and root_note_obj: # フォールバック: ルート音周辺の半音階
                scale_pitches_objs_for_walk = [root_note_obj.transpose(i) for i in [-2,-1,0,1,2]]
                
            if not scale_pitches_objs_for_walk: # それでも空ならルートだけ
                 if root_note_obj:
                     p_root_target_oct = root_note_obj
                     scale_pitches_objs_for_walk = [p_root_target_oct]
                 else: return notes # ルートもないなら終了

            # 現在のピッチをスケール内で探す
            current_p_resolved = root_note_obj # Nameから
            
            # scale_pitches_objs_for_walk の中から current_p_resolved に最も近いものを見つける
            try:
                # まず、現在のルート音のピッチクラスと一番近いオクターブのスケール音を探す
                initial_pitch_candidates = [p for p in scale_pitches_objs_for_walk if p.pitchClass == current_p_resolved.pitchClass]
                if initial_pitch_candidates:
                    current_pitch_idx = min(range(len(initial_pitch_candidates)), key=lambda i: abs(initial_pitch_candidates[i].ps - self._get_bass_pitch_in_octave(current_p_resolved, target_octave)))
                    current_p_resolved = initial_pitch_candidates[current_pitch_idx]
                else: # スケールにルート音がない場合など、最も近いスケール音を選ぶ
                    current_pitch_idx = min(range(len(scale_pitches_objs_for_walk)), key=lambda i: abs(scale_pitches_objs_for_walk[i].ps - self._get_bass_pitch_in_octave(current_p_resolved, target_octave)))
                    current_p_resolved = scale_pitches_objs_for_walk[current_pitch_idx]

            except ValueError: # scale_pitches_objs_for_walk が空の場合
                return notes


            dir_modifier = 1

            for i in range(num_steps):
                selected_pitch_obj = scale_pitches_objs_for_walk[current_pitch_idx]
                midi_pitch = self._get_bass_pitch_in_octave(selected_pitch_obj, target_octave) # オクターブ調整
                n = music21.note.Note()
                n.pitch.midi = midi_pitch
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
                if rel_offset_ql >= block_duration - MIN_NOTE_DURATION_QL / 2: continue # ブロックの終わりを超えないように
                
                target_oct_for_jump = target_octave if i % 2 == 0 else target_octave + 1 # オクターブを交互に
                midi_pitch = self._get_bass_pitch_in_octave(root_note_obj, target_oct_for_jump)
                n = music21.note.Note()
                n.pitch.midi = midi_pitch
                n.duration.quarterLength = note_dur_ql
                n.volume.velocity = base_velocity if i % 2 == 0 else base_velocity - accent_boost // 2
                notes.append((block_offset + rel_offset_ql, n))

        elif pattern_type == "descending_fifths":
            resolution_ql = options.get("note_resolution_ql", 1.0)
            if resolution_ql <=0: resolution_ql = 1.0
            num_steps = int(min(block_duration, options.get("length_beats", 4)) / resolution_ql) if resolution_ql > 0 else 0
            current_p_obj = root_note_obj
            
            for i in range(num_steps):
                midi_pitch = self._get_bass_pitch_in_octave(current_p_obj, target_octave)
                n = music21.note.Note()
                n.pitch.midi = midi_pitch
                n.duration.quarterLength = resolution_ql
                n.volume.velocity = base_velocity
                notes.append((block_offset + i * resolution_ql, n))
                current_p_obj.transpose(interval.Interval('-P4'), inPlace=True) # 完全4度下げる = 完全5度上と同じ

        elif pattern_type == "pedal_tone":
            pedal_type = options.get("pedal_choice", "tonic").lower()
            pedal_note_p: Optional[pitch.Pitch] = None
            if pedal_type == "tonic" and current_scale and current_scale.tonic:
                pedal_note_p = current_scale.tonic # Pitchオブジェクト
            elif pedal_type == "dominant" and current_scale:
                dom_p = current_scale.pitchFromDegree(5)
                if dom_p :
                    pedal_note_p = dom_p # Pitchオブジェクト
            
            if pedal_note_p:
                midi_pitch = self._get_bass_pitch_in_octave(pedal_note_p, target_octave)
                n = music21.note.Note()
                n.pitch.midi = midi_pitch
                n.duration.quarterLength = block_duration
                n.volume.velocity = base_velocity
                notes.append((block_offset, n))
            else: # フォールバック
                self.logger.warning(f"BassGen (Algo): Could not determine pedal note for type '{pedal_type}'. Using basic_chord_tone_quarters fallback.")
                # 新しいデフォルトのアルゴリズムパターンをフォールバックとして使用
                default_algo_options = self.bass_rhythm_library["basic_chord_tone_quarters"]["options"]
                notes.extend(self._generate_algorithmic_pattern(
                    "algorithmic_chord_tone_quarters",
                    m21_cs,
                    default_algo_options,
                    base_velocity,
                    target_octave,
                    block_offset,
                    block_duration,
                    current_scale
                ))
        else:
            self.logger.warning(f"BassGenerator: Unknown algorithmic pattern_type '{pattern_type}'. Using basic_chord_tone_quarters fallback.")
            # 新しいデフォルトのアルゴリズムパターンをフォールバックとして使用
            default_algo_options = self.bass_rhythm_library["basic_chord_tone_quarters"]["options"]
            notes.extend(self._generate_algorithmic_pattern(
                "algorithmic_chord_tone_quarters",
                m21_cs,
                default_algo_options,
                base_velocity,
                target_octave,
                block_offset,
                block_duration,
                current_scale
            ))

        return notes


    def compose(self, processed_blocks: Sequence[Dict[str, Any]], return_pretty_midi: bool = False) -> Union[stream.Part, Any]:
        """
        与えられた処理済みコードブロックのストリームに基づいて、ベースパートを生成します。
        
        Args:
            processed_blocks (Sequence[Dict[str, Any]]): 各コードブロックの情報を含む辞書のシーケンス。
                                                          各辞書には 'chord_label', 'q_length', 'offset'
                                                          および 'part_params' (ベース固有のパラメータ) が含まれる。
            return_pretty_midi (bool): Trueの場合、pretty_midi.PrettyMIDIオブジェクトを返す（未実装）。
                                       Falseの場合、music21.stream.Partオブジェクトを返す。
        
        Returns:
            Union[music21.stream.Part, Any]: 生成されたベースパート (music21.stream.Part) または None。
        """
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

        part_overall_humanize_params = None

        for blk_idx, blk_data in enumerate(processed_blocks):
            bass_params_for_block = blk_data.get("part_params", {}).get("bass", {})
            if not bass_params_for_block:
                self.logger.debug(f"BassGenerator: No bass params for block {blk_idx+1} (Offset: {blk_data.get('offset', 0.0):.2f}). Skipping bass for this block.")
                continue

            if blk_idx == 0: # 最初のブロックでhumanizeパラメータを一度だけ取得
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
            except harmony.HarmonyException as e_harm:
                self.logger.warning(f"BassGen: Could not parse chord '{chord_label_str}' (sanitized: '{sanitized_label}') for block {blk_idx+1}: {e_harm}. Skipping notes.")
            except Exception as e_chord_parse:
                self.logger.error(f"BassGen: Unexpected error parsing chord '{chord_label_str}' (sanitized: '{sanitized_label}') for block {blk_idx+1}: {e_chord_parse}. Skipping notes.", exc_info=True)


            if not m21_cs_obj and (not sanitized_label or sanitized_label.lower() != "rest"):
                self.logger.info(f"BassGen: No valid chord for block {blk_idx+1} (Label: '{chord_label_str}'). No bass notes generated.")
                continue # 次のブロックへ
            
            if m21_cs_obj is None and sanitized_label and sanitized_label.lower() == "rest":
                continue # Restなので次のブロックへ


            # ここでデフォルトのリズムキーの優先順位を調整
            # part_paramsにリズムキーやスタイルが明示的に指定されていなければ、新しいデフォルトアルゴリズムを使う
            rhythm_key_from_params = bass_params_for_block.get("rhythm_key", bass_params_for_block.get("bass_rhythm_key"))
            if not rhythm_key_from_params:
                rhythm_key_from_params = bass_params_for_block.get("style", "basic_chord_tone_quarters") 
                self.logger.debug(f"BassGen: No 'rhythm_key' or 'bass_rhythm_key' in params, using 'style': '{rhythm_key_from_params}' (new default).")

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
                    # alg_options内のvelocityやoctaveは、paramsからの値を優先する
                    # これにより、modular_composer.pyで設定された値がアルゴリズムのオプションを上書きできる
                    algo_base_velocity = bass_params_for_block.get("velocity", base_vel) 
                    algo_target_octave = bass_params_for_block.get("octave", target_oct)
                    # ただし、アルゴリズム固有のオプション (例: strong_beat_velocity_boost) は algo_options から取得
                    algo_options["base_velocity"] = algo_base_velocity # オプションに伝搬
                    algo_options["target_octave"] = algo_target_octave # オプションに伝搬

                    generated_notes_for_block = self._generate_algorithmic_pattern(
                        pattern_type=pattern_details["pattern_type"],
                        m21_cs=m21_cs_obj,
                        options=algo_options, # ここで更新されたalgo_optionsを渡す
                        base_velocity=algo_base_velocity, # base_velocityを直接渡す
                        target_octave=algo_target_octave, # target_octaveを直接渡す
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
                
                if end_of_note > end_of_block + 0.001: # わずかな誤差を許容
                    new_dur = end_of_block - abs_note_offset
                    if new_dur > MIN_NOTE_DURATION_QL / 2: # 非常に短い音符にならないように
                        self.logger.debug(f"BassGen: Note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} (dur {note_obj.duration.quarterLength:.2f}) exceeds block end {end_of_block:.2f}. Truncating to {new_dur:.2f}.")
                        note_obj.duration.quarterLength = new_dur
                    else:
                        self.logger.debug(f"BassGen: Note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} would be too short. Skipping.")
                        continue # 短すぎる音符はスキップ

                if note_obj.duration.quarterLength >= MIN_NOTE_DURATION_QL / 2: # 最終チェック
                     bass_part.insert(abs_note_offset, note_obj)
                else:
                     self.logger.debug(f"BassGen: Final note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} is too short after truncation. Skipping.")

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
