# --- START OF FILE generator/melody_utils.py (インポート修正版) ---
from __future__ import annotations
"""melody_utils.py
... (docstringは変更なし) ...
"""

from typing import List, Sequence, Tuple, Optional
import random as _rand # random を _rand としてインポート
import logging

from music21 import note, harmony, interval, pitch

# utilities パッケージからスケール関連機能をインポート
try:
    from utilities.scale_registry import ScaleRegistry as SR
except ImportError:
    logger.error("MelodyUtils: Could not import ScaleRegistry from utilities. Scale-aware functions might fail.")
    class SR: # Dummy
        @staticmethod
        def get(tonic_str: Optional[str], mode_str: Optional[str]) -> pitch.Pitch: # 戻り値を scale.ConcreteScale にすべき
            from music21 import scale as m21_scale, pitch as m21_pitch
            logger.warning("MelodyUtils: Using dummy ScaleRegistry.get(). This may not produce correct scales.")
            return m21_scale.MajorScale(m21_pitch.Pitch(tonic_str or "C"))
        @staticmethod
        def mode_tensions(mode_str: str) -> List[int]: return [2, 4, 6] # Dummy
        @staticmethod
        def avoid_degrees(mode_str: str) -> List[int]: return [] # Dummy

logger = logging.getLogger(__name__)

# --- (以降の定数、ヘルパー関数、generate_melodic_pitches は変更なし、SR.get の呼び出しは既に適切) ---
# Constants / Config
BEAT_STRENGTH_4_4 = {0.0: 1.0, 1.0: 0.6, 2.0: 0.9, 3.0: 0.4}
_MARKOV_TABLE = {0: {0:0.2,2:0.4,-2:0.4}, 2: {2:0.3,0:0.2,-1:0.3,-2:0.2}, -2: {-2:0.3,0:0.2,1:0.3,2:0.2}, 1: {2:0.4,0:0.2,-1:0.4}, -1: {-2:0.4,0:0.2,1:0.4}}

# Utility helpers
def _weighted_choice(items_with_weight):
    total = sum(w for _,w in items_with_weight)
    if total == 0: return items_with_weight[0][0] if items_with_weight else None # 重み合計0の場合のフォールバック
    r = _rand.random() * total
    upto = 0.0
    for item,w in items_with_weight:
        upto += w
        if upto >= r: return item
    return items_with_weight[-1][0] if items_with_weight else None # フォールバック

def _next_interval(prev_int: int) -> int:
    table = _MARKOV_TABLE.get(prev_int, _MARKOV_TABLE.get(0, {})) # prev_intがない場合、さらに0もない場合のフォールバック
    if not table: return 0 # テーブルが空なら動かない
    return _weighted_choice(list(table.items()))

# Public API
def generate_melodic_pitches(
    chord: harmony.ChordSymbol,
    tonic: str,
    mode: str,
    beat_offsets: Sequence[float],
    octave_range: Tuple[int, int] = (4, 5),
    rnd: Optional[random.Random] = None,
    min_note_duration_ql: float = 0.125 # MIN_NOTE_DURATION_QL を引数で渡すか、ここで定義
) -> List[note.Note]:
    rnd = rnd or _rand
    scale_obj = SR.get(tonic, mode)
    # scale_obj が期待通り ConcreteScale であることを確認
    if not hasattr(scale_obj, 'getPitches') or not hasattr(scale_obj, 'pitchFromDegree'):
        logger.error(f"MelodyUtils: SR.get for {tonic} {mode} did not return a valid scale object. Returning empty notes.")
        return []
        
    tensions_deg = SR.mode_tensions(mode)
    avoid_deg = SR.avoid_degrees(mode)

    chord_pcs = {p.pitchClass for p in chord.pitches}
    tension_pcs = {
        scale_obj.pitchFromDegree(d).pitchClass for d in tensions_deg if d not in avoid_deg and hasattr(scale_obj, 'pitchFromDegree')
    }

    notes_out: List[note.Note] = []
    prev_pitch_obj: Optional[pitch.Pitch] = None
    prev_interval_val = 0

    for beat_offset_val in beat_offsets:
        strength = BEAT_STRENGTH_4_4.get(beat_offset_val % 4, 0.5)
        candidate_pool: List[pitch.Pitch] = []

        for p_chord in chord.pitches:
            for octv_val in range(octave_range[0], octave_range[1] + 1):
                candidate_pool.append(p_chord.transpose(12 * (octv_val - p_chord.octave)))
        for pc_tension in tension_pcs:
            # base_p_tension = pitch.Pitch() # pitch.Pitch(pc_tension) の方が直接的
            # base_p_tension.midi = pc_tension
            for octv_val in range(octave_range[0], octave_range[1] + 1):
                candidate_pool.append(pitch.Pitch(pc_tension + octv_val * 12))
        
        if not candidate_pool: # 候補が全くない場合 (ありえないはずだが念のため)
            logger.warning(f"MelodyUtils: Candidate pool empty for chord {chord.figure}. Using root.")
            p_fallback = chord.root()
            if p_fallback: candidate_pool.append(p_fallback.transpose((octave_range[0]-p_fallback.octave)*12))
            else: continue # ルートもなければスキップ

        weighted_candidate_pool: List[Tuple[pitch.Pitch, float]] = []
        for p_cand in candidate_pool:
            w = 1.0
            if p_cand.pitchClass in chord_pcs: w *= 4.0
            elif p_cand.pitchClass in tension_pcs: w *= 2.0
            if prev_pitch_obj is not None:
                ival_dist = abs(p_cand.midi - prev_pitch_obj.midi)
                w *= max(0.1, 1.5 - ival_dist / 8.0)
            w *= strength
            weighted_candidate_pool.append((p_cand, w))
        
        if not weighted_candidate_pool: # 重み付け後も候補がない場合
             chosen_pitch_obj = candidate_pool[0] if candidate_pool else chord.root().transpose((octave_range[0]-chord.root().octave)*12) if chord.root() else pitch.Pitch("C4")
        else:
            chosen_pitch_obj = _weighted_choice(weighted_candidate_pool)

        if prev_pitch_obj is not None:
            desired_interval_val = _next_interval(prev_interval_val)
            candidate_next_pitch = prev_pitch_obj.transpose(desired_interval_val)
            if octave_range[0] <= candidate_next_pitch.octave <= octave_range[1]:
                chosen_pitch_obj = candidate_next_pitch
                prev_interval_val = desired_interval_val
            else:
                prev_interval_val = chosen_pitch_obj.midi - prev_pitch_obj.midi if chosen_pitch_obj and prev_pitch_obj else 0
        else:
            prev_interval_val = 0

        prev_pitch_obj = chosen_pitch_obj
        n_new = note.Note(chosen_pitch_obj)
        n_new.quarterLength = min_note_duration_ql # 呼び出し側で上書きされる想定
        notes_out.append(n_new)

    return notes_out
# --- END OF FILE generator/melody_utils.py ---
