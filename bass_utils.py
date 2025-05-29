# --- START OF FILE generator/bass_utils.py (アプローチノート関数追加版) ---
from __future__ import annotations
"""bass_utils.py
Low-level helpers for *bass line generation*, now with vocal context awareness (Phase 1).
Generates pitch templates for bass lines, considering current and next chords,
section tonality, and vocal notes within the current block for basic collision avoidance.
Uses music21's getScaleDegreeFromPitch for scale membership testing.
"""

from typing import List, Sequence, Optional, Any, Dict
import random as _rand
import logging

from music21 import note, pitch, harmony, interval, scale as m21_scale

try:
    from utilities.scale_registry import ScaleRegistry as SR
except ImportError:
    logger_fallback_sr_bass = logging.getLogger(__name__ + ".fallback_sr_bass")
    logger_fallback_sr_bass.error("BassUtils: Could not import ScaleRegistry from utilities. Scale-aware functions might fail.")
    class SR: # Dummy ScaleRegistry
        @staticmethod
        def get(tonic_str: Optional[str], mode_str: Optional[str]) -> m21_scale.ConcreteScale:
            logger_fallback_sr_bass.warning("BassUtils: Using dummy ScaleRegistry.get(). This may not produce correct scales.")
            effective_tonic = tonic_str if tonic_str else "C"
            try: return m21_scale.MajorScale(pitch.Pitch(effective_tonic))
            except Exception as e_pitch: logger_fallback_sr_bass.error(f"Error creating pitch for dummy SR: {e_pitch}. Defaulting to C Major."); return m21_scale.MajorScale(pitch.Pitch("C"))

logger = logging.getLogger(__name__)

def get_approach_note_to_target(
    current_bass_pitch: pitch.Pitch, 
    target_pitch: pitch.Pitch, 
    scale_obj: Optional[m21_scale.ConcreteScale],
    allow_chromatic: bool = True,
    max_interval_semitones: int = 2 # 半音または全音でのアプローチを基本とする
) -> Optional[pitch.Pitch]:
    """
    指定されたターゲットピッチに対して、現在のベースピッチからスムーズに繋がる
    アプローチノート（1音）を選択して返します。

    Args:
        current_bass_pitch (pitch.Pitch): 現在のベースラインの最後の音のピッチ。
        target_pitch (pitch.Pitch): 次のコードのルート音など、目標となるピッチ。
        scale_obj (Optional[m21_scale.ConcreteScale]): 現在のキーのスケールオブジェクト。
        allow_chromatic (bool): スケール外の半音アプローチを許容するか。
        max_interval_semitones (int): 考慮するアプローチの最大インターバル（半音単位）。

    Returns:
        Optional[pitch.Pitch]: 最適なアプローチノートのピッチオブジェクト。見つからなければNone。
    """
    if not target_pitch:
        return None

    possible_approaches: List[Tuple[int, pitch.Pitch]] = [] # (優先度, ピッチ)

    # 1. 半音下からのアプローチ
    p_lower_chrom = target_pitch.transpose(-1)
    if scale_obj and scale_obj.getScaleDegreeFromPitch(p_lower_chrom) is not None:
        possible_approaches.append((1, p_lower_chrom)) # スケール音なら優先度高
    elif allow_chromatic:
        possible_approaches.append((3, p_lower_chrom)) # クロマチックなら優先度中

    # 2. 半音上からのアプローチ
    p_upper_chrom = target_pitch.transpose(1)
    if scale_obj and scale_obj.getScaleDegreeFromPitch(p_upper_chrom) is not None:
        possible_approaches.append((1, p_upper_chrom))
    elif allow_chromatic:
        possible_approaches.append((3, p_upper_chrom))

    if max_interval_semitones >= 2:
        # 3. 全音下からのアプローチ (スケール音のみ)
        p_lower_diatonic = target_pitch.transpose(-2)
        if scale_obj and scale_obj.getScaleDegreeFromPitch(p_lower_diatonic) is not None:
            possible_approaches.append((2, p_lower_diatonic)) # 全音スケールアプローチは優先度やや低

        # 4. 全音上からのアプローチ (スケール音のみ)
        p_upper_diatonic = target_pitch.transpose(2)
        if scale_obj and scale_obj.getScaleDegreeFromPitch(p_upper_diatonic) is not None:
            possible_approaches.append((2, p_upper_diatonic))
            
    if not possible_approaches:
        return None

    # 優先度でソートし、最も優先度の高いものの中からランダムに選択（もし複数あれば）
    # ここでは、さらに current_bass_pitch からの距離が近いものを優先するロジックも追加可能
    possible_approaches.sort(key=lambda x: (x[0], abs(x[1].ps - current_bass_pitch.ps))) # 優先度、次に現在の音からの距離

    logger.debug(f"BassUtils (get_approach): Target={target_pitch.name}, Current={current_bass_pitch.name}, PossibleApproaches={[(p.name, prio) for prio, p in possible_approaches]}")
    
    return possible_approaches[0][1] if possible_approaches else None


