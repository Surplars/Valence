`timescale 1ns/1ps
`default_nettype none
// UG974 (2025.2) DCIRESET + STARTUPE3; UG570 startup step 8.
// DCI must be reset AFTER EOS, and DCI I/O remains unavailable until LOCKED.
// No MIG/UI/calibration input is allowed here: MIG is held reset by ready.
module native_dci_startup(input wire cold_reset, output wire ready);
    wire cfg_raw, cfg_clock, eos, locked;
    STARTUPE3 #(.PROG_USR("FALSE"), .SIM_CCLK_FREQ(0.0)) startup (
        .CFGCLK(), .CFGMCLK(cfg_raw), .DI(), .EOS(eos), .PREQ(),
        .DO(4'b0), .DTS(4'b1111), .FCSBO(1'b1), .FCSBTS(1'b1),
        .GSR(1'b0), .GTS(1'b0), .KEYCLEARB(1'b1), .PACK(1'b0),
        .USRCCLKO(1'b0), .USRCCLKTS(1'b1), .USRDONEO(1'b1), .USRDONETS(1'b1));
    BUFG cfg_buffer(.I(cfg_raw), .O(cfg_clock));
    wire restart = cold_reset | ~eos;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [2:0] startup_release = 3'b111;
    always @(posedge cfg_clock or posedge restart)
        if (restart) startup_release <= 3'b111;
        else startup_release <= {startup_release[1:0],1'b0};
    wire local_reset = startup_release[2];
    reg reset_dci = 1'b0;
    reg reset_acknowledged = 1'b0;
    reg completed = 1'b0;
    // Initialize to one so pre-reset LOCKED=0 cannot immediately acknowledge
    // a newly asserted request. Three actual samples while RST is high are
    // required. This is a handshake latency, NOT an invented vendor minimum.
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [2:0] lock_samples = 3'b111;
    always @(posedge cfg_clock or posedge local_reset) begin
        if (local_reset) begin
            reset_dci <= 1'b0;
            reset_acknowledged <= 1'b0;
            completed <= 1'b0;
            lock_samples <= 3'b111;
        end else begin
            if (!reset_dci && !reset_acknowledged) begin
                reset_dci <= 1'b1;
                lock_samples <= 3'b111;
            end else begin
                lock_samples <= {lock_samples[1:0],locked};
                if (reset_dci && !lock_samples[2]) begin
                    reset_dci <= 1'b0;
                    reset_acknowledged <= 1'b1;
                end
                if (reset_acknowledged && lock_samples[2]) completed <= 1'b1;
            end
        end
    end
    DCIRESET dci (.RST(reset_dci), .LOCKED(locked));
    // Loss asserts MIG reset immediately; release waits for synchronized LOCKED.
    wire inhibit = restart | ~completed | ~locked;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [2:0] ready_release = 3'b111;
    always @(posedge cfg_clock or posedge inhibit)
        if (inhibit) ready_release <= 3'b111;
        else ready_release <= {ready_release[1:0],1'b0};
    assign ready = ~ready_release[2];
endmodule
`default_nettype wire
