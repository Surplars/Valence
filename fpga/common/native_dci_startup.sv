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
    // Installed Vivado 2025.2 UNISIM DCIRESET requires BOTH RST levels
    // >=100 ns. DS925 CFGMCLK max=57.5 MHz: 8 cycles >=139.13 ns.
    // Do not asynchronously clear reset_dci: a cold reset during its high
    // pulse must queue a retry, not truncate that pulse below the minimum.
    reg [1:0] phase = 2'd0; // 0 low guard/request, 1 high guard, 2 await lock
    reg [2:0] pulse_age = 3'd0;
    reg pending = 1'b1;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [2:0] lock_samples = 3'b111;
    always @(posedge cfg_clock) begin
        lock_samples <= {lock_samples[1:0],locked};
        if (local_reset) begin
            pending <= 1'b1;
            completed <= 1'b0;
        end
        case (phase)
            2'd0: begin
                if (pulse_age != 3'd7) pulse_age <= pulse_age + 1'b1;
                if (pulse_age == 3'd7 && pending && !local_reset) begin
                    reset_dci <= 1'b1;
                    reset_acknowledged <= 1'b0;
                    completed <= 1'b0;
                    pending <= 1'b0;
                    lock_samples <= 3'b111;
                    pulse_age <= 3'd0;
                    phase <= 2'd1;
                end
            end
            2'd1: begin
                if (pulse_age != 3'd7) pulse_age <= pulse_age + 1'b1;
                if (pulse_age == 3'd7 && !lock_samples[2]) begin
                    reset_dci <= 1'b0;
                    reset_acknowledged <= 1'b1;
                    pulse_age <= 3'd0;
                    phase <= 2'd2;
                end
            end
            2'd2: begin
                if (pulse_age != 3'd7) pulse_age <= pulse_age + 1'b1;
                if (local_reset || pending) begin
                    completed <= 1'b0;
                    phase <= 2'd0;
                end else if (pulse_age == 3'd7 && lock_samples[2]) completed <= 1'b1;
            end
            default: begin
                completed <= 1'b0;
                pending <= 1'b1;
                phase <= 2'd0;
            end
        endcase
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
