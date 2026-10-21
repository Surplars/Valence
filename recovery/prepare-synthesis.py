"""Stage exactly three existing IP DCPs; leave old project and IP untouched."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, sys

p=argparse.ArgumentParser()
for name in ('project-source','emission','destination'):
    p.add_argument('--'+name,required=True,type=Path)
a=p.parse_args()
repo=Path(__file__).resolve().parents[1]
old=a.project_source.resolve(); emission=a.emission.resolve(); dest=a.destination.resolve()
assert old.is_dir() and (old/'common_board.xpr').is_file()
assert not dest.exists(), 'Preserve any prior build directory'
meta=json.loads((emission/'emission-profile.json').read_text())
expected={'cpu':'i1','cpuClockHz':300000000,'fabricClockHz':250000000,'ddrUiHz':250000000,
          'uartHz':50000000,'aonHz':50000000,'romBytes':131072,'hardwareClocks':True,
          'vivadoMemories':True,'programmableRom':False}
assert all(meta.get(k)==v for k,v in expected.items()) and int(meta['timebaseHz'])==250000000
for name,h in meta['artifacts'].items():
    source=Path(name)
    assert source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest()==h, name
sys.path.insert(0,str(repo/'fpga/common'))
import board_inputs
board_inputs.port_check((emission/'CommonMachinePlatform.sv').read_text(),
                       (repo/'fpga/common/soc_top_common_ddr.sv').read_text())
rtl=sorted(f for f in emission.rglob('*.sv') if 'verification' not in f.relative_to(emission).parts)
rtl+= [repo/n for n in board_inputs.BOARD_RTL]
assert len(rtl)==len(set(rtl)) and all(f.is_file() for f in rtl)
ip_inputs=[]
for name in ('ddr4_0','clk_wiz_common','blk_mem_gen_0'):
    rel=Path('common_board.gen/sources_1/ip')/name/(name+'.dcp')
    stub=old/rel.parent/(name+'_stub.v')
    assert (old/rel).is_file() and stub.is_file()
    ip_inputs.append((name,old/rel,stub))
dest.mkdir(parents=True)
(dest/'ip').mkdir()
for name,source,stub in ip_inputs:
    copied=dest/'ip'/(name+'.dcp')
    shutil.copy2(source,copied)
    assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(copied.read_bytes()).digest()
def q(value):
    s=str(value).replace('\\','/')
    assert not any(c in s for c in '{}\r\n')
    return '{'+s+'}'
constraints=[repo/'fpga/common/board_pins.xdc',repo/'fpga/zu15eg/pl_ddr4_pins.xdc']
assert all(f.is_file() for f in constraints)
config='\n'.join([
    'set recovery(output) '+q(dest),
    'set recovery(repo) '+q(repo),
    'set recovery(ip_inputs) [list '+' '.join('[list '+q(name)+' '+q(dest/'ip'/(name+'.dcp'))+' '+q(stub)+']' for name,source,stub in ip_inputs)+']',
    'set recovery(rtl) [list '+' '.join(q(f) for f in rtl)+']',
    'set recovery(xdc) [list '+' '.join(q(f) for f in constraints)+']'])+'\n'
(dest/'synthesis-config.tcl').write_text(config)
receipt={'name':'recovery-r1-source-idle','production_source_commit':'28e2abd0b0a9b893de62ff49a25b1ce0d3694ead',
         'emission_profile_sha256':hashlib.sha256((emission/'emission-profile.json').read_bytes()).hexdigest(),
         'configuration':expected,'timebaseHz':250000000,'readonly_ip_project_source':str(old),
         'copied_files':{str(dest/'ip'/(name+'.dcp')):hashlib.sha256(source.read_bytes()).hexdigest() for name,source,stub in ip_inputs},
         'readonly_stub_sha256':{str(stub):hashlib.sha256(stub.read_bytes()).hexdigest() for name,source,stub in ip_inputs},
         'rtl_sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in rtl},
         'constraints_sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in constraints},
         'ip_regenerated':False,'physical_qualified':False,'place_route_permitted':False}
(dest/'synthesis-inputs.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'prepared':str(dest),'rtl_sources':len(rtl),'cached_ip_checkpoints_verified':3,
                  'source_commit':receipt['production_source_commit'],'place_route_permitted':False},indent=2))
