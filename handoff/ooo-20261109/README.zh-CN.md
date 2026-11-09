# Valence 全分支本地接手入口（2026-11-09）

## 取代码

交付分支：`integration/ooo-local-handoff-20261109`。

```sh
git clone --branch integration/ooo-local-handoff-20261109 https://github.com/Surplars/Valence.git Valence-ooo-local
cd Valence-ooo-local
git log --oneline --graph -20
```

已有仓库请先保存自己的修改，只 fetch 新分支并另建 worktree，不要 reset/clean 原工作树：

```sh
git fetch origin integration/ooo-local-handoff-20261109
git worktree add -b local/ooo-handoff ../Valence-ooo-local origin/integration/ooo-local-handoff-20261109
```

离线恢复：将两个 `Valence-ooo-handoff-20261109-part*.zip` 解压到同一空目录，运行 `python restore.py --out Valence-ooo-local`。脚本仅校验分卷/总SHA256、拼接Git bundle并clone到新目录，不安装工具、不运行硬件、不联网。完整bundle含单一交付分支的全部祖先历史；旧分支HEAD都能按本清单SHA重新建分支。外部Git子模块只保存指针，不包含其仓库对象。

## 已经真正合并的内容

不是 `ours` 占位合并，也不是只存refs或补丁。七个真实双亲merge将各分叉文件纳入工作树，并保留历史；源清单中的全部16个原始ref记录（含重复HEAD）对应的提交均是交付分支祖先。远端盘点时9个分支，加3个远端已不再列出但云端尚有的缓存分支，均保留。

- H/AIA `e437ba20960a7123ba60e7a91f3dbeec86117b8c` 为基线，已包含 verified-A1、nax/coexisting、common-idle和main主线。
- 本地 recovery `fbdb3386c30603d3f4039389a537f18a5ae508f8`：新增4份recovery证明源码/文档。`90b6f9c`与远端`08dfdea`完整Git树相同，因此冲突处保留后来主线的RenameRob和文档，未丢失原storage实验。
- `bd2b6e4ab19695708f2768ce7e15a6b94f79e5f2`：parallel-ingress及final-response源码和独立实验入口实际合并；仍保留原default-off和限定profile检查。
- `5b8fa056870c134849f9aa20fe93062b588c67df`：DDR-resident CPU性能源码与历史证据实际合并。
- `f52faf98b64c777d69e6d2aaab624f0c94c7f877`：W14历史快照实际合并到`recovery/w14-banked-indirect-20261105`，保留原始provenance，不把生成RTL冒称整核Scala实现。
- `b047cf4a337b710fb59b0403a916417a82eb295a`：I1/H/板级及软件分支实际合并；I1仍是独立核，不改变A1选择。
- `dfbf297698efcc099683c8ebc012b0962742a885`：Ethernet RX prefetch与现有runtime admission/bounded检查共同保留，默认关闭新prefetch；增加组合配置/CHIRRTL测试。
- `a88841aeac4eb9f746ff4ba435832691dd6737a1`：store/full-line/cache/Home/transport/backend实验源码、CRC/checksum及固件优化实际合并。默认保留较新的aligned64 `netboot_copy`，`NETBOOT_STORE16_PACKING=1`显式保留incoming halfword路径，两者都有独立oracle。实验仍按各自入口选择，并非自动把所有互斥配置一起开启。
- 原`integration/all-compatible-20261108`的所有未提交源码及交付脚本已提交，包含W11 signed32 opt-in、W14整核配置接入及probe-acquire组合。
- 原未提交`integration/mul-load-capture-20261108`已由先前两份交付物精确重建：4个测试/导出Scala改动+7个delivery文件；1239/1239历史编译输入哈希匹配。该overlay已实际提交，模式`efficiency4-mul-candidate`可由现有导出器选择；生产src/main不另行改写。未伪造当时不存在的Git提交历史。

`BRANCHES.json`给出每个完整SHA、共同祖先、远端存在状态和当前祖先核验。里面的merge-tree冲突输出是合并前诊断，不表示最终树仍有冲突。`inventory/`记录冲突解决；`branches/*.patch.gz`只是额外恢复副本，不是代替以上真实merge。

## 唯一仍无法恢复的源码线路

`Valence-timing`不存在于当前云端；其历史receipt写的`78b4b4298d866a97f1c2804ca299b785639ab7a3`也不能从同一远端获取（`not our ref`）。核对现有源码与MUL恢复后，1248个绑定输入中1229个精确匹配，仍缺19个精确版本，清单与期望SHA在`recovery/TIMING-MISSING-SOURCES.json`。

因此**零额外延迟timing改动没有被声称合并到Scala源码**。完整原始baseline/candidate RTL、证据、生成RTL差异保存在`recovery/Valence-zero-latency-timing-20261108.zip`及相邻文件，654/654 manifest散列已验证。请本地若仍持有Valence-timing工作树或这19个原文件，先按散列补回，再作源码级合并和验证，不能直接以生成RTL差异猜写Scala。

W12/W18旧owner/rank裁剪、W15/W16比较器graft、未定位W17、被拒W19没有可恢复的独立维护分支。已有W14历史closure、现存各实验源码与全部可获取Git历史都已保留；不宣称找到了不存在的历史源码。W18旧有限路径退化等历史结论仍见原交付说明，不能视作本批验证。

## 验证与使用边界

本次最终代码编译通过，8个Scala suite共30项检查通过，固件两种store路径及CRC/checksum的独立oracle与负向控制通过。最终代码提交为`9f9d72f20e2361e696cdd1b0ceccfc20a42adc4c`；随后只新增接手文档/归档。全部结果见`VALIDATION.json`，历史交付的结果仍保留原日期和范围。编译、配置/elaboration、组件行为、整核运行、物理实现是不同层级。

- 不运行或声称通过全GSIM、全CPU/CoreMark/NEMU、Linux长跑、Vivado、路由、CDC签核、板卡或bitstream。
- GSIM是唯一允许硬件行为模拟入口。当前重跑遇到缺少已验证的repaired initialization epoch receipt；不得改用未认证旧二进制或Verilator绕过。按仓库现有`make gsim-setup`在本地准备合格工具后运行必要短检查。
- 主线与互斥实验都在同一个源码分支里，但保留默认关闭、模块边界及各自合法profile。全部源码合并不等于所有优化可同时实例化，更不等于最终时序/吞吐合格。
- 历史W11/W14/MUL RTL包只绑定其原始源码，新增分支merge后不能把旧RTL当本分支重新生成的RTL。
- 常规编译：`mill -i IonSoC.test.compile`。MUL/组合入口见`delivery/combined-20261108`和`delivery/mul-capture-20261108`。需要真实重新导出时重新生成严格compile receipt，不能修改旧receipt迎合新源码。

原云端Valence和Valence-integrated工作树没有reset、clean或覆盖，原远端分支没有删除/强推。本分支提供独立接手点。
