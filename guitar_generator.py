# --- START OF FILE generator/guitar_generator.py (感情スタイル選択機能 組み込み版) ---
import music21
from typing import List, Dict, Optional, Tuple, Any, Sequence, Union, cast

# music21 のサブモジュールを正しい形式でインポート
import music21.stream as stream
import music21.note as note
import music21.harmony as harmony
import music21.pitch as pitch
import music21.meter as meter
import music21.duration as duration
import music21.instrument as m21instrument
# import music21.scale as scale # 現状直接使われていない
import music21.interval as interval
import music21.tempo as tempo
# import music21.key as key # 現状直接使われていない
import music21.chord      as m21chord
import music21.articulations as articulations
import music21.volume as m21volume
# import music21.expressions as expressions # 現状直接使われていない

import random
import logging
import math # ### OtoKotoba: ADD ### math.ceil を使うため

# ユーティリティのインポート
try:
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
        if not label or label.strip().lower() in ["rest", "n.c.", "nc", "none"]: return None # "none"もRest扱いに
        return label.strip()
    def apply_humanization_to_part(part, template_name=None, custom_params=None): return part
    HUMANIZATION_TEMPLATES = {}

logger = logging.getLogger(__name__)

DEFAULT_GUITAR_OCTAVE_RANGE: Tuple[int, int] = (2, 5)
GUITAR_STRUM_DELAY_QL: float = 0.02
MIN_STRUM_NOTE_DURATION_QL: float = 0.05
STYLE_BLOCK_CHORD = "block_chord"; STYLE_STRUM_BASIC = "strum_basic"; STYLE_ARPEGGIO = "arpeggio"
STYLE_POWER_CHORDS = "power_chords"; STYLE_MUTED_RHYTHM = "muted_rhythm"; STYLE_SINGLE_NOTE_LINE = "single_note_line"

### OtoKotoba: ADD ### Emotion / Intensity -> Guitar-Pattern マッピング START
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
    # Haruさんのchordmap.jsonにある感情キーワードとデフォルトコンフィグのギターemotion_mode_to_style_mapを参考に、
    # 既存のrhythm_library.jsonにあるキーと照らし合わせて追加・調整できます。
    # 例: ("ionian_希望", "default"): "guitar_folk_strum_simple",
    #     ("dorian_悲しみ", "default"): "guitar_ballad_arpeggio",
    #     ("aeolian_怒り", "default"): "guitar_rock_mute_16th",
    # デフォルトフォールバック用 (感情・強度がマップにない場合)
    ("default", "default"): "guitar_default_quarters",
    ("default", "low"): "guitar_ballad_arpeggio",
    ("default", "medium_low"): "guitar_ballad_arpeggio",
    ("default", "medium"): "guitar_folk_strum_simple",
    ("default", "medium_high"): "guitar_folk_strum_simple",
    ("default", "high"): "guitar_power_chord_8ths",
}

DEFAULT_GUITAR_STYLE = "guitar_default_quarters"
### OtoKotoba: ADD ### Emotion / Intensity -> Guitar-Pattern マッピング END

