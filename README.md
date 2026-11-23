# Shelter

**English** · [Русский](docs/ru/README.md) · [日本語](docs/ja/README.md) · [简体中文](docs/zh-CN/README.md)

![Shelter with its desktop interface, Pippa, Yuki, Jarvis, and Manju](docs/media/shelter-cover-characters.webp)

<p align="center">
  <a href="https://github.com/IT-Shelter-Labs/shelter/releases/download/v0.1.0-alpha.6/Shelter-0.1.0-alpha.6-windows-x64-setup.exe"><img src="docs/media/download-windows.png" width="190" height="58" alt="Download Windows 10/11 x64"></a>
  <a href="https://github.com/IT-Shelter-Labs/shelter/releases/download/v0.1.0-alpha.6/Shelter-0.1.0-alpha.6-linux-x86_64.tar.gz"><img src="docs/media/download-linux.png" width="190" height="58" alt="Download Linux x86_64"></a>
  <a href="https://github.com/IT-Shelter-Labs/shelter/releases/download/v0.1.0-alpha.7/Shelter-0.1.0-alpha.7-android-test.apk"><img src="docs/media/download-android.png" width="190" height="58" alt="Download Shelter for Android"></a>
</p>

[Game mods ZIP](https://github.com/IT-Shelter-Labs/shelter/releases/download/v0.1.0-alpha.3/Shelter-0.1.0-alpha.3-game-mods.zip) · [Jarvis v4 voice weights](https://github.com/IT-Shelter-Labs/shelter/releases/download/v0.1.0-alpha.5/Shelter-Jarvis-voice-v4.safetensors) · [All releases](https://github.com/IT-Shelter-Labs/shelter/releases)

Shelter is an open-source voice assistant for Windows, Linux, and Android. Open apps, control music, set reminders, run workflows, or chat with a local or cloud model. On desktop, say the active character’s wake word in Russian or click **Speak**.

[Documentation](docs/README.md) · [IT Shelter on Telegram](https://t.me/+tqB8b6h4JbYwZWVi) · [Support the project](https://t.me/itshelter_bot?start=donate)

## Install

| Platform | Package | First launch |
| --- | --- | --- |
| **Windows 10/11 x64** | `Shelter-<version>-windows-x64-setup.exe` | Run the installer and follow the setup wizard to download speech components. |
| **Linux x86_64** | `Shelter-<version>-linux-x86_64.tar.gz` | Extract the archive and run `python3 tools/install_linux.py --light-recognition`. Linux support is experimental. |
| **Android 8+** | **Shelter** APK | Choose cloud chat or PC connection. On compatible 64-bit devices with Android 12+, you can also download a model and chat offline. |

Preview APKs are signed with a debug key. Model weights are downloaded separately. See the [installation and Android sections](docs/GUIDE.md) for requirements and first-run steps.

## What Shelter can do

- **Voice and text.** Use Russian speech recognition on desktop through GigaAM or Vosk, listen to spoken replies, and stop an active request.
- **Desktop controls and workflows.** Open apps, control media and volume, edit text, and build workflows that run from a button, voice command, schedule, or event.
- **Models and projects.** Choose separate models for chat, complex tasks, screen understanding, speech, and image generation. Manage conversations, memory, and project materials in the app.
- **Games.** Connect a companion to a supported Minecraft Java Edition world, track crafting tasks in Factorio, or use campaign tools and screen analysis in Hearts of Iron IV.
- **Connections.** Pair your phone and configure integrations for smart home devices, OBS, Telegram, MCP, and extensions.

The app interface supports Russian and English. The Japanese and Chinese translations cover the documentation.

## Desktop interface and characters

![Shelter desktop home with voice input, workflows, and reminders](docs/media/shelter-desktop.webp)

The desktop app has ten character presets. **Jarvis** is selected on first launch. Pippa, Yuki, Akai, Vain, Manju, Tsukuyomi, Cute, Yamaneko, and Miku are also available. Presets change the wake word, voice, and personality. Your selection is saved across updates.

![Shelter character catalog with Jarvis first, followed by Pippa and Yuki](docs/media/shelter-personas.webp)

![More character cards and their avatar previews](docs/media/shelter-personas-more.webp)

The first screenshot shows a local installation with optional 3D appearances connected. Every desktop preset includes a catalog portrait or the Jarvis reactor.

Shelter includes 3D appearances for Yuki, Vain, Manju, and Tsukuyomi. To use Pippa’s original appearance, download the creator’s archive and attach it from her card. On a compatible NVIDIA GPU, the character voice setup downloads the trained Jarvis v4 profile and uses the bundled voice sample for Yuki and Pippa. See the [character guide](docs/GUIDE.md) and [asset credits](THIRD_PARTY.md).

## Build from source

On Windows, install Python 3.11, Node.js 22.12 or later, Rust, MSVC Build Tools, and WebView2. Run these commands from the repository root in PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.windows.txt
$env:Path = "$(Resolve-Path .\.venv\Scripts);$env:Path"
npm --prefix app ci
npm --prefix app run desktop:build
```

Run `app/src-tauri/target/release/Jarvis.exe`. The executable keeps its original filename for compatibility. To build the Windows installer, run `npm --prefix app run desktop:bundle`.

| Directory | Contents |
| --- | --- |
| `shelter_core/` | Python core for speech, models, actions, and integrations |
| `app/`, `native/`, `hud/` | Svelte and Tauri desktop app, native audio, and Windows HUD |
| `android/` | Kotlin app for both Android variants |
| `personas/` | Built-in presets and distributable artwork |
| `minecraft/`, `games/` | Game clients, adapters, and mods |
| `tests/`, `tools/`, `docs/` | Tests, build tools, and documentation |

[Build and test instructions](docs/GUIDE.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

## Data and license

Local speech recognition runs on the device. Features that use search, weather, or cloud models send the requests they need to the selected services. Personal model files, voice recordings, credentials, and project data stay out of public source exports. The deliberately bundled character samples are listed in the [asset credits](THIRD_PARTY.md).

The Shelter code is released under the [MIT license](LICENSE). Third-party components and artwork have their own terms. [Third-party notices](THIRD_PARTY.md)
