"""Strict inputs; no historical runtime qualification is inherited."""
import copy,hashlib,importlib.util,json,os,re,shutil,subprocess,sys,shlex,urllib.parse
from pathlib import Path
HERE=Path(__file__).resolve().parent;BASE=HERE.parent;ROOT=HERE/'source';ORIGINAL=BASE/'posted-head-offer-bandwidth-pair-r1'
TOOL_RECEIPT=BASE/'toolchain/tool-receipt.json';TOOL_SHA='09a2c9129ebe50f34e3be6529b83e100c74c00f883e675fb5846a2d4f9e5a037'
SOURCE_HEAD='6f975c14edd0ce01cc248b71893d85634fedf408';PRODUCTION_HEAD='aaaf6d701a3b47cb610b6b8b4775487b89b7a5b9'
FLAGS=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
DEFINES=['-DBACKEND_OWNER_COUNT=4','-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0','-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DDDR_MULTI_ID_MODEL=1','-DDDR_READ_CREDITS=8','-DDDR_READ_LATENCY=32','-DDDR_READ_BEAT_GAP=1','-DBOARD_CYCLE_LIMIT=24000000ULL','-DSTORE_PF_ON=1','-DPOSTED_STORE_ON=1']
CASES={0:dict(mode=0,op='READ',row_prefix=[0,0,0,1024,8],result=6863348401280905216,read_bytes=65536,write_bytes=0),19:dict(mode=0,op='COPY',row_prefix=[0,1,2,16384,1],result=0,read_bytes=131072,write_bytes=131072),21:dict(mode=1,op='COPY',row_prefix=[1,1,2,16384,1],result=0,read_bytes=131072,write_bytes=131072)}
SANITIZERS=r'ERROR: AddressSanitizer|runtime error:|SUMMARY: UndefinedBehaviorSanitizer|LeakSanitizer|Sanitizer:DEADLYSIGNAL'
ENV_KEYS=('PATH','JAVA_HOME','JAVA_TOOL_OPTIONS','COURSIER_CACHE','COURSIER_REPOSITORIES','CHISEL_FIRTOOL_PATH','FIRTOOL','LD_LIBRARY_PATH','GSIM_CXX','VALENCE_CLOUD_ENV','VALENCE_GSIM_SOURCE','XDG_CACHE_HOME','CPATH','LIBRARY_PATH','CXXFLAGS','CPPFLAGS','LDFLAGS')
def require(x,m):
 if not x:raise RuntimeError(m)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def read(p):return json.loads(Path(p).read_text())
def exact(a,b):return json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True)
def save(p,d,fresh=False):
 p=Path(p)
 if fresh:
  with p.open('x')as f:json.dump(d,f,indent=2,sort_keys=True);f.write('\n')
 else:
  t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n');t.replace(p)
def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
def source():
 require(git('rev-parse','HEAD')==SOURCE_HEAD,'Board source HEAD differs')
 require(not git('status','--porcelain'),'Board source not clean')
 require(git('ls-tree','-r',PRODUCTION_HEAD,'src/main')==git('ls-tree','-r','HEAD','src/main'),'production blobs differ from canonical freeze aaaf6d7')
 require(not any('registeredStoreDataForwarding' in (ROOT/n).read_text() for n in git('ls-files','src/main').splitlines() if n.endswith('.scala')),'rs2 production delta present')
 subprocess.run([sys.executable,'-B',str(HERE/'prepare_sources.py'),'--check'],check=True,stdout=subprocess.DEVNULL)
 files={n:sha(ROOT/n)for n in git('ls-files').splitlines()if (ROOT/n).is_file()}
 return dict(head=SOURCE_HEAD,tree=git('rev-parse','HEAD^{tree}'),production_head=PRODUCTION_HEAD,production_equal=True,files=files)
