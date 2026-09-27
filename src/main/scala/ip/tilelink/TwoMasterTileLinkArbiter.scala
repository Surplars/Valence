package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** Two independent TL-UL masters sharing one manager. The added high source bit identifies the master on D. */
class TwoMasterTileLinkArbiter(params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3))
    extends Module {
    require(params.sourceBits >= 1 && params.sourceBits <= 6)
    val managerParams = params.copy(sourceBits = params.sourceBits + 1)
    val io = IO(new Bundle {
        val masters = Vec(2, Flipped(new TLBundle(params)))
        val manager = new TLBundle(managerParams)
    })

    val occupied = RegInit(VecInit(Seq.fill(2)(VecInit(Seq.fill(1 << params.sourceBits)(false.B)))))
    val turn = RegInit(false.B)
    val locked = RegInit(false.B)
    val lockedOwner = Reg(Bool())
    val aBurst = RegInit(false.B)
    val aOwner = Reg(Bool())
    val aSource = Reg(UInt(params.sourceBits.W))
    val aAddress = Reg(UInt(params.addrWidth.W))
    val aSize = Reg(UInt(params.sizeBits.W))
    val aOpcode = Reg(UInt(3.W))
    val aParam = Reg(UInt(3.W))
    val aRemaining = Reg(UInt(TLBurst.beats(0.U(params.sizeBits.W), params).getWidth.W))
    val dBurst = RegInit(false.B)
    val dSource = Reg(UInt(managerParams.sourceBits.W))
    val dSize = Reg(UInt(params.sizeBits.W))
    val dOpcode = Reg(UInt(3.W))
    val dRemaining = Reg(UInt(aRemaining.getWidth.W))
    val eligible = VecInit((0 until 2).map { i =>
        val source = Mux(io.masters(i).a.valid, io.masters(i).a.bits.source, 0.U)
        io.masters(i).a.valid && !occupied(i)(source)
    })
    val selected = Mux(aBurst, aOwner, Mux(locked, lockedOwner,
        Mux(eligible(0) && eligible(1), turn, eligible(1))))
    val source = io.masters(selected).a.bits.source
    io.manager.a.valid := Mux(aBurst, io.masters(selected).a.valid, eligible(selected))
    io.manager.a.bits.opcode  := io.masters(selected).a.bits.opcode
    io.manager.a.bits.param   := io.masters(selected).a.bits.param
    io.manager.a.bits.size    := io.masters(selected).a.bits.size
    io.manager.a.bits.source  := Cat(selected, source)
    io.manager.a.bits.address := io.masters(selected).a.bits.address
    io.manager.a.bits.mask    := io.masters(selected).a.bits.mask
    io.manager.a.bits.data    := io.masters(selected).a.bits.data
    io.manager.a.bits.corrupt := io.masters(selected).a.bits.corrupt
    for (i <- 0 until 2) {
        io.masters(i).a.ready := selected === i.U && (aBurst || !occupied(i)(Mux(io.masters(i).a.valid,
            io.masters(i).a.bits.source, 0.U))) &&
            io.manager.a.ready
        io.masters(i).b.valid := false.B
        io.masters(i).b.bits := 0.U.asTypeOf(io.masters(i).b.bits)
        io.masters(i).c.ready := false.B
        io.masters(i).e.ready := false.B
        when(io.masters(i).c.valid || io.masters(i).e.valid) {
            assert(false.B, "Two-master TileLink arbiter only supports TL-UL")
        }
    }
    io.manager.b.ready := false.B
    io.manager.c.valid := false.B
    io.manager.c.bits := 0.U.asTypeOf(io.manager.c.bits)
    io.manager.e.valid := false.B
    io.manager.e.bits := 0.U.asTypeOf(io.manager.e.bits)
    when(io.manager.b.valid) { assert(false.B, "Two-master TileLink arbiter cannot accept coherence probes") }

    when(io.manager.a.valid && !io.manager.a.ready) { locked := true.B; lockedOwner := selected }
    when(io.manager.a.fire) {
        val a = io.manager.a.bits
        when(aBurst) {
            assert(selected === aOwner && source === aSource && a.address === aAddress &&
                a.size === aSize && a.opcode === aOpcode && a.param === aParam,
                "TileLink A burst changed control or source between beats")
            when(aRemaining === 1.U) { aBurst := false.B }
                .otherwise { aRemaining := aRemaining - 1.U }
        }.otherwise {
            assert(!occupied(selected)(source), "Two-master TileLink source reused before response")
            occupied(selected)(source) := true.B
            val beats = TLBurst.beats(a.size, params)
            when(TLBurst.hasDataOnA(a.opcode) && beats > 1.U) {
                aBurst := true.B
                aOwner := selected
                aSource := source
                aAddress := a.address
                aSize := a.size
                aOpcode := a.opcode
                aParam := a.param
                aRemaining := beats - 1.U
            }
        }
        locked := false.B
        turn := !selected
    }

    val responseOwner = Mux(io.manager.d.valid, io.manager.d.bits.source(params.sourceBits), 0.U)
    val responseSource = Mux(io.manager.d.valid, io.manager.d.bits.source(params.sourceBits - 1, 0), 0.U)
    val responseKnown = occupied(responseOwner)(responseSource)
    when(io.manager.d.valid && dBurst) {
        assert(io.manager.d.bits.source === dSource && io.manager.d.bits.size === dSize &&
            io.manager.d.bits.opcode === dOpcode,
            "TileLink D burst interleaved or changed control between beats")
    }
    for (i <- 0 until 2) {
        io.masters(i).d.valid := io.manager.d.valid && responseKnown && responseOwner === i.U
        io.masters(i).d.bits.opcode := io.manager.d.bits.opcode
        io.masters(i).d.bits.param := io.manager.d.bits.param
        io.masters(i).d.bits.size := io.manager.d.bits.size
        io.masters(i).d.bits.source := responseSource
        io.masters(i).d.bits.sink := io.manager.d.bits.sink
        io.masters(i).d.bits.denied := io.manager.d.bits.denied
        io.masters(i).d.bits.data := io.manager.d.bits.data
        io.masters(i).d.bits.corrupt := io.manager.d.bits.corrupt
    }
    io.manager.d.ready := responseKnown && io.masters(responseOwner).d.ready
    when(io.manager.d.valid) {
        assert(responseKnown || (io.manager.a.fire && io.manager.a.bits.source === io.manager.d.bits.source),
            "Two-master TileLink response has no matching source")
    }
    when(io.manager.d.fire) {
        when(dBurst) {
            when(dRemaining === 1.U) {
                dBurst := false.B
                occupied(responseOwner)(responseSource) := false.B
            }.otherwise { dRemaining := dRemaining - 1.U }
        }.otherwise {
            val beats = TLBurst.beats(io.manager.d.bits.size, params)
            when(TLBurst.hasDataOnD(io.manager.d.bits.opcode) && beats > 1.U) {
                dBurst := true.B
                dSource := io.manager.d.bits.source
                dSize := io.manager.d.bits.size
                dOpcode := io.manager.d.bits.opcode
                dRemaining := beats - 1.U
            }.otherwise { occupied(responseOwner)(responseSource) := false.B }
        }
    }
}
