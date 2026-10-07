`timescale 1ns/1ps
// Independent startup oracle; DUT is extracted verbatim from the board top.
module native_calibration_reset_tb;
    reg aon=0, tx=0, rx=0, reset=0, soc_reset=0, ready=0;
    wire phy_reset, tx_reset, rx_reset;
    always #10 aon=~aon;
    always #4 tx=~tx;
    initial begin #1.3; forever #4 rx=~rx; end
    native_calibration_reset_fragment dut(
        .clk_aon(aon),.clk_tx(tx),.eth_rxc(rx),.board_reset(reset),
        .ui_reset(1'b0),.mmcm_locked(1'b1),.soc_reset(soc_reset),
        .delay_ready(ready),.eth_reset_gate(phy_reset),
        .tx_reset(tx_reset),.rx_reset(rx_reset));
    initial begin
        #1.7; reset=1; soc_reset=1;
        #201.1; reset=0; soc_reset=0;
        repeat(20) begin
            @(posedge aon); #0.1;
            if(!phy_reset || !tx_reset || !rx_reset || dut.phy_reset_pipe !== 3'b111)
                $fatal(1,"Calibration unavailable reset oracle");
        end
        @(negedge aon); #3.1; ready=1;
        for(integer edge_count=1;edge_count<=500003;edge_count=edge_count+1) begin
            @(posedge aon); #0.1;
            if(phy_reset !== (edge_count<500003))
                $fatal(1,"PHY 10ms qualified release oracle edge=%0d",edge_count);
            if(edge_count>=4 && (tx_reset || rx_reset))
                $fatal(1,"TX/RX synchronized release oracle");
        end
        #1.7; ready=0; #0.1;
        if(!phy_reset || !tx_reset || !rx_reset)
            $fatal(1,"RDY loss async assertion oracle");
        repeat(20) begin
            @(posedge aon); #0.1;
            if(!phy_reset || !tx_reset || !rx_reset)
                $fatal(1,"RDY loss persistent reset oracle");
        end
        @(negedge aon); #3.1; ready=1;
        repeat(50) @(posedge aon);
        #0.1;
        if(!phy_reset || tx_reset || rx_reset)
            $fatal(1,"Recalibration must restart full PHY hold oracle");
        #1.7; soc_reset=1; #0.1;
        if(!tx_reset || !rx_reset) $fatal(1,"Common CPU reset assertion oracle");
        $display("PASS_NATIVE_CALIBRATION_RESET phy_hold_edges=500000 release_stages=3 rdy_loss=1");
        $finish;
    end
    initial begin #11000000; $fatal(1,"Calibration reset timeout"); end
endmodule
