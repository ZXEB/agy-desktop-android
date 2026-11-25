# 最近列表持续加载修复报告

日期：2026-11-21（Asia/Hong_Kong）。范围：用户授权的本地 Android 客户端排查、修复与 APK 构建；仅涉及目录分页完成状态同步。采用普通技术分析结构（flavor=null），不涉及攻击或账号数据。本文将授权、范围和时间线直接记录在内，未另建 case 目录。

**v79 已构建并通过本地验证，用户随后反馈测试无异常。** 本报告中的诊断和主机回归由本地工具记录；用户反馈不等同于已记录的完整真机冷启动与重启验收。已证实目录服务完成状态与前端 reader 失步，使已耗尽的最近列表反复读取本地目录并显示加载圈。修复同步同一 reader 的状态，不强制隐藏加载圈，也不清除列表。原始前后端资源版本保留，精确触发失步的初始化顺序尚未证实。

## 证据、结论与修复

下列路径均以仓库根目录为起点；`../builds/` 为同一工作区的构建、诊断目录。诊断文件含本地运行上下文，本文不摘录任何私有账号或会话内容。

| Evidence | source_ref 与观察 | content_hash（SHA-256） | 复核方式 |
|---|---|---|---|
| E-001 | `../builds/diagnostics/recent-spinner-20261121/catalog-flow.json`：组件状态已完成；同目录 `service-status.json`、`catalog-live.json`、`catalog-private-error.json` 记录服务完成、reader 仍可加载及持续分页 | `1991a074e042fdd59bb627ecc7020e81f59798c9ed448963e412b44361a262ad`（catalog-flow） | 离线读取上述保留文件；现场状态已临时恢复，无法原样重放现场 |
| E-002 | `../builds/codex-v79/original-catalog.js`：`ig` 仅在激活时同步状态；reader 的 `updateStatus` 维护完成 host 集合 | `775f0ef59fb0b9866f98ad6148c731548f9c5cd8c7ad2d6c60b40ef83d03639f` | 查看实际 bundle 中 `ig`、`r8.updateStatus` 和 `r8` 的 hasMore 判定 |
| E-003 | `../builds/codex-v79/catalog-regression.json`：真实 `ig`、`r8` 执行回归通过 | `a48e80960656b9e8228d0bd354f97cc6f30dd1b07ef2342c39788bd26720f423` | 下方 Node.js 命令 |
| E-004 | `../builds/codex-v79/client-migration.json`：v78 旧 archive/receipt 升级及重复启动通过，官方备份保留 | `a4323e4dab59153e9507921b3ae2236efc6798b154342e6e74fe8c4cb3ae3339` | `../builds/codex-v79/verify-client.py`；需既有 WSL 客户端备份与构建目录 |
| E-005 | `../builds/codex-v79/adapter-tests.json`：POSIX 安装器 21 项测试通过 | `38987cde46f053e18a60dcf7d31f35a9a6cdbe4ebd80ea2d079db64766e00a6d` | WSL 中运行 `python3 -B tools/runtime/test_install_workspace_provider.py` |

**F-001**（category=other，severity=n/a_re，status=validated，confidence=high；evidence_ids=E-001/E-002/E-003）：目录服务已完成而 reader 的完成 host 集合滞后，导致 `hasMore` 保持为真，重复触发本地目录分页。观察到的计数并非网络 `thread/list` 请求数量；没有证据将原因归于网络故障，也未确认唯一的初始化竞态触发顺序。

**F-002**（category=other，severity=n/a_re，status=validated，confidence=high；evidence_ids=E-002/E-003/E-004/E-005）：在 `ig` 激活 effect 后独立同步 `f.updateStatus(n)`，依赖 `[f,n]`，可终止已完成且耗尽的分页；不会因状态变化销毁 reader，真实游标、`hasSourceMore` 和未完成 host 仍保留加载能力。落点为 [安装器](../tools/runtime/install-workspace-provider.py) 的 `catalogSync`，仅对已审核 archive 和成员指纹生效。

## 调用路径与兼容边界

**P-001**（path_type=callflow；start=APK 更新后启动；goal=保留列表并正确结束分页）：

1. `CodexRuntimeService` 调用 `CodexLocalTools.install` 刷新 guest 安装器，`codex-session` 在 Electron 启动前检查并适配客户端（E-004/E-005，F-002）。
2. 安装器验证官方 ASAR 指纹、保留备份，并重新计算旧 v78 archive/receipt 的合法计划，再原子发布新适配文件与 receipt（E-004/E-005，F-002）。
3. 对 `webview/assets/async/191628.72f208c924.js` 校验 E-002 指纹，在字节偏移 132147 插入独立 effect；仅比原有适配多修改该 catalog 成员（E-002/E-004，F-002）。
4. 完成状态变化同步到同一 reader，已耗尽页不再反复读取；仍有数据的页继续加载（E-003，F-001/F-002）。

时间线：11 月 21 日保全 ADB/CDP 现场并临时恢复列表；随后完成指纹补丁、真实 bundle 回归、旧 receipt 迁移与 POSIX 测试；最后生成 v79。临时现场恢复不作为持久修复的真机验收。

## 构建结果与复现

[构建验证结果](../../builds/codex-v79/validation.json)记录 APK 为 `Codex-Android-v79-recent-catalog-fix.apk`，973,970,446 字节；SHA-256 为 `4499d92e07cb122a28a004e9bbaf15aa65edc6aecd1b56181c0d715b5eceb99a`。前端 `26.1117.31558`、后端 `0.171.0` 保留；1398 项 phone 测试、11 项日志测试、签名及 zipalign 验证通过。与 v78 的 2742 个 `assets/`、`lib/` 文件比较，仅 `assets/codex-tools/install-workspace-provider.py` 变化；既有全屏、启动页和 openat native 资源保持。

在工作区根目录以 Node.js 24.20.0 复现真实组件回归：

```powershell
node builds/codex-v79/test-catalog-sync.cjs builds/codex-v79/original-catalog.js builds/codex-v79/patched-catalog.js
```

原 bundle 会重现失步与额外本地读取；补丁版验证完成页停止、同一 reader/缓存保留、未完成 host/有效游标继续分页、卸载清理正常。用户随后反馈 v79 测试无异常；完整冷启动及重启测试过程未另行记录，本文不扩展其验收范围。
