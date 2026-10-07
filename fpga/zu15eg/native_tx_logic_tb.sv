`timescale 1ns/1ps
// Standalone closed-form oracle: all 256 bytes x four DV/ER encodings,
// streaming every 8ns and asynchronous reset/restart. No CPU or MAC model.
module native_tx_logic_tb;
    reg ui_clock=0, cold_reset=1;
    always #2 ui_clock=~ui_clock;
    wire tx_source, delay_source, locked, raw_clock, pad_clock, delay_clock;
    native_eth_clock clock_dut(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(tx_source), .delay_source(delay_source), .locked(locked));
    BUFG raw_buffer(.I(tx_source), .O(raw_clock));
    BUFG pad_buffer(.I(tx_source), .O(pad_clock));
    BUFG delay_buffer(.I(delay_source), .O(delay_clock));
    reg tx_reset=1, delay_reset=1;
    reg [7:0] data=0;
    reg enable=0, error=0;
    wire [3:0] txd;
    wire txctl, txc, ready;
    native_rgmii #(.ISOLATE_TX_PAD_CLOCK(1)) dut(
        .tx_clock(raw_clock), .tx_pad_clock(pad_clock), .tx_reset(tx_reset),
        .rx_clock(raw_clock), .rx_reset(1'b1), .delay_clock(delay_clock),
        .delay_reset(delay_reset), .delay_ready(ready),
        .gmii_tx_data(data), .gmii_tx_enable(enable), .gmii_tx_error(error),
        .rgmii_rx_data(4'b0), .rgmii_rx_control(1'b0),
        .rgmii_tx_data(txd), .rgmii_tx_control(txctl), .rgmii_tx_clock(txc),
        .gmii_rx_data(), .gmii_rx_valid(), .gmii_rx_error(), .gigabit_link());
    function automatic [7:0] payload(input integer index);
        payload=8'h53 ^ index[7:0];
    endfunction
    integer checked=0;
    reg [7:0] expected;
    real last_edge=0;
    always @(posedge raw_clock) if(locked) begin
        if(last_edge!=0 && ($realtime-last_edge<7.999 || $realtime-last_edge>8.001))
            $fatal(1,"TX period oracle");
        if(pad_clock!==1'b1) #0.01;
        if(pad_clock!==1'b1) $fatal(1,"Raw/pad phase mismatch");
        last_edge=$realtime;
    end else last_edge=0;
    initial begin
        #121; cold_reset=0;
        wait(locked); repeat(80) @(posedge delay_clock);
        @(negedge delay_clock); delay_reset=0;
        wait(ready);
        for(integer epoch=0;epoch<3;epoch=epoch+1) begin
            @(negedge raw_clock); tx_reset=0;
            repeat(8) @(negedge raw_clock); #0.4;
            for(integer i=0;i<=1024;i=i+1) begin
                #0.6;
                data=payload(i); enable=(i<1024) && ((i>>9)&1);
                error=(i<1024) && ((i>>8)&1);
                if($test$plusargs("corrupt_data") && i==300) data=data^8'h01;
                if($test$plusargs("corrupt_control") && i==800) error=~error;
                @(posedge raw_clock); #0.4;
                if(txc!==1'b1) $fatal(1,"Forwarded rising clock");
                if(i>0) begin
                    expected=payload(i-1);
                    if(txd!==expected[3:0] || txctl!==(((i-1)>>9)&1))
                        $fatal(1,"Rising symbol oracle epoch=%0d i=%0d",epoch,i-1);
                end
                @(negedge raw_clock); #0.4;
                if(txc!==1'b0) $fatal(1,"Forwarded falling clock");
                if(i>0) begin
                    if(txd!==expected[7:4] || txctl!==((((i-1)>>9)^((i-1)>>8))&1))
                        $fatal(1,"Falling symbol oracle epoch=%0d i=%0d",epoch,i-1);
                    checked=checked+1;
                end
            end
            #1.17; tx_reset=1; data=0; enable=0; error=0;
            #1;
            if(txd!==0 || txctl!==0 || txc!==0) $fatal(1,"Async pad reset");
            repeat(8) @(negedge raw_clock);
        end
        if(checked!=3072) $fatal(1,"Missing oracle cases %0d",checked);
        $display("PASS_NATIVE_TX_LOGIC_SHORT bytes=3072 encodings=4 reset_epochs=3 period_ns=8");
        $finish;
    end
    initial begin #100000; $fatal(1,"TX logic timeout"); end
endmodule
