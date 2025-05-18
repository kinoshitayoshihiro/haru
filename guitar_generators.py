# --- START OF FILE guitar_generator.py (新規作成案) ---
# (または、generators_core.py などに追記)
import music21

from typing import List, Dict, Optional, Tuple, Any, Sequence
from music21 import stream, note, harmony, pitch, meter, duration, instrument as m21instrument, scale, interval, tempo, key, chord as m21chord, articulations
import random
import logging

logger = logging.getLogger(__name__)
# (ロガー設定はファイルの先頭やメインスクリプトで行う想定)

# --- 定数 (GuitarGenerator用) ---
DEFAULT_GUITAR_OCTAVE_RANGE: Tuple[int, int] = (2, 4) # E2 (ギターの最低音) から C#5あたりまでを想定
GUITAR_STRUM_DELAY: float = 0.02 # ストラム時の各弦の発音遅延 (四分音符単位)
GUITAR_STYLE_BLOCK_STRUM = "block_strum"
GUITAR_STYLE_ARPEGGIO_UP = "arpeggio_up"
GUITAR_STYLE_ARPEGGIO_DOWN = "arpeggio_down"
GUITAR_STYLE_ARPEGGIO_UPDOWN = "arpeggio_updown"
GUITAR_STYLE_POWER_CHORDS = "power_chords" # ルートと5度 (オクターブ上も)

