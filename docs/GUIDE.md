# Use and build Shelter

**English** · [Русский](ru/GUIDE.md) · [日本語](ja/GUIDE.md) · [简体中文](zh-CN/GUIDE.md) · [Project overview](../README.md)

## Install and start

**Windows.** Download the x64 installer from [GitHub Releases](https://github.com/IT-Shelter-Labs/shelter/releases). Run it, choose an installation folder, and follow the first-run wizard to install speech recognition and a voice. Select the microphone and test it before enabling wake-word detection. Use **Speak** for a single request and **Stop** to interrupt listening, playback, or work. The default desktop wake word is `Пиппа` (Pippa). A saved character selection takes precedence.

**Linux.** The x86_64 archive is built for Ubuntu 24.04. Install the system packages, then open a terminal in the extracted release folder.

```bash
sudo apt install python3 python3-venv libportaudio2 libgtk-3-0t64 libwebkit2gtk-4.1-0 libayatana-appindicator3-1 librsvg2-2
python3 tools/install_linux.py --light-recognition
"${XDG_DATA_HOME:-$HOME/.local/share}/Shelter/shelter"
```

`--light-recognition` installs Vosk without GigaAM. Use `--directory` to choose a new installation directory. The archive includes the desktop executable and the native audio library. On Linux, volume uses `pactl` and media control uses `playerctl`. On Wayland, window control, global shortcuts, and selection capture are limited by the compositor. Start with **Speak** or text input. Linux build and startup have been checked in Ubuntu under WSL. Physical audio devices and desktop environments still need testing.

## Voice, characters, and workflows

- Open **Settings → Voice and hearing** to choose a microphone, recognizer, and voice. GigaAM and Vosk recognize Russian on desktop. Changing the UI language leaves the recognition language unchanged. An installed compatible speech extension can be selected here.
- Open **Character** to select a preset or edit a copy. To attach Pippa’s original appearance, open **3D model page**, download `08_Pippa.zip` from the creator, and extract it. Edit Pippa, open **Appearance**, select the extracted `.vrm`, save the copy, and select it. Manju’s model is included. Selecting Yuki downloads her pixiv model. [Pippa’s source and terms](https://booth.pm/ja/items/4613310) · [Asset credits](../THIRD_PARTY.md)
- Shelter accepts self-contained humanoid VRM 0.x/1.0 models and VRMA animations. Use **Character** to import them and preserve the creator’s credit. The avatar menu and window controls depend on your platform. You can show the character continuously or only during a conversation.
- Open **Commands → New scenario** to add steps, conditions, and triggers. Test it before scheduling it. Supported triggers include a button, voice, time, and events. A one-off voice request can combine up to six supported steps. For example, `Открой калькулятор, поставь громкость на тридцать, потом напомни через три минуты выпить воды` opens Calculator, sets volume to 30%, and adds a reminder. A successful chain can be saved as a scenario from the task card. If a chain is interrupted, completed steps remain in effect.

## Connect models and extensions

1. In **Settings → Models and reasoning**, add a local or cloud connection. Set its endpoint, model ID, and key when the provider requires one. Assign separate models for chat, complex tasks and materials, and vision in the same section. Vision requires an image-capable model and sends the current question and requested capture. When using Alibaba Model Studio, take the base URL and key from the same region and workspace. Its OpenAI-compatible endpoint uses `/compatible-mode/v1`.
2. In **Settings → Voice and hearing**, choose cloud speech if you want to send the text to a speech provider. Set the connection, speech API, model ID, and voice ID, then test playback. OpenAI-compatible speech uses `/audio/speech` and expects WAV. Alibaba Qwen Audio uses its own API. Local speech is the fallback when cloud speech fails and a local voice is installed.
3. Under **Image generation**, choose a compatible connection and model. The endpoint must support `/images/generations` with PNG in `b64_json`. Generated images are saved in `data/generated`. Cloud usage is governed by your provider’s terms and billing.
4. In **Connections**, configure your phone, smart home, OBS, Telegram, or MCP. **Extensions** accepts `.jarvis-plugin.zip` packages. Review permissions before enabling an extension. Plugins run in a separate process with the current user’s access, so install packages from sources you trust. Extension types include actions, speech, events, widgets, and character reactions.

## Android

**Shelter** runs on Android 8+. **Shelter Local** runs on Android 12+ and adds chat with an on-device model. The two variants can be installed side by side.

- **Cloud.** Select your provider or an OpenAI-compatible endpoint, enter the model ID and key, and choose a system voice in **Voice and microphone**. Requests go to the provider and conversations are stored on the phone.
- **My computer.** On desktop, open **Connections → Phone**, enable access on your home network, and note the address, usually port `8765`. On the phone, enter the address and pair using the code shown on the PC. Enable LAN HTTP explicitly for home use. Connections from outside the home network require HTTPS with a valid certificate. With PC voice enabled, the phone plays the desktop voice and **Stop** interrupts a task on the PC. You can revoke a phone from the desktop app.
- **On device.** In Shelter Local, open **Settings → On device** and download Qwen3 0.6B (about 347 MB). The app checks architecture, memory, storage, and the download before activating it. You can cancel the download or import a compatible `.litertlm` file. The built-in download is intended for short requests.
- **Background microphone.** Download the Russian Vosk pack in **Voice and microphone**. Start listening from the open app and grant the requested permissions. Say `Слушай, помощник`, wait for the signal, then make the request. Stop listening from the app or the persistent notification. A session lasts up to 30 minutes and has to be started again after reboot. Model downloads and background controls have been exercised in an emulator. Battery use and microphone behaviour on physical phones are still unverified.

## Games

| Game | Get started | Controls and compatibility |
| --- | --- | --- |
| **Minecraft Java Edition** | In **Games → Minecraft**, use **Separate account** with Node.js 22+ and a second Microsoft account with Java Edition. Set your player name and server address and allowlist the companion where needed. | Use `!jarvis координаты`, `!jarvis иди за мной`, or `!jarvis стоп`. Paper 1.21.5 with the inventory plugin supports `!inv` near the bot. For an account-free companion, see the Paper 1.21.11 and Fabric/Carpet 1.21.11 adapters. The separate NeoForge 1.21.1 mod uses `/companion summon` and supports `!inv`. Choose the adapter for your world and version. |
| **Factorio 2.0 / 2.1** | Prepare the mod in **Games → Factorio**, install its ZIP in `mods`, then run `/shelter-export` in the world. | Queue ten gear wheels with `/shelter-craft iron-gear-wheel 10`. Monitor progress in Shelter. `/shelter-stop` stops adding new work. Factorio’s crafting queue controls work already queued. |
| **Hearts of Iron IV** | Prepare **Shelter Campaign Tasks**, extract the archive to the game profile’s `mod` folder, and enable the mod in the launcher. | Campaign decisions can create an infantry equipment production line and track a stockpile goal. The package has been generated and inspected. The decisions still need verification in a running campaign. A configured vision model can also describe the foreground game window when asked. |

Game integrations use the supported client or mod’s permissions and state. Modded Minecraft recipes depend on the registry available to the chosen adapter. See [the detailed game notes](GAMES.md) and [Minecraft setup and commands](MINECRAFT.md) in Russian.

## Develop, test, and package

Run the Windows build from the [project overview](../README.md). On Ubuntu 24.04, run `bash tools/setup_linux.sh` from the repository root to prepare system dependencies and `.venv-linux`. For a graphical build, install Node.js 22.12+, Rust, and the Tauri GTK/WebKitGTK development dependencies. Then run `npm --prefix app ci` and `npm --prefix app run desktop:build` with the Python environment on your PATH.

Use the project’s Python environment for these checks from the repository root.

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

For Android, use JDK 21, SDK Platform 35, and Build Tools 36.0.0. In `android/` on Windows, run:

```powershell
.\gradlew.bat --no-daemon :app:assembleCompanionDebug :app:assembleLocalDebug :app:testCompanionDebugUnitTest :app:testLocalDebugUnitTest
```

On Linux, use `./gradlew` with the same arguments. Build a public snapshot with `python tools/export_public.py release/github-source` into a new directory. It includes these translations and excludes personal data and the working Git history. Build release artifacts from that snapshot and verify their checksums before publishing. See [release packaging notes](PUBLIC_RELEASE.md) in Russian and [contribution guidelines](../CONTRIBUTING.md).

## Data, security, and licenses

Keep tokens, voice samples, personal memory, and full logs out of public issues. Report vulnerabilities through the repository’s private reporting channel when available. The local desktop API requires a token and phone access requires pairing. Expose phone access only through the supported companion connection.

The [MIT license](../LICENSE) covers Shelter’s code. Downloaded models, portraits, VRM assets, and other dependencies follow their separate terms. The [third-party notices](../THIRD_PARTY.md) include source links and creator credits.
