# --- START OF FILE utilities/humanizer.py (役割特化版) ---
import random
import math
import copy
from typing import List, Dict, Any, Union, Optional # Optional を追加
from music21 import note, chord as m21chord, volume, duration, pitch, stream, instrument, tempo, meter, key, expressions, exceptions21

# MIN_NOTE_DURATION_QL は core_music_utils からインポートすることを推奨
try:
    from .core_music_utils import MIN_NOTE_DURATION_QL
except ImportError: # フォールバック
    MIN_NOTE_DURATION_QL = 0.125

import logging
logger = logging.getLogger(__name__)

NUMPY_AVAILABLE = False
np = None
try:
    import numpy
    np = numpy
    NUMPY_AVAILABLE = True
    logger.info("Humanizer: NumPy found. Fractional noise generation is enabled.")
except ImportError:
    logger.warning("Humanizer: NumPy not found. Fractional noise will use Gaussian fallback.")

def generate_fractional_noise(length: int, hurst: float = 0.7, scale_factor: float = 1.0) -> List[float]:
    if not NUMPY_AVAILABLE or np is None:
        logger.debug(f"Humanizer (FBM): NumPy not available. Using Gaussian noise for length {length}.")
        return [random.gauss(0, scale_factor / 3) for _ in range(length)] # 標準偏差を調整
    if length <= 0: return []
    # (NumPyを使ったFBM生成ロジックは変更なし)
    white_noise = np.random.randn(length)
    fft_white = np.fft.fft(white_noise)
    freqs = np.fft.fftfreq(length)
    freqs[0] = 1e-6 if freqs.size > 0 and freqs[0] == 0 else freqs[0]
    filter_amplitude = np.abs(freqs) ** (-hurst)
    if freqs.size > 0: filter_amplitude[0] = 0
    fft_fbm = fft_white * filter_amplitude
    fbm_noise = np.fft.ifft(fft_fbm).real
    std_dev = np.std(fbm_noise)
    if std_dev != 0: fbm_norm = scale_factor * (fbm_noise - np.mean(fbm_noise)) / std_dev
    else: fbm_norm = np.zeros(length)
    return fbm_norm.tolist()

HUMANIZATION_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "default_subtle": {"time_variation": 0.01, "duration_percentage": 0.03, "velocity_variation": 5, "use_fbm_time": False},
    "piano_gentle_arpeggio": {"time_variation": 0.008, "duration_percentage": 0.02, "velocity_variation": 4, "use_fbm_time": True, "fbm_time_scale": 0.005, "fbm_hurst": 0.7},
    "piano_block_chord": {"time_variation": 0.015, "duration_percentage": 0.04, "velocity_variation": 7, "use_fbm_time": False},
    "drum_tight": {"time_variation": 0.005, "duration_percentage": 0.01, "velocity_variation": 3, "use_fbm_time": False},
    "drum_loose_fbm": {"time_variation": 0.02, "duration_percentage": 0.05, "velocity_variation": 8, "use_fbm_time": True, "fbm_time_scale": 0.01, "fbm_hurst": 0.6},
    "guitar_strum_loose": {"time_variation": 0.025, "duration_percentage": 0.06, "velocity_variation": 10, "use_fbm_time": True, "fbm_time_scale": 0.015},
    "guitar_arpeggio_precise": {"time_variation": 0.008, "duration_percentage": 0.02, "velocity_variation": 4, "use_fbm_time": False},
    "vocal_ballad_smooth": {"time_variation": 0.025, "duration_percentage": 0.05, "velocity_variation": 4, "use_fbm_time": True, "fbm_time_scale": 0.01, "fbm_hurst": 0.7},
    "vocal_pop_energetic": {"time_variation": 0.015, "duration_percentage": 0.02, "velocity_variation": 8, "use_fbm_time": True, "fbm_time_scale": 0.008},
}

