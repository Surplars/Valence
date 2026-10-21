`timescale 1ns/1ps
module store_clear_admission_tb;
  reg clock=0;always #5 clock=~clock;
  reg reset=1,av=0,write=0,atomic=0,noalloc=0,readahead=0,early=0,invalidate=0;
  reg [63:0] address=64'h80000000,data=0;
  reg [1:0] size=3,privilege=3;
  reg [7:0] mask=255;reg [4:0] atomicop=0;
  wire ar,dv,de,dp,accepted,nv,nw,na,nrr;
  wire [63:0] dd,naddr;
  reg dr=1,nready=1,nrv=0,nerr=0;reg [63:0] ndata=0;
  StoreClearAdmissionBatch dut(
    .clock(clock),.reset(reset),.io_request_valid(av),.io_request_ready(ar),
    .io_request_bits_address(address),.io_request_bits_write(write),.io_request_bits_size(size),
    .io_request_bits_data(data),.io_request_bits_mask(mask),.io_request_bits_noAllocate(noalloc),
    .io_request_bits_atomic(atomic),.io_request_bits_atomicOperation(atomicop),
    .io_response_valid(dv),.io_response_ready(dr),.io_response_bits_data(dd),
    .io_response_bits_error(de),.io_response_bits_pageFault(dp),
    .io_readAhead(readahead),.io_early(early),.io_invalidate(invalidate),.io_privilege(privilege),
    .io_storeAccepted(accepted),.io_nativeReady(nready),.io_nativeValid(nv),
    .io_nativeAddress(naddr),.io_nativeWrite(nw),.io_nativeAtomic(na),
    .io_nativeResponseValid(nrv),.io_nativeResponseReady(nrr),
    .io_nativeResponseData(ndata),.io_nativeResponseError(nerr));
  reg [63:0] expectData[0:4095];reg expectFault[0:4095];
  reg [63:0] memData[0:4095];
  integer er=0,ew=0,mr=0,mw=0,cycles=0,stores=0,reads=0,atomics=0,faults=0;
  integer blocked=0,storeAheadBlocked=0,handoffs=0,returned=0,native=0,invalidations=0;
  reg afire,dfire,nfire,nrfire;reg bad;integer seed=32'h5a64123a;
  function automatic [63:0] replyValue(input [63:0] a);
    replyValue=a^64'hc65b31a2de4f9087;
  endfunction
  task automatic fail(input string reason);
    begin $display("STORE_CLEAR_FAIL cycle=%0d %s owners=%0d/%0d native=%0d/%0d av/ar=%b/%b nv=%b nrv/nrr=%b/%b address=%h",cycles,reason,er,ew,mr,mw,av,ar,nv,nrv,nrr,address);$fatal(1,"store admission scoreboard mismatch");$finish;end
  endtask
  task automatic tick;
    reg expectedAccepted;
    begin
      @(posedge clock);cycles=cycles+1;
      if(!reset)begin
        if(cycles>=23&&cycles<=28)$display("DT_TRACE c=%0d state=%h pmp=%b cap=%b pa=%h size=%h range=%b sz=%b machine=%b fast=%b",cycles,dut.dt.stateStorage,dut.dt._pmp_io_allow,dut.dt.pmp.io_capture,dut.dt.pmp.io_address,dut.dt.pmp.io_size,dut.dt.pmp.inRange_r,dut.dt.pmp.sizeAllowed,dut.dt.pmp.checkedMachine,dut.dt.fastEligible);
        afire=av&&ar;dfire=dv&&dr;nfire=nv&&nready;nrfire=nrv&&nrr;
        expectedAccepted=afire&&write&&!atomic;
        if(bad&&cycles==12)begin expectedAccepted=!expectedAccepted;$display("ORACLE_NEGATIVE_REJECT armed");end
        if(accepted!==expectedAccepted)fail("ordinary-store event differs from actual accepted write history");
        if(av&&write&&readahead)begin
          if(ar||accepted)fail("store+readAhead must never admit or clear");
          storeAheadBlocked=storeAheadBlocked+1;
        end
        if(dv)begin
          if(er>=ew)fail("reply without accepted upstream owner");
          if(de!==expectFault[er]||dp!==1'b0)fail("fault/status order");
          if(dd!==(expectFault[er]?64'b0:expectData[er]))fail("registered reply payload/order/stability");
          if(dfire)begin er=er+1;returned=returned+1;end else blocked=blocked+1;
        end
        if(afire)begin
          expectFault[ew]=(address[63:36]!=0)||(privilege!=3);
          expectData[ew]=replyValue(address);ew=ew+1;
          if(write&&!atomic)stores=stores+1;else if(atomic)atomics=atomics+1;else reads=reads+1;
          if(expectFault[ew-1])faults=faults+1;
          if(readahead)handoffs=handoffs+1;
        end
        if(nfire)begin memData[mw]=replyValue(naddr);mw=mw+1;native=native+1;end
        if(nrfire)begin mr=mr+1;end
        if(invalidate)invalidations=invalidations+1;
      end else begin afire=0;dfire=0;nfire=0;nrfire=0;end
      #1;if(!reset&&nrfire)nrv=0;@(negedge clock);
    end
  endtask
  task automatic service;
    begin
      if(!nrv&&mr<mw)begin nrv=1;ndata=memData[mr];end
    end
  endtask
  task automatic transaction(input [63:0] a,input reg w,input reg atom,input [1:0] priv);
    integer timeout;
    begin
      av=1;address=a;write=w;atomic=atom;privilege=priv;readahead=0;timeout=0;
      do begin service();tick();timeout=timeout+1;if(timeout>100)fail("admission stalled");end while(!afire);
      av=0;
    end
  endtask
  task automatic drain;
    integer timeout;
    begin
      av=0;dr=1;nready=1;timeout=0;
      while(er<ew||mr<mw||nrv)begin service();tick();timeout=timeout+1;if(timeout>100)fail("drain stalled");end
      repeat(3)tick();
    end
  endtask
  integer i,r,j;
  initial begin
    bad=$test$plusargs("BAD_ORACLE");repeat(3)tick();reset=0;
    transaction(64'h80000000,0,0,3);drain();
    transaction(64'h80000008,1,0,3);drain();
    transaction(64'h80000010,1,1,3);drain();
    transaction(64'h1000000000,1,0,3);drain();
    transaction(64'h80000018,0,0,1);drain();
    privilege=3;write=1;atomic=0;readahead=1;av=1;
    repeat(7)tick();av=0;readahead=0;
    // The production common profile's cacheable RAM starts at 0x80200000.
    // The earlier 0x800000xx accesses intentionally cover non-cacheable traffic.
    // Handoff requires a cacheable next read on the genuine response edge.
    transaction(64'h80200020,0,0,3);
    while(mr==mw)begin service();tick();end
    av=1;address=64'h80200028;write=0;atomic=0;readahead=1;
    service();tick();
    if(!afire)fail("proven same-page read handoff was not exercised");
    av=0;readahead=0;drain();
    for(i=0;i<4000;i=i+1)begin
      r=$random(seed);dr=(r&1)!=0;nready=(r&2)!=0;invalidate=(r&255)==12;early=(r&4)!=0;
      if(!av||afire)begin
        av=(r&24)!=0;write=(r&32)!=0;atomic=(r&64)!=0;atomicop=0;
        address=64'h80200000+((r>>8)&511)*8;data={$random(seed),$random(seed)};
        privilege=3;readahead=0;noalloc=(r&128)!=0;
        if((r&1023)==17)address=64'h1000000000;
      end
      if((r&256)!=0)service();
      tick();
    end
    dr=1;nready=1;invalidate=0;
    if(afire)av=0;
    while(av)begin service();tick();if(afire)av=0;end
    drain();
    if(stores<20||reads<20||atomics<20||faults<2||storeAheadBlocked<7||handoffs<1||blocked<1||invalidations<1)
      fail("required directed/random coverage absent");
    if(ew!=er||mw!=mr)fail("accepted request/response conservation");
    $display("STORE_CLEAR_ADMISSION_PASS cycles=%0d requests=%0d responses=%0d stores=%0d reads=%0d atomics=%0d faults=%0d ahead_blocked=%0d handoffs=%0d blocked=%0d native=%0d invalidations=%0d",cycles,ew,er,stores,reads,atomics,faults,storeAheadBlocked,handoffs,blocked,native,invalidations);
    $finish;
  end
  initial begin #300000;$fatal(1,"store-clear fixture watchdog");$finish;end
endmodule
