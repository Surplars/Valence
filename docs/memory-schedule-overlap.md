# 三链调度与所有权交接优化

2026-10-12，WSL `/home/openion/Valence`，`dev` 基于
`f1ef88653dd8f13724742bed7c40888a34242e3b` 的改动；验收时为本地未提交状态。
接续[整行 Grant＋读写预取有限并行](internal-line-grant-prefetch.md)。
本批统一开关 `memoryScheduleOverlap` / `--memory-schedule-overlap` 默认关闭；
验收时尚未 commit/push；本次源码交付以 Git 提交和远程分支记录为准。
没有提升 preset、综合、STA、Linux 验证或生成 bit；原验收回执保留当时状态，不回写。

## 一批修改的三个边界

1. 回填／回复与后续请求：真实 E 确认后，完整 payload、错误和 ticket 交给原有
   response ledger，即可释放非 posted 的 MSHR。CPU 回复背压不再保留 fill way；
   回复仍按原顺序、原信用返回，不能借释放 MSHR 凭空增加回复容量。
2. 脏写回与独立访问：SRAM victim 快照完成后，非 posted Acquire 可提前排队。
   C 只读已锁定的 `evictionWords` 时允许另一安全 way 的 store hit。
   原 WB 保留到真正 ReleaseAck；新 `ownerCapturedMiss` 使用原 enum 的同样两位，
   旧 C 末拍不能再写已复用 MSHR 的 phase。posted 精确事务的旧交接保持不变。
3. 下游准入：Home 根据完整物理行、source、已占用和瞬态预留 directory slot
   判断冲突，不再一律排斥整个 set。distinct dirty C 与瞬态另一目录 way 可共存；
   旧目录仍到完整 C 捕获后才释放，同址未完成写回、真正 E、错误与维护屏障不省略。

第三项改善现有 Sv39 物理请求路径的准入，不改变 MMU/PMP 权限或提前完成 ROB。
没有声称重新设计页表遍历或解除所有年轻 load 的排序限制。

官方 native/GSIM/export 入口已接通；不满足独立准入和已审核 2/2/2 owner 几何的组合
拒绝。FPGA/core/cache 产品字段数为 61/151/22。历史 JSON 合同未修改，桥接要求新字段
明确为 Boolean false；省略、true、数值 0/1 均不能当历史配置。

## 真实 CPU，同容量、同客体、同内存服务

两档均开启前批整行 Grant 和双 origin 预取，仅本批开关不同。
固定双发射、ROB16/PRF48/LSU4、32+32KiB cache、DTLB16/ITLB8、MSHR2、
response2、WB2、共享 DDR4 槽／写2 槽、DMA line4、proof2／early load2。
RV64GC、MAC/CMU/JTAG 等完整板级装配及构造参数回读核验。
byte-identical guest：64KiB COPY，两遍，Sv39 与 Bare；包括真实 final flush。
R32/B32 和原 READY 服务律不变，不是实板 MIG、独立异步时钟或 Linux 吞吐。

| 模式 | 前批周期含 flush | 本批周期含 flush | 前批 MiB/s | 本批 MiB/s | 吞吐提升 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sv39 | 202290 | 196524 | 61.7925 | 63.6055 | +2.9340% |
| Bare | 215747 | 197722 | 57.9382 | 63.2201 | +9.1163% |

相对最初 f1ef886：Sv39 +20.5710%，Bare +31.8488%。MiB/s 是假设 100MHz 的
COPY payload，不是逻辑 R+W、物理测量、峰值带宽或新 10ns 签核。
两档均保持 40984 条退休、同 PC hash 和全部 49157 条回复／完整内存数据核验。

Sv39 ROI 194051→188286 拍，tail8239→8238。请求 fire/valid 比例
48.4168%→54.9283%，cache 请求阻塞 34911→26888 拍。
AR4160、AW2048、R32832、W16384 不变；R/W duty 16.9193/8.4431%→17.4373/8.7017%。
Bare ROI 207810→189789，tail7937→7933；AR4908→4112、R39264→32896，
AW2048/W16384 不变。因此 Bare 收益同时包含调度改变后的冗余读流量减少，不能全部归于少等待。

