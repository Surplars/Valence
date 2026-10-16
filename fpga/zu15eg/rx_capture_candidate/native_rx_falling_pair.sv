`timescale 1ns/1ps
// Source-only, default OFF. Both clocks remain related and fully STA timed.
module native_rx_falling_pair #(parameter ENABLE_FALLING_PAIR = 0)(
    input wire capture_clock, capture_reset,
    input wire [4:0] input_rise, input_fall,
    output wire [4:0] output_rise, output_fall);
    initial if (ENABLE_FALLING_PAIR != 0 && ENABLE_FALLING_PAIR != 1)
        $fatal(1,"ENABLE_FALLING_PAIR must be 0 or 1");
    generate if (ENABLE_FALLING_PAIR) begin: enabled
        // Preserve the entire data/control pair atomically. No DV/ER bypass.
        reg [9:0] pair;
        always @(negedge capture_clock or posedge capture_reset)
            if(capture_reset) pair<=10'b0;
            else pair<={input_fall,input_rise};
        assign {output_fall,output_rise}=pair;
    end else begin: disabled
        assign output_rise=input_rise;
        assign output_fall=input_fall;
    end endgenerate
endmodule
