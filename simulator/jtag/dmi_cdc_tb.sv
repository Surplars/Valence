`timescale 1ns/1ps
module dmi_cdc_tb;
    reg tck=0,clk=0,reset_n=0;
    reg sv=0,sready=0,dr=0,dv=0;
    reg [40:0] sp=0;
    reg [33:0] dp=0;
    wire sr,srv,busy,dmrst,dqv,drr;
    wire [40:0] dq;
    wire [33:0] sdata;
    reg [40:0] request;
    reg [33:0] response;
    integer i,j,sent=0,received=0;
    ValenceDmiCdc dut(.tck(tck),.debug_clk(clk),.reset_n(reset_n),
        .s_req_valid(sv),.s_req_ready(sr),.s_req_payload(sp),.s_rsp_valid(srv),.s_rsp_payload(sdata),
        .s_rsp_ready(sready),.s_busy(busy),.dmi_reset_n(dmrst),.d_req_valid(dqv),.d_req_ready(dr),
        .d_req_payload(dq),.d_rsp_valid(dv),.d_rsp_ready(drr),.d_rsp_payload(dp));
    always #11 tck=~tck;
    always #7 clk=~clk;
    always @(posedge clk) if(dmrst && dqv && dr) received=received+1;
    task send(input [40:0] payload);
        begin
            @(posedge tck);while(!sr)@(posedge tck);
            sp=payload;sv=1;@(negedge tck);#1;sent=sent+1;
            @(posedge tck);sv=0;sp=~payload;
        end
    endtask
    initial begin
        #3;reset_n=1;
        for(i=0;i<100;i=i+1) begin
            request={$random,$random};response={$random,$random};
            send(request);
            wait(dqv);#1;
            for(j=0;j<i%7+2;j=j+1)begin
                @(negedge clk);if(!dqv || dq!==request)$fatal(1,"stalled request unstable");
            end
            dr=1;@(posedge clk);#1;dr=0;
            if(!busy || sr)$fatal(1,"source not busy during outstanding work");
            repeat(i%5+1)@(negedge clk);
            dp=response;dv=1;wait(drr);@(posedge clk);#1;dv=0;dp=~response;
            wait(srv);#1;
            for(j=0;j<i%11+3;j=j+1)begin
                @(posedge tck);if(!srv || sdata!==response || sr)$fatal(1,"stalled response unstable");
            end
            sready=1;@(negedge tck);#1;sready=0;
        end
        if(sent!=100 || received!=100)$fatal(1,"request lost/duplicated");
        // Reset while source has an unconsumed response, then reject stale replay.
        send(41'h123456789ab);wait(dqv);@(negedge clk);dr=1;@(posedge clk);#1;dr=0;
        @(negedge clk);dp=34'h212345678;dv=1;@(posedge clk);#1;dv=0;
        wait(srv);#3;reset_n=0;#1;
        if(srv!==0 || dqv!==0 || drr!==0 || sr!==0)$fatal(1,"reset isolation failure");
        #25;reset_n=1;repeat(12)@(posedge tck);
        if(srv || dqv || busy || received!=101)$fatal(1,"stale request/response after reset");
        $display("PASS CDC requests=101 random_payloads=100 source_response_backpressure=100 reset_no_replay=1");
        $finish;
    end
    initial begin #1000000;$fatal(1,"CDC timeout");end
endmodule
