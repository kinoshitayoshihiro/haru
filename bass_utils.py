# --- START OF FILE generator/bass_utils.py (インポート修正版) ---
from __future__ import annotations
"""bass_utils.py
Low-level helpers for *bass line generation*.
... (docstringは変更なし) ...
"""

from typing import List, Sequence, Optional, Any # Any を追加 (STYLE_DISPATCH のラムダの戻り値のため)
import random as _rand 
import logging

# music21 のサブモジュールを個別にインポート
from music21 import note
from music21 import pitch
from music21 import harmony
from music21 import interval
# from music21 import scale # scale_registry を経由して使用するため、ここでは直接不要

# utilities パッケージからスケール関連機能をインポート
try:
    from utilities.scale_registry import ScaleRegistry as SR
except ImportError:
    logger_fallback_sr_bass = logging.getLogger(__name__ + ".fallback_sr_bass") # logger名を変更
    logger_fallback_sr_bass.error("BassUtils: Could not import ScaleRegistry from utilities. Scale-aware functions might fail.")
    # music21.scale をインポートしてダミークラスで使用
    from music21 import scale as m21_scale # ここでインポート

    class SR: # Dummy
        @staticmethod
        def get(tonic_str: Optional[str], mode_str: Optional[str]) -> m21_scale.ConcreteScale: # pitch.Pitch から m21_scale.ConcreteScale に変更
            logger_fallback_sr_bass.warning("BassUtils: Using dummy ScaleRegistry.get(). This may not produce correct scales.")
            return m21_scale.MajorScale(pitch.Pitch(tonic_str or "C"))
        # mode_tensions や avoid_degrees は bass_utils では直接使用されていないため、ダミーは不要

logger = logging.getLogger(__name__)


def approach_note(cur_root: pitch.Pitch, next_root: pitch.Pitch, direction: Optional[int] = None) -> pitch.Pitch: # direction の型ヒントを Optional[int] に変更
    if direction is None:
        direction = 1 if next_root.midi > cur_root.midi else -1 # next_root.midi と cur_root.midi を比較
    return cur_root.transpose(direction)


def walking_quarters(
    cs_now: harmony.ChordSymbol, # harmony を使用
    cs_next: harmony.ChordSymbol, # harmony を使用
    tonic: str,
    mode: str,
    octave: int = 3,
) -> List[pitch.Pitch]: # pitch を使用
    scl = SR.get(tonic, mode) 
    
    # degrees の取得前に cs_now.third と cs_now.fifth が None でないか確認
    third_pc = cs_now.third.pitchClass if cs_now.third else cs_now.root().pitchClass
    fifth_pc = cs_now.fifth.pitchClass if cs_now.fifth else cs_now.root().pitchClass
    degrees = [cs_now.root().pitchClass, third_pc, fifth_pc]

    root_now = cs_now.root().transpose((octave - cs_now.root().octave) * 12)
    # cs_next.root() も None でないか確認
    root_next_pitch = cs_next.root()
    if root_next_pitch is None: # 万が一 cs_next のルートがない場合 (通常はありえない)
        logger.warning(f"BassUtils (walking_quarters): cs_next '{cs_next.figure}' has no root. Using cs_now's root.")
        root_next_pitch = cs_now.root()
    root_next = root_next_pitch.transpose((octave - root_next_pitch.octave) * 12)


    beat1 = root_now
    
    options_b2 = [p for p in cs_now.pitches if p.pitchClass in degrees[1:]]
    if not options_b2: 
        options_b2 = [cs_now.root()] 
    
    beat2_raw_pitch = cs_now.root() # デフォルト値を設定
    if options_b2: # options_b2 が空でないことを確認
        beat2_raw_candidate = _rand.choice(options_b2)
        if beat2_raw_candidate: # _rand.choice がリストが空の場合にエラーを出す可能性があるが、ここではoptions_b2は空でない
             beat2_raw_pitch = beat2_raw_candidate

    beat2 = beat2_raw_pitch.transpose((octave - beat2_raw_pitch.octave) * 12)

    step_int_val = interval.Interval(2) # interval を使用。明示的に長2度または短2度を指定する方が良い場合もある
    if root_next.midi < beat2.midi:
        step_int_val = interval.Interval(-2) # interval を使用
    
    beat3 = beat2.transpose(step_int_val) # interval オブジェクトを渡す
    
    scale_pitches_classes = []
    if hasattr(scl, 'getPitches') and callable(scl.getPitches): # callable チェックを追加
        try:
            # getPitches に適切な範囲を与える (例: 2オクターブ分)
            # scl.tonic が None でないことを確認
            if scl.tonic:
                scale_pitches_classes = [p.pitchClass for p in scl.getPitches(scl.tonic.transpose(-12), scl.tonic.transpose(12))]
            else:
                logger.warning(f"BassUtils (walking_quarters): Scale object for {tonic} {mode} has no tonic. Cannot get scale pitches.")
        except Exception as e_getpitch:
            logger.warning(f"BassUtils (walking_quarters): Error getting pitches from scale {scl}: {e_getpitch}")


    if not scale_pitches_classes or beat3.pitchClass not in scale_pitches_classes:
        # スケール外の場合、より近いスケール音を探すか、前の音に戻すなどの処理
        # ここでは簡略化のため beat2 に戻すが、実際にはより音楽的な解決策が望ましい
        beat3 = beat2 

    beat4 = approach_note(beat3, root_next)
    return [beat1, beat2, beat3, beat4]


