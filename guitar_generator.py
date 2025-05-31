# --- START OF FILE generator/guitar_generator.py (感情スタイル選択機能・Override対応・copyインポート・rhythm_lib修正版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence, Union, cast
import copy

# music21 のサブモジュールを正しい形式でインポート
import music21.stream as stream
import music21.note as note
import music21.harmony as harmony
import music21.pitch as pitch
import music21.meter as meter
import music21.duration as duration
import music21.instrument as m21instrument
# import music21.scale as scale
import music21.interval as interval
import music21.tempo as tempo
# import music21.key as key
import music21.chord      as m21chord
import music21.articulations as articulations
import music21.volume as m21volume
# import music21.expressions as expressions

import random
import logging
import math

try:
    from utilities.override_loader import get_part_override, Overrides # Overridesもインポート
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("GuitarGen: Could not import from utilities. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"; return meter.TimeSignature(ts_str)
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
        if not label or label.strip().lower() in ["rest", "r", "n.c.", "nc", "none", "-"]: return None
        return label.strip()
    def apply_humanization_to_part(part, template_name=None, custom_params=None): return part
    HUMANIZATION_TEMPLATES = {}
    class DummyPartOverride: model_config = {}; model_fields = {}
    def get_part_override(overrides, section, part) -> DummyPartOverride: return DummyPartOverride()
    class Overrides: root = {} # ダミー


logger = logging.getLogger(__name__)

DEFAULT_GUITAR_OCTAVE_RANGE: Tuple[int, int] = (2, 5)
GUITAR_STRUM_DELAY_QL: float = 0.02
MIN_STRUM_NOTE_DURATION_QL: float = 0.05
STYLE_BLOCK_CHORD = "block_chord"; STYLE_STRUM_BASIC = "strum_basic"; STYLE_ARPEGGIO = "arpeggio"
STYLE_POWER_CHORDS = "power_chords"; STYLE_MUTED_RHYTHM = "muted_rhythm"; STYLE_SINGLE_NOTE_LINE = "single_note_line"

EMOTION_INTENSITY_MAP: Dict[Tuple[str, str], str] = {
    ("quiet_pain_and_nascent_strength", "low"): "guitar_ballad_arpeggio",
    ("deep_regret_gratitude_and_realization", "medium_low"): "guitar_ballad_arpeggio",
    ("acceptance_of_love_and_pain_hopeful_belief", "medium_high"): "guitar_folk_strum_simple",
    ("self_reproach_regret_deep_sadness", "medium_low"): "guitar_ballad_arpeggio",
    ("supported_light_longing_for_rebirth", "medium"): "guitar_folk_strum_simple",
    ("reflective_transition_instrumental_passage", "medium_low"): "guitar_ballad_arpeggio",
    ("trial_cry_prayer_unbreakable_heart", "medium_high"): "guitar_power_chord_8ths",
    ("memory_unresolved_feelings_silence", "low"): "guitar_ballad_arpeggio",
    ("wavering_heart_gratitude_chosen_strength", "medium"): "guitar_folk_strum_simple",
    ("reaffirmed_strength_of_love_positive_determination", "high"): "guitar_power_chord_8ths",
    ("hope_dawn_light_gentle_guidance", "medium"): "guitar_folk_strum_simple",
    ("nature_memory_floating_sensation_forgiveness", "medium_low"): "guitar_ballad_arpeggio",
    ("future_cooperation_our_path_final_resolve_and_liberation", "high_to_very_high_then_fade"): "guitar_power_chord_8ths",
    ("default", "default"): "guitar_default_quarters",
    ("default", "low"): "guitar_ballad_arpeggio",
    ("default", "medium_low"): "guitar_ballad_arpeggio",
    ("default", "medium"): "guitar_folk_strum_simple",
    ("default", "medium_high"): "guitar_folk_strum_simple",
    ("default", "high"): "guitar_power_chord_8ths",
}
DEFAULT_GUITAR_STYLE_KEY = "guitar_default_quarters"

class GuitarStyleSelector:
    def __init__(self, mapping: Dict[Tuple[str, str], str] | None = None):
        self.mapping = mapping if mapping is not None else EMOTION_INTENSITY_MAP

    def select(self, *,
               emotion: str | None,
               intensity: str | None,
               cli_override: str | None = None,
               part_params_override_rhythm_key: str | None = None,
               rhythm_library_keys: List[str] # ギター専用のリズムキーのリスト
               ) -> str:

        if cli_override and cli_override in rhythm_library_keys:
            logger.info(f"GuitarStyleSelector: Using CLI override for guitar rhythm_key: {cli_override}")
            return cli_override
        elif cli_override:
            logger.warning(f"GuitarStyleSelector: CLI override '{cli_override}' not found in guitar rhythm_library. Ignoring.")

        if part_params_override_rhythm_key and part_params_override_rhythm_key in rhythm_library_keys:
            logger.info(f"GuitarStyleSelector: Using part_params_override (rhythm_key): {part_params_override_rhythm_key}")
            return part_params_override_rhythm_key
        elif part_params_override_rhythm_key:
             logger.warning(f"GuitarStyleSelector: part_params_override_rhythm_key '{part_params_override_rhythm_key}' not found in guitar rhythm_library. Ignoring.")

        effective_emotion = (emotion or "default").lower()
        effective_intensity = (intensity or "default").lower()
        key = (effective_emotion, effective_intensity)
        style_from_map = self.mapping.get(key)

        if style_from_map and style_from_map in rhythm_library_keys:
            logger.info(f"GuitarStyleSelector: Auto-selected guitar rhythm_key via EMOTION_INTENSITY_MAP: {style_from_map} for ({effective_emotion}, {effective_intensity})")
            return style_from_map
        elif style_from_map:
            logger.warning(f"GuitarStyleSelector: Style from map '{style_from_map}' not in guitar rhythm_library. Trying fallbacks.")

        style_emo_default = self.mapping.get((effective_emotion, "default"))
        if style_emo_default and style_emo_default in rhythm_library_keys:
             logger.info(f"GuitarStyleSelector: No direct map. Using emotion-default: {style_emo_default}")
             return style_emo_default

        style_int_default = self.mapping.get(("default", effective_intensity))
        if style_int_default and style_int_default in rhythm_library_keys:
            logger.info(f"GuitarStyleSelector: No direct map. Using intensity-default: {style_int_default}")
            return style_int_default

        logger.warning(f"GuitarStyleSelector: No mapping for ({effective_emotion}, {effective_intensity}) or fallbacks not in guitar library; falling back to {DEFAULT_GUITAR_STYLE_KEY}")
        if DEFAULT_GUITAR_STYLE_KEY in rhythm_library_keys:
            return DEFAULT_GUITAR_STYLE_KEY
        else:
            if rhythm_library_keys: return rhythm_library_keys[0]
            logger.error("GuitarStyleSelector: CRITICAL - No guitar rhythm keys available in library, not even default. Returning empty string.")
            return ""

class GuitarGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None, # これは rhythm_library.json 全体
                 default_instrument=m21instrument.AcousticGuitar(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        full_rhythm_library = rhythm_library if rhythm_library is not None else {}
        self.rhythm_library = full_rhythm_library.get("guitar_patterns", {}) # ★★★ ギター専用パターンを保持 ★★★

        ts_obj_for_default = get_time_signature_object(global_time_signature)
        bar_dur_ql = ts_obj_for_default.barDuration.quarterLength if ts_obj_for_default else 4.0
        if "guitar_default_quarters" not in self.rhythm_library: # self.rhythm_library はギターパターンを指す
             self.rhythm_library["guitar_default_quarters"] = {
                 "description": "Default quarter note strums/hits",
                 "pattern": [{"offset":i, "duration":1.0, "velocity_factor":0.8-(i%2*0.05)} for i in range(int(bar_dur_ql))],
                 "reference_duration_ql": bar_dur_ql
            }
             logger.info("GuitarGen: Added 'guitar_default_quarters' to self.rhythm_library (guitar_patterns).")

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        self.style_selector = GuitarStyleSelector()

    def _get_guitar_friendly_voicing(
        self, cs: harmony.ChordSymbol, num_strings: int = 6,
        preferred_octave_bottom: int = 2,
    ) -> List[pitch.Pitch]:
        if not cs or not cs.pitches: return []
        original_pitches = list(cs.pitches);

        try:
            temp_chord = cs.closedPosition(forceOctave=preferred_octave_bottom, inPlace=False)
            candidate_pitches = sorted(list(temp_chord.pitches), key=lambda p_sort: p_sort.ps)
        except Exception as e_closed_pos:
            logger.warning(f"GuitarGen: Error in closedPosition for {cs.figure}: {e_closed_pos}. Using original pitches.")
            candidate_pitches = sorted(original_pitches, key=lambda p_sort:p_sort.ps)

        if not candidate_pitches:
            logger.warning(f"GuitarGen: No candidate pitches for {cs.figure} after closedPosition. Returning empty.")
            return []

        guitar_min_ps = pitch.Pitch(f"E{DEFAULT_GUITAR_OCTAVE_RANGE[0]}").ps
        guitar_max_ps = pitch.Pitch(f"B{DEFAULT_GUITAR_OCTAVE_RANGE[1]}").ps

        if candidate_pitches and candidate_pitches[0].ps < guitar_min_ps:
            oct_shift = math.ceil((guitar_min_ps - candidate_pitches[0].ps) / 12.0)
            candidate_pitches = [p_cand.transpose(int(oct_shift * 12)) for p_cand in candidate_pitches]
            candidate_pitches.sort(key=lambda p_sort: p_sort.ps)

        selected_dict: Dict[str, pitch.Pitch] = {}
        for p_cand_select in candidate_pitches:
            if guitar_min_ps <= p_cand_select.ps <= guitar_max_ps:
                if p_cand_select.name not in selected_dict: # オクターブ違いは別として扱うため、nameでチェック
                     selected_dict[p_cand_select.name] = p_cand_select

        final_voiced_pitches = sorted(list(selected_dict.values()), key=lambda p_sort:p_sort.ps)
        return final_voiced_pitches[:num_strings]


    def _create_notes_from_event(
        self, cs: harmony.ChordSymbol, guitar_params: Dict[str, Any],
        event_abs_offset: float, # この関数内では未使用、呼び出し元で最終的なオフセットに使用
        event_duration_ql: float, event_velocity: int
    ) -> List[Union[note.Note, m21chord.Chord]]: # 返す音符リストはイベント内相対オフセットを持つ
        notes_for_event: List[Union[note.Note, m21chord.Chord]] = []
        style = guitar_params.get("guitar_style", STYLE_BLOCK_CHORD)

        num_strings = guitar_params.get("guitar_num_strings", 6)
        preferred_octave_bottom = guitar_params.get("guitar_target_octave", 3)

        chord_pitches = self._get_guitar_friendly_voicing(cs, num_strings, preferred_octave_bottom)
        if not chord_pitches:
            logger.debug(f"GuitarGen: No guitar-friendly pitches for {cs.figure} with style {style}. Skipping event.")
            return []

        is_palm_muted = guitar_params.get("palm_mute", False)

        if style == STYLE_POWER_CHORDS and cs.root():
            p_root = pitch.Pitch(cs.root().name)
            target_power_chord_octave = DEFAULT_GUITAR_OCTAVE_RANGE[0]
            if p_root.octave < target_power_chord_octave: p_root.octave = target_power_chord_octave
            elif p_root.octave > target_power_chord_octave + 1: p_root.octave = target_power_chord_octave + 1

            power_chord_pitches = [p_root, p_root.transpose(interval.PerfectFifth())]
            if num_strings > 2:
                root_oct_up = p_root.transpose(interval.PerfectOctave())
                if root_oct_up.ps <= pitch.Pitch(f"B{DEFAULT_GUITAR_OCTAVE_RANGE[1]}").ps:
                    power_chord_pitches.append(root_oct_up)

            ch = m21chord.Chord(power_chord_pitches[:num_strings], quarterLength=event_duration_ql * (0.7 if is_palm_muted else 0.95))
            for n_in_ch_note in ch.notes:
                n_in_ch_note.volume.velocity = event_velocity
                if is_palm_muted: n_in_ch_note.articulations.append(articulations.Staccatissimo())
            ch.offset = 0.0 # イベント内相対オフセット
            notes_for_event.append(ch)
            return notes_for_event

        if style == STYLE_BLOCK_CHORD:
            ch = m21chord.Chord(chord_pitches, quarterLength=event_duration_ql * (0.7 if is_palm_muted else 0.9))
            for n_in_ch_note in ch.notes:
                n_in_ch_note.volume.velocity = event_velocity
                if is_palm_muted: n_in_ch_note.articulations.append(articulations.Staccatissimo())
            ch.offset = 0.0 # イベント内相対オフセット
            notes_for_event.append(ch)
        elif style == STYLE_STRUM_BASIC:
            event_stroke_dir = guitar_params.get("current_event_stroke", "down")
            is_down = event_stroke_dir == "down"
            play_order = list(reversed(chord_pitches)) if is_down else chord_pitches
            strum_delay = guitar_params.get("strum_delay_ql", GUITAR_STRUM_DELAY_QL)

            for i, p_obj_strum in enumerate(play_order):
                n_strum = note.Note(p_obj_strum)
                n_strum.duration = duration.Duration(quarterLength=max(MIN_STRUM_NOTE_DURATION_QL, event_duration_ql * (0.6 if is_palm_muted else 0.9)))
                n_strum.offset = (i * strum_delay) # イベント内相対オフセット
                vel_adj_range = 10; vel_adj = 0
                if len(play_order) > 1:
                    if is_down: vel_adj = int(((len(play_order)-1-i)/(len(play_order)-1)*vel_adj_range)-(vel_adj_range/2))
                    else: vel_adj = int((i/(len(play_order)-1)*vel_adj_range)-(vel_adj_range/2))
                n_strum.volume = m21volume.Volume(velocity=max(1, min(127, event_velocity + vel_adj)))
                if is_palm_muted: n_strum.articulations.append(articulations.Staccatissimo())
                notes_for_event.append(n_strum)
        elif style == STYLE_ARPEGGIO:
            arp_pattern_indices = guitar_params.get("arpeggio_indices")
            arp_note_dur_ql = guitar_params.get("arpeggio_note_duration_ql", 0.5)
            ordered_arp_pitches: List[pitch.Pitch] = []
            if isinstance(arp_pattern_indices, list) and chord_pitches:
                 ordered_arp_pitches = [chord_pitches[idx % len(chord_pitches)] for idx in arp_pattern_indices]
            else: ordered_arp_pitches = chord_pitches

            current_offset_in_event = 0.0; arp_idx = 0
            while current_offset_in_event < event_duration_ql and ordered_arp_pitches:
                p_play_arp = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                actual_arp_dur = min(arp_note_dur_ql, event_duration_ql - current_offset_in_event)
                if actual_arp_dur < MIN_NOTE_DURATION_QL / 4.0: break
                n_arp = note.Note(p_play_arp, quarterLength=actual_arp_dur * (0.8 if is_palm_muted else 0.95))
                n_arp.volume = m21volume.Volume(velocity=event_velocity)
                n_arp.offset = current_offset_in_event # イベント内相対オフセット
                if is_palm_muted: n_arp.articulations.append(articulations.Staccatissimo())
                notes_for_event.append(n_arp)
                current_offset_in_event += arp_note_dur_ql
                arp_idx += 1
        elif style == STYLE_MUTED_RHYTHM:
            mute_note_dur = guitar_params.get("mute_note_duration_ql", 0.1)
            mute_interval = guitar_params.get("mute_interval_ql", 0.25)
            t_mute = 0.0
            if not chord_pitches: return []
            mute_base_pitch = chord_pitches[0]
            while t_mute < event_duration_ql:
                actual_mute_dur = min(mute_note_dur, event_duration_ql - t_mute)
                if actual_mute_dur < MIN_NOTE_DURATION_QL / 8.0: break
                n_mute = note.Note(mute_base_pitch); n_mute.articulations = [articulations.Staccatissimo()]
                n_mute.duration.quarterLength = actual_mute_dur
                n_mute.volume = m21volume.Volume(velocity=int(event_velocity * 0.6) + random.randint(-5,5))
                n_mute.offset = t_mute # イベント内相対オフセット
                notes_for_event.append(n_mute)
                t_mute += mute_interval
        else:
            logger.warning(f"GuitarGen: Unknown guitar style '{style}' for chord {cs.figure}. No notes generated for this event.")
        return notes_for_event


    def compose(self, processed_chord_stream: List[Dict],
                overrides: Optional[Any] = None, # Overridesモデルを受け取る
                cli_guitar_style_override: Optional[str] = None
                ) -> stream.Part:
        guitar_part = stream.Part(id="Guitar")
        guitar_part.insert(0, self.default_instrument)
        guitar_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        if self.global_time_signature_obj:
            ts_copy_init = meter.TimeSignature(self.global_time_signature_obj.ratioString)
            guitar_part.insert(0, ts_copy_init)
        else:
            guitar_part.insert(0, meter.TimeSignature("4/4"))


        if not processed_chord_stream: return guitar_part
        logger.info(f"GuitarGen: Starting for {len(processed_chord_stream)} blocks.")

        all_generated_elements_for_part: List[Union[note.Note, m21chord.Chord]] = []

        for blk_idx, blk_data_original in enumerate(processed_chord_stream):
            blk_data = copy.deepcopy(blk_data_original)
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", 4.0))
            chord_label_str = blk_data.get("chord_label", "C")
            current_section_name = blk_data.get("section_name", f"UnnamedSection_{blk_idx}")

            part_specific_overrides_model = get_part_override(
                overrides if overrides else Overrides(root={}),
                current_section_name,
                "guitar"
            )

            guitar_params_from_chordmap = blk_data.get("part_params", {}).get("guitar", {})
            final_guitar_params = guitar_params_from_chordmap.copy()
            if part_specific_overrides_model:
                override_dict = part_specific_overrides_model.model_dump(exclude_unset=True)
                if "options" in override_dict and "options" in final_guitar_params and isinstance(final_guitar_params["options"], dict) and isinstance(override_dict["options"], dict):
                    final_guitar_params["options"].update(override_dict.pop("options"))
                final_guitar_params.update(override_dict)

            logger.debug(f"GuitarGen Block {blk_idx+1}: Offset={block_offset_ql}, Dur={block_duration_ql}, Lbl='{chord_label_str}', FinalParams={final_guitar_params}")

            if chord_label_str.lower() in ["rest", "r", "n.c.", "nc", "none", "-"]:
                logger.info(f"GuitarGen: Block {blk_idx+1} ('{chord_label_str}') is a Rest. Skipping.")
                continue

            sanitized_label = sanitize_chord_label(chord_label_str)
            cs_object: Optional[harmony.ChordSymbol] = None
            if sanitized_label:
                try:
                    cs_object = harmony.ChordSymbol(sanitized_label)
                    if not cs_object.pitches: cs_object = None
                except Exception as e_parse_guitar:
                    logger.warning(f"GuitarGen: Error parsing chord '{sanitized_label}': {e_parse_guitar}.")
                    cs_object = None
            if cs_object is None:
                logger.warning(f"GuitarGen: Could not create ChordSymbol for '{chord_label_str}'. Skipping.")
                continue

            current_musical_intent = blk_data.get("musical_intent", {})
            emotion = current_musical_intent.get("emotion")
            intensity = current_musical_intent.get("intensity")
            param_rhythm_key = final_guitar_params.get("guitar_rhythm_key")

            # ★★★ self.rhythm_library はギター専用パターン辞書を指すように __init__ で修正済み ★★★
            final_rhythm_key_selected = self.style_selector.select(
                emotion=emotion,
                intensity=intensity,
                cli_override=cli_guitar_style_override,
                part_params_override_rhythm_key=param_rhythm_key,
                rhythm_library_keys=list(self.rhythm_library.keys()) # self.rhythm_library はギターパターン辞書
            )
            logger.info(f"GuitarGen Block {blk_idx+1}: Selected rhythm_key='{final_rhythm_key_selected}' for guitar.")
            final_guitar_params["guitar_rhythm_key_selected"] = final_rhythm_key_selected


            rhythm_details = self.rhythm_library.get(final_rhythm_key_selected) # self.rhythm_library はギターパターン辞書
            if not rhythm_details or "pattern" not in rhythm_details:
                logger.warning(f"GuitarGen: Rhythm key '{final_rhythm_key_selected}' not found or invalid in guitar_patterns. Using default.")
                rhythm_details = self.rhythm_library.get(DEFAULT_GUITAR_STYLE_KEY, {"pattern":[]})
                if not rhythm_details or "pattern" not in rhythm_details:
                     logger.error(f"GuitarGen: Default guitar rhythm '{DEFAULT_GUITAR_STYLE_KEY}' also missing. Using empty pattern.")
                     rhythm_details = {"pattern": [], "reference_duration_ql": self.global_time_signature_obj.barDuration.quarterLength if self.global_time_signature_obj else 4.0}


            pattern_events = rhythm_details.get("pattern", [])
            pattern_ref_duration = rhythm_details.get("reference_duration_ql", self.global_time_signature_obj.barDuration.quarterLength if self.global_time_signature_obj else 4.0)
            if pattern_ref_duration <= 0: pattern_ref_duration = self.global_time_signature_obj.barDuration.quarterLength if self.global_time_signature_obj else 4.0


            for event_def in pattern_events:
                event_offset_in_pattern = float(event_def.get("offset", 0.0))
                event_duration_in_pattern = float(event_def.get("duration", 1.0))
                event_velocity_factor = float(event_def.get("velocity_factor", 1.0))
                event_stroke_direction = event_def.get("stroke", event_def.get("strum_direction"))

                scale_factor = block_duration_ql / pattern_ref_duration
                abs_event_start_offset_in_block = event_offset_in_pattern * scale_factor
                actual_event_dur_scaled = event_duration_in_pattern * scale_factor

                final_event_abs_offset_in_score = block_offset_ql + abs_event_start_offset_in_block

                if final_event_abs_offset_in_score >= block_offset_ql + block_duration_ql - (MIN_NOTE_DURATION_QL / 16.0) : continue
                
                max_possible_event_dur_from_here = (block_offset_ql + block_duration_ql) - final_event_abs_offset_in_score
                final_actual_event_dur_for_create = min(actual_event_dur_scaled, max_possible_event_dur_from_here)


                if final_actual_event_dur_for_create < MIN_NOTE_DURATION_QL / 2.0:
                    logger.debug(f"GuitarGen: Skipping very short event (dur: {final_actual_event_dur_for_create:.3f} ql) at offset {final_event_abs_offset_in_score:.2f}")
                    continue

                event_base_velocity = int(final_guitar_params.get("guitar_velocity", final_guitar_params.get("velocity", 70)) * event_velocity_factor)
                event_base_velocity = max(1, min(127, event_base_velocity))


                event_specific_guitar_params = final_guitar_params.copy()
                if event_stroke_direction:
                    event_specific_guitar_params["current_event_stroke"] = event_stroke_direction

                generated_elements = self._create_notes_from_event(
                    cs_object, event_specific_guitar_params,
                    final_event_abs_offset_in_score, # ★★★ 絶対オフセットを渡すように変更 (ただし、_create_notes_from_event側で0.0として扱われる)
                    final_actual_event_dur_for_create, event_base_velocity
                )
                for el in generated_elements:
                    # _create_notes_from_event がイベント内相対オフセットで音符を返すので、
                    # ここで最終的な絶対オフセットを適用する
                    el.offset += final_event_abs_offset_in_score
                    all_generated_elements_for_part.append(el)

        global_guitar_params_for_humanize = {}
        if processed_chord_stream:
            first_block_guitar_params = processed_chord_stream[0].get("part_params", {}).get("guitar", {})
            if first_block_guitar_params.get("humanize_opt", False):
                h_template = first_block_guitar_params.get("template_name", "guitar_strum_loose")
                h_custom_params_dict = first_block_guitar_params.get("custom_params", {})
                
                logger.info(f"GuitarGen: Humanizing guitar part (template: {h_template}, custom_params: {h_custom_params_dict})")

                temp_part_for_humanize = stream.Part()
                for el_item_guitar in all_generated_elements_for_part:
                    temp_part_for_humanize.insert(el_item_guitar.offset, el_item_guitar)

                guitar_part_humanized = apply_humanization_to_part(temp_part_for_humanize, template_name=h_template, custom_params=h_custom_params_dict)
                guitar_part_humanized.id = "Guitar"
                if not guitar_part_humanized.getElementsByClass(m21instrument.Instrument).first():
                    guitar_part_humanized.insert(0, self.default_instrument)
                if not guitar_part_humanized.getElementsByClass(tempo.MetronomeMark).first():
                    guitar_part_humanized.insert(0, tempo.MetronomeMark(number=self.global_tempo))
                if not guitar_part_humanized.getElementsByClass(meter.TimeSignature).first() and self.global_time_signature_obj:
                    ts_copy_humanize = meter.TimeSignature(self.global_time_signature_obj.ratioString)
                    guitar_part_humanized.insert(0, ts_copy_humanize)
                guitar_part = guitar_part_humanized
            else:
                logger.info("GuitarGen: Humanization skipped for guitar part.")
                for el_item_guitar_final in all_generated_elements_for_part:
                    guitar_part.insert(el_item_guitar_final.offset, el_item_guitar_final)
        else:
            logger.info("GuitarGen: No blocks to process, skipping humanization and note insertion.")


        logger.info(f"GuitarGen: Finished. Part has {len(list(guitar_part.flatten().notesAndRests))} elements.")
        return guitar_part

# --- END OF FILE generator/guitar_generator.py ---