# --- 既存の関数 (approach_note, walking_quarters, root_fifth_half, STYLE_DISPATCH, generate_bass_measure) は変更なし ---
def approach_note(cur_note_pitch: pitch.Pitch, next_target_pitch: pitch.Pitch, direction: Optional[int] = None) -> pitch.Pitch:
    if direction is None: direction = 1 if next_target_pitch.midi > cur_note_pitch.midi else -1
    return cur_note_pitch.transpose(direction)
def walking_quarters(cs_now: harmony.ChordSymbol, cs_next: harmony.ChordSymbol, tonic: str, mode: str, octave: int = 3, vocal_notes_in_block: Optional[List[Dict]] = None) -> List[pitch.Pitch]:
    if vocal_notes_in_block: logger.debug(f"walking_quarters for {cs_now.figure if cs_now else 'N/A'}: Received {len(vocal_notes_in_block)} vocal notes.")
    scl = SR.get(tonic, mode)
    if not cs_now or not cs_now.root(): return [pitch.Pitch(f"C{octave}")] * 4
    root_now_init = cs_now.root(); root_now = root_now_init.transpose((octave - root_now_init.octave) * 12)
    effective_cs_next_root = cs_next.root() if cs_next and cs_next.root() else root_now_init
    root_next = effective_cs_next_root.transpose((octave - effective_cs_next_root.octave) * 12)
    beat1 = root_now; options_b2_pitches = []
    if cs_now.third: options_b2_pitches.append(cs_now.third)
    if cs_now.fifth: options_b2_pitches.append(cs_now.fifth)
    if not options_b2_pitches: options_b2_pitches.append(root_now_init)
    beat2_candidate_pitch = _rand.choice(options_b2_pitches) if options_b2_pitches else root_now_init
    beat2 = beat2_candidate_pitch.transpose((octave - beat2_candidate_pitch.octave) * 12)
    beat3_candidate_pitch = beat2.transpose(_rand.choice([-2, -1, 1, 2]))
    if scl.getScaleDegreeFromPitch(beat3_candidate_pitch) is None:
        temp_options_b3 = [p for p in options_b2_pitches if p.nameWithOctave != beat2_candidate_pitch.nameWithOctave]
        if not temp_options_b3: temp_options_b3 = [root_now_init]
        beat3_candidate_pitch = _rand.choice(temp_options_b3) if temp_options_b3 else root_now_init
        beat3 = beat3_candidate_pitch.transpose((octave - beat3_candidate_pitch.octave) * 12)
    else: beat3 = beat3_candidate_pitch
    beat4 = approach_note(beat3, root_next)
    if scl.getScaleDegreeFromPitch(beat4) is None:
        if scl.getScaleDegreeFromPitch(root_next) is not None: beat4 = root_next
        else:
            beat4_alt = scl.nextPitch(beat3, direction=m21_scale.Direction.ASCENDING if root_next.ps > beat3.ps else m21_scale.Direction.DESCENDING)
            if isinstance(beat4_alt, pitch.Pitch) and (scl.getScaleDegreeFromPitch(beat4_alt) is not None): beat4 = beat4_alt
    return [beat1, beat2, beat3, beat4]
def root_fifth_half(cs_now: harmony.ChordSymbol, cs_next: harmony.ChordSymbol, tonic: str, mode: str, octave: int = 3, vocal_notes_in_block: Optional[List[Dict]] = None) -> List[pitch.Pitch]:
    if vocal_notes_in_block: logger.debug(f"root_fifth_half for {cs_now.figure if cs_now else 'N/A'}: Received {len(vocal_notes_in_block)} vocal notes.")
    if not cs_now or not cs_now.root(): return [pitch.Pitch(f"C{octave}")] * 4
    root_init = cs_now.root(); root = root_init.transpose((octave - root_init.octave) * 12)
    fifth_init = cs_now.fifth
    if fifth_init is None: fifth_init = root_init.transpose(12)
    fifth = fifth_init.transpose((octave - fifth_init.octave) * 12)
    return [root, fifth, root, fifth]
