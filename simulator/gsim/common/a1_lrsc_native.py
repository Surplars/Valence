#!/usr/bin/env python3
"""Bounded actual LR/SC plus DMA invalidation, reusing a source-bound DMA fixture."""
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
    ap.add_argument('--model-dir', required=True, type=Path)
    args = ap.parse_args(); out = args.out.resolve()
    if out.exists(): ap.error('fresh evidence directory required')
    out.mkdir(parents=True)
    paths = sorted((ROOT / 'src/main/scala').rglob('*.scala')) + [ROOT / p for p in
        ['src/test/scala/platform/CommonA1DmaProbeMain.scala', 'src/test/scala/platform/CommonA1RuntimeCdcMain.scala',
         'simulator/gsim/common/a1_lrsc_epoch.S','simulator/gsim/common/a1_lrsc_epoch_tb.sv',
         'simulator/gsim/common/a1_runtime_native.py','simulator/gsim/common/i1_msi_epoch_native.py',
         'simulator/gsim/common/i1_runtime_network.ld']] + [Path(__file__)]
    hashes = lambda: {str(p.relative_to(ROOT)):b.sha(p) for p in paths}
    r = dict(status='RUNNING',source_sha256=hashes(),tools={},cases=[],board_verified=False,
             scope='LR/SC real fabric reservation and DMA invalidation before trap; no physical gate/rate test')
    try:
        a1.custom_guest(out,HERE/'a1_lrsc_epoch.S',256,
            ['lr_plain','sc_plain','plain_value','lr_park','sc_park','park_value','lr_dma','sc_dma','dma_start','dma_source','dma_value','dma_guard','irq_claim','irq_count','irq_mret','guest_done','guest_fail'],r)
        t={n:b.tool(v) for n,v in [('iverilog','iverilog'),('vvp','vvp')]}
        r['tools'].update(b.tool_hashes(t))
        def run(cmd,name,seconds=180,negative=False,banner=None):
            rc,log=b.run(cmd,out,name,seconds,r)
            if negative:
                if rc==0 or 'independent' not in log: raise RuntimeError('negative oracle failed: '+name)
            elif rc or (banner and banner not in log): raise RuntimeError('failed: '+name+' '+log[-1200:])
            return log
        model=args.model_dir.resolve(); prior_path=model/'receipt.json'
        prior=json.loads(prior_path.read_text())
        if prior['status']!='PASS_A1_DMA_PROBE_NATIVE': raise RuntimeError('passing real DMA fixture required')
        for name,sha in prior['source_sha256'].items():
            if b.sha(ROOT/name)!=sha: raise RuntimeError('fixture source drift: '+name)
        for name,sha in prior['artifacts'].items():
            if b.sha(model/name)!=sha: raise RuntimeError('fixture artifact drift: '+name)
        fixture_frozen={str(model/name):sha for name,sha in prior['artifacts'].items()}
        fixture_frozen[str(prior_path)]=b.sha(prior_path)
        r['reused_fixture_receipt_sha256']=b.sha(prior_path)
        r['reused_model_artifacts']=prior['artifacts']
        run([t['iverilog'],'-g2012','-I',out,'-s','a1_lrsc_epoch_tb','-o',out/'test.vvp',model/'lowered.v',HERE/'a1_lrsc_epoch_tb.sv'],'compile')
        r['compiled_binary_sha256']=b.sha(out/'test.vvp')
        for name,extra in [('positive',[]),('dma-without-second-park',['+dma-no-park']),('negative-dma-sc',['+dma-no-park','+wrong-dma-sc']),('negative-sc',['+wrong-sc']),('negative-data',['+wrong-data']),('negative-irq',['+wrong-irq'])]:
            run([t['vvp'],'-i',out/'test.vvp','+rom='+str(out/'guest.hex'),*extra],name,
                negative=name.startswith('negative'),banner='A1_LRSC_PASS')
        if b.sha(out/'test.vvp')!=r['compiled_binary_sha256']: raise RuntimeError('compiled executable drift during run')
        if any(b.sha(Path(name))!=sha for name,sha in fixture_frozen.items()): raise RuntimeError('reused fixture artifact drift during run')
        if any(b.sha(out/name)!=sha for name,sha in r['guest']['artifacts'].items()): raise RuntimeError('generated guest/include drift during run')
        if hashes()!=r['source_sha256']: raise RuntimeError('source drift')
        r['artifacts']={str(p.relative_to(out)):b.sha(p) for p in out.rglob('*') if p.is_file()}
        r['status']='PASS_A1_LRSC_NATIVE'
    except Exception as exc:
        r['status']='FAIL';r['error']=str(exc);raise
    finally:(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
if __name__=='__main__':main()
