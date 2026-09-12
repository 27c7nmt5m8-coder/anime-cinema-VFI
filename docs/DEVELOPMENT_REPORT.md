# AnimeCinemaVFI v0.1.1 開発・検証レポート

作成日: 2026-09-10。基準ソース: `AnimeCinemaVFI_v0.1.0_Source.zip`。

v0.1.0の処理機能とOriginal Motion Preservationの方針を維持し、色、フレーム形式、
RIFEのGPU転送寿命、元FPS整数倍率の境界を改修した。大規模な将来機能は追加していない。
**Linux / Python 3.11の検証は完了。Windows 11・CUDA・NVENCの実機検証は未完了。**

## 変更点・修正した不具合

1. 共通FFmpegタグだけに依存せず、x264/x265固有VUIをColor Policyから設定する。
   `-x264-params range=limited`は検証環境で無効パラメーターとなることを確認し、
   有効な`fullrange=off`を使う。x265は`range=limited`を使用する。
2. 完成検査が色情報・SAR・画素形式の喪失を見逃す問題を修正。
   既知の期待値と不一致なら公開前にエラーとし、既存出力保護とcleanupを維持する。
3. `setsar`の既定上限100による比率の丸めを防ぐため、上限65535を指定。
   4/3に加え1001/1000をH.264/HEVCのコンテナとSPSで確認した。
   SARが不明だったことを`VideoInfo.sar_known`で区別し、既知SARの消失を見逃さない。
4. RIFEで同一pairをtimestepごとにGPU転送していた処理を、pairの再利用へ変更。
   複数timestepを1要求にし、既に成功した出力をOOM再試行で二重に送らない。
5. raw uint8配列だけの公開Frame契約をVideoFrameへ変更。
   テスト専用エンジンも契約に追従し、既存テストの対象・アサーションを維持した。
6. Source ×2/×5、CLIの任意整数倍率、正確な解決FPS表示を追加。
7. Windowsの長いファイル引数へextended path表現を使う境界を追加。
   UNC末尾区切りが消える問題も単体テストで修正した。Windows実機での動作は未検証。
8. GUIのSourceモードでは無効なCustom FPS入力欄を非表示にし、固定120との混同を防いだ。
9. Audio/Subtitleの言語・disposition・codec検証を追加。添付・音声オフセット・字幕の処理は維持。

## Color Metadata

`ColorMetadata`は入力のprimaries/transfer/matrix/range/depth/pixel format/side dataを保持する。
`ColorEncodingOptions`がSDR変換後の期待値、SAR、内部RGB形式、変換filterを決定する。
`EncoderColorPolicy`がbackend固有のFFmpeg引数へ変換し、`OutputValidator`が同じ期待値を検査する。

| Backend | 指定 |
|---|---|
| libx264 | 共通color flags + `colorprim/transfer/colormatrix/fullrange` |
| libx265 | 共通color flags + `colorprim/transfer/colormatrix/range`。既存のpools/frame-threads設定を同じparamsへ統合 |
| h264_nvenc / hevc_nvenc | FFmpeg AVCodecContextの共通color flagsからVUIへ渡す。実エンコード診断で可否を確認 |

入力色値をBT.709へ固定しない。BT.709、SMPTE170M、BT470BGとunknownをテストする。
unknown自体を必ず保存する判定にはしない。明確に既知の期待値が失われた場合に失敗する。
現行SDR policyはRGB fullからYUV420P limitedへ変換するため、full入力に対する出力rangeの
期待値はlimited。unknown値の推定は既知matrixまたは解像度を使い、警告する。

HDR / BT.2020 / 10bit以上 / bit depth不明の拒否を維持。HDR VFI、tone mapping、10bit出力を
解禁していない。HDR対応済みとは表示しない。

## VideoFrame / FrameFormat

`VideoFrame`は`data / timestamp: Fraction / format`を持つ。データは読取専用のHWC配列。
`FrameFormat`はdtype、bit_depth、channels、pixel_format、primaries、transfer、matrix、rangeを持つ。
uint8/uint16/float16/float32を表現できるが、現在のdecode→RIFE→encodeはRGB24/uint8。
内部RGBのmatrixはgbr、rangeはfullとして実際の表現を記録する。

`EngineCapabilities`で対応形式・dtype・depth・matrix/range・HDR/wide gamut・任意timestep・
複数timestepを宣言する。RIFEEngineはRGB8/SDRのみを受理する。
Registryには型付き`frame_capabilities`を追加し、旧Registryは安全なRGB8既定値で読み込む。
configもschema 1を維持し、新しいキーがないv0.1.0設定をfixedモードとして読み込む。

Frame別の色・高精度型をv0.5〜v0.7へ渡す基盤を作った。現時点のSceneDetectorは引き続き
RGB8用の簡易アルゴリズムで、HDR解析・planar画像・GPU resident公開Frameは未実装。

## RIFE multi-timestepとメモリ

