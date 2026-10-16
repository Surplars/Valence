#include "EarlyLoadSourceLifetimeGsim.h"
#include <iostream>
#include <string>
int main(int argc,char**argv){
 SEarlyLoadSourceLifetimeGsim d;d.set_reset(0);
 std::string mode=argc>1?argv[1]:"";
 d.set_io$$active(1);d.set_io$$mappingMatches(mode!="--mapping");d.set_io$$inRange(mode!="--range");
 d.set_io$$reserved(mode=="--reserve");d.set_io$$waitingLoad(1);d.set_io$$ready(0);
 d.set_io$$written(0);d.set_io$$acceptedProducerWrite(0);d.step();
 d.set_io$$written(1);d.set_io$$acceptedProducerWrite(mode!="--bad-producer");d.step();
 d.set_io$$waitingLoad(0);d.set_io$$ready(1);d.set_io$$written(mode=="--ready-rewrite");
 d.set_io$$acceptedProducerWrite(0);d.step();
 std::cout<<"EARLY_LOAD_LIFETIME_PASS pending_then_write_then_ready\n";
}
