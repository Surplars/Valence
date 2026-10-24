# A1 fetch S1：生产 transaction/context 通道与精确零周期差异

2026-10-24。基线 commit：`aaa2af4fee09abc42e0b80c9baa1cc5e00897f6c`。

## 结论

**S1已真实接入生产registered translation path，新增寄存级为0，仍只有一个owner。**
同一套九场景、相同host输入与service law下，所有结果字段逐值一致，不只是平均值或ROM/RAM两项周期。
新的token/context边界、冻结旧adapter逐拍对照、独立PMP/byte oracle及严格负例全部通过。

这一步完成的是模块与所有权接口解耦，**不是**多owner供给、II=1、8B/cycle或高性能前端整体完成。
仍未测此改造的综合面积、时序或300MHz；也不把供给fixture的结果称为core IPC。

## 生产改变与保持项

- `InstructionTranslationAdapter` 的公共`InstructionPort`不变；仅registered-heads分支改为真实实例化
  `InstructionFetchTransactionBoundary`和`RegisteredInstructionTranslationEngine`。
- typed command原子运输VA、word mask、SATP、SUM/MXR、privilege与generation token。
  engine捕获的是原virtual acceptance边沿，result返回engine保存的token。
- 原FSM、translation/physical request与response、ready-only dead-payload写入、PMP first-offer采样、
  identity/zero mask、跨页second-only结果放置及turnover覆盖优先级保持。
- credit直到匹配旧owner的公共response被接管才释放；同拍新allocation优先于旧release。
- SynchronousFetch、request buffer、I-cache、ITLB/PTW、RVC/window/reservoir均未因S1改变。
  原九场景fixture、driver、byte oracle、host test和入口五文件保持原字节。

## 九场景：逐字段完全相同

| 场景 | 完成指令 | 基线work cycles | S1 work cycles |
|---|---:|---:|---:|
| rom32 | 128 | 580 | 580 |
| ram32 | 128 | 332 | 332 |
| ram_rvc_boundary | 256 | 644 | 644 |
| ram_backpressure | 256 | 688 | 688 |
| rom_redirect_old_reply | 128 | 1034 | 1034 |
| sv39_cross_page | 128 | 433 | 433 |
| sv39_second_parcel_fault | 1 | 59 | 59 |
| pmp_second_parcel_fault | 1 | 25 | 25 |
| rom_second_parcel_fault | 1 | 22 | 22 |

严格comparison status：`PASS_S1_ALL_SCENARIO_FIELDS_IDENTICAL`。
每个scenario的differences为空，包含consume/fault、instruction/Get hash、virtual/physical请求与latency总和、
直方图、miss/hit和drain。ROI work/consume统计与含drain的事务统计不混算。
四个原PC/data/tval/source observation负例及host ASan/UBSan oracle仍通过。

配置仍为Selected实际前端链，physical I-cache缩为8 lines，Common A1为512 lines；
fabric由原固定host TL/PTE服务替代。这个小cache不能用于声称Common容量性能，host latency也不是板级ROM时序。

## 新边界与adapter独立覆盖

### Boundary event-history oracle

生产默认64-bit与独立2-bit测试参数分别完成256接受、256完成：

- 161次旧response与新command同拍。
- 254拍held result；94拍held command。
- 94次旧result释放但engine commandReady=false，后续保留原token/context接受。
- 1710拍无新request credit。
- latency 1/2/7/17各64笔。
- 2-bit版本64次完整drain后合法generation回绕；64-bit版本无回绕。

四个负例都要求特定诊断而不是任何非零退出：

| 注入 | 必须观察的拒绝 | 实际退出 |
|---|---|---:|
| wrong generation | 生产`fetch transaction result generation mismatch` | -6 |
| duplicate/no owner | 生产`fetch transaction result has no owner` | -6 |
| held data mutation | 独立payload/fault oracle mismatch | 1 |
| turnover context mutation | 独立accepted/offered context oracle mismatch | 1 |