`interpolate_many(pair, Sequence[Fraction]) → Iterator[VideoFrame]`を公開契約へ追加。
既存の単一時刻APIを残し、他エンジンには単一時刻ループの既定アダプターを提供する。
`PairRenderer`がカット・保持・モデル選択を先に判断して、同じengineへの連続要求をまとめる。
カットpairはcustom MotionDirectorが補間を要求してもVFIを呼ばない。

workerの`TensorPairCache`はCPU側に元RGB8を保持し、GPUへ一度転送、float化・padding後の
A/Bを複数時刻の推論で共用する。新pair、scale変更、OOM時に再構築する。
通常フレームではempty_cacheを呼ばない。OOM時は失敗traceback内のGPU参照も解除し、
cacheを解放してからempty_cacheを行い、1→0.5→0.25で未完了時刻を再試行する。

計画とIPCは最大32時刻、結果は1フレームずつ送信・消費する。全中間画像を蓄積しない。
Cancelは待機を解除しworker/FFmpegを終了する。途中異常・出力順不正・不完全payloadはジョブ失敗。

## Source FPS Multiplier

| 入力 | 設定 | 正確な出力FPS |
|---|---|---|
| 24000/1001 | Source ×5 | 120000/1001（GUI表示119.880 fps） |
| 24 | Source ×5 | 120 |
| 25 | Source ×5 | 125 |
| 30000/1001 | Source ×2 | 60000/1001 |

固定120とSource ×5を区別する。計算にfloatの累積加算を使わない。
正確なCFRと一致する格子原点なら元フレームnは出力n×倍率へ配置される。
入力PTSが粗く丸められているコンテナや、格子とずれたPreview開始、VFRではこの一致を保証しない。
その場合は警告する。意図的な止め・コマ打ちの解析や選択的補間はまだ行わない。

## テスト結果

| 検査 | 結果 |
|---|---|
| self review | 責務、色期待値、SPS/VUI、SAR上限、Frame契約、OOM寿命、Cancel、メモリ上限、トラック保持を確認・修正 |
| ruff check | 成功 |
| ruff format --check | 成功（66 Pythonファイル） |
| mypy | 成功（48 sourceファイル） |
| pytest / Python 3.11.16 | **130成功、4 skip、失敗0** |
| Unit / IPC / tensor寿命 | 90件成功 |
| FFmpeg結合 | 旧来13件に加え、color/SAR 20ケース、Source倍率・トラック追加回帰2件が成功 |
| GUI | 3件成功。起動、Source表示、別QThreadでStart/Pause/Resume/Cancel |
| 実RIFEモデル | 2件成功。5秒24→60、24000/1001→Source ×5 |
| GUI起動確認 | Linux offscreenイベントループで起動・入力読込・終了。スクリーンショット確認 |
| NVENC診断 | H.264/HEVCとも`Cannot load libcuda.so.1`。利用不可を検出。実機成功とはしていない |
| GPU benchmark | CUDAなしを検出してexit 2、性能値を作成しないことを確認 |

v0.1.0の64テストケースを維持した。元40個のtest関数も全て残っていることを照合。
テストを削除・skipへ変更して失敗を隠していない。4 skipはWindows長いパス1件、
CUDA実モデルメモリ寿命1件、NVENC 2件で、この実行環境に実機/driverがないため。
CPU上のtensor再利用と疑似OOMのテストは実行しているが、実際のCUDA OOMやメモリ耐久を
確認したとは扱わない。失敗履歴のうちUNC末尾区切りは修正後に成功を確認した。

生の検証出力は`verification/tests-python311.xml`、同txt、ruff/mypy結果、diagnostics.jsonに格納。
FFmpeg 6.1.1-3ubuntu5、PySide6 6.11.2、NumPy 2.2.6、PyTorch 2.14.0+cpu、torchvision 0.29.0+cpu。
OSはLinux x86_64。詳細は`verification/tested-environment.json`。
正式なWindows+RIFE推奨対象はPython 3.11。コアの上限バージョンは不必要に固定しない。

## 短時間の実演・性能改善の確認範囲

別途、人工動画128×72、24000/1001fps、AAC日本語タグ1トラックで5秒プレビューを実行。
実モデルPractical-RIFE 4.25 / CPU / Source ×5 / libx264 Fastで**600フレーム**を作成した。
119ペア準備で476中間フレームを生成。比較用の元フレーム保持動画も作成した。
実処理時間は約16.79秒（この低解像度素材・CPU環境の一例）。出力fpsは120000/1001。
色・SAR・画素形式・音声・フレーム数は完成検査と別FFprobe照合で確認。

同一pairの4時刻に対し、旧実装はA/Bを時刻ごと、新実装はA/Bを1回ずつ転送する構造。
CPUの再利用テストでは100推論に対し準備1回、同じ入力tensorの再利用を確認した。
**GPUの高速化率は未測定。CPUの時間からCUDA/NVENC性能は推定しない。**
`scripts/benchmark_rife.py`を追加し、実GPUで旧float32転送方式と新RGB8転送・pair再利用方式を
同じモデル・入力・scaleで交互に測定できる。decode/encode/IPCの時間は測定対象外。

