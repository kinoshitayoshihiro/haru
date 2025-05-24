# --- START OF FILE generator/humanizer.py ---
import random
import math
import copy
from typing import List, Dict, Any, Union
from music21 import note, chord as m21chord, volume, duration, pitch # m21chord をインポート

# music21.note.Note や music21.chord.Chord などの型ヒントのため
# from music21 import note, chord as m21chord, volume, duration # (必要に応じて)

# core_music_utils から MIN_NOTE_DURATION_QL をインポートしたい場合
try:
    from utilities.core_music_utils import MIN_NOTE_DURATION_QL
except ImportError:
    MIN_NOTE_DURATION_QL = 0.125 # フォールバック値

import logging
logger = logging.getLogger(__name__)

NUMPY_AVAILABLE = False
np = None # numpy モジュールを格納する変数
try:
    import numpy
    np = numpy # インポート成功したら np に代入
    NUMPY_AVAILABLE = True
    logger.info("Humanizer: NumPy found. Fractional noise generation is enabled.")
except ImportError:
    logger.warning("Humanizer: NumPy not found. Fractional noise generation will use Gaussian fallback.")

def generate_fractional_noise(length: int, hurst: float = 0.7, scale_factor: float = 1.0) -> List[float]:
    if not NUMPY_AVAILABLE or np is None: # np is None もチェック
        logger.debug(f"FBM disabled (NumPy not available). Generating Gaussian noise for length {length}.")
        return [random.gauss(0, scale_factor / 3) for _ in range(length)]

    if length <= 0: return []
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
    # ... 他の楽器やスタイル用のテンプレートを追加 ...
}

def apply_humanization_to_element(
    m21_element: Union[note.Note, m21chord.Chord],
    template_name: Optional[str] = None,
    custom_params: Optional[Dict[str, Any]] = None
) -> Union[note.Note, m21chord.Chord]:
    """
    単一のmusic21要素（NoteまたはChord）にヒューマナイゼーションを適用する。
    template_name が指定されれば HUMANIZATION_TEMPLATES からパラメータを取得し、
    custom_params で個別に上書き可能。
    """
    if not isinstance(m21_element, (note.Note, m21chord.Chord)):
        logger.warning(f"Humanizer: apply_humanization_to_element received non-Note/Chord object: {type(m21_element)}")
        return m21_element # 何もせず返す

    params = HUMANIZATION_TEMPLATES.get("default_subtle", {}).copy() # 基本フォールバック
    if template_name and template_name in HUMANIZATION_TEMPLATES:
        params.update(HUMANIZATION_TEMPLATES[template_name])
    if custom_params:
        params.update(custom_params)

    # 実際の揺らぎ適用ロジック (apply_note_humanization から移植・改名)
    element_copy = copy.deepcopy(m21_element)
    time_var = params.get('time_variation', 0.01)
    dur_perc = params.get('duration_percentage', 0.03)
    vel_var = params.get('velocity_variation', 5)
    use_fbm = params.get('use_fbm_time', False)
    fbm_scale = params.get('fbm_time_scale', 0.01)
    fbm_h = params.get('fbm_hurst', 0.6)

    if use_fbm and NUMPY_AVAILABLE: # NumPyが利用可能な場合のみFBM
        time_shift = generate_fractional_noise(1, hurst=fbm_h, scale_factor=fbm_scale)[0]
    else:
        if use_fbm and not NUMPY_AVAILABLE:
            logger.debug("Humanizer: FBM time shift requested but NumPy not available. Using uniform random time shift.")
        time_shift = random.uniform(-time_var, time_var)
    
    element_copy.offset += time_shift
    if element_copy.offset < 0: element_copy.offset = 0.0

    if element_copy.duration:
        original_ql = element_copy.duration.quarterLength
        duration_change = original_ql * random.uniform(-dur_perc, dur_perc)
        new_ql = max(MIN_NOTE_DURATION_QL / 8, original_ql + duration_change) # 極端に短くならないように
        try:
            element_copy.duration.quarterLength = new_ql
        except exceptions21.DurationException as e:
            logger.warning(f"Humanizer: DurationException setting qL to {new_ql} for element {element_copy}: {e}. Skipping duration change.")


    notes_to_affect = element_copy.notes if isinstance(element_copy, m21chord.Chord) else [element_copy]
    for n_obj in notes_to_affect:
        if isinstance(n_obj, note.Note): # Noteオブジェクトであることを確認
            base_vel = n_obj.volume.velocity if hasattr(n_obj, 'volume') and n_obj.volume and n_obj.volume.velocity is not None else 64
            vel_change = random.randint(-vel_var, vel_var)
            final_vel = max(1, min(127, base_vel + vel_change))
            if hasattr(n_obj, 'volume') and n_obj.volume is not None:
                n_obj.volume.velocity = final_vel
            else:
                n_obj.volume = volume.Volume(velocity=final_vel)
            
    return element_copy

def apply_humanization_to_part(
    part: stream.Part,
    template_name: Optional[str] = None,
    custom_params: Optional[Dict[str, Any]] = None
) -> stream.Part:
    """
    Part内の全てのNoteとChordにヒューマナイゼーションを適用する。
    """
    humanized_part = stream.Part(id=part.id + "_humanized")
    # パートの楽器やテンポ、拍子記号などをコピー
    for item in part.getElementsByClass([m21instrument.Instrument, tempo.MetronomeMark, meter.TimeSignature, key.KeySignature, expressions.TextExpression]):
        humanized_part.insert(item.offset, copy.deepcopy(item))

    for element in part.flatten().notesAndRests:
        if isinstance(element, (note.Note, m21chord.Chord)):
            humanized_element = apply_humanization_to_element(element, template_name, custom_params)
            # オフセットを維持して挿入 (元のオフセットを使う)
            humanized_part.insert(element.offset + (humanized_element.offset - element.offset), humanized_element) # apply_humanization_to_elementでオフセットが変わるため調整
        elif isinstance(element, note.Rest):
            humanized_part.insert(element.offset, copy.deepcopy(element)) # 休符はそのままコピー
        # 他の要素タイプも必要に応じてコピー
    
    # オフセット順にソート (music21が自動で行うことが多いが念のため)
    # humanized_part.sort(key=lambda x: x.offset, inPlace=True)
    return humanized_part

# --- END OF FILE generator/humanizer.py ---
