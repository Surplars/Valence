#!/usr/bin/env python3
"""Bounded actual memory-copy DMA -> dirty A1 cache probe -> park/IRQ acceptance."""
import argparse
import importlib.util
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('a1_tools', HERE / 'a1_runtime_native.py')
a1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(a1)
b = a1.base


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--sv2v', required=True)
    args = ap.parse_args(); out = args.out.resolve()
    if out.exists(): ap.error('fresh evidence directory required')
    out.mkdir(parents=True)
    paths = sorted((ROOT / 'src/main/scala').rglob('*.scala')) + [ROOT / p for p in
        ['src/test/scala/platform/CommonA1DmaProbeMain.scala', 'src/test/scala/platform/CommonA1RuntimeCdcMain.scala',
         'simulator/gsim/common/a1_dma_probe.S','simulator/gsim/common/a1_dma_probe_tb.sv',
         'simulator/gsim/common/a1_runtime_native.py','simulator/gsim/common/i1_msi_epoch_native.py',
         'simulator/gsim/common/i1_runtime_network.ld']] + [Path(__file__)]
    hashes = lambda: {str(p.relative_to(ROOT)):b.sha(p) for p in paths}
    r = dict(status='RUNNING',source_sha256=hashes(),tools={},cases=[],board_verified=False,
             scope='real memory-copy DMA and Home probes, not Ethernet packet DMA; no physical gate/rate test')
    try:
        a1.custom_guest(out,HERE/'a1_dma_probe.S',256,
            ['dma_start','dma_value','dma_guard','irq_claim','irq_count','irq_mret','guest_done','guest_fail'],r)
        t={n:b.tool(v) for n,v in [('mill','mill'),('sv2v',args.sv2v),('iverilog','iverilog'),('vvp','vvp')]}
        r['tools'].update(b.tool_hashes(t))
        def run(cmd,name,seconds=180,negative=False,banner=None):
            rc,log=b.run(cmd,out,name,seconds,r)
            if negative:
                if rc==0 or 'independent' not in log: raise RuntimeError('negative oracle failed: '+name)
            elif rc or (banner and banner not in log): raise RuntimeError('failed: '+name+' '+log[-1200:])
            return log
        run([t['mill'],'-i','IonSoC.test.runMain','platform.CommonA1DmaProbeMain',out/'rtl'],'emit',600)
        files=sorted((out/'rtl').glob('*.sv')); original='\n'.join(p.read_text()for p in files)
        lowered=run([t['sv2v'],'--exclude=SeverityTask',*files],'lower')
        for token in ('$fatal','$error'):
            if not original.count(token) or original.count(token)!=lowered.count(token):
                raise RuntimeError('severity preservation failure')
        (out/'lowered.v').write_text(lowered)
        run([t['iverilog'],'-g2012','-I',out,'-s','a1_dma_probe_tb','-o',out/'test.vvp',out/'lowered.v',HERE/'a1_dma_probe_tb.sv'],'compile')
        for name,extra in [('positive',[]),('negative-data',['+wrong-data']),('negative-irq',['+wrong-irq'])]:
            run([t['vvp'],'-i',out/'test.vvp','+rom='+str(out/'guest.hex'),*extra],name,
                negative=name.startswith('negative'),banner='A1_DMA_PROBE_PASS')
        if hashes()!=r['source_sha256']: raise RuntimeError('source drift')
        r['artifacts']={str(p.relative_to(out)):b.sha(p) for p in out.rglob('*') if p.is_file()}
        r['status']='PASS_A1_DMA_PROBE_NATIVE'
    except Exception as exc:
        r['status']='FAIL';r['error']=str(exc);raise
    finally:(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
if __name__=='__main__':main()
