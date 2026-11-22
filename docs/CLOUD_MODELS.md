# Облачные модели

Подключение содержит адрес сервиса и ключ. В **Настройки → Модели и разум**
можно назначить разные модели для разговора, сложных задач и зрения.
Для зрения отправляются текущий вопрос и запрошенный снимок.

## Alibaba Model Studio

Выберите **Alibaba Model Studio** в списке провайдеров. По умолчанию
подставляется OpenAI-совместимый endpoint Сингапура. Если ключ из другого
региона или рабочей области, возьмите Base URL из той же панели Alibaba.
Для совместимого вызова Qwen используйте путь `/compatible-mode/v1`.
[Адреса Model Studio](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/singapore-regional-access-information)

## Озвучка

В **Настройки → Голос и слух** выберите **Облачная озвучка**, затем
сохранённое подключение, API озвучки, ID модели и ID голоса.

- **OpenAI-compatible** ожидает `/audio/speech` с ответом WAV.
- **Alibaba Qwen Audio** использует отдельный API. В сохранённом
  подключении нужен адрес вашей рабочей области Alibaba в Сингапуре
  или Пекине. Возьмите ID модели и русского или многоязычного голоса из
  каталога вашей области. [API Qwen Audio](https://www.alibabacloud.com/help/en/model-studio/qwen-audio-tts-http-api)

Примените настройки и нажмите **Прослушать**. Сервис получает текст
озвучки. При сетевой ошибке используется установленный локальный голос.

## Создание изображений

В **Настройки → Модели и разум → Создание изображений** назначьте
подключение и модель с поддержкой `/images/generations`. Эта настройка
использует OpenAI-совместимый API с результатом PNG в `b64_json`.
Для Alibaba укажите OpenAI-совместимый адрес рабочей области и модель
`qwen-image-3.0` или `qwen-image-3.0-pro` с доступом к выдаче Base64.
[API изображений Alibaba](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen-image-generation-and-editing-api-reference)
Примените настройки и отправьте описание. Изображение сохраняется
локально в `data/generated` и показывается в приложении.
После настройки можно также сказать «Нарисуй город в тумане».
[API генерации изображений](https://developers.openai.com/api/reference/typescript/resources/images)