def environment():
 values={k:os.environ.get(k,'')for k in ENV_KEYS}
 # Tool calls receive ephemeral executor-proxy endpoints. Preserve that exact
 # route and validate every Java proxy property against the supplied endpoint;
 # normalize only these already-validated transport endpoint strings.
 proxy=urllib.parse.urlsplit(os.environ.get('HTTPS_PROXY',''))
 require(proxy.scheme=='http'and proxy.hostname and proxy.port and not proxy.username and not proxy.password,'expected credential-free executor HTTP proxy')
 tokens=shlex.split(values['JAVA_TOOL_OPTIONS']);mapping={'-Dhttps.proxyHost':proxy.hostname,'-Dhttp.proxyHost':proxy.hostname,'-Dhttps.proxyPort':str(proxy.port),'-Dhttp.proxyPort':str(proxy.port)}
 for name,want in mapping.items():
  matches=[x for x in tokens if x.startswith(name+'=')]
  require(matches==[name+'='+want],'Java proxy must use current supplied executor endpoint '+name)
 require([x for x in tokens if x.startswith('-Dhttp.nonProxyHosts=')]==['-Dhttp.nonProxyHosts=localhost|127.*'],'unexpected proxy bypass')
 normalized=[x.split('=',1)[0]+'=<current-executor-proxy>'if x.split('=',1)[0]in mapping else x for x in tokens]
 values['JAVA_TOOL_OPTIONS']=json.dumps(normalized,separators=(',',':'))
 return {k:hashlib.sha256(v.encode()).hexdigest()for k,v in values.items()}
ENVIRONMENT_NORMALIZATION='Only four Java HTTP(S) proxy host/port values are normalized after exact validation against the current executor-provided HTTPS_PROXY; every other JVM option, ordering and environment value remains exact.' 
def tools():
 require(sha(TOOL_RECEIPT)==TOOL_SHA,'tool receipt changed');t=read(TOOL_RECEIPT)
 for k,v in t['files'].items():require(sha(v['path'])==v['sha256'],'pinned tool changed '+k)
 require(shutil.which('mill')==t['files']['mill_wrapper']['path'],'activate pinned Mill')
 require(os.environ.get('GSIM_CXX')==t['files']['clang']['path'],'activate pinned clang')
 require(str(Path(os.environ.get('CHISEL_FIRTOOL_PATH','/missing'))/'firtool')==t['files']['firtool']['path'],'activate pinned firtool')
 require(os.environ.get('COURSIER_CACHE') and os.environ.get('JAVA_TOOL_OPTIONS'),'recovered environment absent')
 return t
MODEL_INPUTS=('contract.py','model.py','canonical-flags.json','expected-profile-off.json','canonical_model_adapter.hpp','prepare_sources.py')
def model_inputs():return {n:sha(HERE/n)for n in MODEL_INPUTS}
def expected_profile(side):
 require(side in ('off','on'),'unknown canonical-overlap treatment');p=read(HERE/'expected-profile-off.json')
 p['core']['canonicalVirtualStoreOverlap']=side=='on';p['developmentTreatment']['canonicalVirtualStoreOverlap']=side=='on';return p
def profile(p,side):
 require(exact(p,expected_profile(side)),'complete actual profile differs: '+side)
 require(p['core']['registeredLoadIssueForwarding']is True,'existing registered load forwarding disabled')
 require('registeredStoreDataForwarding'not in p['core'] and 'registeredStoreDataForwarding'not in p['profile'],'rs2 candidate accidentally folded in')
 return {'side':side,'profile_fields':len(p['profile']),'core_fields':len(p['core']),'only_treatment':'canonicalVirtualStoreOverlap'}
def pair_profiles(off,on):
 profile(off,'off');profile(on,'on');normal=copy.deepcopy(on)
 for n in ('core','developmentTreatment'):normal[n]['canonicalVirtualStoreOverlap']=False
 require(exact(off,normal),'unexpected A/B full-profile delta')
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def audit(report,p,side):
 require(report['schema']=='posted-board-actual-parameters-v1' and report['mode']==side and report['experiment']=='canonical-virtual-store-overlap' and report['hardwareMutation']is False and report['allActualParametersEqualExpected']is True,'wrong final-constructor audit')
 require(exact(report['developmentTreatment'],p['developmentTreatment']),'development treatment audit mismatch')
 require(exact(report['entryProfile'],p['profile'])and exact(report['expectedCore'],p['core']),'audit profile mismatch')
 require(report['canonicalOptions']==sorted(read(HERE/'canonical-flags.json')[side]),'actual options drift')
 paths={'top.board','top.board.platform','top.board.platform.core','top.board.platform.core.core','top.board.platform.core.core.core','top.board.platform.core.core.core.backend'}
 require({r['instancePath']for r in report['coreParameters']}==paths and len(report['coreParameters'])==6,'core constructor coverage')
 for key,profile_key,num in [('coreParameters','core',6),('ddrParameters','ddr',2),('cacheConcurrency','cache',3)]:
  require(len(report[key])==num,'parameter coverage '+key)
  for row in report[key]:require(exact(row['values'],p[profile_key]),'actual constructor differs '+row['instancePath'])
 require(report['cacheTileLinkParameters'],'missing TL constructor')
 for row in report['cacheTileLinkParameters']:require(exact(row['values'],dict(addrWidth=64,dataWidth=64,sourceBits=3,sinkBits=1,sizeBits=3)),'actual TL geometry differs')
