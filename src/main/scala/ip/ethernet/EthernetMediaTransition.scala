package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** CPU-domain transaction for changing media rate without resetting an owner.
  * Close admission, abort only partial frames, drain packet/FIFO/adapter tails,
  * send two independent rate mailboxes, await BOTH consumed-image ACKs, then
  * reopen only if the still-current PHY request matches the committed image.
  * No timeout forces a FIFO reset. A stopped RX clock or unconsumed packet is
  * visible as pending+timeout and safely resumes when the missing service does.
  */
class EthernetMediaTransition(timeoutCycles: Int = 50000000) extends Module {
    require(timeoutCycles >= 4)
    val io = IO(new Bundle {
        val requestedLink = Input(Bool())
        val requestedSpeed = Input(UInt(2.W))
        val txDrained = Input(Bool())
        val rxDrained = Input(Bool())
        val txRate = Decoupled(UInt(2.W))
        val rxRate = Decoupled(UInt(2.W))
        val txRateIdle = Input(Bool())
        val rxRateIdle = Input(Bool())
        val ingressReady = Input(Bool())
        val ingressReset = Output(Bool())
        val stopNewTraffic = Output(Bool())
        val abortTraffic = Output(Bool())
        val linkUp = Output(Bool())
        val appliedSpeed = Output(UInt(2.W))
        val pending = Output(Bool())
        val timedOut = Output(Bool())
        val timeoutCount = Output(UInt(32.W))
    })
    val stable :: drain :: sendRates :: waitRates :: releaseIngress :: Nil = Enum(5)
    val state = RegInit(drain)
    val activeLink = RegInit(false.B)
    val applied = RegInit(EthernetSpeed.Mbps1000.U(2.W))
    val targetLink = RegInit(false.B)
    val targetSpeed = RegInit(EthernetSpeed.Mbps1000.U(2.W))
    val sentTx = RegInit(false.B)
    val sentRx = RegInit(false.B)
    val requestValid = io.requestedLink && EthernetSpeed.legal(io.requestedSpeed)
    val changed = requestValid =/= activeLink || (requestValid && io.requestedSpeed =/= applied)
    val pending = state =/= stable || changed
    io.pending := pending
    io.linkUp := activeLink && !pending && requestValid
    io.appliedSpeed := applied
    io.stopNewTraffic := !io.linkUp
    io.abortTraffic := !io.linkUp
    io.ingressReset := !(state === releaseIngress || (state === stable && activeLink && !changed))
    io.txRate.valid := state === sendRates && !sentTx && requestValid
    io.rxRate.valid := state === sendRates && !sentRx && requestValid
    io.txRate.bits := targetSpeed
    io.rxRate.bits := targetSpeed
    when(state === stable && changed) { state := drain; activeLink := false.B }
    when(state === drain && io.txDrained && io.rxDrained && !io.ingressReady) {
        when(requestValid) {
            targetLink := true.B
            targetSpeed := io.requestedSpeed
            sentTx := false.B
            sentRx := false.B
            state := sendRates
        }.otherwise {
            // Frame ownership lives in the continuously clocked domain. A
            // down-link MUST NOT await a dead recovered-clock configuration ACK.
            // An old rate mailbox stays owned until that source clock returns.
            activeLink := false.B
            state := stable
        }
    }
    when(io.txRate.fire) { sentTx := true.B }
    when(io.rxRate.fire) { sentRx := true.B }
    when(state === sendRates && sentTx && sentRx) { state := waitRates }
    when(state === waitRates && io.txRateIdle && io.rxRateIdle) {
        applied := targetSpeed
        when(requestValid === targetLink && (!requestValid || io.requestedSpeed === targetSpeed)) {
            state := releaseIngress
        }.otherwise { activeLink := false.B; state := drain }
    }
    when(state === releaseIngress && io.ingressReady) {
        when(requestValid && io.requestedSpeed === targetSpeed) { activeLink := true.B; state := stable }
            .otherwise { activeLink := false.B; state := drain }
    }
    // Link loss during an outstanding rate offer/ACK cannot deadlock down-link
    // drain. Neither mailbox is reset or falsely acknowledged by this priority.
    when(state =/= stable && state =/= drain && !requestValid) {
        activeLink := false.B
        state := drain
    }
    val timer = RegInit(0.U(log2Ceil(timeoutCycles + 1).W))
    val timedOut = RegInit(false.B)
    val timeouts = RegInit(0.U(32.W))
    when(!pending) { timer := 0.U; timedOut := false.B }
        .elsewhen(!timedOut) {
            when(timer === (timeoutCycles - 1).U) { timedOut := true.B; timeouts := timeouts + 1.U }
                .otherwise { timer := timer + 1.U }
        }
    io.timedOut := timedOut
    io.timeoutCount := timeouts
    when(io.linkUp) {
        assert(io.txRateIdle && io.rxRateIdle && io.ingressReady,
            "media link enabled before rate ACKs and returned ingress epoch")
    }
}

