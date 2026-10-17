"""Declared scalar fixture ABI; no port is wider than uint64_t.

This lists external port names only, not DUT internals or expected behavior.
"""
from pathlib import Path

REQUEST = ['atomic', 'atomicOp', 'address', 'write', 'size', 'data', 'mask', 'virtualized',
           'precheckedLoad', 'translationEpoch', 'prefetchNextAllowed', 'uncached']
TOKEN = ['index', 'tag']
OWNER = ['slot', 'generation']
CONTEXT = ['owner.' + n for n in OWNER] + ['cohortRoot.' + n for n in OWNER] + ['epoch', 'lineAddress']
RESERVATION = ['mshr', 'set', 'way', 'victimValid', 'victimDirty', 'victimAddress']
PROOF = ['token.' + n for n in TOKEN] + ['epoch', 'address', 'data', 'mask', 'size', 'headAuthorized',
         'physicalPmpAllowed', 'originalPhysical', 'integerOrigin', 'legacyPostedAccepted', 'finalChecked']
OFFER = ['request.' + n for n in REQUEST] + ['proof.' + n for n in PROOF]
MEMBER = ['token.' + n for n in TOKEN] + ['context.' + n for n in CONTEXT] + ['responseTicket']
EVENT = ['context.' + n for n in CONTEXT] + ['reservation.' + n for n in RESERVATION]
INPUTS = (['reset', 'enq.valid'] + ['enq.bits.' + n for n in OFFER] +
          ['cacheAdmission.responseAvailable', 'cacheAdmission.targetAbsent',
           'cacheAdmission.reservationValid', 'cacheAdmission.responseTicket'] +
          ['cacheAdmission.reservation.' + n for n in RESERVATION] +
          ['contextEpoch', 'seal', 'endEpisode', 'acknowledged.valid'] +
          ['acknowledged.bits.' + n for n in MEMBER] + ['event.' + n for n in EVENT] +
          ['acquireValid', 'refillValid', 'refillError', 'refillToT', 'refillHasData', 'refillGrantAcked'] +
          ['refillWord' + str(n) for n in range(8)] + ['writebackTicket.slot'] +
          ['writebackTicket.owner.' + n for n in OWNER] +
          ['writebackAttach', 'writebackSent', 'writebackComplete', 'victimCancel', 'installReady',
           'drainReady', 'releaseReady', 'fallbackReady', 'fallbackAcknowledged.valid'] +
          ['fallbackAcknowledged.bits.token.' + n for n in TOKEN] + ['fallbackAcknowledged.bits.responseTicket'])
OUTPUTS = (['enq.ready', 'eligible', 'canJoin'] + ['admission.' + n for n in CONTEXT] +
           ['accepted.valid', 'accepted.bits.newLine'] + ['accepted.bits.member.' + n for n in MEMBER] +
           ['accepted.bits.reservation.' + n for n in RESERVATION] + ['refillReady', 'installValid'] +
           ['installEvent.' + n for n in EVENT] + ['installWord' + str(n) for n in range(8)] +
           ['drained.valid'] + ['drained.bits.' + n for n in MEMBER] + ['released.valid'] +
           ['released.bits.' + n for n in EVENT] + ['fallback.valid'] + ['fallback.bits.' + n for n in OFFER] +
           ['busy', 'exhausted', 'failed', 'stores', 'lines', 'episodeActive'])
PULSES = ['enq.valid', 'seal', 'endEpisode', 'acknowledged.valid', 'acquireValid', 'refillValid',
          'writebackAttach', 'writebackSent', 'writebackComplete', 'victimCancel', 'installReady',
          'drainReady', 'releaseReady', 'fallbackReady', 'fallbackAcknowledged.valid']


def method(prefix, name):
    return prefix + ('reset' if name == 'reset' else 'io$$' + name.replace('.', '$$'))


def emit_driver(destination):
    """Mechanical port access; authored tests and independent byte oracle live in Python."""
    setters = '\n'.join('    setters.emplace("' + name + '", [&](uint64_t v) { d.' +
                        method('set_', name) + '(v); });' for name in INPUTS)
    getters = '\n'.join('            std::cout << ",\\"' + name + '\\":" << uint64_t(d.' +
                        method('get_', name) + '());' for name in OUTPUTS)
    source = '''#include "PostedStoreMergeGsim.h"
#include <cstdint>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
int main() {
  try {
    SPostedStoreMergeGsim d;
    std::unordered_map<std::string, std::function<void(uint64_t)>> setters;
SETTERS
    for (auto& [name, set] : setters) { (void)name; set(0); }
    std::string line; unsigned cycle = 0;
    while (std::getline(std::cin, line)) {
      if (line == "quit") break;
      if (++cycle > 20000) throw std::runtime_error("component cycle budget exceeded");
      std::istringstream input(line); std::string item;
      while (input >> item) {
        const auto equal = item.find('=');
        if (equal == std::string::npos) throw std::runtime_error("malformed driver input");
        const auto name = item.substr(0, equal);
        if (!setters.count(name)) throw std::runtime_error("unknown driver input: " + name);
        size_t consumed = 0; const auto text = item.substr(equal + 1);
        const auto value = std::stoull(text, &consumed, 0);
        if (consumed != text.size()) throw std::runtime_error("trailing input data");
        setters.at(name)(value);
      }
      d.step();
      std::cout << "{\\"cycle\\":" << cycle;
GETTERS
      std::cout << "}\\n" << std::flush;
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "POSTED_OWNER_DRIVER_FAIL " << error.what() << "\\n";
    return 1;
  }
}
'''.replace('SETTERS', setters).replace('GETTERS', getters)
    Path(destination).write_text(source)
