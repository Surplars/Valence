#!/usr/bin/env python3
"""Bounded host-only independent checks for passive cache telemetry accounting."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
HERE = Path(__file__).resolve().parent
headers = [HERE/'harness/frontend_observer.h', HERE/'harness/performance_observer.h']
names = sorted(set(re.findall(r'get_[A-Za-z0-9_$]+', '\n'.join(p.read_text() for p in headers))))
stub = '\n'.join(f'uint64_t {n}() {{return values["{n}"];}}' for n in names)
source = '''#include <cstdint>
#include <iostream>
#include <map>
#include <string>
#include <cassert>
struct SBoardSocGsim { std::map<std::string,uint64_t> values;
'''+stub+'\n};\n#include "'+str(headers[0])+'''"
int main(){
 SBoardSocGsim d; CacheCounts c;
 // Independent sequence: demand miss at cycle0, reply at41, simultaneous next hit,
 // and that hit's reply at42. This tests boundary ownership without DUT code.
 d.values["get_perfCacheEvents"]=(1<<1)|(1<<12);c.sample(d);
 d.values["get_perfCacheEvents"]=0;for(unsigned i=1;i<41;++i)c.sample(d);
 d.values["get_perfCacheEvents"]=(1<<11)|(1<<0)|(1<<12);c.sample(d);
 d.values["get_perfCacheEvents"]=(1<<11);c.sample(d);
 assert(c.latencyCount[1]==1&&c.latencySum[1]==41&&c.latencyHist[1][41]==1);
 assert(c.latencyCount[0]==1&&c.latencySum[0]==1&&!c.pending);
 // ROI may begin with a pre-existing response, which is explicitly censored.
 CacheCounts boundary;boundary.sample(d);assert(boundary.orphanReplies==1);
 bool rejected=false;d.values["get_perfCacheEvents"]=(1<<12);
 try{CacheCounts bad;bad.sample(d);}catch(const std::runtime_error&){rejected=true;}
 assert(rejected);
 rejected=false;d.values["get_perfCacheEvents"]=(1<<0)|(1<<12);
 try{CacheCounts bad;bad.sample(d);bad.sample(d);}catch(const std::runtime_error&){rejected=true;}
 assert(rejected);std::cout<<"PASS passive cache observer ownership, latency, boundary, negative controls\\n";
}
'''
with tempfile.TemporaryDirectory(prefix='frontend-observer-') as temp:
    path=Path(temp); (path/'test.cpp').write_text(source)
    subprocess.run([os.environ.get('GSIM_CXX','clang++'),'-std=c++20','-O1','-g','-fsanitize=address,undefined',str(path/'test.cpp'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