STYLE_DISPATCH: Dict[str, Any] = {
    "root_only": lambda cs_now, cs_next, tonic, mode, octave, vocal_notes_in_block, **k: ([cs_now.root().transpose((octave - cs_now.root().octave) * 12)] * 4 if cs_now and cs_now.root() else [pitch.Pitch(f"C{octave}")]*4),
    "simple_roots": lambda cs_now, cs_next, tonic, mode, octave, vocal_notes_in_block, **k: ([cs_now.root().transpose((octave - cs_now.root().octave) * 12)] * 4 if cs_now and cs_now.root() else [pitch.Pitch(f"C{octave}")]*4),
    "root_fifth": root_fifth_half, "walking": walking_quarters,
}
def generate_bass_measure(style: str, cs_now: harmony.ChordSymbol, cs_next: harmony.ChordSymbol, tonic: str, mode: str, octave: int = 3, vocal_notes_in_block: Optional[List[Dict]] = None) -> List[note.Note]:
    func = STYLE_DISPATCH.get(style)
    if not func: style = "root_only"; func = STYLE_DISPATCH[style]
    if cs_now is None or not cs_now.root(): cs_now = harmony.ChordSymbol("C");
    initial_pitches: List[pitch.Pitch]
    try: initial_pitches = func(cs_now=cs_now, cs_next=cs_next, tonic=tonic, mode=mode, octave=octave, vocal_notes_in_block=vocal_notes_in_block)
    except Exception as e_dispatch: root_p_obj = cs_now.root(); initial_pitches = [root_p_obj.transpose((octave - root_p_obj.octave) * 12)] * 4 if root_p_obj else [pitch.Pitch(f"C{octave}")] * 4
    if not initial_pitches or len(initial_pitches) != 4:
        root_p_obj = cs_now.root(); fill_pitch = root_p_obj.transpose((octave - root_p_obj.octave) * 12) if root_p_obj else pitch.Pitch(f"C{octave}")
        if not initial_pitches: initial_pitches = [fill_pitch] * 4
        elif len(initial_pitches) < 4: initial_pitches.extend([fill_pitch] * (4 - len(initial_pitches)))
        else: initial_pitches = initial_pitches[:4]
    final_adjusted_pitches: List[pitch.Pitch] = []; scl_obj = SR.get(tonic, mode)
    for beat_idx, p_bass_initial in enumerate(initial_pitches):
        adjusted_pitch_current_beat = p_bass_initial
        vocal_notes_on_this_beat = [vn for vn in (vocal_notes_in_block or []) if beat_idx <= vn.get("block_relative_offset", -999.0) < (beat_idx + 1.0)]
        if vocal_notes_on_this_beat and cs_now.root():
            root_pc = cs_now.root().pitchClass; fifth_pc = cs_now.fifth.pitchClass if cs_now.fifth else (root_pc + 7) % 12
            for vn_data in vocal_notes_on_this_beat:
                if not p_bass_initial: continue
                try:
                    vocal_pitch_obj = pitch.Pitch(vn_data["pitch_str"])
                    if vocal_pitch_obj.pitchClass == adjusted_pitch_current_beat.pitchClass:
                        current_bass_is_root = (adjusted_pitch_current_beat.pitchClass == root_pc); candidate_pitch: Optional[pitch.Pitch] = None
                        if current_bass_is_root and cs_now.fifth:
                            candidate_pitch = cs_now.fifth.transpose((octave - cs_now.fifth.octave) * 12)
                            if scl_obj.getScaleDegreeFromPitch(candidate_pitch) is not None: adjusted_pitch_current_beat = candidate_pitch
                            elif cs_now.third:
                                candidate_pitch = cs_now.third.transpose((octave - cs_now.third.octave) * 12)
                                if scl_obj.getScaleDegreeFromPitch(candidate_pitch) is not None: adjusted_pitch_current_beat = candidate_pitch
                        elif adjusted_pitch_current_beat.pitchClass == fifth_pc: adjusted_pitch_current_beat = cs_now.root().transpose((octave - cs_now.root().octave) * 12)
                        break 
                except Exception: pass
        final_adjusted_pitches.append(adjusted_pitch_current_beat)
    notes_out: List[note.Note] = []
    for p_obj_final in final_adjusted_pitches:
        if p_obj_final is None: p_obj_final = pitch.Pitch(f"C{octave}")
        n = note.Note(p_obj_final); n.quarterLength = 1.0; notes_out.append(n)
    return notes_out
# --- END OF FILE generator/bass_utils.py ---
