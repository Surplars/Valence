#!/usr/bin/env python3
"""Focused single-clock RAM endpoint test; does not validate TCK CDC or OpenOCD."""
import hashlib, json, os, subprocess
import run as common

def main():
    sources=[common.ROOT/'src/main/scala/ip/debug/JtagRamLoader.scala',
             common.ROOT/'src/main/scala/core/ooo/DmaRegisterDataAdapter.scala',
             common.ROOT/'src/test/scala/debug/JtagRamLoaderSpec.scala',
             common.ROOT/'src/test/scala/debug/JtagDmaLaneGsimMain.scala',
             common.HERE/'harness/jtag_ram_loader.cpp',common.HERE/'harness/jtag_dma_lane.cpp']
    hashes=lambda:{str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    before=hashes()
    gsim,cxx=common.setup(False)
    target=common.test(gsim,cxx,'jtag-ram-loader','debug.JtagRamLoaderGsimMain',
        'JtagRamLoader','jtag_ram_loader.cpp',timeout=120)
    assert 'JTAG_RAM_LOADER_PASS' in (target/'test.log').read_text()
    r=subprocess.run([target/'run','--corrupt-readback'],capture_output=True,text=True,timeout=120,
                     env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
    log=r.stdout+r.stderr;(target/'negative-readback.log').write_text(log)
    assert r.returncode!=0 and 'independent RAM readback oracle mismatch' in log
    lane=common.test(gsim,cxx,'jtag-dma-lanes','debug.JtagDmaLaneGsimMain',
        'DmaRegisterDataAdapter','jtag_dma_lane.cpp',timeout=120)
    assert 'JTAG_DMA_LANES_PASS' in (lane/'test.log').read_text()
    assert hashes()==before,'source changed during test'
    (target/'receipt.json').write_text(json.dumps(dict(status='PASS',
        scope='single-clock endpoint, DMI/register protocol and independent byte-array memory oracle',
        negative_readback='detected', source_sha256=before, dma_lane_cases=64, cdc='NOT_RUN', openocd='NOT_RUN', board='NOT_RUN'),indent=2)+'\n')
if __name__=='__main__': main()
