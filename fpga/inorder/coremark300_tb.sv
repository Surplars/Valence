`timescale 1ns/1fs
// Real generated cached CPU, with a bounded two-port memory server.
// C/Q/V/R/P trace records are checked by the original independent C++ oracles.
module coremark300_tb;
reg clock=0; always #(5.0/3.0) clock=~clock;
reg reset=1;
reg [63:0] sim_time=0;
reg [1:0] request_ready=0,response_valid=0,response_error=0,response_last=0;
wire [1:0] request_valid,request_write,response_ready;
wire [63:0] request_address[0:1],request_data[0:1];
wire [7:0] request_mask[0:1];
wire [3:0] request_beats[0:1];
reg [63:0] response_data[0:1];
wire retire_valid,retire_write,retire_trap,trap_taken;
wire [63:0] retire_pc,retire_next,retire_data,retire_cause,retire_tval,retire_prediction;
wire [31:0] retire_instruction; wire [4:0] retire_rd;
wire resolve_valid;wire [63:0] resolve_pc,resolve_prediction,resolve_next;
wire mispredict,stall_fetch,stall_memory,stall_load,stall_mdu,store_ack,data_accepted,data_offered;
wire instruction_hit,instruction_miss,data_hit,data_miss;
I1PerformanceCachedCore dut(
 .clock(clock),.reset(reset),.io_time(sim_time),
 .io_externalIrq(1'b0),.io_timerIrq(1'b0),.io_softwareIrq(1'b0),
 .io_instructionMemory_request_ready(request_ready[0]),
 .io_instructionMemory_request_valid(request_valid[0]),
 .io_instructionMemory_request_bits_address(request_address[0]),
 .io_instructionMemory_request_bits_write(request_write[0]),
 .io_instructionMemory_request_bits_data(request_data[0]),
 .io_instructionMemory_request_bits_mask(request_mask[0]),
 .io_instructionMemory_request_bits_beats(request_beats[0]),
 .io_instructionMemory_response_ready(response_ready[0]),
 .io_instructionMemory_response_valid(response_valid[0]),
 .io_instructionMemory_response_bits_data(response_data[0]),
 .io_instructionMemory_response_bits_error(response_error[0]),
 .io_instructionMemory_response_bits_last(response_last[0]),
 .io_dataMemory_request_ready(request_ready[1]),
 .io_dataMemory_request_valid(request_valid[1]),
 .io_dataMemory_request_bits_address(request_address[1]),
 .io_dataMemory_request_bits_write(request_write[1]),
 .io_dataMemory_request_bits_data(request_data[1]),
 .io_dataMemory_request_bits_mask(request_mask[1]),
 .io_dataMemory_request_bits_beats(request_beats[1]),
 .io_dataMemory_response_ready(response_ready[1]),
 .io_dataMemory_response_valid(response_valid[1]),
 .io_dataMemory_response_bits_data(response_data[1]),
 .io_dataMemory_response_bits_error(response_error[1]),
 .io_dataMemory_response_bits_last(response_last[1]),
 .io_retire_valid(retire_valid),
 .io_retire_bits_pc(retire_pc),
 .io_retire_bits_instruction(retire_instruction),
 .io_retire_bits_nextPc(retire_next),
 .io_retire_bits_rd(retire_rd),
 .io_retire_bits_writesRd(retire_write),
 .io_retire_bits_data(retire_data),
 .io_retire_bits_trap(retire_trap),
 .io_retire_bits_cause(retire_cause),
 .io_retire_bits_tval(retire_tval),
 .io_trapTaken(trap_taken),
 .io_branchMispredict(mispredict),
 .io_stallFetch(stall_fetch),
 .io_stallMemory(stall_memory),
 .io_stallLoadUse(stall_load),
 .io_stallMulDiv(stall_mdu),
 .io_stallStoreAck(store_ack),
 .io_dataRequestAccepted(data_accepted),
 .io_dataRequestOffered(data_offered),
 .io_instructionHit(instruction_hit),
 .io_instructionMiss(instruction_miss),
 .io_dataHit(data_hit),
 .io_dataMiss(data_miss),
 .observation_retiredPrediction(retire_prediction),
 .observation_resolveValid(resolve_valid),
 .observation_resolvePc(resolve_pc),
 .observation_resolvePrediction(resolve_prediction),
 .observation_resolveNextPc(resolve_next)
);
localparam [63:0] BASE=64'h80000000,TIMER=64'h0200bff8;
reg [7:0] memory[0:73727];
reg owner[0:1],prepared[0:1],write_owner[0:1],error_owner[0:1];
reg [63:0] address[0:1],data_owner[0:1],value[0:1];
reg [7:0] mask[0:1];
integer beats[0:1],beat[0:1];longint unsigned due[0:1];
integer active=-1,last=1,latency=1,fd,i,j,port,choice;
longint unsigned cycle=0,retired=0;
reg [31:0] flags;
reg [63:0] current_address;
reg held[0:1];reg [140:0] held_request[0:1];
string image,traceName,ramName;
initial begin
 for(i=0;i<73728;i=i+1)memory[i]=0;
 if(!$value$plusargs("IMAGE=%s",image))$fatal(1,"IMAGE required");
 if(!$value$plusargs("LATENCY=%d",latency))latency=1;
 if(latency<1)$fatal(1,"positive latency required");
 $readmemh(image,memory);
 if(!$value$plusargs("TRACE=%s",traceName))traceName="cpu.trace";
 if(!$value$plusargs("FINAL_RAM=%s",ramName))$fatal(1,"FINAL_RAM required");
 fd=$fopen(traceName,"w");if(!fd)$fatal(1,"trace open failed");
 for(i=0;i<2;i=i+1)begin
  owner[i]=0;prepared[i]=0;write_owner[i]=0;error_owner[i]=0;
  address[i]=0;data_owner[i]=0;value[i]=0;mask[i]=0;beats[i]=0;beat[i]=0;due[i]=0;
  held[i]=0;held_request[i]=0;response_data[i]=0;
 end
 repeat(8)@(posedge clock);#0.05;reset=0;
end
always @(negedge clock)begin
 if(reset)begin request_ready=0;response_valid=0;response_error=0;response_last=0;end
 else begin
  sim_time=cycle;
  if(active<0)begin
   choice=-1;
   if(owner[(last+1)%2])choice=(last+1)%2;else if(owner[last])choice=last;
   if(choice>=0)begin active=choice;last=choice;due[choice]=cycle+latency;end
  end
  if(active>=0&&due[active]<=cycle&&!prepared[active])begin
   current_address=address[active]+8*beat[active];
   error_owner[active]=current_address!=TIMER&&
      (current_address<BASE||current_address+8>BASE+73728);
   value[active]=0;
   if(current_address==TIMER)value[active]=cycle;
   else if(!error_owner[active])for(j=0;j<8;j=j+1)
     value[active][j*8+:8]=memory[current_address-BASE+j];
   prepared[active]=1;
  end
  for(port=0;port<2;port=port+1)begin
   request_ready[port]=!owner[port];
   response_valid[port]=active==port&&prepared[port];
   response_data[port]=owner[port]?value[port]:0;
   response_error[port]=owner[port]&&error_owner[port];
   response_last[port]=owner[port]&&beat[port]+1==beats[port];
  end
 end
end
always @(posedge clock)if(!reset)begin
 `ifdef I1_TRACE_DEBUG
 if(cycle<32)$display("CONTROL c=%0d IF=%b ID=%b RF=%b EX=%b ADDR=%b MEM=%b CMP=%b WB=%b rec=%b cmpFault=%b memFire=%b instID=%h instEX=%h",
 cycle,dut.core.ifValid,dut.core.idValid,dut.core.rrValid,dut.core.exValid,
 dut.core.addrValid,dut.core.memValid,dut.core.cmpValid,dut.core.wbValid,dut.core.wbRecovery,
 dut.core.cmpPacket_completion_fault,dut.core.memFire,dut.core.idPacket_instruction,dut.core.exPacket_instruction_instruction);
 if(cycle<24)$display("FETCH c=%0d req=%b/%b pc=%h resp=%b/%b data=%h upper=%b inst=%h state=%0d ram=%h saved=%h hit=%b",cycle,
 dut.core.io_instructionRequest_valid,dut.core.io_instructionRequest_ready,dut.core.io_instructionRequest_bits,
 dut.core.io_instructionResponse_valid,dut.core.io_instructionResponse_ready,dut.icache.io_response_bits_data,
 dut.fetchUpper,dut.core.io_instructionResponse_bits_instruction,dut.icache.state,dut.icache._data_ext_R0_data,
 dut.icache.saved_address,dut.icache.hit);
 `endif
 flags=0;
 flags[0]=mispredict;flags[1]=stall_fetch;flags[2]=stall_memory;flags[3]=stall_load;
 flags[4]=stall_mdu;flags[5]=data_accepted;flags[6]=resolve_valid;
 flags[7]=instruction_hit;flags[8]=instruction_miss;flags[9]=data_hit;flags[10]=data_miss;
 flags[11]=store_ack;flags[12]=data_offered;
 flags[13]=request_valid[0];flags[14]=request_valid[1];
 flags[15]=response_ready[0];flags[16]=response_ready[1];flags[17]=retire_valid;
 flags[18]=request_ready[0];flags[19]=request_ready[1];
 flags[20]=response_valid[0];flags[21]=response_valid[1];
 flags[22]=response_error[0];flags[23]=response_error[1];
 flags[24]=response_last[0];flags[25]=response_last[1];flags[26]=trap_taken;
 if($isunknown(flags))begin
  $display("unknown diagnostic req=%b respReady=%b respValid=%b retireValid=%b resolveValid=%b trap=%b flags=%b",
    request_valid,response_ready,response_valid,retire_valid,resolve_valid,trap_taken,flags);
  $fatal(1,"unknown valid/control cycle=%0d flags=%h",cycle,flags);
 end
 $fwrite(fd,"C %0d %h\n",cycle,flags);
 for(port=0;port<2;port=port+1)begin
  if(request_valid[port])$fwrite(fd,"Q %h %h %h %h %h %h\n",port,
    request_address[port],request_write[port],request_write[port]?request_data[port]:64'b0,
    request_write[port]?request_mask[port]:8'b0,request_beats[port]);
  if(response_valid[port])$fwrite(fd,"V %h %h\n",port,response_data[port]);
 end
 if(resolve_valid)$fwrite(fd,"P %h %h %h\n",resolve_pc,resolve_prediction,resolve_next);
 if(retire_valid)$fwrite(fd,"R %h %h %h %h %h %h %h %h %h %h\n",
   retire_pc,retire_instruction,retire_write?retire_rd:5'b0,retire_write,
   retire_write?retire_data:64'b0,retire_next,retire_trap,
   retire_trap?retire_cause:64'b0,retire_trap?retire_tval:64'b0,
   (retire_instruction[6:0]==7'h63||retire_instruction[6:0]==7'h6f||retire_instruction[6:0]==7'h67)?retire_prediction:64'b0);
 // The server commits only the accepted beat. CPU stores are never speculative successes.
 if(active>=0&&prepared[active]&&response_ready[active])begin
  current_address=address[active]+8*beat[active];
  if(!error_owner[active]&&write_owner[active])begin
   if(current_address<BASE||current_address+8>BASE+73728)$fatal(1,"write range");
   for(j=0;j<8;j=j+1)if(mask[active][j])memory[current_address-BASE+j]=data_owner[active][j*8+:8];
  end
  prepared[active]=0;due[active]=cycle+1;beat[active]=beat[active]+1;
  if(beat[active]==beats[active])begin owner[active]=0;active=-1;end
 end
 for(port=0;port<2;port=port+1)begin
  if(held[port]&&(!request_valid[port]||
     {request_address[port],request_write[port],request_data[port],request_mask[port],request_beats[port]}!==held_request[port]))
    $fatal(1,"burst offer changed while blocked");
  held[port]=request_valid[port]&&!request_ready[port];
  held_request[port]={request_address[port],request_write[port],request_data[port],request_mask[port],request_beats[port]};
  if(request_valid[port]&&request_ready[port])begin
   if(owner[port]||request_address[port][2:0]!=0||request_beats[port]<1||request_beats[port]>8)
      $fatal(1,"duplicate owner or illegal burst");
   owner[port]=1;address[port]=request_address[port];write_owner[port]=request_write[port];
   data_owner[port]=request_data[port];mask[port]=request_mask[port];
   beats[port]=request_beats[port];beat[port]=0;prepared[port]=0;error_owner[port]=0;
   value[port]=0;due[port]=cycle+latency;
  end
 end
 if(retire_valid&&retire_trap)begin
  if(retire_instruction!==32'h00100073||retire_cause!==64'd3)$fatal(1,"unexpected CPU trap");
  if((owner[1]&&write_owner[1])||(request_valid[1]&&request_write[1]))
      $fatal(1,"CPU stopped with an external write owner");
  $writememh(ramName,memory);
  $fwrite(fd,"E\nZ\n");$fclose(fd);
  $display("XSIM_COREMARK_DONE cycles=%0d retired=%0d latency=%0d clock_hz=300000000",cycle,retired,latency);
  $finish;
 end
 $fwrite(fd,"Z\n");
 if(retire_valid&&!retire_trap)retired=retired+1;
 cycle=cycle+1;
 if(cycle>2000000)$fatal(1,"CPU simulation exceeded bounded timeout");
end
endmodule
