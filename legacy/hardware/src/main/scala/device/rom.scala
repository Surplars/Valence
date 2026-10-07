package soc.device

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.config.Config

class ROM(initPlusArg: String = "") extends BlackBox(Map("INIT_PLUSARG" -> initPlusArg)) with HasBlackBoxInline {
	val io = IO(new Bundle {
		val en = Input(Bool())
		val pc_in  = Input(UInt(Config.XLEN.W))
		val instr_out = Output(UInt(32.W))
	})

    setInline(
        "ROM.sv",
        s"""
module ROM #(
    parameter ROM_DEPTH = ${Config.romDepth},
    parameter ADDR_WIDTH = ${Config.XLEN},
    parameter INSTR_WIDTH = 32,
    parameter string INIT_PLUSARG = ""
)(
    input logic                     en,
    input logic [ADDR_WIDTH-1:0]    pc_in,
    output logic [INSTR_WIDTH-1:0]  instr_out
);

localparam BYTES_PER_WORD = INSTR_WIDTH / 8;
localparam IDX_LSB = $$clog2(BYTES_PER_WORD);
localparam int INDEX_BITS = $$clog2(ROM_DEPTH);

logic [INSTR_WIDTH-1:0] mem [0:ROM_DEPTH - 1];
logic [INDEX_BITS-1:0] idx;
string init_file;

initial begin
    for (int i = 0; i < ROM_DEPTH; i++) begin
        mem[i] = '0;
    end
    if (INIT_PLUSARG != "" && $$value$$plusargs({INIT_PLUSARG, "=%s"}, init_file)) begin
        $$readmemh(init_file, mem);
    end
end

/* verilator lint_off WIDTHTRUNC */
always_comb begin
    idx = pc_in[IDX_LSB +: INDEX_BITS];
    if (en) begin
        instr_out = mem[idx];
    end else begin
        instr_out = 32'h0000_0013;
    end
end
/* verilator lint_on WIDTHTRUNC */

endmodule
"""
    )
}

class BROM(XLEN: Int, depth: Int, init: Seq[Int]) extends Module {
    require(init.length == depth, "Initialization sequence length must match ROM depth")

    val io = IO(new Bundle {
        val fetch_en = Input(Bool())
        val addr     = Input(UInt(XLEN.W))
        val instr    = Output(UInt(64.W))
    })

	val loRom = Module(new ROM("ion_rom_lo"))
	val hiRom = Module(new ROM("ion_rom_hi"))

	loRom.io.en := io.fetch_en
	loRom.io.pc_in := io.addr
	hiRom.io.en := io.fetch_en
	hiRom.io.pc_in := io.addr + 4.U
	io.instr := Cat(hiRom.io.instr_out, loRom.io.instr_out)
}

class TLROM(params: TLParams) extends Module {
    require(params.dataWidth == 64, "TLROM currently expects a 64-bit TileLink data beat")

    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
    })
    TLBundle.tieoffSlaveCoherence(io.tl)

    private val beatBytes  = params.dataWidth / 8
    private val offsetBits = log2Ceil(beatBytes)

    val loRom = Module(new ROM("ion_rom_lo"))
    val hiRom = Module(new ROM("ion_rom_hi"))

    val beatBase = Cat(io.tl.a.bits.address(params.addrWidth - 1, offsetBits), 0.U(offsetBits.W))
    loRom.io.en    := io.tl.a.fire
    loRom.io.pc_in := beatBase
    hiRom.io.en    := io.tl.a.fire
    hiRom.io.pc_in := beatBase + 4.U

    val respValid  = RegInit(false.B)
    val respOpcode = RegInit(TLOpcode.AccessAck)
    val respParam  = RegInit(0.U(3.W))
    val respSize   = RegInit(0.U(params.sizeBits.W))
    val respSource = RegInit(0.U(params.sourceBits.W))
    val respDenied = RegInit(false.B)
    val respData   = RegInit(0.U(params.dataWidth.W))

    io.tl.a.ready := !respValid

    when(io.tl.a.fire) {
        val isRead = io.tl.a.bits.opcode === TLOpcode.Get || io.tl.a.bits.opcode === TLOpcode.AcquireBlock
        val rawBeat = Cat(hiRom.io.instr_out, loRom.io.instr_out)

        respValid  := true.B
        respOpcode := TLOpcode.responseOpcodeForA(io.tl.a.bits.opcode)
        respParam  := TLOpcode.responseParamForA(io.tl.a.bits.opcode, io.tl.a.bits.param)
        respSize   := io.tl.a.bits.size
        respSource := io.tl.a.bits.source
        respDenied := !isRead
        // Return the whole aligned beat. Downstream LSU/cache logic is
        // responsible for selecting bytes according to the original address.
        respData   := Mux(isRead, rawBeat, 0.U)
    }

    io.tl.d.valid        := respValid
    io.tl.d.bits.opcode  := respOpcode
    io.tl.d.bits.param   := respParam
    io.tl.d.bits.size    := respSize
    io.tl.d.bits.source  := respSource
    io.tl.d.bits.sink    := 0.U
    io.tl.d.bits.denied  := respDenied
    io.tl.d.bits.data    := respData
    io.tl.d.bits.corrupt := false.B

    when(io.tl.d.fire) {
        respValid := false.B
    }
}
