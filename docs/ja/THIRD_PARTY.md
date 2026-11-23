# サードパーティのライセンスとクレジット

[English](../../THIRD_PARTY.md) · [Русский](../ru/THIRD_PARTY.md) · **日本語** · [简体中文](../zh-CN/THIRD_PARTY.md)

- Quaternius と Mesh2Motion のアニメーションは CC0 で配布されています。出典とチェックサムは[アニメーションのクレジット](../../app/public/animations/NOTICE.md)に記載されています。
- Tauri、Svelte、Three.js、@pixiv/three-vrm、Lucide のバージョンは Cargo.lock と package-lock.json で固定しています。ライセンスは各パッケージで確認できます。
- ネイティブのリサンプラーは Kaiser 窓を用いたポリフェーズ FIR フィルターです。テストでは SciPy と比較します。ライブラリに SciPy のコードは含まれません。
- GigaAM、Vosk、Piper、Qwen、Ollama にはそれぞれ利用条件があります。公開用ソースのスナップショットにモデルの重みや個人のクローン音声は含まれません。
- Android 版は [LiteRT-LM 0.19.1](https://github.com/google-ai-edge/LiteRT-LM/tree/v0.19.1)、[Vosk Android 0.3.75](https://github.com/alphacep/vosk-api)、[JNA 5.18.1](https://github.com/java-native-access/jna/tree/5.18.1) を使用します。Vosk と LiteRT-LM は Apache 2.0、JNA は Apache 2.0 または LGPL 2.1 です。アプリから取得できる [Qwen3 0.6B](https://huggingface.co/litert-community/Qwen3-0.6B-int4) と [Vosk ロシア語パック](https://alphacephei.com/vosk/models)には Apache 2.0 が適用されます。
- インポートした VRM、アクセサリー、音声サンプルを共有する前に、再配布の条件を確認してください。
- ロシア語の国名は [Unicode CLDR](https://github.com/unicode-org/cldr-json)（[Unicode License v3](https://www.unicode.org/license.txt)）、首都と英語名は [GeoNames countryInfo](https://download.geonames.org/export/dump/countryInfo.txt)（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)）が出典です。天気のデータでは国コードで統合し、首都のない項目を除いています。
- 武器の選択と釣りの処理は Mindcraft と初期の MinePal フォークをもとにしています。[Mindcraft の MIT ライセンス](../../minecraft/MINDCRAFT-LICENSE) · [MinePal の MIT ライセンス](../../minecraft/MINEPAL-LICENSE)
- ユキのポートレートと README のカバーは **VRM1_Constraint_Twist_Sample** © 2022 pixiv Inc. を参照しています。モデル内のメタデータと [VRM Public License 1.0](https://vrm.dev/licenses/1.0/) が適用されます。
- ピッパのポートレートと README のカバーは、一般配布されている **Pippa** © loulou_yurika（ねこのゆりか）を参照しています。3D ファイルは作者が配布しています。[モデルと利用条件](https://booth.pm/ja/items/4613310)
- キュートのポートレートには **Cute Model** © Jessair を使用しています。[モデルと利用条件](https://booth.pm/ja/items/7100270)
- つくよみちゃんのポートレートには **つくよみちゃん公式3Dモデル タイプA** © 夢前黎を使用しています。Shelter が生成した発言は公式の発言とは別です。[モデルと利用条件](https://tyc.rei-yumesaki.net/material/avatar/3d-a/)
- マンジュの同梱 VRM と README のカバーは **まんじゅうにゃんこ（MeowManju）** © 見習いにゃんこを使用・参照しています。作者は改変、再配布、商用利用を許可しています。政治利用は対象外です。[モデルと利用条件](https://booth.pm/ko/items/6405885)

Shelter のコードは [MIT ライセンス](../../LICENSE)で公開されています。
