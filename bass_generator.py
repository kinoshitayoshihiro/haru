# --- START OF FILE generator/bass_generator.py (アプローチノート強化・弱拍3rd/5th実装版) ---
import music21
import logging
from music21 import stream, note, chord as m21chord, harmony, pitch, tempo, meter, instrument as m21instrument, key, interval, scale
import random
from typing import List, Dict, Optional, Any, Tuple, Union, cast, Sequence

try:
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL, _ROOT_RE_STRICT
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
    from utilities.scale_registry import ScaleRegistry
    from .bass_utils import get_approach_note_to_target # ★★★ 新しいヘルパー関数をインポート ★★★
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
    # ダミーの get_approach_note_to_target (インポート失敗時)
    def get_approach_note_to_target(curr, target, scale, allow_chromatic=True, max_interval=2): return target if target else curr

# --- (EMOTION_TO_BUCKET_BASS, BUCKET_TO_PATTERN_BASS, choose_bass_pattern_key は変更なし) ---
EMOTION_TO_BUCKET_BASS: dict[str, str] = { "quiet_pain_and_nascent_strength": "calm", "deep_regret_gratitude_and_realization": "calm", "self_reproach_regret_deep_sadness": "calm", "memory_unresolved_feelings_silence": "calm", "nature_memory_floating_sensation_forgiveness": "calm", "supported_light_longing_for_rebirth": "groovy", "wavering_heart_gratitude_chosen_strength": "groovy", "hope_dawn_light_gentle_guidance": "groovy", "acceptance_of_love_and_pain_hopeful_belief": "energetic", "trial_cry_prayer_unbreakable_heart": "energetic", "reaffirmed_strength_of_love_positive_determination": "energetic", "future_cooperation_our_path_final_resolve_and_liberation": "energetic", "default": "groovy" }
BUCKET_TO_PATTERN_BASS: dict[tuple[str, str], str] = { ("calm", "low"): "root_only", ("calm", "medium_low"): "root_fifth", ("calm", "medium"): "bass_half_time_pop", ("calm", "medium_high"):"bass_half_time_pop", ("calm", "high"): "walking", ("groovy", "low"): "bass_syncopated_rnb", ("groovy", "medium_low"): "walking", ("groovy", "medium"): "bass_walking_8ths", ("groovy", "medium_high"):"bass_walking_8ths", ("groovy", "high"): "bass_funk_octave", ("energetic", "low"): "bass_quarter_notes", ("energetic", "medium_low"): "bass_pump_8th_octaves", ("energetic", "medium"): "bass_pump_8th_octaves", ("energetic", "medium_high"):"bass_funk_octave", ("energetic", "high"): "bass_funk_octave", ("default", "low"): "root_only", ("default", "medium_low"): "bass_quarter_notes", ("default", "medium"): "walking", ("default", "medium_high"):"bass_walking_8ths", ("default", "high"): "bass_pump_8th_octaves", }
def choose_bass_pattern_key(section_musical_intent: dict) -> str:
    emotion = section_musical_intent.get("emotion", "default"); intensity = section_musical_intent.get("intensity", "medium").lower()
    bucket = EMOTION_TO_BUCKET_BASS.get(emotion, "default") 
    pattern_key = BUCKET_TO_PATTERN_BASS.get((bucket, intensity), "bass_quarter_notes") 
    logging.getLogger(__name__).info(f"Bass pattern choice: Emotion='{emotion}', Intensity='{intensity}' -> Bucket='{bucket}' -> PatternKey='{pattern_key}'")
    return pattern_key

