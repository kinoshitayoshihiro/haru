# --- START OF FILE vocal_generator.py (整形・修正案) ---
import music21

from typing import List, Dict, Optional, Any, Tuple # Tuple を追加
from music21 import stream, note, pitch, meter, duration, instrument as m21instrument, tempo, key, expressions # expressions を追加
import logging
import json # json をインポート (ファイルロードに必要)
import re

# (logging.basicConfig はメインスクリプトで行う想定)
logger = logging.getLogger(__name__)

# melody_generator_final.py から定数をインポートするか、ここで再定義
# from .melody_generator_final import MIN_NOTE_DURATION_QL # 例 (相対インポート)
MIN_NOTE_DURATION_QL = 0.25 # ここで定義する場合

DEFAULT_BREATH_DURATION_QL: float = 0.25
MIN_DURATION_FOR_BREATH_AFTER_NOTE_QL: float = 1.5 # 変更 (以前は2.0)
PUNCTUATION_FOR_BREATH: Tuple[str, ...] = ('、', '。', '！', '？', ',', '.', '!', '?')

DEFAULT_MICRO_TIMING_OFFSET_RANGE_QL: float = 0.02
DEFAULT_MICRO_TIMING_DURATION_SCALE_RANGE: float = 0.05
DEFAULT_MICRO_TIMING_VELOCITY_VARIATION: int = 8
class VocalGenerator:
    def __init__(self,
                 default_instrument = m21instrument.Vocalist(), # Voice() から Vocalist() に変更
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"
                 # Vocal part doesn't usually set its own key, it follows the song's key
                 # global_key_signature_tonic: str = "C",
                 # global_key_signature_mode: str = "major"
                 ):

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        try:
            self.global_time_signature_obj = meter.TimeSignature(self.global_time_signature_str)
        except meter.MeterException:
            logger.error(f"VocalGen: Invalid global time sig '{self.global_time_signature_str}'. Defaulting to 4/4.")
            self.global_time_signature_obj = meter.TimeSignature("4/4")
        # self.global_key_tonic = global_key_signature_tonic
        # self.global_key_mode = global_key_signature_mode

    def _parse_midivocal_data(self, midivocal_data: List[Dict]) -> List[Dict]:
        parsed_notes = []
        for item_idx, item in enumerate(midivocal_data):
            try:
                offset = float(item["Offset"])
                pitch_name = str(item["Pitch"])
                length = float(item["Length"])

                if not pitch_name: # ピッチ名が空やNoneの場合
                    logger.warning(f"Vocal note #{item_idx+1} has empty pitch. Skipping.")
                    continue
                try:
                    _ = pitch.Pitch(pitch_name) # パース可能かテスト
                except Exception as e_pitch:
                    logger.warning(f"Skipping vocal note #{item_idx+1} due to invalid pitch: '{pitch_name}' ({e_pitch})")
                    continue
                if length <= 0:
                    logger.warning(f"Skipping vocal note #{item_idx+1} with non-positive length: {length} for {pitch_name}")
                    continue
                parsed_notes.append({"offset": offset, "pitch_str": pitch_name, "q_length": length})
            except KeyError as ke:
                logger.error(f"Skipping vocal data item #{item_idx+1} due to missing key: {ke} in {item}")
            except ValueError as ve:
                logger.error(f"Skipping vocal data item #{item_idx+1} due to ValueError: {ve} in {item}")
            except Exception as e:
                logger.error(f"Unexpected error parsing vocal data item #{item_idx+1}: {e} in {item}", exc_info=True)
        
        parsed_notes.sort(key=lambda x: x["offset"])
        logger.info(f"Parsed {len(parsed_notes)} valid notes from midivocal_data.")
        return parsed_notes

    def _get_section_for_offset(self,
                                offset: float,
                                lyrics_timeline_data: List[Dict], # timelineを優先
                                chordmap_data: Dict[str, Dict] # フォールバック用
                               ) -> Optional[str]:
        # lyrics_timeline からセクションを特定
        for entry in lyrics_timeline_data:
            sec_name = entry.get("section")
            start_beat = entry.get("start_beat", -1.0)
            end_beat = entry.get("end_beat", -1.0) # end_beatがない場合は正確な判定が難しい
            if sec_name and start_beat >= 0:
                # end_beatがない場合は、次のセクションの開始までと仮定するか、大きな値を設定
                effective_end_beat = end_beat if end_beat > start_beat else start_beat + 1000 # 仮の大きな値
                if start_beat <= offset < effective_end_beat:
                    return sec_name
        
        # フォールバックとして chordmap を使う (より複雑なオフセット計算が必要)
        # この部分は、呼び出し側で processed_chord_stream にセクション情報を付与する方が堅牢
        logger.warning(f"No section found for offset {offset} in lyrics_timeline. Chordmap fallback needs improvement or data enrichment.")
        # (簡易フォールバック: chordmap のキーをイテレート)
        # calculated_offset = 0.0
        # for sec, info in chordmap_data.items():
        #     sec_len = len(info.get("chords", [])) * 4.0 # 4拍/コードと仮定
        #     if calculated_offset <= offset < calculated_offset + sec_len:
        #         return sec
        #     calculated_offset += sec_len
        return None


    def _insert_breaths(self, vocal_part: stream.Part, breath_duration_ql: float) -> stream.Part:
        logger.info(f"Attempting to insert breaths (duration: {breath_duration_ql}qL) into vocal part.")
        part_elements = list(vocal_part.flatten().notesAndRests)
        if not part_elements:
            return vocal_part

        new_part = stream.Part(id=vocal_part.id + "_breaths")
        new_part.insert(0, vocal_part.getElementsByClass(m21instrument.Instrument).first() or self.default_instrument)
        # Copy global elements like tempo and time signature
        for el_type in [tempo.MetronomeMark, meter.TimeSignature, key.Key]:
            global_el = vocal_part.getElementsByClass(el_type).first()
            if global_el:
                new_part.insert(0, global_el)

        # オフセットをキーにした要素の辞書を作成 (高速アクセスのため)
        # elements_by_offset = {el.offset: el for el in part_elements}
        
        # 変更を加える要素を一時的にリストに保持し、最後にまとめて新しいパートを構築
        final_elements_with_offsets: List[Tuple[float, Any]] = []

        for i, current_el in enumerate(part_elements):
            original_offset = current_el.offset
            original_duration_ql = current_el.duration.quarterLength

            final_elements_with_offsets.append((original_offset, current_el)) # まず元の要素を追加

            should_insert_breath_after = False
            
            if isinstance(current_el, note.Note) and current_el.lyric:
                if any(punc in current_el.lyric for punc in PUNCTUATION_FOR_BREATH):
                    if original_duration_ql > breath_duration_ql: # 音符を短くする余裕がある
                        current_el.duration.quarterLength = original_duration_ql - breath_duration_ql
                        logger.debug(f"Shortened note {current_el.pitch} at {original_offset:.2f} for breath (punctuation). New dur: {current_el.duration.quarterLength:.2f}")
                        should_insert_breath_after = True
                    else:
                        logger.debug(f"Note {current_el.pitch} at {original_offset:.2f} too short for breath after punctuation.")
            
            if not should_insert_breath_after and isinstance(current_el, note.Note) and \
               original_duration_ql >= MIN_DURATION_FOR_BREATH_AFTER_NOTE_QL:
                # 次の要素がノートで、かつ隙間があまりない場合にブレスを検討
                if i + 1 < len(part_elements):
                    next_el = part_elements[i+1]
                    gap_to_next = next_el.offset - (original_offset + original_duration_ql)
                    if isinstance(next_el, note.Note) and gap_to_next < breath_duration_ql * 0.5:
                        if original_duration_ql > breath_duration_ql:
                            current_el.duration.quarterLength = original_duration_ql - breath_duration_ql
                            logger.debug(f"Shortened note {current_el.pitch} at {original_offset:.2f} for breath (long note). New dur: {current_el.duration.quarterLength:.2f}")
                            should_insert_breath_after = True
                        else:
                             logger.debug(f"Note {current_el.pitch} at {original_offset:.2f} too short for breath after long note.")
                else: # 曲の最後のノートの後
                     should_insert_breath_after = True # この場合はノートを短くしない

            if should_insert_breath_after:
                breath_offset = current_el.offset + current_el.duration.quarterLength # 短縮後のオフセット
                # 後続の要素と衝突しないか確認
                can_add_breath = True
                if i + 1 < len(part_elements):
                    if breath_offset + breath_duration_ql > part_elements[i+1].offset + 0.001: # わずかな重複許容
                        can_add_breath = False
                        logger.debug(f"Breath at {breath_offset:.2f} would overlap with next element at {part_elements[i+1].offset:.2f}. Skipping breath.")
                
                if can_add_breath:
                    breath_rest = note.Rest(quarterLength=breath_duration_ql)
                    final_elements_with_offsets.append((breath_offset, breath_rest))
                    logger.info(f"Scheduled breath at offset {breath_offset:.2f}qL for {breath_duration_ql:.2f}qL.")
        
        # 新しい要素リストをオフセットでソート
        final_elements_with_offsets.sort(key=lambda x: x[0])

        # 新しいパートに要素を挿入
        for offset, element in final_elements_with_offsets:
            new_part.insert(offset, element)
        
        logger.info(f"Breath insertion process completed. New part has {len(new_part.flatten().notesAndRests)} elements.")
        return new_part


    def _apply_micro_timing_adjustments(
            self,
            vocal_part: stream.Part,
            offset_range_ql: float = DEFAULT_MICRO_TIMING_OFFSET_RANGE_QL,
            duration_scale_range: float = DEFAULT_MICRO_TIMING_DURATION_SCALE_RANGE,
            velocity_variation: int = DEFAULT_MICRO_TIMING_VELOCITY_VARIATION
    ) -> stream.Part:
        logger.info("Applying micro-timing adjustments...")
        
        # 新しいPartを作成して、調整済みのノートをそこに追加する方が安全
        adjusted_part = stream.Part(id=vocal_part.id + "_timed")
        adjusted_part.insert(0, vocal_part.getElementsByClass(m21instrument.Instrument).first() or self.default_instrument)
        for el_type in [tempo.MetronomeMark, meter.TimeSignature, key.Key]: # グローバル要素コピー
            global_el = vocal_part.getElementsByClass(el_type).first()
            if global_el: adjusted_part.insert(0, global_el)

        for n_orig in vocal_part.flatten().notesAndRests:
            if isinstance(n_orig, note.Note):
                n_adj = note.Note(n_orig.pitch) # ピッチをコピー
                n_adj.lyric = n_orig.lyric # 歌詞をコピー

                original_offset = n_orig.offset
                original_duration = n_orig.duration.quarterLength
                original_velocity = n_orig.volume.velocity if hasattr(n_orig.volume, 'velocity') else 64

                time_shift = random.uniform(-offset_range_ql, offset_range_ql)
                new_offset = max(0.0, original_offset + time_shift)

                duration_scaler = 1.0 + random.uniform(-duration_scale_range, duration_scale_range)
                new_duration_ql = max(MIN_NOTE_DURATION_QL / 2.0, original_duration * duration_scaler)

                vel_shift = random.randint(-velocity_variation, velocity_variation)
                new_velocity = max(1, min(127, original_velocity + vel_shift))

                n_adj.duration.quarterLength = new_duration_ql
                n_adj.volume.velocity = new_velocity
                
                adjusted_part.insert(new_offset, n_adj) # 新しいオフセットで挿入
                logger.debug(f"Adjusted Note {n_adj.nameWithOctave}: Off {original_offset:.2f}->{new_offset:.2f}, Dur {original_duration:.2f}->{new_duration_ql:.2f}, Vel {original_velocity}->{new_velocity}")
            
            elif isinstance(n_orig, note.Rest): # 休符もオフセットをわずかに揺らすか、そのままか
                r_adj = note.Rest(quarterLength=n_orig.duration.quarterLength)
                # 休符のオフセットも揺らすと、ノートとの間の「間」が変わる
                # time_shift_rest = random.uniform(-offset_range_ql / 2, offset_range_ql / 2) # ノートより揺らぎを小さく
                # new_offset_rest = max(0.0, n_orig.offset + time_shift_rest)
                # adjusted_part.insert(new_offset_rest, r_adj)
                adjusted_part.insert(n_orig.offset, r_adj) # 休符はオフセットそのまま
                logger.debug(f"Kept Rest at {n_orig.offset:.2f} for {n_orig.duration.quarterLength:.2f} qL")


        # オフセットが変更された可能性があるので、パートをクリーンアップ
        # makeMeasures().stripTies() は、予期せぬ挙動をすることがあるので慎重に
        # cleaned_adjusted_part = adjusted_part.makeMeasures()
        # cleaned_adjusted_part.stripTies(inPlace=True)
        # return cleaned_adjusted_part
        
        # ここでは、単純に挿入した結果のパートを返す
        # music21がよしなにソートしてくれることを期待
        logger.info("Micro-timing adjustments application finished.")
        return adjusted_part


    def compose(self,
                midivocal_data: List[Dict],
                kasi_rist_data: Dict[str, List[str]],
                lyrics_timeline_data: List[Dict],
                chordmap_data: Dict[str, Dict], # セクション情報取得のため
                insert_breaths: bool = True,
                breath_duration_ql: float = DEFAULT_BREATH_DURATION_QL,
                apply_micro_timing: bool = True,
                micro_timing_params: Optional[Dict[str, Any]] = None
                ) -> stream.Part:

        vocal_part_initial = stream.Part(id="VocalRaw")
        # グローバル要素の追加 (前回同様)
        vocal_part_initial.insert(0, self.default_instrument)
        vocal_part_initial.append(tempo.MetronomeMark(number=self.global_tempo))
        try:
            vocal_part_initial.append(meter.TimeSignature(self.global_time_signature_str))
            # vocal_part_initial.append(key.Key(self.global_key_tonic, self.global_key_mode.lower())) # キーは任意
        except Exception as e_glob_init:
             logger.error(f"Error setting global elements for vocal_part_initial: {e_glob_init}")
             vocal_part_initial.append(meter.TimeSignature("4/4"))


        parsed_notes = self._parse_midivocal_data(midivocal_data)
        if not parsed_notes:
            return vocal_part_initial # 空のパートを返す

        # --- 歌詞割り当て ---
        logger.info(f"Assigning lyrics to {len(parsed_notes)} vocal notes...")
        # (前回提示した歌詞割り当てループのロジックをここに記述)
        # ... (セクション管理、歌詞インデックス管理、同一オフセットの歌詞重複防止など) ...
        current_section_name: Optional[str] = None
        current_lyrics_for_section: List[str] = []
        current_lyric_idx: int = 0
        last_lyric_assigned_offset: float = -1.001 # 最初のノートで必ず割り当てられるように初期値を調整
        LYRIC_OFFSET_THRESHOLD: float = 0.005 # 同一オフセットとみなす閾値

        for note_data in parsed_notes:
            note_offset = note_data["offset"]
            note_pitch_str = note_data["pitch_str"]
            note_q_length = note_data["q_length"]
            
            section_for_note = self._get_section_for_offset(note_offset, chordmap_data, lyrics_timeline_data)
            
            if section_for_note != current_section_name:
                if current_section_name and current_lyric_idx < len(current_lyrics_for_section):
                     logger.warning(f"{len(current_lyrics_for_section) - current_lyric_idx} lyrics left in '{current_section_name}'.")
                current_section_name = section_for_note
                current_lyrics_for_section = kasi_rist_data.get(current_section_name, []) if current_section_name else []
                current_lyric_idx = 0
                last_lyric_assigned_offset = -1.001 # セクション変更でリセット
                if current_section_name:
                    logger.info(f"Switched to lyric section: '{current_section_name}' ({len(current_lyrics_for_section)} syllables).")
                else:
                    logger.warning(f"Note at offset {note_offset} has no section. No lyrics will be assigned.")

            try:
                m21_n = note.Note(note_pitch_str, quarterLength=note_q_length)
            except Exception as e:
                logger.error(f"Failed to create Note object for {note_pitch_str} at {note_offset}: {e}")
                continue

            if current_section_name and current_lyric_idx < len(current_lyrics_for_section):
                if abs(note_offset - last_lyric_assigned_offset) > LYRIC_OFFSET_THRESHOLD:
                    m21_n.lyric = current_lyrics_for_section[current_lyric_idx]
                    logger.debug(f"Lyric '{m21_n.lyric}' to note {m21_n.nameWithOctave} at {note_offset:.2f} (Sec: {current_section_name})")
                    current_lyric_idx += 1
                    last_lyric_assigned_offset = note_offset
                else:
                    logger.debug(f"Skipped lyric for note {m21_n.nameWithOctave} at same offset {note_offset:.2f} as prev lyric.")
            
            vocal_part_initial.insert(note_offset, m21_n)
        # --- 歌詞割り当てここまで ---

        final_vocal_part = vocal_part_initial
        if insert_breaths:
            final_vocal_part = self._insert_breaths(final_vocal_part, breath_duration_ql)

        if apply_micro_timing:
            mt_params = micro_timing_params or {}
            final_vocal_part = self._apply_micro_timing_adjustments(
                final_vocal_part,
                offset_range_ql=mt_params.get("offset_range_ql", DEFAULT_MICRO_TIMING_OFFSET_RANGE_QL),
                duration_scale_range=mt_params.get("duration_scale_range", DEFAULT_MICRO_TIMING_DURATION_SCALE_RANGE),
                velocity_variation=mt_params.get("velocity_variation", DEFAULT_MICRO_TIMING_VELOCITY_VARIATION)
            )
        
        # 最終的なパートID設定
        final_vocal_part.id = "Vocal"
        logger.info(f"VocalGenerator.compose: Finished. Final part has {len(final_vocal_part.flatten().notesAndRests)} elements.")
        return final_vocal_part

# --- END OF FILE vocal_generator.py (整形・修正案) ---