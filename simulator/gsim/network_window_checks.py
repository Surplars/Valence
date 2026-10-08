#!/usr/bin/env python3
"""Focused posted-RX/window hardware checks; no CPU/Linux/physical-board run."""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path
from run import ROOT, HERE, BUILD, setup, test, run

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inputs():
    paths = list((ROOT/'src/main/scala').rglob('*.scala'))
    paths += list((ROOT/'src/test/scala/ip').glob('*.scala'))
    paths += [HERE/'harness'/n for n in ('ethernet_packet_dma.cpp','self_gmac_frames.cpp',
              'self_gmac_dma.cpp','gmac_shutdown.cpp','gmii_reference.h')]
    paths += [Path(__file__), HERE/'run.py', ROOT/'build.mill', HERE/'config/toolchain.json']
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--tag',required=True)
    args=ap.parse_args()
    if not args.tag.replace('-','').isalnum(): ap.error('unsafe tag')
    name='network-window-'+args.tag; output=BUILD/name; output.mkdir(parents=True,exist_ok=False)
    before=inputs(); report={'status':'running','source_sha256':before,'checks':{},
        'source_frozen_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':'bounded MAC banks, posted RX DMA, coherent fabric, aliased-clock shutdown; no CPU or Linux',
        'physical_cdc_verified':False,'board_verified':False,'routed_timing_verified':False}
    try:
        run(['mill','-i','IonSoC.test.testOnly','ip.EthernetPacketDmaSpec','ip.GmacRxAdmissionStopSpec',
             'ip.SelfGmacParamsSpec'],log=output/'scala.log')
        gsim,cxx=setup(False)
        rows=[('packet','ip.EthernetPacketDmaGsimMain','EthernetPacketDma','ethernet_packet_dma.cpp',{},
               [('--inject-mismatch','TX independent byte oracle mismatch')]),
              ('coherence','ip.EthernetDmaCoherenceGsimMain','EthernetDmaCoherenceGsim','ethernet_packet_dma.cpp',
               {'COHERENT_DMA':1},[('--inject-mismatch','TX independent byte oracle mismatch')]),
              ('frames','ip.SelfGmacFramesGsimMain','SelfGmacFramesGsim','self_gmac_frames.cpp',{},
               [('--inject-mismatch','GMII TX independent wire oracle mismatch')]),
              ('framed-dma','ip.SelfGmacDmaGsimMain','SelfGmacDmaGsim','self_gmac_dma.cpp',{},
               [('--inject-mismatch','GMAC DMA independent TX wire oracle mismatch')]),
              ('shutdown','ip.GmacShutdownGsimMain','GmacShutdownGsim','gmac_shutdown.cpp',{},
               [('--inject-'+n,'RX shutdown independent '+m+' oracle mismatch') for n,m in
                [('payload','frame payload'),('status','status-tail'),('memory','memory/canary')]]+
               [('--inject-drain','RX shutdown independent premature-drain oracle mismatch')])]
        for stem,entry,top,harness,defines,negatives in rows:
            model=test(gsim,cxx,name+'/'+stem,entry,top,harness,defines=defines,sanitizer=True)
            for flag,marker in negatives:
                bad=subprocess.run([str(model/'run'),flag],capture_output=True,text=True,timeout=120,
                    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                (model/(flag[2:]+'.log')).write_text(bad.stdout+bad.stderr)
                if bad.returncode!=1 or marker not in bad.stdout+bad.stderr:
                    raise RuntimeError('independent negative oracle failed: '+stem+' '+flag)
            report['checks'][stem]={'status':'passed','fir_sha256':sha(model/(top+'.fir')),
                'binary_sha256':sha(model/'run'),'negative_oracles':len(negatives),
                'summary':(model/'test.log').read_text().strip()}
            (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
        if inputs()!=before: raise RuntimeError('source drift')
        report['status']='passed'
    except BaseException as error:
        report.update(status='failed',failure=str(error)); raise
    finally:
        (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print('NETWORK_WINDOW_HARDWARE_PASS receipt='+str(output/'receipt.json'))
if __name__=='__main__': main()
