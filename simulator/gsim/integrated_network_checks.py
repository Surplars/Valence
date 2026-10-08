#!/usr/bin/env python3
"""Merged32KiB/cache+four-slot AXI+posted network sanity; no board simulation."""
import datetime
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from run import ROOT,HERE,BUILD,run,setup,test
from data_cache_geometry import verify,module
from frontend_perf import verify_instruction_geometry

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inputs():
    files=list((ROOT/'src/main/scala').rglob('*.scala'))+list((ROOT/'src/test/scala').rglob('*.scala'))
    files += [HERE/'harness'/n for n in ('ethernet_packet_dma.cpp','gmac_shutdown.cpp','gmii_reference.h')]
    files += [Path(__file__),ROOT/'build.mill',HERE/'run.py']
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(files)}
def main():
    name='integrated-network-20261007';out=BUILD/name;out.mkdir(parents=True,exist_ok=False)
    before=inputs();report={'status':'running','source_sha256':before,'checks':{},
        'frozen_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':'merged Scala, managed production FIR geometry, coherent posted DMA, aliased-clock shutdown',
        'board_simulated':False,'physical_cdc_verified':False,'timing_verified':False}
    try:
        h=(HERE/'harness/ethernet_packet_dma.cpp').read_text()
        for anchor in ('ETHERNET_POSTED_RX_PASS','ETHERNET_DMA_FULL_DIRECTORY_PASS','DCACHE_CAPACITY * 128'):
            assert anchor in h,'merged harness lost '+anchor
        run(['mill','-i','IonSoC.test.testOnly','ip.EthernetPacketDmaSpec','ip.GmacRxAdmissionStopSpec',
             'ooo.InstructionCacheCapacitySpec','ooo.DataCacheCapacitySpec'],log=out/'scala.log')
        geom=out/'managed-fir';geom.mkdir()
        run(['mill','-i','IonSoC.test.runMain','ooo.IntegratedNetworkGeometryMain',geom],log=out/'geometry.log')
        fir=(geom/'BoardSocTop.fir').read_text();d=verify(fir,512);i=verify_instruction_geometry(fir,512)
        axi=module(fir,'TileLinkAxi4OutstandingBridge');rx=module(fir,'GmiiFrameRx');dma=module(fir,'EthernetPacketDma')
        assert 'regreset active : UInt<1>[4]' in axi and 'regreset arIssued : UInt<1>[4]' in axi
        assert 'smem buffer : UInt<32>[2048]' in rx and 'reg producer : UInt<2>' not in rx
        assert 'regreset producer : UInt<2>' in rx and 'regreset consumer : UInt<2>' in rx
        assert 'regreset slotOwned : UInt<1>[4]' in dma and '0h403' in dma
        assert '0h100200000' in fir,'2GiB DDR upper bound missing'
        report['geometry']={'fir_sha256':sha(geom/'BoardSocTop.fir'),'instruction':i,'data':d,
            'axi_outstanding_slots':4,'mac_rx_banks':4,'mac_bank_bytes':2048,'posted_rx_slots':4,
            'posted_capabilities':0x403,'ddr_bytes':2147483648}
        gsim,cxx=setup(False)
        for stem,entry,top,harness,params,defines,negatives in [
            ('coherence512','ip.EthernetDmaCoherenceGsimMain','EthernetDmaCoherenceGsim',
             'ethernet_packet_dma.cpp',('512',),{'COHERENT_DMA':1,'DCACHE_CAPACITY':512},
             [('--inject-mismatch','TX independent byte oracle mismatch')]),
            ('shutdown','ip.GmacShutdownGsimMain','GmacShutdownGsim','gmac_shutdown.cpp',(),{},
             [('--inject-'+n,'RX shutdown independent '+m+' oracle mismatch') for n,m in
               [('payload','frame payload'),('status','status-tail'),('memory','memory/canary')]]+
             [('--inject-drain','RX shutdown independent premature-drain oracle mismatch')])]:
            model=test(gsim,cxx,name+'/'+stem,entry,top,harness,parameters=params,defines=defines,sanitizer=True)
            if stem=='coherence512':verify((model/(top+'.fir')).read_text(),512)
            for flag,anchor in negatives:
                p=subprocess.run([str(model/'run'),flag],text=True,capture_output=True,timeout=120,
                    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                (model/(flag[2:]+'.log')).write_text(p.stdout+p.stderr)
                assert p.returncode==1 and anchor in p.stdout+p.stderr,'negative failed '+stem
            report['checks'][stem]={'status':'passed','fir_sha256':sha(model/(top+'.fir')),
                'binary_sha256':sha(model/'run'),'summary':(model/'test.log').read_text().strip(),
                'negative_count':len(negatives)}
        assert inputs()==before,'source drift'
        report['status']='passed'
    except BaseException as error:
        report.update(status='failed',failure=str(error));raise
    finally:(out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print('INTEGRATED_NETWORK_SANITY_PASS receipt='+str(out/'receipt.json'))
if __name__=='__main__':main()
