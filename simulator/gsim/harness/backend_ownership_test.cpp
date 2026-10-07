#include "backend_ownership_ledger.h"
#include <iostream>
#include <functional>
static void bit(BackendSample &s,unsigned n){s.events|=uint64_t(1)<<n;}
static BackendToken A{0x100000001ULL,3},B{0x200000001ULL,3}; // SAME index, different full generations.
static BackendSample accepting(BackendToken t){BackendSample s;s.start=s.request=t;for(auto n:{3,20,21,41})bit(s,n);return s;}
static BackendSample queued(BackendToken t){BackendSample s;s.live[0]=true;s.phase[0]=2;s.slots[0]=t;s.fifoCount=1;bit(s,22);return s;}
static void failure(const std::function<void()> &fn,const char *expected){try{fn();}catch(const std::runtime_error &e){
    if(std::string(e.what()).find(expected)!=std::string::npos)return;throw;
}throw std::runtime_error("negative ownership case silently passed");}
int main(){try{
    // Non-flow FIFO, simultaneous dequeue/enqueue, and cancelled read still draining.
    BackendOwnershipLedger l;l.advance(accepting(A));auto s=queued(A);s.cancelled[0]=true;
    s.start=s.request=B;for(auto n:{3,20,21,23,41})bit(s,n);l.advance(s);
    s={};s.live={true,true};s.phase={2,2};s.slots={A,B};s.fifoCount=1;for(auto n:{22,23,24,25,28})bit(s,n);
    s.returnSlot=0;l.advance(s);s={};s.live[1]=true;s.phase[1]=2;s.slots[1]=B;
    for(auto n:{24,25,28})bit(s,n);s.returnSlot=1;l.advance(s);
    BackendOwnershipLedger::require(l.responses.empty()&&l.requests.empty()&&l.returns==2&&l.simultaneous==1&&l.cancellationWhileOutstanding==1,"normal conservation");
    // Local forwarded acknowledgement shares the dequeue cycle; no external request presumed.
    BackendOwnershipLedger local;local.advance(accepting(A));s=queued(A);for(auto n:{23,24,25,28,38})bit(s,n);local.advance(s);
    BackendOwnershipLedger::require(local.returns==1&&local.localAccepts==1,"local reply ownership");
    // Start forwarded directly inside LSU never enters either request ledger.
    BackendOwnershipLedger forwarded;s={};for(auto n:{3,36,42,43})bit(s,n);s.start=A;forwarded.advance(s);
    BackendOwnershipLedger::require(forwarded.enqueues==0&&forwarded.forwardedStarts==1&&forwarded.fastStores==1,"bypass paths");
    // Reset is the only event allowed to discard queued ownership.
    BackendOwnershipLedger reset;reset.advance(accepting(A));s={};s.reset=true;reset.advance(s);reset.advance(accepting(B));
    BackendOwnershipLedger::require(reset.requests.size()==1&&reset.resetRequestDrops==1,"reset accounting");
    // A completing old generation may be replaced by the new accepted-start owner.
    BackendOwnershipLedger replace;s=accepting(B);s.live[0]=true;s.phase[0]=3;s.slots[0]=A;s.complete=A;bit(s,26);bit(s,27);replace.advance(s);
    // Independently corrupt the return route, preserving both live full tokens.
    BackendOwnershipLedger wrong;wrong.advance(accepting(A));s=queued(A);bit(s,23);wrong.advance(s);
    s={};s.live={true,true};s.phase={2,1};s.slots={A,B};s.returnSlot=1;for(auto n:{24,25,28})bit(s,n);
    failure([&]{wrong.advance(s);},"response full-token owner corruption");
    BackendOwnershipLedger wrongEnq;s=accepting(A);s.request=B;
    failure([&]{wrongEnq.advance(s);},"request acceptance does not match");
    BackendOwnershipLedger wrongCount;s={};s.fifoCount=1;
    failure([&]{wrongCount.advance(s);},"hardware FIFO count differs");
    // Launch, full slots and serial exclusion must be distinct primary categories.
    BackendOwnershipLedger categories;s={};s.headValid=s.headQueued=s.headMemory=true;s.head=A;s.start=A;
    bit(s,3);BackendOwnershipLedger::require(categories.category(s)=="queued_memory_launch","launch bin");
    s.events=0;bit(s,0);bit(s,2);BackendOwnershipLedger::require(categories.category(s)=="queued_memory_no_available_slot","full slot bin");
    bit(s,5);BackendOwnershipLedger::require(categories.category(s)=="queued_memory_serial_exclusion","serial bin");
    std::cout<<"PASS backend ownership independent scenarios and three corruption rejections\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}}
