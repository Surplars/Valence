#!/usr/bin/env python3
"""Fail-closed emitted-RTL census; not mapped CDC/RDC/STA qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def audit(rtl, inventory):
    texts = {}
    for path in sorted(rtl.glob('*.sv')):
        for match in re.finditer(r'^module\s+(\w+)\s*\(', path.read_text(), re.M):
            texts[match.group(1)] = path.read_text()
    top = texts['TriSpeedManagedGmac']
    def instances(module):
        return {m.group(2): (m.group(1), m.group(3)) for m in re.finditer(
            r'^[ \t]+('+ '|'.join(re.escape(n) for n in texts)+r')[ \t]+(\w+)[ \t]*\((.*?)\);', texts[module], re.M | re.S)}
    def walk(module, prefix=''):
        found = {}
        for name, (child, _) in instances(module).items():
            path = prefix+name
            found[path] = child
            found.update(walk(child, path+'/'))
        return found
    tree = walk('TriSpeedManagedGmac')
    mailboxes = sorted(p for p,m in tree.items() if re.fullmatch(r'CdcMailbox(?:_\d+)?',m))
    fifos = sorted(p for p,m in tree.items() if re.fullmatch(r'CdcDataFifo(?:_\d+)?',m))
    assert mailboxes==sorted(inventory['mailboxes']), ('mailbox census', mailboxes)
    assert fifos==sorted(inventory['fifos']), ('FIFO census', fifos)
    constraint_path=Path(__file__).resolve().parents[2]/'fpga/zu15eg/trispeed_board_constraints.tcl'
    packet_lists=re.findall(r'foreach path\s+\{([^}]+)\}',constraint_path.read_text())
    packet_lists=[part.replace('\\',' ').split() for part in packet_lists]
    assert packet_lists==[inventory['mailboxes'],inventory['fifos']], 'packet recipe census drift'
    clock_names={'txManaged':'_txManaged_gate_managedClock','rxManaged':'_rxManaged_gate_managedClock',
                 'rawRxClock':'rawRxClock','sourceClock':'sourceClock'}
    reset_names={'txManaged':'_txRelease_resetOut','rxManaged':'_rxRelease_resetOut',
                 'rawRxClock':'_rawRxRelease_resetOut','sourceClock':'_cpuRelease_resetOut'}
    source_blocks={clock:re.search(r'always @\(posedge '+clock+r' or posedge [^)]+\) begin(.*?)end // always',top,re.S).group(1)
                   for clock in ('sourceClock','rawTxClock')}
    launches = {}
    for instance, rule in inventory['registered_level_launches'].items():
        module, connections = instances('TriSpeedManagedGmac')[instance]
        ports = dict(re.findall(r'\.(\w+)\s*\(([^()]*)\)', connections))
        assert module=='CdcLevel' and ports['levelIn'].strip()==rule['source'], instance
        assert re.search(r'\breg\s+'+rule['source']+r'\s*;', top), instance
        assert ports['clockIn'].strip()==clock_names[rule['target_clock']],instance
        assert ports['resetIn'].strip()==reset_names[rule['target_clock']],instance
        assert rule['source']+" <= 1'h0;" in source_blocks[rule['source_clock']],instance
        launches[instance] = ports
    assert top.count('.levelIn  (mediaOpen)')==3
    for retired in inventory['retired_independent_level_chains']:
        assert retired not in instances('TriSpeedManagedGmac'), retired
    for signal, chain in [('txAbort','txLink'),('rxAbort','rxLink'),('rawRxAbort','rawRxOpen')]:
        assert re.search(r'wire\s+'+signal+r'\s*=\s*~_'+chain+r'_sync_levelOut;',top), signal
    assert '.captureEnable     (_rawRxOpen_sync_levelOut)' in top
    assert '.commonReset       (commonReset | _media_io_ingressReset)' in top
    level = texts['CdcLevel']
    assert '(* ASYNC_REG = "TRUE" *)' in level and 'reg [1:0] stages;' in level
    assert "stages <= {stages[0], levelIn};" in level and 'assign levelOut = stages[1];' in level
    assert level.count('stages[0]')==1
    epoch = texts['EthernetMediaTransition']
    assert 'reg         ingressResetSource;' in epoch
    assert "ingressResetSource <= 1'h1;" in epoch
    assert re.search(r'wire\s+io_ingressReset_\d+\s*= ingressResetSource;', epoch)
    assert '$fatal' in epoch and 'media link enabled before rate ACKs' in epoch
    assert all('automatic logic' not in text for text in texts.values())
    tx_type = instances('TriSpeedManagedGmac')['tx'][0]
    return {'status':'PASS_EMITTED_RTL_STRUCTURE_ONLY','mailboxes':mailboxes,'fifos':fifos,
            'level_launches':launches,'epoch_launch':'media/ingressResetSource',
            'two_stage_async_reg_rtl':True,'production_assertions_inline':True,
            'tx_owner_module':tx_type,'registered_source_ff_delta':4,
            'duplicate_synchronizer_ff_delta':-6,'net_logical_ff_delta':-2,
            'mapped_utilization_verified':False,
            'physical_collector_status':inventory['physical_collector_status'],
            'physical_collector_run':False,
            'packet_recipe_sha256':hashlib.sha256(constraint_path.read_bytes()).hexdigest(),
            'rtl_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(rtl.glob('*.sv'))}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rtl',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    inventory=json.loads((Path(__file__).parent/'mac-boundary-cdc-inventory.json').read_text())
    result=audit(args.rtl,inventory)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'])


if __name__=='__main__':main()
