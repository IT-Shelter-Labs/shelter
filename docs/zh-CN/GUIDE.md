# Shelter 使用与开发指南

[English](../GUIDE.md) · [Русский](../ru/GUIDE.md) · [日本語](../ja/GUIDE.md) · **简体中文** · [项目概览](README.md)

本指南保留了英文界面中的菜单名称，便于查找。语音示例保留俄语，可以直接按原文说出。

## 安装和首次启动

**Windows。** 从 [GitHub Releases](https://github.com/IT-Shelter-Labs/shelter/releases) 下载 x64 安装程序。运行后选择安装目录，按首次启动向导安装语音识别和朗读组件。启用唤醒词前，请先选择并测试麦克风。点击 **Speak** 发出一次请求，点击 **Stop** 中断监听、朗读或正在执行的操作。桌面端默认唤醒词为 `Джарвис`（Jarvis）。已有角色选择时沿用原设置。

**Linux。** x86_64 压缩包面向 Ubuntu 24.04 构建。先安装系统依赖，再在解压后的发行包目录中运行命令。

```bash
sudo apt install python3 python3-venv libportaudio2 libgtk-3-0t64 libwebkit2gtk-4.1-0 libayatana-appindicator3-1 librsvg2-2
python3 tools/install_linux.py --light-recognition
"${XDG_DATA_HOME:-$HOME/.local/share}/Shelter/shelter"
```

`--light-recognition` 会配置 Vosk，省去 GigaAM。使用 `--directory` 可指定新的安装目录。压缩包包含桌面可执行文件和原生音频库。音量控制使用 `pactl`，媒体控制使用 `playerctl`。在 Wayland 下，窗口控制、全局快捷键和选中文本的获取受合成器限制，可以先使用 **Speak** 或文本输入。构建和启动已在 Ubuntu WSL 环境中验证，实体音频设备及其他桌面环境仍待测试。

## 语音、角色与工作流

- 在 **Settings → Voice and hearing** 中选择麦克风、识别引擎和语音。桌面端的 GigaAM 和 Vosk 识别俄语。更改界面语言不会改变识别语言。已安装的兼容语音扩展也可以在这里选择。
- 在 **Character** 中选择预设。要使用 Pippa 的原版外观，打开 **3D model page** 下载 `08_Pippa.zip`，然后在她的角色卡中点击 **Attach 3D appearance** 并选择该压缩包。要导入旧版角色外观和本地 Jarvis 声音，请点击 **Restore from a previous installation**，再选择原 Shelter 目录。[Pippa 的来源和使用条款](https://booth.pm/ja/items/4613310) · [素材署名](THIRD_PARTY.md)
- Shelter 支持包含内嵌纹理的人形 VRM 0.x/1.0 模型及 VRMA 动画。在 **Character** 中导入并保留作者署名。虚拟角色窗口的控制方式因平台而异，可以始终显示角色，也可以仅在对话时显示。
- 在 **Commands → New scenario** 中添加步骤、条件和触发器。设置定时运行前先测试。触发方式包括按钮、语音、时间和事件。一次语音请求最多可以组合六个受支持的步骤。例如 `Открой калькулятор, поставь громкость на тридцать, потом напомни через три минуты выпить воды` 会打开计算器、将音量设为 30%，并创建三分钟后的提醒。执行成功的步骤链可以通过任务卡保存。中途中断时，已完成的操作仍然有效。

## 接入模型和扩展

1. 在 **Settings → Models and reasoning** 中添加本地或云端连接。填写服务地址、模型 ID，以及服务商要求的 API 密钥。此处可以分别指定聊天、复杂任务与资料、视觉分析使用的模型。视觉分析需要支持图像输入的模型，会发送当前问题及请求的截图。使用 Alibaba Model Studio 时，请从同一区域和工作空间获取 Base URL 与密钥。OpenAI 兼容路径为 `/compatible-mode/v1`。
2. 在 **Settings → Voice and hearing** 中配置云端语音合成。选择连接和语音 API，填写模型 ID 与音色 ID 后试听。兼容 OpenAI 的 `/audio/speech` 接口应返回 WAV。Alibaba Qwen Audio 使用专用接口。云端出错时会回退到已安装的本地语音。
3. 在 **Image generation** 中指定连接和模型。服务必须支持 `/images/generations`，并在 `b64_json` 中返回 PNG。图像保存在 `data/generated`。云端使用量按服务商的条款和计费规则计算。
4. 在 **Connections** 配置手机、智能家居、OBS、Telegram 或 MCP。**Extensions** 支持安装 `.jarvis-plugin.zip`。启用扩展前请检查其所需权限。扩展在独立进程中以当前用户权限运行，请从可信来源安装。扩展可提供操作、语音处理、事件、组件和角色反应。

## Android

统一的 Shelter 应用在 Android 8 及以上支持云端和电脑模式。端侧聊天需要兼容的 64 位设备和 Android 12 及以上。首次启动时可选择模式，之后可在设置中切换。旧版 APK 分为 Companion 和 Local。

- **Cloud（云端）。** 选择服务商或兼容 OpenAI 的 API，输入模型 ID 和密钥。系统朗读语音可在 **Voice and microphone** 中选择。请求直接发送给服务商，对话记录保存在手机上。
- **My computer（我的电脑）。** 在电脑端打开 **Connections → Phone**，启用家庭网络访问并记下地址，默认端口通常为 `8765`。在手机上输入地址，用电脑显示的代码配对。通过家庭网络使用 HTTP 时需手动启用 LAN 访问。从外部网络连接时，需要具有有效证书的 HTTPS。启用电脑朗读后，手机可以播放电脑端语音，点击 **Stop** 可中断电脑上的任务。设备访问权限可以在电脑端撤销。
- **On device（端侧）。** 在 **Settings → On device** 中下载 Qwen3 0.6B（约 347 MB）。应用会检查设备架构、内存、存储空间和模型文件。下载可以取消，也可以手动导入兼容的 `.litertlm` 文件。内置下载项适合简短请求。
- **后台麦克风。** 在 **Voice and microphone** 下载俄语 Vosk 语音包。在应用打开时启动监听并授予所需权限。说出 `Слушай, помощник`，听到提示后再说请求。可在应用内或常驻通知中停止监听。一次会话最长 30 分钟，重启后需要手动启用。模型下载和后台控制已在模拟器中验证，实体手机的麦克风行为和电池消耗仍待测试。

## 游戏

| 游戏 | 接入步骤 | 操作和兼容性 |
| --- | --- | --- |
| **Minecraft Java 版** | 在 **Games → Minecraft** 选择使用独立账户的模式。需要 Node.js 22 或更高版本，以及另一个有 Java 版使用权限的 Microsoft 帐户。填写玩家名和服务器地址，必要时将伙伴加入白名单。 | 使用 `!jarvis координаты` 查询坐标、`!jarvis иди за мной` 跟随、`!jarvis стоп` 停止。Paper 1.21.5 安装物品栏插件后，可在伙伴附近输入 `!inv`。Paper 1.21.11 和 Fabric/Carpet 1.21.11 提供无需单独账户的适配器。独立的 NeoForge 1.21.1 模组支持 `/companion summon` 和 `!inv`。请按世界版本选择适配器。 |
| **Factorio 2.0 / 2.1** | 在 **Games → Factorio** 准备 0.3.0 版模组。要从 Shelter 发出指令，请启用本机 RCON，并在游戏中运行 `/shelter-remote`。 | 查询材料、启动制作、查看进度和停止任务，也可排入研究、放置蓝图虚影或设置组装机配方。连接独立的 Factorio AI Companion 后，可以添加能够采矿和跟随玩家的角色。 |
| **钢铁雄心 IV** | 将 HOI4 Live Tools 添加为本机 MCP 服务 `hoi4-live`。需要库存目标决议时可另行使用 **Shelter Campaign Tasks**。 | 支持战役简报、生产、科研、国策，以及在限定天数内推进和停止时间。已验证工具发现，战役内操作仍需在游戏中验证。 |

游戏集成使用对应客户端或模组的权限及游戏状态。Minecraft 模组配方取决于所选适配器能访问的注册表。[游戏详细说明（俄语）](../GAMES.md) · [Minecraft 设置与命令（俄语）](../MINECRAFT.md)

## 开发、测试和打包

Windows 构建步骤见 [README](README.md)。在 Ubuntu 24.04 上，从仓库根目录运行 `bash tools/setup_linux.sh`，准备系统依赖和 `.venv-linux`。构建桌面界面需要 Node.js 22.12 或更高版本、Rust，以及 Tauri 所需的 GTK/WebKitGTK 开发包。将项目的 Python 环境加入 `PATH`，再运行 `npm --prefix app ci` 和 `npm --prefix app run desktop:build`。

在仓库根目录使用项目的 Python 环境运行以下检查。

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

Android 需要 JDK 21、SDK Platform 35 和 Build Tools 36.0.0。在 Windows 的 `android/` 目录中运行以下命令。

```powershell
.\gradlew.bat --no-daemon :app:assembleDebug :app:testDebugUnitTest
```

在 Linux 中用 `./gradlew` 和相同参数运行。使用 `python tools/export_public.py release/github-source` 在新目录中生成公开源码快照。快照包含这些翻译，并排除个人数据与工作区 Git 历史。从快照构建发行包，发布前校验文件。[发行打包详情（俄语）](../PUBLIC_RELEASE.md) · [贡献指南](CONTRIBUTING.md)

## 数据、安全与许可证

请勿在公开 Issue 中上传访问令牌、语音样本、个人记忆或完整日志。仓库提供私密漏洞报告渠道时，请通过该渠道提交。桌面本地 API 要求令牌，手机访问需要配对。请通过受支持的手机连接方式访问电脑。

Shelter 代码采用 [MIT 许可证](../../LICENSE)。下载的模型、头像、VRM 素材和其他依赖项分别适用各自条款。[第三方来源与署名](THIRD_PARTY.md)
