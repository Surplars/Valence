`timescale 1ns/1ps
// Pin-event integration witness: production BSCAN transport (including its real
// ValenceDmiCdc) and source-bound production JtagRamLoader. The only interposed
// logic is a test-controlled valid/ready stall gate; no endpoint is reimplemented.
// This is not a vendor TAP model, metastability test, or physical timing proof.
module bscan_loader_fault_tb #(
    parameter integer SYS_HALF=7, TCK_HALF=25, BAD_RESET_OWNER=0
);
    // Exact elaborated production constant. Never shorten the staged loader.
    localparam integer TIMEOUT_CYCLES=1000000;
    localparam [31:0] RAM_ADDRESS=32'h80200004;
    localparam [31:0] REPLACEMENT_B=32'hdeadbeef;
    reg clk=0, tck=0, drck=0, capture=0, shift=0, update=0, sel=1, tap_reset=0, tdi=0;
    reg system_reset=1, por_n=0, endpoint_enable=1, response_enable=1;
    always #(SYS_HALF) clk=~clk;
    wire tdo, link, req_valid, req_ready, loader_req_ready, loader_rsp_valid, rsp_ready;
    wire [1:0] req_op, rsp_status;
    wire [6:0] req_address;
    wire [31:0] req_data, rsp_data;
    assign req_ready=endpoint_enable && loader_req_ready;
    ValenceBscanUserTransport dut(
        .bscan_tck(tck),.bscan_drck(drck),.bscan_capture(capture),.bscan_shift(shift),
        .bscan_update(update),.bscan_sel(sel),.bscan_reset(tap_reset),.bscan_tdi(tdi),.bscan_tdo(tdo),
        .debug_clk(clk),.debug_por_n(por_n),.dmi_reset_n(link),
        .dmi_req_valid(req_valid),.dmi_req_ready(req_ready),.dmi_req_op(req_op),
        .dmi_req_address(req_address),.dmi_req_data(req_data),
        .dmi_rsp_valid(loader_rsp_valid && response_enable),.dmi_rsp_ready(rsp_ready),
        .dmi_rsp_status(rsp_status),.dmi_rsp_data(rsp_data));
    reg cv=0, cwrite=0, crready=0;
    reg [63:0] ca=0, cd=0;
    wire cqready, crvalid, crerror;
    wire [63:0] crdata;
    reg mqready=0, mrvalid=0, mrerror=0;
    wire mqvalid, mwrite, mrready;
    wire [63:0] ma, md;
    wire [2:0] msize;
    wire [7:0] mbytes;
    JtagRamLoader loader(.clock(clk),.reset(system_reset || (BAD_RESET_OWNER && !link)),
        .io_linkUp(link),.io_dmi_request_valid(req_valid && endpoint_enable),
        .io_dmi_request_ready(loader_req_ready),.io_dmi_request_bits_op(req_op),
        .io_dmi_request_bits_address(req_address),.io_dmi_request_bits_data(req_data),
        .io_dmi_response_valid(loader_rsp_valid),.io_dmi_response_ready(rsp_ready && response_enable),
        .io_dmi_response_bits_data(rsp_data),.io_dmi_response_bits_status(rsp_status),
        .io_control_request_valid(cv),.io_control_request_ready(cqready),
        .io_control_request_bits_address(ca),.io_control_request_bits_write(cwrite),
        .io_control_request_bits_size(3'd3),.io_control_request_bits_data(cd),
        .io_control_request_bits_byteEnable(8'hff),.io_control_response_valid(crvalid),
        .io_control_response_ready(crready),.io_control_response_bits_data(crdata),
        .io_control_response_bits_error(crerror),.io_memory_request_valid(mqvalid),
        .io_memory_request_ready(mqready),.io_memory_request_bits_address(ma),
        .io_memory_request_bits_write(mwrite),.io_memory_request_bits_size(msize),
        .io_memory_request_bits_data(md),.io_memory_request_bits_byteEnable(mbytes),
        .io_memory_response_valid(mrvalid),.io_memory_response_ready(mrready),
        .io_memory_response_bits_data(64'h12345678),.io_memory_response_bits_error(mrerror));

    integer admissions=0, dmi_writes=0, memory_writes=0, memory_replies=0;
    integer epoch_dmi=0, epoch_memory=0, owner_cycles=0, timeout_edges=0;
    reg [31:0] expected_a=0;
    reg timeout_monitor=0;
    // Score the three actual boundaries independently. A distinct B is forbidden
    // at both public downstream boundaries, not just in a transport register.
    always @(negedge tck)
        if(dut.accept_dmi && dut.source_ready) admissions=admissions+1;
    always @(posedge clk) begin
        if(!system_reset && req_valid && req_ready && req_op==2 && req_address==7'h3c) begin
            if(req_data!==expected_a || req_data===REPLACEMENT_B)
                $fatal(1,"BSCAN_LOADER_ORACLE replacement reached production endpoint");
            dmi_writes=dmi_writes+1;
            if(dmi_writes!=epoch_dmi+1)$fatal(1,"BSCAN_LOADER_ORACLE duplicate endpoint write");
        end
        if(!system_reset && mqvalid && mqready) begin
            if(ma!=={32'b0,RAM_ADDRESS} || md!=={32'b0,expected_a} || !mwrite || msize!==2 || mbytes!==15)
                $fatal(1,"BSCAN_LOADER_ORACLE wrong first memory write/replacement B");
            memory_writes=memory_writes+1;
            if(memory_writes!=epoch_memory+1)$fatal(1,"BSCAN_LOADER_ORACLE duplicate memory write");
        end
        if(!system_reset && mrvalid && mrready) memory_replies=memory_replies+1;
        // Count ownership from public offered/awaiting signals, independent of
        // the implementation counter. Observe the exact timeout transition after
        // NBA, then also verify BUSY/fault via the CPU control interface below.
        if(timeout_monitor && (mqvalid || mrready)) begin
            owner_cycles=owner_cycles+1;
            #1;
            if(owner_cycles<TIMEOUT_CYCLES && loader.timedOut!==0)
                $fatal(1,"TIMEOUT_LAW_ORACLE production timeout fired early");
            if(owner_cycles==TIMEOUT_CYCLES) begin
                if(loader.timedOut!==1 || !mrready)
                    $fatal(1,"TIMEOUT_LAW_ORACLE exact timeout/retained owner");
                timeout_edges=timeout_edges+1;
            end
        end
    end

    function [63:0] frame(input [1:0] op,input [6:0] address,input [31:0] data);
        frame={16'h5642,4'h1,3'b0,address,data,op};
    endfunction
    task rise; begin #(TCK_HALF-1);tck=1;#1;end endtask
    task fall; begin #(TCK_HALF-1);tck=0;#1;end endtask
    task cycle; begin rise;fall;end endtask
    task idle(input integer count);
        integer k;begin for(k=0;k<count;k=k+1)cycle;end
    endtask
    task event_update; begin update=1;#1;update=0;#1;end endtask
    reg [63:0] rx;
    task load(input [63:0] value);
        integer k;
        begin
            capture=1;rise;drck=1;#1;drck=0;capture=0;fall;
            for(k=0;k<64;k=k+1)begin
                shift=1;tdi=value[k];rx[k]=tdo;
                rise;drck=1;#1;drck=0;shift=0;fall;
            end
            if(rx[63:44]!==20'h56421)$fatal(1,"BSCAN_LOADER_ORACLE serial status signature");
        end
    endtask
    task command(input [63:0] value);
        begin load(value);cycle;cycle;event_update;end
    endtask
    task raw_replace_shift(input [63:0] value);
        integer k;
        begin
            // Deliberately illegal pin stimulus: no TCK from P3 through this
            // complete DRCK shift and duplicate UPDATE. The first bundle stays A.
            capture=1;drck=1;#1;drck=0;capture=0;#1;
            for(k=0;k<64;k=k+1)begin
                shift=1;tdi=value[k];drck=1;#1;drck=0;#1;
            end
            shift=0;
            if(dut.shift_frame!==value)$fatal(1,"BSCAN_LOADER_ORACLE B stimulus was not shifted");
        end
    endtask
    reg [63:0] status;
    task cpu(input integer offset,input logic write,input [63:0] value,input logic expected_error);
        begin
            @(negedge clk);ca=64'h10003000+offset;cwrite=write;cd=value;cv=1;
            while(!cqready)@(negedge clk);
            @(posedge clk);#1;@(negedge clk);cv=0;
            wait(crvalid);#1;
            if(crerror!==expected_error)$fatal(1,"BSCAN_LOADER_ORACLE CPU control response mismatch");
            status=crdata;crready=1;@(posedge clk);#1;@(negedge clk);crready=0;
        end
    endtask
    task open_session(input logic error); begin cpu(8,1,1,error);end endtask
    task fresh_transport;
        begin
            tap_reset=1;#2;
            if(link)$fatal(1,"BSCAN_LOADER_ORACLE TAP reset did not isolate link");
            tap_reset=0;idle(10);
            if(!link || dut.protocol_error || dut.update_overrun || dut.fault_sample)
                $fatal(1,"BSCAN_LOADER_ORACLE new fault epoch did not clear");
        end
    endtask
    task legal_address;
        integer old_admissions;
        begin
            old_admissions=admissions;
            command(frame(2,7'h39,RAM_ADDRESS));idle(16);
            command(frame(0,0,0));
            if(admissions!=old_admissions+1 || rx[43] || rx[42] || !rx[41] || rx[1:0]!==0)
                $fatal(1,"BSCAN_LOADER_ORACLE legal address setup failed");
            idle(5);
        end
    endtask
    task stalled_memory(input integer cycles);
        integer k;
        begin
            for(k=0;k<cycles;k=k+1)begin
                @(negedge clk);
                if(!mqvalid || mqready || ma!=={32'b0,RAM_ADDRESS} || md!=={32'b0,expected_a} ||
                   !mwrite || msize!==2 || mbytes!==15 || memory_writes!=epoch_memory)
                    $fatal(1,"DRAIN_OWNER_ORACLE stalled request withdrawn/changed");
            end
        end
    endtask
    task late_write(input [31:0] value,input logic backpressure);
        integer old_admissions,k;
        reg [63:0] a,b;
        reg held_toggle;
        begin
            expected_a=value;epoch_dmi=dmi_writes;epoch_memory=memory_writes;
            endpoint_enable=1;response_enable=1;mqready=0;
            legal_address;
            endpoint_enable=!backpressure;response_enable=0;
            a=frame(2,7'h3c,value);b=frame(2,7'h3c,REPLACEMENT_B);
            old_admissions=admissions;
            command(a);held_toggle=dut.update_toggle;
            cycle;cycle;rise; // P3, with A due for consumption at F3.
            if(dut.update_seen===held_toggle || dut.fault_sample || dut.protocol_error)
                $fatal(1,"BSCAN_LOADER_ORACLE late-fault stimulus phase");
            raw_replace_shift(b);event_update;
            if(dut.update_frame!==a || dut.update_toggle!==held_toggle || !dut.update_overrun)
                $fatal(1,"BSCAN_LOADER_ORACLE late duplicate replaced ingress A");
            fall; // F3 must admit exactly A despite this unsampled late fault.
            if(admissions!=old_admissions+1 || dut.bridge.request_held!==a[40:0] ||
               !dut.source_busy || dut.result_done)
                $fatal(1,"BSCAN_LOADER_ORACLE exact F3 first admission");
            cycle; // P4/F4, including the independent sticky-fault merge.
            if(!dut.fault_sample || !dut.protocol_error)
                $fatal(1,"BSCAN_LOADER_ORACLE late fault missing by F4");
            if(backpressure)begin
                wait(req_valid);
                for(k=0;k<12;k=k+1)begin
                    @(negedge clk);
                    if(!req_valid || req_op!==2 || req_address!==7'h3c || req_data!==value ||
                       dmi_writes!=epoch_dmi || !dut.source_busy)
                        $fatal(1,"BSCAN_LOADER_ORACLE stalled endpoint request changed");
                end
                endpoint_enable=1;
            end
            wait(loader_rsp_valid);wait(mqvalid);stalled_memory(12);
            if(dmi_writes!=epoch_dmi+1 || !dut.source_busy || rsp_status!==0)
                $fatal(1,"BSCAN_LOADER_ORACLE delayed DMI reply or count");
            // Deliver the real loader DMI reply after the fault. The delayed
            // memory reply is separate: a successful SBA write command merely
            // starts bus work; it does not report memory completion.
            @(negedge clk);response_enable=1;idle(16);
            command(frame(0,0,0));
            if(!rx[43] || rx[42] || !rx[41] || rx[1:0]!==2)
                $fatal(1,"BSCAN_LOADER_ORACLE completed first DMI reply/error visibility");
            idle(5);command(b);idle(12);
            if(admissions!=old_admissions+1 || dmi_writes!=epoch_dmi+1 || memory_writes!=epoch_memory)
                $fatal(1,"BSCAN_LOADER_ORACLE subsequent valid command was not rejected");
            stalled_memory(4);
        end
    endtask
    task accept_memory;
        begin
            @(negedge clk);mqready=1;@(posedge clk);#1;@(negedge clk);mqready=0;
            if(memory_writes!=epoch_memory+1 || mqvalid || !mrready)
                $fatal(1,"DRAIN_OWNER_ORACLE first memory write acceptance count/owner");
        end
    endtask
    task drain(input logic error);
        begin
            repeat(19)@(negedge clk);
            if(!mrready)$fatal(1,"DRAIN_OWNER_ORACLE delayed response owner lost");
            mrerror=error;mrvalid=1;@(posedge clk);#1;@(negedge clk);mrvalid=0;mrerror=0;
            if(mrready || mqvalid || memory_writes!=epoch_memory+1)
                $fatal(1,"DRAIN_OWNER_ORACLE drain/replay count");
        end
    endtask
    task assert_hard_reset;
        begin
            command(frame(3,2,0));idle(3);
            if(!dut.hard_reset || link)$fatal(1,"BSCAN_LOADER_ORACLE hard reset assertion");
        end
    endtask

    initial begin
        #1;por_n=1;#1;por_n=0;
        repeat(4)@(negedge clk);system_reset=0;por_n=1;idle(10);
        open_session(0);
        late_write(32'h12345678,0);accept_memory;drain(0);cpu(0,0,0,0);
        if(status[3] || status[4] || !status[0])$fatal(1,"BSCAN_LOADER_ORACLE success status");
        $display("BSCAN_LOADER_CASE endpoint_ready first_A_once delayed_success subsequent_reject");

        fresh_transport;open_session(0);
        late_write(32'h89abcdef,1);accept_memory;drain(1);cpu(0,0,0,0);
        if(status[3] || !status[4] || status[0])$fatal(1,"BSCAN_LOADER_ORACLE delayed bus error status");
        $display("BSCAN_LOADER_CASE endpoint_backpressure held_request delayed_error first_A_once");

        fresh_transport;open_session(0);
        late_write(32'h31415926,1);assert_hard_reset;
        // TCK stays stopped high-reset while the production loader keeps its
        // offered owner. The bad-owner negative fails here, not by compilation.
        stalled_memory(12);open_session(1);
        cycle;idle(10);open_session(1);stalled_memory(4);
        accept_memory;drain(0);cpu(0,0,0,0);
        if(status[3] || status[0])$fatal(1,"DRAIN_OWNER_ORACLE offered-reset drain status");
        $display("BSCAN_LOADER_CASE hard_reset_before_memory_accept owner_retained_and_drained");

        open_session(0);owner_cycles=0;timeout_monitor=1;
        late_write(32'h27182818,0);accept_memory;
        tap_reset=1;repeat(12)@(negedge clk);
        if(!mrready || memory_writes!=epoch_memory+1)
            $fatal(1,"DRAIN_OWNER_ORACLE accepted owner lost across TAP reset");
        open_session(1);tap_reset=0;idle(10);open_session(1);
        // Actual 1,000,000-cycle owner timeout, including cycles elapsed before
        // reset. No parameter override, timer force, or modified RTL constant.
        wait(owner_cycles>=TIMEOUT_CYCLES+4);@(negedge clk);cpu(0,0,0,0);
        if(!status[3] || !status[4] || status[0] || timeout_edges!=1 || !mrready)
            $fatal(1,"TIMEOUT_LAW_ORACLE timeout did not retain BUSY/fault/owner");
        open_session(1);drain(0);timeout_monitor=0;open_session(0);
        idle(12);
        if(dmi_writes!=4 || memory_writes!=4 || memory_replies!=4)
            $fatal(1,"BSCAN_LOADER_ORACLE final exact transaction census");
        $display("BSCAN_LOADER_FAULT_PASS writes=%0d replies=%0d timeout_cycles=%0d sys_half=%0d tck_half=%0d late_P3_F3 first_A_once no_B endpoint_stall delayed_error hard_reset_offered tap_reset_accepted timeout_owner_drain",
            memory_writes,memory_replies,TIMEOUT_CYCLES,SYS_HALF,TCK_HALF);
        $finish;
    end
    initial begin #(1000000 + 4*SYS_HALF*TIMEOUT_CYCLES);$fatal(1,"BSCAN_LOADER_WATCHDOG");end
endmodule
