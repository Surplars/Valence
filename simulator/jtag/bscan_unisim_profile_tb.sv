`timescale 1ns/1ps
// Installed vendor model introspection ONLY; not a USER transaction test.
module bscan_unisim_profile_tb;
    wire tdo;
    JTAG_SIME2 #(.PART_NAME("XCZU15EG")) tap(.TCK(1'b0), .TMS(1'b1), .TDI(1'b0), .TDO(tdo));
    initial begin
        #1000; // Let glbl GSR and model initial blocks finish.
        $display("BSCAN_UNISIM_PROFILE_ONLY part=XCZU15EG ir_length=%0d user1=%h user2=%h idcode=%h",
            tap.IRLength,
            tap.USER1_INSTR >> (tap.IRLengthMax - tap.IRLength),
            tap.USER2_INSTR >> (tap.IRLengthMax - tap.IRLength), tap.IDCODEval_sig);
        $display("MODEL_PROFILE_IS_NOT_PHYSICAL_BOARD_BSDL_OR_CHAIN_ORDER");
        $finish;
    end
endmodule
