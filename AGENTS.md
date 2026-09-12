# AnimeCinemaVFI 開発ルール

## 目的と変更範囲

このリポジトリはWindows 11向け映像補間アプリのソースコードです。依頼された範囲を実装し、既存機能とテストを維持してください。バージョン更新やロードマップ機能の追加は、その作業の目的に含まれる場合に行います。

- Original Motion Preservationを維持します。高fpsだけを画質向上の根拠にしません。
- GUI、ジョブ制御、映像入出力、色管理、補間エンジンの責務を分離します。
- `VideoFrame` / `FrameFormat`と有理数によるPTS・fps計算を維持します。
- カットを跨ぐ補間を禁止し、元PTSと出力格子が一致するフレームを不要に補間しません。
- SDRの色タグ・range・SAR・bit depth検証、未対応HDR入力の明示的な拒否を維持します。
- 公式モデルの出典、固定commit、ライセンス、登録時のハッシュ記録と実行時の検査を尊重します。未確認のモデルコードを自動実行しません。
- テスト用エンジンを製品のAI補間として提供しません。OOM回復と画質への影響を区別し、CPU・模擬テストからGPUの高速化率を断定しません。
- キャンセル・失敗時にも子プロセス、パイプ、SQLite cursor、generatorを明示的に閉じ、一時領域を削除する前に解放します。
- 既存出力の保護、完成後の検証、音声・字幕保持の契約を維持します。UTF-8のJSON・文書は文字コードを明示して読み書きします。

## 主な配置

| 場所 | 責務 |
|---|---|
| `src/animecinemavfi/app/`, `ui/` | CLI、GUI、UIワーカー |
| `src/animecinemavfi/core/` | JobManager、PairRenderer、制御、設定、GPU診断 |
| `src/animecinemavfi/video/` | フレーム抽象化、FFmpeg、PTS索引、読み取り |
| `src/animecinemavfi/color/`, `encoding/` | 色管理、エンコード、音声mux、出力検証 |
| `src/animecinemavfi/interpolation/`, `models/` | 補間契約、RIFE、モデル登録・検査 |
| `tests/`, `scripts/`, `docs/` | 回帰テスト、検証ツール、設計・実機検証手順 |

## 環境と検証

Windows + Practical-RIFEの基準は64bit Python 3.11です。依存関係は`requirements-core.txt`と`pyproject.toml`に従い、仮想環境で導入します。FFmpegとFFprobeが必要です。LinuxのGUIテストにはQtのランタイム依存が必要で、CIの導入手順を参照してください。

```sh
python -m pip install -r requirements-core.txt -e ".[dev]"
python -m pip install "torch>=2.6,<3" "torchvision>=0.21,<1" --index-url https://download.pytorch.org/whl/cpu
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m mypy src
python -m pytest -q -m "not rife"
```

- ヘッドレスのGUIテストでは`QT_QPA_PLATFORM=offscreen`を設定します。
- 不具合修正では原因を再現する回帰テストを確認し、関連テストと上記の標準ゲートで検証します。通過させる目的で既存の検査を削除・弱体化しません。
- 通常CIはWindows/LinuxのCPU検証です。実モデル・CUDA・NVENCの検証は`docs/WINDOWS_VALIDATION.md`と対応する手動ワークフローに従い、必要なモデル・実機で行います。
- skipした理由と未測定の範囲を報告します。GitHubのWindowsランナーで通ったことを、Windows 11実機やGPU性能の検証済みと表現しません。
- テスト素材は人工生成データを使います。実動画、モデル重み、個人の設定・パス、認証情報をコミットしません。

## 記録と配布ファイル

`verification/`はソース配布時の検証記録です。今回の結果として流用せず、新しい実行結果はCIのActionsログ・artifact、または作業用の出力先で確認します。機能や手順を変えた場合は対応するREADME・設計文書を更新してください。

配布対象を変更・追加・削除した場合は`MANIFEST.sha256`を更新します。Git管理する配布ファイルをパス順に並べ、各ファイルの実バイト列のSHA256を記録してください。manifest自身と生成物・キャッシュは含めず、新規ファイルの追加漏れにも注意します。
