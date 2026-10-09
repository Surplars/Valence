#include "memory_oracle.h"
#include <functional>
#include <iostream>
using namespace monitor_replay;
int main() {
    MemoryOracle m; m.initialize(std::vector<uint8_t>(26952), std::vector<uint8_t>(64));
    const uint64_t sd = 1 | (3 << 7) | (255 << 9), ld = sd ^ 1;
    unsigned rejected = 0;
    auto negative = [&](const std::function<void()> &f, const char *why) {
        try { f(); } catch (const std::runtime_error &e) { require(std::string(e.what()) == why, "wrong negative reason"); ++rejected; return; }
        throw std::runtime_error("oracle negative accepted corruption");
    };
    negative([&]{m.accept(base, 1, sd);}, "oracle write outside mutable diagnostic region");
    negative([&]{m.accept(mailbox, 1, sd);}, "oracle write outside mutable diagnostic region");
    negative([&]{m.accept(stackStart - 8, 0, ld);}, "oracle unexpected CPU memory region");
    negative([&]{m.accept(aBase, 0, sd ^ (1 << 9));}, "oracle illegal request alignment/size/mask");
    negative([&]{m.accept(aBase, 0, ld | (1 << 18));}, "oracle unexpected atomic/virtual/uncached request");
    negative([&]{m.accept(0x10000005, 0, 1 | (32 << 9));}, "oracle unexpected UART register operation");
    m.accept(0x10000005, 0, 32 << 9);
    m.accept(0x10000002, 7ULL << 16, 1 | (4 << 9));
    negative([&]{auto c=m;c.accept(aBase, pattern(0)^1, sd);}, "oracle buffer store pattern mismatch");
    negative([&]{auto c=m;c.accept(aBase+8, pattern(1), sd);}, "oracle buffer store ordinal/address mismatch");
    for (unsigned size : {1024, 16384}) {
        for (unsigned i=0;i<size;++i) { m.accept(aBase+8*i,pattern(i),sd);m.accept(bBase+8*i,0,sd); }
        for (unsigned i=0;i<size;++i) m.accept(aBase+8*i,~pattern(i),sd);
        for (unsigned i=0;i<size;++i) m.accept(aBase+8*i,pattern(i),sd);
        for (unsigned i=0;i<size;++i) m.accept(bBase+8*i,pattern(i),sd);
    }
    m.verifyBuffers();
    for(unsigned i=0;i<4;++i)require(m.accept(bBase+bufferBytes+i*8,0,ld)==0,"guard read is not known zero");
    negative([&]{m.accept(bBase+bufferBytes+32,0,ld);},"oracle unexpected CPU memory region");
    negative([&]{m.accept(bBase+bufferBytes,0,sd);},"oracle write outside mutable diagnostic region");
    negative([&]{auto c=m;c.words[bBase]^=1;c.verifyBuffers();}, "oracle final B pattern mismatch");
    m.accept(stackStart+3, 0x5aULL<<24, 1|(8<<9));
    require(m.accept(stackStart+3, 0, 8<<9) == 0x5aULL<<24, "oracle byte lanes failed");
    std::cout << "PASS_MONITOR_ORACLE_HOST negatives=" << rejected << " a_stores=" << m.aWrites << " b_stores=" << m.bWrites << "\n";
}
