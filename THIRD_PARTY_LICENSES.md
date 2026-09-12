# 第三者ライセンスの整理

確認日: 2026-09-09。これは配布物の整理であり、製品一式の商用配布を承認する文書ではありません。
このリポジトリで新規作成したアプリコードのMITライセンスと、外部コード・モデル・バイナリの
ライセンスは別です。完成品としての商用配布が確認済みとは表明しません。

| 対象 | 確認内容 | v0.1の扱い |
|---|---|---|
| AnimeCinemaVFI新規コード | 本リポジトリのMIT | ソースを同梱 |
| Practical-RIFEコード | 公式リポジトリのMIT | 外部取得・別プロセスで利用。コード本体は非同梱 |
| 公式RIFE 4.25重み | 公式READMEがリンク先の内容にもMITが適用されると明記 | 個別に取得。モデル名・版・出典・ローカルハッシュを登録 |
| PyTorch | 本体のBSD系ライセンスと、配布物に含まれる複数の第三者ライセンス | ユーザー環境へpipで導入。CUDA関連も別途確認 |
| torchvision | BSD 3-Clause。内包物にも注意 | 公式RIFEの補助コードからのimportに必要 |
| NumPy | BSD 3-Clauseと同梱された依存物の告知 | pipで導入 |
| PySide6 / Qt for Python | LGPLv3/GPLv3/商用ライセンスの条件、モジュールと内包物による相違 | QtCore/QtGui/QtWidgetsを使用。バイナリ配布時に利用モジュールとwheel内容を再確認 |
| FFmpeg | 基本LGPL 2.1+。有効化した構成によりGPL/nonfree等が関係 | 実行ファイル非同梱。利用ビルドのconfigure/licenseを確認 |
| libx264 / libx265 | FFmpegビルドのGPL構成に関わる。コーデック特許の論点は別 | ユーザーのFFmpegに含まれる場合のみ使用 |
| NVIDIA NVENC/CUDA | NVIDIA関連コンポーネント・ドライバーの条件を別途確認 | 再配布せずユーザー環境を利用 |
| GMFSS Fortuna | 公式リポジトリのコードはMIT表記 | 未導入。採用する重みの個別条件・派生元・依存物はv0.3前に確認 |
| その他GMFSS・将来モデル・Anime-RIFE | 未採用・未確認 | アプリのライセンスから利用許諾を推定しない |
| libplacebo / 将来HDR処理 | v0.1では未採用 | v0.7で品質・ライセンス・Windows対応・保守性を評価 |

主な一次資料：

- [Practical-RIFE READMEとモデル案内](https://github.com/hzwer/Practical-RIFE)
- [Practical-RIFE LICENSE](https://github.com/hzwer/Practical-RIFE/blob/main/LICENSE)
- [PyTorch LICENSE](https://github.com/pytorch/pytorch/blob/main/LICENSE)
- [torchvision LICENSE](https://github.com/pytorch/vision/blob/main/LICENSE)
- [NumPyライセンス](https://numpy.org/doc/stable/license.html)
- [Qt for Pythonのライセンス一覧](https://doc.qt.io/qtforpython-6/licenses.html)
- [Qtのオープンソースライセンス案内](https://www.qt.io/development/download-open-source)
- [FFmpeg License and Legal Considerations](https://ffmpeg.org/legal.html)
- [GMFSS Fortuna LICENSE](https://github.com/98mxr/GMFSS_Fortuna/blob/main/LICENSE)

配布用EXEを作る前に、実際に含めるDLL、FFmpegビルド、Qtモジュール、PyTorch/CUDA配布物、
モデルコードと重みそれぞれについて、ライセンス本文、著作権表示、ソース提供等の条件を確認します。
「別プロセスだから」「モデルがMITだから」という理由だけで製品全体の配布条件を結論づけません。

開発用依存（pytest、ruff、mypy）はアプリの実行に必須ではありません。
モデルの登録時SHA256は取得後の変更を検出するための情報であり、第三者による配布元認証ではありません。
