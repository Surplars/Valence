#include "WholeLineGrantGsim.h"
#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#ifndef WHOLE_LINE_GRANT
#error "explicit transport mode required"
#endif
static void check(bool x,const char* s){if(!x)throw std::runtime_error(s);}
static uint64_t word(unsigned owner,unsigned beat){return 0x9182736455463728ULL^(uint64_t(owner+1)<<40)^(0x0102040810204081ULL*(beat+1));}
struct Test {
    SWholeLineGrantGsim d; unsigned cycles=0, e=0, results=0; bool eReady=false,resultReady=false;
    std::array<unsigned,2> sources{}; std::array<bool,2> done{},errors{}; std::string injection;
    Test(){std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();idle();d.set_reset(1);tick();tick();d.set_reset(0);}
    void idle(){d.set_io$$request$$valid(0);d.set_io$$a$$ready(1);d.set_io$$d$$valid(0);d.set_io$$fullValid(0);}
    void tick(){
        d.set_io$$e$$ready(eReady);d.set_io$$resultReady(resultReady);d.step();++cycles;
        if(d.get_io$$e$$valid()&&eReady)++e;
        if(d.get_io$$resultValid()){
            const unsigned tag=d.get_io$$tag(),owner=tag-0x40;
            check(owner<2&&!done[owner],"unknown/duplicate complete owner");
            check(e>0,"result exposed before actual GrantAck");
            check(bool(d.get_io$$error())==(errors[owner]^(injection=="error")),"independent whole Grant error oracle mismatch");
            check(d.get_io$$cap()==0,"whole Grant permission metadata mismatch");
            uint64_t words[]={d.get_io$$outputWords$$word0(),d.get_io$$outputWords$$word1(),d.get_io$$outputWords$$word2(),d.get_io$$outputWords$$word3(),d.get_io$$outputWords$$word4(),d.get_io$$outputWords$$word5(),d.get_io$$outputWords$$word6(),d.get_io$$outputWords$$word7()};
            if(injection=="data")words[3]^=1;
            for(unsigned b=0;b<8;++b)check(words[b]==word(owner,b),"independent whole Grant byte oracle mismatch");
            if(resultReady){done[owner]=true;++results;}
        }
    }
    void request(unsigned owner){
        d.set_io$$request$$valid(1);d.set_io$$request$$bits$$address(0x80200000+owner*64);
        d.set_io$$request$$bits$$tag(0x40+owner);d.set_io$$request$$bits$$grow(1);d.set_io$$request$$bits$$permissionOnly(0);
        tick();check(d.get_io$$request$$ready(),"free Acquire refused");d.set_io$$request$$valid(0);
        bool seen=false;
        for(unsigned k=0;k<12&&!seen;++k){tick();if(d.get_io$$a$$valid()){sources[owner]=d.get_io$$a$$bits$$source();seen=true;}}
        check(seen,"Acquire A absent");
    }
    void grant(unsigned owner,bool denied,bool corrupt){
        const unsigned n=WHOLE_LINE_GRANT?1:8;
        for(unsigned b=0;b<n;++b){
            if(WHOLE_LINE_GRANT){
                d.set_io$$fullValid(1);d.set_io$$fullSource(sources[owner]);d.set_io$$fullSink(owner);d.set_io$$fullCap(0);d.set_io$$fullDenied(denied);d.set_io$$fullCorrupt(corrupt);
                d.set_io$$inputWords$$word0(word(owner,0));d.set_io$$inputWords$$word1(word(owner,1));d.set_io$$inputWords$$word2(word(owner,2));d.set_io$$inputWords$$word3(word(owner,3));
                d.set_io$$inputWords$$word4(word(owner,4));d.set_io$$inputWords$$word5(word(owner,5));d.set_io$$inputWords$$word6(word(owner,6));d.set_io$$inputWords$$word7(word(owner,7));
            }else{
                d.set_io$$d$$valid(1);d.set_io$$d$$bits$$opcode(5);d.set_io$$d$$bits$$size(6);d.set_io$$d$$bits$$source(sources[owner]);d.set_io$$d$$bits$$sink(owner);d.set_io$$d$$bits$$param(0);
                d.set_io$$d$$bits$$data(word(owner,b));d.set_io$$d$$bits$$denied(denied&&b==7);d.set_io$$d$$bits$$corrupt(corrupt&&b==7);
            }
            tick();check(WHOLE_LINE_GRANT?d.get_io$$fullReady():d.get_io$$d$$ready(),"Grant transport refused live source");
            check(!d.get_io$$resultValid(),"Grant exposed result while E held");
        }
        idle();
    }
};
int main(int argc,char**argv){try{
    const std::string injection=argc==2?argv[1]:"";
    unsigned cases=0;
    for(unsigned order=0;order<2;++order)for(unsigned error=0;error<3;++error){
        Test t;t.injection=injection;t.errors[order]=error!=0;t.request(0);t.request(1);
        t.grant(order,error==1,error==2);for(unsigned k=0;k<4;++k)t.tick();
        check(t.e==0&&t.results==0,"held E released completion");t.grant(1-order,false,false);
        t.eReady=true;
        for(unsigned k=0;k<8;++k)t.tick();check(t.e==2,"two real GrantAck handshakes missing");
        // Priority selection must retain its complete owner under result stall.
        const auto tag=t.d.get_io$$tag();for(unsigned k=0;k<4;++k){t.tick();check(t.d.get_io$$tag()==tag,"held result changed owner");}
        t.resultReady=true;
        for(unsigned k=0;k<12&&t.results<2;++k)t.tick();check(t.results==2,"held results did not retire");
        ++cases;
    }
    check(injection.empty(),"requested mutation did not reject");
    std::cout<<"WHOLE_LINE_GRANT_PASS mode="<<WHOLE_LINE_GRANT<<" cases="<<cases<<" actual_E_required=1 owners=2 buffer_unchanged=1\n";return 0;
}catch(const std::exception&e){std::cerr<<"WHOLE_LINE_GRANT_FAIL "<<e.what()<<'\n';return 1;}}