def root_fifth_half(
    cs: harmony.ChordSymbol, # harmony を使用
    octave: int = 3,
) -> List[pitch.Pitch]: # pitch を使用
    if cs.root() is None: # ルートがない場合はデフォルト値を返す
        logger.warning(f"BassUtils (root_fifth): Chord {cs.figure} has no root. Returning default C notes.")
        default_pitch = pitch.Pitch(f"C{octave}")
        return [default_pitch] * 4 # リストの要素数を合わせる

    root = cs.root().transpose((octave - cs.root().octave) * 12)
    fifth_pitch_obj = cs.fifth
    if fifth_pitch_obj is None: 
        logger.warning(f"BassUtils (root_fifth): Chord {cs.figure} has no fifth. Using octave root as substitute.")
        fifth_pitch_obj = cs.root().transpose(12) 
    
    # fifth_pitch_obj が None でないことを再度確認 (transpose 前)
    if fifth_pitch_obj is None: # 万が一、ルートのオクターブ上も取得できない場合
        logger.error(f"BassUtils (root_fifth): Could not determine fifth for {cs.figure}. Using root for all.")
        return [root, root, root, root]

    fifth = fifth_pitch_obj.transpose((octave - fifth_pitch_obj.octave) * 12)
    return [root, fifth, root, fifth]

STYLE_DISPATCH: Dict[str, Any] = { # 型ヒントを修正
    "root_only": lambda cs_now, cs_next, **k: [cs_now.root().transpose((k.get("octave",3) - cs_now.root().octave) * 12)] * 4 if cs_now.root() else [pitch.Pitch(f"C{k.get('octave',3)}")]*4, # pitch を使用
    "root_fifth": root_fifth_half,
    "walking": walking_quarters,
}

def generate_bass_measure(
    style: str,
    cs_now: harmony.ChordSymbol, # harmony を使用
    cs_next: harmony.ChordSymbol, # harmony を使用
    tonic: str,
    mode: str,
    octave: int = 3,
) -> List[note.Note]: # note を使用
    func = STYLE_DISPATCH.get(style, STYLE_DISPATCH["root_only"])
    
    # cs_now が None の場合のフォールバックを追加
    if cs_now is None:
        logger.warning("BassUtils (generate_bass_measure): cs_now is None. Returning empty list.")
        return []
    # cs_next が None の場合、cs_now を使用 (これは BassGenerator 側で処理されるべきかもしれない)
    effective_cs_next = cs_next if cs_next is not None else cs_now

    try:
        pitches_list = func(cs_now=cs_now, cs_next=effective_cs_next, tonic=tonic, mode=mode, octave=octave)
    except Exception as e_dispatch:
        logger.error(f"BassUtils (generate_bass_measure): Error in dispatched style function '{style}': {e_dispatch}. Using root notes.")
        root_pitch = cs_now.root()
        if root_pitch:
            pitches_list = [root_pitch.transpose((octave - root_pitch.octave) * 12)] * 4
        else:
            pitches_list = [pitch.Pitch(f"C{octave}")] * 4 # pitch を使用
            
    notes_out = []
    for p_obj in pitches_list:
        n = note.Note(p_obj) # note を使用
        n.quarterLength = 1.0
        notes_out.append(n)
    return notes_out
# --- END OF FILE generator/bass_utils.py ---
