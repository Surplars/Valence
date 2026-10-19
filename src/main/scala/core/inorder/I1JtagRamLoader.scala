// I1-local timing specialization. Shared/OoO JtagRamLoader remains unchanged.
package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterPort, RegisterRequest}
import soc.ip.debug.{DebugDmiPort, DmiResponse}

/** Boot-only RAM loader, deliberately NOT a RISC-V Debug Module.
  * Standard DTM/DMI transport and SBA register layout are usable with raw OpenOCD
  * scans; dmstatus.version=0 truthfully rejects native RISC-V target examination.
  * One 32-bit operation at a time, no bursts. A presented bus request is an
  * obligation even before ready: abort/timeout/link reset never drops its owner.
  */
class I1JtagRamLoader(ramBase: BigInt, ramEnd: BigInt,
    controlBase: BigInt = BigInt("10003000", 16), timeoutCycles: Int = 1000000,
    timingCuts: Boolean = false) extends Module {
    require(ramBase >= 0 && ramBase % 4 == 0 && ramEnd % 4 == 0 && ramEnd > ramBase && ramEnd < (BigInt(1) << 32))
    require(timeoutCycles >= 4)
    val io = IO(new Bundle {
        val dmi = Flipped(new DebugDmiPort(7))
        // Synchronously released DTM interface reset, NOT the bus-owner reset.
        val linkUp = Input(Bool())
        val control = Flipped(new RegisterPort)
        val memory = new RegisterPort
    })
    val armed = RegInit(false.B)
    val committed = RegInit(false.B)
    val cancelled = RegInit(false.B)
    val fault = RegInit(false.B)
    val claimed = RegInit(false.B)
    private val generationWord = new I1LoaderPreparedWord(timingCuts)
    val generation = generationWord.value
    // Host token binds COMMIT atomically across CPU abort/re-arm.
    private val expectedGenerationWord = new I1LoaderPreparedWord(timingCuts)
    val expectedGeneration = expectedGenerationWord.value
    val expectedGenerationValid = RegInit(false.B)
    private val entryWord = new I1LoaderPreparedWord(timingCuts)
    val entry = entryWord.value
    private val lengthWord = new I1LoaderPreparedWord(timingCuts)
    val length = lengthWord.value
    private val crcWord = new I1LoaderPreparedWord(timingCuts)
    val crc = crcWord.value
    private val addressWord = new I1LoaderPreparedWord(timingCuts)
    val address = addressWord.value
    private val dataWord = new I1LoaderPreparedWord(timingCuts)
    val data = dataWord.value
    val access = RegInit(2.U(3.W))
    val readOnAddress = RegInit(false.B)
    val readOnData = RegInit(false.B)
    val autoIncrement = RegInit(false.B)
    val sbError = RegInit(0.U(3.W))
    val busyError = RegInit(false.B)
    val offered = RegInit(false.B)
    val awaiting = RegInit(false.B)
    val pending = Reg(new RegisterRequest)
    val pendingIncrement = Reg(Bool())
    val ticks = RegInit(0.U(log2Ceil(timeoutCycles + 1).W))
    val timedOut = RegInit(false.B)
    val busy = offered || awaiting
    val status = Cat(claimed, io.linkUp, fault, busy, cancelled, committed, armed)
    val sbcs = (1.U(32.W) << 29) | (busyError.asUInt << 22) | (busy.asUInt << 21) |
        (readOnAddress.asUInt << 20) | (access << 17) | (autoIncrement.asUInt << 16) |
        (readOnData.asUInt << 15) | (sbError << 12) | (32.U(32.W) << 5) | 4.U

    io.memory.request.valid := offered
    io.memory.request.bits := pending
    io.memory.response.ready := awaiting
    when(io.memory.request.fire) { offered := false.B; awaiting := true.B }
    when(busy && !timedOut) {
        when(ticks === (timeoutCycles - 1).U) {
            timedOut := true.B; sbError := 1.U; fault := true.B
            armed := false.B; committed := false.B; cancelled := true.B
        }.otherwise { ticks := ticks + 1.U }
    }
    when(io.memory.response.fire) {
        awaiting := false.B
        when(io.memory.response.bits.error) {
            sbError := 7.U; fault := true.B; armed := false.B; committed := false.B; cancelled := true.B
        }.elsewhen(!timedOut && armed && io.linkUp) {
            when(!pending.write) { dataWord.load := true.B }
            when(pendingIncrement) { addressWord.load := true.B }
        }
    }

    // Trigger while error latched is a no-op, as for SBA. Busy access is sticky.
    def startMemory(write: Bool, at: UInt, value: UInt): Unit = {
        when(busy) { if (!timingCuts) busyError := true.B }
        .elsewhen(sbError === 0.U && !busyError) {
            when(!armed || committed || claimed || !io.linkUp) { if (!timingCuts) sbError := 7.U }
            .elsewhen(access =/= 2.U) { if (!timingCuts) sbError := 4.U }
            .elsewhen(at(1, 0) =/= 0.U) { if (!timingCuts) sbError := 3.U }
            .elsewhen(if (timingCuts) !I1AddressWindow.contains(at, ramBase, ramEnd - ramBase)
                else at < ramBase.U || (at +& 4.U) > ramEnd.U(33.W)) {
                if (!timingCuts) sbError := 2.U
            }
            .otherwise {
                offered := true.B; ticks := 0.U; timedOut := false.B
                pending.address := at; pending.write := write; pending.size := 2.U
                pending.data := value; pending.byteEnable := 15.U
                pendingIncrement := autoIncrement
            }
        }
    }

    val controlValid = RegInit(false.B)
    val controlData = RegInit(0.U(64.W))
    val controlError = RegInit(false.B)
    io.control.request.ready := !controlValid
    io.control.response.valid := controlValid
    io.control.response.bits.data := controlData
    io.control.response.bits.error := controlError
    when(io.control.response.fire) { controlValid := false.B }
    val c = io.control.request.bits
    // Aligned constant windows need only an equality tree and low offset
    // bits, not a 64-bit subtract/compare before every loader control CE.
    val offset = if (timingCuts && controlBase % 64 == 0) c.address(5, 0)
        else c.address - controlBase.U
    val command = c.data(31, 0)
    val openLegal = command === 1.U && c.data(63, 32) === 0.U && !busy && !claimed && io.linkUp
    val closeLegal = command === 2.U && c.data(63, 32) === 0.U && !claimed
    val claimLegal = command === 3.U && c.data(63, 32) === generation && committed && !busy &&
        !fault && !claimed && io.linkUp
    val inControl = if (timingCuts) I1AddressWindow.contains(c.address, controlBase, 64)
        else c.address >= controlBase.U && c.address < (controlBase + 64).U
    val controlLegal = inControl &&
        offset(2, 0) === 0.U && c.size === 3.U && c.byteEnable === 255.U &&
        (!c.write || (offset === 8.U && (openLegal || closeLegal || claimLegal)))
    when(io.control.request.fire) {
        controlValid := true.B; controlError := !controlLegal
        controlData := Mux(controlLegal && !c.write, MuxLookup(offset, 0.U)(Seq(
            0.U -> status, 16.U -> entry, 24.U -> length, 32.U -> crc,
            40.U -> generation, 48.U -> ramBase.U, 56.U -> ramEnd.U)), 0.U)
    }

    val responseValid = RegInit(false.B)
    val response = Reg(new DmiResponse)
    io.dmi.request.ready := io.linkUp && !responseValid && !(io.control.request.fire && c.write)
    io.dmi.response.valid := responseValid && io.linkUp
    io.dmi.response.bits := response
    when(io.dmi.response.fire) { responseValid := false.B }
    val r = io.dmi.request.bits
    // Payload preparation does not depend on late transport linkUp or actual
    // request acceptance. Only a one-bit commit selects these freshly written
    // bytes. A dropped link never authorizes a DMI/CPU command or drops memory.
    generationWord.candidate := generation + 1.U
    expectedGenerationWord.candidate := r.data
    entryWord.candidate := r.data
    lengthWord.candidate := r.data
    crcWord.candidate := r.data
    addressWord.candidate := Mux(awaiting && pendingIncrement,
        pending.address(31, 0) + 4.U, r.data)
    dataWord.candidate := Mux(awaiting && !pending.write,
        io.memory.response.bits.data(31, 0), r.data)
    val read = r.op === 1.U
    val write = r.op === 2.U
    val roundedLength = (length +& 3.U) & "h1fffffffc".U(33.W)
    val logicalEnd = ramBase.U(33.W) +& length
    val metadataLegal = length =/= 0.U && (ramBase.U(34.W) + roundedLength) <= ramEnd.U(34.W) &&
        entry(1, 0) === 0.U && entry >= ramBase.U && entry < logicalEnd
    // Decode error data from the retained DMI payload and local state before
    // the transport's falling-edge link/VALID permission arrives. Only the
    // final scalar write enable depends on acceptance. Link-down still bars
    // every request immediately; no link-up register or extra DMI edge.
    val configClear = write && r.address === "h38".U && !busy
    val addressAccess = r.address === "h39".U
    val dataAccess = r.address === "h3c".U
    val memoryTrigger = (addressAccess && write && readOnAddress) ||
        (dataAccess && (write || (read && readOnData)))
    val memoryAddress = Mux(addressAccess, r.data, address)
    val invalidSession = !armed || committed || claimed
    val invalidSize = access =/= 2.U
    val invalidAlignment = memoryAddress(1, 0) =/= 0.U
    val invalidWindow = !I1AddressWindow.contains(memoryAddress, ramBase, ramEnd - ramBase)
    val memoryError = memoryTrigger && !busy && sbError === 0.U && !busyError &&
        (invalidSession || invalidSize || invalidAlignment || invalidWindow)
    val memoryErrorCode = Mux(invalidSession, 7.U, Mux(invalidSize, 4.U,
        Mux(invalidAlignment, 3.U, 2.U)))
    when(io.dmi.request.fire) {
        responseValid := true.B; response.status := 0.U; response.data := 0.U
        when(!(read || write)) { response.status := 2.U }
        .otherwise {
            if (timingCuts) {
                when(configClear || memoryError) {
                    sbError := Mux(configClear, sbError & ~r.data(14, 12), memoryErrorCode)
                }
                when(configClear || ((addressAccess || dataAccess) && busy)) {
                    busyError := Mux(busy, true.B, busyError && !r.data(22))
                }
            }
            switch(r.address) {
                is("h10".U) { when(write && r.data =/= 0.U) { response.status := 2.U } }
                is("h11".U) { when(write) { response.status := 2.U } } // version=0, no DM
                is("h38".U) {
                    when(read) { response.data := sbcs }
                    .elsewhen(!busy) {
                        if (!timingCuts) {
                            busyError := busyError && !r.data(22)
                            sbError := sbError & ~r.data(14, 12)
                        }
                        readOnAddress := r.data(20); access := r.data(19, 17)
                        autoIncrement := r.data(16); readOnData := r.data(15)
                    }
                }
                is("h39".U) {
                    when(busy) { if (!timingCuts) busyError := true.B }
                    .elsewhen(read) { response.data := address }
                    .otherwise {
                        addressWord.load := true.B
                        when(readOnAddress) { startMemory(false.B, r.data, 0.U) }
                    }
                }
                is("h3c".U) {
                    when(busy) { if (!timingCuts) busyError := true.B }
                    .elsewhen(read) {
                        response.data := data
                        when(readOnData) { startMemory(false.B, address, 0.U) }
                    }.otherwise { dataWord.load := true.B; startMemory(true.B, address, r.data) }
                }
                is("h40".U) { when(read) { response.data := "h564c0101".U }.otherwise { response.status := 2.U } }
                is("h41".U) { when(read) { response.data := status }.otherwise { response.status := 2.U } }
                is("h42".U) {
                    when(!write) { response.status := 2.U }
                    .elsewhen(r.data === 1.U && !claimed) {
                        armed := false.B; committed := false.B; cancelled := true.B
                    }.elsewhen(r.data === 2.U && armed && !busy && sbError === 0.U && !busyError &&
                        !fault && metadataLegal && !claimed && expectedGenerationValid && expectedGeneration === generation) { armed := false.B; committed := true.B }
                    .otherwise { response.status := 2.U }
                }
                is("h43".U) {
                    when(read) { response.data := entry }
                    .elsewhen(armed && !busy) { entryWord.load := true.B }.otherwise { response.status := 2.U }
                }
                is("h44".U) {
                    when(read) { response.data := length }
                    .elsewhen(armed && !busy) { lengthWord.load := true.B }.otherwise { response.status := 2.U }
                }
                is("h45".U) {
                    when(read) { response.data := crc }
                    .elsewhen(armed && !busy) { crcWord.load := true.B }.otherwise { response.status := 2.U }
                }
                is("h46".U) { when(read) { response.data := generation }.otherwise { response.status := 2.U } }
                is("h47".U) { when(read) { response.data := ramBase.U }.otherwise { response.status := 2.U } }
                is("h48".U) { when(read) { response.data := ramEnd.U }.otherwise { response.status := 2.U } }
                is("h49".U) {
                    when(read) { response.data := expectedGeneration }
                    .elsewhen(armed && !busy) { expectedGenerationWord.load := true.B; expectedGenerationValid := true.B }
                    .otherwise { response.status := 2.U }
                }
            }
            when(!Seq(0x10, 0x11, 0x38, 0x39, 0x3c, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49)
                .map(n => r.address === n.U).reduce(_ || _)) { response.status := 2.U }
        }
    }
    // CPU ownership commands take priority, and bar simultaneous DMI acceptance.
    when(io.control.request.fire && controlLegal && c.write) {
        when(openLegal) {
            armed := true.B; committed := false.B; cancelled := false.B; fault := false.B
            generationWord.load := true.B; expectedGenerationWord.clear := true.B; expectedGenerationValid := false.B
            entryWord.clear := true.B; lengthWord.clear := true.B; crcWord.clear := true.B
            addressWord.clear := true.B; dataWord.clear := true.B; access := 2.U; readOnAddress := false.B
            readOnData := false.B; autoIncrement := false.B; sbError := 0.U; busyError := false.B
            timedOut := false.B; ticks := 0.U
        }.elsewhen(closeLegal) { armed := false.B; committed := false.B; cancelled := true.B }
        .elsewhen(claimLegal) { armed := false.B; committed := false.B; claimed := true.B }
    }
    when(!io.linkUp) {
        responseValid := false.B
        armed := false.B; committed := false.B
        when(!claimed) { cancelled := true.B }
    }
    assert(!(offered && awaiting), "RAM loader has multiple bus owners")
    assert(!(armed && (committed || claimed)), "RAM loader ownership overlaps launch")
}

/** Two unowned payload banks, ONE architectural word and no request owner.
  * The free bank writes every edge, independent of late link permission.
  * An accepted write flips only the selector; OPEN changes only the zero bit.
  * CLEAR has the same priority as the original later CPU OPEN assignment.
  */
private class I1LoaderPreparedWord(timingCuts: Boolean) {
    val candidate = WireDefault(0.U(32.W))
    val load = WireDefault(false.B)
    val clear = WireDefault(false.B)
    val value = Wire(UInt(32.W))
    if (timingCuts) {
        val banks = Reg(Vec(2, UInt(32.W)))
        val selected = RegInit(false.B)
        val zero = RegInit(true.B)
        when(selected) { banks(0) := candidate }.otherwise { banks(1) := candidate }
        when(load) { selected := !selected; zero := false.B }
        when(clear) { zero := true.B }
        value := Mux(zero, 0.U, Mux(selected, banks(1), banks(0)))
    } else {
        val stored = RegInit(0.U(32.W))
        when(load) { stored := candidate }
        when(clear) { stored := 0.U }
        value := stored
    }
}
