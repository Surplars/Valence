`timescale 1ns/1ps
module gmac_ready_tb;
  reg clock=0, reset=1;
  reg av=0, dr=0, ac=0;
  reg [2:0] op=0, param=0, size=3;
  reg [3:0] source=0, mr=0, resp=0, busy=0;
  reg [63:0] address=0, data=0;
  reg [7:0] mask=255;
  wire ar,dv,denied,corrupt;
  wire [2:0] dop,dparam,dsize;
  wire [3:0] dsource,cmd,stop,restart,irq;
  wire dsink;
  wire [63:0] dd;
  wire [107:0] payload;
  wire [15:0] controls;
  wire [191:0] macs;
  GmacReadyBatch dut(
    .clock(clock),.reset(reset),.io_a_valid(av),.io_a_ready(ar),
    .io_a_bits_opcode(op),.io_a_bits_param(param),.io_a_bits_size(size),
    .io_a_bits_source(source),.io_a_bits_address(address),.io_a_bits_mask(mask),
    .io_a_bits_data(data),.io_a_bits_corrupt(ac),
    .io_d_valid(dv),.io_d_ready(dr),.io_d_bits_opcode(dop),.io_d_bits_param(dparam),
    .io_d_bits_size(dsize),.io_d_bits_source(dsource),.io_d_bits_sink(dsink),
    .io_d_bits_denied(denied),.io_d_bits_data(dd),.io_d_bits_corrupt(corrupt),
    .io_mdioReady(mr),.io_mdioResponse(resp),.io_busy(busy),
    .io_cmdValid(cmd),.io_cmdPayload(payload),.io_controls(controls),.io_macs(macs),
    .io_rxStop(stop),.io_restart(restart),.io_irq(irq));
  localparam [63:0] BASE=64'h10040000;
  // Software oracle uses numeric interval selection and byte-by-byte access rules.
  // It deliberately retains the original broad legality/MDIO-credit expression.
  reg [63:0] ctl[0:3],mac[0:3],en[0:3];
  reg [6:0] pending[0:3];
  reg [16:0] result[0:3];
  reg done[0:3],active[0:3],stopped[0:3];
  reg [2:0] qo[0:16383],qs[0:16383];
  reg [3:0] qsrc[0:16383];
  reg qden[0:16383],qcor[0:16383];
  reg [63:0] qdata[0:16383];
  integer head=0,tail=0,count=0,cycles=0,accepted=0,replied=0,launches=0;
  integer blockedMdio=0,deniedWithoutCredit=0,fullCycles=0,stableCycles=0;
  integer launchPort[0:3],i,j,n,k,off,bytes,lanes,p;
  integer seed=32'h47ac1234;
  reg negative;
  reg selected,readReq,putReq,legal,protocolOk,known,writable,reservedOk,commandOk;
  reg start,needCredit,expectedReady,acceptNow,popNow;
  reg [7:0] access;
  reg [63:0] expanded,masked,allowed,rd;
  reg [3:0] ecmd,erestart,eirq,estop;
  reg [15:0] econtrols;
  reg [191:0] emacs;
  reg [26:0] expectedPayload;
  reg [79:0] heldD;
  reg holding=0;

  function automatic [31:0] random32;
    begin
      seed=seed ^ (seed << 13); seed=seed ^ (seed >> 17); seed=seed ^ (seed << 5);
      random32=seed;
    end
  endfunction
  task automatic fail(input string reason);
    begin
      $display("GMAC_READY_FAIL cycle=%0d accepted=%0d replied=%0d q=%0d op=%0d size=%0d mask=%h addr=%h data=%h: %s",
        cycles,accepted,replied,count,op,size,mask,address,data,reason);
      if(negative) $display("ORACLE_NEGATIVE_REJECT");
      $fatal(1,"GMAC scoreboard mismatch");
    end
  endtask

  task automatic tick;
    begin
      #2;
      p=-1;
      for(n=0;n<4;n=n+1)
        if(address >= BASE+4096*n && address < BASE+4096*(n+1)) p=n;
      selected=(p>=0); off=(address & 4095) & 4088;
      readReq=(op==4); putReq=(op==0 || op==1);
      bytes=(size<=3) ? (1<<size) : 0;
      access=0; expanded=0;
      for(n=0;n<8;n=n+1) begin
        if(n>=(address & 7) && n<(address & 7)+bytes) access[n]=1;
        if(mask[n]) expanded[n*8+:8]=255;
      end
      masked=data & expanded;
      protocolOk=(readReq || putReq) && size<=3 && ((address & (bytes-1))==0) &&
        ((op==1) ? ((mask & ~access)==0) : (mask==access)) && param==0 && !ac;
      known=(off<=8'h90 && (off%8)==0) || (off>=12'h98 && off<=12'h128);
      writable=0; allowed=0;
      case(off)
        'h10: begin writable=1;allowed=15;end
        'h18: begin writable=1;allowed=64'hffffffffffff;end
        'h30,'h38: begin writable=1;allowed=127;end
        'h70,'h90,'h118: begin writable=1;allowed=1;end
        'h78: begin writable=1;allowed=64'hfffffff;end
      endcase
      reservedOk=((masked & ~allowed)==0);
      start=putReq && off=='h78 && masked[17];
      commandOk=(!(start || (putReq && (off=='h90 || off=='h118)))) || (size==3 && mask==255);
      legal=selected && protocolOk && known;
      if(putReq) begin
        legal=legal && writable && reservedOk && commandOk;
        if(selected && (off=='h10 || off=='h18) && mask!=0 && busy[p]) legal=0;
      end
      needCredit=legal && start;
      expectedReady=(count<4) && (!needCredit || mr[p]);
      if(ar !== expectedReady) fail("A.ready differs from independent original legality oracle");
      acceptNow=av && expectedReady;
      popNow=(count!=0) && dr;
      if(dv !== (count!=0)) fail("D.valid / reply count");
      if(count!=0) begin
        if(dop !== qo[head] || dsize !== qs[head] || dsource !== qsrc[head] ||
           denied !== qden[head] || corrupt !== qcor[head] || dd !== qdata[head] ||
           dparam !== 0 || dsink !== 0) fail("D metadata/data/order/stability");
      end
      // Keep an additional direct snapshot of the entire stalled response.
      if(holding && {dop,dparam,dsize,dsource,dsink,denied,dd,corrupt} !== heldD)
        fail("stalled D changed");
      holding=dv && !dr;
      heldD={dop,dparam,dsize,dsource,dsink,denied,dd,corrupt};
      if(holding) stableCycles=stableCycles+1;
      ecmd=0;erestart=0;
      if(acceptNow && legal && putReq) begin
        if(start) ecmd[p]=1;
        if(off=='h118 && masked[0]) erestart[p]=1;
      end
      if(cmd !== ecmd) fail("MDIO command duplicate/drop or launch on denied/stalled A");
      if(restart !== erestart) fail("PHY restart side effect");
      if(|ecmd) begin
        expectedPayload={data[27:18],data[16:0]};
        if(payload[p*27+:27] !== expectedPayload) fail("MDIO command payload");
        if(!mr[p]) fail("MDIO valid with absent ready");
      end
      econtrols=0;emacs=0;estop=0;eirq=0;
      for(n=0;n<4;n=n+1) begin
        econtrols[n*4+:4]=ctl[n][3:0];emacs[n*48+:48]=mac[n][47:0];
        estop[n]=stopped[n];eirq[n]=|(pending[n] & en[n][6:0]);
      end
      if(controls !== econtrols || macs !== emacs || stop !== estop || irq !== eirq)
        fail("register state/side effects");
      if(av && needCredit && !mr[p] && count<4) blockedMdio=blockedMdio+1;
      if(acceptNow && !legal && mr==0) deniedWithoutCredit=deniedWithoutCredit+1;
      if(count==4) fullCycles=fullCycles+1;
      rd=0;
      if(legal && readReq) case(off)
        'h00: rd=64'h56474d4100010001;
        'h08: rd=64'h80000081d01;
        'h10: rd=ctl[p]; 'h18: rd=mac[p]; 'h20: rd=2048;
        'h28: rd=busy[p] ? 7 : 1;
        'h30: rd=pending[p]; 'h38: rd=en[p];
        'h80: rd={62'b0,done[p],active[p]}; 'h88: rd=result[p];
        'h90: rd=stopped[p] ? 3 : 0;
        'h98: rd='h9000+p;
        'ha0: rd='ha000+p*16;
        'ha8: rd='ha001+p*16;
        'h110: rd='ha002+p*16;
      endcase
      if(popNow) begin head=head+1;replied=replied+1;end
      if(acceptNow) begin
        qo[tail]=(op==4 || op==2 || op==3) ? 1 : 0;
        qs[tail]=size;qsrc[tail]=source;qden[tail]=!legal;
        qcor[tail]=!legal && (op==4 || op==2 || op==3);qdata[tail]=rd;
        if(negative && accepted==9) qden[tail]=!qden[tail];
        tail=tail+1;accepted=accepted+1;
      end
      count=count+acceptNow-popNow;
      for(n=0;n<4;n=n+1) begin
        if(acceptNow && legal && putReq && p==n) begin
          case(off)
            'h10: ctl[n]=(ctl[n] & ~expanded) | masked;
            'h18: mac[n]=(mac[n] & ~expanded) | masked;
            'h38: en[n]=(en[n] & ~expanded) | masked;
            'h30: pending[n]=pending[n] & ~masked[6:0];
            'h90: stopped[n]=masked[0];
          endcase
        end
        if(ecmd[n]) begin
          active[n]=1;done[n]=0;launches=launches+1;launchPort[n]=launchPort[n]+1;
        end
        if(resp[n]) begin
          active[n]=0;done[n]=1;result[n]={(n%2==1),16'hc000+n[15:0]};pending[n][6]=1;
        end
      end
      #2;clock=1;#2;clock=0;cycles=cycles+1;
    end
  endtask

  task automatic req(input [2:0] o,input [63:0] a,input [2:0] s,input [7:0] m,input [63:0] d);
    begin op=o;address=a;size=s;mask=m;data=d;param=0;ac=0;source=source+1;av=1;end
  endtask
  task automatic transact;
    integer timeout;
    begin
      timeout=0;
      tick();
      while(!acceptNow) begin
        timeout=timeout+1;
        if(timeout>100) fail("request timeout");
        tick();
      end
      av=0;
    end
  endtask
  task automatic drain;
    begin av=0;dr=1;while(count!=0) tick();tick();end
  endtask

  initial begin
    negative=$test$plusargs("BAD_ORACLE");
    for(i=0;i<4;i=i+1) begin
      ctl[i]=8;mac[i]=0;en[i]=0;pending[i]=0;result[i]=0;
      done[i]=0;active[i]=0;stopped[i]=0;launchPort[i]=0;
    end
    #2;clock=1;#2;clock=0;#2;clock=1;#2;clock=0;reset=0;
    // Each port: legal launch stalls with zero command credit; denied variants do not.
    for(i=0;i<4;i=i+1) begin
      dr=1;mr=0;req(0,BASE+i*4096+'h78,3,255,64'h0a560123);
      repeat(7) tick();
      if(acceptNow) fail("legal launch accepted without MDIO credit");
      mr=1<<i;transact();mr=0;
      for(j=0;j<8;j=j+1) begin
        req(0,BASE+i*4096+'h78,3,255,64'h20000);
        case(j)
          0: begin op=1;mask=8'hfb;end // launch byte masked away: legal update, no launch
          1: mask=8'h0f; // masked command launch is denied
          2: size=2;
          3: address=address+1;
          4: param=1;
          5: ac=1;
          6: data=data | 64'h10000000;
          7: op=2;
        endcase
        transact();
      end
      req(1,BASE+i*4096+'h78,3,0,~64'b0);transact();
      req(1,BASE+i*4096+'h78,3,8'hfb,64'h20000);transact();
      resp=1<<i;av=0;tick();resp=0;
      req(4,BASE+i*4096+'h80,3,255,0);transact();
      req(4,BASE+i*4096+'h88,3,255,0);transact();
    end
    drain();
    // All size/lane/mask/opcode combinations near the launch register, with no credit.
    mr=0;
    for(i=0;i<8;i=i+1) for(j=0;j<8;j=j+1) for(k=0;k<4;k=k+1) begin
      req(k,BASE+'h78+j,i,k==1 ? 8'hfb : 8'hff,64'h20000);
      // Fully legal launch must be released after observing the stall.
      tick();
      if(!acceptNow) begin mr=15;transact();mr=0;end else av=0;
    end
    // Exhaust partial masks with launch and a reserved upper bit independently masked.
    for(i=0;i<4;i=i+1) for(j=0;j<256;j=j+1) begin
      req(1,BASE+i*4096+'h78,3,j,64'h800000000002005a);
      transact(); // Every variant is legal without launch, or denied; none needs credit.
      req(1,BASE+i*4096+'h78,3,j,64'h2005a);
      tick();
      if(!acceptNow) begin mr=1<<i;transact();mr=0;end else av=0;
    end
    // Busy-frame configuration writes reject atomically; empty partial writes remain legal.
    for(i=0;i<4;i=i+1) begin
      busy=1<<i;
      req(0,BASE+i*4096+'h10,3,255,15);transact();
      req(0,BASE+i*4096+'h18,3,255,64'habcdef);transact();
      req(1,BASE+i*4096+'h10,3,0,~64'b0);transact();
      busy=0;
    end
    // Every port's first/last byte, neighboring windows, 32/64-bit alias traps.
    for(i=0;i<4;i=i+1) begin
      req(4,BASE+i*4096,3,255,0);transact();
      req(4,BASE+i*4096+4095,0,128,0);transact();
      req(4,BASE+i*4096+'h08,3,255,0);transact();
      req(0,BASE+i*4096+'h10,3,255,i+1);transact();
      req(0,BASE+i*4096+'h18,3,255,64'h123456789abc+i);transact();
      req(0,BASE+i*4096+'h90,3,255,1);transact();
      req(0,BASE+i*4096+'h118,3,255,1);transact();
    end
    req(4,BASE-1,0,128,0);transact();req(4,BASE+16384,3,255,0);transact();
    req(4,BASE+64'h100000000,3,255,0);transact();
    req(4,64'hfffffffffffff078,3,255,0);transact();
    drain();
    // Non-flow/non-pipe depth-four queue: full ready remains low on a draining cycle.
    dr=0;
    for(i=0;i<4;i=i+1) begin req(4,BASE+i*4096+'h10,3,255,0);transact();end
    req(0,BASE+'h118,3,255,1);repeat(13) tick();
    dr=1;tick();if(acceptNow) fail("full non-pipe queue accepted with simultaneous dequeue");
    transact();drain();
    // Seeded randomized traffic, holding each request until accepted.
    for(i=0;i<6000;i=i+1) begin
      if(!av) begin
        n=random32()%4;
        case(random32()%12)
          0: address=BASE+n*4096+'h78;
          1: address=BASE+n*4096+'h10;
          2: address=BASE+n*4096+'h18;
          3: address=BASE+n*4096+'h90;
          4: address=BASE+n*4096+'h118;
          5: address=BASE+n*4096+'h80;
          6: address=BASE+n*4096+'h88;
          7: address=BASE+n*4096+'h38;
          8: address=BASE+n*4096+'h30;
          9: address=BASE+(random32()%20480);
          10: address=BASE+64'h100000000+(random32()%16384);
          11: address=BASE+n*4096+(random32()%38)*8;
        endcase
        op=random32()%8;size=(random32()%3==0) ? random32()%8 : 3;
        mask=(random32()%3==0) ? random32() : 255;
        data={random32(),random32()};
        case(random32()%4)
          0: data=data & 64'hfffffff;
          1: data=data & 15;
          2: data=64'h20000 | (data & 65535);
        endcase
        param=(random32()%8==0) ? random32()%8 : 0;
        ac=(random32()%16==0);source=random32();av=1;
      end
      mr=random32();dr=(random32()%4!=0);busy=random32();resp=0;
      for(j=0;j<4;j=j+1) if(active[j] && random32()%7==0) resp[j]=1;
      tick();if(acceptNow) av=0;
    end
    mr=15;dr=1;resp=0;busy=0;
    if(av) transact();drain();
    if(accepted!=replied || count!=0 || launches<4 || blockedMdio<28 ||
       deniedWithoutCredit<28 || fullCycles<13 || stableCycles<13) fail("coverage floor");
    for(i=0;i<4;i=i+1) if(launchPort[i]==0) fail("missing port command coverage");
    if(negative) fail("negative oracle was not exercised");
    $display("GMAC_READY_BATCH_PASS cycles=%0d accepted=%0d replied=%0d mdio=%0d blocked=%0d denied_no_credit=%0d full=%0d stable=%0d seed=47ac1234",
      cycles,accepted,replied,launches,blockedMdio,deniedWithoutCredit,fullCycles,stableCycles);
    $finish;
  end
  initial begin #200000;$fatal(1,"GMAC fixture watchdog");end
endmodule
