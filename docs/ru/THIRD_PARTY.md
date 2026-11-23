# Сторонние компоненты

[English](../../THIRD_PARTY.md) · **Русский** · [日本語](../ja/THIRD_PARTY.md) · [简体中文](../zh-CN/THIRD_PARTY.md)

- Движения Quaternius и Mesh2Motion: CC0. Источники и контрольные суммы:
  `app/public/animations/NOTICE.md`.
- Tauri, Svelte, Three.js, @pixiv/three-vrm, Lucide: версии зафиксированы в
  Cargo.lock и package-lock.json; условия находятся в соответствующих пакетах.
- Нативный ресемплер реализует полифазный FIR с окном Kaiser. Проверка
  эквивалентности использует SciPy как эталон; код SciPy в библиотеку не включён.
- Модели GigaAM, vosk, Piper, Qwen, Ollama имеют собственные условия. Веса и
  личные клоны голосов не входят в публичный снимок исходников.
- Android использует [LiteRT-LM 0.19.1](https://github.com/google-ai-edge/LiteRT-LM/tree/v0.19.1),
  [Vosk Android 0.3.75](https://github.com/alphacep/vosk-api) и
  [JNA 5.18.1](https://github.com/java-native-access/jna/tree/5.18.1).
  Vosk и LiteRT-LM распространяются под Apache 2.0. JNA доступна под
  Apache 2.0 или LGPL 2.1. Загружаемые [Qwen3 0.6B](https://huggingface.co/litert-community/Qwen3-0.6B-int4)
  и [русский пакет Vosk](https://alphacephei.com/vosk/models) используют Apache 2.0.
- Пользовательские VRM, аксессуары и голоса не становятся ресурсами,
  разрешёнными для распространения вместе с приложением автоматически.
- Русские названия стран в справочнике погоды взяты из [Unicode CLDR](https://github.com/unicode-org/cldr-json)
  ([Unicode License v3](https://www.unicode.org/license.txt)). Столицы и английские
  названия взяты из [GeoNames countryInfo](https://download.geonames.org/export/dump/countryInfo.txt)
  ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). Справочник объединяет
  данные по коду страны и опускает строки без столицы.

- Функции выбора оружия и рыбалки адаптированы из Mindcraft и раннего форка
  MinePal. Уведомления MIT находятся в `minecraft/MINDCRAFT-LICENSE` и
  `minecraft/MINEPAL-LICENSE`.
- На снимке панели «Персонаж» показана модель Юки на основе
  VRM1_Constraint_Twist_Sample © 2022 pixiv Inc. Её портрет использован
  как референс для обложки README. Условия заданы в
  метаданных модели и [VRM Public License 1.0](https://vrm.dev/licenses/1.0/).
- Портрет Пиппы — рендер общедоступной модели **Pippa** © loulou_yurika
  (ねこのゆりか). Портрет использован для обложки README; 3D-файл доступен у автора.
  [Модель и условия автора](https://booth.pm/ja/items/4613310).
- Портрет Кьют — рендер **Cute Model** © Jessair. [Модель и условия автора](https://booth.pm/ja/items/7100270).
- Портрет Цукуёми — рендер **Tsukuyomi-chan, тип A** © Rei Yumesaki. Это
  общедоступный персонаж, реплики Shelter не относятся к официальному проекту.
  [Модель и условия автора](https://tyc.rei-yumesaki.net/material/avatar/3d-a/).
- 3D-облик Мандзю (`personas/manju/appearance.vrm`) — **MeowManju** © MinaraiNyanko.
  Рендер Мандзю использован для обложки README.
  Автор разрешает модификацию, повторное распространение и коммерческое использование,
  кроме использования в политических целях. [Условия на странице автора](https://booth.pm/ko/items/6405885).

Собственный код Shelter распространяется по [MIT](../../LICENSE).