class GuitarGenerator:
    def __init__(self,
                 rhythm_library: Optional[Dict[str, Dict]] = None, # ストロークパターン用
                 default_instrument = m21instrument.AcousticGuitar(), # AcousticGuitar or ElectricGuitar
                 global_tempo: int = 120,
                 global_time_signature: str = "4/4"):

        self.rhythm_library = rhythm_library if rhythm_library else {}
        if rhythm_library and not self.rhythm_library.get("default_4_4"):
             self.rhythm_library["default_4_4"] = {"pattern": [0.0, 1.0, 2.0, 3.0], "durations": [1.0,1.0,1.0,1.0]}
             logger.warning("Added missing 'default_4_4' with durations to rhythm_library for GuitarGenerator.")

        self.default_instrument = default_instrument
        self.global_tempo = global_tempo
        self.global_time_signature_str = global_time_signature
        self.global_time_signature_obj = meter.TimeSignature(self.global_time_signature_str)

    def _get_guitar_friendly_voicing(self,
                                     m21_chord_symbol: harmony.ChordSymbol,
                                     num_strings: int = 6,
                                     preferred_octave: int = 3) -> List[pitch.Pitch]:
        """
        ギターで演奏しやすいボイシング（主に音域と弦の数を考慮）を生成する。
        ChordSymbolから得られるピッチを元に、適切なオクターブに配置し、弦の数に合わせる。
        """
        if not m21_chord_symbol.pitches:
            return []

        # まずはクローズドボイシングで基準を得る
        # forceOctave は全体の音域を固定しすぎるので、後で調整
        try:
            base_pitches = sorted(list(m21_chord_symbol.closedPosition(inPlace=False).pitches), key=lambda p: p.ps)
        except Exception: # ピッチがない、または closedPosition でエラーの場合
            base_pitches = sorted(list(m21_chord_symbol.pitches), key=lambda p: p.ps)


        if not base_pitches:
            return []

        # ギターの音域に近づける (E2あたりが最低音の目安)
        # ボトムノートを preferred_octave のE音あたりに持ってくる
        target_bottom_ps = pitch.Pitch(f"E{preferred_octave}").ps
        current_bottom_ps = base_pitches[0].ps
        octave_shift_for_bottom = round((target_bottom_ps - current_bottom_ps) / 12.0)
        
        shifted_pitches = [p.transpose(octave_shift_for_bottom * 12) for p in base_pitches]
        shifted_pitches.sort(key=lambda p: p.ps) # 再ソート

        # 弦の数に合わせてピッチを選択 (通常は下から、または重要な音を選択)
        # ここでは簡易的に下から num_strings を取るが、重複音の扱いなど改善の余地あり
        guitar_voicing = []
        # ルート音は必ず含めるようにする
        root_note = m21_chord_symbol.root()
        if root_note:
            # 移調後のルート音を探す
            shifted_root = pitch.Pitch(root_note.name)
            shifted_root.octave = shifted_pitches[0].octave # 最低音のオクターブに合わせるか、計算する
            # shifted_pitches 内にルート音（オクターブ違い含む）があればそれを使う
            found_root_in_shifted = None
            for sp in shifted_pitches:
                if sp.name == root_note.name:
                    found_root_in_shifted = sp
                    break
            if found_root_in_shifted:
                guitar_voicing.append(found_root_in_shifted)
            else: # なければ計算したものを追加 (音域考慮)
                 # shifted_root を shifted_pitches の最低音のオクターブに合わせる
                temp_root = pitch.Pitch(root_note.name)
                temp_root.octave = shifted_pitches[0].octave
                while temp_root.ps < pitch.Pitch(f"E{DEFAULT_GUITAR_OCTAVE_RANGE[0]}"): temp_root.octave +=1
                guitar_voicing.append(temp_root)


        # 残りの弦の音を追加 (重複を避けつつ、元のコードの音から)
        for p in shifted_pitches:
            if len(guitar_voicing) >= num_strings:
                break
            is_duplicate = False
            for voiced_p in guitar_voicing:
                if voiced_p.name == p.name: # オクターブ違いの同音は許容する場合もあるが、ここでは音名で重複チェック
                    is_duplicate = True
                    break
            if not is_duplicate and p.ps >= pitch.Pitch(f"E{DEFAULT_GUITAR_OCTAVE_RANGE[0]}").ps: # 最低音チェック
                 guitar_voicing.append(p)
        
        # それでも足りない場合、テンションや重複音を上のオクターブで追加 (簡易的)
        idx = 0
        while len(guitar_voicing) < num_strings and idx < len(shifted_pitches):
            p_to_add_octave_up = shifted_pitches[idx].transpose(12)
            if p_to_add_octave_up.ps <= pitch.Pitch(f"C{DEFAULT_GUITAR_OCTAVE_RANGE[1]+1}").ps: # 上限チェック
                 is_duplicate_name = any(vp.name == p_to_add_octave_up.name for vp in guitar_voicing)
                 if not is_duplicate_name: # 音名での重複を避ける
                     guitar_voicing.append(p_to_add_octave_up)
            idx +=1
        
        # 最終的にソート
        return sorted(list(set(guitar_voicing)), key=lambda p:p.ps)[:num_strings]


    def _create_strum(self,
                      chord_pitches: List[pitch.Pitch],
                      base_offset: float,
                      duration_ql: float,
                      velocity: int,
                      is_down_stroke: bool = True) -> List[note.Note]:
        """1回のストローク（ダウンまたはアップ）を生成する"""
        strum_notes = []
        if not chord_pitches: return []

        # ストローク方向でピッチの順序を変える (ダウン: 高音弦から低音弦へ / アップ: 低音弦から高音弦へ遅れて発音)
        # 実際の演奏とは逆の順序でノートをリストに入れると、遅延が自然に聞こえる
        play_order = list(reversed(chord_pitches)) if is_down_stroke else chord_pitches

        for i, p_obj in enumerate(play_order):
            n = note.Note(p_obj)
            n.duration = duration.Duration(quarterLength=duration_ql) # 全音符を基本に、後でアーティキュレーションで調整も
            n.offset = base_offset + (i * GUITAR_STRUM_DELAY) # 各弦のわずかな遅延
            # ベロシティも弦によって少し変えるとリアルになる (例: ダウンストロークは低音弦が少し強い)
            vel_adj = 0
            if is_down_stroke:
                vel_adj = - (i * 2) # 低音弦側(リストの後方)が少し強くなるように（iが大きいほど弱く）
            else:
                vel_adj = - ((len(play_order) - 1 - i) * 2) # 高音弦側(リストの後方)が少し強くなるように

            n.volume.velocity = max(1, min(127, velocity + vel_adj))
            strum_notes.append(n)
        return strum_notes

    def _create_arpeggio(self,
                         chord_pitches: List[pitch.Pitch],
                         base_offset: float,
                         block_duration_ql: float,
                         num_notes_in_pattern: int, # アルペジオパターンを何音で繰り返すか
                         pattern_type: str, # "up", "down", "updown"
                         note_duration_ql: float,
                         velocity: int) -> List[note.Note]:
        arpeggio_notes = []
        if not chord_pitches or num_notes_in_pattern == 0: return []

        ordered_pitches: List[pitch.Pitch]
        if pattern_type == GUITAR_STYLE_ARPEGGIO_DOWN:
            ordered_pitches = list(reversed(chord_pitches))
        elif pattern_type == GUITAR_STYLE_ARPEGGIO_UPDOWN:
            if len(chord_pitches) > 2:
                ordered_pitches = chord_pitches + list(reversed(chord_pitches[1:-1]))
            else: # 2音以下なら単純往復
                ordered_pitches = chord_pitches + list(reversed(chord_pitches)) if len(chord_pitches) == 2 else chord_pitches * 2
        else: # GUITAR_STYLE_ARPEGGIO_UP or default
            ordered_pitches = chord_pitches

        current_offset_in_block = 0.0
        arp_idx = 0
        while current_offset_in_block < block_duration_ql:
            if not ordered_pitches: break # 万が一空になったら終了
            p_to_play = ordered_pitches[arp_idx % len(ordered_pitches)]
            
            actual_note_duration = min(note_duration_ql, block_duration_ql - current_offset_in_block)
            if actual_note_duration < MIN_NOTE_DURATION_QL / 2: # 短すぎる
                break

            n = note.Note(p_to_play)
            n.duration = duration.Duration(quarterLength=actual_note_duration * 0.95) # 少し短く
            n.offset = base_offset + current_offset_in_block
            n.volume.velocity = velocity
            arpeggio_notes.append(n)

            current_offset_in_block += note_duration_ql # 次のノートの開始は固定の音価分進める
            arp_idx += 1
        return arpeggio_notes

    def compose(self, processed_chord_stream: List[Dict], style: str = GUITAR_STYLE_BLOCK_STRUM) -> stream.Part:
        guitar_part = stream.Part(id="Guitar")
        guitar_part.insert(0, self.default_instrument)
        guitar_part.append(tempo.MetronomeMark(number=self.global_tempo))
        guitar_part.append(self.global_time_signature_obj)
        # キー設定は任意

        if not processed_chord_stream:
            logger.info("Guitar generation skipped: processed_chord_stream is empty.")
            return guitar_part

        logger.info(f"Starting guitar generation for {len(processed_chord_stream)} blocks, style: {style}.")

        for blk_idx, blk in enumerate(processed_chord_stream):
            block_offset_ql = blk.get("offset", 0.0)
            block_duration_ql = blk.get("q_length", 4.0)
            chord_label_str = blk.get("chord_label", "C")
            logger.debug(f"Guitar Block {blk_idx+1}: Chord '{chord_label_str}', Offset {block_offset_ql}, Style {style}")

            try:
                m21_chord_symbol = harmony.ChordSymbol(chord_label_str)
                if not m21_chord_symbol.pitches:
                    logger.warning(f"Guitar: Chord '{chord_label_str}' has no pitches. Skipping.")
                    continue

                # ギター用のボイシングを取得
                guitar_voicing_pitches = self._get_guitar_friendly_voicing(m21_chord_symbol)
                if not guitar_voicing_pitches:
                    logger.warning(f"Guitar: Could not get friendly voicing for '{chord_label_str}'. Skipping block.")
                    continue
                
                block_velocity = blk.get("guitar_velocity", 70) # ブロックごとにベロシティ指定可能に

                if style == GUITAR_STYLE_BLOCK_STRUM:
                    # ここではリズムライブラリを使ってストロークパターンを生成することも可能
                    # 例: 4分音符ごとのダウンストローク
                    rhythm_key_for_guitar = blk.get("guitar_rhythm_key", "default_4_4") # 4分音符パターンをデフォルトに
                    r_details = self.rhythm_library.get(rhythm_key_for_guitar, self.rhythm_library.get("default_4_4"))
                    r_pattern_beats = r_details.get("pattern", [0.0,1.0,2.0,3.0])
                    r_durs = r_details.get("durations")

                    for i, beat_local_offset in enumerate(r_pattern_beats):
                        note_start_abs_offset = block_offset_ql + beat_local_offset
                        note_q_len: float
                        if r_durs and i < len(r_durs): note_q_len = r_durs[i]
                        elif i < len(r_pattern_beats) - 1: note_q_len = r_pattern_beats[i+1] - beat_local_offset
                        else:
                            bar_dur_ql = self.global_time_signature_obj.barDuration.quarterLength
                            rem_measure = bar_dur_ql - beat_local_offset
                            note_q_len = min(rem_measure, block_duration_ql - beat_local_offset)
                        
                        if note_q_len < MIN_NOTE_DURATION_QL / 2.0: continue

                        # ダウンストロークを生成
                        strum_notes = self._create_strum(guitar_voicing_pitches, note_start_abs_offset, note_q_len, block_velocity, is_down_stroke=True)
                        for n_obj in strum_notes:
                            guitar_part.insert(n_obj.offset, n_obj) # insertしないとオフセットがズレる

                elif style in [GUITAR_STYLE_ARPEGGIO_UP, GUITAR_STYLE_ARPEGGIO_DOWN, GUITAR_STYLE_ARPEGGIO_UPDOWN]:
                    arp_note_duration = blk.get("guitar_arp_note_duration", 0.5) # 8分音符アルペジオをデフォルトに
                    arp_notes = self._create_arpeggio(guitar_voicing_pitches, block_offset_ql, block_duration_ql,
                                                      len(guitar_voicing_pitches), style, arp_note_duration, block_velocity)
                    for n_obj in arp_notes:
                        guitar_part.insert(n_obj.offset, n_obj)
                
                elif style == GUITAR_STYLE_POWER_CHORDS:
                    root = m21_chord_symbol.root()
                    if root:
                        power_chord_pitches = [root, root.transpose(interval.PerfectFifth())]
                        # オクターブ上のルートも加えることが多い
                        power_chord_pitches.append(root.transpose(interval.PerfectOctave()))
                        # ギターの音域に調整
                        adjusted_power_chord_pitches = []
                        for p_power in power_chord_pitches:
                            temp_p = pitch.Pitch(p_power.name)
                            # E2 より下にならないように、かつC5より上にもなりすぎないように
                            while temp_p.ps < pitch.Pitch("E2").ps: temp_p.octave +=1
                            while temp_p.ps > pitch.Pitch("C5").ps and temp_p.octave > 1 : temp_p.octave -=1
                            adjusted_power_chord_pitches.append(temp_p)
                        
                        # リズムパターンに合わせてパワーコードを配置
                        rhythm_key_for_power = blk.get("guitar_rhythm_key", "rock8") # ロックらしいリズムをデフォルトに
                        r_details_p = self.rhythm_library.get(rhythm_key_for_power, self.rhythm_library.get("default_4_4"))
                        r_pattern_p = r_details_p.get("pattern", [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5])
                        r_durs_p = r_details_p.get("durations")

                        for i, beat_local_offset_p in enumerate(r_pattern_p):
                            note_start_p = block_offset_ql + beat_local_offset_p
                            note_q_len_p: float
                            if r_durs_p and i < len(r_durs_p): note_q_len_p = r_durs_p[i]
                            elif i < len(r_pattern_p) - 1: note_q_len_p = r_pattern_p[i+1] - beat_local_offset_p
                            else:
                                bar_dur_ql = self.global_time_signature_obj.barDuration.quarterLength
                                rem_measure = bar_dur_ql - beat_local_offset_p
                                note_q_len_p = min(rem_measure, block_duration_ql - beat_local_offset_p)
                            if note_q_len_p < MIN_NOTE_DURATION_QL / 2.0: continue

                            pc_chord = m21chord.Chord(adjusted_power_chord_pitches)
                            pc_chord.duration = duration.Duration(quarterLength=note_q_len_p * 0.9) # 少し短く歯切れよく
                            for n_in_pc in pc_chord: n_in_pc.volume.velocity = block_velocity
                            guitar_part.insert(note_start_p, pc_chord)
                    else:
                        logger.warning(f"Guitar: Could not get root for power chord style from '{chord_label_str}'.")


                # TODO: カッティングスタイルの実装 (短いデュレーション、休符、ゴーストノートなど)

            except harmony.HarmonyException as he:
                logger.error(f"Guitar: HarmonyException for chord '{chord_label_str}' in block {blk_idx+1}: {he}")
            except Exception as e:
                logger.error(f"Guitar: Unexpected error processing block {blk_idx+1} (chord: {chord_label_str}): {e}", exc_info=True)
        logger.info(f"Guitar generation finished. Part contains {len(guitar_part.flatten().notesAndRests)} elements.")
        return guitar_part

# --- END OF FILE guitar_generator.py ---