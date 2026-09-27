package soc.bus.tilelink

import chisel3._
import chisel3.util._
import chisel3.util.experimental.loadMemoryFromFileInline

private class DifftestRAM extends BlackBox with HasBlackBoxInline {
    val io = IO(new Bundle {
        val clock = Input(Clock())
        val rEn   = Input(Bool())
        val rIdx  = Input(UInt(64.W))
        val rData = Output(UInt(64.W))
        val wEn   = Input(Bool())
        val wIdx  = Input(UInt(64.W))
        val wData = Input(UInt(64.W))
        val wMask = Input(UInt(64.W))
    })

    setInline(
        "DifftestRAM.sv",
        """
module DifftestRAM (
    input  logic        clock,
    input  logic        rEn,
    input  logic [63:0] rIdx,
    output logic [63:0] rData,
    input  logic        wEn,
    input  logic [63:0] wIdx,
    input  logic [63:0] wData,
    input  logic [63:0] wMask
);
    import "DPI-C" function longint difftest_ram_read(input longint rIdx);
    import "DPI-C" function void difftest_ram_write(
        input longint wIdx,
        input longint wData,
        input longint wMask
    );

    always @(posedge clock) begin
        if (rEn)
            rData <= difftest_ram_read(rIdx);
        if (wEn)
            difftest_ram_write(wIdx, wData, wMask);
    end
endmodule
"""
    )
}

