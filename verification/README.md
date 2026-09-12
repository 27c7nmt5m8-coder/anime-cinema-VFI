# v0.1.1 検証資料

- `tests-python311.xml` / `.txt`: 全テスト。ハードウェア不足の4 skipを含む。
- `ruff-check.txt` / `ruff-format.txt` / `mypy.txt`: 静的検査。
- `tested-environment.json`: 実行したOS/Python/ライブラリ/FFmpeg版。
- `diagnostics.json`: 実エンコードとSPS/VUI検査。NVENC利用不可の理由も記録。
- `gui-source-x5.png`: Linux offscreen GUIで入力読込後。Windowsの画面ではない。
- `source-24000_1001.mp4`: FFmpegで人工生成した128×72・5.005秒・AAC素材。
- `rife-4.25-source-x5-preview.mp4`: 公式モデルCPUによる5秒Preview、Source ×5、600フレーム。
- 同名の`.original.mp4`: 同じ時刻に元フレームを保持・再圧縮した比較参照。
- `.report.json` / `demo-media-probe.json`: ジョブ記録と独立したFFprobe照合。
- `benchmark-unavailable.txt`: CUDAなしの診断。GPU速度の測定結果ではない。

実在のアニメ・映画や音楽はテスト素材に含まない。映像・音声は全て人工生成。
Sourceの元PTSと出力格子が一致した画素はVFIを通らないが、色変換・再圧縮は非可逆。
