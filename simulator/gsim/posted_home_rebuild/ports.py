"""Mechanical scalar ABI for real-home fixture; no expected semantics."""
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location('posted_cache_scalar_ports', Path(__file__).resolve().parent.parent / 'posted_cache_rebuild/ports.py')
_cache = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cache)
REQUEST, PROOF, MEMBER, EVENT, OWNER, TOKEN, RESERVATION = (_cache.REQUEST, _cache.PROOF, _cache.MEMBER, _cache.EVENT, _cache.OWNER, _cache.TOKEN, _cache.RESERVATION)
AB, C, D = _cache.AB, _cache.C, _cache.D
ADDRESS = ['id', 'addr', 'len', 'size', 'burst', 'lock', 'cache', 'prot', 'qos']
CHANNELS = {'a': AB, 'b': AB, 'c': C, 'd': D, 'e': ['sink']}
def monitor(ch, field): return 'mon' + ch.upper() + field[0].upper() + field[1:]
INPUTS = ([n for n in _cache.INPUTS if not n.startswith(('tl.', 'downstream.'))] +
          ['dma.request.valid'] + ['dma.request.bits.' + n for n in REQUEST] + ['dma.response.ready'] +
          ['holdAcquire', 'holdGrantAck', 'holdReleaseAck', 'holdCoherentC'] +
          ['ddrAxi.aw.ready', 'ddrAxi.w.ready', 'ddrAxi.ar.ready', 'ddrAxi.r.valid', 'ddrAxi.b.valid'] +
          ['ddrAxi.r.bits.' + n for n in ['id', 'data', 'resp', 'last']] +
          ['ddrAxi.b.bits.' + n for n in ['id', 'resp']])
OUTPUTS = ([n for n in _cache.OUTPUTS if not n.startswith(('tl.', 'downstream.'))] +
           ['dma.request.ready', 'dma.response.valid'] + ['dma.response.bits.' + n for n in _cache.RESPONSE] +
           ['cacheFlushDone', 'homeDrainDone'] +
           [monitor(ch,n) for ch, fields in CHANNELS.items() for n in ['valid', 'ready', *fields]] +
           ['ddrAxi.aw.valid', 'ddrAxi.w.valid', 'ddrAxi.ar.valid', 'ddrAxi.r.ready', 'ddrAxi.b.ready'] +
           ['ddrAxi.' + ch + '.bits.' + n for ch in ['ar','aw'] for n in ADDRESS] +
           ['ddrAxi.w.bits.' + n for n in ['data','strb','last']])

def method(prefix, name):
    return prefix + ('reset' if name == 'reset' else 'io$$' + name.replace('.', '$$'))


def emit_driver(path):
    setters = '\n'.join('setters.emplace("' + n + '", [&](uint64_t v) { d.' + method('set_', n) + '(v); });' for n in INPUTS)
    getters = '\n'.join('std::cout << ",\\"' + n + '\\":" << uint64_t(d.' + method('get_', n) + '());' for n in OUTPUTS)
    Path(path).write_text('''#include "PostedStoreHomeGsim.h"
#include <cstdint>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
int main() { try {
 SPostedStoreHomeGsim d;
 std::unordered_map<std::string, std::function<void(uint64_t)>> setters;
SETTERS
 for (auto& [name, set] : setters) { (void)name; set(0); }
 std::string line; unsigned cycle = 0;
 while (std::getline(std::cin, line)) {
  if (line == "quit") break;
  if (++cycle > 50000) throw std::runtime_error("cycle budget");
  std::istringstream input(line); std::string item;
  while (input >> item) {
   const auto p = item.find('=');
   if (p == std::string::npos) throw std::runtime_error("malformed input");
   const auto name = item.substr(0,p); size_t used = 0;
   if (!setters.count(name)) throw std::runtime_error("unknown input: " + name);
   const auto value = item.substr(p+1); auto v = std::stoull(value,&used,0);
   if (used != value.size()) throw std::runtime_error("trailing input");
   setters.at(name)(v);
  }
  d.step(); std::cout << "{\\"cycle\\":" << cycle;
GETTERS
  std::cout << "}\\n" << std::flush;
 }
 return 0;
} catch (const std::exception& e) { std::cerr << "POSTED_HOME_DRIVER_FAIL " << e.what() << "\\n"; return 1; } }
'''.replace('SETTERS', setters).replace('GETTERS', getters))
