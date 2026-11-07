// Independent fetched-program driver. Architectural predictions decode the frozen
// RV64 instruction bytes and walk the frozen Sv39/Sv39x4 PTE bytes; no DUT table,
// decoder, reference component, expected commit ledger, or injected trap is used.
#include "GuardedGuestFpArithmeticGsim.h"
#include <array>

#include <cctype>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
using U=uint64_t;
using Fields=std::map<std::string,U>;
static U checks=0;
static void require(bool x,const std::string&s){
    ++checks;
    if(!x)throw std::runtime_error("GUARDED_GUEST_ARITHMETIC_CHECK["+s+"]");
}
static void equal(U a,U b,const std::string&s){
    if(a!=b){
        std::cerr<<s<<" actual=0x"<<std::hex<<a<<" expected=0x"<<b<<std::dec<<'\n';
    }
    require(a==b,s);
}
static U sext(U n,unsigned w){
    return U(int64_t(n<<(64-w))>>(64-w));
}
// Independent exact dyadic arithmetic in units of the smallest subnormal.
// No host floating point, HardFloat, DUT tables or expected result fixtures.
// 2176 bits cover two maximum finite binary64 magnitudes in minimum
// subnormal units (highest possible sum bit is 2098).
struct Magnitude {
    std::array<U,34> words{};
    explicit Magnitude(U n=0){words[0]=n;}
    bool bit(unsigned n)const{return n<2176 && ((words[n/64]>>(n%64))&1);}
    Magnitude shifted(unsigned n)const{
        Magnitude r;
        for(unsigned b=0;b+n<2176;++b)if(bit(b))r.words[(b+n)/64]|=1ULL<<((b+n)%64);
        return r;
    }
    int compare(const Magnitude&b)const{
        for(int n=33;n>=0;--n)if(words[n]!=b.words[n])return words[n]>b.words[n]?1:-1;
        return 0;
    }
    Magnitude plus(const Magnitude&b)const{
        Magnitude r; U carry=0;
        for(unsigned n=0;n<34;++n){unsigned __int128 v=(unsigned __int128)words[n]+b.words[n]+carry;r.words[n]=v;carry=v>>64;}
        require(!carry,"numeric_magnitude_capacity");return r;
    }
    Magnitude minus(const Magnitude&b)const{
        Magnitude r; U borrow=0;
        for(unsigned n=0;n<34;++n){U v=words[n]-b.words[n];U next=words[n]<b.words[n] || v<borrow;r.words[n]=v-borrow;borrow=next;}
        require(!borrow,"numeric_magnitude_nonnegative");return r;
    }
    unsigned top()const{for(int n=2175;n>=0;--n)if(bit(n))return n;return 0;}
    bool zero()const{for(U w:words)if(w)return false;return true;}
};
struct Numeric { U value,flags; };
static bool arithmetic(U i){return (i&127)==0x53 && (i>>25==0 || i>>25==1 || i>>25==4 || i>>25==5);}
static Numeric numeric(U i,U left,U right,U frm){
    unsigned width=(i>>25)&1?64:32, f=width==32?23:52, e=width==32?8:11;
    U signBit=1ULL<<(width-1), fracMask=(1ULL<<f)-1, expMask=(1ULL<<e)-1;
    U box=width==32?0xffffffff00000000ULL:0, qnan=(expMask<<f)|(1ULL<<(f-1));
    auto unpack=[&](U raw){return width==32?(raw>>32==0xffffffff?raw&0xffffffff:qnan):raw;};
    U a=unpack(left),b=unpack(right);
    unsigned rm=(i>>12)&7; if(rm==7)rm=frm;
    require(rm<5,"numeric_legal_rounding");
    auto exp=[&](U v){return (v>>f)&expMask;};
    auto nan=[&](U v){return exp(v)==expMask && (v&fracMask);};
    auto snan=[&](U v){return nan(v)&&!(v&(1ULL<<(f-1)));};
    if(nan(a)||nan(b))return {box|qnan,(snan(a)||snan(b))?16ULL:0ULL};
    if((i>>25)&4)b^=signBit;
    if(exp(a)==expMask || exp(b)==expMask){
        if(exp(a)==expMask && exp(b)==expMask && ((a^b)&signBit))return {box|qnan,16};
        return {box|(exp(a)==expMask?a:b),0};
    }
    auto exact=[&](U v){
        U exponent=exp(v),fraction=v&fracMask;
        return Magnitude(exponent?((1ULL<<f)|fraction):fraction).shifted(exponent?exponent-1:0);
    };
    Magnitude am=exact(a),bm=exact(b),sum;
    bool negative=a&signBit;
    if((a^b)&signBit){
        if(am.compare(bm)>=0)sum=am.minus(bm);
        else {sum=bm.minus(am);negative=b&signBit;}
    } else sum=am.plus(bm);
    if(sum.zero()){
        negative=(!(a&~signBit)&&!(b&~signBit)&&((a^b)&signBit)==0)?bool(a&signBit):rm==2;
        return {box|(negative?signBit:0),0};
    }
    unsigned top=sum.top(),shift=top>f?top-f:0;
    U mantissa=0;
    for(unsigned n=0;n<=f;++n)if(sum.bit(shift+n))mantissa|=1ULL<<n;
    bool nx=false,belowHalf=false;
    for(unsigned n=0;n<shift;++n)if(sum.bit(n)){nx=true;if(n+1<shift)belowHalf=true;}
    bool increment=false;
    if(nx){
        if(rm==2)increment=negative;
        if(rm==3)increment=!negative;
        if(rm==0 || rm==4)increment=sum.bit(shift-1)&&(belowHalf || rm==4 || (mantissa&1));
    }
    if(increment)++mantissa;
    if(mantissa==(1ULL<<(f+1))){mantissa>>=1;++shift;}
    U exponent=mantissa>fracMask?shift+1:0;
    if(exponent>=expMask){
        bool infinity=rm==0||rm==4||(rm==2&&negative)||(rm==3&&!negative);
        U magnitude=infinity?(expMask<<f):((expMask-1)<<f)|fracMask;
        return {box|(negative?signBit:0)|magnitude,5};
    }
    return {box|(negative?signBit:0)|(exponent<<f)|(mantissa&fracMask),nx?1ULL:0ULL};
}
static void numericSelfTest(){
    U count=0;
    auto test=[&](unsigned width,bool sub,unsigned rm,U a,U b,U value,U flags,unsigned frm=0){
        U instruction=(((sub?4:0)+(width==64))<<25)|(2<<20)|(1<<15)|(rm<<12)|(3<<7)|0x53;
        Numeric n=numeric(instruction,a,b,frm);
        equal(n.value,value,"selftest_numerical_bits"); equal(n.flags,flags,"selftest_numerical_flags");++count;
    };
    for(unsigned width:{32,64}){
        unsigned f=width==32?23:52,e=width==32?8:11;
        U box=width==32?0xffffffff00000000ULL:0,sign=1ULL<<(width-1);
        U one=((1ULL<<(e-1))-1)<<f,half=(((1ULL<<(e-1))-1)-f-1)<<f;
        U inf=((1ULL<<e)-1)<<f,qnan=inf|(1ULL<<(f-1));
        for(unsigned rm=0;rm<5;++rm){
            test(width,false,rm,box|one,box|half,box|one|U(rm==3||rm==4),1);
            test(width,true,7,box|sign|one,box|half,box|sign|one|U(rm==2||rm==4),1,rm);
            test(width,true,rm,box|one,box|one,box|(rm==2?sign:0),0);
        }
        test(width,false,0,box|sign,box|sign,box|sign,0);
        test(width,false,0,box|1,box|1,box|2,0);
        test(width,true,0,box|(1ULL<<f),box|((1ULL<<f)-1),box|1,0);
        test(width,false,0,box|qnan,box|one,box|qnan,0);
        test(width,true,0,box|inf|1,box|one,box|qnan,16);
        test(width,false,0,box|inf,box|sign|inf,box|qnan,16);
        test(width,true,0,box|inf,box|inf,box|qnan,16);
        test(width,false,0,box|(inf-1),box|(inf-1),box|inf,5);
        test(width,false,3,box|sign|(inf-1),box|sign|(inf-1),box|sign|(inf-1),5);
        test(width,false,3,box|one,box|half,box|one|1,1,7);
    }
    test(32,false,0,0x3f800000,0xffffffff7f800001ULL,0xffffffff7fc00000ULL,16);
    test(32,false,0,0x3f800000,0xffffffff3f800000ULL,0xffffffff7fc00000ULL,0);
    std::cout<<"GUARDED_GUEST_FP_ARITHMETIC_NUMERIC_SELFTEST_PASS cases="<<count<<"\n";
}
// Tiny input-only JSON reader. Recipe numbers are unsigned integers, never doubles.
struct Json {
    U number=0;
    std::string string;
    std::vector<Json> array;
    std::map<std::string,Json> object;
    const Json& at(const std::string&k)const{
        return object.at(k);
    }
};
struct Parser {
    std::string s;
    size_t p=0;
    void space(){
        while(p<s.size()&&isspace(static_cast<unsigned char>(s[p])))++p;
    }
    std::string str(){
        require(s.at(p++)=='"',"recipe_string");
        std::string v;
        while(s.at(p)!='"'){
            require(s.at(p)!='\\',"recipe_unescaped_string");
            v+=s.at(p++);
        }
        ++p;
        return v;
    }
    Json value(){
        space();
        Json j;
        char c=s.at(p);
        if(c=='{'){
            ++p;
            space();
            while(s.at(p)!='}'){
                auto k=str();
                space();
                require(s.at(p++)==':',"recipe_colon");
                j.object.emplace(k,value());
                space();
                if(s.at(p)!=',')break;
                ++p;
                space();
            }
            require(s.at(p++)=='}',"recipe_object");
        }
        else if(c=='['){
            ++p;
            space();
            while(s.at(p)!=']'){
                j.array.push_back(value());
                space();
                if(s.at(p)!=',')break;
                ++p;
            }
            require(s.at(p++)==']',"recipe_array");
        }
        else if(c=='"')j.string=str();
        else if(s.compare(p,4,"true")==0){
            p+=4;
            j.number=1;
        }
        else if(s.compare(p,5,"false")==0){
            p+=5;
        }
        else{
            size_t n=0;
            j.number=std::stoull(s.substr(p),&n);
            p+=n;
        }
        return j;
    }
};
struct Memory {
    std::map<U,uint8_t> b;
    U read(U a,unsigned n)const{
        U v=0;
        for(unsigned i=0;i<n;i++){
            auto it=b.find(a+i);
            require(it!=b.end(),"physical_address_mapped");
            v|=U(it->second)<<(8*i);
        }
        return v;
    }
    void write(U a,U v,unsigned n){
        for(unsigned i=0;i<n;i++)b[a+i]=v>>(8*i);
    }
};
struct Input {
    Json j;
    Memory initial;
    std::map<U,U> code;
    U reset=0,terminal=0,limit=0,traceLimit=0;
    explicit Input(const std::string&path){
        std::ifstream f(path);
        require(bool(f),"recipe_open");
        std::stringstream ss;
        ss<<f.rdbuf();
        Parser parser{
            ss.str()
        };
        j=parser.value();
        parser.space();
        equal(parser.p,parser.s.size(),"recipe_no_trailing_data");
        reset=j.at("reset_pc").number;
        terminal=j.at("terminal_pc").number;
        limit=j.at("cycle_limit").number;
        traceLimit=j.at("trace_bytes_limit").number;
        // Reviewed request-count margin; these are abort caps, not throughput claims.
        equal(limit,180000,"frozen_cycle_limit");
        equal(traceLimit,22ULL*1024*1024,"frozen_trace_limit");
        equal(j.at("native_timeout_seconds").number,120,"frozen_native_timeout");
        for(auto&a:j.at("zero_pages").array)for(unsigned n=0;n<4096;n++)initial.b[a.number+n]=0;
        for(auto key:{
            "program","ptes","bytes"
        })for(auto&a:j.at(key).array)initial.write(a.array.at(0).number,a.array.at(1).number,key==std::string("program")?4:key==std::string("ptes")?8:1);
        for(auto&a:j.at("code").array)code[a.array.at(0).number]=initial.read(a.array.at(1).number,4);
        require(code.size()<700,"bounded_program_words");
    }
};
struct State {
    std::array<U,44> v{
    };
    bool operator==(const State&)const=default;
};
static State state(SGuardedGuestFpArithmeticGsim&d){
    State a;
#define F(N) a.v[N]=d.get_io$$fpr_##N()
    F(0);
    F(1);
    F(2);
    F(3);
    F(4);
    F(5);
    F(6);
    F(7);
    F(8);
    F(9);
    F(10);
    F(11);
    F(12);
    F(13);
    F(14);
    F(15);
    F(16);
    F(17);
    F(18);
    F(19);
    F(20);
    F(21);
    F(22);
    F(23);
    F(24);
    F(25);
    F(26);
    F(27);
    F(28);
    F(29);
    F(30);
    F(31);
#undef F
#define S(I,N) a.v[I]=d.get_io$$##N()
    S(32,hostFs);
    S(33,guestFs);
    S(34,fcsr);
    S(35,virtualized);
    S(36,privilege);
    S(37,hstatus);
    S(38,htval);
    S(39,htinst);
    S(40,scause);
    S(41,sepc);
    S(42,stval);
    S(43,hostSd);
#undef S
    return a;
}
static Fields observe(SGuardedGuestFpArithmeticGsim&d){
    Fields o;
#define R(N) o[#N]=d.get_io$$##N()
    R(fpBusy);
    R(ownerActive);
    R(ownerToken$$index);
    R(ownerToken$$tag);
    R(contextMemoryEpoch);
    R(hMemoryEpoch);
    R(fpMemoryEpoch);
    R(retireMatches);
    R(statePhase);
    R(systemState);
    R(trapReady);
    R(recovering);
    R(memoryBusy);
    R(fpMemoryBusy);
    R(adapterIdle);
    R(translatorIdle);
    R(fetchAdapterIdle);
    R(fetchTranslatorIdle);
    R(assemblerIdle);
    R(responseBufferIdle);
    R(completionCount);
    R(memoryDrained);
    R(systemExecute);
    R(fpStartOffered);
    R(fpStartReady);
    R(systemStartReady);
    R(fpCompleteOffered);
    R(guestSd);
#define TOKEN(N) R(N##$$token$$index);R(N##$$token$$tag)
#define REQUEST(N) R(N##$$valid);TOKEN(N##$$bits);R(N##$$bits$$pc);R(N##$$bits$$instruction);R(N##$$bits$$operand);R(N##$$bits$$operand2)
    REQUEST(fpStart);
    REQUEST(systemStart);
    TOKEN(systemRequest);
    R(systemRequest$$pc);
    R(systemRequest$$instruction);
    R(systemRequest$$operand);
    R(systemRequest$$operand2);
#define FAULT(N) TOKEN(N);R(N##$$pc);R(N##$$cause);R(N##$$tval);R(N##$$guestFault$$guestPageFault);R(N##$$guestFault$$guestAddress);R(N##$$guestFault$$guestPhysicalAddress);R(N##$$guestFault$$implicitPte)
    R(trap$$valid);
    FAULT(trap$$bits);
    R(pendingException$$valid);
    FAULT(pendingException$$bits);
#define COMPLETE(N) TOKEN(N);R(N##$$data);R(N##$$nextPc);R(N##$$exception);R(N##$$cause);R(N##$$tval);R(N##$$guestFault$$guestPageFault);R(N##$$guestFault$$guestAddress);R(N##$$guestFault$$guestPhysicalAddress);R(N##$$guestFault$$implicitPte)
    R(fpComplete$$valid);
    COMPLETE(fpComplete$$bits);
    R(systemComplete$$valid);
    COMPLETE(systemComplete$$bits$$completion);
    R(systemComplete$$bits$$redirect);
    R(systemComplete$$bits$$invalidateFetch);
#define COMMIT(N) R(commit##N##$$valid);TOKEN(commit##N##$$bits);R(commit##N##$$bits$$pc);R(commit##N##$$bits$$instruction);R(commit##N##$$bits$$rd);R(commit##N##$$bits$$writesRd);R(commit##N##$$bits$$data);R(commit##N##$$bits$$nextPc)
    COMMIT(0);
    COMMIT(1);
    R(fpRetire$$valid);
    R(fpRetire$$bits$$index);
    R(fpRetire$$bits$$tag);
    R(mutation$$valid);
    R(mutation$$bits$$guest);
    R(fpCsrWrite$$valid);
    R(fpCsrWrite$$bits$$address);
    R(fpCsrWrite$$bits$$operation);
    R(fpCsrWrite$$bits$$write);
    R(fpCsrWrite$$bits$$value);
    R(hostFsWrite$$valid);
    R(hostFsWrite$$bits);
    R(hWrite$$valid);
    R(hWrite$$bits$$address);
    R(hWrite$$bits$$data);
#define READPORT(N) R(N##$$request$$valid);R(N##$$request$$bits);R(N##$$response$$ready)
    READPORT(instruction);
    READPORT(fetchPte);
    READPORT(dataPte);
    R(data$$request$$valid);
    R(data$$response$$ready);
    R(dataVirtualRequest$$valid);
    R(dataVirtualRequest$$bits$$address);
    R(dataVirtualRequest$$bits$$data);
    R(dataVirtualRequest$$bits$$mask);
    R(dataVirtualRequest$$bits$$write);
    R(dataVirtualRequest$$bits$$size);
    R(dataVirtualRequest$$bits$$virtualized);
    R(dataVirtualRequest$$bits$$atomic);
    R(dataVirtualRequest$$bits$$atomicOp);
    R(dataVirtualRequest$$bits$$precheckedLoad);
    R(dataVirtualRequest$$bits$$translationEpoch);
    R(dataVirtualRequest$$bits$$prefetchNextAllowed);
    R(dataVirtualRequest$$bits$$uncached);
#define DATA(N) R(data$$request$$bits$$##N)
    DATA(address);
    DATA(data);
    DATA(mask);
    DATA(write);
    DATA(size);
    DATA(virtualized);
    DATA(atomic);
    DATA(atomicOp);
    DATA(precheckedLoad);
    DATA(translationEpoch);
    DATA(prefetchNextAllowed);
    DATA(uncached);
#undef DATA
#undef READPORT
#undef COMMIT
#undef COMPLETE
#undef FAULT
#undef REQUEST
#undef TOKEN
#undef R
    // Invalid payloads have no semantic value. Normalize them explicitly so the
    // compact raw schema records every meaningful sample without stale garbage.
    // String-key ordering makes every matching prefix a contiguous map range.
    auto zeroPrefix=[&](const std::string& prefix) {
        for(auto it=o.lower_bound(prefix);it!=o.end()&&it->first.starts_with(prefix);++it)
            it->second=0;
    };
    for(const auto& prefix:{
        "fpStart","systemStart","fpComplete","systemComplete","trap","pendingException","commit0","commit1","fpRetire","mutation","fpCsrWrite","hostFsWrite","hWrite","dataVirtualRequest"
    })if(!o.at(std::string(prefix)+"$$valid"))zeroPrefix(std::string(prefix)+"$$bits");
    for(const auto& prefix:{
        "instruction","fetchPte","dataPte","data"
    })if(!o.at(std::string(prefix)+"$$request$$valid"))zeroPrefix(std::string(prefix)+"$$request$$bits");
    if(!o.at("systemExecute"))zeroPrefix("systemRequest$$");
    if(!o.at("ownerActive")){
        o["ownerToken$$index"]=0;
        o["ownerToken$$tag"]=0;
    }
    return o;
}
struct Port {
    bool valid=false,held=false;
    U data=0;
    unsigned delay=0,wait=0;
    std::vector<U> bits;
    U accepted=0,returned=0,stalls=0;
    bool ready(bool stagger)const{
        return !valid&&(!stagger||wait>=2);
    }
    void stable(bool offer,bool ready,const std::vector<U>&b){
        if(held){
            require(offer,"held_offer_valid");
            require(bits==b,"held_offer_stable");
        }
        held=offer&&!ready;
        if(held){
            bits=b;
            ++stalls;
            ++wait;
        }
    }
    void accept(U d,unsigned l){
        require(!valid,"single_response_owner");
        valid=true;
        data=d;
        delay=l;
        wait=0;
        ++accepted;
    }
    void consume(bool ready){
        if(valid&&!delay&&ready){
            valid=false;
            ++returned;
        }
    }
};
struct Fault {
    U cause=0,tval=0,gpa=0;
    bool gva=false,gp=false;
};
struct Walk {
    U physical=0;
    std::optional<Fault> fault;
};
struct Oracle {
    const Input&in;
    Memory memory;
    U pc;
    std::array<U,32>x{
    },f{
    };
    std::array<bool,32>initialized{
    };
    U fcsr=0,hostFs=0,guestFs=0;
    bool v=false;
    U priv=3;
    std::map<U,U>csr;
    U commits=0,traps=0,fpIssues=0,fpCompletions=0,fpRetires=0;
    U faultReleaseWait=0,csrFaultTraps=0;
    U hstatus=2ULL<<32;
    unsigned terminal=0;
    struct Owner {
        U index,tag,pc,inst,operand,value;
        bool writes;
        std::optional<Fault> fault;
        unsigned completions=0;
        U flags=0; bool guest=false;
    };
    std::optional<Owner>owner,eventOwner;
    std::vector<std::array<U,3>>actualStores,expectedStores;
    std::vector<U> walkReads;
    Oracle(const Input&i):in(i),memory(i.initial),pc(i.reset){
    }
    U gpa(U address,bool write,bool fetch,bool&denied){
        U table=(csr[0x680]&((1ULL<<44)-1))<<12;
        for(int level=2;level>=0;--level){
            unsigned bits=level==2?11:9;
            U slot=table+((address>>(12+level*9))&((1ULL<<bits)-1))*8;
            walkReads.push_back(slot);
            U p=memory.read(slot,8);
            bool valid=p&1,read=p&2,w=p&4,execute=p&8;
            if(!valid||(!read&&w)){
                denied=true;
                return 0;
            }
            if(read||execute){
                if(!(p&16)||!(p&64)||(write&&(!(p&128)||!w))||(fetch&&!execute)||(!write&&!fetch&&!read)){
                    denied=true;
                    return 0;
                }
                U low=(1ULL<<(12+level*9))-1;
                require(((p>>10)<<12&low)==0,"aligned_g_superpage");
                return ((p>>10)<<12)|(address&low);
            }
            table=(p>>10)<<12;
        }
        denied=true;
        return 0;
    }
    Walk translate(U va,bool write=false,bool fetch=false){
        if(!v)return {
            va,{
            }
        };
        U table=(csr[0x280]&((1ULL<<44)-1))<<12;
        for(int level=2;level>=0;--level){
            U pa=table+((va>>(12+level*9))&511)*8;
            bool denied=false;
            U physical=gpa(pa,false,false,denied);
            require(!denied,"recipe_vs_pte_g_readable");
            walkReads.push_back(physical);
            U p=memory.read(physical,8);
            bool r=p&2,w=p&4,e=p&8;
            require((p&1)&&(r||!w),"recipe_vs_pte_valid");
            if(r||e){
                require((p&64)&&(!write||((p&128)&&w))&&(!fetch||e)&&(write||fetch||r),"recipe_vs_leaf_permission");
                U low=(1ULL<<(12+level*9))-1;
                U guest=((p>>10)<<12)|(va&low);
                U dest=gpa(guest,write,fetch,denied);
                if(denied)return {
                    0,Fault{
                        write?23ULL:fetch?20ULL:21ULL,va,guest,true,true
                    }
                };
                return {
                    dest,{
                    }
                };
            }
            table=(p>>10)<<12;
        }
        throw std::runtime_error("VS walk exhausted");
    }
    U csrRead(U c)const{
        auto get=[&](U k){
            auto p=csr.find(k);
            return p==csr.end()?0ULL:p->second;
        };
        U fs=hostFs;
        auto status=[&](U fs,U base){
            return base|(fs<<13)|(fs==3?1ULL<<63:0);
        };
        switch(c){
            case 1:return fcsr&31;
            case 2:return fcsr>>5;
            case 3:return fcsr;
            case 0x100:return v?status(guestFs,(2ULL<<32)|(get(0x200)&0x122)):status(fs,(2ULL<<32)|(get(0x100)&0x122));
            case 0x200:return status(guestFs,(2ULL<<32)|(get(0x200)&0x122));
            case 0x300:return status(fs,(0xaULL<<32)|(get(0x300)&0x218aa));
            case 0x600:return hstatus;
            default:return get(c);
        }
    }
    std::optional<Fault> fault(U inst){
        unsigned op=inst&127;
        bool fp=op==7||op==0x27||op==0x53;
        bool fc=op==0x73&&((inst>>12)&7)&&((inst>>20)>=1&&(inst>>20)<=3);
        if((fp||fc)&&(!hostFs||(v&&!guestFs)))return Fault{
            2,inst,0,false,false
        };
        if(arithmetic(inst)){
            unsigned rm=(inst>>12)&7;
            if(rm==7)rm=fcsr>>5;
            if(rm>=5)return Fault{2,inst,0,false,false};
        }
        if(op==7||op==0x27){
            bool wr=op==0x27;
            U imm=wr?sext((inst>>25)<<5|((inst>>7)&31),12):sext(inst>>20,12);
            U address=x[(inst>>15)&31]+imm;
            if(address&7)return Fault{
                wr?6ULL:4ULL,address,0,v,false
            };
            return translate(address,wr).fault;
        }
        if(inst==0x73)return Fault{
            v?10ULL:priv==3?11ULL:9ULL,0,0,false,false
        };
        return {
        };
    }
    U fpValue(U i,U operand){
        unsigned op=i&127;
        if(arithmetic(i)){
            require(initialized[(i>>15)&31]&&initialized[(i>>20)&31],"arithmetic_initialized_inputs");
            return numeric(i,f[(i>>15)&31],f[(i>>20)&31],fcsr>>5).value;
        }
        if(op==7){
            auto w=translate(operand+sext(i>>20,12));
            require(!w.fault,"allowed_fp_load_translation");
            return memory.read(w.physical,8);
        }
        if((i&0xfff0707f)==0xf2000053)return operand;
        if((i&0xfff0707f)==0xe2000053){
            require(initialized[(i>>15)&31],"FP_move_reads_initialized_register");
            return f[(i>>15)&31];
        }
        if(op==0x27){
            require(initialized[(i>>20)&31],"FP_store_reads_initialized_register");
            return 0;
        }
        throw std::runtime_error("unplanned FP opcode");
    }
    void store(U address,U value){
        auto w=translate(address,true);
        require(!w.fault,"retired_store_translates");
        memory.write(w.physical,value,8);
        expectedStores.push_back({
            w.physical,value,255
        });
    }
    void commit(const Fields&o,const std::string&n,bool actual=true){
        if(actual&&!o.at(n+"$$valid"))return;
        U p=actual?o.at(n+"$$bits$$pc"):pc;
        U i=actual?o.at(n+"$$bits$$instruction"):in.code.at(pc);
        equal(p,pc,"commit_pc");
        equal(i,in.code.at(pc),"commit_instruction");
        require(!fault(i),"fault_must_not_retire");
        unsigned op=i&127,rd=(i>>7)&31,a=(i>>15)&31,b=(i>>20)&31,fun=(i>>12)&7;
        U val=0,next=pc+4;
        bool writes=rd;
        if(op==0x13){
            if(fun==0)val=x[a]+sext(i>>20,12);
            else if(fun==1)val=x[a]<<((i>>20)&63);
            else throw std::runtime_error("OPIMM subset");
        }
        else if(op==3){
            auto w=translate(x[a]+sext(i>>20,12));
            require(!w.fault,"integer_load_translates");
            val=memory.read(w.physical,8);
        }
        else if(op==0x23){
            writes=false;
            store(x[a]+sext((i>>25)<<5|((i>>7)&31),12),x[b]);
        }
        else if(op==7||op==0x27||op==0x53){
            require(owner.has_value(),"FP_retirement_has_owner");
            val=owner->value;
            if(op==0x27){
                writes=false;
                store(x[a]+sext((i>>25)<<5|((i>>7)&31),12),f[b]);
            }
            else if(op==7||(i&0xfff0707f)==0xf2000053||arithmetic(i)){
                writes=false;
                f[rd]=val;
                fcsr|=owner->flags;
                initialized[rd]=true;
                hostFs=3;
                if(v)guestFs=3;
            }
            else writes=rd;
        }
        else if(op==0x73&&fun){
            U c=i>>20;
            val=csrRead(c);
            if(fun==1){
                U value=x[a];
                if(c>=1&&c<=3){
                    if(c==3)fcsr=value&255;
                    else if(c==1)fcsr=(fcsr&224)|(value&31);
                    else fcsr=(fcsr&31)|((value&7)<<5);
                    hostFs=3;
                    if(v)guestFs=3;
                }
                else if(c==0x100){
                    if(v){
                        guestFs=(value>>13)&3;
                        csr[0x200]=value;
                    }
                    else{
                        hostFs=(value>>13)&3;
                        csr[c]=value;
                    }
                }
                else if(c==0x200){
                    guestFs=(value>>13)&3;
                    csr[c]=value;
                }
                else if(c==0x300){
                    hostFs=(value>>13)&3;
                    csr[c]=value;
                }
                else if(c==0x600)hstatus=(2ULL<<32)|(value&0x1c0);
                else csr[c]=value;
            }
            else require(fun==2&&a==0,"CSR_read_subset");
        }
        else if(i==0x30200073){
            writes=false;
            next=csr[0x341];
            priv=(csr[0x300]>>11)&3;
            v=(csr[0x300]>>39)&1;
            csr[0x300]=(csr[0x300]&~0x1888ULL)|0x80;
        }
        else if(i==0x10200073){
            writes=false;
            next=csr[0x141];
            priv=(csr[0x100]&0x100)?1:0;
            v=hstatus&0x80;
            hstatus&=~0x80ULL;
            csr[0x100]=(csr[0x100]&~0x122ULL)|0x20|((csr[0x100]&0x20)>>4);
        }
        else if(i==0x6f){
            writes=false;
            next=pc;
            if(pc==in.terminal)++terminal;
            else throw std::runtime_error("poison/unexpected terminal reached");
        }
        else throw std::runtime_error("unplanned retired instruction");
        if(actual)equal(o.at(n+"$$bits$$writesRd"),writes,"commit_write_enable");
        if(writes){
            if(actual){
                equal(o.at(n+"$$bits$$rd"),rd,"commit_rd");
                equal(o.at(n+"$$bits$$data"),val,"commit_value");
            }
            x[rd]=val;
        }
        if(actual)equal(o.at(n+"$$bits$$nextPc"),next,"commit_next_pc");
        pc=next;
        ++commits;
    }
    void events(const Fields&o,const State&s){
        if(owner&&owner->fault&&owner->completions==1&&
            !o.at("ownerActive")&&!o.at("trap$$valid")) {
            require(o.at("fpBusy"),"released_fault_keeps_architectural_FP_busy");
            require(!o.at("fpStartReady")&&!o.at("systemStartReady"),
                "released_fault_rejects_new_work");
            require(!o.at("fpStart$$valid")&&!o.at("systemStart$$valid")&&
                !o.at("fpComplete$$valid"),"released_fault_no_start_or_duplicate_completion");
            ++faultReleaseWait;
        }
        // MSU execution is real ROB-head authorization, not an expected-value
        // injection. Bind its captured command to the independent ISA frontier.
        if(o.at("systemExecute")) {
            U instruction=in.code.at(pc);
            equal(o.at("systemRequest$$pc"),pc,"MSU_execute_frontier_PC");
            equal(o.at("systemRequest$$instruction"),instruction,"MSU_execute_instruction");
            unsigned op=instruction&127;
            bool integerSource=op!=0x53||(instruction&0xfff0707f)==0xf2000053;
            if(integerSource)equal(o.at("systemRequest$$operand"),
                x[(instruction>>15)&31],"MSU_execute_integer_operand");
        }
        if(o.at("fpStart$$valid")){
            require(!owner,"single_FP_owner");
            U i=o.at("fpStart$$bits$$instruction"),p=o.at("fpStart$$bits$$pc");
            equal(p,pc,"FP_issue_at_retirement_frontier");
            equal(i,in.code.at(p),"FP_issue_instruction");
            unsigned op=i&127;
            U operand=x[(i>>15)&31];
            if(op==7||op==0x27||(i&0xfff0707f)==0xf2000053)equal(o.at("fpStart$$bits$$operand"),operand,"FP_issue_integer_operand");
            auto e=fault(i);
            bool writes=op==7||(i&0xfff0707f)==0xf2000053||arithmetic(i);
            owner=Owner{
                o.at("fpStart$$bits$$token$$index"),o.at("fpStart$$bits$$token$$tag"),p,i,operand,e?0:fpValue(i,operand),writes,e,0
            };
            owner->guest=v;
            if(!e&&arithmetic(i))owner->flags=numeric(i,f[(i>>15)&31],f[(i>>20)&31],fcsr>>5).flags;
            ++fpIssues;
        }
        if(o.at("fpComplete$$valid")){
            require(owner.has_value(),"completion_owner");
            auto&q=*owner;
            equal(o.at("fpComplete$$bits$$token$$index"),q.index,"completion_index");
            equal(o.at("fpComplete$$bits$$token$$tag"),q.tag,"completion_tag");
            equal(++q.completions,1,"completion_once");
            equal(o.at("fpComplete$$bits$$exception"),q.fault.has_value(),"completion_exception");
            if(q.fault){
                equal(o.at("fpComplete$$bits$$cause"),q.fault->cause,"completion_cause");
                equal(o.at("fpComplete$$bits$$tval"),q.fault->tval,"completion_tval");
                equal(o.at("fpComplete$$bits$$guestFault$$guestPhysicalAddress"),q.fault->gpa,"completion_GPA");
                equal(o.at("fpComplete$$bits$$guestFault$$guestPageFault"),q.fault->gp,"completion_G_fault");
                equal(o.at("fpComplete$$bits$$guestFault$$guestAddress"),q.fault->gva,"completion_guest_address");
                equal(o.at("fpComplete$$bits$$guestFault$$implicitPte"),0,"completion_explicit_access");
                require(o.at("memoryDrained"),"exception_completion_drained");
            }
            else if((q.inst&127)!=0x27)equal(o.at("fpComplete$$bits$$data"),q.value,"completion_value");
            ++fpCompletions;
        }
        bool retiring=o.at("fpRetire$$valid");
        if(retiring){
            require(owner.has_value()&&!owner->fault,"only_success_retires_FP");
            equal(o.at("fpRetire$$bits$$index"),owner->index,"FP_retire_index");
            equal(o.at("fpRetire$$bits$$tag"),owner->tag,"FP_retire_tag");
            equal(owner->completions,1,"FP_retire_after_completion");
            bool matched=false;
            for(auto n:{"commit0","commit1"}) {
                const std::string prefix=std::string(n)+"$$bits$$";
                if(o.at(std::string(n)+"$$valid") && o.at(prefix+"pc")==owner->pc) {
                    equal(o.at(prefix+"token$$index"),owner->index,"ROB_FP_token_index");
                    equal(o.at(prefix+"token$$tag"),owner->tag,"ROB_FP_token_tag");
                    matched=true;
                }
            }
            require(matched,"FP_retire_matches_real_commit");
            ++fpRetires;
        }
        if(!o.at("commitEnable")){
            require(!o.at("commit0$$valid")&&!o.at("commit1$$valid")&&!o.at("trap$$valid"),"commit_hold_delays_retirement_and_trap");
        }
        eventOwner=owner; // Preserve same-edge issue/completion/retirement owner for transition checks.
        commit(o,"commit0");
        commit(o,"commit1");
        if(retiring)owner.reset();
        if(o.at("trap$$valid")){
            U i=in.code.at(pc);
            auto e=fault(i);
            require(e.has_value(),"trap_has_independent_fault");
            equal(o.at("trap$$bits$$pc"),pc,"trap_precise_pc");
            equal(o.at("trap$$bits$$cause"),e->cause,"trap_cause");
            equal(o.at("trap$$bits$$tval"),e->tval,"trap_tval");
            equal(o.at("trap$$bits$$guestFault$$guestPageFault"),e->gp,"trap_G_fault");
            equal(o.at("trap$$bits$$guestFault$$guestAddress"),e->gva,"trap_guest_address");
            equal(o.at("trap$$bits$$guestFault$$guestPhysicalAddress"),e->gpa,"trap_GPA");
            equal(o.at("trap$$bits$$guestFault$$implicitPte"),0,"trap_explicit_access");
            require(v&&priv==1,"only_VS_to_HS_traps");
            require(o.at("memoryDrained")&&!o.at("fpMemoryBusy")&&o.at("adapterIdle")&&o.at("translatorIdle"),"trap_data_path_drained");
            if(owner){
                require(owner->fault.has_value(),"trap_owns_completed_FP_fault");
                equal(owner->completions,1,"fault_completed_once_before_trap");
                require(o.at("fpBusy"),"fault_FP_busy_until_trap");
                owner.reset();
            }
            else {
                require((i&127)==0x73,"CSR_or_ECALL_no_FP_owner");
                require(!o.at("fpBusy"),"CSR_fault_has_no_FP_pending_state");
                if(e->cause==2)++csrFaultTraps;
            }
            csr[0x142]=e->cause;
            csr[0x141]=pc;
            csr[0x143]=e->tval;
            csr[0x643]=e->gpa>>2;
            csr[0x64a]=0;
            hstatus=(2ULL<<32)|0x180|(e->gva?0x40:0);
            csr[0x100]=(csr[0x100]&~0x122ULL)|0x100|((csr[0x100]&2)<<4);
            v=false;
            priv=1;
            pc=csr[0x105];
            ++traps;
        }
        // Metadata equality is checked by every actual handler CSR retirement.
        equal(s.v[43],s.v[32]==3,"host_SD_from_FS");
        equal(o.at("guestSd"),s.v[33]==3,"guest_SD_from_FS");
    }
};
// Build the entire native memory ledger before reset from instruction bytes.
// The live ISA checker above still checks every real retirement independently.
struct MemoryAccess {
    U address=0,physical=0,data=0;
    bool write=false,virtualized=false,denied=false;
    std::vector<U> ptes;
};
static std::vector<MemoryAccess> memoryPlan(const Input& input) {
    Oracle model(input);
    std::vector<MemoryAccess> plan;
    for(unsigned step=0;step<700;++step) {
        U instruction=input.code.at(model.pc),op=instruction&127;
        unsigned a=(instruction>>15)&31,b=(instruction>>20)&31;
        auto fault=model.fault(instruction);
        bool memory=op==3||op==0x23||op==7||op==0x27;
        if(memory&&(!fault||fault->gp)) {
            bool store=op==0x23||op==0x27;
            U offset=store?sext((instruction>>25)<<5|((instruction>>7)&31),12):
                sext(instruction>>20,12);
            MemoryAccess access;
            access.address=model.x[a]+offset;
            access.write=store;
            access.virtualized=model.v;
            access.data=store?(op==0x27?model.f[b]:model.x[b]):0;
            model.walkReads.clear();
            auto walk=model.translate(access.address,store);
            access.physical=walk.physical;
            access.denied=walk.fault.has_value();
            access.ptes=model.walkReads;
            plan.push_back(access);
        }
        if(fault) {
            model.csr[0x142]=fault->cause;
            model.csr[0x141]=model.pc;
            model.csr[0x143]=fault->tval;
            model.csr[0x643]=fault->gpa>>2;
            model.csr[0x64a]=0;
            model.hstatus=(2ULL<<32)|0x180|(fault->gva?0x40:0);
            model.csr[0x100]=(model.csr[0x100]&~0x122ULL)|0x100|
                ((model.csr[0x100]&2)<<4);
            model.v=false;
            model.priv=1;
            model.pc=model.csr[0x105];
            ++model.traps;
        } else {
            if(op==7||op==0x27||op==0x53) {
                bool writes=op==7||(instruction&0xfff0707f)==0xf2000053||arithmetic(instruction);
                U operand=model.x[a];
                model.owner=Oracle::Owner{0,0,model.pc,instruction,operand,
                    model.fpValue(instruction,operand),writes,{},1};
                model.owner->guest=model.v;
                if(arithmetic(instruction))model.owner->flags=numeric(instruction,model.f[a],model.f[b],model.fcsr>>5).flags;
            }
            model.commit({},"",false);
            model.owner.reset();
        }
        if(model.terminal) {
            equal(model.traps,9,"input_plan_trap_count");
            return plan;
        }
    }
    throw std::runtime_error("input program does not terminate within instruction bound");
}
// Full bank is sampled every cycle. State IDs only eliminate byte-for-byte
// repetition; a row's post ID is the next row's pre ID, with no skipped cycles.
struct Trace {
    std::ofstream f;
    std::vector<std::string> columns;
    State last;
    bool have=false;
    U id=0,limit;
    Trace(const std::string&path,U bound,const std::string&schedule,const Fields&fields):f(path),limit(bound){
        require(bool(f),"trace_open");
        f<<"{\"type\":\"header\",\"schema\":1,\"schedule\":\""<<schedule<<"\",\"columns\":[";
        bool first=true;
        for(auto&[k,v]:fields){
            columns.push_back(k);
            if(!first)f<<',';
            first=false;
            f<<'"'<<k<<'"';
        }
        f<<"],\"state_columns\":[";
        for(unsigned n=0;n<32;n++){
            if(n)f<<',';
            f<<"\"fpr_"<<n<<"\"";
        }
        for(auto n:{
            "hostFs","guestFs","fcsr","virtualized","privilege","hstatus","htval","htinst","scause","sepc","stval","hostSd"
        })f<<",\""<<n<<'"';
        f<<"]}\n";
    }
    U stateId(const State&s){
        if(have&&s==last)return id;
        if(have)++id;
        have=true;
        last=s;
        f<<"[\"S\","<<id<<",[";
        for(unsigned n=0;n<s.v.size();n++){
            if(n)f<<',';
            f<<s.v[n];
        }
        f<<"]]\n";
        return id;
    }
    void cycle(U c,U pre,U post,const Fields&o){
        f<<"[\"C\","<<c<<','<<pre<<','<<post<<",[";
        bool first=true;
        for(unsigned n=0;n<columns.size();n++){
            U val=o.at(columns[n]);
            if(val){
                if(!first)f<<',';
                first=false;
                f<<'['<<n<<','<<val<<']';
            }
        }
        f<<"]]\n";
        require(U(f.tellp())<limit,"raw_trace_byte_bound");
    }
    U footer(U cycles,const Oracle&o,const Memory&m,const Memory&initial){
        const U reportedChecks=checks;
        f<<"{\"type\":\"footer\",\"cycles\":"<<cycles<<",\"native_checks\":"<<reportedChecks<<",\"commits\":"<<o.commits<<",\"traps\":"<<o.traps<<",\"fp_issues\":"<<o.fpIssues<<",\"fp_completions\":"<<o.fpCompletions<<",\"fp_retires\":"<<o.fpRetires<<",\"final_memory\":[";
        bool first=true;
        for(auto&[a,v]:m.b)if(v!=initial.b.at(a)){
            if(!first)f<<',';
            first=false;
            f<<'['<<a<<','<<unsigned(v)<<']';
        }
        f<<"]}\n";
        f.flush();
        require(bool(f),"trace_complete_write");
        require(U(f.tellp())<limit,"raw_trace_byte_bound");
        return reportedChecks;
    }
};
struct Pending {
    U cycle,id;
    Fields raw;
    State pre;
    std::optional<Oracle::Owner> owner;
};
static void transition(const Pending&r,const State&post){
    const auto&o=r.raw;
    State expected=r.pre;
    U&host=expected.v[32],&guest=expected.v[33],&fcsr=expected.v[34];
    bool mut=false,mutGuest=false;
    if(o.at("fpRetire$$valid")){
        require(r.owner.has_value(),"transition_retire_owner");
        auto&q=*r.owner;
        if(q.writes){
            expected.v[(q.inst>>7)&31]=q.value;
            host=3;
            equal(expected.v[35],q.guest,"retirement_uses_captured_guest_context");
            if(q.guest)guest=3;
            fcsr|=q.flags;
            mut=true;
            mutGuest=q.guest;
        }
    }
    if(o.at("systemExecute")){
        U i=o.at("systemRequest$$instruction"),operand=o.at("systemRequest$$operand"),c=i>>20,fun=(i>>12)&7;
        bool writing=fun==1;
        bool permitted=host&&(!expected.v[35]||guest);
        if((i&127)==0x73&&fun&&c>=1&&c<=3&&writing&&permitted){
            if(c==3)fcsr=operand&255;
            else if(c==1)fcsr=(fcsr&224)|(operand&31);
            else fcsr=(fcsr&31)|((operand&7)<<5);
            host=3;
            if(expected.v[35])guest=3;
            mut=true;
            mutGuest=expected.v[35];
        }
        if((i&127)==0x73&&writing&&(c==0x300||(c==0x100&&!expected.v[35])))host=(operand>>13)&3;
        if((i&127)==0x73&&writing&&(c==0x200||(c==0x100&&expected.v[35])))guest=(operand>>13)&3;
    }
    equal(o.at("mutation$$valid"),mut,"mutation_only_authorized_event");
    if(mut)equal(o.at("mutation$$bits$$guest"),mutGuest,"mutation_captured_context");
    // Uninitialized payload is not specified by ISA. Preserve its observed value
    // until real software initializes it; every subsequent change is predicted.
    for(unsigned n=0;n<35;n++)equal(post.v[n],expected.v[n],n<32?"FPR_changes_only_at_retirement":"FS_fcsr_authorized_transition");
    if(o.at("trap$$valid")){
        equal(post.v[35],0,"trap_clears_V");
        equal(post.v[36],1,"trap_enters_HS");
        equal(post.v[38],o.at("trap$$bits$$guestFault$$guestPhysicalAddress")>>2,"trap_sets_HTVAL");
        equal(post.v[39],0,"trap_clears_HTINST");
        equal(post.v[40],o.at("trap$$bits$$cause"),"trap_sets_SCAUSE");
        equal(post.v[41],o.at("trap$$bits$$pc"),"trap_sets_SEPC");
        equal(post.v[42],o.at("trap$$bits$$tval"),"trap_sets_STVAL");
    }
}
static void run(const std::string&recipe,const std::string&path,const std::string&schedule){
    Input in(recipe);
    Oracle oracle(in);
    Memory memory=in.initial;
    const auto plan=memoryPlan(in);
    size_t nextAccess=0,pteCursor=0;
    const MemoryAccess* activeAccess=nullptr;
    bool physicalSeen=false;
    bool stagger=schedule=="staggered";
    require(stagger||schedule=="baseline","schedule_name");
    auto allocated=std::make_unique<SGuardedGuestFpArithmeticGsim>();
    auto&d=*allocated;
    std::memset(&d,0,sizeof(d));
    d.LOG_START=1;
    d.activateAll();
    d.set_reset(1);
    d.step();
    d.step();
    d.set_reset(0);
    d.set_io$$enable(1);
    std::array<Port,4> ports;
    std::optional<Pending>previous;
    std::unique_ptr<Trace>trace;
    unsigned hold=0;
    U heldRetire=0,heldTrap=0;
    std::map<U,bool>heldTokens;
    const std::array<std::string,4>names{
        "instruction","fetchPte","dataPte","data"
    };
    for(U cycle=0;cycle<in.limit;cycle++){
        bool enable=hold==0;
        if(hold)--hold;
        d.set_io$$commitEnable(enable);
        Fields inputs;
        inputs["commitEnable"]=enable;
        for(auto error:{"instruction$$responseError","instruction$$responsePageFault",
            "fetchPte$$response$$bits$$error","dataPte$$response$$bits$$error",
            "data$$response$$bits$$error","data$$response$$bits$$pageFault"})inputs[error]=0;
        for(auto&p:ports)if(p.delay)--p.delay;
        for(unsigned n=0;n<4;n++){
            auto&p=ports[n];
            const auto&name=names[n];
            inputs[name+"$$request$$ready"]=p.ready(stagger);
            inputs[name+"$$response$$valid"]=p.valid&&!p.delay;
            inputs[name+(n==0?"$$response$$bits":"$$response$$bits$$data")]=p.valid&&!p.delay?p.data:0;
        }
#define DRIVE(N,P) d.set_io$$##N##$$request$$ready(ports[P].ready(stagger));d.set_io$$##N##$$response$$valid(ports[P].valid&&!ports[P].delay)
        DRIVE(instruction,0);
        d.set_io$$instruction$$response$$bits(inputs.at("instruction$$response$$bits"));
        d.set_io$$instruction$$responseError(0);
        d.set_io$$instruction$$responsePageFault(0);
        DRIVE(fetchPte,1);
        d.set_io$$fetchPte$$response$$bits$$data(inputs.at("fetchPte$$response$$bits$$data"));
        d.set_io$$fetchPte$$response$$bits$$error(0);
        DRIVE(dataPte,2);
        d.set_io$$dataPte$$response$$bits$$data(inputs.at("dataPte$$response$$bits$$data"));
        d.set_io$$dataPte$$response$$bits$$error(0);
        DRIVE(data,3);
        d.set_io$$data$$response$$bits$$data(inputs.at("data$$response$$bits$$data"));
        d.set_io$$data$$response$$bits$$error(0);
        d.set_io$$data$$response$$bits$$pageFault(0);
#undef DRIVE
        d.step();
        State s=state(d);
        Fields raw=observe(d);
        raw.insert(inputs.begin(),inputs.end());
        if(!trace)trace=std::make_unique<Trace>(path,in.traceLimit,schedule,raw);
        U sid=trace->stateId(s);
        if(previous){
            transition(*previous,s);
            if(previous->raw.at("ownerActive")&&!raw.at("ownerActive")){
                require(previous->raw.at("memoryDrained"),"protected_owner_release_drained");
                require(!previous->raw.at("fpMemoryBusy")&&previous->raw.at("adapterIdle")&&previous->raw.at("translatorIdle"),"protected_owner_release_no_memory_work");
            }
            trace->cycle(previous->cycle,previous->id,sid,previous->raw);
        }
        // A prior completed FP owner or accepted exceptional MSU completion
        // closes actual commitEnable for the next five cycles. No ready/busy,
        // owner, ROB, exception or trap signal is driven by the harness.
        if(stagger){
            bool fc=raw.at("fpComplete$$valid"),sc=raw.at("systemComplete$$valid")&&raw.at("systemComplete$$bits$$completion$$exception");
            if(fc||sc){
                U tag=raw.at(fc?"fpComplete$$bits$$token$$tag":"systemComplete$$bits$$completion$$token$$tag");
                if(!heldTokens[tag]){
                    heldTokens[tag]=true;
                    hold=5;
                }
            }
        }
        if(!enable&&raw.at("fpBusy")&&raw.at("statePhase")==3)++heldRetire;
        if(!enable&&raw.at("pendingException$$valid"))++heldTrap;
        oracle.events(raw,s);
        auto savedOwner=oracle.eventOwner;
        previous=Pending{
            cycle,sid,raw,s,savedOwner
        };
        if(raw.at("dataVirtualRequest$$valid")) {
            if(activeAccess) {
                equal(pteCursor,activeAccess->ptes.size(),"previous_data_walk_complete");
                equal(physicalSeen,!activeAccess->denied,"previous_physical_access_exactly_once");
            }
            require(nextAccess<plan.size(),"no_extra_virtual_data_access");
            activeAccess=&plan[nextAccess++];
            pteCursor=0;physicalSeen=false;
            equal(raw.at("dataVirtualRequest$$bits$$address"),activeAccess->address,"input_virtual_data_address");
            equal(raw.at("dataVirtualRequest$$bits$$write"),activeAccess->write,"input_virtual_data_direction");
            equal(raw.at("dataVirtualRequest$$bits$$size"),3,"input_virtual_doubleword_size");
            equal(raw.at("dataVirtualRequest$$bits$$virtualized"),activeAccess->virtualized,"input_memory_context");
            if(activeAccess->write)equal(raw.at("dataVirtualRequest$$bits$$data"),activeAccess->data,"input_virtual_store_value");
        }
        for(unsigned n=0;n<4;n++){
            auto&p=ports[n];
            const auto&name=names[n];
            p.consume(raw.at(name+"$$response$$ready"));
            bool offer=raw.at(name+"$$request$$valid"),ready=inputs.at(name+"$$request$$ready");
            std::vector<U>bits;
            if(n==3)for(auto key:{
                "address","data","mask","write","size","virtualized","atomic","atomicOp","precheckedLoad","translationEpoch","prefetchNextAllowed","uncached"
            })bits.push_back(raw.at("data$$request$$bits$$"+std::string(key)));
            else bits.push_back(raw.at(name+"$$request$$bits"));
            p.stable(offer,ready,bits);
            if(offer&&ready){
                U address=bits[0];
                unsigned latency=stagger?2+cycle%5:1;
                U value=0;
                if(n<3) {
                    if(n==2) {
                        require(activeAccess&&pteCursor<activeAccess->ptes.size(),"data_PTE_has_planned_owner");
                        equal(address,activeAccess->ptes[pteCursor++],"input_nested_data_PTE_sequence");
                    }
                    value=memory.read(address,n==0?2:8);
                }
                else{
                    U data=bits[1],mask=bits[2];
                    bool write=bits[3];
                    require(activeAccess&&!activeAccess->denied&&!physicalSeen,"no_physical_access_on_fault");
                    equal(pteCursor,activeAccess->ptes.size(),"physical_after_complete_walk");
                    equal(address,activeAccess->physical,"input_physical_data_destination");
                    equal(write,activeAccess->write,"input_physical_data_direction");
                    if(write)equal(data,activeAccess->data,"input_physical_store_value");
                    physicalSeen=true;
                    equal(bits[4],3,"physical_doubleword_size");
                    equal(bits[5],0,"physical_not_virtualized");
                    equal(bits[6],0,"no_atomics");
                    equal(bits[11],0,"cacheable_RAM");
                    equal(address&7,0,"aligned_physical_data");
                    require((address>=0x80400000&&address<0x80401000)||
                        (address>=0x80210000&&address<0x80212000),"only_recipe_data_pages");
                    if(write){
                        equal(mask,255,"full_store_mask");
                        require(address!=0x80210608&&address!=0x80211608&&address!=0x80400608,"younger_poison_store_never_issues");
                        oracle.actualStores.push_back({
                            address,data,mask
                        });
                        memory.write(address,data,8);
                    }
                    value=memory.read(address,8);
                }
                p.accept(value,latency);
            }
        }
        if(oracle.terminal>=2){
            // One final cycle captures the post-state of the final real retirement.
            d.set_io$$enable(0);
            d.set_io$$commitEnable(0);
            d.step();
            State post=state(d);
            transition(*previous,post);
            U postid=trace->stateId(post);
            trace->cycle(previous->cycle,previous->id,postid,previous->raw);
            equal(nextAccess,plan.size(),"complete_native_data_access_plan");
            require(activeAccess&&!activeAccess->denied&&physicalSeen,"last_physical_access_completed");
            equal(pteCursor,activeAccess->ptes.size(),"last_nested_walk_completed");
            equal(oracle.traps,9,"seven_arithmetic_faults_two_ECALLs");
            equal(oracle.csrFaultTraps,0,"arithmetic_faults_have_FP_owner");
            require(!oracle.owner,"no_final_FP_owner");
            equal(oracle.fpIssues,oracle.fpCompletions,"all_FP_complete_once");
            equal(oracle.fpIssues-oracle.fpRetires,7,"seven_arithmetic_faults_do_not_retire");
            require(oracle.actualStores==oracle.expectedStores,"external_stores_match_ISA");
            require(memory.b==oracle.memory.b,"independent_final_byte_memory");
            for(unsigned n=1;n<4;n++)require(!ports[n].valid,"final_data_and_PTE_responses_drained");
            if(stagger){
                require(heldRetire>0,"actual_FP_retirement_backpressure");
                require(heldTrap>0,"actual_trap_backpressure");
                require(oracle.faultReleaseWait>0,"fault_released_while_trap_held");
                for(auto&p:ports)require(p.stalls>0,"all_ports_held_offer");
            }
            U reportedChecks=trace->footer(cycle+1,oracle,memory,in.initial);
            std::cout<<"GUARDED_GUEST_FP_ARITHMETIC_PASS schedule="<<schedule<<" cycles="<<cycle+1<<" commits="<<oracle.commits<<" traps="<<oracle.traps<<" checks="<<reportedChecks<<" held_retire="<<heldRetire<<" held_trap="<<heldTrap<<'\n';
            return;
        }
    }
    throw std::runtime_error("GUARDED_GUEST_ARITHMETIC_CHECK[cycle_timeout]");
}
int main(int argc,char**argv){
    try{
        if(argc==2&&std::string(argv[1])=="--numeric-self-test"){numericSelfTest();return 0;}
        std::string recipe,trace,schedule;
        for(int n=1;n<argc;n++){
            std::string a=argv[n];
            require(n+1<argc,"argument_value");
            std::string v=argv[++n];
            if(a=="--recipe")recipe=v;
            else if(a=="--trace")trace=v;
            else if(a=="--schedule")schedule=v;
            else throw std::runtime_error("unknown argument");
        }
        require(!recipe.empty()&&!trace.empty()&&!schedule.empty(),"required_arguments");
        run(recipe,trace,schedule);
        return 0;
    }
    catch(const std::exception&e){
        std::cerr<<"FAIL "<<e.what()<<'\n';
        return 1;
    }
}
