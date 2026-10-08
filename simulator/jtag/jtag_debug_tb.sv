`timescale 1ns/1ps
module jtag_debug_tb;
    reg tck=0, tms=1, tdi=0, trst_n=0, debug_clk=0, debug_por_n=0;
    wire tdo, tdo_oe, dmi_reset_n, req_valid, rsp_ready;
    reg req_ready=1, rsp_valid=0;
    wire [1:0] req_op;
    wire [6:0] req_address;
    wire [31:0] req_data;
    reg [1:0] rsp_status=0, next_status=0;
    reg [31:0] rsp_data=0;
    integer sys_half=7, tck_half=11, delay_cycles=2, delay_left=0;
    reg sys_run=1, responder_run=1, pending=0;
    integer accepted=0, responded=0, expected_head=0, expected_tail=0;
    reg [40:0] expected [0:4095];
    reg [40:0] held_request;
    reg was_stalled=0;
    integer ref_state=0;
    integer edges [0:31];
    integer tck_edges=0, last_request_time=0, min_latency=32'h7fffffff, max_latency=0;
    integer seed=32'h17bad123;
    integer i,j,a, prior, base_count, rnd, throughput_start, throughput_edges;
    reg sample, oe_sample;
    reg [63:0] out_bits, in_bits;
    wire stub_tdo, stub_oe, off_tdo, off_oe;
    ValenceJtagDebugPort #(.ENABLE(1),.EXTERNAL_DMI(1)) dut (
        .tck(tck),.tms(tms),.tdi(tdi),.trst_n(trst_n),.debug_clk(debug_clk),.debug_por_n(debug_por_n),
        .tdo(tdo),.tdo_oe(tdo_oe),.dmi_reset_n(dmi_reset_n),.dmi_req_valid(req_valid),
        .dmi_req_ready(req_ready),.dmi_req_op(req_op),.dmi_req_address(req_address),.dmi_req_data(req_data),
        .dmi_rsp_valid(rsp_valid),.dmi_rsp_ready(rsp_ready),.dmi_rsp_status(rsp_status),.dmi_rsp_data(rsp_data));
    ValenceJtagDebugPort #(.ENABLE(1)) stub (
        .tck(tck),.tms(tms),.tdi(tdi),.trst_n(trst_n),.debug_clk(debug_clk),.debug_por_n(debug_por_n),
        .tdo(stub_tdo),.tdo_oe(stub_oe),.dmi_reset_n(),.dmi_req_valid(),.dmi_req_ready(1'b0),
        .dmi_req_op(),.dmi_req_address(),.dmi_req_data(),.dmi_rsp_valid(1'b0),.dmi_rsp_ready(),
        .dmi_rsp_status(2'b00),.dmi_rsp_data(32'b0));
    ValenceJtagDebugPort #(.ENABLE(0)) off (
        .tck(tck),.tms(tms),.tdi(tdi),.trst_n(trst_n),.debug_clk(debug_clk),.debug_por_n(debug_por_n),
        .tdo(off_tdo),.tdo_oe(off_oe),.dmi_reset_n(),.dmi_req_valid(),.dmi_req_ready(1'b0),
        .dmi_req_op(),.dmi_req_address(),.dmi_req_data(),.dmi_rsp_valid(1'b0),.dmi_rsp_ready(),
        .dmi_rsp_status(2'b00),.dmi_rsp_data(32'b0));
    always begin #(sys_half); if (sys_run) debug_clk=~debug_clk; else debug_clk=0; end
    function integer transition(input integer state, input integer tm);
        // IEEE TAP transition table: columns are TMS=0 and TMS=1.
        case(state)
          0:transition=tm?0:1; 1:transition=tm?2:1; 2:transition=tm?9:3; 3:transition=tm?5:4;
          4:transition=tm?5:4; 5:transition=tm?8:6; 6:transition=tm?7:6; 7:transition=tm?8:4;
          8:transition=tm?2:1; 9:transition=tm?0:10; 10:transition=tm?12:11; 11:transition=tm?12:11;
          12:transition=tm?15:13; 13:transition=tm?14:13; 14:transition=tm?15:11; 15:transition=tm?2:1;
          default:transition=0;
        endcase
    endfunction
    function [31:0] response_value(input [1:0] op,input [6:0] addr,input [31:0] data);
        response_value=op==1 ? (32'ha5000000 | addr) : (data ^ 32'h55aa77bb);
    endfunction
    always @(posedge debug_clk or negedge dmi_reset_n) begin
        if (!dmi_reset_n) begin rsp_valid<=0; pending<=0; was_stalled<=0; end
        else begin
            if (was_stalled && (!req_valid || {req_address,req_data,req_op} !== held_request))
                $fatal(1,"DMI request changed under backpressure");
            was_stalled<=req_valid && !req_ready;
            held_request<={req_address,req_data,req_op};
            if (req_valid && req_ready) begin
                if (pending || rsp_valid) $fatal(1,"overlapping DMI request");
                if (expected_head>=expected_tail) $fatal(1,"unexpected/duplicate request");
                if ({req_address,req_data,req_op} !== expected[expected_head])
                    $fatal(1,"payload mismatch: got %h expected %h",{req_address,req_data,req_op},expected[expected_head]);
                expected_head=expected_head+1; accepted=accepted+1;
                pending<=1; delay_left<=delay_cycles;
                rsp_data<=response_value(req_op,req_address,req_data); rsp_status<=next_status;
                last_request_time=$time;
            end
            if (pending && responder_run) begin
                if (delay_left==0) begin pending<=0; rsp_valid<=1; end
                else delay_left<=delay_left-1;
            end
            if (rsp_valid && rsp_ready) begin
                rsp_valid<=0; responded=responded+1;
                if ($time-last_request_time < min_latency) min_latency=$time-last_request_time;
                if ($time-last_request_time > max_latency) max_latency=$time-last_request_time;
            end
        end
    end
    task tick(input bit tm,input bit td,output bit result);
        begin
            tms=tm; tdi=td; #(tck_half);
            result=tdo;
            if (tdo_oe !== (ref_state==4 || ref_state==11)) $fatal(1,"TDO OE state %d",ref_state);
            edges[ref_state*2+tm]=edges[ref_state*2+tm]+1;
            ref_state=transition(ref_state,tm);
            tck=1; #1;
            if (dut.enabled.tap.state !== ref_state[3:0]) $fatal(1,"TAP transition mismatch");
            if (off_tdo !== 0 || off_oe !== 0) $fatal(1,"disabled debug not tied off");
            #(tck_half); tck=0; #1; tck_edges=tck_edges+1;
        end
    endtask
    task idle(input integer n);
        integer k; begin for(k=0;k<n;k=k+1) tick(0,0,sample); end
    endtask
    task reset_tap;
        integer k; begin
            for(k=0;k<5;k=k+1) tick(1,0,sample);
            if(ref_state!=0 || dut.enabled.tap.instruction!=1) $fatal(1,"five TMS reset failed");
            tick(0,0,sample); idle(8);
        end
    endtask
    task ir(input [4:0] value);
        integer k; reg [4:0] captured;
        begin
            tick(1,0,sample); tick(1,0,sample); tick(0,0,sample); tick(0,0,sample);
            for(k=0;k<5;k=k+1) tick(k==4,value[k],captured[k]);
            tick(1,0,sample); tick(0,0,sample);
            if(captured!==1) $fatal(1,"IR capture off-by-one: %h",captured);
        end
    endtask
    task scan(input integer width,input [63:0] value,output [63:0] result);
        integer k;
        begin
            result=0; tick(1,0,sample); tick(0,0,sample); tick(0,0,sample);
            for(k=0;k<width;k=k+1) tick(k==width-1,value[k],result[k]);
            tick(1,0,sample); tick(0,0,sample);
        end
    endtask
    task expect_request(input [1:0] op,input [6:0] addr,input [31:0] data);
        begin expected[expected_tail]={addr,data,op}; expected_tail=expected_tail+1; end
    endtask
    task clear_error;
        begin ir(5'h10); scan(32,64'h10000,out_bits); idle(8); ir(5'h11); end
    endtask
    task request(input [1:0] op,input [6:0] addr,input [31:0] data);
        begin expect_request(op,addr,data); scan(41,{23'b0,addr,data,op},out_bits); end
    endtask
    task wait_result(input [6:0] addr,input [31:0] value,input [1:0] status);
        begin
            idle(30); scan(41,0,out_bits);
            if(out_bits[1:0]!==status) $fatal(1,"DMI status got %h expected %h",out_bits[1:0],status);
            if(status==0 && (out_bits[40:34]!==addr || out_bits[33:2]!==value))
                $fatal(1,"DMI result/address got %h",out_bits);
        end
    endtask
    task visit(input integer target);
        integer q[0:15], previous[0:15], route[0:31];
        integer head,tail,node,child,bitval,depth;
        begin
            for(node=0;node<16;node=node+1) previous[node]=-2;
            q[0]=ref_state; previous[ref_state]=-1; head=0;tail=1;
            while(head<tail && previous[target]==-2) begin
                node=q[head];head=head+1;
                for(bitval=0;bitval<2;bitval=bitval+1) begin
                    child=transition(node,bitval);
                    if(previous[child]==-2) begin previous[child]=node*2+bitval;q[tail]=child;tail=tail+1;end
                end
            end
            node=target;depth=0;
            while(previous[node]!=-1) begin route[depth]=previous[node]%2;depth=depth+1;node=previous[node]/2;end
            while(depth>0) begin depth=depth-1;tick(route[depth],0,sample);end
        end
    endtask
    initial begin
        for(i=0;i<32;i=i+1) edges[i]=0;
        #2; debug_por_n=1; trst_n=1; #2;
        reset_tap;
        scan(32,0,out_bits); if(out_bits[31:0]!==32'h1) $fatal(1,"IDCODE shift order %h",out_bits);
        // IR pause must preserve both partial shift data and the old active IR.
        out_bits=0;in_bits=31;
        tick(1,0,sample);tick(1,0,sample);tick(0,0,sample);tick(0,0,sample);
        for(i=0;i<2;i=i+1) tick(i==1,in_bits[i],out_bits[i]);
        tick(0,0,sample);idle(6);
        if(dut.enabled.tap.instruction!==1) $fatal(1,"IR updated during pause");
        tick(1,0,sample);tick(0,0,sample);
        for(i=2;i<5;i=i+1) tick(i==4,in_bits[i],out_bits[i]);
        tick(1,0,sample);tick(0,0,sample);
        if(out_bits[4:0]!==1 || dut.enabled.tap.instruction!==31) $fatal(1,"IR capture/pause/update");
        for(i=0;i<32;i=i+1) begin
            ir(i[4:0]);
            if(i!=1 && i!=16 && i!=17) begin
                scan(16,64'ha35c,out_bits);
                if(out_bits[15:0]!==16'h46b8) $fatal(1,"BYPASS instruction=%d got=%h",i,out_bits);
            end
        end
        reset_tap;
        // Pausing in the middle of a 32-bit IDCODE must neither shift nor capture.
        out_bits=0; tick(1,0,sample);tick(0,0,sample);tick(0,0,sample);
        for(i=0;i<7;i=i+1) tick(i==6,0,out_bits[i]);
        tick(0,0,sample);idle(9);tick(1,0,sample);tick(0,0,sample);
        for(i=7;i<32;i=i+1) tick(i==31,0,out_bits[i]);
        tick(1,0,sample);tick(0,0,sample);
        if(out_bits[31:0]!==1) $fatal(1,"DR pause corrupted data");
        // Walk every arc using a graph search independent of the DUT state logic.
        for(i=0;i<16;i=i+1) for(j=0;j<2;j=j+1) begin visit(i);tick(j,0,sample);end
        for(i=0;i<16;i=i+1) begin visit(i);reset_tap;end
        for(i=0;i<2000;i=i+1) begin rnd=$random(seed);tick(rnd&1,0,sample);end
        reset_tap;
        for(i=0;i<32;i=i+1) if(edges[i]==0) $fatal(1,"uncovered TAP arc %d",i);
        ir(5'h10);scan(32,0,out_bits);
        if(out_bits[31:0]!==32'h7071) $fatal(1,"DTMCS wrong version/abits/idle/fields %h",out_bits);
        ir(5'h11);
        request(1,7'h11,0);wait_result(7'h11,32'ha5000011,0);
        // Stub is independently observed: all DMI requests fail, including dmstatus.
        if(stub.enabled.sticky_status!==2) $fatal(1,"stub falsely reported a Debug Module");
        clear_error;
        request(2,7'h04,32'h01234567);wait_result(7'h04,32'h548932dc,0);
        // Changing DR shift payload while the system endpoint stalls cannot change
        // the already accepted mailbox contents or dispatch a second command.
        req_ready=0; request(2,7'h20,32'hcafebabe);base_count=accepted;
        scan(41,64'h1fffffffffe,out_bits);
        if(out_bits[1:0]!==3) $fatal(1,"pending request did not return busy");
        idle(10); if(accepted!=base_count) $fatal(1,"stalled request accepted");
        req_ready=1;idle(30);
        scan(41,0,out_bits);if(out_bits[1:0]!==3) $fatal(1,"busy not sticky");
        clear_error; scan(41,0,out_bits);if(out_bits[1:0]!==0) $fatal(1,"busy reset failed");
        // Failure remains sticky; ignored scans must not create hidden commands.
        next_status=2;request(1,7'h33,0);wait_result(0,0,2);base_count=accepted;
        scan(41,{23'b0,7'h01,32'hffff,2'b10},out_bits);idle(20);
        if(accepted!=base_count) $fatal(1,"request escaped sticky error");
        clear_error;next_status=0;
        // dmireset clears only sticky status. It cannot cancel an outstanding access.
        responder_run=0;request(1,7'h44,0);idle(20);scan(41,0,out_bits);
        clear_error;responder_run=1;wait_result(7'h44,32'ha5000044,0);
        // Hard reset cancels a hung access and resets the endpoint while TCK resumes.
        responder_run=0;request(1,7'h55,0);idle(20);
        ir(5'h10);scan(32,64'h20000,out_bits);idle(10);responder_run=1;
        ir(5'h11);request(1,7'h56,0);wait_result(7'h56,32'ha5000056,0);
        // Stop TCK: the destination may finish but cannot duplicate or lose payload.
        request(2,7'h61,32'hf00d1234);#2000;
        wait_result(7'h61,32'ha5a7658f,0);
        // Stop system clock, then asynchronously reset the complete debug island.
        sys_run=0;request(1,7'h62,0);idle(5);
        #3;trst_n=0;ref_state=0;#31;
        expected_tail=expected_head; // explicitly cancelled before system acceptance
        if(req_valid!==0 || rsp_ready!==0 || tdo_oe!==0) $fatal(1,"async reset did not isolate");
        trst_n=1;sys_run=1;reset_tap;ir(5'h11);
        // Random independent clock ratios, backpressure, pauses, and read/write payloads.
        for(i=0;i<200;i=i+1) begin
            rnd=$random(seed);sys_half=2+(rnd&15);rnd=$random(seed);tck_half=2+(rnd&31);
            rnd=$random(seed);delay_cycles=rnd&7;
            in_bits={$random(seed),$random(seed)};a=i%128;
            req_ready=0;request(i[0]?2:1,a[6:0],in_bits[31:0]);
            #((i%13)*31);req_ready=1;
            idle(100);wait_result(a[6:0],response_value(i[0]?2:1,a[6:0],in_bits[31:0]),0);
        end
        // Fixed-configuration transport cost, measured in TCK edges, not FPGA Fmax.
        sys_half=7;tck_half=11;delay_cycles=2;throughput_start=tck_edges;
        for(i=0;i<100;i=i+1) begin
            expect_request(1,i[6:0],0);scan(41,{23'b0,i[6:0],32'b0,2'b01},out_bits);
            if(out_bits[1:0]!==0) $fatal(1,"recommended-idle throughput returned busy");
            if(i>0 && (out_bits[40:34]!==((i-1)&127) || out_bits[33:2]!== (32'ha5000000 | (i-1))))
                $fatal(1,"pipelined response mismatch");
            idle(7);
        end
        scan(41,0,out_bits);throughput_edges=tck_edges-throughput_start;
        if(out_bits[1:0]!==0 || out_bits[33:2]!==32'ha5000063) $fatal(1,"last throughput response");
        $display("PERF completed=100 tck_edges=%0d steady_tck_per_request=53 includes_final_drain=46",throughput_edges);
        if(expected_head!=expected_tail) $fatal(1,"requests not all delivered");
        $display("PASS JTAG arcs=32 instructions=32 random_transactions=200 accepted=%0d responses=%0d tck_edges=%0d endpoint_latency_ns_min=%0d max=%0d",accepted,responded,tck_edges,min_latency,max_latency);
        $finish;
    end
    initial begin #100000000; $fatal(1,"timeout"); end
endmodule
