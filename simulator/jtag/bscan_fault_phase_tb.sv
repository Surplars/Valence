`timescale 1ns/1ps
// Explicit pin-event regression of the production transport + CDC. This is not
// a TAP/vendor model and does not prove AMD primitive phase or physical timing.
module bscan_fault_phase_tb;
    reg tck=0, drck=0, capture=0, shift=0, update=0, sel=1, reset=0, tdi=0;
    reg clk=0, por_n=0, ready=1, endpoint=1, rsp_valid=0;
    wire tdo, link, req_valid, rsp_ready;
    wire [1:0] op;
    wire [6:0] address;
    wire [31:0] data;
    reg [31:0] rsp_data=0;
    integer accepted=0, admitted=0, n, before_count, before_admitted, release_cases=0, turnover_cases=0;
    integer polarity, slot, sweeps=0;
    reg [40:0] last_admitted, last_accepted;
    always @(negedge tck) if (dut.accept_dmi) begin
        admitted=admitted+1; last_admitted=dut.handoff_frame[40:0];
    end
    reg pending=0;
    reg [63:0] rx, held, a, b;
    reg old_toggle;
    always #7 clk=~clk;
    ValenceBscanUserTransport dut(
        .bscan_tck(tck),.bscan_drck(drck),.bscan_capture(capture),.bscan_shift(shift),
        .bscan_update(update),.bscan_sel(sel),.bscan_reset(reset),.bscan_tdi(tdi),.bscan_tdo(tdo),
        .debug_clk(clk),.debug_por_n(por_n),.dmi_reset_n(link),
        .dmi_req_valid(req_valid),.dmi_req_ready(ready),.dmi_req_op(op),
        .dmi_req_address(address),.dmi_req_data(data),.dmi_rsp_valid(rsp_valid),
        .dmi_rsp_ready(rsp_ready),.dmi_rsp_status(2'b00),.dmi_rsp_data(rsp_data));
    always @(posedge clk or negedge link) begin
        if(!link)begin pending<=0;rsp_valid<=0;rsp_data<=0;end
        else begin
            if(req_valid && ready)begin
                if(pending || rsp_valid)$fatal(1,"QUAL endpoint overlap");
                accepted=accepted+1;last_accepted={address,data,op};pending<=1;rsp_data<=32'ha5000000 | address;
            end
            if(pending && endpoint)begin pending<=0;rsp_valid<=1;end
            if(rsp_valid && rsp_ready)rsp_valid<=0;
        end
    end
    function [63:0] frame(input [1:0] cmd,input [6:0] addr,input [31:0] value);
        frame={16'h5642,4'h1,3'b0,addr,value,cmd};
    endfunction
    task rise;
        begin #24;tck=1;#1;end
    endtask
    task fall;
        begin #24;tck=0;#1;end
    endtask
    task cycle;
        begin rise;fall;end
    endtask
    task idle(input integer count);
        integer k;begin for(k=0;k<count;k=k+1)cycle;end
    endtask
    task event_update;
        begin update=1;#1;update=0;#1;end
    endtask
    task capture_cycle(output reg [63:0] value);
        begin capture=1;rise;drck=1;#1;value=dut.shift_frame;drck=0;capture=0;fall;end
    endtask
    task load(input [63:0] value,input integer bits);
        integer k;reg [63:0] unused;
        begin
            capture_cycle(unused);
            for(k=0;k<bits;k=k+1)begin
                shift=1;tdi=value[k%64];rise;drck=1;#1;drck=0;shift=0;fall;
            end
        end
    endtask
    task command(input [63:0] value,input integer bits);
        begin load(value,bits);cycle;cycle;event_update;end
    endtask
    task cold_reset;
        begin
            por_n=0;#2;
            if(dut.update_release!==0 || dut.update_selected!==0 || dut.update_ack!==0 ||
               dut.update_toggle!==0 || dut.update_overrun!==0 || dut.fault_sample!==0 || dut.handoff_toggle!==0 ||
               dut.handoff_frame!==0 || dut.handoff_length_ok!==0 || dut.hard_release!==0 ||
               dut.hard_reset!==0 || dut.shift_frame!==0 || dut.scan_captured!==0 ||
               req_valid || rsp_ready || link)
                $fatal(1,"QUAL asynchronous reset isolation");
            por_n=1;#2;
            if(dut.update_reset_n!==0)$fatal(1,"QUAL release without TCK");
        end
    endtask
    task start_clean;
        begin cold_reset;idle(8);end
    endtask
    initial begin
        // Force an actual assertion event even on simulators that initialize
        // declaration-assigned zero registers before registering always blocks.
        #1;por_n=1;#1;por_n=0;#1;por_n=1;
        // Observe EVERY adjacent release edge, not a long warm-up hiding bugs.
        for(n=1;n<=4;n=n+1)begin
            rise;
            if(n<3 && dut.update_reset_n!==0)$fatal(1,"QUAL positive fence early");
            if(n==3 && (dut.update_reset_n!==1 || dut.source_reset_n!==0 || dut.update_selected!==0))
                $fatal(1,"QUAL third positive edge must release fence only");
            if(n==4 && (dut.source_reset_n!==1 || dut.update_selected!==1))
                $fatal(1,"QUAL fourth positive edge must sample selected/released");
            fall;
            if(n==3 && (dut.source_reset_n!==1 || dut.update_selected!==0))
                $fatal(1,"QUAL third negative edge must not bypass qualifier");
            if(n<4)begin
                event_update;
                if(dut.update_toggle!==0)$fatal(1,"QUAL UPDATE accepted before qualification");
            end
            release_cases=release_cases+1;
        end
        // Earliest qualified capture begins immediately at the next DRCK edge;
        // a full 64-bit command needs no artificial release wait after this.
        a=frame(1,7'h25,0);before_count=accepted;
        command(a,64);
        if(dut.update_frame!==a || !dut.update_length_ok || dut.update_overrun)
            $fatal(1,"QUAL first legal 64-bit command");
        capture_cycle(rx);
        if(!rx[42] || rx[41])$fatal(1,"QUAL immediate capture must show pending not stale DONE");
        idle(12);
        if(accepted!=before_count+1)$fatal(1,"QUAL first command exactly once");

        // A held command never bypasses the negative-TCK consumer while stopped.
        start_clean;before_count=accepted;command(frame(1,7'h11,0),64);#500;
        if(accepted!=before_count)$fatal(1,"QUAL stopped TCK bypass");
        idle(12);if(accepted!=before_count+1)$fatal(1,"QUAL stopped TCK recovery");

        // Capacity-one failure must preserve the original frame even if raw
        // DRCK changes the shift register between malformed UPDATE events.
        start_clean;a=frame(2,7'h12,32'h12345678);b=frame(2,7'h34,32'h87654321);
        load(a,64);cycle;cycle;event_update;held=dut.update_frame;old_toggle=dut.update_toggle;
        if(held!==a)$fatal(1,"QUAL first malformed-sequence frame missing");
        capture=1;drck=1;#1;drck=0;capture=0; // no TCK: definitely changes shift_frame
        if(dut.shift_frame===held)$fatal(1,"QUAL duplicate test did not change payload");
        event_update;
        if(dut.update_frame!==held || dut.update_toggle!==old_toggle || !dut.update_overrun)
            $fatal(1,"QUAL duplicate UPDATE overwrote held frame");
        before_count=accepted;idle(12);
        if(accepted!=before_count)$fatal(1,"QUAL overrun did not fail closed");

        // Observe the new handoff at its actual edges, including a stopped
        // positive phase. No old or partially copied frame can enter the bridge.
        start_clean;a=frame(2,7'h12,32'h12345678);before_count=accepted;
        command(a,64);
        if(dut.handoff_toggle!==0 || dut.handoff_frame!==0)
            $fatal(1,"QUAL handoff advanced without positive TCK");
        rise;
        if(dut.handoff_frame!==a || !dut.handoff_length_ok || dut.handoff_toggle!==1 ||
           dut.update_sync!==0 || dut.update_seen!==0)
            $fatal(1,"QUAL positive handoff bundle");
        #200;
        if(accepted!=before_count || dut.update_seen!==0)
            $fatal(1,"QUAL stopped positive handoff bypass");
        fall;
        if(dut.update_sync!==2'b01 || dut.update_seen!==0)
            $fatal(1,"QUAL first negative handoff notification");
        cycle;
        if(dut.update_sync!==2'b11 || dut.update_seen!==0)
            $fatal(1,"QUAL second negative handoff notification");
        // Versioned phase contract: preserve the original P3-F3 stimulus.
        // A is admitted exactly once at F3; the late fault is sticky at F4.
        // The preserved prephase bench still rejects this as its old contract.
        rise;held=dut.update_frame;old_toggle=dut.update_toggle;
        capture=1;drck=1;#1;drck=0;capture=0;
        event_update;
        if(dut.update_frame!==held || dut.update_toggle!==old_toggle || !dut.update_overrun)
            $fatal(1,"QUAL late duplicate held frame");
        before_admitted=admitted;
        if(dut.fault_sample || dut.protocol_error)$fatal(1,"PHASE late fault observed early");
        fall;
        if(admitted!=before_admitted+1 || last_admitted!==a[40:0] || dut.protocol_error)
            $fatal(1,"PHASE late A admission exact F3");
        rise;
        if(!dut.fault_sample || dut.protocol_error)$fatal(1,"PHASE fault sample exact P4");
        fall;
        if(!dut.protocol_error)$fatal(1,"PHASE independent sticky F4 without UPDATE");
        idle(12);
        if(accepted!=before_count+1 || last_accepted!==a[40:0])
            $fatal(1,"PHASE late A endpoint once");
        command(b,64);idle(12);
        if(accepted!=before_count+1)$fatal(1,"PHASE subsequent command admitted");
        command(frame(3,1,0),64);idle(3);
        if(!dut.protocol_error)$fatal(1,"PHASE CLEAR defeated fault");
        idle(4);
        if(!dut.protocol_error || !dut.fault_sample || !dut.update_overrun)
            $fatal(1,"PHASE stale fault cleared without reset");

        // Sweep every pre/post-positive sample window through consumption,
        // with both token polarities. Raw DRCK shifts B without TCK; first A
        // and its token must survive every illegal duplicate in this epoch.
        for(polarity=0;polarity<2;polarity=polarity+1)begin
            for(slot=0;slot<5;slot=slot+1)begin
                start_clean;
                if(polarity==1)begin command(frame(0,0,0),64);idle(8);end
                a=frame(2,7'h16,32'habc00000+slot);b=frame(2,7'h36,32'hbad00000+slot);
                before_count=accepted;before_admitted=admitted;command(a,64);
                held=dut.update_frame;old_toggle=dut.update_toggle;
                if(slot>=1)rise; // after P1
                if(slot>=2)begin fall;rise;end // after P2
                if(slot>=3)begin fall;rise;end // after P3
                if(slot>=4)fall; // after F3 but before returned ACK at P4
                shift=1;
                for(n=0;n<64;n=n+1)begin tdi=b[n];#1;drck=1;#1;drck=0;end
                shift=0;
                event_update;event_update;
                if(dut.update_frame!==held || dut.update_toggle!==old_toggle || !dut.update_overrun)
                    $fatal(1,"PHASE duplicate integrity both polarities");
                #200;
                if(slot<3 && admitted!=before_admitted)$fatal(1,"PHASE stopped fault bypass");
                if(tck)fall;
                // For slots >=3, A has already been admitted at F3.
                rise;
                if(!dut.fault_sample)$fatal(1,"PHASE sample never observed fault");
                fall;
                if(!dut.protocol_error)$fatal(1,"PHASE independent sticky without new UPDATE");
                idle(12);
                if(admitted!=before_admitted+(slot>=3) || accepted!=before_count+(slot>=3))
                    $fatal(1,"PHASE exact swept admission count");
                if(slot>=3 && (last_admitted!==a[40:0] || last_accepted!==a[40:0]))
                    $fatal(1,"PHASE replacement B admitted");
                sweeps=sweeps+1;
            end
        end
        // Seed old DONE. Immediate BUSY remains visible across pending->mailbox
        // ownership, while a legally admitted/backpressured A keeps its owner.
        start_clean;command(frame(3,0,0),64);idle(8);
        if(!dut.result_done)$fatal(1,"PHASE old DONE precondition");
        a=frame(2,7'h22,32'h77112233);ready=0;before_count=accepted;
        command(a,64);
        capture_cycle(rx);
        if(!rx[42] || !rx[41])$fatal(1,"PHASE pending old DONE must be BUSY");
        cycle;rise;event_update;fall;
        if(!dut.source_busy || dut.result_done)$fatal(1,"PHASE F3 BUSY handover");
        capture_cycle(rx);
        if(!rx[42] || rx[41] || !dut.protocol_error)$fatal(1,"PHASE fault BUSY capture");
        idle(8);
        if(!req_valid || address!==7'h22 || data!==32'h77112233 || op!==2)
            $fatal(1,"PHASE fault canceled held request");
        ready=1;idle(12);
        if(accepted!=before_count+1 || !dut.result_done || !dut.protocol_error)
            $fatal(1,"PHASE accepted owner response lost");
        // Capability at the first sampled-fault edge cannot replace result data.
        start_clean;command(frame(3,0,0),64);cycle;cycle;
        event_update;rise;fall;
        if(!dut.protocol_error || dut.result_done || dut.result_data!==0)
            $fatal(1,"PHASE sampled fault admitted capability");
        // Hard reset recovers a faulted epoch; all fault bits clear together.
        command(frame(3,2,0),64);idle(3);
        if(!dut.hard_reset || dut.fault_sample || dut.update_overrun || dut.protocol_error)
            $fatal(1,"PHASE hard reset fault epoch");
        idle(9);before_count=accepted;command(frame(1,7'h23,0),64);idle(12);
        if(accepted!=before_count+1 || dut.protocol_error || dut.fault_sample)
            $fatal(1,"PHASE hard reset recovery stale fault");

        // Four TCK cycles is the shortest legal UPDATE-to-UPDATE (SelectDR,
        // CaptureDR, Exit1DR, UpdateDR). The returned ACK must be sampled on
        // the fourth rising edge. Empty scans set length error, never overrun.
        start_clean;command(frame(0,0,0),64);
        for(n=0;n<16;n=n+1)begin
            old_toggle=dut.update_toggle;
            cycle;capture_cycle(rx);cycle;
            if(dut.update_seen!==old_toggle)$fatal(1,"QUAL third falling edge missed ACK");
            rise;
            if(dut.update_ack!==old_toggle)$fatal(1,"QUAL fourth rising edge missed sampled ACK");
            fall;event_update;
            if(dut.update_toggle===old_toggle || dut.update_overrun || dut.update_length_ok)
                $fatal(1,"QUAL shortest empty-scan turnover");
            turnover_cases=turnover_cases+1;
        end

        // SEL changes only enter the UPDATE guard on positive TCK. These two
        // deliberate invalid pin sequences expose any residual live SEL guard.
        start_clean;load(a,64);rise;sel=0;fall;event_update;
        if(dut.update_frame!==a || dut.update_toggle!==1)$fatal(1,"QUAL raw SEL bypassed registered selection");
        start_clean;sel=0;load(b,64);rise;sel=1;fall;event_update;
        if(dut.update_toggle!==0)$fatal(1,"QUAL raw SEL granted unsampled selection");
        cycle; // normal IR-to-DR sequencing provides positive sampling before a scan
        command(a,64);idle(12);
        if(dut.update_overrun)$fatal(1,"QUAL selected restart overrun");

        // Reset an UPDATE-pending frame with TCK stopped at both levels. Release
        // while stopped cannot resurrect it, and early UPDATE pulses are ignored.
        for(n=0;n<2;n=n+1)begin
            start_clean;command(a,64);before_count=accepted;
            if(n==1)rise;
            cold_reset;event_update;#100;
            if(dut.update_toggle!==0 || dut.update_selected!==0 || accepted!=before_count)
                $fatal(1,"QUAL stopped-clock reset replay");
            if(tck)fall;
            idle(8);command(frame(0,0,0),64);idle(8);
            if(accepted!=before_count)$fatal(1,"QUAL pending frame replay after reset");
        end
        // Hard reset itself uses the original consumer and asynchronously resets
        // the new release fence. No endpoint/bus ownership implementation changes.
        start_clean;command(frame(3,2,0),64);idle(3);
        if(!dut.hard_reset || dut.update_reset_n!==0 || dut.update_toggle!==0)
            $fatal(1,"QUAL hard reset assertion");
        #200;if(dut.update_reset_n!==0 || !dut.hard_reset || !dut.hard_reset_n)
            $fatal(1,"QUAL stopped hard reset release");
        rise;
        if(!dut.hard_reset || !dut.hard_reset_n || dut.source_reset_n || dut.update_reset_n)
            $fatal(1,"QUAL independent hard reset full pulse");
        fall;
        if(dut.hard_reset || dut.source_reset_n || dut.update_reset_n)
            $fatal(1,"QUAL hard reset pulse completion");
        idle(8);before_count=accepted;command(frame(0,0,0),64);idle(8);
        if(accepted!=before_count || dut.update_overrun)$fatal(1,"QUAL hard reset replay");
        $display("PASS BSCAN_FAULT_PHASE release_edges=%0d shortest_turnover=%0d swept_fault_windows=%0d duplicate_no_tck positive_handoff late_A_once independent_sticky CLEAR_sticky immediate_capture selection reset_low_high hard_reset",release_cases,turnover_cases,sweeps);
        $finish;
    end
    initial begin #1000000;$fatal(1,"QUAL watchdog");end
endmodule
