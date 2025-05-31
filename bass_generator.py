# --- START OF FILE generator/bass_generator.py (override対応・ヘルパー実装・修正版) ---
import music21
import logging
from music21 import stream, note, chord as m21chord, harmony, pitch, tempo, meter, instrument as m21instrument, key, interval, scale
import random
from typing import List, Dict, Optional, Any, Tuple, Union, cast, Sequence # Sequence を追加
import copy # deepcopyのため

try:
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL, _ROOT_RE_STRICT
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
    from utilities.scale_registry import ScaleRegistry
    from .bass_utils import get_approach_note
    from utilities.override_loader import get_part_override, Overrides # Overridesもインポート
except ImportError as e:
    print(f"BassGenerator: Warning - could not import all utilities: {e}")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature: return meter.TimeSignature(ts_str or "4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]: return label
    def apply_humanization_to_part(part, template_name=None, custom_params=None): return part
    HUMANIZATION_TEMPLATES = {}
    class ScaleRegistry:
        @staticmethod
        def get(tonic_str: Optional[str], mode_str: Optional[str]) -> music21.scale.ConcreteScale:
            return music21.scale.MajorScale(tonic_str or "C")
    import re
    _ROOT_RE_STRICT = re.compile(r'^([A-G](?:[#b]{1,2}|[ns])?)(?![#b])')
    def get_approach_note(from_p, to_p, scale_o, style="chromatic_or_diatonic", max_s=2, pref_dir=None): return to_p
    class DummyPartOverride: model_config = {}; model_fields = {}
    def get_part_override(overrides, section, part) -> DummyPartOverride: return DummyPartOverride()
    class Overrides: root = {} # ダミー


EMOTION_TO_BUCKET_BASS: dict[str, str] = { "quiet_pain_and_nascent_strength": "calm", "deep_regret_gratitude_and_realization": "calm", "self_reproach_regret_deep_sadness": "calm", "memory_unresolved_feelings_silence": "calm", "nature_memory_floating_sensation_forgiveness": "calm", "supported_light_longing_for_rebirth": "groovy", "wavering_heart_gratitude_chosen_strength": "groovy", "hope_dawn_light_gentle_guidance": "groovy", "acceptance_of_love_and_pain_hopeful_belief": "energetic", "trial_cry_prayer_unbreakable_heart": "energetic", "reaffirmed_strength_of_love_positive_determination": "energetic", "future_cooperation_our_path_final_resolve_and_liberation": "energetic", "default": "groovy" }
BUCKET_TO_PATTERN_BASS: dict[tuple[str, str], str] = { ("calm", "low"): "root_only", ("calm", "medium_low"): "root_fifth", ("calm", "medium"): "bass_half_time_pop", ("calm", "medium_high"):"bass_half_time_pop", ("calm", "high"): "walking", ("groovy", "low"): "bass_syncopated_rnb", ("groovy", "medium_low"): "walking", ("groovy", "medium"): "bass_walking_8ths", ("groovy", "medium_high"):"bass_walking_8ths", ("groovy", "high"): "bass_funk_octave", ("energetic", "low"): "bass_quarter_notes", ("energetic", "medium_low"): "bass_pump_8th_octaves", ("energetic", "medium"): "bass_pump_8th_octaves", ("energetic", "medium_high"):"bass_funk_octave", ("energetic", "high"): "bass_funk_octave", ("default", "low"): "root_only", ("default", "medium_low"): "bass_quarter_notes", ("default", "medium"): "walking", ("default", "medium_high"):"bass_walking_8ths", ("default", "high"): "bass_pump_8th_octaves", }

class BassGenerator:
    def __init__(self, rhythm_library: Optional[Dict[str, Dict]] = None, default_instrument: m21instrument.Instrument = m21instrument.AcousticBass(), global_tempo: int = 120, global_time_signature: str = "4/4", global_key_tonic: str = "C", global_key_mode: str = "major", rng_seed: Optional[int] = None):
        self.logger = logging.getLogger(__name__)
        # BassGeneratorはrhythm_library全体の "bass_patterns" 部分のみを扱う
        full_rhythm_library = rhythm_library if rhythm_library is not None else {}
        self.bass_rhythm_library = full_rhythm_library.get("bass_patterns", {})

        if not self.bass_rhythm_library:
            self.logger.warning("BassGenerator: No 'bass_patterns' found in rhythm_library or rhythm_library is empty. Using internal defaults only.")
            self.bass_rhythm_library = {} # 空の辞書として初期化

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        try:
            self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except Exception:
            self.logger.warning(f"BassGenerator: Could not parse global_time_signature '{global_time_signature}'. Defaulting to 4/4.")
            self.global_time_signature_obj = music21.meter.TimeSignature("4/4")
        self.measure_duration = self.global_time_signature_obj.barDuration.quarterLength if self.global_time_signature_obj else 4.0
        self.global_key_tonic = global_key_tonic
        self.global_key_mode = global_key_mode
        if rng_seed is not None:
            self.rng = random.Random(rng_seed)
        else:
            self.rng = random.Random()

        # デフォルトパターンの追加 (もし存在しなければ)
        if "basic_chord_tone_quarters" not in self.bass_rhythm_library:
            self.bass_rhythm_library["basic_chord_tone_quarters"] = {"description": "Basic quarter note pattern with configurable weak beats and approach.", "tags": ["bass", "default", "algorithmic"], "pattern_type": "algorithmic_chord_tone_quarters", "options": {"base_velocity": 85, "strong_beat_velocity_boost": 15, "off_beat_velocity_reduction": 5, "target_octave": 2, "weak_beat_style": "root", "approach_on_4th_beat": True, "approach_style_on_4th": "chromatic_or_diatonic"}}
            self.logger.info("BassGenerator: Added 'basic_chord_tone_quarters' to bass_rhythm_library.")
        if "bass_quarter_notes" not in self.bass_rhythm_library: # これは固定パターンの例
            self.bass_rhythm_library["bass_quarter_notes"] = {"description": "Default fixed quarter notes.", "tags": ["bass", "default", "fixed_pattern"], "pattern_type":"fixed_pattern", "pattern": [{"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"}, {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}, {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"}, {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}]}
            self.logger.info("BassGenerator: Added 'bass_quarter_notes' to bass_rhythm_library.")
        if "root_only" not in self.bass_rhythm_library:
            self.bass_rhythm_library["root_only"] = {"description": "Fallback whole-note roots.", "tags": ["bass", "fallback", "algorithmic"], "pattern_type": "algorithmic_root_only", "pattern": [{"offset": 0.0, "duration": 4.0, "velocity_factor": 0.6}]} # patternはアルゴリズム用には不要だが一応
            self.logger.info("BassGenerator: Added 'root_only' to bass_rhythm_library.")


    def _choose_bass_pattern_key(self, section_musical_intent: dict) -> str: # メソッド化
        emotion = section_musical_intent.get("emotion", "default"); intensity = section_musical_intent.get("intensity", "medium").lower()
        bucket = EMOTION_TO_BUCKET_BASS.get(emotion, "default")
        pattern_key = BUCKET_TO_PATTERN_BASS.get((bucket, intensity), "bass_quarter_notes") # デフォルトを "bass_quarter_notes" に
        self.logger.info(f"Bass pattern choice: Emotion='{emotion}', Intensity='{intensity}' -> Bucket='{bucket}' -> PatternKey='{pattern_key}'")
        return pattern_key

    def _get_rhythm_pattern_details(self, rhythm_key: str) -> Dict[str, Any]:
        if not rhythm_key:
            rhythm_key = "basic_chord_tone_quarters" # デフォルトのアルゴリズムパターン
            self.logger.debug(f"BassGenerator _get_rhythm_pattern_details: No rhythm_key provided, using default '{rhythm_key}'.")

        details = self.bass_rhythm_library.get(rhythm_key)
        if not details:
            self.logger.warning(f"BassGenerator _get_rhythm_pattern_details: Rhythm key '{rhythm_key}' not found in bass_rhythm_library. Using 'basic_chord_tone_quarters'.")
            details = self.bass_rhythm_library.get("basic_chord_tone_quarters")
            if not details: # これもなければ究極のフォールバック
                self.logger.error("BassGenerator _get_rhythm_pattern_details: CRITICAL - Default 'basic_chord_tone_quarters' also not found. Returning empty pattern.")
                return {"pattern_type": "algorithmic_root_only", "pattern": [], "options": {}} # 最低限のフォールバック
        return details

    def _get_bass_pitch_in_octave(self, base_pitch_obj: Optional[pitch.Pitch], target_octave: int) -> int:
        if not base_pitch_obj: return pitch.Pitch(f"C{target_octave}").midi
        p_new = pitch.Pitch(base_pitch_obj.name); p_new.octave = target_octave; min_bass_midi = 28; max_bass_midi = 60; current_midi = p_new.midi
        while current_midi < min_bass_midi: current_midi += 12
        while current_midi > max_bass_midi:
            if current_midi - 12 >= min_bass_midi: current_midi -= 12
            else: break
        return max(min_bass_midi, min(current_midi, max_bass_midi))

    def _generate_notes_from_fixed_pattern( self, pattern: List[Dict[str, Any]], m21_cs: harmony.ChordSymbol, base_velocity: int, target_octave: int, block_duration: float, current_scale: Optional[music21.scale.ConcreteScale] = None) -> List[Tuple[float, music21.note.Note]]:
        notes: List[Tuple[float, music21.note.Note]] = [];
        if not m21_cs or not m21_cs.pitches: return notes
        root_pitch_obj = m21_cs.root(); third_pitch_obj = m21_cs.third; fifth_pitch_obj = m21_cs.fifth; chord_tones = [p for p in [root_pitch_obj, third_pitch_obj, fifth_pitch_obj] if p]
        for p_event in pattern:
            offset_in_block = p_event.get("offset", 0.0); duration_ql = p_event.get("duration", 1.0); vel_factor = p_event.get("velocity_factor", 1.0); note_type = p_event.get("type", "root").lower()
            final_velocity = max(1, min(127, int(base_velocity * vel_factor))); chosen_pitch_base: Optional[pitch.Pitch] = None
            if note_type == "root" and root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "fifth" and fifth_pitch_obj: chosen_pitch_base = fifth_pitch_obj
            elif note_type == "third" and third_pitch_obj: chosen_pitch_base = third_pitch_obj
            elif note_type == "octave_root" and root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "random_chord_tone" and chord_tones: chosen_pitch_base = self.rng.choice(chord_tones)
            elif note_type == "scale_tone" and current_scale:
                try: p_s = current_scale.pitchFromDegree(self.rng.choice([1,2,3,4,5,6,7]))
                except Exception: p_s = None
                if p_s: chosen_pitch_base = p_s
                elif root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "approach" and root_pitch_obj: chosen_pitch_base = root_pitch_obj.transpose(-1) # 単純な半音下
            if not chosen_pitch_base and root_pitch_obj: chosen_pitch_base = root_pitch_obj # フォールバック
            if chosen_pitch_base:
                midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch
                n.duration = music21.duration.Duration(duration_ql); n.volume.velocity = final_velocity
                if p_event.get("glide_to_next", False): n.tie = music21.tie.Tie("start")
                notes.append((offset_in_block, n))
        return notes

    def _apply_weak_beat(self, notes_in_measure: List[Tuple[float, music21.note.Note]],
                         style: str,
                         base_velocity: int) -> List[Tuple[float, music21.note.Note]]:
        if style == "none" or not notes_in_measure: return notes_in_measure
        new_notes_tuples: List[Tuple[float, music21.note.Note]] = []
        beats_in_measure = self.global_time_signature_obj.beatCount if self.global_time_signature_obj else 4
        beat_q_len = self.global_time_signature_obj.beatDuration.quarterLength if self.global_time_signature_obj else 1.0

        for rel_offset, note_obj in notes_in_measure:
            is_weak_beat = False
            # 拍番号を計算 (0-indexed)
            beat_number_float = rel_offset / beat_q_len
            # 厳密に拍頭にあるかチェック (浮動小数点誤差を考慮)
            is_on_beat = abs(beat_number_float - round(beat_number_float)) < 0.01
            beat_index = int(round(beat_number_float)) # 0-indexed

            if is_on_beat:
                if beats_in_measure == 4 and (beat_index == 1 or beat_index == 3): # 2拍目と4拍目 (0-indexedで1と3)
                    is_weak_beat = True
                elif beats_in_measure == 3 and (beat_index == 1 or beat_index == 2): # 3拍子の2,3拍目
                    is_weak_beat = True

            if is_weak_beat:
                if style == "rest": self.logger.debug(f"BassGen _apply_weak_beat: Removing note at offset {rel_offset} for style 'rest'."); continue
                elif style == "ghost":
                    original_vel = note_obj.volume.velocity if note_obj.volume and note_obj.volume.velocity is not None else base_velocity
                    note_obj.volume.velocity = max(1, int(original_vel * 0.4))
                    self.logger.debug(f"BassGen _apply_weak_beat: Ghosting note at offset {rel_offset} to vel {note_obj.volume.velocity}.")
            new_notes_tuples.append((rel_offset, note_obj))
        return new_notes_tuples

    def _insert_approach_note_to_measure(self,
                                      notes_in_measure: List[Tuple[float, music21.note.Note]],
                                      current_chord_symbol: harmony.ChordSymbol,
                                      next_chord_root: Optional[pitch.Pitch],
                                      current_scale: music21.scale.ConcreteScale,
                                      approach_style: str,
                                      target_octave: int,
                                      base_velocity: int
                                      ) -> List[Tuple[float, music21.note.Note]]:
        if not next_chord_root or self.measure_duration < 1.0:
            return notes_in_measure

        approach_note_rel_offset = self.measure_duration - 0.25

        can_insert = True
        original_last_note_tuple: Optional[Tuple[float, music21.note.Note]] = None
        sorted_notes_in_measure = sorted(notes_in_measure, key=lambda x: x[0])

        for rel_offset, note_obj in reversed(sorted_notes_in_measure):
            if rel_offset >= approach_note_rel_offset:
                can_insert = False; break
            if rel_offset < approach_note_rel_offset and (rel_offset + note_obj.duration.quarterLength > approach_note_rel_offset):
                original_last_note_tuple = (rel_offset, note_obj)
                break

        if not can_insert:
            self.logger.debug(f"BassGen _insert_approach: Cannot insert approach note at {approach_note_rel_offset}, existing note conflict.")
            return notes_in_measure

        from_pitch_for_approach = current_chord_symbol.root()
        if original_last_note_tuple:
            from_pitch_for_approach = original_last_note_tuple[1].pitch
        elif sorted_notes_in_measure:
             from_pitch_for_approach = sorted_notes_in_measure[-1][1].pitch

        approach_pitch_obj = get_approach_note(
            from_pitch_for_approach, next_chord_root, current_scale, approach_style=approach_style
        )

        if approach_pitch_obj:
            app_note = music21.note.Note()
            app_note.pitch.midi = self._get_bass_pitch_in_octave(approach_pitch_obj, target_octave)
            app_note.duration.quarterLength = 0.25
            app_note.volume.velocity = min(127, int(base_velocity * 0.85))

            if original_last_note_tuple:
                orig_rel_offset, orig_note_obj_ref = original_last_note_tuple
                new_dur = approach_note_rel_offset - orig_rel_offset
                if new_dur >= MIN_NOTE_DURATION_QL / 2:
                    orig_note_obj_ref.duration.quarterLength = new_dur
                else:
                    self.logger.debug(f"BassGen _insert_approach: Last note would be too short ({new_dur}) after making space. Skipping approach.")
                    return notes_in_measure

            notes_in_measure.append((approach_note_rel_offset, app_note))
            notes_in_measure.sort(key=lambda x: x[0])
            self.logger.info(f"BassGen _insert_approach: Added approach note {app_note.nameWithOctave} at {approach_note_rel_offset} for next root {next_chord_root.name}")
        return notes_in_measure


    def _generate_algorithmic_pattern(self, pattern_type: str, m21_cs: harmony.ChordSymbol, options: Dict[str, Any], base_velocity: int, target_octave: int, block_offset_ignored: float, block_duration: float, current_scale: music21.scale.ConcreteScale, next_chord_root: Optional[pitch.Pitch] = None, section_overrides: Optional[Any] = None) -> List[Tuple[float, music21.note.Note]]:
        notes_tuples: List[Tuple[float, music21.note.Note]] = []
        if not m21_cs or not m21_cs.pitches: return notes_tuples
        root_note_obj = m21_cs.root()
        if not root_note_obj: return notes_tuples
        
        current_options = copy.deepcopy(options) # 元のoptionsをディープコピー
        effective_base_velocity = base_velocity

        if section_overrides: # section_overrides は PartOverride インスタンス
            override_values = section_overrides.model_dump(exclude_unset=True)
            
            temp_velocity_shift = override_values.pop("velocity_shift", None) # 先にpop
            temp_velocity_direct = override_values.pop("velocity", None) # 先にpop

            if temp_velocity_direct is not None:
                effective_base_velocity = temp_velocity_direct
            elif temp_velocity_shift is not None:
                effective_base_velocity += temp_velocity_shift
            
            # 'options' キーはネストしてマージ
            if "options" in override_values and isinstance(override_values["options"], dict):
                current_options.setdefault("options", {}).update(override_values.pop("options"))
            
            current_options.update(override_values) # 残りの値をマージ
        
        effective_base_velocity = max(1, min(127, effective_base_velocity))


        if pattern_type == "algorithmic_chord_tone_quarters":
            strong_beat_vel_boost = current_options.get("strong_beat_velocity_boost", 15)
            off_beat_vel_reduction = current_options.get("off_beat_velocity_reduction", 5)
            weak_beat_style_final = current_options.get("weak_beat_style", "root")
            approach_on_4th_final = current_options.get("approach_on_4th_beat", True) # Trueがデフォルト
            approach_style_final = current_options.get("approach_style_on_4th", "chromatic_or_diatonic")

            beats_per_measure_in_block = self.global_time_signature_obj.beatCount if self.global_time_signature_obj else 4
            
            measure_notes_raw: List[Tuple[float, music21.note.Note]] = []
            for beat_idx in range(beats_per_measure_in_block):
                current_rel_offset_in_measure = beat_idx * 1.0
                chosen_pitch_base: Optional[pitch.Pitch] = None
                current_velocity = effective_base_velocity
                note_duration_ql = 1.0

                if beat_idx == 0 :
                    chosen_pitch_base = root_note_obj
                    current_velocity = min(127, effective_base_velocity + strong_beat_vel_boost)
                elif beats_per_measure_in_block >= 4 and beat_idx == (beats_per_measure_in_block // 2) :
                    if m21_cs.fifth: chosen_pitch_base = m21_cs.fifth
                    elif m21_cs.third: chosen_pitch_base = m21_cs.third
                    else: chosen_pitch_base = root_note_obj
                    current_velocity = min(127, effective_base_velocity + (strong_beat_vel_boost // 2))
                else:
                    chosen_pitch_base = root_note_obj
                    current_velocity = max(1, effective_base_velocity - off_beat_vel_reduction)
                
                if chosen_pitch_base:
                    if note_duration_ql < MIN_NOTE_DURATION_QL: continue
                    midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch
                    n.duration.quarterLength = note_duration_ql; n.volume.velocity = current_velocity
                    measure_notes_raw.append((current_rel_offset_in_measure, n))
            
            processed_measure_notes = self._apply_weak_beat(measure_notes_raw, weak_beat_style_final, effective_base_velocity)

            if approach_on_4th_final and next_chord_root and beats_per_measure_in_block == 4:
                processed_measure_notes = self._insert_approach_note_to_measure(
                    processed_measure_notes, m21_cs, next_chord_root, current_scale,
                    approach_style_final, target_octave, effective_base_velocity
                )
            
            current_pos_in_block = 0.0
            while current_pos_in_block < block_duration - (MIN_NOTE_DURATION_QL / 8.0):
                for rel_offset_in_measure, note_obj_template in processed_measure_notes:
                    abs_offset_in_block = current_pos_in_block + rel_offset_in_measure
                    if abs_offset_in_block >= block_duration - (MIN_NOTE_DURATION_QL / 8.0): break
                    note_to_add = music21.note.Note(note_obj_template.pitch)
                    note_to_add.duration.quarterLength = note_obj_template.duration.quarterLength
                    note_to_add.volume.velocity = note_obj_template.volume.velocity
                    remaining_block_dur = block_duration - abs_offset_in_block
                    if note_to_add.duration.quarterLength > remaining_block_dur:
                        note_to_add.duration.quarterLength = remaining_block_dur
                    if note_to_add.duration.quarterLength >= MIN_NOTE_DURATION_QL / 2:
                        notes_tuples.append((abs_offset_in_block, note_to_add))
                current_pos_in_block += self.measure_duration
                if self.measure_duration <=0: break

        elif pattern_type == "algorithmic_root_only":
            note_duration_ql = current_options.get("note_duration_ql", block_duration);
            if note_duration_ql <= 0: note_duration_ql = block_duration
            num_notes = int(block_duration / note_duration_ql) if note_duration_ql > 0 else 0
            for i in range(num_notes):
                current_rel_offset = i * note_duration_ql
                midi_pitch = self._get_bass_pitch_in_octave(root_note_obj, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch; n.duration.quarterLength = note_duration_ql
                n.volume.velocity = effective_base_velocity; notes_tuples.append((current_rel_offset, n))
        else: # 未知のアルゴリズムパターンの場合、デフォルトのアルゴリズムにフォールバック
            self.logger.warning(f"BassGenerator: Unknown algorithmic pattern_type '{pattern_type}'. Falling back to 'algorithmic_chord_tone_quarters'.")
            default_algo_options = self.bass_rhythm_library.get("basic_chord_tone_quarters",{}).get("options",{})
            # section_overrides は最初の呼び出しで適用済みなので、再帰呼び出しでは None を渡す
            notes_tuples.extend(self._generate_algorithmic_pattern("algorithmic_chord_tone_quarters", m21_cs, default_algo_options, base_velocity, target_octave, 0.0, block_duration, current_scale, next_chord_root, None))
        return notes_tuples

    def compose(self, processed_blocks: Sequence[Dict[str, Any]], overrides: Optional[Any] = None, return_pretty_midi: bool = False) -> Union[stream.Part, Any]:
        bass_part = stream.Part(id="Bass"); bass_part.insert(0, self.default_instrument)
        if self.global_tempo: bass_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        if self.global_time_signature_obj: bass_part.insert(0, meter.TimeSignature(self.global_time_signature_obj.ratioString))
        else: bass_part.insert(0, meter.TimeSignature("4/4"))

        if processed_blocks:
            first_block_tonic = processed_blocks[0].get("tonic_of_section", self.global_key_tonic); first_block_mode = processed_blocks[0].get("mode", self.global_key_mode)
            try:
                if not bass_part.getElementsByClass(key.Key).first(): bass_part.insert(0, key.Key(first_block_tonic, first_block_mode.lower()))
            except Exception:
                 if not bass_part.getElementsByClass(key.Key).first(): bass_part.insert(0, key.Key(self.global_key_tonic, self.global_key_mode.lower()))
        else:
            if not bass_part.getElementsByClass(key.Key).first(): bass_part.insert(0, key.Key(self.global_key_tonic, self.global_key_mode.lower()))

        part_overall_humanize_params = None

        for blk_idx, blk_data_original in enumerate(processed_blocks):
            blk_data = copy.deepcopy(blk_data_original) # 元のデータを変更しないようにコピー
            current_section_name = blk_data.get("section_name", f"UnnamedSection_{blk_idx}")
            
            part_specific_overrides_model = get_part_override(
                overrides if overrides else Overrides(root={}), # 空のOverridesモデルを渡す
                current_section_name,
                "bass"
            )

            bass_params_from_chordmap = blk_data.get("part_params", {}).get("bass", {})
            final_bass_params = bass_params_from_chordmap.copy()
            if part_specific_overrides_model:
                override_dict = part_specific_overrides_model.model_dump(exclude_unset=True)
                if "options" in override_dict and "options" in final_bass_params and isinstance(final_bass_params["options"], dict) and isinstance(override_dict["options"], dict):
                    final_bass_params["options"].update(override_dict.pop("options"))
                final_bass_params.update(override_dict)
            
            blk_data["part_params"]["bass"] = final_bass_params # マージ結果をblk_dataに反映

            block_musical_intent = blk_data.get("musical_intent", {})
            rhythm_key_from_params = final_bass_params.get("rhythm_key", final_bass_params.get("style"))
            if not rhythm_key_from_params:
                rhythm_key_from_params = self._choose_bass_pattern_key(block_musical_intent)
                self.logger.info(f"Bass rhythm key for block {blk_idx} (Sec: {current_section_name}) chosen by emotion: {rhythm_key_from_params}")
            if not rhythm_key_from_params or rhythm_key_from_params not in self.bass_rhythm_library:
                self.logger.warning(f"Bass rhythm key '{rhythm_key_from_params}' not found or invalid. Using 'basic_chord_tone_quarters'.")
                rhythm_key_from_params = "basic_chord_tone_quarters"
            
            final_bass_params["rhythm_key"] = rhythm_key_from_params # 最終的なリズムキーを格納

            if blk_idx == 0:
                part_overall_humanize_params = {
                    "humanize_opt": final_bass_params.get("humanize_opt", True),
                    "template_name": final_bass_params.get("template_name", "default_subtle"),
                    "custom_params": final_bass_params.get("custom_params", {})
                }

            chord_label_str = blk_data.get("chord_label", "C"); block_q_length = float(blk_data.get("q_length", 4.0)); block_abs_offset = float(blk_data.get("offset", 0.0))
            m21_cs_obj: Optional[harmony.ChordSymbol] = None; sanitized_label : Optional[str] = None; parse_failure_reason = "Unknown parse error"
            try:
                sanitized_label = sanitize_chord_label(chord_label_str)
                if sanitized_label and sanitized_label.lower() != "rest": m21_cs_obj = harmony.ChordSymbol(sanitized_label);
                elif sanitized_label and sanitized_label.lower() == "rest": self.logger.info(f"BassGen: Block {blk_idx+1} is a Rest."); continue
                else: parse_failure_reason = f"sanitize_chord_label returned None for '{chord_label_str}'"
            except harmony.HarmonyException as e_harm: parse_failure_reason = f"HarmonyException for '{sanitized_label}': {e_harm}"
            except Exception as e_chord_parse: parse_failure_reason = f"Unexpected parse error for '{sanitized_label}': {e_chord_parse}"

            if not m21_cs_obj and sanitized_label and sanitized_label.lower() != "rest":
                self.logger.warning(f"BassGen: Chord '{chord_label_str}' (sanitized: '{sanitized_label}') could not be fully parsed ({parse_failure_reason}). Attempting root-only fallback.")
                root_only_match = _ROOT_RE_STRICT.match(sanitized_label if sanitized_label else "")
                if root_only_match:
                    try: m21_cs_obj = harmony.ChordSymbol(root_only_match.group(0)); self.logger.info(f"BassGen: Fallback to root: '{m21_cs_obj.figure}' for original '{chord_label_str}'.")
                    except Exception as e_root_parse: self.logger.error(f"BassGen: Could not even parse root '{root_only_match.group(0)}' from '{chord_label_str}': {e_root_parse}. Skipping block."); continue
                else: self.logger.error(f"BassGen: Could not extract root from '{sanitized_label}' after sanitize failure ({parse_failure_reason}). Skipping block."); continue
            elif not m21_cs_obj and (not sanitized_label or sanitized_label.lower() != "rest"): self.logger.error(f"BassGen: No valid chord or root for block {blk_idx+1} (Label: '{chord_label_str}', Sanitized: '{sanitized_label}', Reason: {parse_failure_reason}). Skipping."); continue

            pattern_details = self._get_rhythm_pattern_details(final_bass_params.get("rhythm_key"))
            if not pattern_details: self.logger.warning(f'Skipped block {blk_idx+1} in compose: chord="{chord_label_str}", reason="No pattern_details for rhythm_key {final_bass_params.get("rhythm_key")}"'); continue
            
            # base_velocity は final_bass_params から取得 (override適用済み)
            base_vel = final_bass_params.get("velocity", pattern_details.get("velocity_base", 70))
            target_oct = final_bass_params.get("octave", pattern_details.get("target_octave", 2))
            section_tonic = blk_data.get("tonic_of_section", self.global_key_tonic); section_mode = blk_data.get("mode", self.global_key_mode)
            current_m21_scale = ScaleRegistry.get(section_tonic, section_mode)
            if not current_m21_scale: current_m21_scale = music21.scale.MajorScale("C")
            next_chord_root_pitch: Optional[pitch.Pitch] = None
            if blk_idx + 1 < len(processed_blocks):
                next_blk_data = processed_blocks[blk_idx + 1]; next_chord_label_str = next_blk_data.get("chord_label")
                if next_chord_label_str:
                    next_sanitized_label = sanitize_chord_label(next_chord_label_str)
                    if next_sanitized_label and next_sanitized_label.lower() != "rest":
                        try: next_cs_obj = harmony.ChordSymbol(next_sanitized_label);
                        except Exception: next_cs_obj = None
                        if next_cs_obj and next_cs_obj.root(): next_chord_root_pitch = next_cs_obj.root()
            
            generated_notes_for_block: List[Tuple[float, music21.note.Note]] = []
            if m21_cs_obj:
                if "pattern_type" in pattern_details and isinstance(pattern_details["pattern_type"], str) and "algorithmic" in pattern_details["pattern_type"]:
                    algo_options = pattern_details.get("options", {}).copy() # パターン固有のオプション
                    # final_bass_params の中の "options" をマージ (chordmapやoverride由来)
                    algo_options.update(final_bass_params.get("options", {}))
                    
                    # weak_beat_style など、final_bass_params 直下のキーもアルゴリズムオプションとして渡す
                    # (ただし、algo_options内の同名キーを上書きしないように注意)
                    for k in ["weak_beat_style", "approach_on_4th_beat", "approach_style_on_4th"]:
                        if k in final_bass_params and k not in algo_options : # algo_optionsになければ追加
                             algo_options[k] = final_bass_params[k]

                    generated_notes_for_block = self._generate_algorithmic_pattern(
                        pattern_details["pattern_type"], m21_cs_obj, algo_options,
                        base_vel, target_oct, 0.0, block_q_length, current_m21_scale,
                        next_chord_root_pitch, section_overrides=part_specific_overrides_model
                    )
                elif "pattern" in pattern_details and isinstance(pattern_details["pattern"], list):
                    generated_notes_for_block = self._generate_notes_from_fixed_pattern(
                        pattern_details["pattern"], m21_cs_obj, base_vel, target_oct, block_q_length, current_m21_scale
                    )
            
            for rel_offset, note_obj in generated_notes_for_block:
                abs_note_offset = block_abs_offset + rel_offset
                end_of_note = abs_note_offset + note_obj.duration.quarterLength
                end_of_block = block_abs_offset + block_q_length
                if end_of_note > end_of_block + 0.001:
                    new_dur = end_of_block - abs_note_offset
                    if new_dur > MIN_NOTE_DURATION_QL / 2: note_obj.duration.quarterLength = new_dur
                    else: continue
                if note_obj.duration.quarterLength >= MIN_NOTE_DURATION_QL / 2:
                     bass_part.insert(abs_note_offset, note_obj)
                else: self.logger.debug(f"BassGen: Final note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} is too short. Skipping.")
        
        if part_overall_humanize_params and part_overall_humanize_params.get("humanize_opt", False):
            try:
                bass_part_humanized = apply_humanization_to_part(bass_part, template_name=part_overall_humanize_params.get("template_name"), custom_params=part_overall_humanize_params.get("custom_params"))
                if isinstance(bass_part_humanized, stream.Part): bass_part_humanized.id = "Bass";
                bass_part = bass_part_humanized
            except Exception as e_hum: self.logger.error(f"BassGen: Error during bass part humanization: {e_hum}", exc_info=True)
        
        if return_pretty_midi: return None
        return bass_part

# --- END OF FILE generator/bass_generator.py ---