# dev 分支源码交付（2026-10-08）

本次交付以 `6c8977f684830137fae088d4679f9d84e5ce4a11` 为基线，保存到 `dev`。
只包含源码、构建脚本、测试、配置和必要文档；不包含工具链、编译对象、仿真模型、
波形、内核/rootfs 镜像、Vivado DCP/bit 或批量日志。`main` 不作更新。

文档中的 `${VALENCE_ROOT}`、`${LEGACY_ROOT}` 和 `${EVIDENCE_ROOT}` 分别表示
当前工程、历史工程和本地证据根目录，需按环境设置；不记录个人绝对目录。

## 内容与证据

- 继承交接：219 个文件的累计补丁和归档清单已逐项核对。原始树为
  `8ae3db0badcfef91192cf159df871eb89cfb9d33`；首次交付仅概括两处文档中的本地路径和
  内部调度描述，源码字节不变。其历史短验证属于继承证据，没有重新执行整个旧验证集。
- RAM/存储结构：bridge payload 复用与 home tag RAM 的短 A/B、独立负对照、
  主机模型和受影响 Scala 检查通过。实际 RAM 推断、布局布线资源和时序尚未验证。
- CPU：新增默认关闭的 virtual-load precheck policy2。相同 ELF 的完整核心短检查中，
  warm 用例为 4422 → 1809 拍，依赖链为 2311 → 2311 拍，cold 用例为 512 → 538 拍。
  保留冷缓存代价与独立负对照；这些是限定负载的仿真结果，不代表广泛应用或物理频率提升。
- Linux：保留适配驱动、posted RX/TX 队列头文件、镜像构建器和主机验证。
  Debian 模块打包明确包含所需队列头文件；闭包和缺失头文件负对照通过。
  驱动相关主机检查不能替代匹配内核编译、镜像重建或实板网络验收。
- rootfs：移除自编译 fastfetch 及其专用源码/CMake 下载与构建链，旧 seed
  镜像再打包时也过滤遗留文件。新增内容/负对照检查通过；未重建整张镜像。
- AXI：AW/W 独立推进作为单独批次；编译、配置、pipeline、denied tail、
  AW-leading-W、skew reset、384 请求 fabric 检查和独立负对照通过。
- 交付入口：源码/证明输入校验与导出门禁的 122 项主机检查通过。

## 当前边界

默认双发射配置保留，virtual-load precheck 仍需显式开启。
本轮 Vivado 物理验证仍待完成；本次没有新的整板 setup/hold、CDC、ROM INIT、资源或物理时序签核，
也没有生成新 bit。不得把历史板级结果当作本次候选结果。

Linux 匹配内核模块编译、完整镜像重建、实板启动/网络与 Linux 浮点调度仍待验证。
主机环境缺少 `dtc` 和固定 CoreMark 源码的检查保留为未完成，不记为通过。
失败与后续修正的测试历史未被删除，原始大型证据和生成物不随 Git 提交。

详细范围：
[当前性能记录](performance-status.md)、[RAM/payload](axi-payload-reuse.md)、
[home tag RAM](home-tag-ram.md)、[CPU policy2](virtual-load-precheck-candidate.md)、
[AXI write pipeline](axi-write-pipeline.md)。
