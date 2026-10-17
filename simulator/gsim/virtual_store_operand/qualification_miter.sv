module qualification_miter(input [14:0] flags, input [5:0] operation, input [3:0] control,
 output ok);
 wire virtualOperands, off, on;
 VirtualStoreOperandQualification dut(.clock(1'b0), .reset(1'b0), .io_flags(flags),
  .io_operation(operation), .io_control(control), .io_virtualOperands(virtualOperands),
  .io_off(off), .io_on(on));
 // Independently enumerated static qualification: pending/live/index/memory/store/saved/known.
 // Negative fields: head, atomic, system, muldiv, fetch fault, fetch page fault.
 wire ordinary = flags[12:0] == 13'h183b && operation == 6'd0 && control == 4'd0;
 wire expect_virtual = ordinary && flags[14];
 wire expect_off = ordinary && flags[13] && !flags[14];
 wire expect_on = ordinary && (flags[14] || flags[13]);
 assign ok = virtualOperands == expect_virtual && off == expect_off && on == expect_on;
endmodule