前两项是实际错误输入触发硬件assert；后两项是host/observation mutation，不能混称生产RTL mutant验证。

### 冻结peer逐拍比较，独立oracle另验语义

- exact Selected stream：20接受/20完成，19次同拍turnover，10次translation、14次physical request。
- generic two-word跨页stream：20接受/20完成，turnover关闭，0次同拍；18次translation、17次physical request。
  实际持续offer覆盖old reply释放拍新command受阻、下一拍接受的live-context窗口。
- four-word isolated：100 cases，含同拍translation request/reply、partial/zero mask、fault、PMP首次offer采样、
  held permission/response；这是adapter通用宽度测试，不是四发射CPU验证。
- 三个实例各自的独立response-oracle mutation被精确诊断拒绝。

冻结旧implementation只证明cycle comparison，不作为ISA或fault唯一oracle。
PMP byte-range及accepted-owner history继续由原未改host独立计算。

## 成本、上下文与token的边界

`matches → response.valid/result.ready → releasing → credit → command.valid/request.ready`
是新增组合路径，包含64-bit equality。新增token计数器及两侧保存token也有潜在面积成本。
综合是否合并同事件寄存器未知；**零额外cycle不等于零Fmax/面积成本**。

64位是保守诊断选择，不是单owner所需的最短编码，也不是沿用ROB tag就能证明必要。
小tag合法wrap依赖恰好一个terminal result和复用前完全drain；任意迟到重复消息跨wrap后的永久区分不在合同内。
它不是streamEpoch或PMP版本，不改变现有redirect/权限context drain责任。

command不提前快照live VM。caller必须在held offer期间稳定VA/mask/context；关闭turnover时这个约束尤其可见。
S1保留原fire采样，不能为了方便独立engine-ready而偷偷提前改变架构context接受时间。

## 失败与修复记录

首轮增量compile失败：机械字符串替换把两处子module的`checker.io.privilege`
误替换成`checker.io.command.bits.privilege`。无硬件模型从该失败输入运行。
修复仅恢复这两个checker端口；r2重新freeze与增量compile后通过，compile receipt无source drift。

首轮compile结束后，新paired fixture补入generic stream的no-turnover覆盖，作为r2新输入记录，
不把它冒充r1冻结输入。原九场景输入未变化。独立review随后改为只映射顶层`io`，并单独核对子module连接。

## 可复现证据

- `build/a1-s1-20261024-r1/scala-compile.log`：保留首轮失败。
- `build/a1-s1-20261024-r2/compile-receipt.json`：exit0、source_drift为空。
- `build/a1-s1-20261024-r2/source-manifest.json`及`scala-inputs.tar.gz`：实际r2冻结输入。
- `build/gsim/a1-fetch-supply-s1-20261024-r2-comparison/receipt.json`：九场景全字段一致及模型hash。
- `build/gsim/a1-fetch-transaction-s1-20261024-r2/receipt.json`：5个模型、7个负例、源/工具hash。
- `docs/a1-fetch-stage1-independent-review.md`：独立静态审查与失败修复边界。

入口：

```sh
source /workspace/shared/valence-a1-toolchain-r1/env.sh
GSIM_CXX=clang++-19 python3 simulator/gsim/fetch_transaction_boundary.py \
  --gsim simulator/build/gsim-src/build/gsim/gsim --tag FRESH_TRANSACTION_TAG
```

旧九场景运行与strict all-field比较由`simulator/gsim/a1_frontend_stage.py`协调，使用保存基线而不重跑基线。
复跑必须使用新的tag并遵守统一freeze/增量compile顺序，不为了单项修改重复全回归。

## 下一阶段

当前瓶颈没有消失：supply单pending、translation单owner、cache单demand仍在。
下一步是在实际typed通道上拆开context admission、translation/permission与ordered return owner，
先保证有限credit与精确drain，再分步使调用者真正并发，并对每个新增级重复同流量的整链供给比较。
不能仅把单pending改成计数，也不能只做一个未接入生产的N-owner模块后称前端完成。
