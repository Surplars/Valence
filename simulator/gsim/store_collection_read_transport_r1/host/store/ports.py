from pathlib import Path
REQUEST=['returnHandle','atomic','atomicOp','address','write','size','data','mask','virtualized','precheckedLoad','translationEpoch','prefetchNextAllowed','uncached']
RESPONSE=['returnHandle','data','error','pageFault']
PROOF=['token.index','token.tag','epoch','address','data','mask','size','headAuthorized','physicalPmpAllowed','originalPhysical','integerOrigin','legacyPostedAccepted','finalChecked']
ORIGIN=['token.index','token.tag','epoch']
FROZEN=['address','physicalAddress','size','mask']
def fields(prefix,names):return [prefix+'.'+n for n in names]
def valid(prefix,names):return [prefix+'.valid']+fields(prefix+'.bits',names)
INPUTS=['reset','upstream.request.valid','upstream.response.ready','memory.request.ready','memory.response.valid','fastStore.valid','upstreamCollectionHeadRead','externalPostedBusy']+fields('upstream.request.bits',REQUEST)+fields('memory.response.bits',RESPONSE)+fields('fastStore.bits',REQUEST[1:])+valid('upstreamProof',PROOF)+valid('fastProof',PROOF)+valid('upstreamCanonicalStoreOrigin',ORIGIN)+valid('upstreamFrozenStoreProof',FROZEN)
OUTPUTS=['upstream.request.ready','upstream.response.valid','memory.request.valid','memory.response.ready','fastStore.ready','memoryCollectionHeadRead','busy','forwarded','requestStallCause']+fields('upstream.response.bits',RESPONSE)+fields('memory.request.bits',REQUEST)+valid('memoryProof',PROOF)+valid('memoryCanonicalStoreOrigin',ORIGIN)+valid('memoryFrozenStoreProof',FROZEN)+valid('postedCompleted',['index','tag'])
def method(prefix, name):
    return prefix + ('reset' if name == 'reset' else 'io$$' + name.replace('.', '$$'))


def emit_driver(destination):
    """Mechanical port access; authored tests and independent byte oracle live in Python."""
    setters = '\n'.join('    setters.emplace("' + name + '", [&](uint64_t v) { d.' +
                        method('set_', name) + '(v); });' for name in INPUTS)
    getters = '\n'.join('            std::cout << ",\\"' + name + '\\":" << uint64_t(d.' +
                        method('get_', name) + '());' for name in OUTPUTS)
    source = '''#include "CollectionReadStoreGsim.h"
#include <cstdint>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
int main() {
  try {
    SCollectionReadStoreGsim d;
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
