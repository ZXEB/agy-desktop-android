# 小 APK 与独立环境包

v80 将 Android 应用与完整 Linux 环境分开发放。首次安装需要同一批次的 APK 与环境包；已有 v79 配套前后端环境的用户可以直接覆盖升级 APK。

## 首次安装

1. 安装 `Codex-Android-v80-small.apk`。
2. 将 `codex-phone-rootfs.tar.gz` 放入手机内部存储的 `Download` 目录，通常为 `/storage/emulated/0/Download/codex-phone-rootfs.tar.gz`。保留原文件名，无需解压。
3. 打开 Codex，按提示在系统设置中授予“所有文件访问”权限，然后返回应用。
4. 应用自动检查固定路径，校验并安装运行环境。下载后返回应用会重新检查，也可以点击“重新检查”。

没有环境包时会显示下载提示和发布页面入口。没有文件选择器。首次安装成功后，环境位于应用私有目录，后续启动不再依赖 Download 中的压缩包；确认启动成功后可自行删除该压缩包。

首次安装需要临时保留经过验证的压缩包副本及解压后的文件，并预留空间。应用会检查内部可用空间并提示所需容量。空间不足、大小不匹配或哈希不符时不会启用该环境。

## 覆盖升级

已有环境会直接复用，不要求再次授权或下载。v80 延续 v79 的桌面端 `26.1117.31558`、GNU 后端 `0.171.0` 和手机操控资源。此版本没有实现任意旧环境的自动迁移；过旧或不兼容的前后端会报版本或完整性错误。

## 打包约定

- APK 保留 Android 界面、手机操控、原生执行器、Bionic Python、桥接脚本和可信元数据。
- 环境包包含 Debian、依赖、字体、GPU 支持、原始桌面端及配套 GNU 后端。环境包来自经过哈希验证的干净完整安装镜像，不包含已选择的用户、登录信息或密钥环。
- APK 内的 `phone-runtime/release.json` 和 `inventory.json` 绑定环境包 SHA-256、大小、成员数及启动文件清单。外部压缩包不能提供自己的可信校验值。
- 首次安装将压缩包复制到私有暂存文件，完整校验后解压；创建本机账户及密钥环后，验证不可变清单与运行环境，再原子启用。
- 桌面端按 APK 内的 manifest 匹配环境描述；GNU 双文件核对长度、SHA-256 和 ARM64 ELF 格式，再记录安装凭据。

本地构建入口为工作区 `builds/codex-v80/build-environment.py` 和 `builds/codex-v80/build-apk.py`。先生成环境与元数据，再编译 APK。拆分模式使用 `codexExternalEnvironment=true` 和 `codexEmbedPhoneImage=false`。桌面与 GNU 元数据分别从独立资源目录提供，以免重复合并 phone-runtime 资源。

## 验证范围

构建会执行 Download 来源测试、首次启动门控测试、后端文件验证测试、手机操控回归、拆包契约测试、真实压缩包 Java 解包与清单验证，以及签名和 APK 原生资源检查。另用 QEMU 运行干净环境里的 ARM64 Python 依赖导入与 GNU 后端版本检查。

这些主机检查不能代替 Android 真机首次安装、权限界面、桌面启动和手机操控验收。最终产物及每项实际结果记录于 `builds/codex-v80/validation.json` 等验证文件。
