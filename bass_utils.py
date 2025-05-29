# --- START OF FILE generator/bass_utils.py (get_approach_note追加版) ---
from __future__ import annotations
"""bass_utils.py
Low-level helpers for *bass line generation*.
"""

from typing import List, Sequence, Optional, Any, Dict, Tuple
import random as _rand
import logging

from music21 import note, pitch, harmony, interval, scale as m21_scale

try:
    from utilities.scale_registry import ScaleRegistry as SR
except ImportError:
    logger_fallback_sr_bass = logging.getLogger(__name__ + ".fallback_sr_bass")
    logger_fallback_sr_bass.error("BassUtils: Could not import ScaleRegistry from utilities. Scale-aware functions might fail.")
    class SR: 
        @staticmethod
        def get(tonic_str: Optional[str], mode_str: Optional[str]) -> m21_scale.ConcreteScale:
            logger_fallback_sr_bass.warning("BassUtils: Using dummy ScaleRegistry.get().")
            effective_tonic = tonic_str if tonic_str else "C"
            try: return m21_scale.MajorScale(pitch.Pitch(effective_tonic))
            except Exception: return m21_scale.MajorScale(pitch.Pitch("C"))

logger = logging.getLogger(__name__)

def get_approach_note(
    from_pitch: pitch.Pitch,
    to_pitch: pitch.Pitch,
    scale_obj: Optional[m21_scale.ConcreteScale],
    approach_style: str = "chromatic_or_diatonic", # "chromatic_优先", "diatonic_only", "chromatic_only"
    max_step: int = 2, # 半音単位での最大距離 (2なら全音まで)
    preferred_direction: Optional[str] = None # "above", "below", None (近い方)
) -> Optional[pitch.Pitch]:
    """
    指定された2音間を繋ぐのに適したアプローチノート（1音）を提案します。

    Args:
        from_pitch (pitch.Pitch): アプローチを開始する音。
        to_pitch (pitch.Pitch): 目標とする音。
        scale_obj (Optional[m21_scale.ConcreteScale]): 使用するスケール。
        approach_style (str): アプローチのスタイル。
        max_step (int): 考慮する最大ステップ（半音単位）。
        preferred_direction (Optional[str]): "above" または "below" で優先方向を指定。

    Returns:
        Optional[pitch.Pitch]: 提案されるアプローチノート。見つからなければNone。
    """
    if not from_pitch or not to_pitch:
        return None

    candidates: List[Tuple[int, pitch.Pitch]] = [] # (優先度, ピッチ) - 数値が小さいほど高優先度

    for step in range(1, max_step + 1):
        # 下からのアプローチ
        p_below = to_pitch.transpose(-step)
        is_diatonic_below = scale_obj and scale_obj.getScaleDegreeFromPitch(p_below) is not None
        
        # 上からのアプローチ
        p_above = to_pitch.transpose(step)
        is_diatonic_above = scale_obj and scale_obj.getScaleDegreeFromPitch(p_above) is not None

        # 優先度付け:
        # 1: スケール内の半音
        # 2: スケール内の全音
        # 3: スケール外の半音 (クロマチック)
        # 4: スケール外の全音 (クロマチック) - 通常は避けるがスタイルによる

        if approach_style == "diatonic_only":
            if is_diatonic_below: candidates.append((step, p_below))
            if is_diatonic_above: candidates.append((step, p_above))
        elif approach_style == "chromatic_only":
            if step == 1: # 半音のみ
                candidates.append((1, p_below))
                candidates.append((1, p_above))
        elif approach_style == "chromatic_or_diatonic": # デフォルト
            priority_below = 0
            if step == 1: priority_below = 1 if is_diatonic_below else 3
            elif step == 2 and is_diatonic_below: priority_below = 2
            
            priority_above = 0
            if step == 1: priority_above = 1 if is_diatonic_above else 3
            elif step == 2 and is_diatonic_above: priority_above = 2

            if priority_below > 0: candidates.append((priority_below, p_below))
            if priority_above > 0: candidates.append((priority_above, p_above))
            
    if not candidates:
        return None

    # 優先方向と現在の音からの距離でソート
    def sort_key(candidate_tuple):
        priority, p = candidate_tuple
        distance_from_current = abs(p.ps - from_pitch.ps)
        direction_score = 0
        if preferred_direction == "above" and p.ps < to_pitch.ps: direction_score = 100 # ペナルティ
        if preferred_direction == "below" and p.ps > to_pitch.ps: direction_score = 100 # ペナルティ
        return (priority, direction_score, distance_from_current)

    candidates.sort(key=sort_key)
    
    logger.debug(f"BassUtils (get_approach): From={from_pitch.name}, To={to_pitch.name}, Style='{approach_style}', Candidates (Prio, Pitch, Dist): {[(c[0], c[1].nameWithOctave, abs(c[1].ps - from_pitch.ps)) for c in candidates]}")
    
    return candidates[0][1] if candidates else None


# --- 既存の関数 (walking_quarters, root_fifth_half, STYLE_DISPATCH, generate_bass_measure) は変更なし ---
# (ただし、STYLE_DISPATCH内のlambda関数でのlogger呼び出しは、このファイルスコープのloggerを使うように修正を推奨)
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
    # approach_note はシンプルな半音/全音移動なので、ここでは get_approach_note を使うか検討
    beat4 = approach_note(beat3, root_next) # もし get_approach_note を使うなら: get_approach_note(beat3, root_next, scl) or root_next
    if scl.getScaleDegreeFromPitch(beat4) is None:
        if scl.getScaleDegreeFromPitch(root_next) is not None: beat4 = root_next
        else:
            beat4_alt = scl.nextPitch(beat3, direction=m21_scale.Direction.ASCENDING if root_next.ps > beat3.ps else m21_scale.Direction.DESCENDING)
            if isinstance(beat4_alt, pitch.Pitch) and (scl.getScaleDegreeFromPitch(beat4_alt) is not None): beat4 = beat4_alt
            elif isinstance(beat4_alt, list) and beat4_alt and isinstance(beat4_alt[0], pitch.Pitch) and (scl.getScaleDegreeFromPitch(beat4_alt[0]) is not None) : beat4 = beat4_alt[0] # nextPitchがリストを返す場合
            else: beat4 = root_next # 最終フォールバック
    return [beat1, beat2, beat3, beat4]

def root_fifth_half(cs_now: harmony.ChordSymbol, cs_next: harmony.ChordSymbol, tonic: str, mode: str, octave: int = 3, vocal_notes_in_block: Optional[List[Dict]] = None) -> List[pitch.Pitch]:
    if vocal_notes_in_block: logger.debug(f"root_fifth_half for {cs_now.figure if cs_now else 'N/A'}: Received {len(vocal_notes_in_block)} vocal notes.")
    if not cs_now or not cs_now.root(): return [pitch.Pitch(f"C{octave}")] * 4
    root_init = cs_now.root(); root = root_init.transpose((octave - root_init.octave) * 12)
    fifth_init = cs_now.fifth
    if fifth_init is None: fifth_init = root_init.transpose(12) # 5度がない場合はオクターブ上のルート
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
