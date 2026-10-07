package soc.bus.tilelink

import chisel3._
import chisel3.util._

// Minimal blocking TL-C coherence hub for a single downstream memory manager.
// It tracks one owner per line and handles the essential conflict path:
// Acquire from a new client -> Probe old owner -> Grant requester.
class TLCoherenceHub(params: TLParams, nClients: Int, nEntries: Int = 16) extends Module {
    require(nClients > 0, "nClients must be positive")
    require(isPow2(nEntries), "nEntries must be a power of two")

    private val clientBits = math.max(1, log2Ceil(nClients))
    private val hubParams = params.copy(sourceBits = params.sourceBits + (if (nClients <= 1) 0 else log2Ceil(nClients)))

    val io = IO(new Bundle {
        val clients = Vec(nClients, Flipped(new TLBundle(params)))
        val manager = new TLBundle(hubParams)
    })

    private val beatBytes = params.dataWidth / 8
    private val offsetBits = log2Ceil(beatBytes)
    private val indexBits = log2Ceil(nEntries)
    private val tagBits = params.addrWidth - offsetBits - indexBits

    private def lineIndex(addr: UInt): UInt = addr(offsetBits + indexBits - 1, offsetBits)
    private def lineTag(addr: UInt): UInt = addr(params.addrWidth - 1, offsetBits + indexBits)
    private def lineBase(addr: UInt): UInt = Cat(addr(params.addrWidth - 1, offsetBits), 0.U(offsetBits.W))
    private def expandSource(client: UInt, source: UInt): UInt =
        if (nClients <= 1) source else Cat(client, source)
    private def shrinkSource(source: UInt): UInt =
        if (nClients <= 1) source else source(params.sourceBits - 1, 0)

    private val dirValid = RegInit(VecInit(Seq.fill(nEntries)(false.B)))
    private val dirOwner = RegInit(VecInit(Seq.fill(nEntries)(0.U(clientBits.W))))
    private val dirTag = Reg(Vec(nEntries, UInt(tagBits.W)))

    private val (
        sIdle :: sProbe :: sProbeWait :: sProbeWritebackC :: sProbeWritebackD ::
        sMemA :: sMemD :: sLocalGrant :: sRelC :: sRelD :: Nil
    ) = Enum(10)
    private val state = RegInit(sIdle)

    private val pendingClient = RegInit(0.U(clientBits.W))
    private val pendingOldOwner = RegInit(0.U(clientBits.W))
    private val pendingOpcode = RegInit(0.U(3.W))
    private val pendingParam = RegInit(0.U(3.W))
    private val pendingSize = RegInit(0.U(params.sizeBits.W))
    private val pendingSource = RegInit(0.U(params.sourceBits.W))
    private val pendingAddress = RegInit(0.U(params.addrWidth.W))
    private val pendingMask = RegInit(0.U((params.dataWidth / 8).W))
    private val pendingData = RegInit(0.U(params.dataWidth.W))
    private val pendingCorrupt = RegInit(false.B)
    private val pendingIsAcquire = RegInit(false.B)
    private val pendingIdx = RegInit(0.U(indexBits.W))
    private val pendingTag = RegInit(0.U(tagBits.W))
    private val pendingProbeData = RegInit(0.U(params.dataWidth.W))
    private val pendingProbeHasData = RegInit(false.B)

    private val aValidVec = VecInit((0 until nClients).map(i => io.clients(i).a.valid))
    private val aSel = PriorityEncoder(aValidVec)
    private val aAny = aValidVec.asUInt.orR
    private val cReleaseVec = VecInit((0 until nClients).map { i =>
        io.clients(i).c.valid && TLOpcode.isRelease(io.clients(i).c.bits.opcode)
    })
    private val cSel = PriorityEncoder(cReleaseVec)
    private val cAny = cReleaseVec.asUInt.orR

    for (i <- 0 until nClients) {
        io.clients(i).a.ready := false.B
        io.clients(i).b.valid := false.B
        io.clients(i).b.bits := 0.U.asTypeOf(io.clients(i).b.bits)
        io.clients(i).c.ready := false.B
        io.clients(i).d.valid := false.B
        io.clients(i).d.bits := 0.U.asTypeOf(io.clients(i).d.bits)
        io.clients(i).e.ready := true.B
    }

