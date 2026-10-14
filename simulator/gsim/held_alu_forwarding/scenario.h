#pragma once
#include <cstdint>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
namespace b1 {
struct Scenario {
    std::string name,family,mode;unsigned phase=0;
    uint64_t entry=0,terminal=0,signatureAddress=0,signature=0,sentinelAddress=0,sentinel=0;
    bool fault=false;uint64_t faultPc=0,faultCause=0,faultTval=0,resume=0;
    uint64_t delayedLine=0,errorLine=0;unsigned delay=0,expectedFaults=0;
    std::map<uint64_t,uint64_t> seed;std::map<std::string,uint64_t> roles;
    static Scenario read(const std::string& path) {
        std::ifstream in(path);if(!in)throw std::runtime_error("cannot read frozen scenario input");
        Scenario s;std::string key;
        auto number=[&](){std::string text;if(!(in>>text))throw std::runtime_error("truncated scenario");size_t used=0;auto n=std::stoull(text,&used,0);if(used!=text.size())throw std::runtime_error("invalid scenario integer");return n;};
        while(in>>key){
            if(key=="name")in>>s.name;else if(key=="family")in>>s.family;else if(key=="mode")in>>s.mode;
            else if(key=="phase")s.phase=number();else if(key=="entry")s.entry=number();
            else if(key=="terminal")s.terminal=number();else if(key=="signature"){s.signatureAddress=number();s.signature=number();}
            else if(key=="sentinel"){s.sentinelAddress=number();s.sentinel=number();}
            else if(key=="fault"){s.fault=true;s.faultPc=number();s.faultCause=number();s.faultTval=number();s.resume=number();}
            else if(key=="faults")s.expectedFaults=number();
            else if(key=="delay"){s.delayedLine=number();s.delay=number();}
            else if(key=="error")s.errorLine=number();
            else if(key=="seed"){auto a=number(),v=number();if(!s.seed.emplace(a,v).second)throw std::runtime_error("duplicate scenario seed");}
            else if(key=="role"){std::string role;in>>role;s.roles[role]=number();}
            else throw std::runtime_error("unknown scenario field: "+key);
        }
        if(s.name.empty()||s.phase>3||!s.terminal||s.signature!=0x600d||s.expectedFaults>1)throw std::runtime_error("scenario contract invalid");
        return s;
    }
};
}
