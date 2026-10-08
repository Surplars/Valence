package soc.ip.ethernet

import chisel3._
import chisel3.util._
import soc.ip.bus._

/** Pack uninterrupted physical bytes (including preamble/FCS) into four-byte
  * tokens. An explicit LAST produces an idle delimiter at the sink. PHY input
  * is never backpressured. Overflow poisons the prefix already sent and skips
  * the rest of that physical frame; never concatenate it with a later frame.
  * Frames skipped before any prefix escapes are counted separately.
  */
class EthernetIngressPacker extends Module {
    val io = IO(new Bundle {
        val data = Input(UInt(8.W))
        val valid = Input(Bool())
        val error = Input(Bool())
        val byteStep = Input(Bool())
        val physicalValid = Input(Bool())
        val captureEnable = Input(Bool())
        val word = Decoupled(new EthernetFrameBeat(4))
        val overflow = Output(Bool())
        val wholeFrameSkipped = Output(Bool())
    })
    val waitIdle = RegInit(true.B)
    val active = RegInit(false.B)
    val discard = RegInit(false.B)
    val prefixSent = RegInit(false.B)
    val count = RegInit(0.U(2.W))
    val pack = RegInit(0.U(32.W))
    val bad = RegInit(false.B)
    val pendingEnd = RegInit(false.B)
    val endData = Reg(UInt(32.W))
    val endKeep = Reg(UInt(4.W))
    val endBad = Reg(Bool())
    val valid = RegInit(false.B)
    val word = Reg(new EthernetFrameBeat(4))
    io.word.valid := valid
    io.word.bits := word
    io.overflow := false.B
    io.wholeFrameSkipped := false.B
    val available = !valid || io.word.ready
    when(io.word.fire) { valid := false.B }
    when(pendingEnd && available) {
        word.data := endData
        word.keep := endKeep
        word.last := true.B
        word.bad := endBad
        valid := true.B
        pendingEnd := false.B
    }
    when(!io.captureEnable) {
        waitIdle := true.B
    }.elsewhen(waitIdle) {
        // This is the actual IDDR RX_DV, not the decoder's masked abort level.
        // Release in the middle of a wire frame must wait for a real idle.
        when(!io.physicalValid) { waitIdle := false.B }
    }.elsewhen(io.byteStep) {
        when(io.valid) {
            when(!active) {
                active := true.B
                prefixSent := false.B
                discard := pendingEnd
                count := 1.U
                pack := io.data
                bad := io.error
                when(pendingEnd) { io.overflow := true.B; count := 0.U }
            }.elsewhen(!discard) {
                val packed = pack | (io.data << Cat(count, 0.U(3.W)))
                when(count === 3.U) {
                    when(available && !pendingEnd) {
                        word.data := packed
                        word.keep := 15.U
                        word.last := false.B
                        word.bad := bad || io.error
                        valid := true.B
                        prefixSent := true.B
                    }.otherwise {
                        discard := true.B
                        io.overflow := true.B
                    }
                    count := 0.U
                    pack := 0.U
                    bad := false.B
                }.otherwise {
                    count := count + 1.U
                    pack := packed
                    bad := bad || io.error
                }
            }
        }.elsewhen(active) {
            active := false.B
            count := 0.U
            pack := 0.U
            bad := false.B
            when(!discard || prefixSent) {
                // Pending-end storage is separate from the held output word.
                // A poison LAST invalidates every byte of an escaped prefix.
                assert(!pendingEnd, "physical ingress overwrote an EOF owner")
                pendingEnd := true.B
                endData := Mux(discard, 0.U, pack)
                endKeep := Mux(discard, 0.U, ((1.U(5.W) << count) - 1.U)(3, 0))
                endBad := discard || bad
            }.otherwise { io.wholeFrameSkipped := true.B }
            discard := false.B
            prefixSent := false.B
        }
    }
}

/** Fixed-clock byte replay. A gap in token arrival is byteStep=0 while inside
  * a frame, never a fabricated RX_DV=0. LAST emits a real one-cycle idle after
  * its final data byte. A zero-keep bad LAST emits a synthetic errored byte first.
  */
