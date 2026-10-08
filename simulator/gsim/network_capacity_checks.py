#!/usr/bin/env python3
"""Focused network capacity proof. Preflight only unless --build-run is explicit."""
import argparse
import datetime
import json
import os
import subprocess
from pathlib import Path
from network_window_checks import inputs, sha
from run import ROOT, HERE, BUILD, setup, test, run


def sources():
    result = inputs()
    for path in (Path(__file__), ROOT/'src/test/scala/ooo/EthernetTimingMain.scala',
                 ROOT/'src/test/scala/ooo/ManagedBoardSocMain.scala'):
        result[str(path.relative_to(ROOT))] = sha(path)
    return result


def rows():
    result = []
    for slots, credits in ((1, 1), (4, 4), (16, 2)):
        result.append((f'packet-{slots}-{credits}', 'ip.EthernetPacketDmaGsimMain',
            'EthernetPacketDma', 'ethernet_packet_dma.cpp', (slots, credits, 2147483648),
            {'RX_POSTED_SLOTS': slots, 'DMA_MEMORY_CREDITS': credits, 'DMA_RAM_BYTES': '2147483648ULL'},
            '--inject-mismatch', 'TX independent byte oracle mismatch'))
    for slots in (1, 16):
        result.append((f'mac-{slots}', 'ip.SelfGmacFramesGsimMain', 'SelfGmacFramesGsim',
            'self_gmac_frames.cpp', (slots,), {'RX_FRAME_SLOTS': slots},
            '--inject-mismatch', 'GMII TX independent wire oracle mismatch'))
    result += [('coherent', 'ip.EthernetDmaCoherenceGsimMain', 'EthernetDmaCoherenceGsim',
        'ethernet_packet_dma.cpp', (), {'COHERENT_DMA': 1},
        '--inject-mismatch', 'TX independent byte oracle mismatch'),
        ('shutdown', 'ip.GmacShutdownGsimMain', 'GmacShutdownGsim', 'gmac_shutdown.cpp', (), {},
        '--inject-drain', 'RX shutdown independent premature-drain oracle mismatch')]
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--build-run', action='store_true')
    args = ap.parse_args()
    if not args.tag.replace('-', '').isalnum(): ap.error('unsafe tag')
    if not args.build_run:
        print(json.dumps({'status': 'preflight-only', 'models': [r[0] for r in rows()],
            'source_files': len(sources()), 'heavy_execution_started': False}, indent=2))
        return
    name = 'network-capacity-' + args.tag
    output = BUILD/name
    output.mkdir(parents=True, exist_ok=False)
    before = sources()
    receipt = {'status': 'running', 'source_sha256': before, 'checks': {},
        'source_frozen_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'selected packet-owner/memory-credit and MAC-bank configurations, coherent DMA and shutdown',
        'all_configurations_tested': False, 'kernel_build': False, 'physical_cdc_verified': False,
        'board_verified': False, 'routed_timing_verified': False}
    try:
        run(['mill', '-i', 'IonSoC.test.testOnly', 'ip.NetworkDmaConfigSpec',
             'ip.EthernetPacketDmaSpec', 'ip.GmacRxAdmissionStopSpec', 'ip.SelfGmacParamsSpec'],
            log=output/'scala.log')
        gsim, cxx = setup(False)
        for stem, entry, top, harness, parameters, defines, flag, marker in rows():
            model = test(gsim, cxx, name+'/'+stem, entry, top, harness,
                parameters=tuple(map(str, parameters)), defines=defines, sanitizer=True)
            bad = subprocess.run([str(model/'run'), flag], capture_output=True, text=True,
                timeout=120, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            (model/'negative.log').write_text(bad.stdout+bad.stderr)
            if bad.returncode != 1 or marker not in bad.stdout+bad.stderr:
                raise RuntimeError('negative oracle failed: '+stem)
            receipt['checks'][stem] = {'status': 'passed', 'parameters': parameters, 'defines': defines,
                'fir_sha256': sha(model/(top+'.fir')), 'binary_sha256': sha(model/'run'),
                'negative_oracle': marker, 'summary': (model/'test.log').read_text().strip()}
            (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
        if before != sources(): raise RuntimeError('source drift')
        receipt['status'] = 'passed'
    except BaseException as error:
        receipt.update(status='failed', failure=str(error))
        raise
    finally:
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('NETWORK_CAPACITY_HARDWARE_PASS receipt='+str(output/'receipt.json'))


if __name__ == '__main__':
    main()