### OtoKotoba: ADD ### Pattern Selector START
class GuitarStyleSelector:
    """Return guitar pattern key according to (emotion, intensity) with overrides."""

    def __init__(self, mapping: Dict[Tuple[str, str], str] | None = None):
        self.mapping = mapping if mapping is not None else EMOTION_INTENSITY_MAP

    def select(self, *,
               emotion: str | None,
               intensity: str | None,
               mode_of_block: str | None = "default", # modular_composer.pyから渡される想定
               cli_override: str | None = None,
               section_override: str | None = None,
               part_params_override: str | None = None, # コードブロックのpart_specific_hintsからの指定用
               default_config_emotion_mode_map: Optional[Dict[str, Any]] = None # DEFAULT_CONFIGのemotion_mode_to_style_map
               ) -> str:

        # 優先順位:
        # 1. CLI Override (最優先)
        if cli_override:
            logger.info(f"GuitarStyleSelector: Using CLI override for guitar style: {cli_override}")
            return cli_override

        # 2. Chordmapのコードブロック内 part_specific_hints.guitar.guitar_style_key (またはguitar_rhythm_key)
        if part_params_override:
            logger.info(f"GuitarStyleSelector: Using part_params_override (from block's part_specific_hints): {part_params_override}")
            return part_params_override

        # 3. Chordmapのセクション全体 part_settings.guitar.guitar_style_key (またはguitar_rhythm_key)
        if section_override:
            logger.info(f"GuitarStyleSelector: Using section_override (from section's part_settings): {section_override}")
            return section_override

        # 4. DEFAULT_CONFIG の emotion_mode_to_style_map (Haruさんの以前の仕組みに近いもの)
        #    これは modular_composer.py の translate_keywords_to_params で既に解決されているはずだが、念のため。
        #    ただし、このSelectorの責務としては、より直接的なマッピング(EMOTION_INTENSITY_MAP)を優先する。
        #    もし translate_keywords_to_params での解決値を優先したい場合は、それを section_override や part_params_override として渡す。
        effective_emotion = (emotion or "default").lower()
        effective_intensity = (intensity or "default").lower()
        # effective_mode = (mode_of_block or "default").lower() # EMOTION_INTENSITY_MAPではモードを直接使わない

        # 5. EMOTION_INTENSITY_MAP に基づく選択
        key = (effective_emotion, effective_intensity)
        style = self.mapping.get(key)

        if style is None:
            # 特定の感情キーに対するフォールバック (強度が一致しない場合)
            style = self.mapping.get((effective_emotion, "default"))
            if style:
                 logger.info(f"GuitarStyleSelector: No direct map for ({effective_emotion}, {effective_intensity}). Using emotion-default: {style}")
                 return style

            # 特定の強度キーに対するフォールバック (感情が一致しない場合)
            style = self.mapping.get(("default", effective_intensity))
            if style:
                logger.info(f"GuitarStyleSelector: No direct map for ({effective_emotion}, {effective_intensity}). Using intensity-default: {style}")
                return style

            logger.warning(f"GuitarStyleSelector: No mapping for ({effective_emotion}, {effective_intensity}) in EMOTION_INTENSITY_MAP; falling back to {DEFAULT_GUITAR_STYLE}")
            return DEFAULT_GUITAR_STYLE

        logger.info(f"GuitarStyleSelector: Auto-selected guitar style via EMOTION_INTENSITY_MAP: {style} for ({effective_emotion}, {effective_intensity})")
        return style
### OtoKotoba: ADD ### Pattern Selector END


class GuitarGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None,
                 default_instrument=m21instrument.AcousticGuitar(),
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):
        self.rhythm_library = rhythm_library if rhythm_library is not None else {}
        if "guitar_default_quarters" not in self.rhythm_library:
             self.rhythm_library["guitar_default_quarters"] = {"description": "Default quarter note strums/hits", "pattern": [{"offset":i, "duration":1.0, "velocity_factor":0.8-(i%2*0.05)} for i in range(4)]}
             logger.info("GuitarGen: Added 'guitar_default_quarters' to rhythm_library.")
        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = get_time_signature_object(global_time_signature)
        self.style_selector = GuitarStyleSelector() ### OtoKotoba: ADD ### StyleSelectorのインスタンス化

    def _get_guitar_friendly_voicing(
        self, cs: harmony.ChordSymbol, num_strings: int = 6,
        preferred_octave_bottom: int = 2, # max_octave_top は現状未使用なのでコメントアウトも検討
        max_octave_top: int = 5,
    ) -> List[pitch.Pitch]:
        if not cs or not cs.pitches: return []
        original_pitches = list(cs.pitches); # root = cs.root() # root 変数は未使用
        # voiced_pitches: List[pitch.Pitch] = [] # voiced_pitches はこのスコープでは直接使われない

        try:
            # 適切なオクターブを指定してクローズドポジションを取得
            temp_chord = cs.closedPosition(forceOctave=preferred_octave_bottom, inPlace=False)
            candidate_pitches = sorted(list(temp_chord.pitches), key=lambda p_sort: p_sort.ps)
        except Exception as e_closed_pos: # より具体的な例外も補足できると良い
            logger.warning(f"GuitarGen: Error in closedPosition for {cs.figure}: {e_closed_pos}. Using original pitches.")
            candidate_pitches = sorted(original_pitches, key=lambda p_sort:p_sort.ps)

        if not candidate_pitches:
            logger.warning(f"GuitarGen: No candidate pitches for {cs.figure} after closedPosition. Returning empty.")
            return []

        # ギターの最低音E2 (MIDI 40) より低い音は調整
        guitar_min_ps = pitch.Pitch(f"E{DEFAULT_GUITAR_OCTAVE_RANGE[0]}").ps
        # ### OtoKotoba: MODIFIED ### candidate_pitchesが空でないことを確認
        if candidate_pitches and candidate_pitches[0].ps < guitar_min_ps:
            # math.ceil を使うために import math が必要
            oct_shift = math.ceil((guitar_min_ps - candidate_pitches[0].ps) / 12.0)
            candidate_pitches = [p_cand.transpose(int(oct_shift * 12)) for p_cand in candidate_pitches] # int()でキャスト
            candidate_pitches.sort(key=lambda p_sort: p_sort.ps)
        
        selected_dict: Dict[str, pitch.Pitch] = {}
        for p_cand_select in candidate_pitches:
            if pitch.Pitch(f"E{DEFAULT_GUITAR_OCTAVE_RANGE[0]}").ps <= p_cand_select.ps <= pitch.Pitch(f"G{DEFAULT_GUITAR_OCTAVE_RANGE[1]}").ps:
                if p_cand_select.nameWithOctave not in selected_dict:
                     selected_dict[p_cand_select.nameWithOctave] = p_cand_select

        final_voiced_pitches = sorted(list(selected_dict.values()), key=lambda p_sort:p_sort.ps)
        return final_voiced_pitches[:num_strings]


    def _create_notes_from_event(
        self, cs: harmony.ChordSymbol, guitar_params: Dict[str, Any],
        event_abs_offset: float, event_duration_ql: float, event_velocity: int
    ) -> List[Union[note.Note, m21chord.Chord]]:
        notes_for_event: List[Union[note.Note, m21chord.Chord]] = []
        style = guitar_params.get("guitar_style", STYLE_BLOCK_CHORD) # デフォルトを block_chord に

        num_strings = guitar_params.get("guitar_num_strings", 6)
        # preferred_octave_bottom に名前を変更 (役割に合わせて)
        preferred_octave_bottom = guitar_params.get("guitar_target_octave", guitar_params.get("target_octave",3))

        # chord_pitches はここで取得
        chord_pitches = self._get_guitar_friendly_voicing(cs, num_strings, preferred_octave_bottom)
        if not chord_pitches:
            logger.debug(f"GuitarGen: No guitar-friendly pitches for {cs.figure} with style {style}. Skipping event.")
            return []

        if style == STYLE_POWER_CHORDS and cs.root():
            p_root = pitch.Pitch(cs.root().name)
            # 適切なオクターブに調整 (ギターの低音域に合わせる)
            target_power_chord_octave = DEFAULT_GUITAR_OCTAVE_RANGE[0] # E2のオクターブ
            if p_root.octave < target_power_chord_octave:
                p_root.octave = target_power_chord_octave
            elif p_root.octave > target_power_chord_octave + 1: # あまり高くならないように
                p_root.octave = target_power_chord_octave + 1

            power_chord_pitches = [p_root, p_root.transpose(interval.PerfectFifth())]
            # オクターブ上のルート音を追加する場合、弦の数と音域を考慮
            if num_strings > 2:
                root_oct_up = p_root.transpose(interval.PerfectOctave())
                if root_oct_up.ps <= pitch.Pitch(f"G{DEFAULT_GUITAR_OCTAVE_RANGE[1]}").ps:
                    power_chord_pitches.append(root_oct_up)
            
            ch = m21chord.Chord(power_chord_pitches[:num_strings], quarterLength=event_duration_ql * 0.95)
            for n_in_ch_note in ch.notes: n_in_ch_note.volume.velocity = event_velocity
            ch.offset = event_abs_offset
            notes_for_event.append(ch)
            return notes_for_event

        if style == STYLE_BLOCK_CHORD:
            ch = m21chord.Chord(chord_pitches, quarterLength=event_duration_ql * 0.9) # 持続を少し短く
            for n_in_ch_note in ch.notes: n_in_ch_note.volume.velocity = event_velocity
            ch.offset = event_abs_offset
            notes_for_event.append(ch)
        elif style == STYLE_STRUM_BASIC:
            is_down = guitar_params.get("strum_direction", "down").lower() == "down"
            # ストラム時はボイシングされた音をそのまま使う
            play_order = list(reversed(chord_pitches)) if is_down else chord_pitches
            for i, p_obj_strum in enumerate(play_order):
                n_strum = note.Note(p_obj_strum)
                n_strum.duration = duration.Duration(quarterLength=max(MIN_STRUM_NOTE_DURATION_QL, event_duration_ql * 0.9))
                n_strum.offset = event_abs_offset + (i * GUITAR_STRUM_DELAY_QL)
                vel_adj_range = 10
                vel_adj = 0
                if len(play_order) > 1:
                    if is_down:
                        vel_adj = int(((len(play_order)-1-i)/(len(play_order)-1)*vel_adj_range)-(vel_adj_range/2))
                    else:
                        vel_adj = int((i/(len(play_order)-1)*vel_adj_range)-(vel_adj_range/2))
                n_strum.volume = m21volume.Volume(velocity=max(1, min(127, event_velocity + vel_adj)))
                notes_for_event.append(n_strum)
        elif style == STYLE_ARPEGGIO:
            arp_pattern_type = guitar_params.get("arpeggio_type", "up")
            arp_note_dur_ql = guitar_params.get("arpeggio_note_duration_ql", 0.5)

            ordered_arp_pitches: List[pitch.Pitch] = []
            if isinstance(arp_pattern_type, list): # 数値インデックスのリストの場合
                 ordered_arp_pitches = [chord_pitches[idx % len(chord_pitches)] for idx in arp_pattern_type if chord_pitches]
            elif arp_pattern_type == "down":
                ordered_arp_pitches = list(reversed(chord_pitches))
            elif arp_pattern_type == "up_down" and len(chord_pitches) > 2 :
                ordered_arp_pitches = chord_pitches + list(reversed(chord_pitches[1:-1]))
            else: # "up" or default
                ordered_arp_pitches = chord_pitches

            current_offset_in_event = 0.0; arp_idx = 0
            while current_offset_in_event < event_duration_ql and ordered_arp_pitches:
                p_play_arp = ordered_arp_pitches[arp_idx % len(ordered_arp_pitches)]
                actual_arp_dur = min(arp_note_dur_ql, event_duration_ql - current_offset_in_event)
                if actual_arp_dur < MIN_NOTE_DURATION_QL / 4.0: break # 128分音符より短い場合はスキップ
                n_arp = note.Note(p_play_arp, quarterLength=actual_arp_dur * 0.95) # 少し短く
                n_arp.volume = m21volume.Volume(velocity=event_velocity)
                n_arp.offset = event_abs_offset + current_offset_in_event
                notes_for_event.append(n_arp)
                current_offset_in_event += arp_note_dur_ql # 実際の音価ではなく、パターンの音価で進める
                arp_idx += 1
        elif style == STYLE_MUTED_RHYTHM:
            mute_note_dur = guitar_params.get("mute_note_duration_ql", 0.1)
            mute_interval = guitar_params.get("mute_interval_ql", 0.25) # リズムステップ
            t_mute = 0.0
            if not chord_pitches: return []
            mute_base_pitch = chord_pitches[0] # ミュート音はボイシングされた最低音などを使用
            while t_mute < event_duration_ql:
                actual_mute_dur = min(mute_note_dur, event_duration_ql - t_mute)
                if actual_mute_dur < MIN_NOTE_DURATION_QL / 8.0: break # 256分音符より短い場合はスキップ
                n_mute = note.Note(mute_base_pitch); n_mute.articulations = [articulations.Staccatissimo()]
                n_mute.duration.quarterLength = actual_mute_dur
                n_mute.volume = m21volume.Volume(velocity=int(event_velocity * 0.6) + random.randint(-5,5)) # ベロシティも調整
                n_mute.offset = event_abs_offset + t_mute
                notes_for_event.append(n_mute)
                t_mute += mute_interval
        else:
            logger.warning(f"GuitarGen: Unknown guitar style '{style}' for chord {cs.figure}. No notes generated for this event.")

        return notes_for_event


    def compose(self, processed_chord_stream: List[Dict],
                # ### OtoKotoba: ADD ### CLIからのスタイル指定を受け取る引数を追加 (modular_composer.pyから渡される想定)
                cli_guitar_style_override: Optional[str] = None
                ) -> stream.Part:
        guitar_part = stream.Part(id="Guitar")
        guitar_part.insert(0, self.default_instrument)
        guitar_part.insert(0, tempo.MetronomeMark(number=self.global_tempo))
        ts_copy_init = meter.TimeSignature(self.global_time_signature_obj.ratioString)
        guitar_part.insert(0, ts_copy_init)

        if not processed_chord_stream: return guitar_part
        logger.info(f"GuitarGen: Starting for {len(processed_chord_stream)} blocks.")

        all_generated_elements_for_part: List[Union[note.Note, m21chord.Chord]] = []

        for blk_idx, blk_data in enumerate(processed_chord_stream):
            block_offset_ql = float(blk_data.get("offset", 0.0))
            block_duration_ql = float(blk_data.get("q_length", 4.0))
            chord_label_str = blk_data.get("chord_label", "C") # "Rest" もそのまま受け取る
            
            # ### OtoKotoba: MODIFIED ### part_paramsの取得とログ出力
            guitar_params_from_block = blk_data.get("part_params", {}).get("guitar", {})
            logger.debug(f"GuitarGen Block {blk_idx+1}: Offset={block_offset_ql}, Dur={block_duration_ql}, Label='{chord_label_str}', RawParams={guitar_params_from_block}")
            
            if not guitar_params_from_block:
                logger.warning(f"GuitarGen: No guitar_params found for block {blk_idx+1}. Skipping.")
                continue

            if chord_label_str.lower() == "rest":
                logger.info(f"GuitarGen: Block {blk_idx+1} ('{chord_label_str}') is a Rest. Skipping guitar notes for this block.")
                continue

            sanitized_label = sanitize_chord_label(chord_label_str)
            cs_object: Optional[harmony.ChordSymbol] = None
            if sanitized_label: # sanitize_chord_labelがNone (Rest扱い) を返さなかった場合
                try:
                    cs_object = harmony.ChordSymbol(sanitized_label)
                    if not cs_object.pitches: # パースできても音がない場合 (例: "major"だけなど)
                        logger.warning(f"GuitarGen: ChordSymbol '{sanitized_label}' (from '{chord_label_str}') has no pitches. Treating as unplayable.")
                        cs_object = None
                except Exception as e_parse_guitar:
                    logger.warning(f"GuitarGen: Error parsing chord '{chord_label_str}' (sanitized: '{sanitized_label}') for block {blk_idx+1}: {e_parse_guitar}. Treating as unplayable.")
                    cs_object = None
            
            if cs_object is None: # 有効なコードオブジェクトが作れなかった場合
                logger.warning(f"GuitarGen: Could not create valid ChordSymbol for '{chord_label_str}' in block {blk_idx+1}. Skipping notes.")
                continue

            # ### OtoKotoba: MODIFIED ### スタイル選択ロジックの呼び出し
            current_musical_intent = blk_data.get("musical_intent", {})
            emotion = current_musical_intent.get("emotion")
            intensity = current_musical_intent.get("intensity")
            mode_of_block = blk_data.get("mode") # ブロックのモード

            # chordmapのpart_settingsやpart_specific_hintsからのスタイル指定キーを特定
            # modular_composer.pyのtranslate_keywords_to_paramsで解決されたものがguitar_params_from_blockに入っている想定
            section_style_override = guitar_params_from_block.get("guitar_style_key") # セクション設定由来
            block_specific_style_override = guitar_params_from_block.get("guitar_rhythm_key") # ブロック設定由来 (rhythm_keyもスタイル指定として使えるように)

            # GuitarStyleSelectorに渡す優先順位でキーを決定
            # 1. CLI (引数で受け取る)
            # 2. ブロック固有の指定 (part_specific_hints -> guitar_rhythm_key)
            # 3. セクション全体の指定 (part_settings -> guitar_style_key)
            final_rhythm_key = self.style_selector.select(
                emotion=emotion,
                intensity=intensity,
                mode_of_block=mode_of_block,
                cli_override=cli_guitar_style_override, # CLIからの指定を渡す
                part_params_override=block_specific_style_override, # ブロック固有
                section_override=section_style_override # セクション共通
            )
            logger.info(f"GuitarGen Block {blk_idx+1}: Selected rhythm_key='{final_rhythm_key}' for guitar.")

            # 決定されたリズムキーをguitar_params_from_blockに反映 (主にログやデバッグのため)
            guitar_params_from_block["guitar_rhythm_key"] = final_rhythm_key
            # 注意: guitar_style (strum_basic, arpeggioなど) はリズムキーとは別で、奏法を指定する。
            # style_selector はリズムキーを選択するので、guitar_style は別途 guitar_params_from_block から取得する。
            # もしEMOTION_INTENSITY_MAPが奏法も暗に含むなら、その情報をどう分離・活用するか設計が必要。
            # 現状のEMOTION_INTENSITY_MAPはリズムキーを返すと仮定。

            rhythm_details = self.rhythm_library.get(final_rhythm_key, self.rhythm_library.get("guitar_default_quarters"))
            if not rhythm_details or "pattern" not in rhythm_details:
                logger.warning(f"GuitarGen: Rhythm key '{final_rhythm_key}' not found or invalid pattern for block {blk_idx+1}. Using default rhythm 'guitar_default_quarters'.")
                rhythm_details = self.rhythm_library.get("guitar_default_quarters")
                if not rhythm_details or "pattern" not in rhythm_details:
                    logger.error(f"GuitarGen: Default rhythm 'guitar_default_quarters' is also missing or invalid. Skipping rhythm for block {blk_idx+1}.")
                    continue
            pattern_events = rhythm_details.get("pattern", [])

            for event_def in pattern_events:
                event_offset_in_pattern = float(event_def.get("offset", 0.0))
                event_duration_in_pattern = float(event_def.get("duration", 1.0)) # パターン内の相対デュレーション
                event_velocity_factor = float(event_def.get("velocity_factor", 1.0))

                abs_event_start_offset = block_offset_ql + event_offset_in_pattern
                
                # イベントの実際のデュレーションは、ブロックの終わりを超えないように調整
                max_possible_event_dur = block_duration_ql - event_offset_in_pattern
                actual_event_dur = min(event_duration_in_pattern, max_possible_event_dur)

                if actual_event_dur < MIN_NOTE_DURATION_QL / 2.0: # 短すぎるイベントはスキップ
                    logger.debug(f"GuitarGen: Skipping very short event (dur: {actual_event_dur:.3f} ql) at offset {abs_event_start_offset:.2f}")
                    continue
                
                event_base_velocity = int(guitar_params_from_block.get("guitar_velocity", 70) * event_velocity_factor)

                # _create_notes_from_event に渡す guitar_params は、ブロックのパラメータを渡す
                generated_elements = self._create_notes_from_event(
                    cs_object, guitar_params_from_block, abs_event_start_offset, actual_event_dur, event_base_velocity
                )
                all_generated_elements_for_part.extend(generated_elements)

        # ヒューマナイズ処理 (パート全体に一度だけ適用)
        # ### OtoKotoba: MODIFIED ### ヒューマナイズパラメータの取得方法を修正
        # processed_chord_streamが空の場合のガードを追加
        global_guitar_params_for_humanize = {}
        if processed_chord_stream:
            # 最初のブロックのパラメータを代表として使うか、あるいは全ブロックの平均などを取るか検討の余地あり
            # ここでは最初のブロックのパラメータからヒューマナイズ設定を取得する
            first_block_guitar_params = processed_chord_stream[0].get("part_params", {}).get("guitar", {})
            if first_block_guitar_params.get("humanize_opt", first_block_guitar_params.get("default_humanize", False)): # humanize_optを優先
                h_template = first_block_guitar_params.get("template_name", first_block_guitar_params.get("default_humanize_style_template", "default_guitar_subtle"))
                
                h_custom_params_dict = first_block_guitar_params.get("custom_params", {})
                # DEFAULT_CONFIG の default_humanize_*** も考慮してマージする (humanizer.py側のapply_humanization_to_partの挙動に依存)
                # ここでは、translate_keywords_to_params で解決された custom_params をそのまま使う
                
                logger.info(f"GuitarGen: Humanizing guitar part (template: {h_template}, custom_params from block: {h_custom_params_dict})")

                temp_part_for_humanize = stream.Part()
                # ゼロ位置からのオフセットで要素を挿入するため、元のオフセット情報を保持して挿入
                for el_item_guitar in all_generated_elements_for_part:
                    temp_part_for_humanize.insert(el_item_guitar.offset, el_item_guitar) # 既に絶対オフセットのはず

                guitar_part_humanized = apply_humanization_to_part(temp_part_for_humanize, template_name=h_template, custom_params=h_custom_params_dict)
                
                # apply_humanization_to_part が新しいPartを返すので、IDなどを再設定
                guitar_part_humanized.id = "Guitar"
                if not guitar_part_humanized.getElementsByClass(m21instrument.Instrument).first():
                    guitar_part_humanized.insert(0, self.default_instrument)
                if not guitar_part_humanized.getElementsByClass(tempo.MetronomeMark).first():
                    guitar_part_humanized.insert(0, tempo.MetronomeMark(number=self.global_tempo))
                if not guitar_part_humanized.getElementsByClass(meter.TimeSignature).first():
                    ts_copy_humanize = meter.TimeSignature(self.global_time_signature_obj.ratioString)
                    guitar_part_humanized.insert(0, ts_copy_humanize)
                guitar_part = guitar_part_humanized # Humanizeされたパートで置き換え
            else:
                logger.info("GuitarGen: Humanization skipped for guitar part based on parameters.")
                for el_item_guitar_final in all_generated_elements_for_part:
                    guitar_part.insert(el_item_guitar_final.offset, el_item_guitar_final)
        else: # processed_chord_streamが空の場合 (通常ありえないが念のため)
            logger.info("GuitarGen: No blocks to process, skipping humanization and note insertion.")


        logger.info(f"GuitarGen: Finished. Part has {len(list(guitar_part.flatten().notesAndRests))} elements.")
        return guitar_part

# --- END OF FILE generator/guitar_generator.py ---
