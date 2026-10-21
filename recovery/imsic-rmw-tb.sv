`timescale 1ns/1ps
module imsic_rmw_tb;
  reg clock=0; always #5 clock=~clock;
  reg reset=1;
  reg io_mmio_request_valid=0, io_mmio_request_bits_write=0;
  wire io_mmio_request_ready;
  reg [63:0] io_mmio_request_bits_address=0,io_mmio_request_bits_data=0;
  reg [2:0] io_mmio_request_bits_size=2;
  reg [7:0] io_mmio_request_bits_byteEnable=15;
  wire io_mmio_response_valid,io_mmio_response_bits_error;
  wire [63:0] io_mmio_response_bits_data;
  reg io_mmio_response_ready=1;
  reg io_csrRequest_valid=0,io_csrRequest_bits_topei=0;
  wire io_csrRequest_ready;
  reg [7:0] io_csrRequest_bits_file=0;
  reg [11:0] io_csrRequest_bits_selector=0;
  reg [1:0] io_csrRequest_bits_operation=0;
  reg [63:0] io_csrRequest_bits_data=0;
  wire io_csrResponse_valid,io_csrResponse_bits_error;
  wire [63:0] io_csrResponse_bits_data;
  reg io_csrResponse_ready=1;
  wire [3:0] io_interrupts;
  Imsic dut(.*);

  reg [127:0] pend[0:3],en[0:3];
  reg delivery[0:3]; integer threshold[0:3];
  reg [63:0] qdata[0:16383]; reg qerr[0:16383],merr[0:16383];
  integer qr=0,qw=0,mr=0,mw=0,cycles=0,claims=0,simultaneous=0,blocked=0,errors=0;
  integer f,g,k,id,topid,msifile,msiid; reg err,berr,msival,cfire,mfire;
  reg [63:0] oldvalue,newvalue; reg [31:0] msiword;
  reg [3:0] expected_irq; reg bad_oracle;
  integer seed=32'h152ac913;
  function automatic integer top(input integer fileid);
    integer j; begin
      top=0;
      for(j=127;j>=1;j=j-1)
        if(pend[fileid][j]&&en[fileid][j]&&(threshold[fileid]==0||j<threshold[fileid])) top=j;
    end
  endfunction
  task automatic fail(input string why);
    begin $display("IMSIC_FAIL cycle=%0d %s",cycles,why); $fatal(1,"IMSIC scoreboard mismatch"); $finish; end
  endtask
  task automatic step;
    begin
      @(posedge clock);
      cycles=cycles+1;
      if(reset) begin
        for(f=0;f<4;f=f+1) begin pend[f]=0;en[f]=0;delivery[f]=0;threshold[f]=0;end
        qr=0;qw=0;mr=0;mw=0;
      end else begin
        if(io_csrResponse_valid !== (qw>qr)) fail("CSR valid/credit/order");
        if(io_mmio_response_valid !== (mw>mr)) fail("MMIO valid/credit/order");
        if(io_csrResponse_valid) begin
          if(io_csrResponse_bits_data!==qdata[qr] || io_csrResponse_bits_error!==qerr[qr])
            fail($sformatf("CSR response expected=%h/%b got=%h/%b",qdata[qr],qerr[qr],io_csrResponse_bits_data,io_csrResponse_bits_error));
          if(io_csrResponse_ready) qr=qr+1; else blocked=blocked+1;
        end
        if(io_mmio_response_valid) begin
          if(io_mmio_response_bits_data!==64'b0 || io_mmio_response_bits_error!==merr[mr]) fail("MMIO response");
          if(io_mmio_response_ready) mr=mr+1; else blocked=blocked+1;
        end
        cfire=io_csrRequest_valid&&io_csrRequest_ready;
        mfire=io_mmio_request_valid&&io_mmio_request_ready;
        msival=0; msifile=0; msiid=0;
        if(mfire) begin
          berr=io_mmio_request_bits_size!=2 || io_mmio_request_bits_address[1:0]!=0 ||
            (io_mmio_request_bits_write&&io_mmio_request_bits_byteEnable!=15) ||
            !((io_mmio_request_bits_address>=64'h24000000&&io_mmio_request_bits_address<64'h24001000)||
              (io_mmio_request_bits_address>=64'h28000000&&io_mmio_request_bits_address<64'h28004000));
          merr[mw]=berr;mw=mw+1;
          if(io_mmio_request_bits_address>=64'h28000000) msifile=1+((io_mmio_request_bits_address-64'h28000000)>>12);
          msiword=io_mmio_request_bits_data[31:0];
          if(io_mmio_request_bits_address[11:0]==4)
            msiword={msiword[7:0],msiword[15:8],msiword[23:16],msiword[31:24]};
          msiid=msiword;
          msival=!berr && io_mmio_request_bits_write && msifile<4 &&
            (io_mmio_request_bits_address[11:0]==0||io_mmio_request_bits_address[11:0]==4)&&msiword>0&&msiword<=127;
        end
        if(cfire) begin
          f=io_csrRequest_bits_file;
          err=f>=4 || (!io_csrRequest_bits_topei &&
            (io_csrRequest_bits_selector<12'h70||io_csrRequest_bits_selector>12'hff||
              (io_csrRequest_bits_selector>=12'h80&&io_csrRequest_bits_selector[0])));
          oldvalue=0;topid=0;
          if(f<4) begin
            topid=top(f);
            if(io_csrRequest_bits_topei) oldvalue=(topid<<16)|topid;
            else case(io_csrRequest_bits_selector)
              'h70:oldvalue=delivery[f]; 'h72:oldvalue=threshold[f];
              'h80:oldvalue=pend[f][63:0]; 'h82:oldvalue=pend[f][127:64];
              'hc0:oldvalue=en[f][63:0]; 'hc2:oldvalue=en[f][127:64];
              default:oldvalue=0;
            endcase
          end
          qdata[qw]=err?0:oldvalue;qerr[qw]=err;
          if(bad_oracle && qw==3) begin qdata[qw]=qdata[qw]^64'h1; $display("ORACLE_NEGATIVE_REJECT armed");end
          qw=qw+1;
          if(!err && io_csrRequest_bits_operation!=0) begin
            case(io_csrRequest_bits_operation)
              1:newvalue=io_csrRequest_bits_data;
              2:newvalue=oldvalue|io_csrRequest_bits_data;
              3:newvalue=oldvalue&~io_csrRequest_bits_data;
              default:newvalue=oldvalue;
            endcase
            if(io_csrRequest_bits_topei) begin
              if(topid!=0) begin pend[f][topid]=0;claims=claims+1;end
              if(msival&&msifile==f&&msiid==topid) simultaneous=simultaneous+1;
            end else case(io_csrRequest_bits_selector)
              'h70:delivery[f]=newvalue[0];
              'h72:if(newvalue<=127)threshold[f]=newvalue;
              'h80:pend[f][63:0]=newvalue; 'h82:pend[f][127:64]=newvalue;
              'hc0:en[f][63:0]=newvalue; 'hc2:en[f][127:64]=newvalue;
              default:begin end
            endcase
          end
        end
        if(msival) pend[msifile][msiid]=1;
        for(f=0;f<4;f=f+1) begin pend[f][0]=0;en[f][0]=0;end
      end
      #1;
      expected_irq=0;
      for(k=0;k<4;k=k+1) expected_irq[k]=delivery[k]&&(top(k)!=0);
      if(!reset && io_interrupts!==expected_irq) fail("interrupt priority/threshold/delivery");
      @(negedge clock);
    end
  endtask
  task automatic csr(input integer fileid,input integer selector,input integer operation,input reg [63:0] data,input reg claim);
    begin
      io_csrRequest_valid=1;io_csrRequest_bits_file=fileid;io_csrRequest_bits_selector=selector;
      io_csrRequest_bits_operation=operation;io_csrRequest_bits_data=data;io_csrRequest_bits_topei=claim;
      while(!io_csrRequest_ready) step();
      step();io_csrRequest_valid=0;
    end
  endtask
  task automatic msi(input integer fileid,input integer ident,input reg bigendian);
    begin
      io_mmio_request_valid=1;io_mmio_request_bits_write=1;
      io_mmio_request_bits_address=(fileid==0?64'h24000000:64'h28000000+(fileid-1)*4096)+(bigendian?4:0);
      io_mmio_request_bits_data=bigendian?{ident[7:0],ident[15:8],ident[23:16],ident[31:24]}:ident;
      while(!io_mmio_request_ready) step();
      step();io_mmio_request_valid=0;
    end
  endtask
  integer a,b,r;
  initial begin
    bad_oracle=$test$plusargs("BAD_ORACLE");
    repeat(3)step();reset=0;
    for(a=0;a<4;a=a+1) begin
      csr(a,'h70,1,1,0);csr(a,'h70,3,1,0);csr(a,'h70,2,1,0);
      csr(a,'hc0,1,~64'b0,0);csr(a,'hc0,3,64'h100,0);csr(a,'hc0,2,64'h100,0);csr(a,'hc2,1,~64'b0,0);
      csr(a,'h80,1,64'h8000000000000101,0);csr(a,'h82,2,64'h8000000000000001,0);
      csr(a,0,0,0,1);csr(a,'h72,1,64'h1000000000000040,0);csr(a,'h72,0,0,0);
      csr(a,'h72,1,64,0);csr(a,0,0,0,1);csr(a,'h72,2,128,0);csr(a,'h72,3,64'hffffffffffffffff,0);
      csr(a,'h72,1,127,0);csr(a,'h72,0,0,0);csr(a,'h72,1,128,0);csr(a,'h72,0,0,0);
      csr(a,'h72,1,1,0);csr(a,0,0,0,1);csr(a,'h72,1,0,0);
      msi(a,63,0);msi(a,64,1);csr(a,0,1,0,1);csr(a,0,2,0,1);csr(a,0,3,0,1);
    end
    // Same-cycle claim and incoming MSI of the winning identity must retain the interrupt.
    csr(0,'h80,1,2,0);csr(0,'h82,1,0,0);
    io_mmio_request_valid=1;io_mmio_request_bits_write=1;io_mmio_request_bits_address='h24000000;io_mmio_request_bits_data=1;
    csr(0,0,1,0,1);io_mmio_request_valid=0;csr(0,0,0,0,1);
    // Fill both independent response queues and exercise stable blocked replies.
    repeat(4)step();io_csrResponse_ready=0;io_mmio_response_ready=0;
    csr(0,'h70,0,0,0);csr(1,'h70,0,0,0);msi(0,11,0);msi(1,12,0);
    repeat(6)step();io_csrResponse_ready=1;io_mmio_response_ready=1;repeat(4)step();
    for(a=0;a<6000;a=a+1) begin
      r=$random(seed);
      io_csrResponse_ready=(r&16)!=0;io_mmio_response_ready=(r&32)!=0;
      if(!io_csrRequest_valid || cfire) begin
      io_csrRequest_valid=(r&3)!=0;
      io_csrRequest_bits_file=(r>>6)&7;io_csrRequest_bits_operation=(r>>9)&3;io_csrRequest_bits_topei=(r&4096)!=0;
      case((r>>13)&15)
        0:io_csrRequest_bits_selector='h70;1:io_csrRequest_bits_selector='h72;
        2:io_csrRequest_bits_selector='h80;3:io_csrRequest_bits_selector='h82;
        4:io_csrRequest_bits_selector='hc0;5:io_csrRequest_bits_selector='hc2;
        6:io_csrRequest_bits_selector='h81;7:io_csrRequest_bits_selector='h6f;
        default:io_csrRequest_bits_selector='h7f;
      endcase
      io_csrRequest_bits_data={$random(seed),$random(seed)};
      if((r&256)==0)io_csrRequest_bits_data=(r>>18)&127;
      end
      if(!io_mmio_request_valid || mfire) begin
      io_mmio_request_valid=(r&12)!=0;
      b=(r>>20)&7;
      io_mmio_request_bits_address=(b==0?'h24000000:'h28000000+(b-1)*4096)+((r&8192)?4:0);
      io_mmio_request_bits_data=(r>>24)&255;io_mmio_request_bits_write=(r&16384)!=0;
      io_mmio_request_bits_size=(r&32768)?2:3;io_mmio_request_bits_byteEnable=(r&65536)?15:255;
      end
      step();
    end
    io_csrResponse_ready=1;io_mmio_response_ready=1;
    // Preserve the final outstanding offers as well as payloads stalled in the loop.
    if(cfire)io_csrRequest_valid=0;
    if(mfire)io_mmio_request_valid=0;
    while(io_csrRequest_valid || io_mmio_request_valid) begin
      step();
      if(cfire)io_csrRequest_valid=0;
      if(mfire)io_mmio_request_valid=0;
    end
    repeat(5)step();
    if(qr!=qw||mr!=mw||claims==0||simultaneous==0||blocked==0)fail("coverage/response conservation");
    $display("IMSIC_RMW_BATCH_PASS cycles=%0d csr=%0d mmio=%0d claims=%0d simultaneous=%0d blocked=%0d",cycles,qw,mw,claims,simultaneous,blocked);
    $finish;
  end
  initial begin #200000;$fatal(1,"timeout");end
endmodule


