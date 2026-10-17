#include "I1HomeReadPairFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void need(bool p,const char* why){if(!p)throw std::runtime_error(why);}
static uint64_t pattern(unsigned n,unsigned client,unsigned word){
    return 0x9375abcdf1375602ULL ^ uint64_t(n+1)*0x9e3779b97f4a7c15ULL ^
        uint64_t(client+1)*0x5102040810204081ULL ^ uint64_t(word)*0x102030405060708ULL;
}
int main(int argc,char**argv){try{
    SI1HomeReadPairFixture d;
    const bool wrong=argc>1&&std::string(argv[1])=="--wrong-word";
    S(a0$$valid,0);S(a1$$valid,0);S(e0$$valid,0);S(e1$$valid,0);
    S(g0$$ready,0);S(g1$$ready,0);S(read$$ready,0);S(responseValid,0);S(inspect,0);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
    unsigned pairs=0,errors=0,grantStalls=0,eStalls=0,reverse=0;
    for(unsigned n=0;n<24;++n){
        const uint64_t base=0x80010000ULL+n*128;
        const std::array<unsigned,2> source{n%7,(n+3)%7};
        const std::array<bool,2> error{n%4==1,n%4==2};
        std::array<bool,2> accepted{},reads{},returned{},granted{},acked{};
        std::array<unsigned,2> tag{};
        const unsigned first=(n&1)?1:0;
        for(unsigned cycle=0;cycle<200&&(!acked[0]||!acked[1]);++cycle){
            S(a0$$valid,!accepted[0]);S(a1$$valid,!accepted[1]);
#define A(c,i) S(a##c##$$bits$$opcode,6);S(a##c##$$bits$$param,1);S(a##c##$$bits$$size,6); \
            S(a##c##$$bits$$source,source[i]);S(a##c##$$bits$$address,base+64*i); \
            S(a##c##$$bits$$mask,255);S(a##c##$$bits$$data,0);S(a##c##$$bits$$corrupt,0)
            A(0,0);A(1,1);
            const bool readReady=cycle%4!=1;
            S(read$$ready,readReady);
            const unsigned selected=!returned[first]?first:1-first;
            const bool respond=reads[0]&&reads[1]&&!returned[selected]&&cycle>=25;
            S(responseValid,respond);S(responseTag,tag[selected]);S(responseError,error[selected]);
            S(word0,pattern(n,selected,0));S(word1,pattern(n,selected,1));
            S(word2,pattern(n,selected,2));S(word3,pattern(n,selected,3));
            S(word4,pattern(n,selected,4));S(word5,pattern(n,selected,5));
            S(word6,pattern(n,selected,6));S(word7,pattern(n,selected,7));
            const bool grantReady=cycle>=34 && cycle%3!=1;
            S(g0$$ready,grantReady);S(g1$$ready,grantReady);
            // Delay the next backing return until the current checked Grant
            // handshakes; this allows one scalar inspection port without
            // hiding simultaneous pending Home ownership.
            const unsigned inspect=granted[first]?1-first:first;
            S(inspect,inspect);
            const bool ackEnable=granted[0]&&granted[1]&&cycle>=60;
            S(e0$$valid,ackEnable&&!acked[0]);S(e1$$valid,ackEnable&&!acked[1]);
            S(e0$$bits$$sink,0);S(e1$$bits$$sink,1);
            // Actual A arbitration starts at client 0; tag/sink 0 is primary.
            const bool responseOffered=respond&&!(returned[first]&&!granted[first]);
            S(responseValid,responseOffered);
            if(argc>1&&std::string(argv[1])=="--trace")
                std::cerr<<"pair="<<n<<" cycle="<<cycle<<" selected="<<selected
                    <<" tag="<<tag[selected]<<" offered="<<responseOffered
                    <<" accepted="<<accepted[0]<<accepted[1]<<" reads="<<reads[0]<<reads[1]
                    <<" returned="<<returned[0]<<returned[1]<<" granted="<<granted[0]<<granted[1]<<"\n";
            d.step();
            if(G(a0$$ready)&&!accepted[0])accepted[0]=true;
            if(G(a1$$ready)&&!accepted[1])accepted[1]=true;
            if(G(read$$valid)&&readReady){
                unsigned client=unsigned((G(read$$bits$$address)-base)/64);
                need(client<2&&!reads[client]&&accepted[client],"independent paired Home A/read identity");
                reads[client]=true;tag[client]=G(read$$bits$$tag);
            }
            need(!G(probe),"independent new/error line unexpectedly became owned");
            if(cycle==24)need(reads[0]&&reads[1],"Home second read waited for the first return/GrantAck");
            if(responseOffered&&G(responseReady))returned[selected]=true;
            const bool valid=inspect?G(g1$$valid):G(g0$$valid);
            if(valid){
                need(returned[inspect]|| (responseOffered&&selected==inspect),
                    "Home Grant preceded the actual retained backing response");
                const std::array<uint64_t,8> data{G(result0),G(result1),G(result2),G(result3),
                    G(result4),G(result5),G(result6),G(result7)};
                for(unsigned w=0;w<8;++w)need(data[w]==(pattern(n,inspect,w)^(wrong&&w==6)),
                    "independent paired Home eight-word/error/source oracle");
                need((inspect?G(g1$$bits$$source):G(g0$$bits$$source))==source[inspect]&&
                    (inspect?G(g1$$bits$$sink):G(g0$$bits$$sink))==inspect&&
                    bool(inspect?G(g1$$bits$$denied):G(g0$$bits$$denied))==error[inspect]&&
                    bool(inspect?G(g1$$bits$$corrupt):G(g0$$bits$$corrupt))==error[inspect],
                    "independent paired Home eight-word/error/source oracle");
                if(grantReady)granted[inspect]=true;else ++grantStalls;
            }
            if(ackEnable){
                if(!acked[0]&&G(e0$$ready))acked[0]=true;
                if(!acked[1]&&G(e1$$ready))acked[1]=true;
            }else if(granted[0]||granted[1])++eStalls;
        }
        need(acked[0]&&acked[1],"paired Home read/error/E bounded completion");
        S(a0$$valid,0);S(a1$$valid,0);S(e0$$valid,0);S(e1$$valid,0);S(responseValid,0);d.step();
        need(G(drained),"Home retained a read context after both real E handshakes");
        ++pairs;errors+=error[0]+error[1];reverse+=(first==1);
    }
    std::cout<<"I1_HOME_READ_PAIR_PASS pairs="<<pairs<<" errors="<<errors<<" reverse="<<reverse
        <<" grant_stalls="<<grantStalls<<" e_stalls="<<eStalls<<"\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
