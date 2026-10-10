"""Only scalar fixture ABI; no DUT semantics or expected bytes."""
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location('posted_owner_scalar_ports', Path(__file__).resolve().parent.parent / 'posted_merge_rebuild/ports.py')
_owner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_owner)
REQUEST, PROOF, MEMBER, EVENT, OWNER, TOKEN, RESERVATION = (_owner.REQUEST, _owner.PROOF, _owner.MEMBER, _owner.EVENT, _owner.OWNER, _owner.TOKEN, _owner.RESERVATION)

RESPONSE = ['data', 'error', 'pageFault']
AB = ['opcode', 'param', 'size', 'source', 'address', 'mask', 'data', 'corrupt']
C = ['opcode', 'param', 'size', 'source', 'address', 'data', 'corrupt']
D = ['opcode', 'param', 'size', 'source', 'sink', 'denied', 'data', 'corrupt']
WB = EVENT + ['ticket.slot'] + ['ticket.owner.' + n for n in OWNER]
FALLBACK = ['token.' + n for n in TOKEN] + ['responseTicket']
INPUTS = (['reset', 'upstream.request.valid'] + ['upstream.request.bits.' + n for n in REQUEST] +
          ['upstream.response.ready', 'downstream.request.ready', 'downstream.response.valid'] +
          ['downstream.response.bits.' + n for n in RESPONSE] + ['tl.a.ready', 'tl.c.ready', 'tl.e.ready', 'tl.b.valid'] +
          ['tl.b.bits.' + n for n in AB] + ['tl.d.valid'] + ['tl.d.bits.' + n for n in D] +
          ['posted.requestProof.valid'] + ['posted.requestProof.bits.' + n for n in PROOF] +
          ['posted.contextEpoch', 'posted.seal', 'posted.endEpisode', 'flushRequest'])
OUTPUTS = (['upstream.request.ready', 'upstream.response.valid'] + ['upstream.response.bits.' + n for n in RESPONSE] +
           ['downstream.request.valid'] + ['downstream.request.bits.' + n for n in REQUEST] + ['downstream.response.ready'] +
           ['tl.a.valid'] + ['tl.a.bits.' + n for n in AB] + ['tl.c.valid'] + ['tl.c.bits.' + n for n in C] +
           ['tl.e.valid', 'tl.e.bits.sink', 'tl.b.ready', 'tl.d.ready', 'posted.busy', 'posted.episodeActive',
            'flushDone', 'hit', 'miss', 'prefetchBusy', 'accepted.valid', 'accepted.bits.newLine'] +
           ['accepted.bits.member.' + n for n in MEMBER] + ['accepted.bits.reservation.' + n for n in RESERVATION] +
           ['refillValid'] + ['refillEvent.' + n for n in EVENT] + ['refillError', 'installedValid'] +
           ['installedEvent.' + n for n in EVENT] +
           sum(([label + '.valid'] + [label + '.bits.' + n for n in fields]
                for label, fields in [('acknowledged', MEMBER), ('acquired', EVENT), ('drained', MEMBER),
                                      ('released', EVENT), ('attached', WB), ('sent', WB), ('completed', WB),
                                      ('cancelled', EVENT), ('fallback', FALLBACK), ('fallbackAck', FALLBACK)]), []) +
           ['failed', 'mshrMask', 'postedMask', 'responseMask', 'responseCompleteMask', 'wbMask',
            'lineWrite', 'lineWritePosted', 'lineWriteAddress'] +
           ['refillWord' + str(i) for i in range(8)] + ['installWord' + str(i) for i in range(8)])


PF_FIELDS = ['candidate', 'candidateStore', 'allocated', 'allocatedStore', 'useful', 'usefulStore', 'allocatedAddress', 'allocatedSlot', 'demandAlloc', 'demandAllocSlot', 'demandAllocAddress', 'mshrLiveMask', 'mshrPrefetchMask', 'mshrStoreMask', 'refill', 'refillSlot', 'refillAddress', 'refillPrefetch', 'refillError', 'wbCapture', 'wbCaptureSlot', 'wbCaptureMshr', 'wbCaptureAddress', 'wbCaptureDirty', 'wbCaptureDirect', 'wbCaptureFromMiss', 'wbCapturePrefetch', 'wbLiveMask', 'wbSentMask', 'wbPrefetchMask', 'wbAddress0', 'wbAddress1', 'wbMshr0', 'wbMshr1', 'acquireResponsePending', 'queuedEvictWanted', 'responseFull', 'cValid', 'cReady', 'cOpcode', 'cParam', 'cSize', 'cData', 'dData', 'dDenied', 'dCorrupt']
PREFETCH_FIELDS = ['candidate', 'allocated', 'useful', 'error', 'missOwners', 'releaseOwners']
OUTPUTS += ["pfObservation." + n for n in PF_FIELDS] + ["prefetch." + n for n in PREFETCH_FIELDS]

def method(prefix, name):
    return prefix + ('reset' if name == 'reset' else 'io$$' + name.replace('.', '$$'))


def emit_driver(path):
    setters = '\n'.join('setters.emplace("' + n + '", [&](uint64_t v) { d.' + method('set_', n) + '(v); });' for n in INPUTS)
    getters = '\n'.join('std::cout << ",\\"' + n + '\\":" << uint64_t(d.' + method('get_', n) + '());' for n in OUTPUTS)
    Path(path).write_text('''#include "PostedPrefetchCoexistGsim.h"
#include <cstdint>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
int main() { try {
 SPostedPrefetchCoexistGsim d;
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
} catch (const std::exception& e) { std::cerr << "POSTED_PREFETCH_DRIVER_FAIL " << e.what() << "\\n"; return 1; } }
'''.replace('SETTERS', setters).replace('GETTERS', getters))
