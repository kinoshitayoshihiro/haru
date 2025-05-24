# --- START OF FILE generator/bass_utils.py (インポート修正版) ---
from __future__ import annotations
"""bass_utils.py
Low-level helpers for *bass line generation*.
... (docstringは変更なし) ...
"""

from typing import List, Sequence, Optional # Optional を追加
import random as _rand # random を _rand としてインポート (melody_utils との整合性)
import logging

from music21 import note, pitch, harmony, interval

# utilities パッケージからスケール関連機能をインポート
try:
    # ScaleRegistry クラスの get 静的メソッドを使用
    from utilities.scale_registry import ScaleRegistry as SR
except ImportError:
    logger.error("BassUtils: Could not import ScaleRegistry from utilities. Scale-aware functions might fail.")
    # フォールバック用のダミーScaleRegistry
    class SR:
        @staticmethod
        def get(tonic_str: Optional[str], mode_str: Optional[str]) -> pitch.Pitch: # 戻り値を scale.ConcreteScale にすべき
            from music21 import scale as m21_scale, pitch as m21_pitch # music21のインポートをここで行う
            logger.warning("BassUtils: Using dummy ScaleRegistry.get(). This may not produce correct scales.")
            return m21_scale.MajorScale(m21_pitch.Pitch(tonic_str or "C"))
        # mode_tensions や avoid_degrees もダミーが必要ならここに追加

logger = logging.getLogger(__name__)

# --- (以降の関数定義は変更なし、SR.get の呼び出しは既に適切) ---

# approach_note 関数 (変更なし)
def approach_note(cur_root: pitch.Pitch, next_root: pitch.Pitch, direction: int | None = None) -> pitch.Pitch:
    if direction is None:
        direction = 1 if next_root.midi - cur_root.midi > 0 else -1
    return cur_root.transpose(direction)

# walking_quarters 関数 (SR.get の呼び出しは既に適切)
def walking_quarters(
    cs_now: harmony.ChordSymbol,
    cs_next: harmony.ChordSymbol,
    tonic: str,
    mode: str,
    octave: int = 3,
) -> List[pitch.Pitch]:
    scl = SR.get(tonic, mode) # ここはOK
    # ... (以降のロジックは変更なし) ...
    degrees = [cs_now.root().pitchClass,
               cs_now.third.pitchClass if cs_now.third else cs_now.root().pitchClass, # thirdがない場合へのフォールバック
               cs_now.fifth.pitchClass if cs_now.fifth else cs_now.root().pitchClass] # fifthがない場合へのフォールバック

    root_now = cs_now.root().transpose((octave - cs_now.root().octave) * 12)
    root_next = cs_next.root().transpose((octave - cs_next.root().octave) * 12)

    beat1 = root_now
    
    options_b2 = [p for p in cs_now.pitches if p.pitchClass in degrees[1:]]
    if not options_b2: # 3rdや5thがない場合 (ルートのみのコードなど)
        options_b2 = [cs_now.root()] # ルート音を候補にする
    beat2_raw = _rand.choice(options_b2) if options_b2 else cs_now.root() # 更にフォールバック
    beat2 = beat2_raw.transpose((octave - beat2_raw.octave) * 12)

    step_int = +2 if root_next.midi - beat2.midi > 0 else -2
    beat3 = beat2.transpose(step_int)
    
    # scl.getPitches() は music21.scale.ConcreteScale のメソッド
    # SR.get が正しい ConcreteScale インスタンスを返す必要がある
    scale_pitches_classes = [p.pitchClass for p in scl.getPitches()] if hasattr(scl, 'getPitches') else []
    if not scale_pitches_classes or beat3.pitchClass not in scale_pitches_classes:
        beat3 = beat2

    beat4 = approach_note(beat3, root_next)
    return [beat1, beat2, beat3, beat4]


# root_fifth_half 関数 (変更なし)
def root_fifth_half(
    cs: harmony.ChordSymbol,
    octave: int = 3,
) -> List[pitch.Pitch]:
    root = cs.root().transpose((octave - cs.root().octave) * 12)
    # fifth が存在しないコード (例: C(no5)) の場合のエラーを避ける
    fifth_pitch = cs.fifth
    if fifth_pitch is None: # 5度がない場合はルート音のオクターブ上など代替案
        logger.warning(f"BassUtils (root_fifth): Chord {cs.figure} has no fifth. Using octave root as substitute.")
        fifth_pitch = cs.root().transpose(12) # ルートのオクターブ上
    fifth = fifth_pitch.transpose((octave - fifth_pitch.octave) * 12)
    return [root, fifth, root, fifth]

# STYLE_DISPATCH と generate_bass_measure (変更なし)
STYLE_DISPATCH = {
    "root_only": lambda cs_now, cs_next, **k: [cs_now.root().transpose((k.get("octave",3) - cs_now.root().octave) * 12)] * 4,
    "root_fifth": root_fifth_half,
    "walking": walking_quarters,
}

def generate_bass_measure(
    style: str,
    cs_now: harmony.ChordSymbol,
    cs_next: harmony.ChordSymbol,
    tonic: str,
    mode: str,
    octave: int = 3,
) -> List[note.Note]:
    func = STYLE_DISPATCH.get(style, STYLE_DISPATCH["root_only"])
    # cs_next が None になる可能性を考慮 (リストの最後など)
    # generate_bass_measure を呼び出す BassGenerator.compose で cs_next が None の場合の処理が必要
    pitches = func(cs_now=cs_now, cs_next=cs_next, tonic=tonic, mode=mode, octave=octave)
    notes_out = []
    for p_obj in pitches:
        n = note.Note(p_obj)
        n.quarterLength = 1.0
        notes_out.append(n)
    return notes_out
# --- END OF FILE generator/bass_utils.py ---
