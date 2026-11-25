# Google Antigravity Desktop Android (`agy-desktop-android`)

将官方 **Google Antigravity 2.0 Linux ARM64 桌面端** 完整移植到 Android 手机上运行的独立适配项目，参考并致谢 [codex-desktop-android](https://github.com/JinShichang/codex-desktop-android) 与 [FoldGPT](https://github.com/pironjulien/FoldGPT)。

应用独立包名为 `com.ai.agy`，可与 Codex Android 并存安装。全流程通过 **GitHub Actions 云端自动构建并发布完整 APK**，无需在本地电脑安装 Android SDK/NDK 或占满系统盘。

## 功能亮点

- **原生 Google Antigravity Linux ARM64 桌面端**：通过内置 Debian 13 (Trixie) ARM64 用户空间与内嵌 Termux:X11，在手机上直接运行官方 Antigravity 桌面客户端及内置 `language_server`。
- **完整手机本地开发环境**：预装 `git`、`python3`、`nodejs`、`npm`、`ripgrep`、`curl`、`openssh-client` 等开发工具，支持授权后直接访问共享存储项目目录 `/sdcard/agy/Projects`。
- **内置 MCP 手机操控**：启动时自动将 `phone`（前台读屏/点击/滑动/输入）和 `agy_android`（设备能力与只读查询）注册到 `~/.gemini/config/mcp_config.json`，并同步安装 `agy-phone` / `agy-android` Skills 到 `~/.gemini/config/skills/`。
- **实时通知 / 灵动岛与边缘光效**：监听 `~/.gemini/antigravity/brain` 对话日志与手机操控状态，在 Android 16+ / ColorOS 等支持系统上通过 Live Updates 实时展示思考、执行命令、修改文件与屏幕操作。
- **中文输入、高刷新率与图形模式切换**：内置 Electron CDP 中文输入法焦点桥接、高刷同步以及 Mesa Zink/Turnip 硬件加速 / llvmpipe 兼容模式切换。
- **`.gemini` 配置目录共享（DocumentsProvider）**：通过系统文件选择器授权访问 **Antigravity → `.gemini`**，方便外部工具读写 `mcp_config.json`、`skills` 和 `rules`。

## 使用说明

1. **关闭系统子进程限制（重要）**：在手机「开发者选项」中开启 **停止限制子进程**，或通过 ADB 执行：
   ```bash
   adb shell device_config set_sync_disabled_for_tests persistent
   adb shell device_config put activity_manager max_phantom_processes 999999999
   ```
2. **安装完整 APK**：从本仓库 [Releases](https://github.com/ZXEB/agy-desktop-android/releases) 下载 `Antigravity-Android-v*-full.apk` 安装。
3. **首次启动初始化**：完整 APK 已内置 `agy-phone-rootfs.tgz` 运行环境，首次启动会自动流式解压并初始化本机账户与加密密钥环（约需 2~5 分钟，请保证足够内部存储空间）。
4. **常用手势与入口**：
   - **长按桌面应用图标**：快速进入「Android 工具」（图形模式、日志导出 `/sdcard/agy/log`、手机操控开关、所有文件访问权限）与「Antigravity 显示设置」。
   - **双指同时点击**：鼠标右键。
   - **横竖屏切换**：旋转手机自动适配 X11 视口；可在视图中缩放界面。

## 云端构建 APK（GitHub Actions）

工作流位于 `.github/workflows/build-apk.yml`：

1. 进入仓库 **Actions → Build Antigravity Android APK → Run workflow**。
2. 默认 `desktop_version=latest` 会自动解析 Google 官方文档中的最新 `linux-arm/Antigravity.tar.gz` 版本并冻结。
3. 云端并行构建/复用 Debian 13 ARM64、Mesa Zink/Turnip 与 PRoot/X11 原生组件，组装环境镜像、编译签名完整 APK 并自动发布至 GitHub Releases。
4. 如需使用固定签名证书以支持后续覆盖升级，可在仓库 **Settings → Secrets → Actions** 中配置 `AGY_KEYSTORE_BASE64`（可选：`AGY_SIGNING_STORE_PASSWORD`、`AGY_SIGNING_KEY_ALIAS`、`AGY_SIGNING_KEY_PASSWORD`）；未配置时工作流会自动生成临时签名证书完成构建。

## 开源许可与致谢

- 宿主适配代码遵循 GPL-3.0-or-later 许可协议。
- 致谢 [JinShichang/codex-desktop-android](https://github.com/JinShichang/codex-desktop-android)、[FoldGPT](https://github.com/pironjulien/FoldGPT)、[Termux:X11](https://github.com/termux/termux-x11)、[PRoot](https://github.com/termux/proot)、[Mesa](https://www.mesa3d.org/) 与 [dsh-Go](https://github.com/ccch1mneyyy/dsh-Go)。
- Google Antigravity 客户端版权归 Google 所有，由构建流程从 Google 官方公开地址获取，本仓库开源许可不涵盖上游专有客户端的再分发授权。
