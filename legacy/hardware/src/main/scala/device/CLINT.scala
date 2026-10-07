package soc.device

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

class CLINT(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val tl   = Flipped(new TLBundle(params))
        val msip = Output(Bool())
        val mtip = Output(Bool())
    })
    TLBundle.tieoffSlaveCoherence(io.tl)

    private val beatBytes = params.dataWidth / 8

    // mtime: 64-bit free-running counter
    val mtime = RegInit(0.U(64.W))
    mtime := mtime + 1.U

    // mtimecmp: 64-bit compare register, writable via bus
    val mtimecmp = RegInit(0.U(64.W))
    val msip = RegInit(false.B)

    val cond = Wire(UInt(2.W))
    cond := Cat(mtime >= mtimecmp, mtimecmp.orR)
    io.msip := msip
    io.mtip := cond.andR

    // TL request handling
    val req_ready  = Wire(Bool())
    val resp_valid = RegInit(false.B)
    val resp_data  = RegInit(0.U(64.W))
    val resp_opcode = RegInit(TLOpcode.AccessAck)
    val resp_param  = RegInit(0.U(3.W))
    val resp_size   = RegInit(0.U(params.sizeBits.W))
    val resp_source = RegInit(0.U(params.sourceBits.W))
    val resp_denied = RegInit(false.B)

    io.tl.a.ready := req_ready
    req_ready := !resp_valid

    // Address offset within CLINT region. Decode on the 64-bit beat so
    // 32-bit high-word accesses to mtime/mtimecmp hit the same register.
    val addr_offset = io.tl.a.bits.address(15, 0)
    val beat_offset = addr_offset(15, log2Ceil(beatBytes)) ## 0.U(log2Ceil(beatBytes).W)

    when(io.tl.a.fire) {
        val is_read  = io.tl.a.bits.opcode === TLOpcode.Get
        val is_write = io.tl.a.bits.opcode === TLOpcode.PutFullData ||
                       io.tl.a.bits.opcode === TLOpcode.PutPartialData
        val is_legal = is_read || is_write

        resp_valid  := true.B
        resp_source := io.tl.a.bits.source
        resp_size   := io.tl.a.bits.size
        resp_param  := TLOpcode.responseParamForA(io.tl.a.bits.opcode, io.tl.a.bits.param)
        // Keep CLINT aligned with other TL slaves: unsupported opcodes get a
        // real D-channel response with denied set instead of silently acking.
        resp_denied := !is_legal

        when(is_read) {
            resp_opcode := TLOpcode.AccessAckData
            when(beat_offset === 0x0000.U) {
                resp_data := msip.asUInt
            }.elsewhen(beat_offset === 0x4000.U) {
                resp_data := mtimecmp
            }.elsewhen(beat_offset === 0xBFF8.U) {
                resp_data := mtime
            }.otherwise {
                resp_data := 0.U
            }
        }.elsewhen(is_write) {
            resp_opcode := TLOpcode.AccessAck
            resp_data   := 0.U
            val maskBits = Cat((0 until beatBytes).reverse.map { i =>
                Fill(8, io.tl.a.bits.mask(i))
            })
            when(beat_offset === 0x0000.U) {
                when(io.tl.a.bits.mask(0)) {
                    msip := io.tl.a.bits.data(0)
                }
            }.elsewhen(beat_offset === 0x4000.U) {
                // Write to mtimecmp with byte mask
                mtimecmp := (mtimecmp & ~maskBits) | (io.tl.a.bits.data & maskBits)
            }
        }.otherwise {
            resp_opcode := TLOpcode.responseOpcodeForA(io.tl.a.bits.opcode)
            resp_data   := 0.U
        }
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
