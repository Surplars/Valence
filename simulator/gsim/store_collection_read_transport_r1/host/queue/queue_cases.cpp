#include "CollectionReadQueueGsim.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
using Word = decltype(std::declval<SCollectionReadQueueGsim>().get_io$$deqBits());
static void need(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
static uint64_t randomWord(uint64_t& x) { x ^= x << 13; x ^= x >> 7; x ^= x << 17; return x; }
static Word lowMask(unsigned width) { Word x = 0; for (unsigned i=0;i<width;++i) x=(x<<1)|1; return x; }
int main(int argc, char** argv) { try {
    need(argc >= 2 && argc <= 3, "QUEUE_ARGS");
    const bool enabled = std::string(argv[1]) == "1";
    need(enabled || std::string(argv[1]) == "0", "QUEUE_MODE");
    const std::string mutation = argc == 3 ? argv[2] : "";
    need(mutation.empty() || mutation == "frozen" || (enabled && mutation == "read"), "QUEUE_MUTATION_ARGS");
    SCollectionReadQueueGsim d;
    std::deque<Word> queue;
    uint64_t seed=0x9e3779b97f4a7c15ULL, accepted=0, returned=0, resetDiscard=0;
    uint64_t fullStalls=0, heldCycles=0, simultaneous=0, digest=1469598103934665603ULL;
    uint64_t matrix[4]={}; unsigned cycle=0, serial=0; bool pending=false, mutated=false; Word offer=0;
    auto record = [&]() {
        Word base=0;
        for (unsigned n=0;n<670;n+=64) base |= Word(randomWord(seed)) << n;
        base &= lowMask(670);
        const bool frozen=(serial&1)!=0, read=(serial&2)!=0;
        base = (base & ~(Word(1)<<139)) | (Word(frozen)<<139);
        ++serial;
        if (!enabled) return base;
        return (base & lowMask(140)) | ((base >> 140) << 141) | (Word(read)<<140);
    };
    auto tick = [&](bool reset, bool valid, Word bits, bool ready) {
        d.set_reset(reset); d.set_io$$enqValid(valid); d.set_io$$enqBits(bits); d.set_io$$deqReady(ready); d.step();
        ++cycle;
        if (reset) { resetDiscard += queue.size(); queue.clear(); pending=false; return; }
        need(d.get_io$$requestBits()==184, "QUEUE_EXTERNAL_SCHEMA");
        need(d.get_io$$recordBits()==(enabled ? 671 : 670), "QUEUE_RECORD_SCHEMA");
        const bool expectedEnq=queue.size()<4, expectedDeq=!queue.empty();
        need(bool(d.get_io$$enqReady())==expectedEnq, "QUEUE_NO_PIPE_READY");
        need(bool(d.get_io$$deqValid())==expectedDeq, "QUEUE_NO_FLOW_VALID");
        need(d.get_io$$count()==queue.size(), "QUEUE_COUNT");
        if (expectedDeq) {
            Word got=d.get_io$$deqBits();
            if (!mutation.empty() && !mutated) {
                got ^= Word(1) << (mutation=="frozen" ? 139 : 140); mutated=true;
            }
            need(got==queue.front(), mutation=="read" ? "QUEUE_READ_QUALIFICATION_MISMATCH" :
                mutation=="frozen" ? "QUEUE_FROZEN_VALID_MISMATCH" : "QUEUE_COMPLETE_RECORD_MISMATCH");
        }
        if (valid && !expectedEnq) { ++fullStalls; ++heldCycles; }
        if (valid && expectedEnq && expectedDeq && ready) ++simultaneous;
        if (expectedDeq && ready) {
            Word normalized=queue.front();
            if (enabled) normalized=(normalized&lowMask(140))|((normalized>>141)<<140);
            for (unsigned n=0;n<670;n+=64) { digest ^= uint64_t(normalized>>n); digest *=1099511628211ULL; }
            queue.pop_front();++returned;
        }
        if (valid && expectedEnq) {
            queue.push_back(bits); ++accepted; pending=false;
            const unsigned frozen=unsigned((bits>>139)&1);
            const unsigned read=enabled ? unsigned((bits>>140)&1) : 0;
            ++matrix[frozen+2*read];
        }
    };
    tick(true,false,0,false);tick(true,false,0,false);
    for (unsigned n=0;n<3000;++n) {
        if (n==1500) { tick(true,false,0,false);continue; }
        if (!pending && (n<32 || (randomWord(seed)&3)!=0)) { offer=record();pending=true; }
        const bool ready=n>=24 && ((n%97)>=11) && ((randomWord(seed)&3)!=0);
        tick(false,pending,offer,ready);
    }
    for (unsigned n=0;n<20 && (pending || !queue.empty());++n) tick(false,pending,offer,true);
    need(queue.empty() && !pending, "QUEUE_DRAIN");
    need(accepted==returned+resetDiscard, "QUEUE_RESET_OWNER_CONSERVATION");
    need(accepted>500 && fullStalls>20 && simultaneous>100 && resetDiscard>0, "QUEUE_NONVACUITY");
    need(matrix[0]>50 && matrix[1]>50 && (!enabled || (matrix[2]>50 && matrix[3]>50)), "QUEUE_2X2_MATRIX");
    need(mutation.empty(), "QUEUE_MUTATION_DID_NOT_FIRE");
    std::cout<<"QUEUE_ROUNDTRIP_PASS enabled="<<enabled<<" accepted="<<accepted<<" returned="<<returned
      <<" resetDiscard="<<resetDiscard<<" fullStalls="<<fullStalls<<" heldCycles="<<heldCycles
      <<" simultaneous="<<simultaneous<<" cycles="<<cycle<<" digest="<<digest
      <<" matrix="<<matrix[0]<<","<<matrix[1]<<","<<matrix[2]<<","<<matrix[3]<<"\n";
    return 0;
} catch (const std::exception& e) { std::cerr<<e.what()<<"\n";return 1; } }
