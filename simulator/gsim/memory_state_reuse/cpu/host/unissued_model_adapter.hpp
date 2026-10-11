#pragma once
#include "unissued_observer.hpp"
namespace unissued {
template<class D> struct Access {
 D& d;
 uint64_t killed(unsigned i)const{return d.board$platform$core$core$core$backend$killed[i];}
 uint64_t pending(unsigned i)const{return d.board$platform$core$core$core$backend$pending[i];}
 uint64_t memoryLive(unsigned i)const{return d.board$platform$core$core$core$backend$memoryLive[i];}
 uint64_t addressKnown(unsigned i)const{return d.board$platform$core$core$core$backend$storeAddressKnown[i];}
 uint64_t prepared(unsigned i)const{return d.board$platform$core$core$core$backend$storePrepared[i];}
 uint64_t address(unsigned i)const{return d.board$platform$core$core$core$backend$storeAddress[i];}
 uint64_t memoryCanonical(unsigned i)const{return d.board$platform$core$core$core$backend$memoryCanonical[i];}
 uint64_t tokenIndex(unsigned i)const{
#if RECONSTRUCT_ISSUE_TOKEN_INDEX
  static_assert(capacity::robEntries==64,"fixed-index CPU observer requires the verified ROB64 profile");
  need(i<capacity::robEntries,"fixed queue index outside active geometry");return i;
#else
  return d.board$platform$core$core$core$backend$queue$$renamed$$token$$index[i];
#endif
 }
 uint64_t tokenTag(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$renamed$$token$$tag[i];}
 uint64_t source1(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$renamed$$source1[i];}
 uint64_t source2(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$renamed$$source2[i];}
 uint64_t destination(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$renamed$$destination[i];}
 uint64_t writesRd(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$renamed$$writesRd[i];}
 uint64_t moveAlias(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$renamed$$moveAlias[i];}
 uint64_t memory(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$request$$memory[i];}
 uint64_t store(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$request$$store[i];}
 uint64_t atomic(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$request$$atomic[i];}
 uint64_t system(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$request$$system[i];}
 uint64_t usePc(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$request$$usePc[i];}
 uint64_t useImmediate(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$request$$useImmediate[i];}
 uint64_t size(unsigned i)const{return d.board$platform$core$core$core$backend$queue$$request$$memorySize[i];}
 uint64_t ledgerTag(unsigned i)const{return d.board$platform$core$core$core$backend$ledger$entries$$tag[i];}
 uint64_t prfReady(unsigned i)const{return d.board$platform$core$core$core$backend$ready[i];}
 uint64_t ready1(unsigned i)const{switch(i){
 case 0:return d.board$platform$core$core$core$backend$ownerReady$ready1_0;
 case 1:return d.board$platform$core$core$core$backend$ownerReady$ready1_1;
 case 2:return d.board$platform$core$core$core$backend$ownerReady$ready1_2;
 case 3:return d.board$platform$core$core$core$backend$ownerReady$ready1_3;
 case 4:return d.board$platform$core$core$core$backend$ownerReady$ready1_4;
 case 5:return d.board$platform$core$core$core$backend$ownerReady$ready1_5;
 case 6:return d.board$platform$core$core$core$backend$ownerReady$ready1_6;
 case 7:return d.board$platform$core$core$core$backend$ownerReady$ready1_7;
 case 8:return d.board$platform$core$core$core$backend$ownerReady$ready1_8;
 case 9:return d.board$platform$core$core$core$backend$ownerReady$ready1_9;
 case 10:return d.board$platform$core$core$core$backend$ownerReady$ready1_10;
 case 11:return d.board$platform$core$core$core$backend$ownerReady$ready1_11;
 case 12:return d.board$platform$core$core$core$backend$ownerReady$ready1_12;
 case 13:return d.board$platform$core$core$core$backend$ownerReady$ready1_13;
 case 14:return d.board$platform$core$core$core$backend$ownerReady$ready1_14;
 case 15:return d.board$platform$core$core$core$backend$ownerReady$ready1_15;
#if ROB_ENTRIES > 16
 case 16:return d.board$platform$core$core$core$backend$ownerReady$ready1_16;
 case 17:return d.board$platform$core$core$core$backend$ownerReady$ready1_17;
 case 18:return d.board$platform$core$core$core$backend$ownerReady$ready1_18;
 case 19:return d.board$platform$core$core$core$backend$ownerReady$ready1_19;
 case 20:return d.board$platform$core$core$core$backend$ownerReady$ready1_20;
 case 21:return d.board$platform$core$core$core$backend$ownerReady$ready1_21;
 case 22:return d.board$platform$core$core$core$backend$ownerReady$ready1_22;
 case 23:return d.board$platform$core$core$core$backend$ownerReady$ready1_23;
 case 24:return d.board$platform$core$core$core$backend$ownerReady$ready1_24;
 case 25:return d.board$platform$core$core$core$backend$ownerReady$ready1_25;
 case 26:return d.board$platform$core$core$core$backend$ownerReady$ready1_26;
 case 27:return d.board$platform$core$core$core$backend$ownerReady$ready1_27;
 case 28:return d.board$platform$core$core$core$backend$ownerReady$ready1_28;
 case 29:return d.board$platform$core$core$core$backend$ownerReady$ready1_29;
 case 30:return d.board$platform$core$core$core$backend$ownerReady$ready1_30;
 case 31:return d.board$platform$core$core$core$backend$ownerReady$ready1_31;
#if ROB_ENTRIES > 32
 case 32:return d.board$platform$core$core$core$backend$ownerReady$ready1_32;
 case 33:return d.board$platform$core$core$core$backend$ownerReady$ready1_33;
 case 34:return d.board$platform$core$core$core$backend$ownerReady$ready1_34;
 case 35:return d.board$platform$core$core$core$backend$ownerReady$ready1_35;
 case 36:return d.board$platform$core$core$core$backend$ownerReady$ready1_36;
 case 37:return d.board$platform$core$core$core$backend$ownerReady$ready1_37;
 case 38:return d.board$platform$core$core$core$backend$ownerReady$ready1_38;
 case 39:return d.board$platform$core$core$core$backend$ownerReady$ready1_39;
 case 40:return d.board$platform$core$core$core$backend$ownerReady$ready1_40;
 case 41:return d.board$platform$core$core$core$backend$ownerReady$ready1_41;
 case 42:return d.board$platform$core$core$core$backend$ownerReady$ready1_42;
 case 43:return d.board$platform$core$core$core$backend$ownerReady$ready1_43;
 case 44:return d.board$platform$core$core$core$backend$ownerReady$ready1_44;
 case 45:return d.board$platform$core$core$core$backend$ownerReady$ready1_45;
 case 46:return d.board$platform$core$core$core$backend$ownerReady$ready1_46;
 case 47:return d.board$platform$core$core$core$backend$ownerReady$ready1_47;
 case 48:return d.board$platform$core$core$core$backend$ownerReady$ready1_48;
 case 49:return d.board$platform$core$core$core$backend$ownerReady$ready1_49;
 case 50:return d.board$platform$core$core$core$backend$ownerReady$ready1_50;
 case 51:return d.board$platform$core$core$core$backend$ownerReady$ready1_51;
 case 52:return d.board$platform$core$core$core$backend$ownerReady$ready1_52;
 case 53:return d.board$platform$core$core$core$backend$ownerReady$ready1_53;
 case 54:return d.board$platform$core$core$core$backend$ownerReady$ready1_54;
 case 55:return d.board$platform$core$core$core$backend$ownerReady$ready1_55;
 case 56:return d.board$platform$core$core$core$backend$ownerReady$ready1_56;
 case 57:return d.board$platform$core$core$core$backend$ownerReady$ready1_57;
 case 58:return d.board$platform$core$core$core$backend$ownerReady$ready1_58;
 case 59:return d.board$platform$core$core$core$backend$ownerReady$ready1_59;
 case 60:return d.board$platform$core$core$core$backend$ownerReady$ready1_60;
 case 61:return d.board$platform$core$core$core$backend$ownerReady$ready1_61;
 case 62:return d.board$platform$core$core$core$backend$ownerReady$ready1_62;
 case 63:return d.board$platform$core$core$core$backend$ownerReady$ready1_63;
#endif
#endif
 default:throw std::runtime_error("unissued scalar index");}}
 uint64_t ready2(unsigned i)const{switch(i){
 case 0:return d.board$platform$core$core$core$backend$ownerReady$ready2_0;
 case 1:return d.board$platform$core$core$core$backend$ownerReady$ready2_1;
 case 2:return d.board$platform$core$core$core$backend$ownerReady$ready2_2;
 case 3:return d.board$platform$core$core$core$backend$ownerReady$ready2_3;
 case 4:return d.board$platform$core$core$core$backend$ownerReady$ready2_4;
 case 5:return d.board$platform$core$core$core$backend$ownerReady$ready2_5;
 case 6:return d.board$platform$core$core$core$backend$ownerReady$ready2_6;
 case 7:return d.board$platform$core$core$core$backend$ownerReady$ready2_7;
 case 8:return d.board$platform$core$core$core$backend$ownerReady$ready2_8;
 case 9:return d.board$platform$core$core$core$backend$ownerReady$ready2_9;
 case 10:return d.board$platform$core$core$core$backend$ownerReady$ready2_10;
 case 11:return d.board$platform$core$core$core$backend$ownerReady$ready2_11;
 case 12:return d.board$platform$core$core$core$backend$ownerReady$ready2_12;
 case 13:return d.board$platform$core$core$core$backend$ownerReady$ready2_13;
 case 14:return d.board$platform$core$core$core$backend$ownerReady$ready2_14;
 case 15:return d.board$platform$core$core$core$backend$ownerReady$ready2_15;
#if ROB_ENTRIES > 16
 case 16:return d.board$platform$core$core$core$backend$ownerReady$ready2_16;
 case 17:return d.board$platform$core$core$core$backend$ownerReady$ready2_17;
 case 18:return d.board$platform$core$core$core$backend$ownerReady$ready2_18;
 case 19:return d.board$platform$core$core$core$backend$ownerReady$ready2_19;
 case 20:return d.board$platform$core$core$core$backend$ownerReady$ready2_20;
 case 21:return d.board$platform$core$core$core$backend$ownerReady$ready2_21;
 case 22:return d.board$platform$core$core$core$backend$ownerReady$ready2_22;
 case 23:return d.board$platform$core$core$core$backend$ownerReady$ready2_23;
 case 24:return d.board$platform$core$core$core$backend$ownerReady$ready2_24;
 case 25:return d.board$platform$core$core$core$backend$ownerReady$ready2_25;
 case 26:return d.board$platform$core$core$core$backend$ownerReady$ready2_26;
 case 27:return d.board$platform$core$core$core$backend$ownerReady$ready2_27;
 case 28:return d.board$platform$core$core$core$backend$ownerReady$ready2_28;
 case 29:return d.board$platform$core$core$core$backend$ownerReady$ready2_29;
 case 30:return d.board$platform$core$core$core$backend$ownerReady$ready2_30;
 case 31:return d.board$platform$core$core$core$backend$ownerReady$ready2_31;
#if ROB_ENTRIES > 32
 case 32:return d.board$platform$core$core$core$backend$ownerReady$ready2_32;
 case 33:return d.board$platform$core$core$core$backend$ownerReady$ready2_33;
 case 34:return d.board$platform$core$core$core$backend$ownerReady$ready2_34;
 case 35:return d.board$platform$core$core$core$backend$ownerReady$ready2_35;
 case 36:return d.board$platform$core$core$core$backend$ownerReady$ready2_36;
 case 37:return d.board$platform$core$core$core$backend$ownerReady$ready2_37;
 case 38:return d.board$platform$core$core$core$backend$ownerReady$ready2_38;
 case 39:return d.board$platform$core$core$core$backend$ownerReady$ready2_39;
 case 40:return d.board$platform$core$core$core$backend$ownerReady$ready2_40;
 case 41:return d.board$platform$core$core$core$backend$ownerReady$ready2_41;
 case 42:return d.board$platform$core$core$core$backend$ownerReady$ready2_42;
 case 43:return d.board$platform$core$core$core$backend$ownerReady$ready2_43;
 case 44:return d.board$platform$core$core$core$backend$ownerReady$ready2_44;
 case 45:return d.board$platform$core$core$core$backend$ownerReady$ready2_45;
 case 46:return d.board$platform$core$core$core$backend$ownerReady$ready2_46;
 case 47:return d.board$platform$core$core$core$backend$ownerReady$ready2_47;
 case 48:return d.board$platform$core$core$core$backend$ownerReady$ready2_48;
 case 49:return d.board$platform$core$core$core$backend$ownerReady$ready2_49;
 case 50:return d.board$platform$core$core$core$backend$ownerReady$ready2_50;
 case 51:return d.board$platform$core$core$core$backend$ownerReady$ready2_51;
 case 52:return d.board$platform$core$core$core$backend$ownerReady$ready2_52;
 case 53:return d.board$platform$core$core$core$backend$ownerReady$ready2_53;
 case 54:return d.board$platform$core$core$core$backend$ownerReady$ready2_54;
 case 55:return d.board$platform$core$core$core$backend$ownerReady$ready2_55;
 case 56:return d.board$platform$core$core$core$backend$ownerReady$ready2_56;
 case 57:return d.board$platform$core$core$core$backend$ownerReady$ready2_57;
 case 58:return d.board$platform$core$core$core$backend$ownerReady$ready2_58;
 case 59:return d.board$platform$core$core$core$backend$ownerReady$ready2_59;
 case 60:return d.board$platform$core$core$core$backend$ownerReady$ready2_60;
 case 61:return d.board$platform$core$core$core$backend$ownerReady$ready2_61;
 case 62:return d.board$platform$core$core$core$backend$ownerReady$ready2_62;
 case 63:return d.board$platform$core$core$core$backend$ownerReady$ready2_63;
#endif
#endif
 default:throw std::runtime_error("unissued scalar index");}}
 uint64_t safeRaw(unsigned i)const{switch(i){
 case 0:return d.board$platform$core$core$core$backend$storeSafeRange_0;
 case 1:return d.board$platform$core$core$core$backend$storeSafeRange_1;
 case 2:return d.board$platform$core$core$core$backend$storeSafeRange_2;
 case 3:return d.board$platform$core$core$core$backend$storeSafeRange_3;
 case 4:return d.board$platform$core$core$core$backend$storeSafeRange_4;
 case 5:return d.board$platform$core$core$core$backend$storeSafeRange_5;
 case 6:return d.board$platform$core$core$core$backend$storeSafeRange_6;
 case 7:return d.board$platform$core$core$core$backend$storeSafeRange_7;
 case 8:return d.board$platform$core$core$core$backend$storeSafeRange_8;
 case 9:return d.board$platform$core$core$core$backend$storeSafeRange_9;
 case 10:return d.board$platform$core$core$core$backend$storeSafeRange_10;
 case 11:return d.board$platform$core$core$core$backend$storeSafeRange_11;
 case 12:return d.board$platform$core$core$core$backend$storeSafeRange_12;
 case 13:return d.board$platform$core$core$core$backend$storeSafeRange_13;
 case 14:return d.board$platform$core$core$core$backend$storeSafeRange_14;
 case 15:return d.board$platform$core$core$core$backend$storeSafeRange_15;
#if ROB_ENTRIES > 16
 case 16:return d.board$platform$core$core$core$backend$storeSafeRange_16;
 case 17:return d.board$platform$core$core$core$backend$storeSafeRange_17;
 case 18:return d.board$platform$core$core$core$backend$storeSafeRange_18;
 case 19:return d.board$platform$core$core$core$backend$storeSafeRange_19;
 case 20:return d.board$platform$core$core$core$backend$storeSafeRange_20;
 case 21:return d.board$platform$core$core$core$backend$storeSafeRange_21;
 case 22:return d.board$platform$core$core$core$backend$storeSafeRange_22;
 case 23:return d.board$platform$core$core$core$backend$storeSafeRange_23;
 case 24:return d.board$platform$core$core$core$backend$storeSafeRange_24;
 case 25:return d.board$platform$core$core$core$backend$storeSafeRange_25;
 case 26:return d.board$platform$core$core$core$backend$storeSafeRange_26;
 case 27:return d.board$platform$core$core$core$backend$storeSafeRange_27;
 case 28:return d.board$platform$core$core$core$backend$storeSafeRange_28;
 case 29:return d.board$platform$core$core$core$backend$storeSafeRange_29;
 case 30:return d.board$platform$core$core$core$backend$storeSafeRange_30;
 case 31:return d.board$platform$core$core$core$backend$storeSafeRange_31;
#if ROB_ENTRIES > 32
 case 32:return d.board$platform$core$core$core$backend$storeSafeRange_32;
 case 33:return d.board$platform$core$core$core$backend$storeSafeRange_33;
 case 34:return d.board$platform$core$core$core$backend$storeSafeRange_34;
 case 35:return d.board$platform$core$core$core$backend$storeSafeRange_35;
 case 36:return d.board$platform$core$core$core$backend$storeSafeRange_36;
 case 37:return d.board$platform$core$core$core$backend$storeSafeRange_37;
 case 38:return d.board$platform$core$core$core$backend$storeSafeRange_38;
 case 39:return d.board$platform$core$core$core$backend$storeSafeRange_39;
 case 40:return d.board$platform$core$core$core$backend$storeSafeRange_40;
 case 41:return d.board$platform$core$core$core$backend$storeSafeRange_41;
 case 42:return d.board$platform$core$core$core$backend$storeSafeRange_42;
 case 43:return d.board$platform$core$core$core$backend$storeSafeRange_43;
 case 44:return d.board$platform$core$core$core$backend$storeSafeRange_44;
 case 45:return d.board$platform$core$core$core$backend$storeSafeRange_45;
 case 46:return d.board$platform$core$core$core$backend$storeSafeRange_46;
 case 47:return d.board$platform$core$core$core$backend$storeSafeRange_47;
 case 48:return d.board$platform$core$core$core$backend$storeSafeRange_48;
 case 49:return d.board$platform$core$core$core$backend$storeSafeRange_49;
 case 50:return d.board$platform$core$core$core$backend$storeSafeRange_50;
 case 51:return d.board$platform$core$core$core$backend$storeSafeRange_51;
 case 52:return d.board$platform$core$core$core$backend$storeSafeRange_52;
 case 53:return d.board$platform$core$core$core$backend$storeSafeRange_53;
 case 54:return d.board$platform$core$core$core$backend$storeSafeRange_54;
 case 55:return d.board$platform$core$core$core$backend$storeSafeRange_55;
 case 56:return d.board$platform$core$core$core$backend$storeSafeRange_56;
 case 57:return d.board$platform$core$core$core$backend$storeSafeRange_57;
 case 58:return d.board$platform$core$core$core$backend$storeSafeRange_58;
 case 59:return d.board$platform$core$core$core$backend$storeSafeRange_59;
 case 60:return d.board$platform$core$core$core$backend$storeSafeRange_60;
 case 61:return d.board$platform$core$core$core$backend$storeSafeRange_61;
 case 62:return d.board$platform$core$core$core$backend$storeSafeRange_62;
 case 63:return d.board$platform$core$core$core$backend$storeSafeRange_63;
#endif
#endif
 default:throw std::runtime_error("unissued scalar index");}}
 uint64_t capturedOwners(unsigned r)const{if(r==0)return d.board$platform$core$core$core$backend$capturedOwners_0;if(r==1)return d.board$platform$core$core$core$backend$capturedOwners_1;throw std::runtime_error("unissued capture rank");}
 uint64_t capturedIndex(unsigned r)const{if(r==0)return d.board$platform$core$core$core$backend$captured$$token$$index_0;if(r==1)return d.board$platform$core$core$core$backend$captured$$token$$index_1;throw std::runtime_error("unissued capture rank");}
 uint64_t capturedTag(unsigned r)const{if(r==0)return d.board$platform$core$core$core$backend$captured$$token$$tag_0;if(r==1)return d.board$platform$core$core$core$backend$captured$$token$$tag_1;throw std::runtime_error("unissued capture rank");}
 uint64_t capturedBase(unsigned r)const{if(r==0)return d.board$platform$core$core$core$backend$captured$$base_0;if(r==1)return d.board$platform$core$core$core$backend$captured$$base_1;throw std::runtime_error("unissued capture rank");}
 uint64_t capturedImmediate(unsigned r)const{if(r==0)return d.board$platform$core$core$core$backend$captured$$immediate_0;if(r==1)return d.board$platform$core$core$core$backend$captured$$immediate_1;throw std::runtime_error("unissued capture rank");}
 uint64_t capturedDataReady(unsigned r)const{if(r==0)return d.board$platform$core$core$core$backend$captured$$dataReady_0;if(r==1)return d.board$platform$core$core$core$backend$captured$$dataReady_1;throw std::runtime_error("unissued capture rank");}
 uint64_t head()const{return d.board$platform$core$core$core$backend$head;}
 uint64_t ledgerHead()const{return d.board$platform$core$core$core$backend$ledger$head;}
 uint64_t count()const{return d.board$platform$core$core$core$backend$ledger$count;}
 uint64_t busy()const{return d.board$platform$core$core$core$backend$storePreparationBusy;}
 uint64_t pc(unsigned i)const{if(i&1)return d.board$platform$core$core$core$backend$payload_1$pcBank1[i>>1];return d.board$platform$core$core$core$backend$payload_1$pcBank0[i>>1];}
 uint64_t satp()const{return d.board$platform$core$core$core$backend$systemUnit$satp;}
 uint64_t privilege()const{return d.board$platform$core$core$core$backend$systemUnit$privilege;}
};
template<class A> Sample readAccess(const A& a,const canonical_overlap::Sample& c){
 Sample s;if(c.reset)return s;
 s.head=a.head();s.robCount=a.count();need(s.head==a.ledgerHead()&&s.robCount<=capacity::robEntries,"unissued ledger/head contract");
 s.satp=a.satp();s.privilege=a.privilege();
 for(unsigned i=0;i<capacity::robEntries;++i){
  auto& x=s.owners[i];x.live=(capacity::age(i,s.head))<s.robCount;
  if(!x.live)continue;
  x.token={a.tokenIndex(i),a.tokenTag(i)};
  need(x.token.index==i&&x.token.tag==a.ledgerTag(i),"unissued live full-token mismatch");
  x.age=capacity::age(i,s.head);x.pc=a.pc(i);x.pending=a.pending(i);x.memoryLive=a.memoryLive(i);
  x.killed=a.killed(i);x.memory=a.memory(i);x.store=a.store(i);x.atomic=a.atomic(i);x.system=a.system(i);
  x.writesRd=a.writesRd(i);x.destination=a.destination(i);x.moveAlias=a.moveAlias(i);
  if(x.pending){
   x.sourcesKnown=true;x.source1=a.source1(i);x.source2=a.source2(i);need(x.source1<capacity::physicalRegs&&x.source2<capacity::physicalRegs,"unissued source range");
   x.ready1=a.ready1(i);x.ready2=a.ready2(i);x.prfReady1=a.prfReady(x.source1);x.prfReady2=a.prfReady(x.source2);
   need(x.ready1==x.prfReady1&&x.ready2==x.prfReady2,"unissued registered readiness differs from PRF");
   x.usePc=a.usePc(i);x.useImmediate=a.useImmediate(i);
  }
  if(x.memoryLive)x.memoryCanonical=a.memoryCanonical(i);
  if(x.memoryLive&&x.memory&&x.store){
   x.addressKnown=a.addressKnown(i);x.prepared=a.prepared(i);x.busy=(a.busy()>>i)&1;x.size=a.size(i);
   if(x.addressKnown){x.va=a.address(i);x.safeRaw=a.safeRaw(i);}
   need(!x.prepared||x.addressKnown,"unissued prepared without known address");
  }
 }
 for(unsigned r=0;r<2;++r){
  auto& z=s.captures[r];const auto mask=a.capturedOwners(r);if(!mask)continue;
  need((mask&(mask-1))==0,"unissued captured owner not onehot");
  z.token={a.capturedIndex(r),a.capturedTag(r)};need(z.token.index<capacity::robEntries&&mask==capacity::mask(z.token.index),"unissued capture mask/token mismatch");
  const auto& x=s.owners[z.token.index];
  if(!x.live||!x.pending||!x.memoryLive||x.killed||x.token!=z.token)continue;
  need(x.store&&x.memory,"unissued capture class");
  z.valid=true;z.va=a.capturedBase(r)+a.capturedImmediate(r);z.dataReady=a.capturedDataReady(r);
 }
 return s;
}
template<class D> Sample read(D& d,const canonical_overlap::Sample& c){return readAccess(Access<D>{d},c);}
}