def header_and_fir(folder,side):
 p=read(folder/'profile.json');profile(p,side);audit(read(folder/'actual-parameters.json'),p,side)
 v=load('canonical_fir_profile',ROOT/'simulator/gsim/posted_board_lineage/profile_check.py');structure=v.verify_fir(folder/'BoardSocGsim.fir')
 census=load('canonical_model_census',ROOT/'simulator/gsim/posted_cpu/verify_model.py')
 f=(folder/'BoardSocGsim.fir').read_text();c=census.verify_posted_model(f,True)
 parallel=census._module(f,'ParallelLoadStoreUnit');require(len(re.findall(r'inst slots_\d+ of LoadStoreUnit',parallel))==4,'four actual LSU owners absent')
 require('node _startEviction_T_4 = and(UInt<1>(0h1), UInt<1>(0h0))' in f and 'node startEviction = and(_startEviction_T_3, _startEviction_T_6)' in f,'read-only legacy eviction alias not source-proven')
 h=(folder/'BoardSocGsim.h').read_text()
 for s in ('get_lineage$$alloc0$$valid','get_lineage$$cache$$proof$$valid','get_lineage$$owner$$accepted$$valid','get_lineage$$owner$$drained$$valid','get_lineage$$tlC$$bits$$source'):require(s in h,'lineage scalar getter missing '+s)
 for s in ('board$platform$coherentHome$ownedLines[4]','board$platform$physicalData_walkers_0$tlb$$valid[8]','board$platform$physicalData_walkers_1$tlb$$valid[16]'):require(s in h,'actual header geometry missing '+s)
 getters=sorted(set(re.findall(r'd\.(get_canonical[^ (]+)\(', (HERE/'canonical_model_adapter.hpp').read_text())))
 require(getters and all((name+'(')in h for name in getters),'actual header lacks requested canonical scalar ABI')
 trace_module=census._module(f,'BoardSocGsim')
 require('canonical' in trace_module,'canonical trace top missing')
 if side=='off':require('module CanonicalStoreTracker'not in f,'OFF unexpectedly retains canonical tracker')
 else:require('module CanonicalStoreTracker' in f,'ON canonical tracker absent')
 return dict(full_profile=p,structure=structure,census=c,actual_parameters=read(folder/'actual-parameters.json'))
def guest():
 pins={'guest.bin':'3af27dccda6acd677bb01fdad4d240ffee2f9af1c1fb4181a71c43ff2087a810','guest.elf':'bdedff34099ab1195df390b5fb1964667cc8819474b3f219a6e7b350a9f77396','kernel.bin':'f5a152ca2779ee567a9f864bc29d524bd91a935dab0323f21353ae9c9af0fec5'}
 for n,h in pins.items():require(sha(HERE/n)==sha(ORIGINAL/n)==h,'immutable guest drift '+n)
 require((HERE/'guest.bin').stat().st_size==6104 and (HERE/'kernel.bin').stat().st_size==1472,'guest/kernel size drift')
 b=(HERE/'guest.bin').read_bytes();require(hashlib.sha256(b[0xbcc:0xbcc+1472]).hexdigest()==pins['kernel.bin'],'embedded kernel drift')
 for off,word in [(0xc24,0xc01028f3),(0x1068,0xc0102773),(0xb0,0x13),(0xa0,0x13)]:require(int.from_bytes(b[off:off+4],'little')==word,'READ marker instruction drift')
 require(sha(HERE/'worksets_symbols.h')==sha(ORIGINAL/'worksets_symbols.h'),'original guest symbols changed')
 return pins
