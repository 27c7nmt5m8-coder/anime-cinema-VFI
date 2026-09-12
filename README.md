# AnimeCinemaVFI v0.1.1

Windows 11向け「アニメ・映画特化型AIフレーム補間ソフト」の基盤版です。
**Original Motion Preservation**を設計の中心に置き、GUIと映像処理、補間モデル、
エンコーダーを分離しました。120fpsそのものを「高画質」とは扱いません。

今回は**ソースコード版**です。Windows用の署名済みEXE・インストーラーは含みません。
Linux / Python 3.11でGUI起動、実FFmpeg処理、公式RIFE 4.25のCPU推論を検証しています。
Windows 11実機、CUDA、NVENCの実動確認は未完了です。詳しくは
[検証・開発レポート](docs/DEVELOPMENT_REPORT.md)を参照してください。

## 実装範囲

- PySide6 GUI、日本語・空白入りパス、ドラッグ＆ドロップ、ファイル選択。
- FFprobeによる解像度、fps、codec、bit depth、色タグ、HDR side data、音声・字幕情報。
- NVIDIA/CUDAの自動検出、GPU名・ドライバー・PyTorch/CUDA版・VRAM表示。CPU処理も選択可能。
- 公式Practical-RIFE 4.25を別プロセスで実行。モデルRegistryと登録時SHA256記録。
- 60 / 120 / Custom FPS / Source ×2 / Source ×5（CLIは1～20倍）。`24000/1001`、`60000/1001`、`120000/1001`等を有理数で計算。
- H.264 / HEVCのソフトウェアエンコード、NVENC呼び出し。High / Balanced / Fast。
- 全音声トラックのコピー、明示的なAAC変換、互換字幕・MKV添付ファイルの保持。
- 基本的なカット検出と、カットを跨ぐ補間の禁止。
- 開始位置指定と5 / 10 / 30秒プレビュー、元タイミング参照動画の同時作成。
- ワーカー処理、処理進捗、一時停止・再開・キャンセル、回転ファイルログ、GUIログ。
- VFRの全PTS検査、ディスク容量チェック、一時領域管理、既存出力の保護、完成後のフレーム数検証。

**v0.2以降のコマ打ち推定、作画意図解析、領域別補間、破綻修復、超解像、HDR VFI、
AI Autoは実装していません。** 拡張契約だけを用意しています。

## v0.1.1の変更

- ColorMetadata → ColorEncodingOptions → EncoderColorPolicyへ責務を分離。
  x264は`colorprim/transfer/colormatrix/fullrange`、x265は対応VUIパラメーターを明示。
  **libx264のAPIでは`range=limited`は無効になるため、`fullrange=off`を使用します。**
  色値は入力とSDR変換方針から生成し、BT.709へ固定しません。
- 完成後にprimaries、transfer、matrix、range、SAR、pixel format、bit depthを検証。
  失われた既知値はエラーとし、未完成ファイルを完成名で公開しません。
  libx264/libx265はコンテナと取り出したビットストリームで色回帰を確認しています。
- `VideoFrame(data, timestamp, format)`と`FrameFormat`を導入。
  uint8/uint16/float16/float32の表現を持てますが、**実際のRIFEはRGB8のみ**です。
- RIFEへ同一pairの複数timestepを1リクエストで渡し、GPU tensorを再利用する実装へ変更。
  出力を逐次送るため、長い区間の全中間画像を蓄積しません。カットpairはVFIを呼びません。
- OOM時だけcacheを解放してscale 1→0.5→0.25へ再試行。正常時の毎フレームempty_cacheは行いません。
- Source ×2/×5、Windows用長いパス処理、実NVENC診断、GPU専用回帰・メモリ寿命テストを追加。

GPU実測の高速化率は未取得です。転送をペア単位にまとめ、転送データをRGB8に変更しましたが、
実際の速度とVRAM挙動はCUDA機で`scripts/benchmark_rife.py`と専用テストを実行して確認してください。
[実機検証手順](docs/WINDOWS_VALIDATION.md)と[変更ファイル一覧](docs/CHANGES_V0.1.1.md)を同梱しています。

## Windowsでのセットアップ

### 1. 必要なもの

1. Windows 11、64bit Python 3.11、Git for Windows。
2. `ffmpeg.exe` / `ffprobe.exe`を含むFFmpeg。ローカル実検証はFFmpeg 6.1.1です。
   6/7/8系の色回帰CIを用意していますが、7/8/9の実行済みとはしていません。
