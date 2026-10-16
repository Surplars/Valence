#define TAGGED_STORE_RETURNS 1
#include <iostream>
#include <map>
#include "tagged_board_probe.h"
struct Mock {
    std::map<std::string,uint64_t> allowed;
    uint64_t read(const std::string &key){if(!allowed.contains(key))throw std::runtime_error("INVALID_PAYLOAD_GETTER "+key);return allowed.at(key);}
    uint64_t get_cpuTagged$$startValid(){return read("cpuTagged$$startValid");}
    uint64_t get_cpuTagged$$startSlot(){return read("cpuTagged$$startSlot");}
    uint64_t get_cpuTagged$$startVa(){return read("cpuTagged$$startVa");}
    uint64_t get_cpuTagged$$startPa(){return read("cpuTagged$$startPa");}
    uint64_t get_cpuTagged$$startData(){return read("cpuTagged$$startData");}
    uint64_t get_cpuTagged$$startSize(){return read("cpuTagged$$startSize");}
    uint64_t get_cpuTagged$$startFlags(){return read("cpuTagged$$startFlags");}
    uint64_t get_cpuTagged$$queued$$valid(){return read("cpuTagged$$queued$$valid");}
    uint64_t get_cpuTagged$$queued$$ready(){return read("cpuTagged$$queued$$ready");}
    uint64_t get_cpuTagged$$queued$$handle(){return read("cpuTagged$$queued$$handle");}
    uint64_t get_cpuTagged$$queued$$address(){return read("cpuTagged$$queued$$address");}
    uint64_t get_cpuTagged$$queued$$data(){return read("cpuTagged$$queued$$data");}
    uint64_t get_cpuTagged$$queued$$write(){return read("cpuTagged$$queued$$write");}
    uint64_t get_cpuTagged$$queued$$size(){return read("cpuTagged$$queued$$size");}
    uint64_t get_cpuTagged$$queued$$ordinary(){return read("cpuTagged$$queued$$ordinary");}
    uint64_t get_cpuTagged$$physical$$valid(){return read("cpuTagged$$physical$$valid");}
    uint64_t get_cpuTagged$$physical$$ready(){return read("cpuTagged$$physical$$ready");}
    uint64_t get_cpuTagged$$physical$$handle(){return read("cpuTagged$$physical$$handle");}
    uint64_t get_cpuTagged$$physical$$address(){return read("cpuTagged$$physical$$address");}
    uint64_t get_cpuTagged$$physical$$data(){return read("cpuTagged$$physical$$data");}
    uint64_t get_cpuTagged$$physical$$write(){return read("cpuTagged$$physical$$write");}
    uint64_t get_cpuTagged$$physical$$size(){return read("cpuTagged$$physical$$size");}
    uint64_t get_cpuTagged$$physical$$ordinary(){return read("cpuTagged$$physical$$ordinary");}
    uint64_t get_cpuTagged$$physicalReply$$valid(){return read("cpuTagged$$physicalReply$$valid");}
    uint64_t get_cpuTagged$$physicalReply$$ready(){return read("cpuTagged$$physicalReply$$ready");}
    uint64_t get_cpuTagged$$physicalReply$$handle(){return read("cpuTagged$$physicalReply$$handle");}
    uint64_t get_cpuTagged$$physicalReply$$data(){return read("cpuTagged$$physicalReply$$data");}
    uint64_t get_cpuTagged$$physicalReply$$flags(){return read("cpuTagged$$physicalReply$$flags");}
    uint64_t get_cpuTagged$$integerReply$$valid(){return read("cpuTagged$$integerReply$$valid");}
    uint64_t get_cpuTagged$$integerReply$$ready(){return read("cpuTagged$$integerReply$$ready");}
    uint64_t get_cpuTagged$$integerReply$$handle(){return read("cpuTagged$$integerReply$$handle");}
    uint64_t get_cpuTagged$$integerReply$$data(){return read("cpuTagged$$integerReply$$data");}
    uint64_t get_cpuTagged$$integerReply$$flags(){return read("cpuTagged$$integerReply$$flags");}
    uint64_t get_cpuTagged$$sbRequest$$valid(){return read("cpuTagged$$sbRequest$$valid");}
    uint64_t get_cpuTagged$$sbRequest$$ready(){return read("cpuTagged$$sbRequest$$ready");}
    uint64_t get_cpuTagged$$sbRequest$$handle(){return read("cpuTagged$$sbRequest$$handle");}
    uint64_t get_cpuTagged$$sbRequest$$address(){return read("cpuTagged$$sbRequest$$address");}
    uint64_t get_cpuTagged$$sbRequest$$data(){return read("cpuTagged$$sbRequest$$data");}
    uint64_t get_cpuTagged$$sbRequest$$write(){return read("cpuTagged$$sbRequest$$write");}
    uint64_t get_cpuTagged$$sbRequest$$size(){return read("cpuTagged$$sbRequest$$size");}
    uint64_t get_cpuTagged$$sbRequest$$ordinary(){return read("cpuTagged$$sbRequest$$ordinary");}
    uint64_t get_cpuTagged$$sbReply$$valid(){return read("cpuTagged$$sbReply$$valid");}
    uint64_t get_cpuTagged$$sbReply$$ready(){return read("cpuTagged$$sbReply$$ready");}
    uint64_t get_cpuTagged$$sbReply$$handle(){return read("cpuTagged$$sbReply$$handle");}
    uint64_t get_cpuTagged$$sbReply$$data(){return read("cpuTagged$$sbReply$$data");}
    uint64_t get_cpuTagged$$sbReply$$flags(){return read("cpuTagged$$sbReply$$flags");}
    uint64_t get_cpuTagged$$sbEnqueue(){return read("cpuTagged$$sbEnqueue");}
    uint64_t get_cpuTagged$$sbFast(){return read("cpuTagged$$sbFast");}
    uint64_t get_cpuTagged$$sbSlot(){return read("cpuTagged$$sbSlot");}
    uint64_t get_cpuTagged$$sbOriginHandle(){return read("cpuTagged$$sbOriginHandle");}
    uint64_t get_cpuTagged$$sbAddress(){return read("cpuTagged$$sbAddress");}
    uint64_t get_cpuTagged$$sbData(){return read("cpuTagged$$sbData");}
    uint64_t get_cpuTagged$$sbSize(){return read("cpuTagged$$sbSize");}
    uint64_t get_cpuTagged$$sbLocal(){return read("cpuTagged$$sbLocal");}
    uint64_t get_cpuTagged$$sbLocalWrite(){return read("cpuTagged$$sbLocalWrite");}
    uint64_t get_cpuTagged$$sbDrainReply(){return read("cpuTagged$$sbDrainReply");}
    uint64_t get_cpuTagged$$fpEpoch(){return read("cpuTagged$$fpEpoch");}
    uint64_t get_cpuTagged$$fpIndex(){return read("cpuTagged$$fpIndex");}
    uint64_t get_cpuTagged$$fpTag(){return read("cpuTagged$$fpTag");}
    uint64_t get_cpuTagged$$backendRequest$$valid(){return read("cpuTagged$$backendRequest$$valid");}
    uint64_t get_cpuTagged$$backendRequest$$ready(){return read("cpuTagged$$backendRequest$$ready");}
    uint64_t get_cpuTagged$$backendRequest$$handle(){return read("cpuTagged$$backendRequest$$handle");}
    uint64_t get_cpuTagged$$backendRequest$$address(){return read("cpuTagged$$backendRequest$$address");}
    uint64_t get_cpuTagged$$backendRequest$$data(){return read("cpuTagged$$backendRequest$$data");}
    uint64_t get_cpuTagged$$backendRequest$$write(){return read("cpuTagged$$backendRequest$$write");}
    uint64_t get_cpuTagged$$backendRequest$$size(){return read("cpuTagged$$backendRequest$$size");}
    uint64_t get_cpuTagged$$backendRequest$$ordinary(){return read("cpuTagged$$backendRequest$$ordinary");}
    uint64_t get_cpuTagged$$backendReply$$valid(){return read("cpuTagged$$backendReply$$valid");}
    uint64_t get_cpuTagged$$backendReply$$ready(){return read("cpuTagged$$backendReply$$ready");}
    uint64_t get_cpuTagged$$backendReply$$handle(){return read("cpuTagged$$backendReply$$handle");}
    uint64_t get_cpuTagged$$backendReply$$data(){return read("cpuTagged$$backendReply$$data");}
    uint64_t get_cpuTagged$$backendReply$$flags(){return read("cpuTagged$$backendReply$$flags");}
    uint64_t get_cpuTagged$$fpComplete(){return read("cpuTagged$$fpComplete");}
    uint64_t get_cpuTagged$$fpCompleteIndex(){return read("cpuTagged$$fpCompleteIndex");}
    uint64_t get_cpuTagged$$fpCompleteTag(){return read("cpuTagged$$fpCompleteTag");}
    uint64_t get_cpuTagged$$fpTval(){return read("cpuTagged$$fpTval");}
    uint64_t get_cpuTagged$$fpException(){return read("cpuTagged$$fpException");}
    uint64_t get_cpuTagged$$fpCause(){return read("cpuTagged$$fpCause");}
    uint64_t get_cpuTagged$$slot0$$live(){return read("cpuTagged$$slot0$$live");}
    uint64_t get_cpuTagged$$slot0$$index(){return read("cpuTagged$$slot0$$index");}
    uint64_t get_cpuTagged$$slot0$$tag(){return read("cpuTagged$$slot0$$tag");}
    uint64_t get_cpuTagged$$slot0$$cancel(){return read("cpuTagged$$slot0$$cancel");}
    uint64_t get_cpuTagged$$slot0$$discard(){return read("cpuTagged$$slot0$$discard");}
    uint64_t get_cpuTagged$$slot0$$complete(){return read("cpuTagged$$slot0$$complete");}
    uint64_t get_cpuTagged$$slot0$$fastLoad(){return read("cpuTagged$$slot0$$fastLoad");}
    uint64_t get_cpuTagged$$slot0$$completeIndex(){return read("cpuTagged$$slot0$$completeIndex");}
    uint64_t get_cpuTagged$$slot0$$completeTag(){return read("cpuTagged$$slot0$$completeTag");}
    uint64_t get_cpuTagged$$slot0$$tval(){return read("cpuTagged$$slot0$$tval");}
    uint64_t get_cpuTagged$$slot0$$exception(){return read("cpuTagged$$slot0$$exception");}
    uint64_t get_cpuTagged$$slot0$$cause(){return read("cpuTagged$$slot0$$cause");}
    uint64_t get_cpuTagged$$slot1$$live(){return read("cpuTagged$$slot1$$live");}
    uint64_t get_cpuTagged$$slot1$$index(){return read("cpuTagged$$slot1$$index");}
    uint64_t get_cpuTagged$$slot1$$tag(){return read("cpuTagged$$slot1$$tag");}
    uint64_t get_cpuTagged$$slot1$$cancel(){return read("cpuTagged$$slot1$$cancel");}
    uint64_t get_cpuTagged$$slot1$$discard(){return read("cpuTagged$$slot1$$discard");}
    uint64_t get_cpuTagged$$slot1$$complete(){return read("cpuTagged$$slot1$$complete");}
    uint64_t get_cpuTagged$$slot1$$fastLoad(){return read("cpuTagged$$slot1$$fastLoad");}
    uint64_t get_cpuTagged$$slot1$$completeIndex(){return read("cpuTagged$$slot1$$completeIndex");}
    uint64_t get_cpuTagged$$slot1$$completeTag(){return read("cpuTagged$$slot1$$completeTag");}
    uint64_t get_cpuTagged$$slot1$$tval(){return read("cpuTagged$$slot1$$tval");}
    uint64_t get_cpuTagged$$slot1$$exception(){return read("cpuTagged$$slot1$$exception");}
    uint64_t get_cpuTagged$$slot1$$cause(){return read("cpuTagged$$slot1$$cause");}
    uint64_t get_cpuTagged$$slot2$$live(){return read("cpuTagged$$slot2$$live");}
    uint64_t get_cpuTagged$$slot2$$index(){return read("cpuTagged$$slot2$$index");}
    uint64_t get_cpuTagged$$slot2$$tag(){return read("cpuTagged$$slot2$$tag");}
    uint64_t get_cpuTagged$$slot2$$cancel(){return read("cpuTagged$$slot2$$cancel");}
    uint64_t get_cpuTagged$$slot2$$discard(){return read("cpuTagged$$slot2$$discard");}
    uint64_t get_cpuTagged$$slot2$$complete(){return read("cpuTagged$$slot2$$complete");}
    uint64_t get_cpuTagged$$slot2$$fastLoad(){return read("cpuTagged$$slot2$$fastLoad");}
    uint64_t get_cpuTagged$$slot2$$completeIndex(){return read("cpuTagged$$slot2$$completeIndex");}
    uint64_t get_cpuTagged$$slot2$$completeTag(){return read("cpuTagged$$slot2$$completeTag");}
    uint64_t get_cpuTagged$$slot2$$tval(){return read("cpuTagged$$slot2$$tval");}
    uint64_t get_cpuTagged$$slot2$$exception(){return read("cpuTagged$$slot2$$exception");}
    uint64_t get_cpuTagged$$slot2$$cause(){return read("cpuTagged$$slot2$$cause");}
    uint64_t get_cpuTagged$$slot3$$live(){return read("cpuTagged$$slot3$$live");}
    uint64_t get_cpuTagged$$slot3$$index(){return read("cpuTagged$$slot3$$index");}
    uint64_t get_cpuTagged$$slot3$$tag(){return read("cpuTagged$$slot3$$tag");}
    uint64_t get_cpuTagged$$slot3$$cancel(){return read("cpuTagged$$slot3$$cancel");}
    uint64_t get_cpuTagged$$slot3$$discard(){return read("cpuTagged$$slot3$$discard");}
    uint64_t get_cpuTagged$$slot3$$complete(){return read("cpuTagged$$slot3$$complete");}
    uint64_t get_cpuTagged$$slot3$$fastLoad(){return read("cpuTagged$$slot3$$fastLoad");}
    uint64_t get_cpuTagged$$slot3$$completeIndex(){return read("cpuTagged$$slot3$$completeIndex");}
    uint64_t get_cpuTagged$$slot3$$completeTag(){return read("cpuTagged$$slot3$$completeTag");}
    uint64_t get_cpuTagged$$slot3$$tval(){return read("cpuTagged$$slot3$$tval");}
    uint64_t get_cpuTagged$$slot3$$exception(){return read("cpuTagged$$slot3$$exception");}
    uint64_t get_cpuTagged$$slot3$$cause(){return read("cpuTagged$$slot3$$cause");}
    uint64_t get_cpuTagged$$cache$$valid(){return read("cpuTagged$$cache$$valid");}
    uint64_t get_cpuTagged$$cache$$ready(){return read("cpuTagged$$cache$$ready");}
    uint64_t get_cpuTagged$$cache$$handle(){return read("cpuTagged$$cache$$handle");}
    uint64_t get_cpuTagged$$cache$$address(){return read("cpuTagged$$cache$$address");}
    uint64_t get_cpuTagged$$cache$$data(){return read("cpuTagged$$cache$$data");}
    uint64_t get_cpuTagged$$cache$$write(){return read("cpuTagged$$cache$$write");}
    uint64_t get_cpuTagged$$cache$$size(){return read("cpuTagged$$cache$$size");}
    uint64_t get_cpuTagged$$cache$$ordinary(){return read("cpuTagged$$cache$$ordinary");}
    uint64_t get_cpuTagged$$cacheReply$$valid(){return read("cpuTagged$$cacheReply$$valid");}
    uint64_t get_cpuTagged$$cacheReply$$ready(){return read("cpuTagged$$cacheReply$$ready");}
    uint64_t get_cpuTagged$$cacheReply$$handle(){return read("cpuTagged$$cacheReply$$handle");}
    uint64_t get_cpuTagged$$cacheReply$$data(){return read("cpuTagged$$cacheReply$$data");}
    uint64_t get_cpuTagged$$cacheReply$$flags(){return read("cpuTagged$$cacheReply$$flags");}
    uint64_t get_cpuTagged$$cacheHandle0(){return read("cpuTagged$$cacheHandle0");}
    uint64_t get_cpuTagged$$cacheHandle1(){return read("cpuTagged$$cacheHandle1");}
    uint64_t get_cpuTagged$$cacheKind0(){return read("cpuTagged$$cacheKind0");}
    uint64_t get_cpuTagged$$cacheKind1(){return read("cpuTagged$$cacheKind1");}
    uint64_t get_cpuTagged$$cacheSelected(){return read("cpuTagged$$cacheSelected");}
    uint64_t get_cpuTagged$$cacheOldestHit(){return read("cpuTagged$$cacheOldestHit");}
    uint64_t get_cpuTagged$$cacheStoreWrite(){return read("cpuTagged$$cacheStoreWrite");}
    uint64_t get_cpuTagged$$cachePostedIntent(){return read("cpuTagged$$cachePostedIntent");}
    uint64_t get_backendSlotCount(){return read("backendSlotCount");}
    uint64_t get_dataPathEvents(){return read("dataPathEvents");}
    uint64_t get_cpuSupplyPrefetch$$responseOwnedMask(){return read("cpuSupplyPrefetch$$responseOwnedMask");}
    uint64_t get_cpuSupplyPrefetch$$responseCompleteMask(){return read("cpuSupplyPrefetch$$responseCompleteMask");}
    uint64_t get_cpuSupplyPrefetch$$responseTailTicket(){return read("cpuSupplyPrefetch$$responseTailTicket");}
    uint64_t get_backendStartIndex(){return read("backendStartIndex");}
    uint64_t get_backendStartTag(){return read("backendStartTag");}
    uint64_t get_backendRequestIndex(){return read("backendRequestIndex");}
    uint64_t get_backendRequestTag(){return read("backendRequestTag");}
    uint64_t get_backendHeadIndex(){return read("backendHeadIndex");}
    uint64_t get_backendHeadTag(){return read("backendHeadTag");}
    uint64_t get_backendQueueHeadIndex(){return read("backendQueueHeadIndex");}
    uint64_t get_backendQueueHeadTag(){return read("backendQueueHeadTag");}
    Mock(){
        allowed["backendSlotCount"]=4;allowed["dataPathEvents"]=0;
        allowed["cpuSupplyPrefetch$$responseOwnedMask"]=0;allowed["cpuSupplyPrefetch$$responseCompleteMask"]=0;
        for(auto n:{"fpEpoch","fpComplete","sbLocal","cacheReply$$valid","physicalReply$$valid","integerReply$$valid","sbDrainReply","startValid","queued$$valid","sbEnqueue","physical$$valid","cache$$valid"})allowed[std::string("cpuTagged$$")+n]=0;
        for(unsigned n=0;n<4;++n)for(auto x:{"live","complete","discard","fastLoad"})allowed["cpuTagged$$slot"+std::to_string(n)+"$$"+x]=0;
    }
    void set(std::string name,uint64_t value){allowed["cpuTagged$$"+name]=value;}
};
int main(int argc,char**){try{
    Mock idle;tagged_board::Probe p;p.sample(idle,1);p.finish();
    if(argc>1){idle.get_cpuTagged$$cacheReply$$handle();throw std::logic_error("poison getter accepted");}
    auto a=tagged_board::Operation{},b=tagged_board::Operation{};a.token={3,0x8000000000000001ULL};a.va=a.pa=0x80400000;
    b.token={4,0x4000000000000002ULL};b.va=b.pa=0x81400000;b.write=true;b.data=0x1234;
    for(auto item:{std::pair{0U,a},std::pair{1U,b}}){auto [i,o]=item;p.ledger.start(i,o);p.ledger.reserve(i,o.token,o.va,o.data,o.write);p.ledger.physicalRequest(i,o.pa,o.data,o.write,3,true);p.ledger.cacheRequest(i,i,o.pa,o.data,o.write,o.write);}
    Mock active;active.allowed["dataPathEvents"]=1ULL<<21;active.allowed["cpuSupplyPrefetch$$responseOwnedMask"]=3;active.allowed["cpuSupplyPrefetch$$responseCompleteMask"]=2;
    for(auto item:{std::pair{0U,a},std::pair{1U,b}}){auto [i,o]=item;std::string q="slot"+std::to_string(i)+"$$";active.set(q+"live",1);active.set(q+"index",o.token.index);active.set(q+"tag",o.token.tag);active.set(q+"cancel",0);active.set("cacheHandle"+std::to_string(i),i);active.set("cacheKind"+std::to_string(i),0);}
    for(auto n:{"cacheReply","physicalReply","integerReply"}){active.set(std::string(n)+"$$valid",1);active.set(std::string(n)+"$$ready",1);active.set(std::string(n)+"$$handle",1);active.set(std::string(n)+"$$flags",0);active.set(std::string(n)+"$$data",0);}
    active.set("cacheSelected",1);active.set("cacheOldestHit",0);p.sample(active,2);
    tagged_board::require(p.ledger.bypassedStores==1&&p.ledger.owner(1).returned,"active response did not use guarded payload");
    std::cout<<"TAGGED_GETTER_GUARD_PASS idle_poison=1 active_store_return=1\n";return 0;
}catch(const std::runtime_error &e){std::cerr<<"TAGGED_GETTER_GUARD_REJECT "<<e.what()<<"\n";return 1;}catch(const std::exception &e){std::cerr<<"TAGGED_GETTER_TEST_ERROR "<<e.what()<<"\n";return 2;}}
