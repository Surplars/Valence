`timescale 1ns/1ps
// Independent pin-level Clause22 PHY oracle. Real 300ns data delay, explicit
// turnaround/high-Z, address search, read-modify-write preservation and faults.
module native_phy_tx_init_tb;
    reg clock=0, reset=1, software_mdc=0, software_oe=0;
    always #10 clock=~clock;
    wire mdc, mdio_out, mdio_oe, released, ready;
    wire [4:0] address;
    wire [3:0] fault;
    tri1 mdio;
    reg phy_drive=0, phy_bit=1;
    assign mdio=mdio_oe ? mdio_out : 1'bz;
    assign mdio=phy_drive ? phy_bit : 1'bz;
    native_phy_tx_init #(.WAIT_CYCLES(20)) dut(
        .clock(clock), .cold_reset(reset), .mdio_pad(mdio),
        .software_mdc(software_mdc), .software_oe(software_oe),
        .mdc(mdc), .mdio_out(mdio_out), .mdio_oe(mdio_oe),
        .bus_released(released), .ready(ready), .phy_address(address), .fault(fault));
    integer selected=3, position=0, frames=0, epoch=0, expected_fault=0;
    reg [63:0] bits;
    reg [15:0] page=0, tx=16'ha5ff, rx=16'h5a50, reply;
    reg is_read, addressed, inject=1;
    integer regno;
    real rise_time=0, fall_time=0;
    initial begin
        if($test$plusargs("phy0")) selected=0;
        if($test$plusargs("phy31")) selected=31;
        if($test$plusargs("no_phy") || $test$plusargs("wrong_id")) expected_fault=1;
        if($test$plusargs("no_ack")) expected_fault=2;
        if($test$plusargs("tx_stuck")) expected_fault=3;
        if($test$plusargs("rx_stuck")) expected_fault=4;
        if($test$plusargs("restore_stuck")) expected_fault=5;
        if($test$plusargs("page_stuck")) expected_fault=7;
    end
    always @(posedge mdc) begin
        if(fall_time && $realtime-fall_time<399.9) $fatal(1,"MDC low width");
        rise_time=$realtime;
        bits[63-position]=mdio;
        if(position==45) begin
            if(bits[63:32]!==32'hffffffff || bits[31:30]!==2'b01)
                $fatal(1,"Preamble/start independent oracle");
            if(bits[29:28]!==2'b10 && bits[29:28]!==2'b01) $fatal(1,"Opcode");
            is_read=(bits[29:28]==2'b10);
            addressed=(bits[27:23]==selected) && !(inject && $test$plusargs("no_phy"));
            regno=bits[22:18];
            reply=16'hffff;
            if(addressed) case(regno)
                2: reply=16'h001c;
                3: reply=(inject && $test$plusargs("wrong_id")) ? 16'hc820 : 16'hc916;
                31: reply=page;
                17: if(page==16'h0d08) reply=tx;
                21: if(page==16'h0d08) reply=rx;
                default: reply=0;
            endcase
            if(inject && $test$plusargs("no_ack") && page==16'h0d08 && regno==17)
                addressed=0;
        end
        if(position==63) begin
            if(!is_read) begin
                if(bits[17:16]!==2'b10) $fatal(1,"Write turnaround");
                if(addressed) case(regno)
                    31: if(!(inject && (($test$plusargs("page_stuck") && bits[15:0]==16'h0d08) ||
                                          ($test$plusargs("restore_stuck") && bits[15:0]==0)))) page=bits[15:0];
                    17: if(page==16'h0d08 && !(inject && $test$plusargs("tx_stuck"))) tx=bits[15:0];
                    21: if(page==16'h0d08 && !(inject && $test$plusargs("rx_stuck"))) rx=bits[15:0];
                endcase
            end
            frames=frames+1; position=0;
        end else position=position+1;
    end
    always @(negedge mdc) begin
        if(!reset && rise_time && $realtime-rise_time<399.9) $fatal(1,"MDC high width");
        fall_time=$realtime;
        if(position>=47 && is_read && addressed) begin
            #300;
            phy_drive=1;
            phy_bit=(position==47) ? 1'b0 : reply[63-position];
        end else begin #300; phy_drive=0; phy_bit=1; end
    end
    always @(posedge reset) begin
        position=0; bits=0; is_read=0; addressed=0; phy_drive=0;
        page=0; tx=16'ha5ff; rx=16'h5a50; rise_time=0; fall_time=0;
    end
    always @(posedge clock) begin
        #1;
        if(mdio_oe && phy_drive) $fatal(1,"MDIO bus contention");
        if(ready && !released) $fatal(1,"Ready before handoff");
        if(released && (software_mdc || software_oe)) begin
            // This test deliberately keeps the software port idle after handoff.
            $fatal(1,"Handoff while software transaction active");
        end
    end
    initial begin
        #121; reset=0;
        // CPU may access MDIO early: ownership cannot change during its transfer.
        software_oe=1;
        fork
            begin wait(dut.state==3); repeat(40) begin #200; software_mdc=~software_mdc; end
                  software_mdc=0; software_oe=0; end
            begin wait(released); end
        join
        if(fault!=expected_fault || ready!==(expected_fault==0))
            $fatal(1,"First configuration oracle fault=%0d expected=%0d ready=%0d",fault,expected_fault,ready);
        if(expected_fault==0 && (address!=selected || page!=0 || tx!=16'ha4ff || rx!=16'h5a58))
            $fatal(1,"Register preservation/restore independent oracle");
        #1.17; reset=1; #41;
        if(ready || released) $fatal(1,"Cold reset did not revoke readiness/ownership");
        inject=0; epoch=1;
        #139; reset=0;
        wait(released);
        if(!ready || fault || address!=selected || page!=0 || tx!=16'ha4ff || rx!=16'h5a58)
            $fatal(1,"Retry after reset must configure and verify");
        $display("PASS_NATIVE_PHY_TX_INIT phy=%0d initial_fault=%0d reset_retry=1 frames=%0d",selected,expected_fault,frames);
        $finish;
    end
    initial begin #10000000; $fatal(1,"PHY init timeout"); end
endmodule