    io.manager.a.valid := false.B
    io.manager.a.bits := 0.U.asTypeOf(io.manager.a.bits)
    io.manager.b.ready := true.B
    io.manager.c.valid := false.B
    io.manager.c.bits := 0.U.asTypeOf(io.manager.c.bits)
    io.manager.d.ready := false.B
    io.manager.e.valid := false.B
    io.manager.e.bits := 0.U.asTypeOf(io.manager.e.bits)

    // Forward downstream D beats only when the manager has produced one. A
    // speculative client-side valid would let an L1 consume a response while
    // the hub still waits for the real beat, deadlocking the next request.
    private def driveClientD(client: UInt, valid: Bool, bits: TLBundleD): Unit = {
        for (i <- 0 until nClients) {
            when(client === i.U) {
                io.clients(i).d.valid := valid
                io.clients(i).d.bits := bits
            }
        }
    }

    private val localD = Wire(new TLBundleD(params))
    localD.opcode := TLOpcode.responseOpcodeForA(pendingOpcode)
    localD.param := TLOpcode.responseParamForA(pendingOpcode, pendingParam)
    localD.size := pendingSize
    localD.source := pendingSource
    localD.sink := 0.U
    localD.denied := false.B
    localD.data := Mux(pendingProbeHasData, pendingProbeData, 0.U)
    localD.corrupt := false.B

