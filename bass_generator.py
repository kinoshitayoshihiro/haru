# --- START OF FILE generator/bass_generator.py (オフセット計算修正版) ---
import music21
import logging
from music21 import stream, note, chord as m21chord, harmony, pitch, tempo, meter, instrument as m21instrument, key, interval, scale
import random
from typing import List, Dict, Optional, Any, Tuple, Union, cast, Sequence

try:
    from utilities.core_music_utils import get_time_signature_object, sanitize_chord_label, MIN_NOTE_DURATION_QL, _ROOT_RE_STRICT
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
    from utilities.scale_registry import ScaleRegistry
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


class BassGenerator:
    def __init__(self, rhythm_library: Optional[Dict[str, Dict]] = None, default_instrument: m21instrument.Instrument = m21instrument.AcousticBass(), global_tempo: int = 120, global_time_signature: str = "4/4", global_key_tonic: str = "C", global_key_mode: str = "major", rng_seed: Optional[int] = None):
        self.logger = logging.getLogger(__name__)
        self.bass_rhythm_library = rhythm_library if rhythm_library else {}
        if not self.bass_rhythm_library: self.logger.warning("BassGenerator: No bass rhythm patterns provided in the rhythm library. Using internal defaults only.")
        self.default_instrument = default_instrument; self.global_tempo = global_tempo; self.global_time_signature_str = global_time_signature
        try: self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        except Exception as e_ts_init: self.logger.error(f"BassGenerator init: Error initializing time signature from '{global_time_signature}': {e_ts_init}. Defaulting to 4/4.", exc_info=True); self.global_time_signature_obj = meter.TimeSignature("4/4")
        self.global_key_tonic = global_key_tonic; self.global_key_mode = global_key_mode
        if rng_seed is not None: self.rng = random.Random(rng_seed)
        else: self.rng = random.Random()
        if "basic_chord_tone_quarters" not in self.bass_rhythm_library: self.bass_rhythm_library["basic_chord_tone_quarters"] = {"description": "Basic quarter note pattern emphasizing root and fifth/third on strong beats.", "tags": ["bass", "default", "quarter_notes", "chord_tones"], "pattern_type": "algorithmic_chord_tone_quarters", "options": {"base_velocity": 85, "strong_beat_velocity_boost": 15, "off_beat_velocity_reduction": 5, "target_octave": 2 }}; self.logger.info("BassGenerator: Added 'basic_chord_tone_quarters' algorithmic pattern to internal library.")
        if "bass_quarter_notes" not in self.bass_rhythm_library: self.bass_rhythm_library["bass_quarter_notes"] = {"description": "Default bass line - simple quarter notes on root.", "tags": ["bass", "default", "quarter_notes", "root"], "pattern": [{"offset": 0.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"}, {"offset": 1.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}, {"offset": 2.0, "duration": 1.0, "velocity_factor": 0.75, "type": "root"}, {"offset": 3.0, "duration": 1.0, "velocity_factor": 0.7, "type": "root"}]}
        if "root_only" not in self.bass_rhythm_library: self.bass_rhythm_library["root_only"] = {"description": "Fallback whole-note roots only.", "tags": ["bass", "fallback", "long_notes", "root"], "pattern_type": "algorithmic_root_only", "pattern": [{"offset": 0.0, "duration": 4.0, "velocity_factor": 0.6}]}

    def _get_rhythm_pattern_details(self, rhythm_key: str) -> Dict[str, Any]:
        default_rhythm = self.bass_rhythm_library.get("basic_chord_tone_quarters"); details = self.bass_rhythm_library.get(rhythm_key)
        if not details: self.logger.warning(f"Bass rhythm key '{rhythm_key}' not found. Using 'basic_chord_tone_quarters' as fallback."); return default_rhythm if default_rhythm else {}
        if "pattern_type" in details and isinstance(details["pattern_type"], str):
            if "pattern" not in details: details["pattern"] = [] 
        elif "pattern" not in details or not isinstance(details["pattern"], list): self.logger.warning(f"Bass rhythm key '{rhythm_key}' has no 'pattern_type' and invalid or missing 'pattern'. Using fallback 'basic_chord_tone_quarters'."); return default_rhythm if default_rhythm else {}
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
        # block_offset_ignored はこの関数内では使用しない (相対オフセットを返すため)
        notes: List[Tuple[float, music21.note.Note]] = []
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
            elif note_type == "approach" and root_pitch_obj: chosen_pitch_base = root_pitch_obj.transpose(-1)
            if not chosen_pitch_base and root_pitch_obj: chosen_pitch_base = root_pitch_obj
            if chosen_pitch_base:
                midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch
                n.duration = music21.duration.Duration(duration_ql); n.volume.velocity = final_velocity
                if p_event.get("glide_to_next", False): n.tie = music21.tie.Tie("start")
                notes.append((offset_in_block, n)) # ★★★ block_offset を加算しない ★★★
        return notes

    def _generate_algorithmic_pattern(self, pattern_type: str, m21_cs: harmony.ChordSymbol, options: Dict[str, Any], base_velocity: int, target_octave: int, block_offset_ignored: float, block_duration: float, current_scale: music21.scale.ConcreteScale) -> List[Tuple[float, music21.note.Note]]:
        # block_offset_ignored はこの関数内では使用しない (相対オフセットを返すため)
        notes: List[Tuple[float, music21.note.Note]] = []
        if not m21_cs or not m21_cs.pitches: return notes
        root_note_obj = m21_cs.root()
        if not root_note_obj: return notes
        
        if pattern_type == "algorithmic_chord_tone_quarters":
            strong_beat_vel_boost = options.get("strong_beat_velocity_boost", 15); off_beat_vel_reduction = options.get("off_beat_velocity_reduction", 5)
            beats_per_measure_in_block = self.global_time_signature_obj.beatCount; num_beats_to_generate = int(block_duration)
            for beat_idx in range(num_beats_to_generate):
                current_rel_offset = beat_idx * 1.0 # ブロック内相対オフセット
                if current_rel_offset >= block_duration - MIN_NOTE_DURATION_QL / 2 : break
                chosen_pitch_base: Optional[pitch.Pitch] = None; current_velocity = base_velocity; beat_in_measure = beat_idx % beats_per_measure_in_block
                if beat_in_measure == 0 : chosen_pitch_base = root_note_obj; current_velocity = min(127, base_velocity + strong_beat_vel_boost)
                elif beats_per_measure_in_block >= 4 and beat_in_measure == (beats_per_measure_in_block // 2) : 
                    if m21_cs.fifth: chosen_pitch_base = m21_cs.fifth
                    elif m21_cs.third: chosen_pitch_base = m21_cs.third
                    else: chosen_pitch_base = root_note_obj
                    current_velocity = min(127, base_velocity + (strong_beat_vel_boost // 2))
                else: chosen_pitch_base = root_note_obj; current_velocity = max(1, base_velocity - off_beat_vel_reduction)
                if chosen_pitch_base:
                    midi_pitch = self._get_bass_pitch_in_octave(chosen_pitch_base, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch
                    note_duration_ql = min(1.0, block_duration - current_rel_offset)
                    if note_duration_ql < MIN_NOTE_DURATION_QL: continue
                    n.duration.quarterLength = note_duration_ql; n.volume.velocity = current_velocity
                    notes.append((current_rel_offset, n)) # ★★★ block_offset を加算しない ★★★
        elif pattern_type == "algorithmic_root_only":
            note_duration_ql = options.get("note_duration_ql", block_duration);
            if note_duration_ql <= 0: note_duration_ql = block_duration
            num_notes = int(block_duration / note_duration_ql) if note_duration_ql > 0 else 0
            for i in range(num_notes):
                current_rel_offset = i * note_duration_ql # ブロック内相対オフセット
                midi_pitch = self._get_bass_pitch_in_octave(root_note_obj, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch; n.duration.quarterLength = note_duration_ql
                n.volume.velocity = base_velocity; notes.append((current_rel_offset, n)) # ★★★ block_offset を加算しない ★★★
        # ... (他のアルゴリズムパターンも同様に、notes.append の第一引数を相対オフセットにする修正が必要) ...
        # (例: algorithmic_root_fifth, algorithmic_walking, walking_8ths, half_time_pop など)
        # 以下、walking_8ths と half_time_pop の修正例
        elif pattern_type == "walking_8ths":
            swing_ratio = options.get("swing_ratio", 0.0); approach_prob = options.get("approach_note_prob", 0.4); step_ql = 0.5
            current_rel_offset = 0.0; idx = 0; scale_pitches_objs: List[pitch.Pitch] = []
            if current_scale and current_scale.tonic: lower_bound = pitch.Pitch(f"{current_scale.tonic.name}{target_octave-1}"); upper_bound = pitch.Pitch(f"{current_scale.tonic.name}{target_octave+2}"); scale_pitches_objs = current_scale.getPitches(lower_bound, upper_bound)
            if not scale_pitches_objs and root_note_obj: scale_pitches_objs = [root_note_obj.transpose(i) for i in [-2,-1,0,1,2,3,4,5]]
            if block_duration < step_ql : return notes
            max_iterations = int(block_duration / step_ql) * 2 + 1; loop_count = 0
            while current_rel_offset + step_ql <= block_duration + (MIN_NOTE_DURATION_QL / 4) and loop_count < max_iterations:
                note_obj_to_add_pitch: Optional[pitch.Pitch] = None; vel = base_velocity; is_approach_note = False; actual_step_ql = step_ql
                if idx % 2 == 0: potential_chord_tones = [ct for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth] if ct];
                else:
                    if self.rng.random() < approach_prob and root_note_obj : root_pc = root_note_obj.pitchClass; approach_pc_int = (root_pc + self.rng.choice([-1, 1])) % 12; note_obj_to_add_pitch = pitch.Pitch(); note_obj_to_add_pitch.pitchClass = approach_pc_int; vel = base_velocity - 10; is_approach_note = True
                    else: 
                        if scale_pitches_objs: chord_tone_pcs = [ct.pitchClass for ct in [m21_cs.root(), m21_cs.third, m21_cs.fifth, m21_cs.seventh] if ct]; non_chord_tones_in_scale = [p_s for p_s in scale_pitches_objs if p_s.pitchClass not in chord_tone_pcs];
                        elif root_note_obj: note_obj_to_add_pitch = root_note_obj
                        vel = base_velocity - 5
                if note_obj_to_add_pitch:
                    midi_pitch = self._get_bass_pitch_in_octave(note_obj_to_add_pitch, target_octave); n = music21.note.Note(); n.pitch.midi = midi_pitch
                    if swing_ratio > 0 and not is_approach_note:
                        if idx % 2 == 0: actual_step_ql = step_ql * (1 + swing_ratio)
                        else: actual_step_ql = step_ql * (1 - swing_ratio)
                    n.duration.quarterLength = min(actual_step_ql, block_duration - current_rel_offset)
                    if n.duration.quarterLength < MIN_NOTE_DURATION_QL / 2: loop_count +=1; continue
                    n.volume.velocity = vel; notes.append((current_rel_offset, n)) # ★★★ block_offset を加算しない ★★★
                current_rel_offset += actual_step_ql; idx += 1; loop_count += 1
            if loop_count >= max_iterations: self.logger.warning(f"BassGen (walking_8ths): Max iterations reached.")
        elif pattern_type == "half_time_pop":
            main_note_duration = block_duration; p_root = root_note_obj; midi_p_root = self._get_bass_pitch_in_octave(p_root, target_octave)
            n_main = music21.note.Note(); n_main.pitch.midi = midi_p_root; n_main.duration.quarterLength = main_note_duration; n_main.volume.velocity = base_velocity
            notes.append((0.0, n_main)) # ★★★ ブロック先頭からの相対オフセットは0.0 ★★★
            if options.get("ghost_on_beat_2_and_a_half", False) and block_duration >= 2.5: 
                ghost_note_rel_offset = 1.5 
                # block_offset (絶対) ではなく block_duration (相対) で比較
                if ghost_note_rel_offset < block_duration - MIN_NOTE_DURATION_QL / 2 :
                    p_ghost = root_note_obj; midi_p_ghost = self._get_bass_pitch_in_octave(p_ghost, target_octave); n_ghost = music21.note.Note(); n_ghost.pitch.midi = midi_p_ghost
                    n_ghost.duration.quarterLength = 0.25; n_ghost.volume.velocity = int(base_velocity * 0.6)
                    notes.append((ghost_note_rel_offset, n_ghost)) # ★★★ 相対オフセット ★★★
        else: # フォールバック
            default_algo_options = self.bass_rhythm_library.get("basic_chord_tone_quarters",{}).get("options",{})
            notes.extend(self._generate_algorithmic_pattern("algorithmic_chord_tone_quarters", m21_cs, default_algo_options, base_velocity, target_octave, 0.0, block_duration, current_scale)) # block_offset_ignored は 0.0
        return notes

    def compose(self, processed_blocks: Sequence[Dict[str, Any]], return_pretty_midi: bool = False) -> Union[stream.Part, Any]:
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
            bass_params_for_block = blk_data.get("part_params", {}).get("bass", {})
            if not bass_params_for_block: bass_params_for_block = {"rhythm_key": "basic_chord_tone_quarters", "velocity": 70, "octave": 2}; self.logger.debug(f"BassGenerator: No bass params for block {blk_idx+1}. Using hardcoded defaults.")
            if blk_idx == 0: part_overall_humanize_params = {"humanize_opt": bass_params_for_block.get("humanize_opt", True), "template_name": bass_params_for_block.get("template_name", "default_subtle"), "custom_params": bass_params_for_block.get("custom_params", {})}
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
            rhythm_key_from_params = bass_params_for_block.get("rhythm_key", bass_params_for_block.get("style", "basic_chord_tone_quarters")) 
            pattern_details = self._get_rhythm_pattern_details(rhythm_key_from_params)
            if not pattern_details: self.logger.warning(f'Skipped block {blk_idx+1} in compose: chord="{chord_label_str}", reason="No pattern_details for rhythm_key {rhythm_key_from_params}"'); continue
            base_vel = bass_params_for_block.get("velocity", 70); target_oct = bass_params_for_block.get("octave", 2)  
            section_tonic = blk_data.get("tonic_of_section", self.global_key_tonic); section_mode = blk_data.get("mode", self.global_key_mode)
            current_m21_scale = ScaleRegistry.get(section_tonic, section_mode)
            if not current_m21_scale: current_m21_scale = music21.scale.MajorScale("C")
            generated_notes_for_block: List[Tuple[float, music21.note.Note]] = []
            if m21_cs_obj:
                if "pattern_type" in pattern_details and isinstance(pattern_details["pattern_type"], str):
                    algo_options = pattern_details.get("options", {}); algo_options["base_velocity"] = base_vel; algo_options["target_octave"] = target_oct
                    generated_notes_for_block = self._generate_algorithmic_pattern( pattern_details["pattern_type"], m21_cs_obj, algo_options, base_vel, target_oct, 0.0, block_q_length, current_m21_scale) # block_offset_ignored を 0.0 に
                elif "pattern" in pattern_details and isinstance(pattern_details["pattern"], list):
                    generated_notes_for_block = self._generate_notes_from_fixed_pattern( pattern_details["pattern"], m21_cs_obj, base_vel, target_oct, 0.0, block_q_length, current_m21_scale) # block_offset_ignored を 0.0 に
            
            # --- o3さん提案の解決策 A を適用 ---
            for rel_offset, note_obj in generated_notes_for_block: 
                abs_note_offset = block_abs_offset + rel_offset   # ★★★ 絶対オフセットを正しく計算 ★★★
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
            # --- 修正ここまで ---

        if part_overall_humanize_params and part_overall_humanize_params.get("humanize_opt", False):
            try:
                bass_part_humanized = apply_humanization_to_part(bass_part, template_name=part_overall_humanize_params.get("template_name"), custom_params=part_overall_humanize_params.get("custom_params"))
                if isinstance(bass_part_humanized, stream.Part): bass_part_humanized.id = "Bass";
            except Exception as e_hum: self.logger.error(f"BassGen: Error during bass part humanization: {e_hum}", exc_info=True)
        if return_pretty_midi: return None 
        return bass_part
# --- END OF FILE generator/bass_generator.py ---
