# Contributing to Shelter

**English** · [Русский](docs/ru/CONTRIBUTING.md) · [日本語](docs/ja/CONTRIBUTING.md) · [简体中文](docs/zh-CN/CONTRIBUTING.md)

Work on a separate branch. Describe the problem, what changed, and how you tested it. For a bug report, include the OS, voice mode, model, reproduction steps, and a redacted log excerpt. [Build and test commands](docs/GUIDE.md)

Audio changes should preserve the sample rates, PCM format, cancellation, and time to first audio. Exercise both the native implementation and the fallback. Test UI changes in the native build as well as the browser development bridge. Keep model weights, credentials, personal memory, and voice samples out of commits.