    switch(state) {
        is(sIdle) {
            when(cAny) {
                val req = io.clients(cSel).c.bits
                io.clients(cSel).c.ready := true.B
                when(io.clients(cSel).c.fire) {
                    pendingClient := cSel
                    pendingOpcode := req.opcode
                    pendingParam := req.param
                    pendingSize := req.size
                    pendingSource := req.source
                    pendingAddress := req.address
                    pendingData := req.data
                    pendingCorrupt := req.corrupt
                    pendingIdx := lineIndex(req.address)
                    pendingTag := lineTag(req.address)
                    state := sRelC
                }
            }.elsewhen(aAny) {
                val req = io.clients(aSel).a.bits
                val idx = lineIndex(req.address)
                val tag = lineTag(req.address)
                val isAcquire = TLOpcode.isAcquire(req.opcode)
                val hit = dirValid(idx) && dirTag(idx) === tag
                val owner = dirOwner(idx)
                val conflict = isAcquire && hit && owner =/= aSel

                io.clients(aSel).a.ready := true.B
                when(io.clients(aSel).a.fire) {
                    pendingClient := aSel
                    pendingOldOwner := owner
                    pendingOpcode := req.opcode
                    pendingParam := req.param
                    pendingSize := req.size
                    pendingSource := req.source
                    pendingAddress := req.address
                    pendingMask := req.mask
                    pendingData := req.data
                    pendingCorrupt := req.corrupt
                    pendingIsAcquire := isAcquire
                    pendingIdx := idx
                    pendingTag := tag
                    pendingProbeHasData := false.B
                    state := Mux(conflict, sProbe, sMemA)
                }
            }
        }

        is(sProbe) {
            for (i <- 0 until nClients) {
                when(pendingOldOwner === i.U) {
                    io.clients(i).b.valid := true.B
                    io.clients(i).b.bits.opcode := TLOpcode.ProbeBlock
                    io.clients(i).b.bits.param := TLPermissions.toN
                    io.clients(i).b.bits.size := pendingSize
                    io.clients(i).b.bits.source := pendingSource
                    io.clients(i).b.bits.address := lineBase(pendingAddress)
                    io.clients(i).b.bits.mask := Fill(beatBytes, 1.U(1.W))
                    io.clients(i).b.bits.data := 0.U
                    io.clients(i).b.bits.corrupt := false.B
                    when(io.clients(i).b.fire) {
                        state := sProbeWait
                    }
                }
            }
        }

        is(sProbeWait) {
            for (i <- 0 until nClients) {
                when(pendingOldOwner === i.U) {
                    io.clients(i).c.ready := true.B
                    when(io.clients(i).c.fire) {
                        pendingProbeHasData := io.clients(i).c.bits.opcode === TLOpcode.ProbeAckData
                        pendingProbeData := io.clients(i).c.bits.data
                        dirValid(pendingIdx) := false.B
                        state := Mux(io.clients(i).c.bits.opcode === TLOpcode.ProbeAckData, sProbeWritebackC, sMemA)
                    }
                }
            }
        }

        is(sProbeWritebackC) {
            io.manager.c.valid := true.B
            io.manager.c.bits.opcode := TLOpcode.ReleaseData
            io.manager.c.bits.param := TLPermissions.tToN
            io.manager.c.bits.size := pendingSize
            io.manager.c.bits.source := expandSource(pendingOldOwner, pendingSource)
            io.manager.c.bits.address := lineBase(pendingAddress)
            io.manager.c.bits.data := pendingProbeData
            io.manager.c.bits.corrupt := false.B
            when(io.manager.c.fire) {
                state := sProbeWritebackD
            }
        }

        is(sProbeWritebackD) {
            io.manager.d.ready := true.B
            when(io.manager.d.fire) {
                state := Mux(io.manager.d.bits.denied, sMemA, sLocalGrant)
            }
        }

        is(sMemA) {
            io.manager.a.valid := true.B
            io.manager.a.bits.opcode := pendingOpcode
            io.manager.a.bits.param := pendingParam
            io.manager.a.bits.size := pendingSize
            io.manager.a.bits.source := expandSource(pendingClient, pendingSource)
            io.manager.a.bits.address := pendingAddress
            io.manager.a.bits.mask := pendingMask
            io.manager.a.bits.data := pendingData
            io.manager.a.bits.corrupt := pendingCorrupt
            when(io.manager.a.fire) {
                state := sMemD
            }
        }

        is(sMemD) {
            val clientD = Wire(new TLBundleD(params))
            clientD.opcode := io.manager.d.bits.opcode
            clientD.param := io.manager.d.bits.param
            clientD.size := io.manager.d.bits.size
            clientD.source := shrinkSource(io.manager.d.bits.source)
            clientD.sink := io.manager.d.bits.sink
            clientD.denied := io.manager.d.bits.denied
            clientD.data := io.manager.d.bits.data
            clientD.corrupt := io.manager.d.bits.corrupt

            driveClientD(pendingClient, io.manager.d.valid, clientD)
            io.manager.d.ready := io.clients(pendingClient).d.ready
            when(io.manager.d.fire) {
                when(pendingIsAcquire && !io.manager.d.bits.denied) {
                    dirValid(pendingIdx) := true.B
                    dirOwner(pendingIdx) := pendingClient
                    dirTag(pendingIdx) := pendingTag
                }
                state := sIdle
            }
        }

        is(sLocalGrant) {
            driveClientD(pendingClient, true.B, localD)
            when(io.clients(pendingClient).d.fire) {
                dirValid(pendingIdx) := true.B
                dirOwner(pendingIdx) := pendingClient
                dirTag(pendingIdx) := pendingTag
                state := sIdle
            }
        }

        is(sRelC) {
            io.manager.c.valid := true.B
            io.manager.c.bits.opcode := pendingOpcode
            io.manager.c.bits.param := pendingParam
            io.manager.c.bits.size := pendingSize
            io.manager.c.bits.source := expandSource(pendingClient, pendingSource)
            io.manager.c.bits.address := pendingAddress
            io.manager.c.bits.data := pendingData
            io.manager.c.bits.corrupt := pendingCorrupt
            when(io.manager.c.fire) {
                state := sRelD
            }
        }

        is(sRelD) {
            val clientD = Wire(new TLBundleD(params))
            clientD.opcode := io.manager.d.bits.opcode
            clientD.param := io.manager.d.bits.param
            clientD.size := io.manager.d.bits.size
            clientD.source := shrinkSource(io.manager.d.bits.source)
            clientD.sink := io.manager.d.bits.sink
            clientD.denied := io.manager.d.bits.denied
            clientD.data := io.manager.d.bits.data
            clientD.corrupt := io.manager.d.bits.corrupt

            driveClientD(pendingClient, io.manager.d.valid, clientD)
            io.manager.d.ready := io.clients(pendingClient).d.ready
            when(io.manager.d.fire) {
                when(!io.manager.d.bits.denied && dirValid(pendingIdx) && dirOwner(pendingIdx) === pendingClient && dirTag(pendingIdx) === pendingTag) {
                    dirValid(pendingIdx) := false.B
                }
                state := sIdle
            }
        }
    }
}