原始事件的 2014 次 Sv39 dirty STORE PF：捕获到首次 A offer 11→3 拍，
但到真正 Home A fire 仅 11→10。提前排队不意味着可以绕过目录所有权。
Home valid 增至18432/fire4096，其中14336拍阻塞；这不等于吞吐回退，也不应叫已消除下游阻塞。
双 MSHR 重叠 53338→51083 拍；较短寿命下 occupancy 减少不是并行能力退化的证明。

## 仍然存在的瓶颈

Sv39 同时 AXI R/W fire 仍为0；Bare ROI 仅6拍（全 raw trace7拍）。
因此读写串行尚未彻底解决，不能把本批称为总线饱和。
Sv39 每个 A fire→AR 常见2/3拍，4096次 AR→首 R 均32拍；首 R→回填
本批分布为11拍3369次、19拍469次、20拍133次、12拍125次。
11拍中还含外部8beat突发跨度，不能全当内部浪费。
下一目标应拆长尾响应仲裁和后继已授权 load 的发出条件，区分物理目录等待、真实
DDR 延迟、外部传输和内部交接，不靠扩 MSHR 或增加发射宽度。
优先级诊断桶只作观测：refill 桶105102→118891，blocked桶34905→26882；
桶内可能包含并发条件，不能相加当独立因果分解。

## 必要短验证与回执

- 17 项 Scala 参数／前提测试；41 项 CLI／严格历史构造桥接测试通过。
- 两模式各12个实际 cache/home 正例：原9个并发预取／错误／flush／probe场景，
  加 dirty C 背压下另一 way store、同 set 两瞬态 owner、CPU 回复保持及原信用拒绝。
  6 项 full-PA/origin/dirty-byte 负控拒绝；逐字节 backing 和真实 E/ReleaseAck 检查未放宽。
- 新准入诊断2个正例和8个 full-line/source/full-directory/slot-alias/owned-slot 负控通过。
- 实际 CPU4个正例和6个 read/memory/trap 负控通过；ASAN/UBSAN 无错误。
- 最终组件／板级1238个源输入及工具哈希相同并匹配当前源码；模型文件20/160个、
  板级229个 artifacts、所有运行日志和原模型父依赖回执已回读核验。

| `build/gsim/` 下回执 | SHA256 |
| --- | --- |
| `memory-schedule-overlap-20261012-components-r4/receipt.json` | `1b60c2fcafcd7a20da52a5af8a40c036675b60189a00c995e62a8c1187a20bf6` |
| `memory-schedule-overlap-20261012-board-r4/receipt.json` | `cf018a62bd846de09bdf1ce745e860fa62795daf5bf951bea52fbd2f8ccaec99` |

最终审计 `memory-schedule-overlap-20261012-final-audit-r1.json` 同时保存 CLI 输出及
raw AXI／写回到 A 的统计。所有编译输出留在 ignored build，没有纳入源码提交。

保留失败：board-r1 的旧被动 observer 把整 set 当硬阻塞，Bare 因合法不同 way 准入退出；
r2 新增打印字段违反冻结指标 schema；r3 新诊断 getter 在跨 shell 转义时被损坏。
修正仅在宿主诊断，DUT 始终不变；r4 完成最终对照。原 JSON/数据/退休/服务 oracle不改。
ON 的 Home blocked mask 位0表示同完整物理行；保留的 witness `transient_same_set`
仍是几何关系，不能据它单独认定新模式必须阻塞。OFF 保持旧判据。
复用仅用于核验未变硬件／工具／对象后的宿主修正，不跳过真实 CPU 执行或依赖检查。

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/memory_schedule_overlap.py \
  --output build/gsim/memory-schedule-overlap-UNIQUE_TAG --jobs 2
# --components-only：只跑必要组件；--skip-components 本身不构成组件验收。
```

范围限制：本轮仅 COPY 短对照，不是新 READ/WRITE/chase 全量性能回归、完整 ISA/NEMU、
Linux 启动、宽 Grant＋dirty 并发错误全组合或物理时序资源证明。所有开关默认关闭。
