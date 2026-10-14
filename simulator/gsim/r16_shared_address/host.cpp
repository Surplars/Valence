#include "R16SharedAddressGsim.h"
#include <array>
#include <deque>
#include <map>
#include <optional>
#include <stdexcept>
#include <vector>
#include <fstream>
#include <bit>
#include <algorithm>
#include "initialize.h"
#include "snapshot.h"
#ifndef SHARED
#define SHARED 0
#endif
static void require(bool p,const char*s){if(!p)throw std::runtime_error(s);}
static uint32_t addi(unsigned d,unsigned s,int n){return (uint32_t(n&4095)<<20)|(s<<15)|(d<<7)|0x13;}
static uint32_t shift(unsigned d,unsigned s,unsigned n){return(n<<20)|(s<<15)|(1<<12)|(d<<7)|0x13;}
static uint32_t load(unsigned d,unsigned s,int n,unsigned z=3){return(uint32_t(n&4095)<<20)|(s<<15)|(z<<12)|(d<<7)|3;}
static uint32_t store(unsigned s,int n,unsigned v,unsigned z=3){unsigned q=n&4095;return((q>>5)<<25)|(v<<20)|(s<<15)|(z<<12)|((q&31)<<7)|0x23;}
static uint64_t sign(uint64_t x,unsigned n){uint64_t b=1ULL<<(n-1);return(x^b)-b;}
struct Owner{unsigned index=0;uint64_t tag=0,pc=0,address=0,result=0;unsigned size=0,rd=0;bool memory=false,store=false,atomic=false,writes=false;};
struct Row{std::optional<Owner>owner;bool known=false;uint64_t address=0;unsigned lanes=0;bool canonical=false;};
struct Response{uint64_t due,data;unsigned handle;};
struct Certificate{unsigned index;uint64_t tag;unsigned epoch;uint64_t va,pa;unsigned size,mask;};
class Bench{
 SR16SharedAddressGsim d;std::array<Row,16> rows{};std::array<uint64_t,32> expected{},committed{};std::array<std::optional<std::pair<uint64_t,unsigned>>,16> mustHold{};std::map<uint64_t,uint8_t> bytes;std::deque<Owner> live;std::deque<Response> replies;
 uint64_t cycle=0,pc=0x1000;unsigned seed;std::ofstream trace;bool virtualMode=false;uint32_t epoch=0;bool flushLast=false;std::optional<Certificate> certificate;static constexpr uint64_t va=0x80401000,pa=0x80201000;
 uint64_t virtualStores=0,prechecked=0,cancelled=0,killedCapture=0,atomicHeld=0,recoveries=0,replayEvents=0,noncanonicalLoads=0;uint64_t requests=0,responses=0,accepted=0,retired=0,loads=0,preps=0,dual=0,triple=0,holds=0,reuses=0,atomic=0,stores=0;uint16_t seenRows=0;
 uint64_t physical(uint64_t a){if(!virtualMode)return a;require(a==va,"unexpected virtual address");return pa;}
 unsigned lanes(uint64_t a,unsigned s){return(((1u<<(1u<<s))-1)<<(a&7))&255;}
 uint64_t beat(uint64_t a){uint64_t x=0;for(unsigned j=0;j<8;++j)x|=uint64_t(bytes[(a&~7ULL)+j])<<(8*j);return x;}
 Owner interpret(uint32_t insn){Owner o;unsigned op=insn&127,rd=(insn>>7)&31,s1=(insn>>15)&31,s2=(insn>>20)&31,f=(insn>>12)&7;uint64_t imm=sign(insn>>20,12);o.rd=rd;o.pc=pc;
 if(op==0x13){o.writes=rd!=0;o.result=f==1?expected[s1]<<((insn>>20)&63):expected[s1]+imm;}
 else if(op==3){o.memory=true;o.writes=rd!=0;o.size=f&3;o.address=expected[s1]+imm;o.result=(beat(physical(o.address))>>((o.address&7)*8));if(o.size<3)o.result=sign(o.result&((1ULL<<(8u<<o.size))-1),8u<<o.size);}
 else if(op==0x23){o.memory=o.store=true;o.size=f&3;o.address=expected[s1]+sign(((insn>>25)<<5)|((insn>>7)&31),12);}
 else if(op==0x63 && f==0){require(s1==s2,"only known taken branch modeled");}
 else if(op==0x73 && f==1){o.writes=rd!=0;require(!o.writes,"CSR readback not modeled");}
 else if(op==0x2f && (insn>>27)==0){o.memory=o.atomic=true;o.size=f&3;o.writes=rd!=0;o.address=expected[s1];o.result=beat(physical(o.address));}
 else if(op==0x33 && (insn>>25)==1 && f==4){o.writes=rd!=0;int64_t a=expected[s1],b=expected[s2];o.result=b==0?~0ULL:(a==INT64_MIN&&b==-1)?uint64_t(a):uint64_t(a/b);}
 else throw std::runtime_error("unimplemented independent instruction");
 if(o.writes)expected[rd]=o.result;return o;}
 unsigned storeLanes(unsigned i){
#if SHARED
 return d.backend$storeByteLanes[i];
#else
 return std::array<unsigned,16>{d.backend$storeByteLanes_0,d.backend$storeByteLanes_1,d.backend$storeByteLanes_2,d.backend$storeByteLanes_3,d.backend$storeByteLanes_4,d.backend$storeByteLanes_5,d.backend$storeByteLanes_6,d.backend$storeByteLanes_7,d.backend$storeByteLanes_8,d.backend$storeByteLanes_9,d.backend$storeByteLanes_10,d.backend$storeByteLanes_11,d.backend$storeByteLanes_12,d.backend$storeByteLanes_13,d.backend$storeByteLanes_14,d.backend$storeByteLanes_15}[i];
#endif
 }
 void verifyState(){for(unsigned i=0;i<16;++i){if(mustHold[i]){require(d.backend$storeAddress[i]==mustHold[i]->first&&storeLanes(i)==mustHold[i]->second,"excluded writer changed shared address row");mustHold[i].reset();}auto &r=rows[i];if(r.owner&&r.owner->memory&&!r.owner->store&&!r.owner->atomic&&(d.get_observation$$live()>>i&1))require(bool(d.get_observation$$canonical()>>i&1)==r.canonical,"canonical authority changed without valid load start/allocation");if(!r.known)continue;uint64_t a;unsigned m;if(r.owner->store){a=d.backend$storeAddress[i];m=storeLanes(i);}else{
#if SHARED
 a=d.backend$storeAddress[i];m=storeLanes(i);
#else
 a=d.backend$loadBeat[i]<<3;m=d.backend$loadLanes[i];
#endif
 }require(a==r.address&&m==r.lanes,"independent row payload mismatch");++holds;}}
 void observe(){verifyState();uint16_t p=d.get_observation$$pending(),l=d.get_observation$$live(),k=d.get_observation$$killed();uint16_t masks[2]{};
 for(unsigned rank=0;rank<2;++rank){unsigned captured=rank?d.backend$capturedOwners_1:d.backend$capturedOwners_0;unsigned ix=rank?d.backend$captured$$token$$index_1:d.backend$captured$$token$$index_0;uint64_t tag=rank?d.backend$captured$$token$$tag_1:d.backend$captured$$token$$tag_0;
 for(unsigned i=0;i<16;++i)if((captured>>i&1)&&(k>>i&1)){mustHold[i]=std::pair<uint64_t,unsigned>{d.backend$storeAddress[i],storeLanes(i)};++killedCapture;}
 for(unsigned i=0;i<16;++i)if((captured>>i&1)&&(p>>i&1)&&(l>>i&1)&&!(k>>i&1)&&rows[i].owner&&rows[i].owner->tag==tag&&i==ix){require(rows[i].owner->store,"prep nonstore owner");masks[rank]|=1u<<i;auto&r=rows[i];r.known=true;r.address=r.owner->address;r.lanes=lanes(r.address,r.owner->size);++preps;}}
#if SHARED
 require(masks[0]==d.get_observation$$storeWrites0()&&masks[1]==d.get_observation$$storeWrites1(),"prep authorization differs from independent accepted owner");
#endif
 require(!(masks[0]&masks[1]),"two prep writers collide");if(masks[0]&&masks[1])++dual;
 if(d.get_observation$$startFire()){unsigned i=d.get_observation$$actualIndex();auto&r=rows[i];require(r.owner&&r.owner->tag==d.get_observation$$actualTag(),"LSU start missing full owner");if(d.get_observation$$startAtomic()){++atomic;require(!d.get_observation$$loadWrite(),"atomic entered ordinary-load writer");mustHold[i]=std::pair<uint64_t,unsigned>{d.backend$storeAddress[i],storeLanes(i)};++atomicHeld;}if(d.get_observation$$startStore()){++stores;if(virtualMode){require(r.owner->address==va,"virtual store owner VA mismatch");if(d.get_observation$$known()>>i&1)require(d.backend$storeAddress[i]==va,"prepared virtual store lost VA");if(((d.get_observation$$known()|masks[0]|masks[1])>>i)&1)++virtualStores;std::cerr<<"VIRTUAL_STORE cycle="<<cycle<<" va="<<std::hex<<va<<" mapped="<<pa<<" canonicalSignal="<<d.get_observation$$canonicalAddress()<<" known="<<d.get_observation$$known()<<std::dec<<"\n";}}
 if(d.get_observation$$loadWrite()){require(r.owner->memory&&!r.owner->store&&!r.owner->atomic,"ordinary load class mismatch");require(!((masks[0]|masks[1])>>i&1),"load/prep same-row collision");uint64_t a=d.get_observation$$canonicalAddress();unsigned m=d.get_observation$$canonicalLanes();bool canonical=!virtualMode||d.backend$precheckedLoad;r.canonical=canonical;if(!canonical)++noncanonicalLoads;uint64_t expectedAddress=physical(r.owner->address);if(canonical)require(a==expectedAddress&&m==lanes(a,r.owner->size),"load metadata differs from independent authorized address");if(virtualMode&&d.backend$precheckedLoad)++prechecked;r.known=canonical;r.address=expectedAddress&~7ULL;r.lanes=lanes(expectedAddress,r.owner->size);++loads;if(masks[0]&&masks[1]){++triple;std::cerr<<"TRIPLE cycle="<<cycle<<" load="<<i<<" prep="<<masks[0]<<","<<masks[1]<<"\n";}}}}
 public:
 Bench(unsigned s,const char*path):seed(s),trace(path){initialize(d);d.set_io_commitEnable(1);d.set_io_fetchQuiescent(1);d.set_io_vmFlushReady(1);d.set_io_fenceIFlushReady(1);d.set_io_imsic_request_ready(1);d.set_io_loadPrecheck_stable(1);d.set_io_memory_request_ready(1);d.set_reset(1);d.step();d.step();d.set_reset(0);for(int j=0;j<6;++j)tick(0,0,false,false);}
 std::array<bool,2> tick(uint32_t a,uint32_t b,bool av=true,bool bv=true){
 d.set_instruction0$$valid(av);d.set_instruction1$$valid(bv);d.set_instruction0$$bits(a);d.set_instruction1$$bits(b);d.set_pc0(pc);d.set_pc1(pc+4);
 if(d.get_io_vmFlush()&&!flushLast)++epoch;flushLast=d.get_io_vmFlush();d.set_io_loadPrecheck_epoch(epoch);d.set_io_posted_contextEpoch(epoch);d.set_io_loadPrecheck_response_bits_epoch(epoch);d.set_io_loadPrecheck_response_bits_physicalAddress(pa);d.set_io_loadPrecheck_response_valid(virtualMode);
 d.set_io_canonicalStore_checked_valid(bool(certificate));if(certificate){auto c=*certificate;d.set_io_canonicalStore_checked_bits_origin_token_index(c.index);d.set_io_canonicalStore_checked_bits_origin_token_tag(c.tag);d.set_io_canonicalStore_checked_bits_origin_epoch(c.epoch);d.set_io_canonicalStore_checked_bits_virtualAddress(c.va);d.set_io_canonicalStore_checked_bits_physicalAddress(c.pa);d.set_io_canonicalStore_checked_bits_size(c.size);d.set_io_canonicalStore_checked_bits_mask(c.mask);}certificate.reset();
 bool enable=cycle<40||((cycle+seed)%11>=2);d.set_io_commitEnable(enable);bool rv=!replies.empty()&&replies.front().due<=cycle;d.set_io_memory_response_valid(rv);d.set_io_memory_response_bits_data(rv?replies.front().data:0);d.set_io_memory_response_bits_returnHandle(rv?replies.front().handle:0);bool ready=(cycle+seed)%7!=0;d.set_io_memory_request_ready(ready);
 d.step();observe();checkReplay();if(d.get_observation$$replayValid()){++replayEvents;unsigned ri=d.get_observation$$replayIndex();require(rows[ri].owner&&rows[ri].owner->memory&&!rows[ri].owner->store&&!rows[ri].owner->atomic&&(d.get_observation$$canonical()>>ri&1)&&!(d.get_observation$$pending()>>ri&1)&&(d.get_observation$$live()>>ri&1),"replay selected an unauthorized metadata row");}if(d.get_io_redirect_valid())++recoveries;unsigned killMask=d.get_observation$$killed();if(killMask){for(auto it=live.begin();it!=live.end();){if(killMask>>it->index&1){it=live.erase(it);++cancelled;}else ++it;}expected=committed;for(auto &o:live)if(o.writes)expected[o.rd]=o.result;}
 if(virtualMode&&d.get_io_loadPrecheck_request_valid())require(d.get_io_loadPrecheck_request_bits_address()==va,"precheck static mapping miss must not be hit");
 std::array<bool,2> acc{bool(d.get_io_renamed_0_valid()),bool(d.get_io_renamed_1_valid())};
 for(unsigned n=0;n<2;++n)if(acc[n]){require(n?bv:av,"unexpected allocation");Owner o=interpret(n?b:a);o.index=n?d.get_io_renamed_1_bits_token_index():d.get_io_renamed_0_bits_token_index();o.tag=n?d.get_io_renamed_1_bits_token_tag():d.get_io_renamed_0_bits_token_tag();if(rows[o.index].owner){require(rows[o.index].owner->tag!=o.tag,"tag reused unchanged");++reuses;}rows[o.index]={o,false,0,0};seenRows|=1u<<o.index;live.push_back(o);++accepted;pc+=4;}
 if(rv&&d.get_io_memory_response_ready()){replies.pop_front();++responses;}
 if(ready&&d.get_io_memory_request_valid()){uint64_t a=d.get_io_memory_request_bits_address();bool wr=d.get_io_memory_request_bits_write();unsigned h=d.get_io_memory_request_bits_returnHandle();bool virt=d.get_io_memory_request_bits_virtualized();if(virt){require(virtualMode&&a==va,"virtual service address mismatch");a=pa;}else if(virtualMode)require(a==pa,"prechecked physical mapping mismatch");bool atom=d.get_io_memory_request_bits_atomic();uint64_t result=beat(a);if(atom){require(d.get_io_memory_request_bits_atomicOp()==0&&d.get_io_memory_request_bits_size()==3,"AMO service opcode mismatch");uint64_t v=result+d.get_io_memory_request_bits_data();for(unsigned j=0;j<8;++j)bytes[a+j]=v>>(8*j);}else if(wr){uint64_t data=d.get_io_memory_request_bits_data();unsigned mask=d.get_io_memory_request_bits_mask();for(unsigned i=0;i<8;++i)if(mask>>i&1)bytes[(a&~7ULL)+i]=data>>(8*i);}if(virt&&wr&&!atom){require(d.get_io_canonicalStore_requestOrigin_valid(),"virtual store origin absent");certificate=Certificate{d.get_io_canonicalStore_requestOrigin_bits_token_index(),d.get_io_canonicalStore_requestOrigin_bits_token_tag(),d.get_io_canonicalStore_requestOrigin_bits_epoch(),va,pa,d.get_io_memory_request_bits_size(),d.get_io_memory_request_bits_mask()};if(d.get_io_canonicalStore_requestFrozenProof_valid())require(d.get_io_canonicalStore_requestFrozenProof_bits_physicalAddress()==pa&&d.get_io_canonicalStore_requestFrozenProof_bits_address()==va,"frozen store differs from independent translation");}
 replies.push_back({cycle+3+seed%5,atom?result:wr?0:beat(a),h});++requests;}
#define COMMIT(N) if(d.get_io_commit_##N##_valid()){require(!live.empty(),"unexpected commit");auto o=live.front();live.pop_front();require(o.index==d.get_io_commit_##N##_bits_token_index()&&o.tag==d.get_io_commit_##N##_bits_token_tag(),"out-of-order commit");require(bool(d.get_io_commit_##N##_bits_writesRd())==o.writes,"commit class mismatch");if(o.writes&&d.get_io_commit_##N##_bits_data()!=o.result){std::cerr<<"COMMIT pc="<<std::hex<<o.pc<<" expected="<<o.result<<" got="<<d.get_io_commit_##N##_bits_data()<<std::dec<<" cycle="<<cycle<<"\n";throw std::runtime_error("independent instruction result mismatch");}if(o.writes)committed[o.rd]=o.result;++retired;}
 COMMIT(0) COMMIT(1)
#undef COMMIT
 trace<<cycle<<" "<<unsigned(acc[0])<<unsigned(acc[1])<<" "<<unsigned(d.get_io_occupancy())<<" "<<unsigned(d.get_observation$$startFire())<<" "<<unsigned(d.get_observation$$actualIndex())<<" "<<unsigned(d.get_observation$$replayValid())<<" "<<unsigned(d.get_observation$$replayIndex())<<" "<<unsigned(d.get_io_commit_0_valid())<<unsigned(d.get_io_commit_1_valid())<<" "<<unsigned(d.get_io_memory_request_valid())<<" "<<d.get_io_memory_request_bits_address()<<"\n";
 snapshot(d,trace);
 ++cycle;require(cycle<12000,"timeout");return acc;}
 void run(const std::vector<uint32_t>&code){unsigned pos=0;while(pos<code.size()){auto x=tick(code[pos],pos+1<code.size()?code[pos+1]:0,true,pos+1<code.size());require(!x[1]||x[0],"non-prefix admission");pos+=x[0]+x[1];}while(!live.empty()||!replies.empty())tick(0,0,false,false);for(unsigned i=0;i<12;++i)tick(0,0,false,false);}
 void constant(unsigned rd,uint64_t value){std::vector<uint32_t> c{addi(rd,0,(value>>60)&15)};for(int j=56;j>=0;j-=4){c.push_back(shift(rd,rd,4));c.push_back(addi(rd,rd,(value>>j)&15));}run(c);}
 void csr(unsigned n,uint64_t v){constant(31,v);run({(n<<20)|(31<<15)|(1<<12)|0x73});}
 void replayTest(){run({addi(26,0,1)});for(unsigned n=0;n<4;++n)run({(1u<<25)|(26u<<20)|(1u<<15)|(4u<<12)|(3u<<7)|0x33,load(5,3,0),load(6,1,0)});run({addi(26,0,3)});}
 void killTest(){uint32_t branch=(25u<<20)|(25u<<15)|(4u<<8)|0x63;for(unsigned i=0;i<12;++i){run({branch,store(1,64,2),store(1,72,2),load(12,1,320),addi(22,0,8)});run({addi(23,0,i)});}}
 void virtualTest(){csr(0x3b0,(1ULL<<54)-1);csr(0x3a0,0x1f);csr(0x180,(8ULL<<60)|0x80000);csr(0x300,(1ULL<<17)|(1ULL<<11));require(d.get_io_vmState_dataPrivilege()==1&&d.get_io_vmState_satp()==((8ULL<<60)|0x80000)&&d.get_io_pmpState_cfg_0()==0x1f&&d.get_io_pmpState_addr_0()==((1ULL<<54)-1),"independent VM and PMP setup check failed");virtualMode=true;constant(4,va);run({store(4,0,2)});run({load(10,4,0)});run({(1u<<25)|(26u<<20)|(25u<<15)|(4u<<12)|(28u<<7)|0x33,load(11,4,0),store(4,0,2)});}
 void checkReplay(){std::optional<unsigned> winner;unsigned checked=d.backend$orderCheckIndex;
 if(d.backend$orderCheckValid&&(d.get_observation$$live()>>checked&1)){
  require(rows[checked].owner&&rows[checked].owner->tag==d.backend$orderCheckTag&&rows[checked].known,"checked replay owner lacks independently tracked canonical load");
  require((rows[checked].address>>3)==d.backend$orderCheckBeat&&rows[checked].lanes==d.backend$orderCheckLanes,"registered check metadata differs from independently accepted load");
  bool younger=false;for(auto&o:live){if(o.index==checked&&o.tag==d.backend$orderCheckTag){younger=true;continue;}if(younger&&o.memory&&!o.store&&!o.atomic&&rows[o.index].known&&rows[o.index].canonical&&!(d.get_observation$$pending()>>o.index&1)&&(d.get_observation$$live()>>o.index&1)&&(rows[o.index].address>>3)==(rows[checked].address>>3)&&(rows[o.index].lanes&rows[checked].lanes)){winner=o.index;break;}}
 }
 require(bool(winner)==bool(d.get_observation$$replayValid()),"independent replay valid mismatch");if(winner)require(*winner==d.get_observation$$replayIndex(),"independent oldest replay winner mismatch");}
 void report(){std::cout<<"RESULT seed="<<seed<<" cycles="<<cycle<<" accepted="<<accepted<<" retired="<<retired<<" loads="<<loads<<" prep="<<preps<<" atomic="<<atomic<<" replayEvents="<<replayEvents<<" noncanonicalLoads="<<noncanonicalLoads<<" cancelled="<<cancelled<<" recoveries="<<recoveries<<" killedCapture="<<killedCapture<<" atomicHeld="<<atomicHeld<<" virtualStores="<<virtualStores<<" prechecked="<<prechecked<<" storeStarts="<<stores<<" dual="<<dual<<" triple="<<triple<<" stateChecks="<<holds<<" reuse="<<reuses<<" rows="<<seenRows<<" requests="<<requests<<" responses="<<responses<<"\n";require(accepted==retired+cancelled&&loads&&preps&&reuses&&seenRows==65535,"basic coverage missing");require(triple&&dual&&atomic&&killedCapture&&virtualStores&&prechecked&&noncanonicalLoads&&replayEvents,"required directed witness missing");}
};
int main(int argc,char**argv){try{require(argc==3,"seed trace required");unsigned seed=std::stoul(argv[1]);Bench b(seed,argv[2]);b.run({addi(1,0,0x401),shift(1,1,21),addi(2,0,90),addi(25,0,157),addi(26,0,3)});std::vector<uint32_t> code;for(unsigned n=0;n<48;++n){unsigned z=n%4;code.push_back(load(8+n%8,1,256+(n%8)*8,z));if(seed%2)code.push_back(addi(20+(n%4),0,n));code.push_back(store(1,(n%16)*8,2,z));code.push_back(store(1,128+(n%16)*8,2,z));if(!(seed%2))code.push_back(addi(20+(n%4),0,n));}b.run(code);b.run({addi(4,1,512),(2u<<20)|(4u<<15)|(3u<<12)|(12u<<7)|0x2f});b.replayTest();b.killTest();b.virtualTest();b.report();return 0;}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}}
