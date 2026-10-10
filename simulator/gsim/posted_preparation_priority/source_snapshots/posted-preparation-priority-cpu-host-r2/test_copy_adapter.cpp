#include "copy_adapter_logic.hpp"
#include <iostream>
using namespace pfcopy;
int main(){try{
    using Tag=unsigned __int128;const uint64_t generation=(1ULL<<63)+1;const Tag tag=(Tag(2)<<66)|(Tag(generation)<<2)|(Tag(1)<<1)|1;
    verifyAcquireTag(tag,1,2,1,generation);unsigned rejected=0;
    for(Tag poison:{Tag(1),Tag(1)<<1,Tag(1)<<33,Tag(1)<<65,Tag(1)<<66}){try{verifyAcquireTag(tag^poison,1,2,1,generation);}catch(const std::runtime_error&){++rejected;}}
    require(rejected==5,"high-generation/full-tag mutation escaped");
    auto held=classifyInstall(true,false,false,false,true,true);require(!held.residentInstall&&!held.storePfInstall&&!held.storePfError,"VALID-held counted as SRAM install");
    auto postedReturn=classifyInstall(true,false,false,false,false,false);require(!postedReturn.residentInstall,"posted refill before install invalidated resident generation");
    auto actual=classifyInstall(false,false,true,false,false,false);require(actual.residentInstall&&!actual.storePfInstall,"real posted install did not clear old resident generation");
    auto pf=classifyInstall(true,true,false,false,true,true);require(pf.residentInstall&&pf.storePfInstall&&!pf.storePfError,"actual store PF install lost");
    auto error=classifyInstall(true,true,false,true,true,true);require(!error.residentInstall&&!error.storePfInstall&&error.storePfError,"PF error became installed data");
    Ledger ledger(0x10000,0x30000,131072);Event a;a.allocate=true;a.allocMshr=0;a.allocIndex=5;a.allocAddress=0x30000;a.cycle=1;ledger.accept(a);
    Event f;f.install=true;f.successfulRefill=true;f.fillMshr=0;f.installIndex=5;f.installAddress=0x30000;f.cycle=2;ledger.accept(f);require(ledger.records[0].live,"PF resident absent");
    Event noInstall;noInstall.successfulRefill=postedReturn.residentInstall;noInstall.installIndex=5;noInstall.cycle=3;ledger.accept(noInstall);require(ledger.records[0].live,"posted return erased PF before actual install");
    Event installed;installed.successfulRefill=actual.residentInstall;installed.installIndex=5;installed.cycle=4;ledger.accept(installed);require(!ledger.records[0].live,"posted actual install left stale PF resident");
    std::cout<<"PASS COPY ABI adapter full68bit_tag=1 high_generation_mutations=5 held_valid_no_install=1 posted_return_no_install=1 actual_posted_install_invalidates_resident=1 PF_fire_error_preserved=1 unchanged_ledger=1\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