def apply_humanization_to_element(
    m21_element: Union[note.Note, m21chord.Chord],
    template_name: Optional[str] = None, # テンプレート名をオプションに
    custom_params: Optional[Dict[str, Any]] = None
) -> Union[note.Note, m21chord.Chord]:
    if not isinstance(m21_element, (note.Note, m21chord.Chord)):
        logger.warning(f"Humanizer: apply_humanization_to_element received non-Note/Chord object: {type(m21_element)}")
        return m21_element

    # テンプレート名がNoneの場合、または存在しない場合は 'default_subtle' を使用
    actual_template_name = template_name if template_name and template_name in HUMANIZATION_TEMPLATES else "default_subtle"
    params = HUMANIZATION_TEMPLATES.get(actual_template_name, {}).copy()
    
    if custom_params: # カスタムパラメータで上書き
        params.update(custom_params)

    element_copy = copy.deepcopy(m21_element)
    time_var = params.get('time_variation', 0.01)
    dur_perc = params.get('duration_percentage', 0.03)
    vel_var = params.get('velocity_variation', 5)
    use_fbm = params.get('use_fbm_time', False)
    fbm_scale = params.get('fbm_time_scale', 0.01)
    fbm_h = params.get('fbm_hurst', 0.6)

    if use_fbm and NUMPY_AVAILABLE:
        time_shift = generate_fractional_noise(1, hurst=fbm_h, scale_factor=fbm_scale)[0]
    else:
        if use_fbm and not NUMPY_AVAILABLE: logger.debug("Humanizer: FBM time shift requested but NumPy not available. Using uniform random.")
        time_shift = random.uniform(-time_var, time_var)
    
    # 元のオフセットを保持し、新しいオフセットを計算
    original_offset = element_copy.offset
    element_copy.offset += time_shift
    if element_copy.offset < 0: element_copy.offset = 0.0

    if element_copy.duration:
        original_ql = element_copy.duration.quarterLength
        duration_change = original_ql * random.uniform(-dur_perc, dur_perc)
        new_ql = max(MIN_NOTE_DURATION_QL / 8, original_ql + duration_change)
        try: element_copy.duration.quarterLength = new_ql
        except exceptions21.DurationException as e: logger.warning(f"Humanizer: DurationException for {element_copy}: {e}. Skip dur change.")

    notes_to_affect = element_copy.notes if isinstance(element_copy, m21chord.Chord) else [element_copy]
    for n_obj in notes_to_affect:
        if isinstance(n_obj, note.Note):
            base_vel = n_obj.volume.velocity if hasattr(n_obj, 'volume') and n_obj.volume and n_obj.volume.velocity is not None else 64
            vel_change = random.randint(-vel_var, vel_var)
            final_vel = max(1, min(127, base_vel + vel_change))
            if hasattr(n_obj, 'volume') and n_obj.volume is not None: n_obj.volume.velocity = final_vel
            else: n_obj.volume = m21volume.Volume(velocity=final_vel)
            
    return element_copy

def apply_humanization_to_part(
    part_to_humanize: stream.Part, # 元のパートを直接変更しないようにコピーして操作
    template_name: Optional[str] = None,
    custom_params: Optional[Dict[str, Any]] = None
) -> stream.Part:
    """
    Part内の全てのNoteとChordにヒューマナイゼーションを適用し、新しいPartを返す。
    """
    if not isinstance(part_to_humanize, stream.Part):
        logger.error("Humanizer: apply_humanization_to_part expects a music21.stream.Part object.")
        return part_to_humanize # Or raise error

    # 新しいPartオブジェクトを作成して、そこにヒューマナイズ済みの要素を再配置する
    humanized_part = stream.Part(id=part_to_humanize.id + "_humanized" if part_to_humanize.id else "HumanizedPart")
    
    # 楽器、テンポ、拍子、調号などのグローバル要素をコピー
    for el_class in [instrument.Instrument, tempo.MetronomeMark, meter.TimeSignature, key.KeySignature, expressions.TextExpression]:
        for item in part_to_humanize.getElementsByClass(el_class):
            humanized_part.insert(item.offset, copy.deepcopy(item)) # オフセットを維持してコピー

    # ノートとコードを処理
    # flatten().notesAndRests だと元の構造が失われるので、要素を直接イテレートする
    elements_to_process = []
    for element in part_to_humanize.recurse().notesAndRests: # recurse() でネストされたStreamも探索
        elements_to_process.append(element)
    
    # オフセット順にソートしてから処理すると、FBMノイズの連続性が保たれる（もし使うなら）
    elements_to_process.sort(key=lambda el: el.getOffsetInHierarchy(part_to_humanize))


    for element in elements_to_process:
        original_hierarchical_offset = element.getOffsetInHierarchy(part_to_humanize)
        
        if isinstance(element, (note.Note, m21chord.Chord)):
            humanized_element = apply_humanization_to_element(element, template_name, custom_params)
            # apply_humanization_to_element でオフセットが変更されるので、
            # 元の階層的オフセットからの差分を考慮して新しいパートに挿入する。
            # ただし、apply_humanization_to_element が返すオフセットは、その要素自身のオフセットなので、
            # 新しいパートにはそのオフセットで挿入すれば良い。
            # music21の insert は賢いので、オフセットが重複してもよしなに扱ってくれるはず。
            # 念のため、元のオフセットを基準に、揺らぎ分を加算したオフセットで挿入する。
            offset_shift_from_humanize = humanized_element.offset - element.offset # ヒューマナイズによるオフセット変化量
            final_insert_offset = original_hierarchical_offset + offset_shift_from_humanize
            if final_insert_offset < 0: final_insert_offset = 0.0
            
            humanized_part.insert(final_insert_offset, humanized_element)
        elif isinstance(element, note.Rest):
            # 休符はタイミングを揺らさないか、揺らすとしてもノートとは別のパラメータで
            # ここでは単純にコピー
            humanized_part.insert(original_hierarchical_offset, copy.deepcopy(element))
        # 他のタイプの要素はここでは無視 (必要なら追加)

    # 最終的なクリーンアップ (重複ノートの削除やタイの再計算などが必要な場合)
    # humanized_part.stripTies(inPlace=True) # 必要に応じて
    # humanized_part.makeNotation(inPlace=True) # 小節割りなど

    return humanized_part
# --- END OF FILE utilities/humanizer.py ---
