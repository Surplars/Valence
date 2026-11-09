#!/usr/bin/env python3
"""Assemble a small standalone RTL candidate and source overlay, without synthesis."""
import ast, difflib, hashlib, json, shutil, subprocess, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
B=ROOT/'build/mul-capture-20261108'
OUT=ROOT.parent/'Valence-mul-capture-vivado-20261108'
OLD=ROOT.parent/'Valence-optimized-local-vivado-20261108'
OLDZIP=OLD.with_suffix('.zip')
EXPECTED_OLD='335c360ab968c78cb2d05dcc4ff2e933622c6749015bfc6793d39d6fe29dd709'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def cp(p,rel):
 q=OUT/rel;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)

def main():
 assert sha(OLDZIP)==EXPECTED_OLD,'Original ZIP changed'
 result=json.loads((B/'backend/execute-receipt.json').read_text())
 assert result['status']=='PASS_MATCHED_BACKEND_DIRECTED'
 assert len(result['accepted'])==24 and all('load-error' not in x and 'page-fault' not in x for x in result['accepted'])
 assert 'Tests: succeeded 27, failed 0' in (B/'contracts.log').read_text()
 assert json.loads((B/'delta-report.json').read_text())['original_delivered_rtl_byte_identical']
 evidence=OUT/'evidence';assert not evidence.exists();evidence.mkdir()
 for rel in ['contracts.log','emission.log','delta-report.json','compile/compile-receipt.json','compile/compile-source-inputs.json','compile/compile.log','compile/classpath.log']:
  cp(B/rel,'evidence/'+rel)
 for p in sorted((B/'backend').iterdir()):
  if p.is_file() and p.suffix in ('.json','.stdout','.stderr'):cp(p,'evidence/backend/'+p.name)
 paths=['src/test/scala/platform/CombinedA1FabricTimingMain.scala','src/test/scala/ooo/CombinedA1OptimizationSpec.scala','src/test/scala/ooo/MulLoadOperandCaptureBackendGsim.scala','src/test/scala/ooo/MulLoadOperandCaptureBackendGsimMain.scala']
 patches=[];files={}
 for rel in paths:
  old,new=OLD/'source'/rel,ROOT/rel
  assert old.is_file() and new.is_file()
  files[rel]={'before_sha256':sha(old),'after_sha256':sha(new)}
  patches.extend(difflib.unified_diff(old.read_text().splitlines(keepends=True),new.read_text().splitlines(keepends=True),fromfile='a/'+rel,tofile='b/'+rel))
  cp(new,'source-delta/'+rel)
 for p in sorted((ROOT/'delivery/mul-capture-20261108').glob('*')):
  if p.is_file():
   if p.suffix=='.py':ast.parse(p.read_text())
   cp(p,'source-delta/delivery/mul-capture-20261108/'+p.name)
 (OUT/'SOURCE-CHANGES.patch').write_text(''.join(patches))
 source={'base_commit':'e437ba20960a7123ba60e7a91f3dbeec86117b8c','worktree_branch':'integration/mul-load-capture-20261108','committed':False,'original_archive':OLDZIP.name,'original_archive_sha256':EXPECTED_OLD,'overlay_basis':'Original archive source/ directory; not bare e437ba2, because prior W11/W14 integration must remain','scala_delta':files,'production_main_sources_changed_vs_delivered_candidate':False,'local_rtl_requires_source_overlay':False}
 (OUT/'SOURCE-DELTA.json').write_text(json.dumps(source,indent=2,ensure_ascii=False)+'\n')
 report={'status':'READY_FOR_USER_LOCAL_OOC_COMPARISON','part':'xczu15eg-ffvb1156-2-i','candidate':'efficiency4-mul-candidate','control':'Earlier package rtl/efficiency4-candidate, NOT efficiency4-baseline','configuration_delta':{'registeredMulLoadOperandCapture':[False,True]},'scala_contract_tests':{'suites':6,'passed':27,'failed':0},'backend_directed':{'passed_positive':22,'expected_observer_rejections':2,'accepted_case_ids':result['accepted'],'sanitizers':'ASAN/UBSAN; no sanitizer error reported; LSAN disabled','resource_guard':'2 CPUs, sampled process-group RSS <=4GiB; not cgroup enforcement','excluded':['load-error','page-fault','IRQ'],'limits':['Backend with actual decode,DTA,response-buffer,Sv39 service; not full CPU/fabric runtime','Observer negatives mutate host observations, not RTL','No witnessed count8/full-pop, held-LSU or late-reject corner qualification']},'structural':{'reachable_modules':292,'unresolved':0,'old_control_sv_byte_identical':True,'changed_rtl_files':['IntegerBackend.sv'],'W11_compact_immediate':True,'W14_banked_indirect16':True,'fabric_unchanged':True},'historical_only':{'coremark_roi_throughput_change':'about +0.83%','LUT_change':'about +0.60%','source':'original source/docs/a1-mul-registered-load-capture.md','current_combined_measurement':False},'not_run':['Vivado synthesis/implementation','Current combined full CPU/fabric workload','Current CoreMark/throughput/bus-bandwidth','Physical timing/Fmax','Board/MIG/DDR PHY qualification'],'original_archive_unchanged':True}
 (OUT/'VALIDATION.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
 (OUT/'README-先读我.md').write_text('''# efficiency4＋W11/W14＋MUL capture 本地 Vivado 对比包

这个小包在已交付的主候选 efficiency4-candidate 上，仅打开
registeredMulLoadOperandCapture。原 W11 compact immediate、W14 banked indirect16、
efficiency4 CPU 和 Probe-Acquire 总线配置全部保留。原包没有改动。

## 本地直接运行

无需重新编译 Scala，本包已包含全部 292 个 SystemVerilog 模块。
安装 Python 3.10+，在 Vivado 命令行环境中运行：

```text
python rtl-candidate/run_local.py --verify-only
python rtl-candidate/run_local.py --out ../mul-candidate-run-01
```

如果找不到 Vivado，给命令补上 --vivado 和你安装的 vivado/vivado.bat 完整路径。
器件严格为 xczu15eg-ffvb1156-2-i；默认 CPU 10ns、fabric 4ns。
可用 --cpu-period NS --fabric-period NS 修改测试目标。输出目录必须不存在。

对照组用原大包的 **rtl/efficiency4-candidate/run_local.py**，不要用
rtl/efficiency4-baseline，否则会同时比较 W11/W14，不能只看新增 MUL 开关。
两次应使用同一 Vivado 版本、机器设置、CPU/fabric 周期和实现流程。

脚本只执行一次综合、优化、布局、物理优化、布线，保存每阶段 DCP 和报告。
请看 routed_timing_summary.rpt、routed_setup_paths.rpt、routed_hold_paths.rpt、
routed_utilization.rpt、routed_route_status.rpt、DRC/CDC 以及未约束路径。
COMPLETED 仅表示命令结束，不表示时序或 DRC 通过。

## 本次实测验证范围

- 全量 Scala 编译成功；6 个契约套件 27 项测试通过。
- 后端开启/关闭配对：22 个非 fault/IRQ 正例通过，2 个观察器负例按预期拒绝。
  当前公开 ABI、64 位 owner tag、操作数和 registered capture 相位已复核。
  模型全部 5 个 C++ 分片编译链接，使用 ASAN/UBSAN。
- 完整 CPU＋真实 CDC＋真实 fabric RTL 导出和有界模块闭包检查通过。
  新旧候选均为 292 个模块；新候选只改变 IntegerBackend.sv。
- 重新导出的对照 292 个 SV 文件与原包逐字节一致，配置也相同；
  ooc-identity 中只有编译出处不同，因为是本次新工作树重新编译。

没有运行 Vivado、当前整机 CoreMark/CPU＋fabric 工作负载、总线带宽测量或板级验证。
上述后端测试不等于完整 CPU/fabric 行为通过，也没有覆盖 fault/IRQ 或所有仲裁角落。
历史同开关的约 +0.83% CoreMark ROI 吞吐、+0.60% LUT 仅是历史单项结果，
不能作为这次组合的性能、面积或 Fmax 结论。实际时序/面积请以你的本地实现报告为准。

## 源码与证据

本包为了小而不重复原大包全部源码；source-delta/ 是相对原大包 source/ 的源码叠加。
如需重建：先复制原大包 source/ 到一个新目录，按 SOURCE-DELTA.json 的 before_sha256
核对四个 Scala 文件，再把 source-delta/ 中的文件按相同相对路径复制进去。
SOURCE-CHANGES.patch 提供这四个文件的可审阅差异；完整变化后的文件也都在。
不要直接叠到裸 e437ba2 上，因为原 W11/W14 集成应保留。
不需要修改原包，也不需要源码叠加才能运行本包已经导出的 RTL。

新工作树分支为 integration/mul-load-capture-20261108，修改尚未提交或推送。
源码重建应生成真实 compile receipt，再用 CombinedA1FabricTimingMain 的
新增模式 efficiency4-mul-candidate 导出。不能把云端 receipt 当作本地新编译证据。
当前契约测试、GSIM 命令和逐项日志、源码绑定和差异检查在 evidence/。
VALIDATION.json 汇总本次结果与未验证事项，MANIFEST.sha256.json 绑定全部文件。

## 边界

这是 OOC CPU＋真实总线候选，不是可直接上板的完整工程或 bitstream。
MIG、DDR 电气接口、PHY、板级时钟/复位/引脚等未包括，接口仍真实暴露。
CPU/fabric 跨域没有随意设 false path 或异步 clock-group 切断；外部 IO 延迟未指定。
因此必须区分核内路径、CDC 和未约束板级边界，不能把汇总 WNS 直接当作整板 Fmax。
详见 rtl-candidate/README.md。I1、H/V 及此前未接纳的实验没有混入。
''')
 files=sorted(p for p in OUT.rglob('*') if p.is_file())
 assert not any(p.is_symlink() for p in files)
 (OUT/'MANIFEST.sha256.json').write_text(json.dumps({p.relative_to(OUT).as_posix():sha(p) for p in files},indent=2,ensure_ascii=False)+'\n')
 target=OUT.with_suffix('.zip');assert not target.exists()
 with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for p in sorted(OUT.rglob('*')):
   if p.is_file():z.write(p,OUT.name+'/'+p.relative_to(OUT).as_posix())
 with zipfile.ZipFile(target) as z:
  assert z.testzip() is None
  manifest=json.loads(z.read(OUT.name+'/MANIFEST.sha256.json'))
  for rel,digest in manifest.items():assert hashlib.sha256(z.read(OUT.name+'/'+rel)).hexdigest()==digest
 assert sha(OLDZIP)==EXPECTED_OLD
 print(json.dumps({'file':str(target),'bytes':target.stat().st_size,'sha256':sha(target),'file_count':len(manifest)+1,'old_archive_unchanged':True}))
if __name__=='__main__':main()