class EthernetIngressUnpacker extends Module {
    val io = IO(new Bundle {
        val word = Flipped(Decoupled(new EthernetFrameBeat(4)))
        val data = Output(UInt(8.W))
        val valid = Output(Bool())
        val error = Output(Bool())
        val byteStep = Output(Bool())
        val idle = Output(Bool())
    })
    val queue = Module(new Queue(new EthernetFrameBeat(4), 2, pipe = true, flow = false))
    queue.io.enq <> io.word
    val head = queue.io.deq
    val index = RegInit(0.U(3.W))
    val active = RegInit(false.B)
    val poison = head.bits.last && head.bits.keep === 0.U && head.bits.bad
    val bytes = Mux(poison, 1.U, PopCount(head.bits.keep))
    val byte = index < bytes
    io.byteStep := head.valid || !active
    io.valid := head.valid && byte
    io.error := head.bits.bad
    io.data := Mux(poison, 0.U, (head.bits.data >> Cat(index(1, 0), 0.U(3.W)))(7, 0))
    io.idle := !active && !head.valid
    head.ready := Mux(head.bits.last, !byte, index === bytes - 1.U)
    when(head.valid) {
        when(byte) { active := true.B; index := index + 1.U }
        when(head.fire) {
            index := 0.U
            when(head.bits.last) { active := false.B }
        }
        assert(head.bits.keep === 0.U || head.bits.keep === 1.U || head.bits.keep === 3.U ||
            head.bits.keep === 7.U || head.bits.keep === 15.U, "physical ingress sparse byte token")
        assert(head.bits.last || head.bits.keep === 15.U, "short physical token without EOF")
    }
}

/** The physical-only CDC epoch owns no completed packet or DMA descriptor.
  * commonReset asserts to BOTH FIFO ends even if recovered RXC is stopped.
  * Each end deasserts only after its own clock resumes. The caller must await
  * sourceReady/destinationReady before opening a new link epoch. Complete frame
  * RAMs and framed-output FIFOs are OUTSIDE this reset and use cold reset only.
  */
class EthernetPhysicalIngress(depth: Int = 64) extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val sourceData = IO(Input(UInt(8.W)))
    val sourceValid = IO(Input(Bool()))
    val sourceError = IO(Input(Bool()))
    val sourceByteStep = IO(Input(Bool()))
    val physicalValid = IO(Input(Bool()))
    val captureEnable = IO(Input(Bool()))
    val data = IO(Output(UInt(8.W)))
    val valid = IO(Output(Bool()))
    val error = IO(Output(Bool()))
    val byteStep = IO(Output(Bool()))
    val idle = IO(Output(Bool()))
    val sourceReady = IO(Output(Bool()))
    val destinationReady = IO(Output(Bool()))
    val overflow = IO(Output(Bool()))
    val wholeFrameSkipped = IO(Output(Bool()))
    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonReset
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonReset
    val pack = withClockAndReset(sourceClock, sourceRelease.resetOut) { Module(new EthernetIngressPacker) }
    val unpack = withClockAndReset(destinationClock, destinationRelease.resetOut) { Module(new EthernetIngressUnpacker) }
    val crossing = Module(new EthernetFrameClockBridge(depth))
    crossing.sourceClock := sourceClock
    crossing.destinationClock := destinationClock
    crossing.commonReset := commonReset
    crossing.source <> pack.io.word
    unpack.io.word <> crossing.destination
    pack.io.data := sourceData
    pack.io.valid := sourceValid
    pack.io.error := sourceError
    pack.io.byteStep := sourceByteStep
    pack.io.physicalValid := physicalValid
    pack.io.captureEnable := captureEnable
    data := unpack.io.data
    valid := unpack.io.valid
    error := unpack.io.error
    byteStep := unpack.io.byteStep
    idle := unpack.io.idle && crossing.destinationIdle
    sourceReady := !sourceRelease.resetOut.asBool
    destinationReady := !destinationRelease.resetOut.asBool
    overflow := pack.io.overflow
    wholeFrameSkipped := pack.io.wholeFrameSkipped
}

/** Missing recovered-clock detector; it never uses the recovered clock as a
  * fabric gate. A 16-edge divided heartbeat makes the legal 2.5 MHz minimum
  * observable well inside a 1 ms default timeout. Presence is evidence of
  * edges only; negotiated speed still comes from verified MDIO status.
  */
class EthernetRxClockWatchdog(timeoutCycles: Int = 100000) extends RawModule {
    require(timeoutCycles >= 64)
    val sourceClock = IO(Input(Clock()))
    val monitorClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val present = IO(Output(Bool()))
    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonReset
    val monitorRelease = Module(new CdcResetRelease)
    monitorRelease.clockIn := monitorClock
    monitorRelease.asyncReset := commonReset
    val heartbeat = withClockAndReset(sourceClock, sourceRelease.resetOut) {
        val count = RegInit(0.U(5.W))
        count := count + 1.U
        count(4)
    }
    val sync = Module(new CdcLevel)
    sync.clockIn := monitorClock
    sync.resetIn := monitorRelease.resetOut
    sync.levelIn := heartbeat
    withClockAndReset(monitorClock, monitorRelease.resetOut) {
        val previous = RegNext(sync.levelOut, false.B)
        val observed = RegInit(false.B)
        val timer = RegInit(0.U(log2Ceil(timeoutCycles + 1).W))
        when(sync.levelOut =/= previous) { observed := true.B; timer := 0.U }
            .elsewhen(timer < timeoutCycles.U) { timer := timer + 1.U }
        present := observed && timer < timeoutCycles.U
    }
}