class BassGenerator:
    # ... (__init__, _get_rhythm_pattern_details, _get_bass_pitch_in_octave, _generate_notes_from_fixed_pattern は変更なし) ...
    def __init__(self, rhythm_library: Optional[Dict[str, Dict]] = None, default_instrument: m21instrument.Instrument = m21instrument.AcousticBass(), global_tempo: int = 120, global_time_signature: str = "4/4", global_key_tonic: str = "C", global_key_mode: str = "major", rng_seed: Optional[int] = None):
        self.logger = logging.getLogger(__name__); self.bass_rhythm_library = rhythm_library if rhythm_library else {};
        if not self.bass_rhythm_library: self.logger.warning("BassGenerator: No bass rhythm patterns provided. Using internal defaults only.")
        self.default_instrument = default_instrument; self.global_tempo = global_tempo; self.global_time_signature_str = global_time_signature
        try: self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except Exception: self.global_time_signature_obj = meter.TimeSignature("4/4")
        self.global_key_tonic = global_key_tonic; self.global_key_mode = global_key_mode
        if rng_seed is not None: self.rng = random.Random(rng_seed)
        else: self.rng = random.Random()
        if "basic_chord_tone_quarters" not in self.bass_rhythm_library: self.bass_rhythm_library["basic_chord_tone_quarters"] = {"description": "Basic quarter note pattern with configurable weak beats and approach.", "tags": ["bass", "default", "algorithmic"], "pattern_type": "algorithmic_chord_tone_quarters", "options": {"base_velocity": 85, "strong_beat_velocity_boost": 15, "off_beat_velocity_reduction": 5, "target_octave": 2, "weak_beat_style": "root", "approach_on_4th_beat": True, "allow_chromatic_approach_on_4th": True}} # allow_chromatic_approach_on_4th を追加
        if "bass_quarter_notes" not in self.bass_rhythm_library: self.bass_rhythm_library["bass_quarter_notes"] = {"description": "Default fixed quarter notes.", "tags": ["bass", "default", "fixed_pattern"], "pattern_type":"fixed_pattern", "pattern": [{"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"}, {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}, {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"}, {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}]}
        if "root_only" not in self.bass_rhythm_library: self.bass_rhythm_library["root_only"] = {"description": "Fallback whole-note roots.", "tags": ["bass", "fallback", "algorithmic"], "pattern_type": "algorithmic_root_only", "pattern": [{"offset": 0.0, "duration": 4.0, "velocity_factor": 0.6}]}
    def _get_rhythm_pattern_details(self, rhythm_key: str) -> Dict[str, Any]:
        if not rhythm_key: rhythm_key = "basic_chord_tone_quarters"
        default_rhythm = self.bass_rhythm_library.get("basic_chord_tone_quarters"); details = self.bass_rhythm_library.get(rhythm_key)
        if not details: return default_rhythm if default_rhythm else {}
        if "pattern_type" in details and isinstance(details["pattern_type"], str):
            if "pattern" not in details and details["pattern_type"] != "algorithmic_chord_tone_quarters": details["pattern"] = [] 
        elif "pattern" not in details or not isinstance(details["pattern"], list):
            if details.get("pattern_type") != "algorithmic_chord_tone_quarters": return default_rhythm if default_rhythm else {}
        return details
    def _get_bass_pitch_in_octave(self, base_pitch_obj: Optional[pitch.Pitch], target_octave: int) -> int:
        if not base_pitch_obj: return pitch.Pitch(f"C{target_octave}").midi 
        p_new = pitch.Pitch(base_pitch_obj.name); p_new.octave = target_octave; min_bass_midi = 28; max_bass_midi = 60; current_midi = p_new.midi
        while current_midi < min_bass_midi: current_midi += 12
        while current_midi > max_bass_midi:
            if current_midi - 12 >= min_bass_midi: current_midi -= 12
            else: break 
        return max(min_bass_midi, min(current_midi, max_bass_midi))
    def _generate_notes_from_fixed_pattern( self, pattern: List[Dict[str, Any]], m21_cs: harmony.ChordSymbol, base_velocity: int, target_octave: int, block_offset_ignored: float, block_duration: float, current_scale: Optional[music21.scale.ConcreteScale] = None) -> List[Tuple[float, music21.note.Note]]:
        notes: List[Tuple[float, music21.note.Note]] = [];
        if not m21_cs or not m21_cs.pitches: return notes
        root_pitch_obj = m21_cs.root(); third_pitch_obj = m21_cs.third; fifth_pitch_obj = m21_cs.fifth; chord_tones = [p for p in [root_pitch_obj, third_pitch_obj, fifth_pitch_obj] if p]
        for p_event in pattern:
            offset_in_block = p_event.get("offset", 0.0); duration_ql = p_event.get("duration", 1.0); vel_factor = p_event.get("velocity_factor", 1.0); note_type = p_event.get("type", "root").lower()
            final_velocity = max(1, min(127, int(base_velocity * vel_factor))); chosen_pitch_base: Optional[pitch.Pitch] = None
            if note_type == "root" and root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "fifth" and fifth_pitch_obj: chosen_pitch_base = fifth_pitch_obj
            elif note_type == "third" and third_pitch_obj: chosen_pitch_base = third_pitch_obj
            elif note_type == "octave_root" and root_pitch_obj: chosen_pitch_base = root_note_obj
            elif note_type == "random_chord_tone" and chord_tones: chosen_pitch_base = self.rng.choice(chord_tones)
            elif note_type == "scale_tone" and current_scale:
                try: p_s = current_scale.pitchFromDegree(self.rng.choice([1,2,3,4,5,6,7]))
                except Exception: p_s = None
                if p_s: chosen_pitch_base = p_s
                elif root_pitch_obj: chosen_pitch_base = root_pitch_obj
            elif note_type == "approach" and root_pitch_obj: chosen_pitch_base = root_pitch_obj.transpose(-1)
            if not chosen_pitch_base and root_pitch_obj: chosen_pitch_base = root_pitch_obj
            if chosen_pitch_base:
                midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch
                n.duration = music21.duration.Duration(duration_ql); n.volume.velocity = final_velocity
                if p_event.get("glide_to_next", False): n.tie = music21.tie.Tie("start")
                notes.append((offset_in_block, n)) 
        return notes

    def _generate_algorithmic_pattern(self, pattern_type: str, m21_cs: harmony.ChordSymbol, options: Dict[str, Any], base_velocity: int, target_octave: int, block_offset_ignored: float, block_duration: float, current_scale: music21.scale.ConcreteScale, next_chord_root: Optional[pitch.Pitch] = None) -> List[Tuple[float, music21.note.Note]]:
        notes: List[Tuple[float, music21.note.Note]] = []
        if not m21_cs or not m21_cs.pitches: return notes
        root_note_obj = m21_cs.root()
        if not root_note_obj: return notes
        
        if pattern_type == "algorithmic_chord_tone_quarters":
            strong_beat_vel_boost = options.get("strong_beat_velocity_boost", 15)
            off_beat_vel_reduction = options.get("off_beat_velocity_reduction", 5)
            weak_beat_style = options.get("weak_beat_style", "root")
            approach_on_4th_beat_opt = options.get("approach_on_4th_beat", True)
            allow_chromatic_approach = options.get("allow_chromatic_approach_on_4th", True) # 新オプション

            beats_per_measure_in_block = self.global_time_signature_obj.beatCount 
            num_beats_to_generate = int(block_duration)
            
            last_generated_pitch = root_note_obj # アプローチノート選択のために直前の音を保持

            for beat_idx in range(num_beats_to_generate):
                current_rel_offset = beat_idx * 1.0 
                if current_rel_offset >= block_duration - MIN_NOTE_DURATION_QL / 2 : break
                
                beat_in_measure = beat_idx % beats_per_measure_in_block
                chosen_pitch_base: Optional[pitch.Pitch] = None
                current_velocity = base_velocity
                note_duration_ql = min(1.0, block_duration - current_rel_offset)

                if beat_in_measure == 0 : 
                    chosen_pitch_base = root_note_obj
                    current_velocity = min(127, base_velocity + strong_beat_vel_boost)
                elif beats_per_measure_in_block >= 4 and beat_in_measure == (beats_per_measure_in_block // 2) : 
                    if m21_cs.fifth: chosen_pitch_base = m21_cs.fifth
                    elif m21_cs.third: chosen_pitch_base = m21_cs.third
                    else: chosen_pitch_base = root_note_obj
                    current_velocity = min(127, base_velocity + (strong_beat_vel_boost // 2))
                elif approach_on_4th_beat_opt and next_chord_root and beat_in_measure == (beats_per_measure_in_block - 1) and beat_idx < num_beats_to_generate -1 :
                    # ★★★ bass_utils.get_approach_note_to_target を使用 ★★★
                    approach_pitch = get_approach_note_to_target(
                        last_generated_pitch, # 直前の音を渡す
                        next_chord_root, 
                        current_scale, 
                        allow_chromatic=allow_chromatic_approach
                    )
                    if approach_pitch:
                        chosen_pitch_base = approach_pitch
                        self.logger.debug(f"BassGen: Approaching next chord {next_chord_root.name} with {chosen_pitch_base.name} on beat {beat_idx+1}")
                    else: 
                        chosen_pitch_base = root_note_obj # アプローチが見つからなければルート
                    current_velocity = max(1, base_velocity - off_beat_vel_reduction)
                else: 
                    current_velocity = max(1, base_velocity - off_beat_vel_reduction)
                    if weak_beat_style == "third_or_fifth":
                        # 5度があれば5度、なければ3度、それもなければルート
                        if m21_cs.fifth and (not current_scale or current_scale.getScaleDegreeFromPitch(m21_cs.fifth) is not None):
                            chosen_pitch_base = m21_cs.fifth
                        elif m21_cs.third and (not current_scale or current_scale.getScaleDegreeFromPitch(m21_cs.third) is not None):
                            chosen_pitch_base = m21_cs.third
                        else:
                            chosen_pitch_base = root_note_obj
                    elif weak_beat_style == "eighth_roots":
                        for i in range(2):
                            eighth_offset = current_rel_offset + (i * 0.5)
                            if eighth_offset >= block_duration - MIN_NOTE_DURATION_QL / 2: break
                            eighth_duration_ql = min(0.5, block_duration - eighth_offset)
                            if eighth_duration_ql < MIN_NOTE_DURATION_QL: continue
                            midi_pitch_8th = self._get_bass_pitch_in_octave(root_note_obj, target_octave); n8 = music21.note.Note(); n8.pitch.midi = midi_pitch_8th
                            n8.duration.quarterLength = eighth_duration_ql; n8.volume.velocity = current_velocity - (i * 3) 
                            notes.append((eighth_offset, n8)); last_generated_pitch = root_note_obj # 8分音符でも更新
                        continue 
                    else: 
                        chosen_pitch_base = root_note_obj
                
                if chosen_pitch_base:
                    if note_duration_ql < MIN_NOTE_DURATION_QL: continue
                    midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch
                    n.duration.quarterLength = note_duration_ql; n.volume.velocity = current_velocity; notes.append((current_rel_offset, n))
                    last_generated_pitch = chosen_pitch_base # 生成された音で更新
        
        elif pattern_type == "algorithmic_root_only":
            note_duration_ql = options.get("note_duration_ql", block_duration);
            if note_duration_ql <= 0: note_duration_ql = block_duration
            num_notes = int(block_duration / note_duration_ql) if note_duration_ql > 0 else 0
            for i in range(num_notes):
                current_rel_offset = i * note_duration_ql 
                midi_pitch = self._get_bass_pitch_in_octave(root_note_obj, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch; n.duration.quarterLength = note_duration_ql
                n.volume.velocity = base_velocity; notes.append((current_rel_offset, n)) 
        else: 
            default_algo_options = self.bass_rhythm_library.get("basic_chord_tone_quarters",{}).get("options",{})
            notes.extend(self._generate_algorithmic_pattern("algorithmic_chord_tone_quarters", m21_cs, default_algo_options, base_velocity, target_octave, 0.0, block_duration, current_scale, next_chord_root))
        return notes

    def compose(self, processed_blocks: Sequence[Dict[str, Any]], return_pretty_midi: bool = False) -> Union[stream.Part, Any]:
        # ... (composeメソッドの前半は変更なし) ...
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
        part_overall_humanize_params = None
        for blk_idx, blk_data in enumerate(processed_blocks):
            bass_params_from_chordmap = blk_data.get("part_params", {}).get("bass", {})
            block_musical_intent = blk_data.get("musical_intent", {}) 
            rhythm_key_from_params = bass_params_from_chordmap.get("rhythm_key", bass_params_from_chordmap.get("style"))
            if not rhythm_key_from_params:
                # ★★★ blk_data から musical_intent を取得して渡すように修正 ★★★
                # (prepare_processed_stream で blk_data に musical_intent が設定されている前提)
                rhythm_key_from_params = choose_bass_pattern_key(block_musical_intent) 
                self.logger.info(f"Bass rhythm key for block {blk_idx} chosen by emotion: {rhythm_key_from_params}")
            if not rhythm_key_from_params: rhythm_key_from_params = "basic_chord_tone_quarters"
            if not bass_params_from_chordmap: bass_params_from_chordmap = {"rhythm_key": rhythm_key_from_params, "velocity": 70, "octave": 2}; self.logger.debug(f"BassGenerator: No bass params for block {blk_idx+1}. Using emotion-driven or hardcoded defaults.")
            if blk_idx == 0: part_overall_humanize_params = {"humanize_opt": bass_params_from_chordmap.get("humanize_opt", True), "template_name": bass_params_from_chordmap.get("template_name", "default_subtle"), "custom_params": bass_params_from_chordmap.get("custom_params", {})}
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
                    except Exception as e_root_parse: self.logger.error(f"BassGen: Could not even parse root '{root_only_match.group(0)}' from '{chord_label_str}': {e_root_parse}. Skipping block."); self.logger.warning(f'Skipped block {blk_idx+1} in compose: chord="{chord_label_str}", reason="Root parse failed after sanitize failure ({parse_failure_reason})"') ; continue
                else: self.logger.error(f"BassGen: Could not extract root from '{sanitized_label}' after sanitize failure ({parse_failure_reason}). Skipping block."); self.logger.warning(f'Skipped block {blk_idx+1} in compose: chord="{chord_label_str}", reason="No root found after sanitize failure ({parse_failure_reason})"') ; continue
            elif not m21_cs_obj and (not sanitized_label or sanitized_label.lower() != "rest"): self.logger.error(f"BassGen: No valid chord or root for block {blk_idx+1} (Label: '{chord_label_str}', Sanitized: '{sanitized_label}', Reason: {parse_failure_reason}). Skipping."); self.logger.warning(f'Skipped block {blk_idx+1} in compose: chord="{chord_label_str}", reason="Final parse/root extraction failed ({parse_failure_reason})"') ; continue
            pattern_details = self._get_rhythm_pattern_details(rhythm_key_from_params) 
            if not pattern_details: self.logger.warning(f'Skipped block {blk_idx+1} in compose: chord="{chord_label_str}", reason="No pattern_details for rhythm_key {rhythm_key_from_params}"'); continue
            base_vel = bass_params_from_chordmap.get("velocity", pattern_details.get("velocity_base", 70)) 
            target_oct = bass_params_from_chordmap.get("octave", pattern_details.get("target_octave", 2))  
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
                if "pattern_type" in pattern_details and isinstance(pattern_details["pattern_type"], str):
                    algo_options = pattern_details.get("options", {}); algo_options.update(bass_params_from_chordmap.get("options", {})) # chordmapのoptionsを優先
                    algo_options["base_velocity"] = base_vel; algo_options["target_octave"] = target_oct
                    algo_options["weak_beat_style"] = bass_params_from_chordmap.get("weak_beat_style", algo_options.get("weak_beat_style", "root"))
                    algo_options["approach_on_4th_beat"] = bass_params_from_chordmap.get("approach_on_4th_beat", algo_options.get("approach_on_4th_beat", True))
                    algo_options["allow_chromatic_approach_on_4th"] = bass_params_from_chordmap.get("allow_chromatic_approach_on_4th", algo_options.get("allow_chromatic_approach_on_4th", True))

                    generated_notes_for_block = self._generate_algorithmic_pattern( pattern_details["pattern_type"], m21_cs_obj, algo_options, base_vel, target_oct, 0.0, block_q_length, current_m21_scale, next_chord_root_pitch)
                elif "pattern" in pattern_details and isinstance(pattern_details["pattern"], list):
                    generated_notes_for_block = self._generate_notes_from_fixed_pattern( pattern_details["pattern"], m21_cs_obj, base_vel, target_oct, 0.0, block_q_length, current_m21_scale)
            for rel_offset, note_obj in generated_notes_for_block: 
                abs_note_offset = block_abs_offset + rel_offset   
                end_of_note = abs_note_offset + note_obj.duration.quarterLength
                end_of_block = block_abs_offset + block_q_length
                if end_of_note > end_of_block + 0.001: 
                    new_dur = end_of_block - abs_note_offset
                    if new_dur > MIN_NOTE_DURATION_QL / 2: note_obj.duration.quarterLength = new_dur
                    else: continue
                if m21_cs_obj: self.logger.info(f"DEBUG Bass Insert: Chord='{m21_cs_obj.figure}', BlockOffset={block_abs_offset:.2f}, RelOffset={rel_offset:.2f}, NoteAbsOffset={abs_note_offset:.2f}, Pitch={note_obj.pitch.nameWithOctave if note_obj.pitch else 'N/A'}, Duration={note_obj.duration.quarterLength:.2f}")
                else: self.logger.info(f"DEBUG Bass Insert (Chord may be Rest or Unparsed): OriginalLabel='{chord_label_str}', Sanitized='{sanitized_label}', BlockOffset={block_abs_offset:.2f}, RelOffset={rel_offset:.2f}, NoteAbsOffset={abs_note_offset:.2f}, Pitch={note_obj.pitch.nameWithOctave if note_obj.pitch else 'N/A'}, Duration={note_obj.duration.quarterLength:.2f}")
                if note_obj.duration.quarterLength >= MIN_NOTE_DURATION_QL / 2:
                     bass_part.insert(abs_note_offset, note_obj)
                else: self.logger.debug(f"BassGen: Final note for {m21_cs_obj.figure if m21_cs_obj else 'N/A'} at {abs_note_offset:.2f} is too short. Skipping.")
        if part_overall_humanize_params and part_overall_humanize_params.get("humanize_opt", False):
            try:
                bass_part_humanized = apply_humanization_to_part(bass_part, template_name=part_overall_humanize_params.get("template_name"), custom_params=part_overall_humanize_params.get("custom_params"))
                if isinstance(bass_part_humanized, stream.Part): bass_part_humanized.id = "Bass";
            except Exception as e_hum: self.logger.error(f"BassGen: Error during bass part humanization: {e_hum}", exc_info=True)
        if return_pretty_midi: return None 
        return bass_part
# --- END OF FILE generator/bass_generator.py ---