/** Command-granularity ownership plus page-sequence locking for ONE MDIO engine.
  * Software reads are permitted only on the verified default page between
  * complete policy sequences. Writes/vendor-page reads are rejected explicitly
  * with noAck. Autonomous policy must remain the sole configuration writer.
  * This avoids phylib/page transactions racing the hardware manager silently.
  */
class ManagedMdioArbiter(phyAddress: Int = 1) extends Module {
    val io = IO(new Bundle {
        val policyCommand = Flipped(Decoupled(new MdioCommand))
        val policyResponse = Decoupled(new MdioResponse)
        val policyLock = Input(Bool())
        val initialized = Input(Bool())
        val softwareCommand = Flipped(Decoupled(new MdioCommand))
        val softwareResponse = Decoupled(new MdioResponse)
        val engineCommand = Decoupled(new MdioCommand)
        val engineResponse = Flipped(Decoupled(new MdioResponse))
        val softwareDenied = Output(Bool())
    })
    require(phyAddress >= 0 && phyAddress < 32)
    val active = RegInit(false.B)
    val policyOwner = RegInit(false.B)
    val deniedReply = RegInit(false.B)
    val softwareAllowed = io.initialized && !io.softwareCommand.bits.write &&
        io.softwareCommand.bits.phy === phyAddress.U && io.softwareCommand.bits.register < 16.U
    io.engineCommand.valid := !active && Mux(io.policyLock, io.policyCommand.valid,
        io.softwareCommand.valid && !deniedReply && softwareAllowed)
    io.engineCommand.bits := Mux(io.policyLock, io.policyCommand.bits, io.softwareCommand.bits)
    io.policyCommand.ready := !active && io.policyLock && io.engineCommand.ready
    io.softwareCommand.ready := !active && !io.policyLock && !deniedReply &&
        (!softwareAllowed || io.engineCommand.ready)
    io.policyResponse.valid := active && policyOwner && io.engineResponse.valid
    io.policyResponse.bits := io.engineResponse.bits
    io.softwareResponse.valid := deniedReply || (active && !policyOwner && io.engineResponse.valid)
    io.softwareResponse.bits := Mux(deniedReply,
        Cat(true.B, "hffff".U(16.W)).asTypeOf(new MdioResponse), io.engineResponse.bits)
    io.engineResponse.ready := active && Mux(policyOwner, io.policyResponse.ready, io.softwareResponse.ready)
    io.softwareDenied := io.softwareCommand.fire && !softwareAllowed
    when(io.softwareDenied) { deniedReply := true.B }
    when(deniedReply && io.softwareResponse.ready) { deniedReply := false.B }
    when(io.engineCommand.fire) { active := true.B; policyOwner := io.policyLock }
    when(io.engineResponse.fire) { active := false.B }
    assert(!io.policyCommand.valid || io.policyLock, "PHY sequence released MDIO before command completed")
    assert(!(deniedReply && active && !policyOwner), "two software MDIO responses own one reply")
}
