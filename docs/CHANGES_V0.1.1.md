# v0.1.1 変更ファイル一覧

基準: AnimeCinemaVFI_v0.1.0_Source.zip。実装・テストファイルの削除なし。
元の40 test関数（パラメーター展開後64ケース）を保持。新旧のテスト関数一覧を照合済み。

## 既存ファイルの更新

- `.github/workflows/ci.yml`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DEVELOPMENT_REPORT.md`
- `pyproject.toml`
- `src/animecinemavfi/__init__.py`
- `src/animecinemavfi/analysis/scene.py`
- `src/animecinemavfi/app/main.py`
- `src/animecinemavfi/color/metadata.py`
- `src/animecinemavfi/core/config.py`
- `src/animecinemavfi/core/extensions.py`
- `src/animecinemavfi/core/job.py`
- `src/animecinemavfi/encoding/audio.py`
- `src/animecinemavfi/encoding/encoder.py`
- `src/animecinemavfi/interpolation/base.py`
- `src/animecinemavfi/interpolation/rife.py`
- `src/animecinemavfi/interpolation/rife_worker.py`
- `src/animecinemavfi/models/catalog.json`
- `src/animecinemavfi/models/registry.py`
- `src/animecinemavfi/ui/window.py`
- `src/animecinemavfi/utils/process.py`
- `src/animecinemavfi/video/probe.py`
- `src/animecinemavfi/video/reader.py`
- `src/animecinemavfi/video/timeline.py`
- `tests/conftest.py`
- `tests/test_gui.py`
- `tests/test_rife_real.py`

## 追加

- `.github/workflows/ffmpeg-color.yml`
- `.github/workflows/windows-cuda.yml`
- `docs/CHANGES_V0.1.1.md`
- `docs/V0.1.1_DESIGN.md`
- `docs/WINDOWS_VALIDATION.md`
- `scripts/benchmark_rife.py`
- `scripts/verify_windows.ps1`
- `src/animecinemavfi/color/encoding.py`
- `src/animecinemavfi/core/diagnostics.py`
- `src/animecinemavfi/core/pair_renderer.py`
- `src/animecinemavfi/encoding/backends.py`
- `src/animecinemavfi/encoding/validation.py`
- `src/animecinemavfi/interpolation/capabilities.py`
- `src/animecinemavfi/interpolation/model_loader.py`
- `src/animecinemavfi/interpolation/worker_runtime.py`
- `src/animecinemavfi/utils/paths.py`
- `src/animecinemavfi/video/frame.py`
- `src/animecinemavfi/video/output_fps.py`
- `tests/test_color_encoding.py`
- `tests/test_frame_fps.py`
- `tests/test_hardware.py`
- `tests/test_rife_batch.py`
- `tests/test_v011_regression.py`
- `tests/test_worker_runtime.py`

## 検証成果物

`verification/`はv0.1.1の実行結果へ更新した。v0.1.0の実行結果を新しい版の結果として流用していない。
人工入力、RIFE出力・元タイミング参照、GUI画像、JUnit XML、診断、静的検査、環境記録を同梱する。
`MANIFEST.sha256`を新しい内容へ更新した。モデル・依存バイナリ・ユーザー設定・ログ原本は含めない。

## 主要な互換性

- Config schema 1の既存設定をfixed FPSとして読み込む。新しいfps_mode/source_multiplierを追加。
- 旧Model Registryにframe_capabilitiesがなくてもRGB8の安全な既定値で読み込む。
- 単一timestep APIを維持。Frameの公開値はVideoFrameへ変更したため、外部エンジンはdata/timestamp/formatへ追従する。
- 音声・字幕・添付、no overwrite、lock、workspace cleanup、Pause/Cancelの動作を維持する。
