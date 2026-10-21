`timescale 1ns/1ps
module packet_dma_control_tb;
  localparam [63:0] BASE=64'h10002000, RAM=64'h80200000;
  reg clock=0,reset=1;
  reg cv=0,cwrite=0,cr=1;reg [63:0] ca=0,cd=0;reg [2:0] cs=3;reg [7:0] cm=255;
  wire cready,cdv,cerror;wire [63:0] cdata;
  wire mv,mwrite,mrr;wire [63:0] ma,md;wire [2:0] ms;wire [7:0] mm;
  reg mr=1,mrv=0,merror=0;reg [63:0] mdata=0;
  reg rdv=0,rsv=0;reg [31:0] rdd=0,rsd=0;reg [3:0] rdk=15,rsk=15;reg rdl=0,rsl=0;
  wire rdr,rsr,tdv,tcv,tdl,tcl,irq,active;
  wire [31:0] tdd,tcd;wire [3:0] tdk,tck;
  EthernetPacketDma dut(
    .clock(clock),.reset(reset),
    .io_control_request_valid(cv),.io_control_request_ready(cready),
    .io_control_request_bits_address(ca),.io_control_request_bits_write(cwrite),
    .io_control_request_bits_size(cs),.io_control_request_bits_data(cd),.io_control_request_bits_byteEnable(cm),
    .io_control_response_valid(cdv),.io_control_response_ready(cr),
    .io_control_response_bits_data(cdata),.io_control_response_bits_error(cerror),
    .io_memory_request_valid(mv),.io_memory_request_ready(mr),
    .io_memory_request_bits_address(ma),.io_memory_request_bits_write(mwrite),
    .io_memory_request_bits_size(ms),.io_memory_request_bits_data(md),.io_memory_request_bits_byteEnable(mm),
    .io_memory_response_valid(mrv),.io_memory_response_ready(mrr),
    .io_memory_response_bits_data(mdata),.io_memory_response_bits_error(merror),
    .io_txData_valid(tdv),.io_txData_ready(1'b1),.io_txData_bits_data(tdd),.io_txData_bits_keep(tdk),.io_txData_bits_last(tdl),
    .io_txControl_valid(tcv),.io_txControl_ready(1'b1),.io_txControl_bits_data(tcd),.io_txControl_bits_keep(tck),.io_txControl_bits_last(tcl),
    .io_rxData_valid(rdv),.io_rxData_ready(rdr),.io_rxData_bits_data(rdd),.io_rxData_bits_keep(rdk),.io_rxData_bits_last(rdl),
    .io_rxStatus_valid(rsv),.io_rxStatus_ready(rsr),.io_rxStatus_bits_data(rsd),.io_rxStatus_bits_keep(rsk),.io_rxStatus_bits_last(rsl),
    .io_irq(irq),.io_active(active));
  integer cycles=0,controls=0,controlReplies=0,memoryRequests=0,memoryReplies=0;
  integer ch=0,ct=0,ccount=0,mh=0,mt=0,mcount=0;
  reg cqerr[0:8191],cqcheck[0:8191];reg [63:0] cqdata[0:8191];
  reg expectedError=0,checkData=0;reg [63:0] expectedData=0,lastReply=0;
  reg memErrors[0:8191];reg replyMemory=1,injectError=0;
  reg expectMemory=0;reg [63:0] frameBase=0;integer frameLength=0,frameTag=0,issued=0;
  integer stalledMemory=0,delayedMemory=0,fullReplies=0,denied=0;
  reg [139:0] heldMem;reg heldMemValid=0;
  reg [64:0] heldControl;reg heldControlValid=0;
  reg negative;reg acceptedControl,poppedControl,pushMemory,popMemory;
  integer n,i,j,k,timeout,seq,oldControls;
  reg [63:0] expectedWord;reg [7:0] expectedMask;
  function automatic [31:0] word32(input integer tag,input integer index);
    word32=32'h10203040+tag*32'h100000+index;
  endfunction
  task automatic fail(input string reason);
    begin
      $display("PACKET_DMA_CONTROL_FAIL cycle=%0d control=%0d/%0d memory=%0d/%0d: %s",cycles,controls,controlReplies,memoryRequests,memoryReplies,reason);
      if(negative) $display("ORACLE_NEGATIVE_REJECT");
      $fatal(1,"packet DMA control scoreboard mismatch");
    end
  endtask
  task automatic tick;
    begin
      mrv=replyMemory && mcount!=0;
      merror=(mcount!=0) ? memErrors[mh] : 0;
      #2;
      if(cready !== (ccount<2)) fail("control credit differs from depth-two non-pipe queue");
      if(cdv !== (ccount!=0)) fail("control response count");
      if(cdv) begin
        if(cerror !== cqerr[ch]) fail("control denied/read/write legality");
        if(cqcheck[ch] && cdata !== cqdata[ch]) fail("control read data");
      end
      if(heldControlValid && {cerror,cdata} !== heldControl) fail("stalled control reply changed");
      heldControlValid=cdv && !cr;heldControl={cerror,cdata};
      if(heldMemValid && (!mv || {ma,mwrite,ms,md,mm} !== heldMem)) fail("held memory request changed/withdrawn");
      heldMemValid=mv && !mr;heldMem={ma,mwrite,ms,md,mm};
      if(heldMemValid) stalledMemory=stalledMemory+1;
      if(ccount==2) fullReplies=fullReplies+1;
      if(mcount!=0 && !replyMemory) delayedMemory=delayedMemory+1;
      if(tdv || tcv) fail("RX-only fixture unexpectedly started TX");
      acceptedControl=cv && cready;poppedControl=cdv && cr;
      pushMemory=mv && mr;popMemory=mrv && mrr;
      if(pushMemory) begin
        if(!expectMemory || issued>=(frameLength+7)/8) fail("unexpected or duplicated memory write");
        expectedWord={word32(frameTag,issued*2+1),word32(frameTag,issued*2)};
        // A final four-byte half has zero upper storage; masked bytes are immaterial.
        expectedMask=(frameLength-issued*8>=8) ? 255 : ((1<<(frameLength-issued*8))-1);
        if(ma !== frameBase+issued*8 || !mwrite || ms!==3 || mm !== expectedMask)
          fail("RX write address/size/mask/order");
        for(n=0;n<8;n=n+1) if(expectedMask[n] && md[n*8+:8] !== expectedWord[n*8+:8]) fail("RX write payload");
        memErrors[mt]=injectError;mt=mt+1;issued=issued+1;memoryRequests=memoryRequests+1;
      end
      if(popMemory) begin mh=mh+1;memoryReplies=memoryReplies+1;end
      mcount=mcount+pushMemory-popMemory;
      if(mcount>4 || mcount<0) fail("memory credits/response owner count");
      if(poppedControl) begin lastReply=cdata;ch=ch+1;controlReplies=controlReplies+1;end
      if(acceptedControl) begin
        cqerr[ct]=expectedError;cqdata[ct]=expectedData;cqcheck[ct]=checkData;
        if(negative && controls==7) cqerr[ct]=!expectedError;
        ct=ct+1;controls=controls+1;if(expectedError) denied=denied+1;
      end
      ccount=ccount+acceptedControl-poppedControl;
      #2;clock=1;#2;clock=0;cycles=cycles+1;
    end
  endtask
  task automatic request(input [63:0] a,input bit w,input [63:0] d,input bit err,input bit check,input [63:0] result);
    begin ca=a;cwrite=w;cd=d;cs=3;cm=255;expectedError=err;checkData=check;expectedData=result;cv=1;end
  endtask
  task automatic accept;
    begin timeout=0;tick();while(!acceptedControl) begin tick();timeout=timeout+1;if(timeout>100) fail("control request timeout");end cv=0;end
  endtask
  task automatic drainControl;
    begin cv=0;cr=1;while(ccount!=0) tick();tick();end
  endtask
  task automatic wr(input integer off,input [63:0] d,input bit err);
    begin request(BASE+off,1,d,err,1,0);accept();drainControl();end
  endtask
  task automatic rd(input integer off,input bit check,input [63:0] d);
    begin request(BASE+off,0,0,0,check,d);accept();drainControl();end
  endtask
  task automatic beginFrame(input [63:0] a,input integer length,input integer tag);
    begin
      if(mcount!=0) fail("prior memory writes remain");
      frameBase=a;frameLength=length;frameTag=tag;issued=0;expectMemory=1;
    end
  endtask
  task automatic sendFrame;
    integer idx,left;
    begin
      for(idx=0;idx<(frameLength+3)/4;idx=idx+1) begin
        left=frameLength-idx*4;rdv=1;rdd=word32(frameTag,idx);rdk=(left>=4) ? 15 : (1<<left)-1;rdl=(left<=4);
        timeout=0;#1;while(!rdr) begin tick();timeout=timeout+1;if(timeout>100) fail("RX data not accepted");end
        tick();rdv=0;
      end
      for(idx=0;idx<6;idx=idx+1) begin
        rsv=1;rsk=15;rsl=(idx==5);
        case(idx) 0:rsd=32'h50000000;3:rsd=64;5:rsd=frameLength;default:rsd=0;endcase
        timeout=0;#1;while(!rsr) begin tick();timeout=timeout+1;if(timeout>100) fail("RX status not accepted");end
        tick();rsv=0;
      end
    end
  endtask
  task automatic waitIdle;
    begin
      timeout=0;#1;
      while(active) begin tick();timeout=timeout+1;if(timeout>500) fail("DMA did not drain");end
      if(mcount!=0) fail("DMA completed before accepted memory replies retired");
      tick();
    end
  endtask
  initial begin
    negative=$test$plusargs("BAD_ORACLE");
    #2;clock=1;#2;clock=0;#2;clock=1;#2;clock=0;reset=0;
    // Numeric old-window/subtraction oracle: all byte offsets, size/mask failures, high aliases.
    for(i=0;i<256;i=i+1) begin
      k=(i%8==0 && i<=216);
      request(BASE+i,0,0,!k,(i==0),64'h56444d4100010001);accept();drainControl();
    end
    for(i=0;i<8;i=i+1) begin
      request(BASE+144,1,1,1,1,0);cs=i;cm=254;accept();drainControl();
      request(BASE+144,1,1,(i!=3),1,0);cs=i;accept();drainControl();
    end
    request(BASE-1,0,0,1,1,0);accept();drainControl();
    request(BASE+256,1,1,1,1,0);accept();drainControl();
    request(BASE+64'h100000000+144,1,1,1,1,0);accept();drainControl();
    request(64'hfffffffffffff090,1,1,1,1,0);accept();drainControl();
    // RX_STOP accepts exactly value one; rejected values do not stop a pending descriptor.
    wr(144,0,1);wr(144,2,1);wr(144,64'h100000001,1);
    wr(184,1,0);wr(160,RAM,0);wr(168,64,0);
    // POST enters pending on this edge; STOP must cancel it on its very next launch edge.
    request(BASE+176,1,1,0,1,0);accept();
    request(BASE+144,1,1,0,1,0);accept();drainControl();repeat(5) tick();
    waitIdle();rd(192,1,64'h20100);rd(200,1,RAM);rd(208,1,65536);wr(216,1,0);
    wr(184,0,0);wr(184,1,0);
    // An invalid STOP at the automatic launch edge must not cancel the posted frame.
    wr(160,RAM+'h100,0);wr(168,64,0);beginFrame(RAM+'h100,9,1);
    request(BASE+176,1,1,0,1,0);accept();
    request(BASE+144,1,0,1,1,0);accept();drainControl();
    sendFrame();waitIdle();if(issued!=2) fail("normal posted frame writes dropped");
    rd(192,1,256);rd(208,1,9);wr(216,1,0);
    // Delayed responses retain the descriptor and do not publish a completion early.
    wr(160,RAM+'h200,0);wr(168,64,0);beginFrame(RAM+'h200,64,2);wr(176,1,0);
    replyMemory=0;sendFrame();repeat(30) tick();
    if(!active || mcount==0) fail("missing outstanding-memory hold");
    rd(192,1,65536);replyMemory=1;waitIdle();if(issued!=8) fail("credit-limited frame writes dropped");
    rd(208,1,64);wr(216,1,0);
    // STOP while a valid memory offer is held: retain it until accepted, then drain all replies.
    wr(160,RAM+'h300,0);wr(168,64,0);beginFrame(RAM+'h300,64,3);wr(176,1,0);
    mr=0;sendFrame();timeout=0;while(!mv) begin tick();timeout=timeout+1;if(timeout>30) fail("missing held RX offer");end
    wr(144,1,0);repeat(11) tick();if(!mv) fail("STOP withdrew held RX offer");
    replyMemory=0;mr=1;tick();repeat(8) tick();if(!active) fail("STOP completed before write response");
    replyMemory=1;waitIdle();if(issued!=1) fail("STOP issued extra later writes");
    rd(208,1,65536+64);wr(216,1,0);wr(184,0,0);
    // Legacy descriptor path, response error and W1C/start behavior.
    wr(48,RAM+'h400,0);wr(56,64,0);beginFrame(RAM+'h400,16,4);wr(64,1,0);
    injectError=1;sendFrame();waitIdle();injectError=0;rd(72,1,6);wr(64,1,1);wr(64,2,0);
    rd(72,1,0);expectMemory=0;
    // Invalid descriptors are retained in the ABI but launch no memory work.
    wr(48,RAM+1,0);wr(56,64,0);wr(64,1,0);rd(72,1,6);wr(64,2,0);
    wr(48,RAM+65536-8,0);wr(56,64,0);wr(64,1,0);rd(72,1,6);wr(64,2,0);
    wr(48,RAM+64'h100000000,0);wr(64,1,0);rd(72,1,6);wr(64,2,0);
    wr(48,RAM,0);wr(56,0,0);wr(64,1,0);rd(72,1,6);wr(64,2,0);
    wr(56,65,0);wr(64,1,0);rd(72,1,6);wr(64,2,0);
    // Invalid/overlapping POSTs consume no slot; STOP of an untouched capture drains cleanly.
    wr(184,1,0);wr(160,RAM+1,0);wr(168,64,0);wr(176,1,1);
    rd(192,1,0);wr(160,RAM+'h500,0);wr(176,1,0);wr(176,1,1);
    wr(144,1,0);waitIdle();rd(208,1,65536);wr(216,1,0);wr(184,0,0);
    // Reply queue full: read and invalid stop replies remain ordered and stable.
    cr=0;request(BASE,0,0,0,1,64'h56444d4100010001);accept();
    request(BASE+144,1,2,1,1,0);accept();
    request(BASE+152,0,0,0,1,64'h40403);repeat(15) tick();
    cr=1;tick();if(acceptedControl) fail("full non-pipe control queue borrowed dequeue credit");
    accept();drainControl();
    if(controls!=controlReplies || memoryRequests!=memoryReplies || mcount!=0 ||
       stalledMemory<11 || delayedMemory<30 || fullReplies<15 || denied<200) fail("coverage floor");
    if(negative) fail("negative oracle was not exercised");
    $display("PACKET_DMA_CONTROL_BATCH_PASS cycles=%0d control=%0d replies=%0d memory=%0d memory_replies=%0d denied=%0d held_memory=%0d delayed_memory=%0d full_replies=%0d",
      cycles,controls,controlReplies,memoryRequests,memoryReplies,denied,stalledMemory,delayedMemory,fullReplies);
    $finish;
  end
  initial begin #100000;$fatal(1,"packet DMA fixture watchdog");end
endmodule
