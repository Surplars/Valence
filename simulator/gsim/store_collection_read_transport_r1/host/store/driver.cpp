#include "CollectionReadStoreGsim.h"
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
    setters.emplace("reset", [&](uint64_t v) { d.set_reset(v); });
    setters.emplace("upstream.request.valid", [&](uint64_t v) { d.set_io$$upstream$$request$$valid(v); });
    setters.emplace("upstream.response.ready", [&](uint64_t v) { d.set_io$$upstream$$response$$ready(v); });
    setters.emplace("memory.request.ready", [&](uint64_t v) { d.set_io$$memory$$request$$ready(v); });
    setters.emplace("memory.response.valid", [&](uint64_t v) { d.set_io$$memory$$response$$valid(v); });
    setters.emplace("fastStore.valid", [&](uint64_t v) { d.set_io$$fastStore$$valid(v); });
    setters.emplace("upstreamCollectionHeadRead", [&](uint64_t v) { d.set_io$$upstreamCollectionHeadRead(v); });
    setters.emplace("externalPostedBusy", [&](uint64_t v) { d.set_io$$externalPostedBusy(v); });
    setters.emplace("upstream.request.bits.returnHandle", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$returnHandle(v); });
    setters.emplace("upstream.request.bits.atomic", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$atomic(v); });
    setters.emplace("upstream.request.bits.atomicOp", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$atomicOp(v); });
    setters.emplace("upstream.request.bits.address", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$address(v); });
    setters.emplace("upstream.request.bits.write", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$write(v); });
    setters.emplace("upstream.request.bits.size", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$size(v); });
    setters.emplace("upstream.request.bits.data", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$data(v); });
    setters.emplace("upstream.request.bits.mask", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$mask(v); });
    setters.emplace("upstream.request.bits.virtualized", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$virtualized(v); });
    setters.emplace("upstream.request.bits.precheckedLoad", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$precheckedLoad(v); });
    setters.emplace("upstream.request.bits.translationEpoch", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$translationEpoch(v); });
    setters.emplace("upstream.request.bits.prefetchNextAllowed", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(v); });
    setters.emplace("upstream.request.bits.uncached", [&](uint64_t v) { d.set_io$$upstream$$request$$bits$$uncached(v); });
    setters.emplace("memory.response.bits.returnHandle", [&](uint64_t v) { d.set_io$$memory$$response$$bits$$returnHandle(v); });
    setters.emplace("memory.response.bits.data", [&](uint64_t v) { d.set_io$$memory$$response$$bits$$data(v); });
    setters.emplace("memory.response.bits.error", [&](uint64_t v) { d.set_io$$memory$$response$$bits$$error(v); });
    setters.emplace("memory.response.bits.pageFault", [&](uint64_t v) { d.set_io$$memory$$response$$bits$$pageFault(v); });
    setters.emplace("fastStore.bits.atomic", [&](uint64_t v) { d.set_io$$fastStore$$bits$$atomic(v); });
    setters.emplace("fastStore.bits.atomicOp", [&](uint64_t v) { d.set_io$$fastStore$$bits$$atomicOp(v); });
    setters.emplace("fastStore.bits.address", [&](uint64_t v) { d.set_io$$fastStore$$bits$$address(v); });
    setters.emplace("fastStore.bits.write", [&](uint64_t v) { d.set_io$$fastStore$$bits$$write(v); });
    setters.emplace("fastStore.bits.size", [&](uint64_t v) { d.set_io$$fastStore$$bits$$size(v); });
    setters.emplace("fastStore.bits.data", [&](uint64_t v) { d.set_io$$fastStore$$bits$$data(v); });
    setters.emplace("fastStore.bits.mask", [&](uint64_t v) { d.set_io$$fastStore$$bits$$mask(v); });
    setters.emplace("fastStore.bits.virtualized", [&](uint64_t v) { d.set_io$$fastStore$$bits$$virtualized(v); });
    setters.emplace("fastStore.bits.precheckedLoad", [&](uint64_t v) { d.set_io$$fastStore$$bits$$precheckedLoad(v); });
    setters.emplace("fastStore.bits.translationEpoch", [&](uint64_t v) { d.set_io$$fastStore$$bits$$translationEpoch(v); });
    setters.emplace("fastStore.bits.prefetchNextAllowed", [&](uint64_t v) { d.set_io$$fastStore$$bits$$prefetchNextAllowed(v); });
    setters.emplace("fastStore.bits.uncached", [&](uint64_t v) { d.set_io$$fastStore$$bits$$uncached(v); });
    setters.emplace("upstreamProof.valid", [&](uint64_t v) { d.set_io$$upstreamProof$$valid(v); });
    setters.emplace("upstreamProof.bits.token.index", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$token$$index(v); });
    setters.emplace("upstreamProof.bits.token.tag", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$token$$tag(v); });
    setters.emplace("upstreamProof.bits.epoch", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$epoch(v); });
    setters.emplace("upstreamProof.bits.address", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$address(v); });
    setters.emplace("upstreamProof.bits.data", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$data(v); });
    setters.emplace("upstreamProof.bits.mask", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$mask(v); });
    setters.emplace("upstreamProof.bits.size", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$size(v); });
    setters.emplace("upstreamProof.bits.headAuthorized", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$headAuthorized(v); });
    setters.emplace("upstreamProof.bits.physicalPmpAllowed", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$physicalPmpAllowed(v); });
    setters.emplace("upstreamProof.bits.originalPhysical", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$originalPhysical(v); });
    setters.emplace("upstreamProof.bits.integerOrigin", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$integerOrigin(v); });
    setters.emplace("upstreamProof.bits.legacyPostedAccepted", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$legacyPostedAccepted(v); });
    setters.emplace("upstreamProof.bits.finalChecked", [&](uint64_t v) { d.set_io$$upstreamProof$$bits$$finalChecked(v); });
    setters.emplace("fastProof.valid", [&](uint64_t v) { d.set_io$$fastProof$$valid(v); });
    setters.emplace("fastProof.bits.token.index", [&](uint64_t v) { d.set_io$$fastProof$$bits$$token$$index(v); });
    setters.emplace("fastProof.bits.token.tag", [&](uint64_t v) { d.set_io$$fastProof$$bits$$token$$tag(v); });
    setters.emplace("fastProof.bits.epoch", [&](uint64_t v) { d.set_io$$fastProof$$bits$$epoch(v); });
    setters.emplace("fastProof.bits.address", [&](uint64_t v) { d.set_io$$fastProof$$bits$$address(v); });
    setters.emplace("fastProof.bits.data", [&](uint64_t v) { d.set_io$$fastProof$$bits$$data(v); });
    setters.emplace("fastProof.bits.mask", [&](uint64_t v) { d.set_io$$fastProof$$bits$$mask(v); });
    setters.emplace("fastProof.bits.size", [&](uint64_t v) { d.set_io$$fastProof$$bits$$size(v); });
    setters.emplace("fastProof.bits.headAuthorized", [&](uint64_t v) { d.set_io$$fastProof$$bits$$headAuthorized(v); });
    setters.emplace("fastProof.bits.physicalPmpAllowed", [&](uint64_t v) { d.set_io$$fastProof$$bits$$physicalPmpAllowed(v); });
    setters.emplace("fastProof.bits.originalPhysical", [&](uint64_t v) { d.set_io$$fastProof$$bits$$originalPhysical(v); });
    setters.emplace("fastProof.bits.integerOrigin", [&](uint64_t v) { d.set_io$$fastProof$$bits$$integerOrigin(v); });
    setters.emplace("fastProof.bits.legacyPostedAccepted", [&](uint64_t v) { d.set_io$$fastProof$$bits$$legacyPostedAccepted(v); });
    setters.emplace("fastProof.bits.finalChecked", [&](uint64_t v) { d.set_io$$fastProof$$bits$$finalChecked(v); });
    setters.emplace("upstreamCanonicalStoreOrigin.valid", [&](uint64_t v) { d.set_io$$upstreamCanonicalStoreOrigin$$valid(v); });
    setters.emplace("upstreamCanonicalStoreOrigin.bits.token.index", [&](uint64_t v) { d.set_io$$upstreamCanonicalStoreOrigin$$bits$$token$$index(v); });
    setters.emplace("upstreamCanonicalStoreOrigin.bits.token.tag", [&](uint64_t v) { d.set_io$$upstreamCanonicalStoreOrigin$$bits$$token$$tag(v); });
    setters.emplace("upstreamCanonicalStoreOrigin.bits.epoch", [&](uint64_t v) { d.set_io$$upstreamCanonicalStoreOrigin$$bits$$epoch(v); });
    setters.emplace("upstreamFrozenStoreProof.valid", [&](uint64_t v) { d.set_io$$upstreamFrozenStoreProof$$valid(v); });
    setters.emplace("upstreamFrozenStoreProof.bits.address", [&](uint64_t v) { d.set_io$$upstreamFrozenStoreProof$$bits$$address(v); });
    setters.emplace("upstreamFrozenStoreProof.bits.physicalAddress", [&](uint64_t v) { d.set_io$$upstreamFrozenStoreProof$$bits$$physicalAddress(v); });
    setters.emplace("upstreamFrozenStoreProof.bits.size", [&](uint64_t v) { d.set_io$$upstreamFrozenStoreProof$$bits$$size(v); });
    setters.emplace("upstreamFrozenStoreProof.bits.mask", [&](uint64_t v) { d.set_io$$upstreamFrozenStoreProof$$bits$$mask(v); });
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
      std::cout << "{\"cycle\":" << cycle;
            std::cout << ",\"upstream.request.ready\":" << uint64_t(d.get_io$$upstream$$request$$ready());
            std::cout << ",\"upstream.response.valid\":" << uint64_t(d.get_io$$upstream$$response$$valid());
            std::cout << ",\"memory.request.valid\":" << uint64_t(d.get_io$$memory$$request$$valid());
            std::cout << ",\"memory.response.ready\":" << uint64_t(d.get_io$$memory$$response$$ready());
            std::cout << ",\"fastStore.ready\":" << uint64_t(d.get_io$$fastStore$$ready());
            std::cout << ",\"memoryCollectionHeadRead\":" << uint64_t(d.get_io$$memoryCollectionHeadRead());
            std::cout << ",\"busy\":" << uint64_t(d.get_io$$busy());
            std::cout << ",\"forwarded\":" << uint64_t(d.get_io$$forwarded());
            std::cout << ",\"requestStallCause\":" << uint64_t(d.get_io$$requestStallCause());
            std::cout << ",\"upstream.response.bits.returnHandle\":" << uint64_t(d.get_io$$upstream$$response$$bits$$returnHandle());
            std::cout << ",\"upstream.response.bits.data\":" << uint64_t(d.get_io$$upstream$$response$$bits$$data());
            std::cout << ",\"upstream.response.bits.error\":" << uint64_t(d.get_io$$upstream$$response$$bits$$error());
            std::cout << ",\"upstream.response.bits.pageFault\":" << uint64_t(d.get_io$$upstream$$response$$bits$$pageFault());
            std::cout << ",\"memory.request.bits.returnHandle\":" << uint64_t(d.get_io$$memory$$request$$bits$$returnHandle());
            std::cout << ",\"memory.request.bits.atomic\":" << uint64_t(d.get_io$$memory$$request$$bits$$atomic());
            std::cout << ",\"memory.request.bits.atomicOp\":" << uint64_t(d.get_io$$memory$$request$$bits$$atomicOp());
            std::cout << ",\"memory.request.bits.address\":" << uint64_t(d.get_io$$memory$$request$$bits$$address());
            std::cout << ",\"memory.request.bits.write\":" << uint64_t(d.get_io$$memory$$request$$bits$$write());
            std::cout << ",\"memory.request.bits.size\":" << uint64_t(d.get_io$$memory$$request$$bits$$size());
            std::cout << ",\"memory.request.bits.data\":" << uint64_t(d.get_io$$memory$$request$$bits$$data());
            std::cout << ",\"memory.request.bits.mask\":" << uint64_t(d.get_io$$memory$$request$$bits$$mask());
            std::cout << ",\"memory.request.bits.virtualized\":" << uint64_t(d.get_io$$memory$$request$$bits$$virtualized());
            std::cout << ",\"memory.request.bits.precheckedLoad\":" << uint64_t(d.get_io$$memory$$request$$bits$$precheckedLoad());
            std::cout << ",\"memory.request.bits.translationEpoch\":" << uint64_t(d.get_io$$memory$$request$$bits$$translationEpoch());
            std::cout << ",\"memory.request.bits.prefetchNextAllowed\":" << uint64_t(d.get_io$$memory$$request$$bits$$prefetchNextAllowed());
            std::cout << ",\"memory.request.bits.uncached\":" << uint64_t(d.get_io$$memory$$request$$bits$$uncached());
            std::cout << ",\"memoryProof.valid\":" << uint64_t(d.get_io$$memoryProof$$valid());
            std::cout << ",\"memoryProof.bits.token.index\":" << uint64_t(d.get_io$$memoryProof$$bits$$token$$index());
            std::cout << ",\"memoryProof.bits.token.tag\":" << uint64_t(d.get_io$$memoryProof$$bits$$token$$tag());
            std::cout << ",\"memoryProof.bits.epoch\":" << uint64_t(d.get_io$$memoryProof$$bits$$epoch());
            std::cout << ",\"memoryProof.bits.address\":" << uint64_t(d.get_io$$memoryProof$$bits$$address());
            std::cout << ",\"memoryProof.bits.data\":" << uint64_t(d.get_io$$memoryProof$$bits$$data());
            std::cout << ",\"memoryProof.bits.mask\":" << uint64_t(d.get_io$$memoryProof$$bits$$mask());
            std::cout << ",\"memoryProof.bits.size\":" << uint64_t(d.get_io$$memoryProof$$bits$$size());
            std::cout << ",\"memoryProof.bits.headAuthorized\":" << uint64_t(d.get_io$$memoryProof$$bits$$headAuthorized());
            std::cout << ",\"memoryProof.bits.physicalPmpAllowed\":" << uint64_t(d.get_io$$memoryProof$$bits$$physicalPmpAllowed());
            std::cout << ",\"memoryProof.bits.originalPhysical\":" << uint64_t(d.get_io$$memoryProof$$bits$$originalPhysical());
            std::cout << ",\"memoryProof.bits.integerOrigin\":" << uint64_t(d.get_io$$memoryProof$$bits$$integerOrigin());
            std::cout << ",\"memoryProof.bits.legacyPostedAccepted\":" << uint64_t(d.get_io$$memoryProof$$bits$$legacyPostedAccepted());
            std::cout << ",\"memoryProof.bits.finalChecked\":" << uint64_t(d.get_io$$memoryProof$$bits$$finalChecked());
            std::cout << ",\"memoryCanonicalStoreOrigin.valid\":" << uint64_t(d.get_io$$memoryCanonicalStoreOrigin$$valid());
            std::cout << ",\"memoryCanonicalStoreOrigin.bits.token.index\":" << uint64_t(d.get_io$$memoryCanonicalStoreOrigin$$bits$$token$$index());
            std::cout << ",\"memoryCanonicalStoreOrigin.bits.token.tag\":" << uint64_t(d.get_io$$memoryCanonicalStoreOrigin$$bits$$token$$tag());
            std::cout << ",\"memoryCanonicalStoreOrigin.bits.epoch\":" << uint64_t(d.get_io$$memoryCanonicalStoreOrigin$$bits$$epoch());
            std::cout << ",\"memoryFrozenStoreProof.valid\":" << uint64_t(d.get_io$$memoryFrozenStoreProof$$valid());
            std::cout << ",\"memoryFrozenStoreProof.bits.address\":" << uint64_t(d.get_io$$memoryFrozenStoreProof$$bits$$address());
            std::cout << ",\"memoryFrozenStoreProof.bits.physicalAddress\":" << uint64_t(d.get_io$$memoryFrozenStoreProof$$bits$$physicalAddress());
            std::cout << ",\"memoryFrozenStoreProof.bits.size\":" << uint64_t(d.get_io$$memoryFrozenStoreProof$$bits$$size());
            std::cout << ",\"memoryFrozenStoreProof.bits.mask\":" << uint64_t(d.get_io$$memoryFrozenStoreProof$$bits$$mask());
            std::cout << ",\"postedCompleted.valid\":" << uint64_t(d.get_io$$postedCompleted$$valid());
            std::cout << ",\"postedCompleted.bits.index\":" << uint64_t(d.get_io$$postedCompleted$$bits$$index());
            std::cout << ",\"postedCompleted.bits.tag\":" << uint64_t(d.get_io$$postedCompleted$$bits$$tag());
      std::cout << "}\n" << std::flush;
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "POSTED_OWNER_DRIVER_FAIL " << error.what() << "\n";
    return 1;
  }
}
