module ROM #(
	parameter ROM_DEPTH = 16384,
    parameter ADDR_WIDTH = 64,
    parameter INSTR_WIDTH = 32
)(
    input logic                     en,
    input logic [ADDR_WIDTH-1:0]    pc_in,
    
    output logic [INSTR_WIDTH-1:0]  instr_out
);

// function integer clogb2 (input integer bit_depth);
//     begin
//         for (clogb2 = 0; bit_depth > 0; clogb2 = clogb2 + 1)
//             bit_depth = bit_depth >> 1;
//     end 
// endfunction

localparam BYTES_PER_WORD = INSTR_WIDTH / 8;
localparam IDX_LSB = $clog2(BYTES_PER_WORD);
localparam int INDEX_BITS = $clog2(ROM_DEPTH);

logic [INSTR_WIDTH-1:0] mem [0:ROM_DEPTH - 1];

/* verilator lint_off WIDTHTRUNC */
logic [INDEX_BITS-1:0] idx;
always_comb begin
    idx = pc_in[IDX_LSB +: INDEX_BITS];
    if(en) begin
        instr_out = mem[idx];
    end else begin
        instr_out = 'h0x0000_0013;
    end
end
/* verilator lint_on WIDTHTRUNC */
endmodule


