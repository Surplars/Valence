#!/usr/bin/env python3
"""SHA-bound metadata and fail-closed stack envelope for the GCC14.2 slice2 ROM."""
from pathlib import Path
import re, json, hashlib, struct, argparse

def normalized(path):
    text = path.read_text()
    if path.suffix == '.su':
        return re.sub(r'^.*?/fpga/firmware/', 'fpga/firmware/', text, flags=re.M)
    return re.sub(r'^.*: +file format ', 'ELF: file format ', text, flags=re.M)

def validate_snapshot(full):
    snapshot = json.loads(Path(__file__).with_name('stack_usage_snapshot.json').read_text())
    assert hashlib.sha256((full/'bootrom.bin').read_bytes()).hexdigest() == snapshot['rom_sha256'], 'unqualified ROM'
    actual = {f.name: hashlib.sha256(normalized(f).encode()).hexdigest()
              for f in [full/'disasm.txt', *full.glob('bootrom.elf-*.su')]}
    assert actual == snapshot['normalized_metadata_sha256'], 'unqualified stack/disassembly metadata'

def analyze(full):
    """Semantic gates; caller must validate_snapshot before trusting production results."""
    frames={};qual={}
    canon=lambda n:re.sub(r'\.(constprop|isra)\.\d+$',r'.\1',n)
    for f in full.glob('bootrom.elf-*.su'):
     for l in f.read_text().splitlines():
      label,n,q=l.split('\t');name=canon(label.rsplit(':',1)[1]);assert name not in frames;frames[name]=int(n);qual[name]=q
    frames.update(_start=0,boot_trap=0,run_image=128)
    edges={};indirect={};fn=None
    for line in (full/'disasm.txt').read_text().splitlines():
     m=re.match(r'[0-9a-f]+ <([^>]+)>:',line)
     if m:fn=canon(m[1]);edges.setdefault(fn,set());continue
     m=re.match(r'\s*([0-9a-f]+):\s+([0-9a-f]+)\s+(jalr|jal|jr|j)\s+(.*)',line)
     if not m:continue
     # Decode rd, rather than relying on objdump's implicit ra/zero aliases.
     is_call=((int(m[2],16)>>7)&31)!=0
     target=re.search(r'<([^>+]+)(?:\+[^>]*)?>',m[4])
     if target:
      dst=canon(target[1]);
      # A linked call back into this function is recursion, not an internal jump.
      if dst!=fn or is_call:edges[fn].add(dst)
     else:indirect.setdefault(fn,[]).append(line.strip())
    callbacks=['now','send','recv','store','verify','protocol_stage','received_frame','prepare_verify']
    # Source-scoped overapproximation: all nb_ops targets at every protocol indirect site.
    # No callback target re-enters protocol. run_image switches to independent payload stack.
    allowed={'stage','receive_for','send_frame','udp_receive.constprop','nb_tftp_receive'}
    rom=(full/'bootrom.bin').read_bytes()
    # Three compiler-generated bounded switch jump tables, inspected in linked code.
    assert len(indirect['boot_loop'])==3 and all('jr\ta5' in x for x in indirect['boot_loop'])
    for base,count in [(0x80007dc0,9),(0x80007de4,21),(0x80007e38,21)]:
     for i in range(count):
      target=base+struct.unpack_from('<i',rom,base-0x80000000+4*i)[0]
      assert 0x80001634 <= target < 0x800026ec,hex(target)
    assert set(indirect)-{'run_image','boot_loop'}<=allowed,set(indirect)
    for fn in set(indirect)-{'run_image','boot_loop'}:edges[fn].update(callbacks)
    unknown=set(edges)-set(frames);assert not unknown,unknown
    for fn,targets in edges.items():assert targets<=set(frames),(fn,targets-set(frames))
    assert all(q=='static' for q in qual.values()),qual
    memo={}
    def bound(fn,seen=()):
     assert fn not in seen,('recursion',seen,fn)
     if fn in memo:return memo[fn]
     children=[bound(x,seen+(fn,)) for x in edges[fn]]
     child=max(children,key=lambda x:x[0],default=(0,[]));value=(frames[fn]+child[0],[fn]+child[1]);memo[fn]=value;return value
    roots=['_start','boot_main','boot_recover','boot_loop','board_netboot_pending','nb_tftp_receive','verify','verify_image','tui_progress','firmware_crc_update','monitor_run_diagnostic']
    # Visit every emitted function so even a currently unreachable recursive cycle fails.
    for f in edges:bound(f)
    results={f:{'bytes':bound(f)[0],'path':bound(f)[1]} for f in roots}
    assert all(n>=0 for n in frames.values()), 'negative stack frame'
    assert all(v[0]<=8192 for v in memo.values()), ('stack budget exceeded', {k:v[0] for k,v in memo.items() if v[0]>8192})
    report={'qualification':'static conservative frame-sum envelope, all protocol callback alternatives included; tail-call frames intentionally overcounted','frames':frames,'qualifiers':qual,'edges':{k:sorted(v) for k,v in edges.items()},'indirect_sites':indirect,'callback_overapproximation':callbacks,'bounds':results,'rom_sha256':hashlib.sha256((full/'bootrom.bin').read_bytes()).hexdigest(),'stack_limit':8192,'budget_pass':True,'assembly_boundary':'run_image saves128 bytes then switches sp to __app_stack_top; payload/diagnostic execution excluded; boot_trap resets sp before recovery'}
    return report

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    out = args.out.resolve()
    validate_snapshot(out/'full')
    report = analyze(out/'full')
    (out/'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['bounds'], indent=2))

if __name__ == '__main__':
    main()
