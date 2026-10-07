`timescale 1ns/1ps
// Only the physical DDR clock boundary, no CPU, MAC engines or whole-board sim.
module native_rgmii_tb;
    reg tx_clock=0, rx_clock=0, tx_reset=1, rx_reset=1;
    reg delay_clock=0, delay_reset=1;
    always #1 delay_clock=~delay_clock;
    wire delay_ready;
    always #4 tx_clock=~tx_clock;
    initial begin #1.3; forever #4 rx_clock=~rx_clock; end
    reg [7:0] tx_data=0;
    reg tx_enable=0, tx_error=0;
    reg [3:0] rxd=4'hd;
    reg rx_ctl=0;
    wire [3:0] txd;
    wire tx_ctl, txc, rx_valid, rx_error, link_up;
    wire [7:0] rx_data;
    native_rgmii dut (.tx_clock(tx_clock),.tx_pad_clock(tx_clock),.rx_clock(rx_clock),.tx_reset(tx_reset),.rx_reset(rx_reset),
        .delay_clock(delay_clock),.delay_reset(delay_reset),.delay_ready(delay_ready),
        .gmii_tx_data(tx_data),.gmii_tx_enable(tx_enable),.gmii_tx_error(tx_error),
        .rgmii_rx_data(rxd),.rgmii_rx_control(rx_ctl),.rgmii_tx_data(txd),
        .rgmii_tx_control(tx_ctl),.rgmii_tx_clock(txc),.gmii_rx_data(rx_data),
        .gmii_rx_valid(rx_valid),.gmii_rx_error(rx_error),.gigabit_link(link_up));
    integer tx_seen=0, rx_seen=0;
    reg monitor_enable=0;
    reg [3:0] low;
    reg rising_ctl;
    always @(posedge tx_clock) begin
        #0.4;
        if (!tx_reset && monitor_enable) begin
            if (txc !== 1'b1) $fatal(1,"TX clock rising polarity");
            low=txd; rising_ctl=tx_ctl;
        end
    end
    always @(negedge tx_clock) begin
        #0.4;
        if (!tx_reset && monitor_enable) begin
            if (txc !== 1'b0) $fatal(1,"TX clock falling polarity");
            if (rising_ctl) begin
                if ({txd,low} !== (8'h31+tx_seen)) $fatal(1,"TX ordered byte %d got %x%x",tx_seen,txd,low);
                if ((rising_ctl ^ tx_ctl) !== (tx_seen==7)) $fatal(1,"TX ER encoding");
                tx_seen=tx_seen+1;
            end
        end
    end
    always @(posedge rx_clock) begin
        #0.6;
        if (!rx_reset && rx_valid) begin
            if (rx_data !== (8'h71+rx_seen)) $fatal(1,"RX ordered byte %d got %x",rx_seen,rx_data);
            if (rx_error !== (rx_seen==5)) $fatal(1,"RX ER decoding");
            rx_seen=rx_seen+1;
        end
    end
    task automatic rx_byte(input [7:0] value,input valid,input error);
        @(negedge rx_clock); #2; rxd=value[3:0]; rx_ctl=valid;
        @(posedge rx_clock); #2; rxd=value[7:4]; rx_ctl=valid ^ error;
    endtask
    initial begin
        #139; // UNISIM glbl GSR remains asserted for the first 100ns.
        if(delay_ready) $fatal(1,"Calibration ready during reset");
        @(negedge delay_clock); delay_reset=0;
        wait(delay_ready);
        @(negedge tx_clock); tx_reset=0;
        @(negedge rx_clock); rx_reset=0;
        repeat(12) rx_byte(8'hdd,0,0);
        if (!link_up) $fatal(1,"In-band 1G/full duplex link not captured");
        monitor_enable=1; // ODDRE1 SR release itself has a four-clock guard.
        fork
            begin
                for(integer i=0;i<16;i=i+1) begin
                    @(negedge tx_clock); #1; tx_data=8'h31+i;
                    if($test$plusargs("corrupt_tx") && i==3) tx_data=tx_data ^ 8'h10;
                    tx_enable=1; tx_error=(i==7);
                end
                @(negedge tx_clock); #1; tx_enable=0; tx_error=0;
            end
            begin
                for(integer i=0;i<16;i=i+1)
                    rx_byte((8'h71+i) ^ (($test$plusargs("corrupt_rx") && i==3) ? 8'h01 : 0),1,(i==5));
                repeat(12) rx_byte(8'hdd,0,0);
            end
        join
        if (tx_seen!=16 || rx_seen!=16) $fatal(1,"Missing boundary bytes tx=%d rx=%d",tx_seen,rx_seen);
        repeat(12) rx_byte(8'hbb,0,0); // 100M/full duplex must NOT claim supported link.
        if(link_up) $fatal(1,"Unsupported speed accepted");
        #1.1; tx_reset=1; rx_reset=1;
        #1;
        if(rx_valid || link_up || tx_ctl) $fatal(1,"Asynchronous boundary reset failed");
        $display("PASS_RGMII_DDR_BOUNDARY tx=16 rx=16 er_tx=1 er_rx=1 clocks_independent=1");
        $finish;
    end
    initial begin #10000; $fatal(1,"Boundary timeout"); end
endmodule
