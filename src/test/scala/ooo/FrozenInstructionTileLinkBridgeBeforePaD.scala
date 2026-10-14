// Frozen bridge from r5 baseline; do not regenerate from the candidate.
// Original file SHA256: 146dce34bfb63c93a3b67bd6e518558a49bafda696f221880bf93c0fb7a34ae1
package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** One instruction packet in flight, with one immutable ROM beat retained across packets. */
class FrozenInstructionTileLinkBridgeBeforePaD(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    immutableBase: BigInt = BigInt("80000000", 16),
    immutableBytes: Int = 8192,
    parallelAddresses: Boolean = false
) extends Module {
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sourceBits >= 2 && params.sizeBits >= 2)
    require(immutableBase >= 0 && immutableBase % 8 == 0 && immutableBytes >= 8 && immutableBytes % 8 == 0)
    require(immutableBase + immutableBytes <= (BigInt(1) << 64))
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort)
        val tl = new TLBundle(params)
    })
    TLBundle.tieoffMasterCoherence(io.tl)
    io.tl.b.ready := false.B
    when(io.tl.b.valid) { assert(false.B, "instruction TileLink bridge cannot accept probes") }

    val active = RegInit(false.B)
    val heldResponse = RegInit(false.B)
    val heldData = Reg(UInt(64.W))
    val heldErrors = Reg(UInt(2.W))
    val alignedPc = Reg(UInt(64.W))
    val odd = Reg(Bool())
    val packetPc = Reg(UInt(64.W))
    val packetMask = Reg(UInt(2.W))
    val fullPacket = Reg(Bool())
    val packetGroup = RegInit(false.B)
    val nextGroup = RegInit(false.B)
    val sent = RegInit(VecInit(Seq.fill(2)(false.B)))
    val received = RegInit(VecInit(Seq.fill(2)(false.B)))
    val beats = Reg(Vec(2, UInt(64.W)))
    val beatGood = Reg(Vec(2, Bool()))
    val cacheValid = RegInit(false.B)
    val cacheAddress = Reg(UInt(64.W))
    val cacheData = Reg(UInt(64.W))
    val startLocked = RegInit(false.B)
    val lockedHit = Reg(Bool())
    val lockedData = Reg(UInt(64.W))
    val startAligned = Cat(io.fetch.request.bits(63, 3), 0.U(3.W))
    val startOdd = io.fetch.request.bits(2)
    val startMask = io.fetch.requestMask
    val startFull = startMask === 3.U
    def alignedInRom(address: UInt): Bool = {
        val lastByte = if (parallelAddresses) Cat(0.U(1.W), address(63, 3), 7.U(3.W))
            else address +& 7.U
        address >= immutableBase.U && lastByte < (immutableBase + immutableBytes).U(65.W)
    }
    val startInRom = alignedInRom(startAligned)
    val startCacheHit = Wire(Bool())
    val startCacheData = Wire(UInt(64.W))

    val issueOld = active && (!sent(0) || (odd && !sent(1)))
    val issueSecond = sent(0)
    io.tl.a.bits.opcode := TLOpcode.Get
    io.tl.a.bits.param := 0.U
    io.tl.a.bits.size := Mux(issueOld || startFull, 3.U, 2.U)
    io.tl.a.bits.source := Cat(Mux(issueOld, packetGroup, nextGroup),
        Mux(issueOld, issueSecond, Mux(startFull, startCacheHit, startMask(1))))
    if (parallelAddresses) {
        // Return/cache-hit qualification selects an already computed address;
        // it must not launch a new XLEN carry after the last D beat arrives.
        val oldNextAddress = alignedPc + 8.U
        val startNextAddress = startAligned + 8.U
        val partialNextAddress = io.fetch.request.bits + 4.U
        io.tl.a.bits.address := Mux(issueOld, Mux(issueSecond, oldNextAddress, alignedPc),
            Mux(startFull, Mux(startCacheHit, startNextAddress, startAligned),
                Mux(startMask(1), partialNextAddress, io.fetch.request.bits)))
    } else {
        io.tl.a.bits.address := Mux(issueOld, alignedPc + Mux(issueSecond, 8.U, 0.U),
            Mux(startFull, startAligned + Mux(startCacheHit, 8.U, 0.U),
                io.fetch.request.bits + Mux(startMask(1), 4.U, 0.U)))
    }
    io.tl.a.bits.mask := Mux(io.tl.a.bits.size === 3.U, 255.U,
        Mux(io.tl.a.bits.address(2), "hf0".U, "h0f".U))
    io.tl.a.bits.data := 0.U
    io.tl.a.bits.corrupt := false.B
    when(io.tl.a.fire && issueOld) { sent(issueSecond.asUInt) := true.B }

    val dSource = io.tl.d.bits.source
    val dIndex = dSource(0)
    val dInRange = dSource <= 3.U && dSource(1) === packetGroup
    io.tl.d.ready := active && dInRange && sent(dIndex) && !received(dIndex)
    when(io.tl.d.valid) {
        assert(active && dInRange && sent(dIndex) && !received(dIndex),
            "instruction TileLink response has no matching Get")
        assert(io.tl.d.bits.opcode === TLOpcode.AccessAckData && io.tl.d.bits.param === 0.U &&
            io.tl.d.bits.size === Mux(fullPacket, 3.U, 2.U),
            "instruction TileLink response opcode or size mismatch")
    }
    val d0Fire = io.tl.d.fire && dIndex === 0.U
    val d1Fire = io.tl.d.fire && dIndex === 1.U
    val dError = io.tl.d.bits.denied || io.tl.d.bits.corrupt
    val next0 = Mux(d0Fire, Mux(dError, 0.U, io.tl.d.bits.data), beats(0))
    val next1 = Mux(d1Fire, Mux(dError, 0.U, io.tl.d.bits.data), beats(1))
    val lastD = io.tl.d.fire && (received(0) || d0Fire) && (received(1) || d1Fire)
    val firstPartial = Mux(packetPc(2), next0(63, 32), next0(31, 0))
    val secondPartial = Mux(packetPc(2), next1(31, 0), next1(63, 32))
    val assembled = Mux(fullPacket, Mux(odd, Cat(next1(31, 0), next0(63, 32)), next0),
        Cat(Mux(packetMask(1), secondPartial, 0.U), Mux(packetMask(0), firstPartial, 0.U)))
    val firstError = Mux(d0Fire, dError, !beatGood(0))
    val secondError = Mux(d1Fire, dError, !beatGood(1))
    val assembledErrors = Mux(fullPacket, Cat(Mux(odd, secondError, firstError), firstError),
        Cat(!packetMask(1) || secondError, !packetMask(0) || firstError))
    val completedAddress = if (parallelAddresses) Mux(odd, alignedPc + 8.U, alignedPc)
        else alignedPc + Mux(odd, 8.U, 0.U)
    val completedData = Mux(odd, next1, next0)
    val completedGood = Mux(odd, Mux(d1Fire, !dError, beatGood(1)), Mux(d0Fire, !dError, beatGood(0)))
    val completedInRom = alignedInRom(completedAddress)
    val bypassHit = lastD && completedGood && completedInRom && completedAddress === startAligned
    val rawCacheHit = startFull && startOdd && startInRom &&
        (bypassHit || (cacheValid && cacheAddress === startAligned))
    startCacheHit := Mux(startLocked, lockedHit, rawCacheHit)
    startCacheData := Mux(startLocked, lockedData, Mux(bypassHit, completedData, cacheData))
    io.fetch.response.valid := heldResponse || lastD
    io.fetch.response.bits := Mux(heldResponse, heldData, assembled)
    io.fetch.responseError := Mux(heldResponse, heldErrors, assembledErrors)
    io.fetch.responsePageFault := 0.U
    val canStart = (!active || lastD) && (!heldResponse || io.fetch.response.ready) &&
        (!lastD || io.fetch.response.ready)
    io.tl.a.valid := issueOld || (canStart && io.fetch.request.valid && startMask.orR)
    io.fetch.request.ready := canStart && !issueOld && (!startMask.orR || io.tl.a.ready)
    when(!issueOld && io.tl.a.valid && !io.tl.a.ready) {
        startLocked := true.B
        lockedHit := startCacheHit
        lockedData := startCacheData
    }
    when(io.fetch.response.fire && heldResponse) { heldResponse := false.B }
    when(io.tl.d.fire) {
        beats(dIndex) := Mux(dError, 0.U, io.tl.d.bits.data)
        beatGood(dIndex) := !dError
        received(dIndex) := true.B
        when(lastD) {
            when(fullPacket) {
                cacheValid := completedGood && completedInRom
                cacheAddress := completedAddress
                cacheData := completedData
            }
            when(!io.fetch.response.ready) {
                heldResponse := true.B
                heldData := assembled
                heldErrors := assembledErrors
            }
            active := false.B
        }
    }
    when(io.fetch.request.fire) {
        assert(io.fetch.request.bits(1, 0) === 0.U, "instruction fetch PC must be 32-bit aligned")
        when(!startMask.orR) {
            heldResponse := true.B
            heldData := 0.U
            heldErrors := 3.U
        }.otherwise {
            alignedPc := startAligned
            odd := startOdd
            packetPc := io.fetch.request.bits
            packetMask := startMask
            fullPacket := startFull
            sent(0) := true.B
            sent(1) := !startFull || !startOdd || startCacheHit
            received(0) := Mux(startFull, startCacheHit, !startMask(0))
            received(1) := Mux(startFull, !startOdd, !startMask(1))
            beats(0) := startCacheData
            beats(1) := 0.U
            beatGood(0) := startFull && startCacheHit
            beatGood(1) := false.B
            startLocked := false.B
            packetGroup := nextGroup
            nextGroup := !nextGroup
            active := true.B
        }
    }
}

