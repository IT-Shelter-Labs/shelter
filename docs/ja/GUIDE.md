# Shelter 利用・開発ガイド

[English](../GUIDE.md) · [Русский](../ru/GUIDE.md) · **日本語** · [简体中文](../zh-CN/GUIDE.md) · [プロジェクト概要](README.md)

画面上の項目名は、英語表示で探せるように英語表記も記載しています。音声コマンドの例は、そのまま使えるようにロシア語で記載しています。

## インストールと初回起動

**Windows。** [GitHub Releases](https://github.com/IT-Shelter-Labs/shelter/releases) から x64 インストーラーをダウンロードします。保存先を選び、初回設定の案内に従って音声認識と読み上げのコンポーネントを取得してください。呼びかけを有効にする前にマイクを選んでテストします。1 回だけ話すときは **Speak**、聞き取り・読み上げ・実行中の処理を中断するときは **Stop** を押します。初回の呼びかけ名は `Джарвис`（ジャーヴィス）です。キャラクターを選択済みの場合は、その設定を引き継ぎます。

**Linux。** x86_64 アーカイブは Ubuntu 24.04 向けにビルドされています。システムパッケージを入れ、リリースアーカイブを展開したディレクトリで実行します。

```bash
sudo apt install python3 python3-venv libportaudio2 libgtk-3-0t64 libwebkit2gtk-4.1-0 libayatana-appindicator3-1 librsvg2-2
python3 tools/install_linux.py --light-recognition
"${XDG_DATA_HOME:-$HOME/.local/share}/Shelter/shelter"
```

`--light-recognition` は GigaAM を追加せず、Vosk をセットアップします。新しいインストール先を指定するには `--directory` を使います。アーカイブにはデスクトップ実行ファイルとネイティブ音声ライブラリが含まれます。音量は `pactl`、メディア操作は `playerctl` を使います。Wayland ではウィンドウ操作、グローバルショートカット、選択範囲の取得がコンポジターの制約を受けます。まず **Speak** またはテキスト入力を使ってください。Ubuntu の WSL 環境でビルドと起動を確認済みです。実機のオーディオや各デスクトップ環境での動作は今後の検証対象です。

## 音声、キャラクター、ワークフロー

- **Settings → Voice and hearing** でマイク、音声認識、読み上げ音声を選びます。デスクトップの GigaAM と Vosk はロシア語を認識します。表示言語を変えても認識言語は変わりません。対応する音声拡張機能をインストール済みの場合は、ここで選択できます。
- **Character** でプリセットを選択できます。ピッパのオリジナルモデルを使うには、**3D model page** から `08_Pippa.zip` をダウンロードし、カードの **Attach 3D appearance** でそのアーカイブを選びます。以前の環境からモデルとローカルのジャーヴィスの声を取り込むには、**Restore from a previous installation** で以前の Shelter フォルダーを指定します。[ピッパの配布元と利用条件](https://booth.pm/ja/items/4613310) · [素材クレジット](THIRD_PARTY.md)
- 外部テクスチャを必要としないヒューマノイドの VRM 0.x/1.0 と、VRMA アニメーションを取り込めます。**Character** からインポートし、作者表記を残してください。ウィンドウの操作方法はプラットフォームによって異なります。キャラクターを常に表示するか、会話中だけ表示するかを選べます。
- **Commands → New scenario** で手順、条件、トリガーを追加します。定期実行を有効にする前に動作を確認してください。ボタン、音声、時刻、イベントで起動できます。対応する操作を最大 6 ステップまで一度の音声リクエストで指示できます。たとえば `Открой калькулятор, поставь громкость на тридцать, потом напомни через три минуты выпить воды` は、電卓の起動、音量を 30% に設定、3 分後のリマインダーを行います。成功した手順はタスクカードから保存できます。途中で止めても、完了した操作は適用されたままです。

## モデルと拡張機能の接続

1. **Settings → Models and reasoning** でローカル接続またはクラウド接続を追加します。エンドポイント、モデル ID、必要に応じて API キーを指定してください。同じ画面で会話、複雑なタスクと資料、画像認識に使うモデルを個別に割り当てられます。画像認識には画像を扱えるモデルが必要で、現在の質問と指定した画面キャプチャをモデルに送信します。Alibaba Model Studio の場合は同じリージョンとワークスペースの URL とキーを使います。OpenAI 互換パスは `/compatible-mode/v1` です。
2. **Settings → Voice and hearing** でクラウド読み上げを設定します。接続、API、モデル ID、音声 ID を選んで試聴してください。OpenAI 互換の `/audio/speech` は WAV 応答を想定しています。Alibaba Qwen Audio は専用 API を使います。クラウドでエラーが発生した場合は、インストール済みのローカル音声に切り替わります。
3. **Image generation** では対応するモデルを割り当てます。エンドポイントは `/images/generations` を提供し、`b64_json` で PNG を返す必要があります。生成した画像は `data/generated` に保存されます。クラウドの利用にはプロバイダーの条件と料金が適用されます。
4. **Connections** でスマートフォン、スマートホーム、OBS、Telegram、MCP を設定できます。**Extensions** では `.jarvis-plugin.zip` をインストールできます。有効化の前に、要求する権限を確認しましょう。拡張機能は別プロセスで実行されますが、現在のユーザーの権限が使われます。信頼できる配布元をご利用ください。操作、音声、イベント、ウィジェット、キャラクターのリアクションを追加できます。

## Android

1 つの Shelter アプリで、Android 8 以降のクラウドモードと PC モードを利用できます。端末内のモデルを使うには、対応する 64 ビット端末と Android 12 以降が必要です。初回起動時にモードを選び、設定から変更できます。従来のリリースでは Companion と Local の 2 つの APK がありました。

- **Cloud（クラウド）。** プロバイダーまたは OpenAI 互換エンドポイントを選び、モデル ID とキーを入力します。端末の読み上げ音声は **Voice and microphone** で選べます。リクエストはサービスに送られ、会話は端末に保存されます。
- **My computer（自分の PC）。** デスクトップ版の **Connections → Phone** で自宅ネットワークからの接続を許可し、通常はポート `8765` のアドレスを確認します。スマートフォンにアドレスを入力し、PC の画面に表示されたコードでペアリングします。自宅ネットワークで HTTP を使う場合は LAN 利用を明示的に許可します。外出先からの接続には有効な証明書付きの HTTPS が必要です。PC の音声を有効にすると端末で再生でき、**Stop** で PC 側の処理を中止できます。アクセスの取り消しはデスクトップ版で行います。
- **On device（端末上）。** **Settings → On device** で Qwen3 0.6B（約 347 MB）をダウンロードします。端末のアーキテクチャ、メモリ、空き容量とモデルのファイルが確認されます。ダウンロードは中止できます。互換性のある `.litertlm` ファイルの手動インポートにも対応しています。アプリから取得できるモデルは短いリクエスト向けです。
- **バックグラウンドマイク。** **Voice and microphone** でロシア語の Vosk パックをダウンロードします。アプリを開いた状態で待ち受けを開始し、必要な権限を許可してください。`Слушай, помощник` と呼びかけ、合図の後に依頼を話します。アプリまたは常時表示の通知から待ち受けを停止できます。セッションは最長 30 分で、再起動した場合は手動で開始します。モデルのダウンロードとバックグラウンド操作はエミュレーターで確認しています。実機でのマイク動作と電池消費は未検証です。

## ゲーム

| ゲーム | 接続方法 | 操作と対応バージョン |
| --- | --- | --- |
| **Minecraft Java Edition** | **Games → Minecraft** で別アカウントを使う接続方式を選びます。Node.js 22 以降と、Java Edition を利用できる別の Microsoft アカウントが必要です。プレイヤー名とサーバーアドレスを設定し、必要に応じて仲間を許可リストに追加します。 | `!jarvis координаты`（座標）、`!jarvis иди за мной`（ついてくる）、`!jarvis стоп`（停止）を使用できます。Paper 1.21.5 ではインベントリ用プラグインを使い、仲間の近くで `!inv` を入力できます。別アカウントを用意せずに使えるアダプターには Paper 1.21.11 と Fabric/Carpet 1.21.11 があります。NeoForge 1.21.1 用の独立 Mod では `/companion summon` と `!inv` を利用できます。ワールドのバージョンに合ったものを選んでください。 |
| **Factorio 2.0 / 2.1** | **Games → Factorio** でバージョン 0.3.0 の Mod を作成します。Shelter から操作するには、ローカル RCON を有効にしたサーバーで `/shelter-remote` を実行します。 | 材料の確認、クラフトの開始・進捗確認・停止、研究予約、設計図の配置、組立機へのレシピ設定ができます。Factorio AI Companion を別途接続すると、採掘や追従を行うキャラクターを追加できます。 |
| **Hearts of Iron IV** | HOI4 Live Tools をローカル MCP サーバー `hoi4-live` として追加します。備蓄目標用の **Shelter Campaign Tasks** は別途利用できます。 | 戦況概要、生産、研究、国家方針、期限付きの時間進行と停止を操作できます。ツールの検出は確認済みです。キャンペーン内の動作は実機での確認が必要です。 |

ゲーム連携では、対象のクライアントや Mod の権限とゲーム内の状態を使います。Minecraft の Mod レシピは選択したアダプターのレジストリに依存します。[ゲームの詳細（ロシア語）](../GAMES.md) · [Minecraft のセットアップとコマンド（ロシア語）](../MINECRAFT.md)

## 開発、テスト、配布

Windows のビルド手順は [README](README.md) にあります。Ubuntu 24.04 では、ルートから `bash tools/setup_linux.sh` を実行して依存関係と `.venv-linux` を用意します。デスクトップ版のビルドには Node.js 22.12 以降、Rust、Tauri 用の GTK/WebKitGTK 開発パッケージが必要です。プロジェクトの Python に `PATH` を通し、`npm --prefix app ci` と `npm --prefix app run desktop:build` を実行します。

プロジェクトの Python 環境を使い、リポジトリのルートでテストします。

```sh
python tools/build_native.py
python -X utf8 -m unittest discover -s tests
npm --prefix app run check
npm --prefix app run test:avatar
npm --prefix app run test:navigation
npm --prefix app run test:i18n
npm --prefix app run build
cargo test --locked --manifest-path app/src-tauri/Cargo.toml --lib
```

Android には JDK 21、SDK Platform 35、Build Tools 36.0.0 が必要です。Windows では `android/` で次を実行します。

```powershell
.\gradlew.bat --no-daemon :app:assembleDebug :app:testDebugUnitTest
```

Linux では同じ引数で `./gradlew` を実行します。`python tools/export_public.py release/github-source` で公開用スナップショットを新しいディレクトリに作成します。翻訳済みの文書を含み、個人データや作業用の Git 履歴は含みません。スナップショットから配布物をビルドし、公開前にチェックサムを確認します。[配布パッケージ作成の詳細（ロシア語）](../PUBLIC_RELEASE.md) · [開発への参加](CONTRIBUTING.md)

## データ、セキュリティ、ライセンス

公開 Issue にトークン、音声サンプル、個人メモリ、ログ全文を添付しないでください。脆弱性は、利用可能であればリポジトリの非公開窓口から報告できます。デスクトップのローカル API はトークンを、スマートフォンはペアリングを要求します。スマートフォンからは対応する接続機能を使ってください。

Shelter のコードには [MIT ライセンス](../../LICENSE)が適用されます。ダウンロードするモデル、ポートレート、VRM 素材、依存ライブラリにはそれぞれの条件が適用されます。[素材の出典とクレジット](THIRD_PARTY.md)
