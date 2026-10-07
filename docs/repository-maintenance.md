# WSL 工程整理与提交清单（2026-10-07）

规范工作树为 `/home/openion/Valence`，分支 `main`。本次只整理路径、构建边界和文档，
不改硬件行为、不重新综合、不覆盖已有开发修改，不自动创建提交。
整理前 HEAD 为 `559e52bf70972804639736ea01d7f74cb9f5bce2`；
工作树包含此前 F/D、GMAC、CMU、DMA、2 GiB 地址及板级优化等未提交开发，不能用 `git reset/clean` 清理。

## 整理结果

- 当前硬件只留根 `src/main/scala`；旧核的 51 个硬件和 3 个测试/导出源文件迁入 `legacy/hardware/src`，字节和包名不变。
- 当前模块 `IonSoC` 不再默认依赖旧 Scala `DifftestLib`；历史模块 `LegacySoC` 显式依赖公共定义及该库。
- `legacy` 保留旧源码、退役测试、有价值的汇编/配置/故障记录。移出未使用的 3 个旧助手/重复配置。
- 15 个 `.orig`、空 `wget-log`、重复 `build.sbt` 和 9 个完成的本机作业移入仓库外归档。
- 根 `build` 的 16,140,196,267 字节产物先完整归档和比对后清空；只重新生成必要 GSIM smoke。
- 保留 `simulator/build` 的工具/Linux/OpenSBI 等源码缓存、`out` 的增量缓存及 Git 子模块，避免重部署。
- 新增生成物与私钥/许可文件的忽略规则；不把镜像、DCP、bit、波形或 rootfs 纳入提交。

## 外部归档

归档位于 `/home/openion/Valence-archive/20261007-precommit`，不进入 Git：

| 文件/目录 | 内容 |
| --- | --- |
| `source-before-cleanup.tar.gz` | 整理前 1104 个源码/文档/工具文件快照 |
| `source-before-cleanup.json` | 文件 SHA256、原路径与 HEAD |
| `worktree-before-cleanup.patch`、`index-before-cleanup.patch` | 整理前 Git 差异，原暂存区为空 |
| `build-before-cleanup.tar.gz` | 完整原 build、历史报告/回执/固件/检查点 |
| `build-before-cleanup.json`、`build-cleanup.json` | 全包校验及清理范围记录 |
| `current-release-r6/` | 可直接读取的最新 bit、签核/审计与发布文件 |
| `obsolete-backups/`、`obsolete-source/`、`completed-local-jobs/` | 从工作树移出的冗余备份、旧助手、完成作业 |
| `source-moves.json`、`source-split-preflight.json`、`source-split-final.json` | 精确迁移清单与独立模块边界证据 |
| `precommit-audit.json`、`cleanup-final.json` | 提交预演、链接/生成物检查与最终整理回执 |

源码包 SHA256：`938a22c403b1620e404fd2ba207033a5940f4e1012a39123893f368d7b49793d`。
build 包 SHA256：`0d025938f03b78a842d58c56868e96b0dcb31567faa3fdca25d4c7217f6f1299`。
两个 tar 包均已与原文件逐项比对，build 包压缩后 6,151,320,461 字节。
归档包含本机历史资料，按私有文件保存，不上传或提交。

恢复应解包到**另一个新的空目录**，不能覆盖已整理的工程：

```bash
# 将下面路径替换为专门用于查阅旧证据的空目录
mkdir -p /home/openion/Valence-restore-20261007
tar -xzf /home/openion/Valence-archive/20261007-precommit/source-before-cleanup.tar.gz -C /home/openion/Valence-restore-20261007
tar -xzf /home/openion/Valence-archive/20261007-precommit/build-before-cleanup.tar.gz -C /home/openion/Valence-restore-20261007
```

子模块不包含在源码 tar 中，版本由 Git 元数据保留。旧证据中记录的原机器绝对路径不自动重写。
最新 bit 和回执的哈希保留原发布口径；目录整理不代表重新签核，更不证明最新 bit 已上板复测。

## 验证与提交

迁移前已核对两模块源码全集、无重叠、公共依赖方向，并通过 10 项历史参数/译码纯展开和
21 项当前 OoO/UART 参数检查。迁移后重新编译两个模块及测试入口，并运行一次短 GSIM smoke。
全部 352 个当前/历史 Scala 源码与整理前备份 SHA256 一致；86 个导航文件链接全部有效，
`git diff --check` 和 `git add --dry-run -A` 通过，待提交清单没有意外大文件、私钥/许可或生成镜像。
短 smoke 后的 `build` 约 1.8 MiB，原暂存区及 HEAD 未变。
不为目录整理重跑全量 GSIM、Linux 启动、Vivado 或 bit 生成。

准备提交时先审查全部既有开发变更，尤其确认源码、第三方许可和 BSP 模板齐全，且无镜像/许可私钥：

```bash
git status --short
git diff --check
git add --dry-run -A
# 审查完成后由用户执行；本次整理未自动暂存或提交
git add -A
git diff --cached --stat
git diff --cached --check
git commit -m "feat: integrate VL100 RV64GC platform and separate legacy hardware"
```

暂存后 Git 会将字节不变的旧源码识别为移动，而非功能删除。提交只包含源码/文档/可复用工具；
完整本机发布归档留在仓库外。模块布局见 [layout](layout.md)。