class TLRAM(
    params: TLParams,
    sizeBytes: Int,
    base: BigInt = 0,
    initFile: String = "",
    useDifftestMemory: Boolean = false
) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
    })
    io.tl.b.valid := false.B
    io.tl.b.bits := 0.U.asTypeOf(io.tl.b.bits)
    io.tl.e.ready := true.B

    require(params.dataWidth % 8 == 0, "dataWidth must be byte-aligned")

    private val beatBytes  = params.dataWidth / 8
    private val offsetBits = log2Ceil(beatBytes)

    require(sizeBytes % beatBytes == 0, s"sizeBytes must be multiple of $beatBytes bytes")

    require(!useDifftestMemory || params.dataWidth == 64, "DiffTest runtime memory requires 64-bit TileLink beats")

    val depth = sizeBytes / beatBytes

    val req_queue = Queue(io.tl.a, 2)
    val rel_queue = Queue(io.tl.c, 2)

    private val localAddr = req_queue.bits.address - base.U(params.addrWidth.W)
    val addr_idx   = localAddr >> offsetBits.U
    val wdata_vec  = VecInit(Seq.tabulate(beatBytes)(i => req_queue.bits.data(8 * i + 7, 8 * i)))
    val mask_vec   = VecInit(Seq.tabulate(beatBytes)(i => req_queue.bits.mask(i)))
    val is_write   = req_queue.bits.opcode === TLOpcode.PutFullData || req_queue.bits.opcode === TLOpcode.PutPartialData
    val is_read    = req_queue.bits.opcode === TLOpcode.Get || req_queue.bits.opcode === TLOpcode.AcquireBlock
    val is_acquire = req_queue.bits.opcode === TLOpcode.AcquireBlock || req_queue.bits.opcode === TLOpcode.AcquirePerm
    val is_legal   = is_read || is_write || is_acquire

    private val relLocalAddr = rel_queue.bits.address - base.U(params.addrWidth.W)
    val rel_addr_idx = relLocalAddr >> offsetBits.U
    val rel_data_vec = VecInit(Seq.tabulate(beatBytes)(i => rel_queue.bits.data(8 * i + 7, 8 * i)))
    val rel_mask_vec = VecInit(Seq.fill(beatBytes)(true.B))
    val rel_has_data = rel_queue.bits.opcode === TLOpcode.ReleaseData
    val rel_is_legal = TLOpcode.isRelease(rel_queue.bits.opcode)

    val req_valid      = RegInit(false.B)
    val req_is_read    = RegInit(false.B)
    val req_is_release = RegInit(false.B)
    val req_opcode     = RegInit(0.U(3.W))
    val req_param      = RegInit(0.U(3.W))
    val req_size       = RegInit(0.U(params.sizeBits.W))
    val req_source     = RegInit(0.U(params.sourceBits.W))
    val req_denied     = RegInit(false.B)

    val resp_valid   = RegInit(false.B)
    val resp_opcode  = RegInit(TLOpcode.AccessAck)
    val resp_param   = RegInit(0.U(3.W))
    val resp_size    = RegInit(0.U(params.sizeBits.W))
    val resp_source  = RegInit(0.U(params.sourceBits.W))
    val resp_denied  = RegInit(false.B)
    val resp_data    = RegInit(0.U(params.dataWidth.W))

    val can_accept = !req_valid && !resp_valid
    val prefer_release = RegInit(false.B)
    val take_release = can_accept && rel_queue.valid && (!req_queue.valid || prefer_release)
    val take_request = can_accept && req_queue.valid && !take_release

    req_queue.ready := take_request
    rel_queue.ready := take_release

    val req_fire = take_request
    val rel_fire = take_release
    val mem_rdata = if (useDifftestMemory) {
        val mem = Module(new DifftestRAM)
        val reqWriteMask = Cat(mask_vec.reverse.map(bit => Fill(8, bit)))
        mem.io.clock := clock
        mem.io.rEn := req_fire && is_read
        mem.io.rIdx := addr_idx
        mem.io.wEn := (req_fire && is_write) || (rel_fire && rel_has_data)
        mem.io.wIdx := Mux(rel_fire && rel_has_data, rel_addr_idx, addr_idx)
        mem.io.wData := Mux(rel_fire && rel_has_data, rel_data_vec.asUInt, wdata_vec.asUInt)
        mem.io.wMask := Mux(rel_fire && rel_has_data, Fill(params.dataWidth, 1.U), reqWriteMask)
        mem.io.rData
    } else {
        val mem = SyncReadMem(depth, Vec(beatBytes, UInt(8.W)))
        if (initFile.nonEmpty) {
            loadMemoryFromFileInline(mem, initFile)
        }
        when(req_fire && is_write) {
            mem.write(addr_idx, wdata_vec, mask_vec)
        }
        when(rel_fire && rel_has_data) {
            mem.write(rel_addr_idx, rel_data_vec, rel_mask_vec)
        }
        mem.read(addr_idx, req_fire && is_read).asUInt
    }

    when(req_fire) {
        req_valid      := true.B
        req_is_read    := is_read
        req_is_release := false.B
        req_opcode     := req_queue.bits.opcode
        req_param      := req_queue.bits.param
        req_size       := req_queue.bits.size
        req_source     := req_queue.bits.source
        req_denied     := !is_legal
        prefer_release := true.B
    }.elsewhen(rel_fire) {
        req_valid      := true.B
        req_is_read    := false.B
        req_is_release := true.B
        req_opcode     := rel_queue.bits.opcode
        req_param      := rel_queue.bits.param
        req_size       := rel_queue.bits.size
        req_source     := rel_queue.bits.source
        req_denied     := !rel_is_legal
        prefer_release := false.B
    }

    when(req_valid && !resp_valid) {
        resp_valid  := true.B
        resp_opcode := Mux(req_is_release, TLOpcode.responseOpcodeForC(req_opcode), TLOpcode.responseOpcodeForA(req_opcode))
        resp_size   := req_size
        resp_source := req_source
        resp_denied := req_denied
        resp_param  := Mux(req_is_release, 0.U, TLOpcode.responseParamForA(req_opcode, req_param))
        // D-channel data keeps the requested byte lanes in their natural beat
        // positions. LSU/cache clients perform size and address-based extraction.
        resp_data   := Mux(req_is_read && !req_denied, mem_rdata.asUInt, 0.U)
        req_valid   := false.B
    }

    io.tl.d.valid        := resp_valid
    io.tl.d.bits.opcode  := resp_opcode
    io.tl.d.bits.param   := resp_param
    io.tl.d.bits.size    := resp_size
    io.tl.d.bits.source  := resp_source
    io.tl.d.bits.sink    := 0.U
    io.tl.d.bits.denied  := resp_denied
    io.tl.d.bits.data    := resp_data
    io.tl.d.bits.corrupt := false.B

    when(io.tl.d.fire) {
        resp_valid := false.B
    }
}
