# Windows / CUDA / NVENC 実機検証

v0.1.1のこの開発環境はLinux・CPUです。以下は検証手順で、実機合格の記録ではありません。
正式なWindows+RIFE推奨環境は **Windows 11 / CPython 3.11 64bit**。

## 自動確認

READMEに従いFFmpeg、PySide6、CUDA PyTorch、公式Practical-RIFE 4.25を導入する。

```powershell
.\scripts\verify_windows.ps1 -ModelDir .\external\Practical-RIFE\train_log -RepositoryDir .\external\Practical-RIFE -RequireCuda
```

`ACVFI_REQUIRE_CUDA=1`ではCUDA環境・モデルが欠けていると失敗する。GPU用テストを
環境未整備のままskipして実機検証成功とすることを防ぐ。
結果は時刻付き`test-artifacts`にJUnit XMLと診断JSONとして保存する。

```powershell
.\.venv\Scripts\python.exe -m animecinemavfi diagnose --encoders --output diagnostics.json
.\.venv\Scripts\python.exe scripts\benchmark_rife.py --pairs 50 --output benchmark.json
```

NVENC診断は一覧表示だけでなくH.264/HEVCそれぞれ3フレームを実エンコードし、
コンテナと取り出したSPS/VUIのBT.709・limited・SAR・8bitを検査する。
ベンチマークは同じ実モデル・同じ入力・scaleで旧転送方式と新方式を交互に計測する。
診断・ベンチマークの既存出力は上書きしない。

## 実機チェックリスト

各行に実施日、OS/build、Python/PySide/PyTorch、CUDA/driver、GPU/VRAM、FFmpeg版と結果を記入。

| 項目 | 合格条件 | 今回の状況 |
|---|---|---|
| Windows 11 GUI起動 | 表示崩れ・Qt警告・終了時のthread破棄エラーがない | 未検証 |
| Drag & Drop / ファイル選択 | 日本語・空白名を読み込み、入力情報が一致 | 未検証 |
| Source ×2 / ×5 | 24000/1001 ×5が120000/1001、固定120と区別される | 実機未検証 |
| Start / Pause / Resume | 処理境界で停止し、再開後フレーム数と音声が一致 | 実機未検証 |
| Cancel / Pause中Cancel / ウィンドウ終了 | worker/FFmpegが終了し、完成名で未完成物を公開しない | 実機未検証 |
| 日本語・空白・280文字超パス | MP4入出力、mux、cleanupが完了 | Windows専用テスト追加、未実行 |
| UNC / ネットワークドライブ | 読み込み、出力lock、no overwriteを確認 | 未検証 |
| H.264 NVENC / HEVC NVENC | 診断と実モデル動画が成功、色・SAR・8bitを保持 | 未検証 |
| GPUメモリ | 同一pair 200回/800推論とpair交換50回でallocatedが増え続けない | CUDA専用テスト追加、未実行 |
| 4K / 低VRAM | scale 1→0.5→0.25、実OOM後再試行、Cancelで解放 | 未検証 |
| 長尺23.976fps | 開始・中間・終端のA/V同期、ディスク不足、複数音声・字幕・添付 | 未検証 |
| HDR/10bit入力 | 明示エラーで止まりSDRへ無断変換しない | 実機未検証 |

GPUメモリテストは小解像度で反復寿命を確認するもの。4K実機耐久試験の代用にはしない。
FFmpegビルドによって長いパス・NVENC・コーデックの可否が異なる。失敗した環境は
ドライバー/FFmpegを記録して原因を解決し、テストをskipへ変更して隠さない。

## CI

- `ci.yml`: Windows/Linux、Python 3.11、CPU torch、GUI・FFmpeg・パス回帰。
- `ffmpeg-color.yml`: 手動起動、FFmpeg 6.1.6 / 7.1.5 / 8.1.2を公式ソースからビルドし色回帰。
- `windows-cuda.yml`: 手動起動、利用者が用意したWindows/CUDA runnerと公式モデルで実機テスト。

これらのCI定義は本開発中にGitHub上で実行していない。FFmpeg 9の検証は未実施で、
公式リリースと入手可能なビルドを確認してからmatrixへ追加する。