3. CUDAを使う場合は対応NVIDIA GPUとドライバー。
4. モデルと動画処理のための空き容量。動画全体を画像連番で展開しませんが、
   中間動画と完成候補を同時に置くため、出力動画の数倍の空きを用意してください。

入手先：[Python](https://www.python.org/downloads/windows/) / [Git](https://git-scm.com/download/win) /
[FFmpeg公式のダウンロード案内](https://ffmpeg.org/download.html) /
[PyTorch公式セットアップ](https://pytorch.org/get-started/locally/)

Practical-RIFEの公式READMEはPython 3.11以下を案内しています。
v0.1.1ではPython 3.11.16で実推論・GUI・回帰テストを実行しました。
Windows+RIFEの推奨・検証対象は3.11です。コアの`requires-python`は>=3.11を維持します。
モデル・FFmpeg・PyTorch・Qtのバイナリはこのパッケージに同梱していません。

### 2. Python環境

ZIPを展開し、`README.md`と同じフォルダーでPowerShellを開きます。
仮想環境のActivateは不要です。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-core.txt -e ".[dev]"
```

NVIDIA CUDA版の導入例です。GPU・ドライバーに適した配布チャネルは上記の
PyTorch公式ページで確認してください。下記はCUDA 12.8のチャネルを使います。

```powershell
.\.venv\Scripts\python.exe -m pip install "torch>=2.6,<3" "torchvision>=0.21,<1" --index-url https://download.pytorch.org/whl/cu128
```

CPUで動作確認する場合：

```powershell
.\.venv\Scripts\python.exe -m pip install "torch>=2.6,<3" "torchvision>=0.21,<1" --index-url https://download.pytorch.org/whl/cpu
```

Python環境の作成は`Setup.ps1 -Backend cuda`または`Setup.ps1 -Backend cpu`でも行えます。
PowerShellの設定でスクリプトを実行できない場合は、上記の個別コマンドを使ってください。
Setupはシステムの実行ポリシーを変更しません。

### 3. FFmpeg

FFmpegの`bin`をPATHに追加するか、GUIの「設定」で実行ファイルを選択します。
例えば`C:\Tools\ffmpeg\bin\ffmpeg.exe`と`ffprobe.exe`を指定します。

```powershell
ffmpeg -version
ffprobe -version
ffmpeg -hide_banner -encoders
```

H.264には`libx264`、HEVCには`libx265`、NVENCには`h264_nvenc` / `hevc_nvenc`が必要です。
NVENCが一覧に存在しても、GPU・ドライバーで実際に起動できるかは別の確認が必要です。
Previewの元タイミング参照には`libx264`を使用します。

### 4. 公式RIFEモデル

初期候補は**Practical-RIFE 4.25**です。2026-09-09に確認した
[公式README](https://github.com/hzwer/Practical-RIFE)の推奨に基づいています。
モデルを最新版番号だけで自動選択しません。出典とリポジトリの固定commitは
`src/animecinemavfi/models/catalog.json`に集約しています。

次の任意ヘルパーは公式リポジトリを取得し、公式配布ZIPを展開・登録します。

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rife.py --download-model
```

Google Driveが確認画面や制限を返してダウンロードできない場合は、公式READMEの
4.25のリンクから手動でダウンロードしてください。必要な配置は次のとおりです。

| 場所 | 内容 |
|---|---|
| `external/Practical-RIFE/model/` | 公式リポジトリに含まれる補助コード |
| `external/Practical-RIFE/train_log/RIFE_HDv3.py` | 公式4.25のModelクラス |
| `external/Practical-RIFE/train_log/IFNet_HDv3.py` | 公式4.25のネットワーク |
| `external/Practical-RIFE/train_log/flownet.pkl` | 対応する学習済み重み |
| `external/Practical-RIFE/train_log/*.py` | 同じモデルZIPのその他のPythonファイル |

モデルのPythonコードは実行されます。公式配布元から取得したファイルを使用してください。
GUIの「RIFEフォルダー登録」で`RIFE_HDv3.py`を選ぶか、次のコマンドで登録します。

```powershell
.\.venv\Scripts\python.exe -m animecinemavfi register-model external\Practical-RIFE\train_log
```

モデルをアプリへ埋め込みません。別モデルを追加するときはRegistryに別IDを用意し、
対応する`VideoInterpolationEngine`を実装します。任意の旧RIFEを4.25の名前で登録しても、
実行時のversion・必要な重みの検査を通過できません。

### 5. 起動

```powershell
.\.venv\Scripts\python.exe -m animecinemavfi
```

以降は`Launch.bat`からも起動できます。
PATH上のFFmpegを使い、実エンコード・SPS/VUIまで調べる環境診断です。

```powershell
.\.venv\Scripts\python.exe -m animecinemavfi diagnose --encoders --output diagnostics.json
```

## GUIの使い方

1. 動画をドロップし、入力情報を確認します。
2. 出力先、fps、Encoder、Quality、RIFE modelを指定します。既定のMKVがトラック保持に適しています。
3. Scene Change Protectionを有効にします。4KではScale 0.5を初期候補にしてください。
4. Previewで5秒程度を処理し、出力と「元タイミング参照」を開いて確認します。
5. 設定を調整してからStartで本編を処理します。

プレビューは本編と別のファイル名になり、繰り返すと連番を付けます。
比較参照は**元フレームを出力FPSに合わせて保持し、再エンコードした動画**です。
元ファイルそのものの無劣化コピーではありません。GUI内の同時再生・Side-by-Sideは未実装です。

PauseはPTS検査・補間中の安全な境界で止まります。発行済みバッチの少数の推論結果が
進んでから止まる場合があります。モデル準備・最終mux中はPauseを無効にし、Cancelは使用可能です。
ETAは出しません。フレーム単位の進捗と、処理段階を表示します。

## タイミング・色・音声について

- 元PTSと出力格子が一致したフレームはVFIに通しません。ただし色変換・再圧縮は行います。
- **Source ×5**は元FPSへ5を掛けます。24000/1001入力なら`120000/1001`、
  GUIには **119.880 fps (120000/1001)** と表示します。固定120.000 fpsとは異なります。
- 24 ×5 =120、25 ×5 =125、30000/1001 ×2 =60000/1001。計算はFractionで行います。
  正確なCFR入力で格子原点が一致する場合、元フレームnを出力n×倍率へ配置できます。
  入力PTS自体がMKV等で丸められている場合やプレビュー開始が格子とずれる場合は
  一致しないことがあり、警告します。倍率だけでコマ打ち・作画意図は判断しません。
- 24→60、23.976→120等では、すべての元フレームを正確な時刻のままCFRへ配置することはできません。
- `23.976`、`29.97`、`59.94`の入力文字列は放送系の分数へ正規化します。
  `23.976`そのものの有限小数を指定したい場合は`2997/125`と入力してください。
- 内部PTSは有理数です。MP4は指定fpsの分子をtrack timescaleに使います。
  FFmpegのMKV出力は通常1ms単位のPTS丸めがあり、表示されるfpsもわずかに近似されます。
  これはフレームごとの時刻丸めで、floatの加算による累積ドリフトとは異なります。
- VFRは全フレームのPTSを調べて検出します。既定では停止し、明示的に許可したときだけ
  実PTSを使ってCFR化します。複雑なVFR・編集リストへの完全対応は保証していません。
- **HDR / BT.2020 / 10bit以上はメタデータ表示のみ。v0.1では処理を拒否します。**
  HDR対応済みとは表示せず、無断のSDR変換も行いません。
- 8bit SDRはRGB24でVFIし、YUV420のlimited rangeへ出力します。既知の色タグとSARを引き継ぎます。
  色タグ不明の場合は既知のmatrix、なければ解像度からBT.709/BT.601を推定し、警告します。
  full入力のrangeは変換後のlimitedを期待値として検証します。
- 音声を元ビデオPTSの起点・プレビュー開始時刻に合わせて移動します。全音声を明示的にmapします。
  コピーではプレビュー境界に音声パケット単位の端数が出ます。サンプル単位の切断は保証しません。
- コピーできない音声を自動で再圧縮しません。MP4に合わない音声はMKV出力またはAAC変換を選びます。
- 字幕は互換コンテナへコピーします。ASS/SRT等をMP4へコピーすることはできません。
  mov_text字幕のMKVコピーも未対応です。字幕の装飾を黙って変える変換は行いません。
- チャプター、グローバルメタデータ、dataトラック、カバーアートはこの版では引き継ぎません。

## CLIでの短時間テスト

```powershell
.\.venv\Scripts\python.exe -m animecinemavfi process "C:\Videos\input.mp4" "C:\Videos\preview.mkv" --source-multiplier 5 --preview-start 10 --preview-seconds 5 --device cuda --scale 0.5
```

CLIではCtrl+Cでキャンセルできます。CLIは既存の出力を上書きしません。

## 設定・ログ・一時ファイル

Windowsでは`%LOCALAPPDATA%\AnimeCinemaVFI`に`config.json`、`models.json`、`logs/application.log`を保存します。
通常ログは2MB×最大4本で回転し、GUIログは最大2500行です。登録した入力・出力・モデルのフルパスと
一般的な絶対パス表現をログでマスクします。共有前に、独自のメタデータ等が残っていないか確認してください。
設定ファイルは動作に必要な実パスを保持するため、ログとは扱いが異なります。

完成動画の隣に`.report.json`を保存し、入力メタデータ、設定、モデルID、GPU、FFmpeg版、
生成フレーム数、警告、処理時間、RIFEのpair準備/転送/推論/OOMカウンターを記録します。入力・出力のフルパスは含めません。

出力先と同じボリュームの専用一時フォルダーにSQLite索引と中間動画を置き、正常終了・処理エラー・
通常のキャンセルで削除します。ディスクが512MBの安全余裕を下回ると処理を停止します。
強制終了・停電時は一時フォルダーと`.acvfi-lock`が残る場合があります。
他の処理が動いていないことを確認し、該当ジョブの残骸だけを削除してください。
アプリは未完成の動画を完成名として公開せず、既存ファイルを上書きしません。

## テスト

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q -m "not rife"
```

実モデルテストを含める場合：

```powershell
$env:RIFE_MODEL_DIR = (Resolve-Path external\Practical-RIFE\train_log).Path
$env:RIFE_REPO_DIR = (Resolve-Path external\Practical-RIFE).Path
.\.venv\Scripts\python.exe -m pytest -q
```

モデル未指定時の実モデルテストはskipになります。通常の結合テストはテスト専用の
決定的エンジンを使い、FFmpegは実行します。このエンジンをGUIでAIとして提供することはありません。
テスト動画はすべて人工生成し、アニメ・映画等の著作権物をリポジトリへ入れていません。
Windows/Linux向けCI定義も同梱していますが、リモートCIはこの開発中には実行していません。

## ディレクトリ構成

| ディレクトリ | 責務 |
|---|---|
| `src/animecinemavfi/app/` | GUI/CLIエントリー |
| `src/animecinemavfi/ui/` | MainWindow、QThread、GUIログ |
| `src/animecinemavfi/core/` | JobManager、PairRenderer、JobControl、設定、GPU検出・診断、拡張契約 |
| `src/animecinemavfi/video/` | VideoFrame/FrameFormat、OutputFPS、Probe、FFmpeg、PTS索引、Reader |
| `src/animecinemavfi/interpolation/` | EngineCapabilities、VFI契約、RIFE、TensorPairCache、厳密なモデルローダー |
| `src/animecinemavfi/analysis/` | SceneDetector |
| `src/animecinemavfi/encoding/` | Encoder、Backend/Capabilities、OutputValidator、AudioMuxer |
| `src/animecinemavfi/color/` | ColorMetadata、ColorEncodingOptions、エンコーダー別VUI Policy |
| `src/animecinemavfi/models/` | Model Registry、公式モデルのカタログ |
| `src/animecinemavfi/utils/` | 外部プロセス、ログ、一時領域・出力管理 |
| `tests/` | 単体、実FFmpeg結合、GUI、実RIFEテスト |
| `scripts/` | 公式RIFE準備、GUI起動、CUDA benchmark、Windows検証 |
| `docs/` | 設計、検証結果、v0.2への引き継ぎ |

使用ライブラリはPython標準ライブラリ、NumPy、PySide6、PyTorch、torchvisionです。
FFmpeg/FFprobeとPractical-RIFEは外部依存です。pytest、ruff、mypyは開発時に使用します。

設計詳細は[ARCHITECTURE.md](docs/ARCHITECTURE.md)、制約と次の作業は
[DEVELOPMENT_REPORT.md](docs/DEVELOPMENT_REPORT.md)、ライセンスは
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)を参照してください。

## ロードマップ

| バージョン | 予定 |
|---|---|
| v0.2 | Anime / Cinema Motion Director |
| v0.3 | Multi VFI Engine |
| v0.4 | Artifact Inspector |
| v0.5 | Semantic / Object-Aware Interpolation |
| v0.6 | Ultra Quality |
| v0.7 | HDR / Color Engine |
| v1.0 | AI Auto |

原画タイミング、コマ打ち、止め、溜め、スミア、モーションブラー、作画意図と映画の24fpsの重量感を
維持し、不快なジャダーや不足する時間情報だけを補うことが目標です。v0.1.1はその基盤整備です。
