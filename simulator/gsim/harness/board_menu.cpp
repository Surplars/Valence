// Reuses the frozen final Board object. Production ROM is unchanged by this test.
#define main old_board_boot_main
#include "board_boot.cpp"
#undef main
struct Watch {
 Test *t;unsigned imageEntries=0,diagnosticEntries=0;bool allowImage=false,lockedWatch=false;
 uint64_t imageReads=0;unsigned maxDmaReads=0,maxDmaWrites=0;
 static void sample(SBoardSocGsim &d,void *ctx){auto &w=*static_cast<Watch *>(ctx);
  if(w.lockedWatch)check(!d.board$platform$dma$busy,"locked monitor started memory DMA");
  check(w.t->received.size()<16000,"bounded menu UART output");
  if(w.t->cycles%500000==0)std::cout<<"MENU_PROGRESS cycles="<<w.t->cycles<<" UART="<<w.t->received.size()<<" pc=0x"<<std::hex<<d.get_io$$fetchPc()<<std::dec<<std::endl;
  for(unsigned lane=0;lane<2;lane++)if(lane?d.get_io$$commit1():d.get_io$$commit0()){
   const auto pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
   if(pc==0x80200000){check(w.allowImage,"unauthorized image execution");++w.imageEntries;}
   if(pc==0xfff78000){check(!d.board$platform$dma$busy,"diagnostic entry while memory DMA busy");++w.diagnosticEntries;}
  }
  if(d.get_io$$ddrAxi$$ar$$valid()&&w.t->ddr.arReady&&d.get_io$$ddrAxi$$ar$$bits$$addr()<64)++w.imageReads;
  w.maxDmaReads=std::max(w.maxDmaReads,unsigned(d.board$platform$dma$readsSent));
  w.maxDmaWrites=std::max(w.maxDmaWrites,unsigned(d.board$platform$dma$writesDone));
 }
 bool residentClean()const {for(unsigned i:{0U,256U})if(t->dut->board$platform$privateCache$valid[i]&&t->dut->board$platform$privateCache$tags[i]==(0x80200000U>>14))return !t->dut->board$platform$privateCache$dirty[i];return false;}
};
static Bytes fixture(){Bytes b;word(b,0x00008067);for(unsigned i=4;i<16;i++)b.push_back(uint8_t(i*7+3));return b;}
static void backing(Test &t,const Bytes &image){for(unsigned i=0;i<image.size();i++){auto found=t.ddr.memory.find(i&~7U);check(found!=t.ddr.memory.end()&&uint8_t(found->second>>(8*(i&7)))==image[i],"independent physical DDR image mismatch");}}
static void lockedCommands(Test &t,Watch &w) {
 const auto entries=w.imageEntries,diagnostics=w.diagnosticEntries;
 const auto reads=w.maxDmaReads,writes=w.maxDmaWrites;
 w.allowImage=false;w.lockedWatch=true;
 for(uint8_t command:Bytes{'d','c','r'}) {
  t.send(command);t.expect("EXTERNAL STATE LOCKED; BOARD RESET REQUIRED");t.expect("locked> ");
 }
 check(w.imageEntries==entries&&w.diagnosticEntries==diagnostics&&w.maxDmaReads==reads&&w.maxDmaWrites==writes&&!t.dut->board$platform$dma$busy,"locked command executed or changed memory DMA");
 std::cout<<"MENU_RETURN_LOCK_PASS blocked=dcr image_entries_unchanged=1 diagnostic_entries_unchanged=1 memory_dma_unchanged=1\n";
}
int main(int argc,char **argv){try {
 check(argc==5,"usage: run ROM.bin crc|negative|diagnostics|info|cpu|dma expected_size expected_crc");
 const auto rom=readFile(argv[1]);check(rom.size()==std::stoul(argv[3])&&crc32(rom)==std::stoul(argv[4],nullptr,0),"exact ROM byte pin");
 const std::string selected=argv[2];check(selected=="crc"||selected=="negative"||selected=="diagnostics"||selected=="info"||selected=="cpu"||selected=="dma","unknown menu case");
 Test t(rom);Watch w{&t};t.observer=Watch::sample;t.observerContext=&w;t.ready();
 check(!w.imageEntries&&!w.diagnosticEntries,"menu auto-executed on boot");
 if(selected=="info") {
  t.send('i');t.expect("HW CSR misa=0x");t.expect("HW network unprobed;");t.ready();
  t.send('a');t.expect("\033[2J\033[H");t.ready();const auto boundary=t.received.size();
  t.send('a');t.ready();check(std::find(t.received.begin()+boundary,t.received.end(),uint8_t(27))==t.received.end(),"plain fallback emitted ANSI");
  check(!w.imageEntries&&!w.diagnosticEntries,"info unexpectedly executed RAM");
 }else if(selected=="cpu"||selected=="dma"){
  t.send(selected=="cpu"?'b':'m');t.expect(selected=="cpu"?"CPU_BANDWIDTH_PASS":"MEMORY_DMA_PASS");
  t.expect("DIAGNOSTIC RETURN STATE PASS sp_gp_saved_sp_mstatus_satp_mie=1\r\n");t.expect("DIAGNOSTIC RETURN\r\n");t.ready();
  check(w.diagnosticEntries==1,"bandwidth diagnostic entry count");
  if(selected=="dma")check(w.maxDmaReads==16384&&w.maxDmaWrites==16384&&!t.dut->board$platform$dma$busy,"128KiB DMA read/completed-write progress in 8-byte words");
  for(unsigned i=0;i<16384;i++){
   const auto a=t.ddr.memory.find(uint32_t(0xfff98000ULL-ramBase+i*8));const auto b=t.ddr.memory.find(uint32_t(0xfffb8000ULL-ramBase+i*8));
   check(a!=t.ddr.memory.end()&&b!=t.ddr.memory.end()&&a->second==b->second&&a->second==(0x935b76124aedc087ULL^(uint64_t(i)*0x102040810204081ULL)),"full bandwidth independent backing mismatch");
  }
 }else if(selected=="diagnostics"){
  t.send('c');t.expect("COREMARK_SHORT_CRC_PASS standard2000=1 score=none\r\n");
  t.expect("DIAGNOSTIC RETURN STATE PASS sp_gp_saved_sp_mstatus_satp_mie=1\r\n");t.expect("DIAGNOSTIC RETURN\r\n");t.ready();
  t.send('t');t.expect("CPU_BANDWIDTH_PASS");t.expect("MEMORY_DMA_PASS");
  t.expect("DIAGNOSTIC RETURN STATE PASS sp_gp_saved_sp_mstatus_satp_mie=1\r\n");t.expect("DIAGNOSTIC RETURN\r\n");t.ready();
  check(w.diagnosticEntries==2&&w.maxDmaReads==64&&w.maxDmaWrites==64&&!t.dut->board$platform$dma$busy,"mem2mem 64-word read/write progress or two diagnostic returns missing");
  for(unsigned i=0;i<64;i++){
   const auto a=t.ddr.memory.find(uint32_t(0xfff98000ULL-ramBase+i*8));const auto b=t.ddr.memory.find(uint32_t(0xfffb8000ULL-ramBase+i*8));
   check(a!=t.ddr.memory.end()&&b!=t.ddr.memory.end()&&a->second==b->second,"DMA independent source/destination DDR mismatch");
   check(a->second==(0x935b76124aedc087ULL^(uint64_t(i)*0x102040810204081ULL)),"DMA independent initial data mismatch");
  }
  const auto image=fixture();t.download(image);backing(t,image);w.allowImage=true;t.send('r');t.expect("APP RETURN\r\n");t.expect("locked> ");lockedCommands(t,w);check(w.imageEntries==1,"diagnostic return broke UART run");
 }else{
  auto image=fixture();t.download(image);if(selected=="crc")backing(t,image);
  t.send('v');t.expect("RAM IMAGE VERIFIED\r\n");t.ready();check(w.residentClean(),"small image was not resident-clean before backing-only fault");
  check(!t.dut->board$platform$dma$busy,"backing fault while memory DMA owned");
  t.ddr.memory[0]^=uint64_t(1)<<40; // Only physical backing; never alter cache/tag/data/metadata.
  const auto readsBefore=w.imageReads;t.send('v');
  if(selected=="negative"){
   t.expect("RAM IMAGE VERIFIED\r\n");t.ready();check(w.imageReads==readsBefore,"negative unexpectedly fetched backing");
   std::cout<<"MENU_PREPARE_OMISSION_DETECTED clean_cache_masked_backing_corruption=1\n";
  }else{
   t.expect("RAM CRC FAIL\r\n");t.ready();check(w.imageReads>readsBefore,"new verification did not request physical image refill");
   t.send('r');t.expect("NO IMAGE\r\n");t.ready();check(w.imageEntries==0,"bad RAM executed");
   image[12]^=0x55;t.download(image);backing(t,image);w.allowImage=true;t.send('r');t.expect("APP RETURN\r\n");t.expect("locked> ");lockedCommands(t,w);check(w.imageEntries==1,"repeated image download/run failed");
  }
 }
 std::cout<<"MENU_BOARD_PASS case="<<selected<<" cycles="<<t.cycles<<" image_entries="<<w.imageEntries<<" diagnostic_entries="<<w.diagnosticEntries<<" memory_dma_read_words="<<w.maxDmaReads<<" memory_dma_written_words="<<w.maxDmaWrites<<" no_gmac_access=1 physical_cdc=0 board=0\n";return 0;
}catch(const std::exception &e){std::cerr<<"MENU_BOARD_FAIL "<<e.what()<<"\n";return 1;}}
