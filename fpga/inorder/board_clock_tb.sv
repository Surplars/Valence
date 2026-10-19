// Short CDC/physical-boundary check with the ACTUAL generated clock IP.
// No CPU/Linux/DDR behavioral simulation or analog/route timing claim.
module i1_board_clock_tb;
    timeunit 1ns;
    timeprecision 1ps;
    reg ui_clock = 0;
    always #2 ui_clock = ~ui_clock;
    reg reset = 1, inhibit = 1;
    wire cpu, aon_raw, tx_raw, pad, ref500, locked, word, encoder;
    clk_wiz_i1 clocks(.clk_in1(ui_clock), .reset(reset), .locked(locked),
        .clk_out1(cpu), .clk_out2(aon_raw), .clk_out3(tx_raw),
        .clk_out4(pad), .clk_out5(ref500));
    BUFG word_buffer(.I(tx_raw), .O(word));
    BUFGCE #(.CE_TYPE("SYNC")) encoder_buffer(.I(tx_raw), .CE(1'b1), .O(encoder));
    wire reset_raw, reset_pad;
    native_tx_word_reset_boundary release_word(.clock_tx(word), .inhibit(inhibit),
        .reset_raw(reset_raw), .reset_forward(reset_pad));
    reg [4:0] rise = 0, fall = 0;
    reg clock_rise = 0, clock_fall = 0;
    wire [3:0] txd;
    wire ctl, txc, ready;
    native_rgmii_trispeed_quarter #(.RX_DATA_DELAY_PS(0)) boundary(
        .tx_clock(word), .tx_pad_clock(pad), .tx_pad_reset(reset_pad),
        .rx_clock(word), .tx_reset(reset_raw), .rx_reset(reset_pad),
        .delay_clock(ref500), .delay_reset(reset | !locked),
        .tx_rise(rise), .tx_fall(fall), .txc_rise(clock_rise), .txc_fall(clock_fall),
        .rgmii_rx_data(4'b0), .rgmii_rx_control(1'b0), .rx_rise(), .rx_fall(),
        .rgmii_tx_data(txd), .rgmii_tx_control(ctl), .rgmii_tx_clock(txc),
        .delay_ready(ready));
    realtime previous[5];
    integer edges[5];
    function automatic real magnitude(input real v);
        magnitude = v < 0 ? -v : v;
    endfunction
    task automatic check_period(input integer index, input real expected);
        if (locked) begin
            if (edges[index] > 4 && magnitude(($realtime - previous[index]) - expected) > 0.025)
                $fatal(1, "Actual generated clock period mismatch index=%0d", index);
            previous[index] = $realtime;
            edges[index] = edges[index] + 1;
        end
    endtask
    always @(posedge cpu) check_period(0, 10.0/3.0);
    always @(posedge aon_raw) check_period(1, 20.0);
    always @(posedge encoder) check_period(2, 8.0);
    always @(posedge pad) check_period(3, 4.0);
    always @(posedge ref500) check_period(4, 2.0);
    integer n;
    reg previous_fall = 0;
    initial begin
        for (n=0; n<5; n=n+1) begin previous[n]=0; edges[n]=0; end
        #500 reset=0;
        wait(locked === 1'b1);
        repeat(8) @(posedge encoder);
        #0.25 inhibit=0;
        wait(reset_pad === 1'b0);
        for(n=0; n<12; n=n+1) begin
            @(posedge encoder);
            #0.01;
            rise=(n ^ 5'h15); fall=(n ^ 5'h0a);
            clock_rise=(n & 1); clock_fall=((n >> 1) & 1);
            #8.5;
            if ({ctl,txd} !== rise || txc !== previous_fall)
                $fatal(1,"Word low half / no early TXC mismatch case=%0d",n);
            #2;
            if(txc !== clock_rise) $fatal(1,"TXC must apply low half at data+2ns case=%0d",n);
            #2;
            if({ctl,txd} !== fall || txc !== clock_rise)
                $fatal(1,"Word high half / held TXC mismatch case=%0d",n);
            #2;
            if(txc !== clock_fall) $fatal(1,"TXC must apply high half at data+2ns case=%0d",n);
            previous_fall=clock_fall;
        end
        for(n=0;n<5;n=n+1) if(edges[n]<8) $fatal(1,"Missing real output clock");
        inhibit=1;
        #1;
        if(reset_raw !== 1'b1 || reset_pad !== 1'b1)
            $fatal(1,"Asynchronous common word/pad reset assertion failed");
        $display("I1_REAL_CLOCK_BOUNDARY_PASS clocks=300_50_125_250_500 all_clock_pairs=4 cases=12 common_word_reset=1 fixed_TX_skew_ns=2");
        $finish;
    end
    initial begin #100000; $fatal(1,"Actual clock/reset boundary timeout"); end
endmodule
