# 手动构建包含环境的 APK

工作流为 `.github/workflows/manual-full-apk.yml`，只有 `workflow_dispatch`。
推送代码、提交 PR、创建标签和定时任务都不会触发；本地修改工作流也不会启动构建。

首次使用时，在仓库 **Settings → Secrets and variables → Actions** 配置：

| Secret | 内容 |
| --- | --- |
| `CODEX_KEYSTORE_BASE64` | 原签名 keystore 文件的 Base64 内容，必填；不要提交密钥文件 |
| `CODEX_SIGNING_STORE_PASSWORD` | keystore 密码；省略时使用 Android 标准 debug 密码 |
| `CODEX_SIGNING_KEY_ALIAS` | 签名条目别名；省略时为 `androiddebugkey` |
| `CODEX_SIGNING_KEY_PASSWORD` | 条目密码；省略时使用 Android 标准 debug 密码 |

签名证书须匹配 `config/android/native-baseline.json`，以便覆盖升级现有安装。
发布使用工作流自己的 `GITHUB_TOKEN`，无需把个人 GitHub token 写进源码或 Secret。

进入 **Actions → Build full APK (manual) → Run workflow**，选择：

| 参数 | 含义 |
| --- | --- |
| `engine_ref` | `latest` 解析上游最新稳定后端标签；`supported` 采用当前恢复清单；也可指定版本号或 `rust-v…` 标签 |
| `desktop_version` | `latest` 采用官方签名 ARM64 软件索引中的最新版本；也可指定索引中仍提供的版本 |
| `rust_toolchain` | 默认安装当前 Rust 稳定版；也可指定所选后端需要的精确编译器版本，实际版本写入构建记录 |
| `rebuild` | 默认 `none` 复用已完成组件；可选 `base`、`mesa`、`engine` 或 `all` 强制重建对应组件 |
| `version_code` | 可填写更大的 Android 版本号；留空为源码版本号加工作流运行编号 |
| `release_tag` | 可填写新的 Release 标签；留空为 `v<versionCode>`；已有标签和 Release 不会被覆盖 |

版本在构建开始时解析并冻结到构建记录，构建中途不会继续追踪 `latest`。
新版后端仍需能应用仓库的 Android 补丁，新版前端仍需通过 ASAR 适配校验。
不兼容时工作流失败并保留日志，不会悄悄回退旧版本，也不会取消校验来强行发布。
后续需要迁移补丁时，更新 `recovery/engine/manifest.json` 与配套补丁即可；GNU 构建器没有另藏固定提交号。

首版从 `config/android/native-baseline.json` 指定的已发布 APK 校验并复用原生 JNI、执行器和 Python 载荷；
Codex GNU 后端、Mesa 和干净 Debian 环境首次在云端构建，以后按各自输入复用已完成的组件。原生载荷必须与当前源码清单相符，否则拒绝构建。
因此需保留该基线 Release 的 APK，且不能将这一流程称为全部原生组件从源码重建。
该输入单独归档在 `ci-native-baseline-v60` 预发布中，不作为最新应用版本。
应用 Release 的整理不应删除或替换这项构建依赖；更换原生基线时应同步更新清单中的下载地址、哈希和签名身份。

## 复用未变化的组件

构建分成九个任务：冻结版本、校验客户端、校验原生基线、Debian、Mesa、后端、环境组装、APK 打包、发布。
客户端和原生基线校验完成后，Debian 与 Mesa 并行；后端只等待 Debian。环境组装等待所需组件全部完成。

| 组件 | 复用依据 | 需要重新构建的情况 |
| --- | --- | --- |
| Debian | 基础环境的构建和验证脚本 | 修改脚本、选择 `rebuild=base`，或缓存不可用 |
| Mesa | 驱动版本、补丁、构建脚本和随包探针源码 | 修改这些输入、选择 `rebuild=mesa`，或缓存不可用 |
| Codex 后端 | 上游提交、Android 补丁、Rust 版本选择与后端构建脚本 | 修改这些输入、选择 `rebuild=engine`，或缓存不可用 |
| 原生基线 | 基线 APK 清单中的地址、哈希与证书身份 | 更换清单或缓存不可用时重新下载并校验 |

例如，只更新 Android 界面或切换 Codex 后端版本，不会使 Mesa 和 Debian 缓存失效。
`rust_toolchain=stable` 复用时保留该组件原先记录的实际编译器；需要用新的稳定编译器重新编译时选择 `rebuild=engine`。
Debian 软件源或工具链可在仓库脚本未变化时更新；需要刷新这些依赖时，手动选择对应的 `rebuild` 项。
`all` 强制重建 Debian、Mesa 和后端；原生基线仍按已固定的清单复用。

每个完成的组件先校验文件清单与 SHA-256，再保存缓存和本轮 artifact。导入时再次核对，
缓存身份或内容不符会失败，不会使用另一个版本代替。组装环境时还会验证已缓存后端与本轮 Debian 的 ELF 依赖，
并通过 QEMU 检查后端版本；APK 中的后端必须与已组装环境使用同一组件。

缓存由 GitHub 管理，可能因过期或容量限制被清理；缓存不存在时会重新构建该组件。
它不是永久归档。各轮产物保留三天，诊断日志保留七天。

## 失败后继续

- 源码无需修改时，在该次运行页面选择 **Re-run failed jobs**。已经成功的任务及其 artifact 会被沿用。
- 修复代码后，重新手动运行工作流，保持 `rebuild=none`。构建配方未变化的组件可通过缓存继续复用。
- 上传 Release 失败时，只需重跑失败任务。发布任务直接读取已校验和签名的 APK，补传缺失或未完成的附件，校验通过后再公开。

如果本轮 artifact 已过保留期，重新手动运行工作流；已有组件缓存仍可按输入匹配复用。
工作流不会覆盖其他构建创建的 Release、草稿或标签。

完整 APK 内置环境包与对应校验清单，首次启动直接流式解压、创建本机账户和密钥环。
已有 Linux 环境继续保留，不会因为内置了新环境包就重置项目或登录信息。
发布前校验 APK 内容、原签名和上传摘要；通过后自动公开 Release，并使用
`config/android/release-notes.txt` 中的说明，同时附带 `build-info.json` 和 `SHA256SUMS`。
未通过的上传保留为草稿；小体积日志保留七天，不上传签名密钥或手机数据。

2026-11-16，[第 10 轮 Actions](https://github.com/JinShichang/codex-desktop-android/actions/runs/43744217664)
已完成完整 APK 构建、签名、校验并发布 [v70](https://github.com/JinShichang/codex-desktop-android/releases/tag/v70)。
发布阶段首次创建草稿后未能从列表识别该草稿；仅重跑失败任务后复用已保存的 APK 发布成功。
下载后的成品也已通过完整环境归档、版本、原签名和 DEX/JNI 离线检查。
新设备首次安装和 Android 11/12 真机运行仍未验证；工作流成功不等于通过真机测试。
完整镜像含官方桌面客户端；公开分发前需按其适用条款处理，仓库的开源许可证不授予该客户端的再分发权。
