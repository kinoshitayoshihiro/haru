# --- START OF FILE generator/guitar_generator.py (ヒューマナイズ外部化版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence, Union
from music21 import (stream, note, harmony, pitch, meter, duration,
                     instrument as m21instrument, scale, interval, tempo, key,
                     chord as m21chord, articulations, volume as m21volume, expressions)
import random
import logging
# import numpy as np # humanizer.py に移管
# import copy      # humanizer.py に移管

# ユーティリティのインポート
try:
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL, get_time_signature_object, sanitize_chord_label
    from utilities.humanizer import apply_humanization_to_part, HUMANIZATION_TEMPLATES # パート全体への適用を想定
except ImportError:
    logger_fallback = logging.getLogger(__name__ + ".fallback_utils")
    logger_fallback.warning("GuitarGen: Could not import from utilities. Using fallbacks.")
    MIN_NOTE_DURATION_QL = 0.125
    def get_time_signature_object(ts_str: Optional[str]) -> meter.TimeSignature:
        if not ts_str: ts_str = "4/4"; return meter.TimeSignature(ts_str)
        try: return meter.TimeSignature(ts_str)
        except: return meter.TimeSignature("4/4")
    def sanitize_chord_label(label: Optional[str]) -> Optional[str]:
        if not label or label.strip().lower() in ["rest", "n.c.", "nc", "none"]: return None
        return label.strip()
    def apply_humanization_to_part(part, template_name=None, custom_params=None): return part
    HUMANIZATION_TEMPLATES = {}

logger = logging.getLogger(__name__)

# --- 定数 (変更なし) ---
DEFAULT_GUITAR_OCTAVE_RANGE: Tuple[int, int] = (2, 5)
GUITAR_STRUM_DELAY_QL: float = 0.02
MIN_STRUM_NOTE_DURATION_QL: float = 0.05
STYLE_BLOCK_CHORD = "block_chord"; STYLE_STRUM_BASIC = "strum_basic"; STYLE_ARPEGGIO = "arpeggio"
STYLE_POWER_CHORDS = "power_chords"; STYLE_MUTED_RHYTHM = "muted_rhythm"; STYLE_SINGLE_NOTE_LINE = "single_note_line"


class GuitarGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 default_instrument=m21instrument.AcousticGuitar(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        # (初期化ロジックは変更なし)
        self.rhythm_library = rhythm_library if rhythm_library else {}
        if "guitar_default_quarters" not in self.rhythm_library:
             self.rhythm_library["guitar_default_quarters"] = {"description": "Default quarter note strums/hits", "pattern": [{"offset":i, "duration":1.0, "velocity_factor":0.8-(i%2*0.05)} for i in range(4)]}
             logger.info("GuitarGen: Added 'guitar_default_quarters' to rhythm_library.")
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)

    def _get_guitar_friendly_voicing(
        self, m21_cs: harmony.ChordSymbol, num_strings: int = 6,
        preferred_octave_bottom: int = 2, max_octave_top: int = 5,
        voicing_style: str = "standard"
    ) -> List[pitch.Pitch]:
        # (このメソッドのロジックは変更なし)
        if not m21_cs or not m21_cs.pitches: return []
        # ... (前回のボイシングロジック) ...
        original_pitches = list(m21_cs.pitches); root = m21_cs.root()
        voiced_pitches: List[pitch.Pitch] = []
        if voicing_style == "power_chord_root_fifth" and root:
            p_root = pitch.Pitch(root.name)
            while p_root.ps < pitch.Pitch(f"E{preferred_octave_bottom}").ps: p_root.octave += 1
            while p_root.ps > pitch.Pitch(f"A{preferred_octave_bottom+1}").ps: p_root.octave -=1
            p_fifth = p_root.transpose(interval.PerfectFifth())
            p_octave_root = p_root.transpose(interval.PerfectOctave())
            voiced_pitches = [p_root, p_fifth]
            if p_octave_root.ps <= pitch.Pitch(f"G{max_octave_top}").ps: voiced_pitches.append(p_octave_root)
            return sorted(list(set(voiced_pitches)), key=lambda p: p.ps)[:num_strings]
        try:
            temp_chord = m21_cs.semiClosedPosition(forceOctave=preferred_octave_bottom, inPlace=False) if voicing_style == "open" and hasattr(m21_cs, 'semiClosedPosition') else m21_cs.closedPosition(forceOctave=preferred_octave_bottom, inPlace=False)
            candidate_pitches = sorted(list(temp_chord.pitches), key=lambda p: p.ps)
        except Exception: candidate_pitches = sorted(original_pitches, key=lambda p:p.ps)
        if not candidate_pitches: return []
        bottom_target_ps = pitch.Pitch(f"E{preferred_octave_bottom}").ps
        if candidate_pitches[0].ps < bottom_target_ps - 6:
            oct_shift = round((bottom_target_ps - candidate_pitches[0].ps) / 12.0)
            candidate_pitches = [p.transpose(oct_shift * 12) for p in candidate_pitches]; candidate_pitches.sort(key=lambda p: p.ps)
        selected_dict: Dict[str, pitch.Pitch] = {}
        for p_cand in candidate_pitches:
            if p_cand.name not in selected_dict and pitch.Pitch(f"E{DEFAULT_GUITAR_OCTAVE_RANGE[0]-1}").ps <= p_cand.ps <= pitch.Pitch(f"G{DEFAULT_GUITAR_OCTAVE_RANGE[1]+1}").ps:
                selected_dict[p_cand.name] = p_cand
        voiced_pitches = sorted(list(selected_dict.values()), key=lambda p:p.ps)
        # ... (残りのボイシング調整ロジック) ...
        return voiced_pitches[:num_strings]


    def _create_notes_from_event(
        self, m21_cs: harmony.ChordSymbol, guitar_params: Dict[str, Any],
        event_abs_offset: float, event_duration_ql: float, event_velocity: int
    ) -> List[Union[note.Note, m21chord.Chord]]:
        # (このメソッドのロジックは変更なし、ヒューマナイズは呼び出し側で行う)
        notes_for_event: List[Union[note.Note, m21chord.Chord]] = []
        style = guitar_params.get("guitar_style", STYLE_BLOCK_CHORD)
        # ... (各スタイルに応じたノート生成ロジック - 前回のコードを流用) ...
        # 例: STYLE_STRUM_BASIC
        # is_down = guitar_params.get("strum_direction", "down").lower() == "down"
        # play_order = list(reversed(chord_pitches)) if is_down else chord_pitches
        # for i, p_obj in enumerate(play_order):
        #    n = note.Note(p_obj)
        #    n.duration = duration.Duration(quarterLength=max(MIN_STRUM_NOTE_DURATION_QL, event_duration_ql * 0.9))
        #    n.offset = event_abs_offset + (i * GUITAR_STRUM_DELAY_QL) # ここは注意、insertでオフセット指定するので、このn.offsetは不要かも
        #    n.volume = volume.Volume(velocity=...)
        #    notes_for_event.append(n)
        # GuitarGenerator の _create_notes_from_event は、各要素のオフセットを event_abs_offset からの相対ではなく、
        # その要素が実際に配置されるべき絶対オフセットで返すか、あるいはオフセット0で返し、
        # compose メソッドで event_abs_offset を加算して insert する。
        # ここでは、各要素が event_abs_offset からの相対オフセットを持つと仮定し、
        # compose で最終的な絶対オフセットを計算して insert する。
        # → GuitarGeneratorの元の設計では、_create_notes_from_event が返すノートリストの各ノートのオフセットは、
        #   そのイベントの開始時刻(event_abs_offset)からの相対ではなく、曲の開始からの絶対オフセットになっている。
        #   そのため、composeメソッドでは、humanize後にそのままguitar_part.insert(el.offset, el)で良い。

        # (前回の _create_notes_from_event のロジックをここに展開)
        num_strings = guitar_params.get("guitar_num_strings", 6)
        preferred_octave = guitar_params.get("guitar_target_octave", 3)
        voicing_style_name = guitar_params.get("guitar_voicing_style", "standard")
        chord_pitches = self._get_guitar_friendly_voicing(m21_cs, num_strings, preferred_octave, voicing_style_name)
        if not chord_pitches: return []

        if style == STYLE_BLOCK_CHORD:
            ch = m21chord.Chord(chord_pitches, quarterLength=event_duration_ql * 0.9)
            for n_in_ch in ch.notes: n_in_ch.volume.velocity = event_velocity
            ch.offset = event_abs_offset # ★ 絶対オフセットを設定
            notes_for_event.append(ch)
        elif style == STYLE_STRUM_BASIC:
            is_down = guitar_params.get("strum_direction", "down").lower() == "down"
            play_order = list(reversed(chord_pitches)) if is_down else chord_pitches
            for i, p_obj in enumerate(play_order):
                n = note.Note(p_obj)
                n.duration = duration.Duration(quarterLength=max(MIN_STRUM_NOTE_DURATION_QL, event_duration_ql * 0.9))
                n.offset = event_abs_offset + (i * GUITAR_STRUM_DELAY_QL) # ★ 絶対オフセット
                vel_adj = int(((len(play_order)-1-i)/(len(play_order)-1)*10)-5) if is_down and len(play_order)>1 else (int((i/(len(play_order)-1)*10)-5) if len(play_order)>1 else 0)
                n.volume = volume.Volume(velocity=max(1, min(127, event_velocity + vel_adj)))
                notes_for_event.append(n)
        elif style == STYLE_ARPEGGIO:
            # ... (アルペジオロジック、各ノートに event_abs_offset を加算してオフセット設定) ...
            arp_pattern_type = guitar_params.get("arpeggio_type", "up")
            arp_note_dur_ql = guitar_params.get("arpeggio_note_duration_ql", 0.5)
            ordered_arp_pitches = [chord_pitches[idx % len(chord_pitches)] for idx in arp_pattern_type] if isinstance(arp_pattern_type, list) else (list(reversed(chord_pitches)) if arp_pattern_type == "down" else chord_pitches) # 他のタイプも考慮
            current_offset_in_event = 0.0; arp_idx = 0
            while current_offset_in_event < event_duration_ql and ordered_arp_pitches:
                p_play = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                actual_arp_dur = min(arp_note_dur_ql, event_duration_ql - current_offset_in_event)
                if actual_arp_dur < MIN_NOTE_DURATION_QL / 4: break
                n = note.Note(p_play, quarterLength=actual_arp_dur * 0.95); n.volume.velocity = event_velocity
                n.offset = event_abs_offset + current_offset_in_event # ★ 絶対オフセット
                notes_for_event.append(n)
                current_offset_in_event += arp_note_dur_ql; arp_idx += 1
        elif style == STYLE_MUTED_RHYTHM:
            # ... (ミュートロジック、各ノートに event_abs_offset を加算してオフセット設定) ...
            mute_note_dur = guitar_params.get("mute_note_duration_ql", 0.1)
            mute_interval = guitar_params.get("mute_interval_ql", 0.25)
            t_mute = 0.0; root_mute = chord_pitches[0]
            while t_mute < event_duration_ql:
                actual_mute_dur = min(mute_note_dur, event_duration_ql - t_mute)
                if actual_mute_dur < MIN_NOTE_DURATION_QL / 8: break
                n = note.Note(root_mute); n.articulations = [articulations.Staccatissimo()]
                n.duration.quarterLength = actual_mute_dur
                n.volume.velocity = int(event_velocity * 0.6) + random.randint(-5,5)
                n.offset = event_abs_offset + t_mute # ★ 絶対オフセット
                notes_for_event.append(n)
                t_mute += mute_interval
        return notes_for_event


    def compose(self, processed_chord_stream: List[Dict]) -> stream.Part:
        guitar_part = stream.Part(id="Guitar")
        # (初期設定は変更なし)
        guitar_part.insert(0, self.default_instrument)
        guitar_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        guitar_part.insert(0, self.global_time_signature_obj.clone())

        if not processed_chord_stream: return guitar_part
        logger.info(f"GuitarGen: Starting for {len(processed_chord_stream)} blocks.")

        all_generated_elements_for_part: List[Union[note.Note, m21chord.Chord]] = []

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            # (パラメータ取得、m21_cs生成は変更なし)
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", 4.0))
            chord_label_str = blk_data.get("chord_label", "C")
            guitar_params = blk_data.get("part_params", {}).get("guitar", {})
            if not guitar_params: continue

            sanitized_label = sanitize_chord_label(chord_label_str)
            m21_cs: Optional[harmony.ChordSymbol] = None
            if sanitized_label:
                try: m21_cs = harmony.ChordSymbol(sanitized_label)
                except: m21_cs = None
            if not m21_cs or not m21_cs.pitches: continue

            rhythm_key = guitar_params.get("guitar_rhythm_key", "guitar_default_quarters")
            rhythm_details = self.rhythm_library.get(rhythm_key, self.rhythm_library.get("guitar_default_quarters"))
            if not rhythm_details or "pattern" not in rhythm_details: continue
            pattern_events = rhythm_details.get("pattern", [])

            for event_def in pattern_events:
                # (イベントパラメータ取得、絶対オフセット計算は変更なし)
                event_offset_in_pattern = float(event_def.get("offset", 0.0))
                event_duration_in_pattern = float(event_def.get("duration", 1.0))
                event_velocity_factor = float(event_def.get("velocity_factor", 1.0))
                abs_event_start_offset = block_offset_ql + event_offset_in_pattern
                max_possible_event_dur = block_duration_ql - event_offset_in_pattern
                actual_event_dur = min(event_duration_in_pattern, max_possible_event_dur)
                if actual_event_dur < MIN_NOTE_DURATION_QL / 2: continue
                event_base_velocity = int(guitar_params.get("guitar_velocity", 70) * event_velocity_factor)

                generated_elements = self._create_notes_from_event(
                    m21_cs, guitar_params, abs_event_start_offset, actual_event_dur, event_base_velocity
                )
                all_generated_elements_for_part.extend(generated_elements)
        
        # --- パート全体にヒューマナイゼーションを適用 ---
        # Humanize settings from the first block's guitar_params (or global defaults)
        # This assumes humanization is applied part-wise with consistent settings.
        # For block-wise humanization, apply_humanization_to_element would be called inside the loop.
        global_guitar_params = processed_chord_stream[0].get("part_params", {}).get("guitar", {}) if processed_chord_stream else {}
        if global_guitar_params.get("guitar_humanize", False):
            h_template = global_guitar_params.get("guitar_humanize_style_template", "default_guitar_subtle")
            # custom_params を構築 (DEFAULT_CONFIGのキー名と合わせる)
            h_custom = {
                k.replace("default_guitar_humanize_", "").replace("guitar_humanize_", ""): v
                for k, v in global_guitar_params.items()
                if (k.startswith("guitar_humanize_") or k.startswith("default_guitar_humanize_")) and not k.endswith("_template") and not k.endswith("humanize") # "guitar_humanize"自体は除く
            }
            logger.info(f"GuitarGen: Humanizing guitar part (template: {h_template}, custom: {h_custom})")
            
            # apply_humanization_to_part を使うために、一度要素をパートに挿入する必要がある
            temp_part_for_humanize = stream.Part()
            for el in all_generated_elements_for_part:
                temp_part_for_humanize.insert(el.offset, el) # el.offset は既に絶対オフセットのはず
            
            guitar_part = apply_humanization_to_part(temp_part_for_humanize, template_name=h_template, custom_params=h_custom)
            # apply_humanization_to_part が新しいIDを振るので、必要なら元に戻す
            guitar_part.id = "Guitar" 
            # グローバル要素を再度挿入（apply_humanization_to_partがコピーする場合）
            if not guitar_part.getElementsByClass(instrument.Instrument).first():
                guitar_part.insert(0, self.default_instrument)
            if not guitar_part.getElementsByClass(tempo.MetronomeMark).first():
                guitar_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
            if not guitar_part.getElementsByClass(meter.TimeSignature).first():
                guitar_part.insert(0, self.global_time_signature_obj.clone())

        else: # ヒューマナイズしない場合は、そのまま挿入
            for el in all_generated_elements_for_part:
                guitar_part.insert(el.offset, el)

        logger.info(f"GuitarGen: Finished. Part has {len(guitar_part.flatten().notesAndRests)} elements.")
        return guitar_part

# (guitar_generator.py 末尾の HUMANIZATION_TEMPLATES は削除)
# --- END OF FILE generator/guitar_generator.py ---
