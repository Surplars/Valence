#include "unissued_guard_fixture.hpp"
struct WithoutStoredIndex { uint64_t board$platform$core$core$core$backend$queue$$renamed$$token$$tag[64]{}; };
struct StaleLedger : Guard {uint64_t ledgerTag(unsigned i)const{return Guard::ledgerTag(i)^(1ULL<<63);}};
int main(int argc,char**argv){try{
 if(argc==2){const std::string mode=argv[1];
  if(mode=="--bad-index"){WithoutStoredIndex d;unissued::Access<WithoutStoredIndex> a{d};a.tokenIndex(64);}
  else if(mode=="--stale-tag"){StaleLedger s;s.n=1;unissued::readAccess(s,canonical_overlap::Sample{});}
  else if(mode=="--bad-class"){Observer x;auto q=state();x.sample(q,control(),100,true);q.owners[1].store=false;x.sample(q,control(),101,true);}
  else throw std::runtime_error("unknown negative mode");
  throw std::runtime_error("requested negative escaped its intended oracle");
 }

 canonical_overlap::Sample empty;Guard g;readAccess(g,empty);need(!g.payloadReads,"zero-owner payload read");g.n=1;readAccess(g,empty);g.pendingValue=true;readAccess(g,empty);
 WithoutStoredIndex d;unissued::Access<WithoutStoredIndex> a{d};
 for(unsigned i=0;i<64;++i){d.board$platform$core$core$core$backend$queue$$renamed$$token$$tag[i]=(1ULL<<63)+i;need(a.tokenIndex(i)==i&&a.tokenTag(i)==(1ULL<<63)+i,"fixed slot changed raw full tag");}
 bool bad=false;try{a.tokenIndex(64);}catch(const std::runtime_error&){bad=true;}need(bad,"out-of-geometry index escaped");
 StaleLedger stale;stale.n=1;bad=false;try{unissued::readAccess(stale,canonical_overlap::Sample{});}catch(const std::runtime_error&){bad=true;}need(bad,"stale ledger tag bit63 escaped");
 setenv("UNISSUED_STORE_TRACE","/tmp/resource-index-class-negative.jsonl",1);bad=false;
 try{Observer x;auto q=state();x.sample(q,control(),100,true);q.owners[1].store=false;x.sample(q,control(),101,true);}catch(const std::runtime_error&){bad=true;}need(bad,"live owner class mutation escaped");
 std::cout<<"RESOURCE_INDEX_HOST_PASS fixed64=1 raw_tag64=1 missing_backing_index=1 invalid_index_rejected=1 stale_bit63_rejected=1 live_class_mutation_rejected=1\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