CUDAテストはwarmup後、同一pair 200要求/800推論、さらにpair交換50回のallocated/reserved量を
検査する。小解像度の寿命テストであり4K・数時間の耐久保証ではない。

## Windows / CUDA / NVENC / FFmpegの状況

Windows 11、CUDA PyTorch、NVENC H.264/HEVC、4K、長尺は実機未検証。
`ci.yml`（Windows/Linux/Python 3.11）、`ffmpeg-color.yml`（FFmpeg 6/7/8）、
`windows-cuda.yml`（手動self-hosted GPU）を追加・強化したが、リモートCIは未実行。
FFmpeg 7/8/9を実検証済みとはしない。9は公式リリースを確認してからCIへ追加する。

`verify_windows.ps1`と`docs/WINDOWS_VALIDATION.md`にコマンドとチェックリストを用意。
`ACVFI_REQUIRE_CUDA=1`は必要なGPU環境やモデル欠落を失敗にし、実機ゲートの黙ったskipを防ぐ。

## 既知の問題・v0.2へ進む前の残件

- **Windows/CUDA実機での受け入れが残る。** 特に4K、実VRAM OOM、NVENCのVUI、長い/UNCパス、
  Cancel後のGPU解放、数時間23.976fpsのA/V同期を確認し、driver/PyTorch/FFmpegの組合せを記録する。
- シーン検出は簡易方式。フラッシュ・似た構図のカット・高速パンの誤判定があり得る。
  利用権のあるアニメ・映画素材での主観画質評価は未実施。
- コマ打ち・意図的静止・スミア・モーションブラーの意味を解析しない。HDR/10bit等も拒否を維持。
- VFRは明示許可時の実験対応。MKVのPTS丸め、audio copyのパケット境界、Preview開始を跨ぐ字幕や
  パケットのない区間、複雑な編集リストは引き続き追加検証が必要。
- 長尺Previewは全PTS走査と開始前decodeが必要。永続ジョブ再開、区間修復、tile fallbackは未実装。
- MP4/MKVの互換性制約、字幕の自動変換なし、チャプター・data・カバーアート・global metadataの
  非保持はv0.1.0のまま。通常Cancel時はcleanupするが、停電/強制終了ではlock等が残り得る。
- 検証はソース配布。署名EXE/インストーラー、全依存の商用再配布判断は完了していない。

**v0.2の設計・分離した開発には進める。Windows/CUDA対応を完了扱いにして安定版配布する段階ではない。**
上の実機ゲートはv0.2統合前に解消する。v0.2本実装をこの版へ混ぜていない。

## v0.2で変更する予定のファイル・インターフェース

| 対象 | 次の作業 |
|---|---|
| `core/extensions.py` | FrameContextへcadence/静止/カメラ情報と信頼度、MotionDirector.decideの判断 |
| `core/pair_renderer.py` | MotionDirectorの区間判断を補間/保持計画へ反映。カット保護と正確な原画時刻を維持 |
| `analysis/scene.py` | カット判定の強化・校正 |
| `analysis/cadence.py`（新規） | 重複、1/2/3コマ打ち、意図的静止の推定 |
| `analysis/motion.py`（新規） | パン・ズーム・動き量 |
| `video/timeline.py` / `video/output_fps.py` | 実PTSと公称/実効FPS、整数倍率の位置関係を解析へ接続 |
| `core/job.py` | 解析結果をdirectorへ渡す。モデル/エンコーダー固有処理は持ち込まない |
| `core/config.py` / `ui/window.py` | Anime/Cinema/Original Motion Preserve設定・解析表示 |
| `tests/` | コマ打ち、止め、パン、カットとA/V同期の回帰 |

VideoFrame/FrameFormat、EngineCapabilities、ColorEncodingOptions、EncoderColorPolicyは将来の
v0.3〜v0.7でも共通境界として維持する。必要な追加フィールドと新Policyで拡張する。
ロードマップはv0.2 Motion Director、v0.3 Multi VFI、v0.4 Artifact、v0.5 Semantic、
v0.6 Ultra Quality、v0.7 HDR/Color、v1.0 AI Autoのまま。

## 公式情報・ライセンス

公式Practical-RIFEの4.25推奨・Python<=3.11とMITの案内を再確認（2026-09-09）。
既存の固定commit `bbfd2ea90910789a860ea3e2b32a240cd577b75e`とモデル登録方式を維持した。
新しいランタイム依存は追加していない。モデル本体とアプリ本体のライセンスを混同せず、
モデル・FFmpeg・Qt/PyTorchバイナリを同梱しない。`THIRD_PARTY_LICENSES.md`を維持。

- [Practical-RIFE](https://github.com/hzwer/Practical-RIFE)
- [FFmpeg codecs](https://ffmpeg.org/ffmpeg-codecs.html)
- [x264 parameter parser](https://code.videolan.org/videolan/x264/-/blob/master/common/base.c)
- [x265 VUI options](https://x265.readthedocs.io/en/master/cli.html#vui-video-usability-information-options)
- [FFmpeg NVENC implementation](https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/nvenc.c)
- [FFmpeg release information](https://ffmpeg.org/download.html)
