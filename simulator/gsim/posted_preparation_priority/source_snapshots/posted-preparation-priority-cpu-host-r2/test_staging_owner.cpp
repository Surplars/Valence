#include "ready_frontier.hpp"
#include <iostream>
struct Guarded {uint64_t value=0;bool readable=false;operator uint64_t()const{canonical_overlap::need(readable,"invalid staged payload read");return value;}};
struct Fake {
 bool board$platform$core$core$core$backend$stagedMemoryValid=false;
 Guarded board$platform$core$core$core$backend$stagedMemoryMetadata$$renamed$$token$$index;
 Guarded board$platform$core$core$core$backend$stagedMemoryMetadata$$renamed$$token$$tag;
};
int main(){Fake d;unissued::Sample u;auto&x=u.owners[9];x.live=x.pending=x.memoryLive=x.memory=true;x.token={9,UINT64_C(0xf123456789abcdef)};
 canonical_overlap::need(!frontier::stagingOwner(d,u).valid,"invalid stage read");
 d.board$platform$core$core$core$backend$stagedMemoryValid=true;
 auto&i=d.board$platform$core$core$core$backend$stagedMemoryMetadata$$renamed$$token$$index;
 auto&t=d.board$platform$core$core$core$backend$stagedMemoryMetadata$$renamed$$token$$tag;i={9,true};t={x.token.tag,true};
 auto good=frontier::stagingOwner(d,u);canonical_overlap::need(good.valid&&good.token==x.token,"full 64-bit tag positive");
 ++t.value;canonical_overlap::need(!frontier::stagingOwner(d,u).valid,"same index wrong full tag accepted");--t.value;
 i.value=10;canonical_overlap::need(!frontier::stagingOwner(d,u).valid,"wrong index accepted");i.value=9;
 x.pending=false;canonical_overlap::need(!frontier::stagingOwner(d,u).valid,"not pending accepted");x.pending=true;
 x.live=false;canonical_overlap::need(!frontier::stagingOwner(d,u).valid,"not live accepted");x.live=true;
 x.killed=true;canonical_overlap::need(!frontier::stagingOwner(d,u).valid,"killed owner accepted");x.killed=false;
 x.memoryLive=false;canonical_overlap::need(!frontier::stagingOwner(d,u).valid,"no live memory accepted");
 std::cout<<"STAGED_OWNER_PASS fulltag64=1 invalid_payload_guard=1 wrong_tag=1 wrong_index=1 pending=1 live=1 killed=1 memory_live=1\n";
}
