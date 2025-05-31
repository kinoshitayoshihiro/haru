# --- START OF FILE generator/piano_generator.py (ヒューマナイズ外部化・.flat/.clone()修正・Override対応・copyインポート版) ---
import music21
from typing import cast, List, Dict, Optional, Tuple, Any, Sequence, Union
import copy # ★★★ import copy を追加 ★★★

# music21 のサブモジュールを正しい形式でインポート
import music21.stream as stream
import music21.note as note
import music21.harmony as harmony
import music21.pitch as pitch
import music21.meter as meter
import music21.duration as duration
import music21.instrument as m21instrument
import music21.scale as scale
import music21.interval as interval
import music21.tempo as tempo
import music21.key as key
import music21.chord      as m21chord
import music21.expressions as expressions
import music21.volume as m21volume
from music21 import exceptions21

import random
import logging

try:
    from utilities.override_loader import get_part_override # load_overrides はここでは不要
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES
except ImportError:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("PianoGen: Could not import from utilities. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"; return meter.TimeSignature(ts_str)
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
        if not label or label.strip().lower() in ["rest", "r", "n.c.", "nc", "none", "-"]: return None # "r", "-", "none" もRest扱いに
        return label.strip()
    def apply_humanization_to_part(part, template_name=None, custom_params=None): return part
    HUMANIZATION_TEMPLATES = {}
    class DummyPartOverride: model_config = {}; model_fields = {}
    def get_part_override(overrides, section, part) -> DummyPartOverride: return DummyPartOverride()


logger = logging.getLogger(__name__)

DEFAULT_PIANO_LH_OCTAVE: int = 2
DEFAULT_PIANO_RH_OCTAVE: int = 4

class PianoGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 chord_voicer_instance: Optional[Any] = None,
                 default_instrument_rh=m21instrument.Piano(),
                 default_instrument_lh=m21instrument.Piano(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.rhythm_library = rhythm_library if rhythm_library is not None else {}
        temp_ts_obj_for_default = get_time_signature_object(global_time_signature)
        bar_dur_for_default = temp_ts_obj_for_default.barDuration.quarterLength if temp_ts_obj_for_default else 4.0

        default_keys_to_add = {
            "default_piano_quarters": {"pattern": [{"offset": i, "duration": 1.0, "velocity_factor": 0.75-(i%2*0.05)} for i in range(int(bar_dur_for_default))], "description": "Default quarter notes", "reference_duration_ql": bar_dur_for_default},
            "piano_fallback_block": {"pattern": [{"offset":0.0, "duration": bar_dur_for_default, "velocity_factor":0.7}], "description": "Fallback block chord", "reference_duration_ql": bar_dur_for_default}
        }
        for k, v_item in default_keys_to_add.items():
            if k not in self.rhythm_library: self.rhythm_library[k] = v_item; logger.info(f"PianoGen: Added '{k}' to rhythm_lib.")

        self.chord_voicer = chord_voicer_instance
        if not self.chord_voicer: logger.warning("PianoGen: No ChordVoicer. Using basic voicing.")
        self.instrument_rh = default_instrument_rh
        self.instrument_lh = default_instrument_lh
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _get_piano_chord_pitches(
            self, cs: Optional[harmony.ChordSymbol],
            num_voices_param: Optional[int], # Can be None
            target_octave_param: int, voicing_style_name: str
    ) -> List[pitch.Pitch]:
        if cs is None or not cs.pitches: return []
        final_num_voices = num_voices_param if num_voices_param is not None and num_voices_param > 0 else None # 0や負の場合はNone扱い
        if self.chord_voicer and hasattr(self.chord_voicer, '_apply_voicing_style'):
            try:
                return self.chord_voicer._apply_voicing_style(cs, voicing_style_name, target_octave_for_bottom_note=target_octave_param, num_voices_target=final_num_voices)
            except Exception as e_cv: logger.warning(f"PianoGen: Error in ChordVoicer for '{cs.figure}' with style '{voicing_style_name}': {e_cv}. Falling back to simple voicing.", exc_info=False) # exc_info=False for less verbose logs

        # Simple fallback voicing
        try:
            temp_chord_obj = cs.closedPosition(inPlace=False) # Get a fresh copy
            if not temp_chord_obj.pitches: return [] # Should not happen if cs.pitches exists

            # Ensure root is present and adjust octave
            root_pitch = cs.root()
            if not root_pitch: return sorted(list(cs.pitches), key=lambda p_sort: p_sort.ps)[:final_num_voices or len(cs.pitches)] # Should not happen

            # Transpose entire chord to target octave of the root
            current_root_octave = root_pitch.octave
            oct_diff = target_octave_param - current_root_octave
            transposed_pitches = [p.transpose(oct_diff * 12) for p in temp_chord_obj.pitches]
            voiced_pitches = sorted(transposed_pitches, key=lambda p_sort: p_sort.ps)

            if final_num_voices is not None and len(voiced_pitches) > final_num_voices:
                # A more musical way to reduce voices might be needed, e.g., keeping root, third, seventh
                return voiced_pitches[:final_num_voices] # Simplistic cut
            return voiced_pitches
        except Exception as e_simple:
            logger.warning(f"PianoGen: Simple voicing for '{cs.figure}' failed: {e_simple}. Returning raw pitches.", exc_info=False)
            raw_pitches = sorted(list(cs.pitches), key=lambda p_sort: p_sort.ps)
            if final_num_voices is not None and raw_pitches: return raw_pitches[:final_num_voices or len(raw_pitches)]
            return raw_pitches if raw_pitches else []


    def _apply_pedal_to_part(self, part_to_apply_pedal: stream.Part, block_offset: float, block_duration: float):
        if block_duration > 0.25:
            pedal_on = expressions.TextExpression("Ped."); pedal_off = expressions.TextExpression("*")
            on_time = block_offset + 0.01
            off_time = block_offset + block_duration - 0.05
            if off_time > on_time:
                part_to_apply_pedal.insert(on_time, pedal_on); part_to_apply_pedal.insert(off_time, pedal_off)

    def _generate_piano_hand_part_for_block(
            self, hand_LR: str,
            cs_or_rest: Optional[music21.Music21Object],
            block_duration_ql: float,
            hand_specific_params: Dict[str, Any],
            rhythm_patterns_for_piano: Dict[str, Any]
    ) -> stream.Part:

        hand_part_obj = stream.Part(id=f"Piano{hand_LR}_temp_block_for_{id(cs_or_rest)}") # よりユニークなID

        rhythm_key = hand_specific_params.get(f"piano_{hand_LR.lower()}_rhythm_key")
        # velocity は override で直接指定される可能性も考慮
        vel_override = hand_specific_params.get("velocity")
        if vel_override is not None:
            velocity = vel_override
        else:
            vel_min = hand_specific_params.get(f"piano_velocity_{hand_LR.lower()}_min", 60)
            vel_max = hand_specific_params.get(f"piano_velocity_{hand_LR.lower()}_max", 70)
            velocity = random.randint(min(vel_min, vel_max), max(vel_min, vel_max)) # min/maxが逆でもOK

        voicing_style = hand_specific_params.get(f"piano_{hand_LR.lower()}_voicing_style", "closed")
        target_octave = int(hand_specific_params.get(f"piano_{hand_LR.lower()}_target_octave", DEFAULT_PIANO_RH_OCTAVE if hand_LR == "RH" else DEFAULT_PIANO_LH_OCTAVE))
        num_voices = hand_specific_params.get(f"piano_{hand_LR.lower()}_num_voices")
        arp_note_ql = float(hand_specific_params.get("piano_arp_note_ql", 0.5))
        perform_style_keyword = hand_specific_params.get(f"piano_{hand_LR.lower()}_style_keyword", "simple_block")

        # arrangement_overrides.json からのピアノ特有パラメータの取得
        # これらは hand_specific_params にマージされているはずだが、明示的に取得する例
        weak_beat_style_hand = hand_specific_params.get(f"weak_beat_style_{hand_LR.lower()}", "none") # "none"がデフォルト
        fill_on_4th_hand = hand_specific_params.get("fill_on_4th", False)
        fill_length_beats_hand = hand_specific_params.get("fill_length_beats", 0.5)


        if isinstance(cs_or_rest, note.Rest):
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            hand_part_obj.insert(0, rest_obj)
            return hand_part_obj

        if not cs_or_rest or not isinstance(cs_or_rest, harmony.ChordSymbol) or not cs_or_rest.pitches:
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            hand_part_obj.insert(0, rest_obj)
            return hand_part_obj

        cs_current: harmony.ChordSymbol = cast(harmony.ChordSymbol, cs_or_rest)
        base_voiced_pitches = self._get_piano_chord_pitches(cs_current, num_voices, target_octave, voicing_style)
        if not base_voiced_pitches:
            rest_obj = note.Rest(quarterLength=block_duration_ql)
            hand_part_obj.insert(0, rest_obj)
            return hand_part_obj

        rhythm_details = rhythm_patterns_for_piano.get(rhythm_key if rhythm_key else "")
        if not rhythm_details or "pattern" not in rhythm_details:
            logger.warning(f"PianoGen: Rhythm key '{rhythm_key}' not found or invalid for {hand_LR}. Using fallback 'piano_fallback_block'.")
            rhythm_details = rhythm_patterns_for_piano.get("piano_fallback_block", {"pattern": [{"offset":0.0, "duration": block_duration_ql, "velocity_factor":0.7}], "reference_duration_ql": block_duration_ql})

        pattern_events = rhythm_details.get("pattern", [])
        pattern_ref_duration = rhythm_details.get("reference_duration_ql", block_duration_ql)
        if pattern_ref_duration <= 0: pattern_ref_duration = block_duration_ql # ゼロ除算防止

        # EDMスタイルなどの特殊処理 (現状のrhythm_libraryにはないが将来用)
        is_edm_bounce_style = "edm_bounce" in (rhythm_key or "").lower() or "bounce" in perform_style_keyword.lower()
        is_edm_spread_style = "edm_spread" in (rhythm_key or "").lower() or "spread" in perform_style_keyword.lower()
        if is_edm_bounce_style or is_edm_spread_style:
            # ... (EDMスタイルのロジックは変更なし) ...
            return hand_part_obj

        for event_idx, event_params in enumerate(pattern_events):
            event_offset_in_pattern = float(event_params.get("offset", 0.0))
            event_dur_from_pattern = float(event_params.get("duration", self.global_time_signature_obj.beatDuration.quarterLength if self.global_time_signature_obj else 1.0))
            event_vf = float(event_params.get("velocity_factor", 1.0))

            scale_factor = block_duration_ql / pattern_ref_duration
            abs_event_start_offset_in_block = event_offset_in_pattern * scale_factor
            actual_event_duration = event_dur_from_pattern * scale_factor

            if abs_event_start_offset_in_block >= block_duration_ql - (MIN_NOTE_DURATION_QL / 16.0) : continue
            actual_event_duration = min(actual_event_duration, block_duration_ql - abs_event_start_offset_in_block)

            if actual_event_duration < MIN_NOTE_DURATION_QL / 4.0: continue
            current_event_vel = int(velocity * event_vf)
            current_event_vel = max(1, min(127, current_event_vel)) # ベロシティを範囲内に収める

            # 弱拍処理 (arrangement_overrides.json からの指定を考慮)
            # 4/4拍子を前提として、2拍目(1.0-)と4拍目(3.0-)を弱拍とする
            # これはリズムパターンのオフセットに基づくべき
            is_weak_beat_event = False
            if self.global_time_signature_obj and self.global_time_signature_obj.beatCount == 4:
                beat_duration = self.global_time_signature_obj.beatDuration.quarterLength
                # パターンイベントの開始が、ブロック内の2拍目または4拍目に該当するか
                # スケーリング後のオフセットで判断
                if (beat_duration <= abs_event_start_offset_in_block < beat_duration * 2) or \
                   (beat_duration * 3 <= abs_event_start_offset_in_block < beat_duration * 4):
                    is_weak_beat_event = True
            
            if is_weak_beat_event:
                if weak_beat_style_hand == "rest": continue # イベントをスキップ
                if weak_beat_style_hand == "ghost": current_event_vel = max(1, int(current_event_vel * 0.5))
                # "none" は何もしない

            # 4拍目のフィル処理 (arrangement_overrides.json からの指定を考慮)
            is_on_4th_beat_start = False
            if self.global_time_signature_obj and self.global_time_signature_obj.beatCount == 4:
                beat_duration = self.global_time_signature_obj.beatDuration.quarterLength
                if abs(abs_event_start_offset_in_block - (beat_duration * 3)) < 0.1: # 4拍目の開始に近いか
                    is_on_4th_beat_start = True
            
            if fill_on_4th_hand and is_on_4th_beat_start and hand_LR == "RH": # 通常RHがフィルを担当
                # 簡単なフィルとして、短いアルペジオや装飾音を入れる
                # ここでは元のイベントを短くして、フィル用のスペースを作る
                original_event_dur_for_fill = actual_event_duration
                actual_event_duration = max(MIN_NOTE_DURATION_QL, original_event_dur_for_fill - fill_length_beats_hand)
                
                fill_start_offset = abs_event_start_offset_in_block + actual_event_duration
                fill_pitches = base_voiced_pitches[-2:] # 上の2音など
                if fill_pitches:
                    for i, p_fill in enumerate(fill_pitches):
                        fill_note = note.Note(p_fill)
                        fill_note.quarterLength = (fill_length_beats_hand / len(fill_pitches)) * 0.9
                        fill_note.volume.velocity = current_event_vel + 5 # 少し強調
                        hand_part_obj.insert(fill_start_offset + i * (fill_length_beats_hand / len(fill_pitches)), fill_note)
                if actual_event_duration < MIN_NOTE_DURATION_QL / 4.0: continue # 元のイベントが短すぎたらスキップ


            if hand_LR == "RH" and "arpeggio" in perform_style_keyword.lower() and base_voiced_pitches:
                arp_type = rhythm_details.get("arpeggio_type", "up")
                ordered_arp_pitches = list(reversed(base_voiced_pitches)) if arp_type == "down" else (base_voiced_pitches + list(reversed(base_voiced_pitches[1:-1])) if arp_type == "up_down" and len(base_voiced_pitches)>2 else base_voiced_pitches)
                current_offset_in_arp = 0.0; arp_idx = 0
                current_arp_note_ql_scaled = (rhythm_details.get("note_duration_ql", arp_note_ql)) * scale_factor

                while current_offset_in_arp < actual_event_duration and ordered_arp_pitches:
                    p_arp_note = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                    single_arp_dur = min(current_arp_note_ql_scaled, actual_event_duration - current_offset_in_arp)
                    if single_arp_dur < MIN_NOTE_DURATION_QL / 4.0: break
                    arp_note_created = note.Note(p_arp_note, quarterLength=single_arp_dur * 0.95)
                    arp_note_created.volume = m21volume.Volume(velocity=current_event_vel + random.randint(-3,3))
                    hand_part_obj.insert(abs_event_start_offset_in_block + current_offset_in_arp, arp_note_created)
                    current_offset_in_arp += current_arp_note_ql_scaled; arp_idx += 1
            else:
                pitches_to_play = []
                if hand_LR == "LH":
                    lh_event_type = event_params.get("type", "root").lower()
                    lh_root_pitch = min(base_voiced_pitches, key=lambda p:p.ps) if base_voiced_pitches else (cs_current.root() if cs_current and cs_current.root() else pitch.Pitch(f"C{DEFAULT_PIANO_LH_OCTAVE}"))
                    if lh_event_type == "root" and lh_root_pitch: pitches_to_play.append(lh_root_pitch)
                    elif lh_event_type == "octave_root" and lh_root_pitch: pitches_to_play.extend([lh_root_pitch, lh_root_pitch.transpose(12)])
                    elif base_voiced_pitches: pitches_to_play.append(min(base_voiced_pitches, key=lambda p:p.ps))
                else: pitches_to_play = base_voiced_pitches

                if pitches_to_play:
                    el_play = m21chord.Chord(pitches_to_play) if len(pitches_to_play) > 1 else note.Note(pitches_to_play[0])
                    el_play.quarterLength = actual_event_duration * 0.9
                    for n_in_chord in el_play.notes if isinstance(el_play, m21chord.Chord) else [el_play]: n_in_chord.volume = m21volume.Volume(velocity=current_event_vel)
                    hand_part_obj.insert(abs_event_start_offset_in_block, el_play)
        return hand_part_obj


    def compose(self, processed_chord_stream: List[Dict], overrides: Optional[Any] = None) -> stream.Score:
        piano_score = stream.Score(id="PianoScore")
        piano_rh_part = stream.Part(id="PianoRH"); piano_rh_part.insert(0, self.instrument_rh)
        piano_lh_part = stream.Part(id="PianoLH"); piano_lh_part.insert(0, self.instrument_lh)
        piano_score.insert(0, tempo.MetronomeMark(number=self.global_tempo))

        if self.global_time_signature_obj:
            ts_copy = meter.TimeSignature(self.global_time_signature_obj.ratioString)
            piano_score.insert(0, ts_copy)
        else:
            logger.warning("PianoGen: global_time_signature_obj is None. Defaulting to 4/4 for piano_score.")
            piano_score.insert(0, meter.TimeSignature("4/4"))

        if not processed_chord_stream:
            piano_score.append(piano_rh_part); piano_score.append(piano_lh_part)
            return piano_score

        logger.info(f"PianoGen: Starting for {len(processed_chord_stream)} blocks.")

        for blk_idx, blk_data_original in enumerate(processed_chord_stream):
            blk_data = copy.deepcopy(blk_data_original) # ★★★ copy.deepcopy を使用 ★★★
            block_offset_abs = float(blk_data.get("offset", 0.0))
            block_dur = float(blk_data.get("q_length", 4.0))
            chord_lbl_original = blk_data.get("chord_label", "C")
            current_section_name = blk_data.get("section_name", f"UnnamedSection_{blk_idx}")

            part_specific_overrides_model = get_part_override(
                overrides if overrides else Overrides(root={}), # 空のOverridesモデルを渡す
                current_section_name,
                "piano"
            )

            piano_params_from_chordmap = blk_data.get("part_params", {}).get("piano", {})
            final_piano_params = piano_params_from_chordmap.copy()
            if part_specific_overrides_model:
                override_dict = part_specific_overrides_model.model_dump(exclude_unset=True)
                final_piano_params.update(override_dict)
            
            blk_data["part_params"]["piano"] = final_piano_params # マージ結果をblk_dataに反映
            logger.debug(f"Piano Blk {blk_idx+1}: AbsOff={block_offset_abs}, Dur={block_dur}, Lbl='{chord_lbl_original}', FinalParams: {final_piano_params}")

            cs_or_rest_current: Optional[music21.Music21Object] = None
            if chord_lbl_original.lower() in ["rest", "r", "n.c.", "nc", "none", "-"]: # Rest判定を強化
                 cs_or_rest_current = note.Rest(quarterLength=block_dur)
            else:
                sanitized_label = sanitize_chord_label(chord_lbl_original)
                if sanitized_label is None:
                    cs_or_rest_current = note.Rest(quarterLength=block_dur)
                else:
                    try:
                        cs_or_rest_current = harmony.ChordSymbol(sanitized_label)
                        if not cs_or_rest_current.pitches:
                            logger.warning(f"PianoGen Blk {blk_idx+1}: ChordSymbol '{sanitized_label}' has no pitches. Treating as Rest.")
                            cs_or_rest_current = note.Rest(quarterLength=block_dur)
                    except Exception as e_parse:
                        logger.error(f"PianoGen Blk {blk_idx+1}: Error parsing ChordSymbol '{sanitized_label}': {e_parse}. Treating as Rest.")
                        cs_or_rest_current = note.Rest(quarterLength=block_dur)

            rh_block_part = self._generate_piano_hand_part_for_block("RH", cs_or_rest_current, block_dur, final_piano_params, self.rhythm_library)
            lh_block_part = self._generate_piano_hand_part_for_block("LH", cs_or_rest_current, block_dur, final_piano_params, self.rhythm_library)

            for el_rh_final in rh_block_part.flatten().notesAndRests:
                piano_rh_part.insert(block_offset_abs + el_rh_final.offset, el_rh_final)
            for el_lh_final in lh_block_part.flatten().notesAndRests:
                piano_lh_part.insert(block_offset_abs + el_lh_final.offset, el_lh_final)

            if final_piano_params.get("piano_apply_pedal", final_piano_params.get("apply_pedal", True)) and not isinstance(cs_or_rest_current, note.Rest):
                self._apply_pedal_to_part(piano_lh_part, block_offset_abs, block_dur)

        global_piano_params_for_humanize = processed_chord_stream[0].get("part_params", {}).get("piano", {}) if processed_chord_stream else {}

        # ヒューマナイズの on/off は final_piano_params (override適用済み) から取得
        # humanize_opt は translate_keywords_to_params で解決されているので、それを参照
        if global_piano_params_for_humanize.get("humanize_rh_opt", False): # humanize_opt を直接参照
            rh_template = global_piano_params_for_humanize.get("template_name", "piano_gentle_arpeggio")
            rh_custom = global_piano_params_for_humanize.get("custom_params", {})
            logger.info(f"PianoGen: Humanizing RH part (template: {rh_template}, custom: {rh_custom})")
            piano_rh_part = apply_humanization_to_part(piano_rh_part, template_name=rh_template, custom_params=rh_custom)
            piano_rh_part.id = "PianoRH"

        if global_piano_params_for_humanize.get("humanize_lh_opt", False): # humanize_opt を直接参照
            lh_template = global_piano_params_for_humanize.get("template_name", "piano_block_chord")
            lh_custom = global_piano_params_for_humanize.get("custom_params", {})
            logger.info(f"PianoGen: Humanizing LH part (template: {lh_template}, custom: {lh_custom})")
            piano_lh_part = apply_humanization_to_part(piano_lh_part, template_name=lh_template, custom_params=lh_custom)
            piano_lh_part.id = "PianoLH"


        piano_score.append(piano_rh_part); piano_score.append(piano_lh_part)
        logger.info(f"PianoGen: Finished. RH notes: {len(list(piano_rh_part.flatten().notesAndRests))}, LH notes: {len(list(piano_lh_part.flatten().notesAndRests))}")
        return piano_score

# --- END OF FILE generators/piano_generator.py ---