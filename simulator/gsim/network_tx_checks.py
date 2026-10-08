#!/usr/bin/env python3
"""Focused optional posted TX candidate. Preflight only without --build-run."""
import argparse,datetime,hashlib,json,os,re,subprocess
from pathlib import Path
from run import ROOT,HERE,BUILD,setup,test,run

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def sources():
    paths=list((ROOT/'src/main/scala').rglob('*.scala'))+list((ROOT/'src/test/scala/ip').glob('*.scala'))
    paths += [Path(__file__),HERE/'run.py',ROOT/'build.mill',HERE/'config/toolchain.json']
    paths += [HERE/'harness'/x for x in ('ethernet_packet_dma.cpp','ethernet_tx_queue_events.cpp','self_gmac_dma.cpp','gmii_reference.h')]
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}
def rows():
    rows=[]
    for tx in (0,1,4):
        rows.append((f'packet-tx{tx}','ip.EthernetPacketDmaGsimMain','EthernetPacketDma','ethernet_packet_dma.cpp',
            (4,4,2147483648,tx),{'TX_POSTED_SLOTS':tx,'DMA_RAM_BYTES':'2147483648ULL'},'TX independent byte oracle mismatch'))
    rows += [('events','ip.EthernetTxQueueEventGsimMain','EthernetTxQueueEventGsim','ethernet_tx_queue_events.cpp',(),{},'queue independent owner/result mismatch'),
        ('framed-tx4','ip.SelfGmacDmaGsimMain','SelfGmacDmaGsim','self_gmac_dma.cpp',(4,),{'TX_POSTED_SLOTS':4},'GMAC DMA independent TX wire oracle mismatch'),
        ('coherent-tx4','ip.EthernetDmaCoherenceGsimMain','EthernetDmaCoherenceGsim','ethernet_packet_dma.cpp',(512,4),{'COHERENT_DMA':1,'DCACHE_CAPACITY':512,'TX_POSTED_SLOTS':4},'TX independent byte oracle mismatch')]
    return rows

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);ap.add_argument('--build-run',action='store_true');ap.add_argument('--resume',action='store_true');a=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.tag):ap.error('unsafe tag')
    if a.resume and not a.build_run:ap.error('resume requires build-run')
    if not a.build_run:print(json.dumps({'status':'prepared_not_executed','models':[r[0] for r in rows()],'source_files':len(sources())},indent=2));return
    name='network-tx-'+a.tag;out=BUILD/name;before=sources()
    if a.resume:
        report=json.loads((out/'receipt.json').read_text());assert report['source_sha256']==before
        if report['status']=='passed':raise RuntimeError('already passed; refusing repeat')
        (out/('receipt-before-resume-'+datetime.datetime.now(datetime.timezone.utc).strftime('%H%M%S')+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        if 'failure' in report:report.setdefault('prior_failures',[]).append(report.pop('failure'))
    else:
        out.mkdir(parents=True,exist_ok=False);report={'source_sha256':before,'checks':{},'source_frozen_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'kernel_build':False,'board_verified':False,'physical_cdc_verified':False,'throughput_verified':False}
    report['status']='running'
    def checkpoint():(out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    checkpoint()
    try:
        if not report.get('scala_passed'):
            run(['mill','-i','IonSoC.test.testOnly','ip.NetworkDmaConfigSpec','ip.EthernetPacketDmaSpec'],log=out/'scala.log')
            report['scala_passed']=True;checkpoint()
        gsim,cxx=setup(False)
        for stem,entry,top,harness,parameters,defines,marker in rows():
            model=out/stem
            if stem in report['checks']:
                prior=report['checks'][stem];assert sha(model/(top+'.fir'))==prior['fir_sha256'] and sha(model/'run')==prior['binary_sha256'];continue
            model=test(gsim,cxx,name+'/'+stem,entry,top,harness,parameters=tuple(map(str,parameters)),defines=defines,sanitizer=True)
            negative=subprocess.run([model/'run','--inject-mismatch'],capture_output=True,text=True,timeout=120,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
            (model/'negative.log').write_text(negative.stdout+negative.stderr)
            assert negative.returncode==1 and marker in negative.stdout+negative.stderr,stem
            report['checks'][stem]={'status':'passed','parameters':parameters,'defines':defines,'fir_sha256':sha(model/(top+'.fir')),'binary_sha256':sha(model/'run'),'negative_oracle':marker,'summary':(model/'test.log').read_text()};checkpoint()
        assert before==sources(),'source drift';report['status']='passed'
    except BaseException as e:report.update(status='failed',failure=str(e));raise
    finally:checkpoint()
    print('NETWORK_TX_HARDWARE_PASS receipt='+str(out/'receipt.json'))
if __name__=='__main__':main()
