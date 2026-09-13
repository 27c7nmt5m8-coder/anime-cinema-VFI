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

## GitHub / Codex の標準開発フロー

GitHub の `main` を正本かつ安定版として扱います。Codex を含む自動修正では、ユーザーが明示的に別方式を指定しない限り、次の流れを標準とします。

1. 作業開始前に `main` の現行コード、`AGENTS.md`、関連設計文書、直近の変更を確認します。
2. 原則として `main` を直接変更せず、目的が分かる専用branchを作ります。例: `fix/v012-av-sync`、`feat/v020-motion-director`。
3. 変更範囲を必要最小限に限定し、ユーザーから明示されていない補間ロジック、色管理、A/V同期、モデル選択、出力互換性を勝手に変更しません。
4. 不具合修正では症状だけでなく根本原因を特定し、可能なら修正前に再現テストまたは回帰テストを追加します。Mock、fixture、CPU代替経路と実CUDA/RIFE実装の仕様差が原因なら、テスト側も実仕様に合わせます。
5. 既存テストを削除・弱体化せず、変更に対応するテストを追加して標準ゲートを実行します。
6. 変更差分を確認し、`VideoFrame` / `FrameFormat`、PTS、scene cut、色タグ/range/SAR/bit depth、音声・字幕保持、モデルハッシュ、OOM回復、リソース解放への副作用がないかレビューします。
7. 修正branchにコミットし、`main` 向けPull Requestを作ります。PR本文には変更理由、変更ファイル、追加テスト、検証結果、実機未測定項目を明記します。
8. CIとレビュー結果を確認します。CUDA/GPU、NVENC、VRAM、実動画A/V同期、画質・性能など実機依存項目は、実測前に「検証済み」と扱いません。
9. ランタイムに影響する変更は、必要なWindows 11/GPU実機確認が完了して問題がなければPRをマージします。問題があれば同じbranch/PRで最小限の修正を続けます。文書のみの変更など実機影響がない場合は、CIと差分レビューを基準にします。

ZIPやチャット添付ファイルが提供された場合も、GitHub版との対応関係を確認し、可能ならGitHubを正本として差分管理します。GitHubへ反映できない場合だけ一時的にZIPベースで作業し、その状態を明記します。

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

## 検証結果の区分

PRと完了報告では、少なくとも次を区別して記録します。実行していない項目は「未実測」とします。

- **機能回帰**: unit/integration/GUI/CLI、例外処理、キャンセル・cleanup。
- **画質・モーション回帰**: Original Motion Preservation、scene cut、HOLD/補間判定、元フレーム保持。
- **A/V同期**: PTS、duration、音声・字幕mux、長尺ドリフト。人工fixtureと実動画検証を区別します。
- **色管理**: SDRタグ、range、SAR、bit depth、FFmpeg入出力。必要に応じて実FFmpegで確認します。
- **RIFE整合性**: 固定commit、モデルハッシュ、loader/runtime整合、実モデル実行。
- **CUDA/GPU**: 対象GPU、driver、CUDA/PyTorch、実行可否。CPU/mock結果で代用しません。
- **性能/VRAM**: fps、frame time、VRAM peak、OOM発生条件、fallback回数。対象GPU実機でのみ性能値を確定します。
- **OOM時の品質**: fallbackがどの区間に影響したかを区別し、全体画質が同等だったと未測定で断定しません。
- **エンコード**: NVENC/CPU encoder、出力検証、A/V保持。実機依存backendは別に記録します。

GPUや実動画が使えない環境では、CPU/Mock/CIで確認できた範囲を明示したうえで、`GPU実測未実施`、`実動画A/V同期未実測`、`性能未実測`などを残してください。

## 記録と配布ファイル

`verification/`はソース配布時の検証記録です。今回の結果として流用せず、新しい実行結果はCIのActionsログ・artifact、または作業用の出力先で確認します。機能や手順を変えた場合は対応するREADME・設計文書を更新してください。

配布対象を変更・追加・削除した場合は`MANIFEST.sha256`を更新します。Git管理する配布ファイルをパス順に並べ、各ファイルの実バイト列のSHA256を記録してください。manifest自身と生成物・キャッシュは含めず、新規ファイルの追加漏れにも注意します。
