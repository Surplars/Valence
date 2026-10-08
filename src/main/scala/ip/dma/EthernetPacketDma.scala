package soc.ip.dma

import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterArbiter, RegisterPort, RegisterResponse}

class EthernetAxisWord extends Bundle {
    val data = UInt(32.W)
    val keep = UInt(4.W)
    val last = Bool()
}

/** Simple, full-duplex store-and-forward DMA; NOT AXI DMA register/SG compatible.
  * Legacy single descriptors plus a bounded opt-in posted RX ownership queue.
  * Ordered memory credits remain independent of packet queue capacity.
  * 64-bit aligned buffers, arbitrary byte lengths <= maxFrameBytes. Frames are
  * staged in synchronous RAM before transmission / before any RX memory write.
  * RX data and six-word PG138 status can arrive in either relative order.
  * All ports here are single-clock: a wrapper must cross ALL four MAC streams.
  */
class EthernetPacketDma(base: BigInt = BigInt("10002000", 16),
    ramBase: BigInt = BigInt("80200000", 16), ramBytes: BigInt = BigInt(512) * 1024 * 1024,
    maxFrameBytes: Int = 2048, postedRxSlots: Int = 4, memoryCredits: Int = 4, postedTxSlots: Int = 0) extends Module {
    require(base >= 0 && base % 256 == 0 && base + 256 <= (BigInt(1) << 64))
    require(ramBase >= 0 && ramBase % 8 == 0 && ramBytes >= maxFrameBytes && ramBytes % 8 == 0 &&
        ramBase + ramBytes <= (BigInt(1) << 64))
    require(maxFrameBytes >= 64 && maxFrameBytes <= 16384 && isPow2(maxFrameBytes))
    require(postedRxSlots >= 1 && postedRxSlots <= 16 && isPow2(postedRxSlots))
    require(postedTxSlots == 0 || (postedTxSlots >= 1 && postedTxSlots <= 16 && isPow2(postedTxSlots)))
    require(memoryCredits >= 1 && memoryCredits <= 16 && isPow2(memoryCredits))
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val memory = new RegisterPort
        val txData = Decoupled(new EthernetAxisWord)
        val txControl = Decoupled(new EthernetAxisWord)
        val rxData = Flipped(Decoupled(new EthernetAxisWord))
        val rxStatus = Flipped(Decoupled(new EthernetAxisWord))
        val irq = Output(Bool())
        val active = Output(Bool())
    })
    private val words = maxFrameBytes / 8
    private val indexBits = log2Ceil(words)
    private val countBits = indexBits + 1
    val arbiter = Module(new RegisterArbiter(memoryCredits))
    io.memory <> arbiter.io.memory
    val tx = arbiter.io.clients(0)
    val rx = arbiter.io.clients(1)
    val txBuffer = SyncReadMem(words, UInt(64.W))
    val rxBuffer = SyncReadMem(words, UInt(64.W))
    val irqEnable = RegInit(0.U(2.W))
    val txAddress = RegInit(0.U(64.W))
    val txLength = RegInit(0.U(64.W))
    val rxAddress = RegInit(0.U(64.W))
    val rxCapacity = RegInit(0.U(64.W))
    // Posted RX ABI is additive; disabled at reset for existing Linux drivers.
    // A slot remains owned from POST through completion POP, so retained
    // completions can never be overwritten by new submissions.
    private val rxSlots = postedRxSlots
    private val slotBits = log2Ceil(rxSlots).max(1)
    private val ownerBits = log2Ceil(rxSlots + 1)
    private val queuedAddressBits = (ramBase + ramBytes - 1).bitLength.max(3)
    private val queuedCapacityBits = log2Ceil(maxFrameBytes + 1)
    val queueEnabled = RegInit(false.B)
    val queueStopped = RegInit(false.B)
    val postAddress = RegInit(0.U(64.W))
    val postCapacity = RegInit(0.U(64.W))
    val slotOwned = RegInit(VecInit(Seq.fill(rxSlots)(false.B)))
    // POST validation proves bounded, eight-byte-aligned physical addresses.
    // Retain only their significant word bits; the MMIO ABI remains full64.
    val queuedAddressWords = Reg(Vec(rxSlots, UInt((queuedAddressBits - 3).W)))
    val queuedAddress = Wire(Vec(rxSlots, UInt(queuedAddressBits.W)))
    for (i <- 0 until rxSlots) { queuedAddress(i) := Cat(queuedAddressWords(i), 0.U(3.W)) }
    val queuedCapacity = Reg(Vec(rxSlots, UInt(queuedCapacityBits.W)))
    val completedMetadata = Reg(Vec(rxSlots, UInt(17.W)))
    val postIndex = RegInit(0.U(slotBits.W))
    val launchIndex = RegInit(0.U(slotBits.W))
    val completionIndex = RegInit(0.U(slotBits.W))
    val activeIndex = Reg(UInt(slotBits.W))
    val queueActive = RegInit(false.B)
    val ownedCount = RegInit(0.U(ownerBits.W))
    val pendingCount = RegInit(0.U(ownerBits.W))
    val completedCount = RegInit(0.U(ownerBits.W))
    val post = WireDefault(false.B)
    val consumePending = WireDefault(false.B)
    val complete = WireDefault(false.B)
    val pop = WireDefault(false.B)
    when(post =/= pop) { ownedCount := Mux(post, ownedCount + 1.U, ownedCount - 1.U) }
    when(post =/= consumePending) {
        pendingCount := Mux(post, pendingCount + 1.U, pendingCount - 1.U)
    }
    when(complete =/= pop) {
        completedCount := Mux(complete, completedCount + 1.U, completedCount - 1.U)
    }
    val txDone = RegInit(false.B)
    val txFailed = RegInit(false.B)
    val rxDone = RegInit(false.B)
    val rxFailed = RegInit(false.B)
    val txIdle :: txFill :: txControlState :: txLoad :: txWait :: txEmit :: Nil = Enum(6)
    val txState = RegInit(txIdle)
    val rxIdle :: rxCollect :: rxLoad :: rxWait :: rxOffer :: rxDrain :: Nil = Enum(6)
    val rxState = RegInit(rxIdle)
    val txQueue = if (postedTxSlots > 0) Some(Module(new EthernetTxDescriptorQueue(
        postedTxSlots, ramBase, ramBytes, maxFrameBytes))) else None
    val txQueueEnabled = txQueue.map(_.io.enabled).getOrElse(false.B)
    val txBusy = txState =/= txIdle
    val rxBusy = rxState =/= rxIdle
    io.active := txQueue.map(_.io.work).getOrElse(false.B) || txBusy || rxBusy || queueActive || (queueEnabled && pendingCount =/= 0.U)
    io.irq := (irqEnable(0) && Mux(txQueueEnabled, txQueue.map(_.io.irq).getOrElse(false.B), txDone)) || (irqEnable(1) && Mux(queueEnabled, completedCount =/= 0.U, rxDone))

    // TX prefetch: errors drain accepted/held reads; no partial frame reaches MAC.
    val txSent = RegInit(0.U(countBits.W))
    val txReceived = RegInit(0.U(countBits.W))
    val txLocked = RegInit(false.B)
    val txWordCount = ((txLength + 7.U) >> 3)(countBits - 1, 0)
    tx.request.valid := txState === txFill && (txLocked || !txFailed) &&
        txSent < txWordCount && txSent - txReceived < memoryCredits.U
    tx.request.bits.address := txAddress + (txSent << 3)
    tx.request.bits.write := false.B
    tx.request.bits.size := 3.U
    tx.request.bits.data := 0.U
    tx.request.bits.byteEnable := 255.U
    tx.response.ready := txState === txFill
    when(tx.request.valid && !tx.request.ready) { txLocked := true.B }
    when(tx.request.fire) { txSent := txSent + 1.U; txLocked := false.B }
    when(tx.response.fire) {
        txBuffer.write(txReceived(indexBits - 1, 0), tx.response.bits.data)
        txReceived := txReceived + 1.U
        when(tx.response.bits.error) { txFailed := true.B }
    }
    val controlIndex = RegInit(0.U(3.W))
    io.txControl.valid := txState === txControlState
    io.txControl.bits.data := Mux(controlIndex === 0.U, "ha0000000".U, 0.U)
    io.txControl.bits.keep := 15.U
    io.txControl.bits.last := controlIndex === 5.U
    when(txState === txFill && !txLocked && txReceived === txSent &&
        (txFailed || txReceived === txWordCount)) {
        when(txFailed) { txState := txIdle; txDone := true.B }
            .otherwise { txState := txControlState; controlIndex := 0.U }
    }
    val txIndex = RegInit(0.U(indexBits.W))
    val txBytes = RegInit(0.U(log2Ceil(maxFrameBytes + 1).W))
    val txUpper = RegInit(false.B)
    val txWord = Reg(UInt(64.W))
    val txRead = txBuffer.read(txIndex, txState === txLoad)
    when(io.txControl.fire) {
        when(controlIndex === 5.U) {
            txState := txLoad; txIndex := 0.U; txBytes := 0.U; txUpper := false.B
        }.otherwise { controlIndex := controlIndex + 1.U }
    }
    when(txState === txLoad) { txState := txWait }
    when(txState === txWait) { txWord := txRead; txState := txEmit }
    val txRemaining = txLength - txBytes
    io.txData.valid := txState === txEmit
    io.txData.bits.data := Mux(txUpper, txWord(63, 32), txWord(31, 0))
    io.txData.bits.keep := Mux(txRemaining >= 4.U, 15.U,
        ((1.U(5.W) << txRemaining(1, 0)) - 1.U)(3, 0))
    io.txData.bits.last := txRemaining <= 4.U
    when(io.txData.fire) {
        txBytes := txBytes + 4.U
        when(io.txData.bits.last) { txState := txIdle; txDone := true.B }
            .elsewhen(!txUpper) { txUpper := true.B }
            .otherwise { txUpper := false.B; txIndex := txIndex + 1.U; txState := txLoad }
    }

    // RX is independently armed. Never consume the next frame before software
    // acknowledges completion and installs a buffer. Malformed frames are drained.
    val rxBytes = RegInit(0.U(17.W))
    val rxDataDone = RegInit(false.B)
    val rxStatusDone = RegInit(false.B)
    val rxStatusIndex = RegInit(0.U(3.W))
    val statusWords = RegInit(VecInit(Seq.fill(6)(0.U(32.W))))
    val rxLow = Reg(UInt(32.W))
    val rxUpper = RegInit(false.B)
    val rxCaptureIndex = RegInit(0.U(indexBits.W))
    io.rxData.ready := rxState === rxCollect && !rxDataDone
    io.rxStatus.ready := rxState === rxCollect && !rxStatusDone
    val keep = io.rxData.bits.keep
    val keepLegal = keep === 1.U || keep === 3.U || keep === 7.U || keep === 15.U
    val rxNextBytes = rxBytes +& PopCount(keep)
    when(io.rxData.fire) {
        rxBytes := Mux(rxNextBytes > 65535.U, 65535.U, rxNextBytes)
        when(!keepLegal || (!io.rxData.bits.last && keep =/= 15.U) ||
            rxNextBytes > rxCapacity || rxNextBytes > maxFrameBytes.U) { rxFailed := true.B }
        when(rxNextBytes <= maxFrameBytes.U) {
            when(rxUpper || io.rxData.bits.last) {
                rxBuffer.write(rxCaptureIndex, Mux(rxUpper,
                    Cat(io.rxData.bits.data, rxLow), Cat(0.U(32.W), io.rxData.bits.data)))
                rxCaptureIndex := rxCaptureIndex + 1.U
            }.otherwise { rxLow := io.rxData.bits.data }
        }
        rxUpper := !rxUpper
        when(io.rxData.bits.last) { rxDataDone := true.B }
    }
    when(io.rxStatus.fire) {
        when(rxStatusIndex < 6.U) { statusWords(rxStatusIndex) := io.rxStatus.bits.data }
        when(io.rxStatus.bits.keep =/= 15.U || rxStatusIndex > 5.U ||
            (rxStatusIndex === 0.U && io.rxStatus.bits.data(31, 28) =/= 5.U) ||
            (io.rxStatus.bits.last =/= (rxStatusIndex === 5.U))) { rxFailed := true.B }
        when(io.rxStatus.bits.last) { rxStatusDone := true.B }
        when(rxStatusIndex < 6.U) { rxStatusIndex := rxStatusIndex + 1.U }
    }
    val rxIssued = RegInit(0.U(countBits.W))
    val rxReplied = RegInit(0.U(countBits.W))
    val rxStoreIndex = RegInit(0.U(indexBits.W))
    val rxWord = Reg(UInt(64.W))
    val rxRead = rxBuffer.read(rxStoreIndex, rxState === rxLoad && !rxFailed)
    val rxRemaining = rxBytes - (rxStoreIndex << 3)
    val rxMask = Mux(rxRemaining >= 8.U, 255.U,
        ((1.U(9.W) << rxRemaining(2, 0)) - 1.U)(7, 0))
    rx.request.valid := rxState === rxOffer && rxIssued - rxReplied < memoryCredits.U
    rx.request.bits.address := rxAddress + (rxStoreIndex << 3)
    rx.request.bits.write := true.B
    rx.request.bits.size := 3.U
    rx.request.bits.data := rxWord
    rx.request.bits.byteEnable := rxMask
    rx.response.ready := rxState =/= rxIdle && rxState =/= rxCollect
    when(rx.response.fire) {
        rxReplied := rxReplied + 1.U
        when(rx.response.bits.error) { rxFailed := true.B }
    }
    when(rxState === rxCollect && rxDataDone && rxStatusDone) {
        val frameBad = rxFailed || rxBytes === 0.U || statusWords(5)(15, 0) =/= rxBytes ||
            !statusWords(3)(6) || statusWords(3)(7) || statusWords(3)(8)
        when(frameBad) { rxState := rxIdle; rxDone := true.B; rxFailed := true.B }
            .otherwise { rxState := rxLoad }
    }
    when(rxState === rxLoad) { rxState := Mux(rxFailed, rxDrain, rxWait) }
    when(rxState === rxWait) { rxWord := rxRead; rxState := Mux(rxFailed, rxDrain, rxOffer) }
    when(rx.request.fire) {
        rxIssued := rxIssued + 1.U
        when(rxFailed || rxRemaining <= 8.U) { rxState := rxDrain }
            .otherwise { rxStoreIndex := rxStoreIndex + 1.U; rxState := rxLoad }
    }
    when(rxState === rxDrain && rxIssued === rxReplied) { rxState := rxIdle; rxDone := true.B }

    // Register ABI V1. Full-width accesses only; descriptor mutation while active
    // and completion overwrite are rejected. W1C acknowledgements precede starts.
    val replies = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    val r = io.control.request.bits
    val offset = r.address - base.U
    // Additive ABI: 0x90 RX_STOP=1; 0x98 bit 0 advertises safe RX stop.
    // Accepted memory requests are NEVER cancelled. A partly captured frame is
    // drained to both stream boundaries, then discarded without new DDR writes.
    val rxStop = offset === 144.U
    val known = Seq(0, 8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96, 104, 112, 120, 128, 136,
        144, 152, 160, 168, 176, 184, 192, 200, 208, 216)
        .map(n => offset === n.U).reduce(_ || _)
    val txWrite = offset === 16.U || offset === 24.U || offset === 32.U
    val txQueueKnown = txQueue.map(_.io.known).getOrElse(false.B)
    val txQueueAllowed = txQueue.map(_.io.allowed).getOrElse(false.B)
    val rxWrite = offset === 48.U || offset === 56.U || offset === 64.U
    val queueWrite = offset === 160.U || offset === 168.U || offset === 176.U ||
        offset === 184.U || offset === 216.U
    val queueEmpty = !rxBusy && !rxDone && !queueActive && ownedCount === 0.U
    val overlapsOwned = (0 until rxSlots).map { i =>
        slotOwned(i) && postAddress < (queuedAddress(i) +& queuedCapacity(i)) &&
            queuedAddress(i) < (postAddress +& postCapacity)
    }.reduce(_ || _)
    val writable = offset === 8.U || txWrite || rxWrite || rxStop || queueWrite || txQueueKnown
    val legal = r.address >= base.U && r.address < (base + 256).U(65.W) && (known || txQueueKnown) &&
        r.size === 3.U && r.byteEnable === 255.U &&
        (!r.write || (writable && (!txWrite || (!txBusy && !txQueueEnabled)) && (!rxWrite || (!rxBusy && !queueEnabled)) &&
            !(offset === 32.U && r.data(0) && txDone && !r.data(1)) &&
            !(offset === 64.U && r.data(0) && rxDone && !r.data(1)) &&
            (!rxStop || r.data === 1.U) &&
            (offset =/= 176.U || (r.data === 1.U && queueEnabled && !queueStopped &&
                ownedCount < rxSlots.U && !overlapsOwned && descriptorLegal(postAddress, postCapacity))) &&
            (offset =/= 184.U || (r.data <= 1.U && queueEmpty)) &&
            (offset =/= 216.U || (r.data === 1.U && queueEnabled && completedCount =/= 0.U)) &&
            (!txQueueKnown || txQueueAllowed)))
    io.control.request.ready := replies.io.enq.ready
    replies.io.enq.valid := io.control.request.valid
    replies.io.enq.bits.error := !legal
    replies.io.enq.bits.data := Mux(legal && !r.write, MuxLookup(offset, 0.U(64.W))(Seq(
        0.U -> "h56444d4100010001".U(64.W), 8.U -> irqEnable,
        16.U -> txAddress, 24.U -> txLength, 40.U -> Cat(txFailed, txDone, txBusy),
        48.U -> rxAddress, 56.U -> rxCapacity, 72.U -> Cat(rxFailed, rxDone, rxBusy),
        80.U -> rxBytes, 136.U -> maxFrameBytes.U, 152.U -> ((BigInt(postedTxSlots) << 24) | (memoryCredits << 16) | (rxSlots << 8) |
            (if (postedTxSlots > 0) 7 else 3)).U,
        160.U -> postAddress, 168.U -> postCapacity, 184.U -> queueEnabled,
        192.U -> (pendingCount | (completedCount << 8) | (queueActive.asUInt << 16) |
            (queueStopped.asUInt << 17)),
        200.U -> Mux(completedCount =/= 0.U, queuedAddress(completionIndex), 0.U),
        208.U -> Mux(completedCount =/= 0.U, completedMetadata(completionIndex), 0.U)
    ) ++ Seq(224, 232, 240, 248).map(n => n.U -> txQueue.map(_.io.readData).getOrElse(0.U)) ++ (0 until 6).map(i => (88 + i * 8).U -> statusWords(i))), 0.U)
    io.control.response <> replies.io.deq
    txQueue.foreach { q =>
        q.io.offset := offset(7, 0); q.io.data := r.data; q.io.accessWrite := r.write
        q.io.write := io.control.request.fire && legal && r.write && q.io.known
        q.io.engineIdle := !txBusy && !txDone
        q.io.engineDone := txDone && !txBusy
        q.io.engineFailed := txFailed; q.io.engineBytes := Mux(txFailed, 0.U, txLength(15, 0))
        when(q.io.consumeDone) { txDone := false.B; txFailed := false.B }
        when(q.io.launch.valid) {
            txAddress := q.io.launch.bits.address; txLength := q.io.launch.bits.length
            txState := txFill; txDone := false.B; txFailed := false.B
            txSent := 0.U; txReceived := 0.U; txLocked := false.B; txBytes := 0.U
        }
    }

    def descriptorLegal(address: UInt, length: UInt): Bool = {
        val rounded = (length +& 7.U) & ~7.U(65.W)
        address(2, 0) === 0.U && address >= ramBase.U(65.W) && length =/= 0.U &&
            length <= maxFrameBytes.U && (address +& rounded) <= (ramBase + ramBytes).U(66.W)
    }
    when(io.control.request.fire && legal && r.write) {
        switch(offset) {
            is(160.U) { postAddress := r.data }
            is(168.U) { postCapacity := r.data }
            is(176.U) {
                slotOwned(postIndex) := true.B
                queuedAddressWords(postIndex) := postAddress(queuedAddressBits - 1, 3)
                queuedCapacity(postIndex) := postCapacity(queuedCapacityBits - 1, 0)
                postIndex := (if (rxSlots == 1) 0.U else postIndex + 1.U)
                post := true.B
            }
            is(184.U) {
                queueEnabled := r.data(0)
                queueStopped := false.B
                postIndex := 0.U; launchIndex := 0.U; completionIndex := 0.U
            }
            is(216.U) {
                pop := true.B; slotOwned(completionIndex) := false.B
                completionIndex := (if (rxSlots == 1) 0.U else completionIndex + 1.U)
            }
            is(144.U) {
                when(queueEnabled) { queueStopped := true.B }
                when(rxBusy) {
                    rxFailed := true.B
                    when(rxState === rxCollect && rxBytes === 0.U && rxStatusIndex === 0.U &&
                        !rxDataDone && !rxStatusDone && !io.rxData.valid && !io.rxStatus.valid) {
                        rxState := rxIdle; rxDone := true.B
                    }.elsewhen(rxState === rxLoad || rxState === rxWait ||
                        (rxState === rxOffer && (!rx.request.valid || rx.request.fire))) {
                        rxState := rxDrain
                    }
                    // A valid held rxOffer retains payload; a credit-blocked (invalid)
                    // offer has no external owner and may stop without issuing it.
                    // rxCollect with any received/offered beat retains ready and
                    // drains data + status; rxFailed suppresses the memory phase.
                }
            }
            is(8.U) { irqEnable := r.data(1, 0) }
            is(16.U) { txAddress := r.data }
            is(24.U) { txLength := r.data }
            is(48.U) { rxAddress := r.data }
            is(56.U) { rxCapacity := r.data }
            is(32.U) {
                when(r.data(1)) { txDone := false.B; txFailed := false.B }
                when(r.data(0)) {
                    val valid = descriptorLegal(txAddress, txLength)
                    txState := Mux(valid, txFill, txIdle); txDone := !valid; txFailed := !valid
                    txSent := 0.U; txReceived := 0.U; txLocked := false.B
                }
            }
            is(64.U) {
                when(r.data(1)) { rxDone := false.B; rxFailed := false.B }
                when(r.data(0)) {
                    val valid = descriptorLegal(rxAddress, rxCapacity)
                    rxState := Mux(valid, rxCollect, rxIdle); rxDone := !valid; rxFailed := !valid
                    rxBytes := 0.U; rxDataDone := false.B; rxStatusDone := false.B
                    rxStatusIndex := 0.U; rxUpper := false.B; rxCaptureIndex := 0.U
                    rxIssued := 0.U; rxReplied := 0.U
                    rxStoreIndex := 0.U
                    statusWords.foreach(_ := 0.U)
                }
            }
        }
    }
    // Publish completion only after both frame streams and all accepted DDR
    // responses have retired. Firmware's consume fence precedes payload reads.
    when(queueEnabled && queueActive && rxDone && !rxBusy) {
        completedMetadata(activeIndex) := rxBytes(15, 0) | (rxFailed.asUInt << 16)
        complete := true.B
        queueActive := false.B
        rxDone := false.B
        rxFailed := false.B
    }
    // Stop wins over launches in the very cycle its MMIO write is accepted.
    val stopping = queueStopped || (io.control.request.fire && legal && r.write && rxStop)
    when(queueEnabled && !queueActive && !rxBusy && !rxDone && pendingCount =/= 0.U) {
        consumePending := true.B
        launchIndex := (if (rxSlots == 1) 0.U else launchIndex + 1.U)
        when(stopping) {
            completedMetadata(launchIndex) := (1 << 16).U // cancelled before capture
            complete := true.B
        }.otherwise {
            rxAddress := queuedAddress(launchIndex)
            rxCapacity := queuedCapacity(launchIndex)
            activeIndex := launchIndex
            queueActive := true.B
            rxState := rxCollect
            rxDone := false.B; rxFailed := false.B
            rxBytes := 0.U; rxDataDone := false.B; rxStatusDone := false.B
            rxStatusIndex := 0.U; rxUpper := false.B; rxCaptureIndex := 0.U
            rxIssued := 0.U; rxReplied := 0.U; rxStoreIndex := 0.U
            statusWords.foreach(_ := 0.U)
        }
    }
    assert(ownedCount === PopCount(slotOwned))
    assert(ownedCount <= rxSlots.U)
    assert(ownedCount === pendingCount +& completedCount + queueActive.asUInt)
    assert(!queueActive || queueEnabled)
    assert(txSent >= txReceived && txSent - txReceived <= memoryCredits.U)
    assert(rxIssued >= rxReplied && rxIssued - rxReplied <= memoryCredits.U)
}
