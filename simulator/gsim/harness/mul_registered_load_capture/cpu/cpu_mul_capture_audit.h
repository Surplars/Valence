#pragma once
#include "cpu_capture_frame.h"
#include <map>
#include <optional>
#include <iostream>
#include <stdexcept>
#include <string>
namespace mul_cpu_capture {
class Audit {
    struct Entry {
        Allocation allocation; uint64_t ordinal=0,product=0;
        bool mul=false,div=false,started=false,available=false,completed=false,retired=false,killed=false;
    };
    std::map<Token,Entry> entries;
    std::array<bool,48> ready{};
    std::array<uint64_t,48> values{};
    std::optional<Payload> previous;
    unsigned previousSlot=0;
    uint64_t frames=0,allocations=0,mulStarts=0,divStarts=0,forwarded=0,left=0,right=0,both=0;
    uint64_t captures=0,available=0,retired=0,killed=0,oldWinners=0,rejected=0,fullPop=0;
    unsigned expectedCount=0;
    bool finished=false;
    void check(bool ok,const char* why) const {
        if(!ok)throw std::runtime_error("MUL_CPU_CAPTURE_AUDIT_FAIL frame="+std::to_string(frames)+" "+why);
    }
    Entry& owner(Token token) {
        auto it=entries.find(token);check(it!=entries.end(),"unknown accepted full owner");return it->second;
    }
    static unsigned age(const Frame& f,unsigned index){return (index+16-f.head)&15;}
    static bool live(const Frame& f,Token token){return token.index<16&&age(f,token.index)<f.count&&f.rows[token.index].robTag==token.tag;}
    static uint64_t product(uint64_t a,uint64_t b,unsigned operation,bool word) {
        using U=unsigned __int128;U x=a,y=b;
        if((operation==1||operation==2)&&(a>>63))x|=U(UINT64_MAX)<<64;
        if(operation==1&&(b>>63))y|=U(UINT64_MAX)<<64;
        U p=x*y;uint64_t value=operation?uint64_t(p>>64):uint64_t(p);
        return word?uint64_t(int64_t(int32_t(uint32_t(value)))):value;
    }
    void payloadEqual(const Payload& a,const Payload& b) {
        check(a.token==b.token&&a.left==b.left&&a.right==b.right&&a.operation==b.operation&&a.word==b.word,
            "registered capture changed accepted full token or numerical payload");
    }
public:
    Audit(){for(unsigned i=0;i<32;++i)ready[i]=true;}
    void observe(const Frame& f) {
        check(!finished,"observation after finish");
        check(f.head<16&&f.count<=16&&f.mulCount<=8,"logical capacity");
        check(f.mulCount==expectedCount&&f.mulReady==(f.mulCount<8),"old MUL reservation/credit mismatch");
        check(f.divReady==(f.divState==0),"old DIV availability mismatch");
        for(unsigned i=0;i<48;++i)check(f.ready[i]==ready[i],"PRF readiness differs from accepted publication/reservation history");
        if(previous){check(f.arithmeticFire,"accepted MUL missing registered capture");
            check(f.capturedSlot==previousSlot&&f.capturedReservation==previous->token,"captured reservation is not the prior accepted tail/full owner");
            payloadEqual(f.captured,*previous);++captures;}
        else check(!f.arithmeticFire,"unowned registered MUL capture");
        previous.reset();

        // Current pre-edge rows must retain the immutable accepted allocation.
        for(const Row& row:f.rows)if(row.pending||row.memoryLive){
            Entry& e=owner(row.token);const auto& a=e.allocation;
            check(!e.retired&&row.source1==a.source1&&row.source2==a.source2&&row.destination==a.destination&&row.writes==a.writes,
                "live row changed accepted physical source/destination ownership");
            if(row.pending&&row.mulDiv){
                check(e.mul||e.div,"M row not raw M allocation");
                check(row.operation==((a.instruction>>12)&7)&&row.word==((a.instruction&127)==0x3b),"M row changed raw operation");
                check(!e.started&&!e.completed&&!e.killed,"pending M owner already consumed or killed");
                check(row.source1<48&&row.source2<48,"M source capacity");
                check(row.ready1==ready[row.source1]&&row.ready2==ready[row.source2],"owner-ready is not current PRF-ready");
            }
        }
        // Independent OLD class winner. Never use DUT expanded eligibility as oracle.
        std::optional<Token> oldWinner;
        for(unsigned offset=0;offset<16;++offset){unsigned i=(f.head+offset)&15;const Row& row=f.rows[i];
            if(!row.pending||!row.mulDiv)continue;
            Entry& e=owner(row.token);check(live(f,row.token),"pending M owner outside live ROB full tag/window");
            if(ready[row.source1]&&ready[row.source2]&&(e.mul?f.mulReady:f.divReady)){
                oldWinner=row.token;break;
            }
        }
        if(oldWinner){++oldWinners;Entry& e=owner(*oldWinner);
            check(f.selectedValid&&f.selectedIndex==oldWinner->index&&f.grantMul==e.mul&&f.grantDiv==e.div,
                "expanded selection displaced original available MUL/DIV owner");
        }
        uint64_t reserves=0;
        for(unsigned lane=0;lane<2;++lane){const Allocation& a=f.allocations[lane];
            check(f.reserveValid[lane]==(a.valid&&a.writes&&!a.alias),"reserve event differs from accepted nonalias allocation");
            if(a.valid){
                check(a.token.index<16&&a.source1<48&&a.source2<48&&a.destination<48,"allocation logical range");
                check(!entries.count(a.token)&&entries.size()<1048576,"duplicate/unbounded full-token allocation history");
                Entry e;e.allocation=a;e.ordinal=allocations++;
                const unsigned opcode=a.instruction&127,op=(a.instruction>>12)&7;
                bool m=(opcode==0x33||opcode==0x3b)&&(a.instruction>>25)==1;
                e.mul=m&&op<4;e.div=m&&op>=4;
                if(a.alias)check(!m&&a.writes&&a.destination==a.source1,"invalid allocation alias");
                entries.emplace(a.token,e);
                if(a.writes&&!a.alias){check(a.destination!=0&&f.reserveDestination[lane]==a.destination,"physical reserve destination");reserves|=1ULL<<a.destination;}
            }
        }
        const bool gates=!f.systemReserve&&!f.recovering&&!f.recoveryAccepted&&!f.headException;
        if(f.mulFire){
            check(f.mulReady&&f.grantMul&&f.selectedValid&&f.start.token.index==f.selectedIndex&&gates,"MUL start without original admission/old credit");
            Entry& e=owner(f.start.token);const Allocation& a=e.allocation;
            check(e.mul&&!e.started&&!e.completed&&!e.retired&&!e.killed&&live(f,f.start.token),"MUL start lacks live unconsumed full owner");
            const Row& row=f.rows[f.start.token.index];
            check(row.pending&&row.token==f.start.token&&!row.killed&&row.source1==a.source1&&row.source2==a.source2,"MUL start current owner mismatch");
            check(f.start.operation==((a.instruction>>12)&7)&&f.start.word==((a.instruction&127)==0x3b),"MUL start operation mismatch");
            const bool f1=!ready[a.source1],f2=!ready[a.source2];
            uint64_t expectedLeft=values[a.source1],expectedRight=values[a.source2];
            if(f1||f2){
                check(!oldWinner&&f.load.valid&&!f.load.exception&&f.loadPromise,"forwarded start lacks old-free port/successful registered load");
                Entry& p=owner(f.load.token);const Allocation& producer=p.allocation;
                const Row& pr=f.rows.at(f.load.token.index);
                check(producer.memory&&!producer.store&&!producer.atomic&&producer.writes&&producer.destination!=0,
                    "forward producer is not ordinary writing load");
                check(!p.killed&&!p.retired&&live(f,f.load.token)&&pr.memoryLive&&pr.token==f.load.token&&!pr.killed,
                    "forward producer lacks current full owner");
                check(p.ordinal<e.ordinal&&age(f,f.load.token.index)<age(f,f.start.token.index),"forward producer is not strictly older");
                check(f.loadDestination==producer.destination&&pr.destination==producer.destination,"forward destination owner mismatch");
                check((!f1||a.source1==producer.destination)&&(!f2||a.source2==producer.destination),"one load cannot supply unrelated sources");
                check(!(reserves&((f1?(1ULL<<a.source1):0)|(f2?(1ULL<<a.source2):0))),"forward source rebound on capture edge");
                if(f1)expectedLeft=f.load.data;if(f2)expectedRight=f.load.data;
                ++forwarded;left+=f1;right+=f2;both+=f1&&f2;
            }
            check(f.start.left==expectedLeft&&f.start.right==expectedRight,"actual MUL payload does not match old PRF/stable LSU source");
            check(!f.start.word||f.start.operation==0,"invalid MULW operation");
            e.started=true;e.product=product(expectedLeft,expectedRight,f.start.operation,f.start.word);
            ++mulStarts;previous=f.start;previousSlot=f.mulTail;
        }
        if(f.divFire){
            check(f.divReady&&f.grantDiv&&f.selectedValid&&gates&&oldWinner&&oldWinner->index==f.selectedIndex,
                "DIV start changed old winner/admission");
            Entry& e=owner(f.rows[f.selectedIndex].token);
            check(e.div&&!e.started&&!e.killed&&!f.rows[f.selectedIndex].killed&&ready[e.allocation.source1]&&ready[e.allocation.source2],
                "DIV consumed unavailable/invalid owner");e.started=true;++divStarts;
        }
        if(f.selectedValid&&f.grantMul&&f.mulReady&&gates&&!f.mulFire)++rejected;
        if(f.mulCount==8&&f.mulPop){++fullPop;check(!f.mulFire,"borrowed same-edge full MUL pop");}
        check(!f.mulPop||f.mulCount!=0,"empty MUL pop");
        expectedCount=f.mulCount+unsigned(f.mulFire)-unsigned(f.mulPop);
        if(f.mulResult.valid){Entry& e=owner(f.mulResult.token);
            check(e.mul&&e.started&&!f.mulResult.exception&&f.mulResult.data==e.product,"MUL result has wrong owner/product");
            if(!e.available){e.available=true;++available;}
        }
        for(unsigned lane=0;lane<2;++lane){const Completion& c=f.completions[lane];
            bool publish=false;unsigned destination=0;
            if(c.valid){Entry& e=owner(c.token);check(!e.completed&&!e.killed&&!f.rows[c.token.index].killed,"duplicate/killed accepted completion");
                if(e.mul)check(e.started&&!c.exception&&c.data==e.product,"MUL accepted completion lacks verified start/product");
                e.completed=true;publish=!c.exception&&e.allocation.writes;destination=e.allocation.destination;
                if(publish){ready[destination]=true;values[destination]=c.data;}
            }
            check(f.writeValid[lane]==publish&&(!publish||f.writeDestination[lane]==destination),"PRF publication differs from accepted full owner");
        }
        for(const Completion& c:f.commits)if(c.valid){Entry& e=owner(c.token);
            check(!e.retired&&!e.killed&&(e.completed||e.allocation.alias),"retirement lacks accepted live completion");e.retired=true;
            if(e.mul){check(e.started&&c.data==e.product,"MUL retirement product mismatch");++retired;}
        }
        for(const Row& row:f.rows)if(row.killed&&live(f,row.token)){
            auto it=entries.find(row.token);if(it!=entries.end()&&!it->second.retired&&!it->second.killed){
                Entry& e=it->second;e.killed=true;if(e.mul&&e.started)++killed;
            }
        }
        for(unsigned i=0;i<48;++i)if(reserves&(1ULL<<i))ready[i]=false;
        ready[0]=true;values[0]=0;++frames;
    }
    void finish(){
        check(!finished&&!previous&&captures==mulStarts,"unfinished or duplicate capture audit");finished=true;
        uint64_t open=0;for(const auto& pair:entries){const Entry& e=pair.second;if(e.mul&&e.started&&!e.retired&&!e.killed)++open;}
        check(retired+killed+open==mulStarts,"MUL lifetime conservation");
        std::cout<<"MUL_CPU_CAPTURE_AUDIT_PASS frames="<<frames<<" allocations="<<allocations<<" mul_starts="<<mulStarts
            <<" div_starts="<<divStarts<<" forwarded="<<forwarded<<" forwarded_left="<<left<<" forwarded_right="<<right
            <<" forwarded_both="<<both<<" captures="<<captures<<" mul_available="<<available<<" mul_retired="<<retired
            <<" killed_mul="<<killed<<" open_mul="<<open<<" old_winner_frames="<<oldWinners<<" late_rejected="<<rejected<<" full_pop="<<fullPop<<'\n';
    }
};
}
