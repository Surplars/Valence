package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** Exclusive hardware PHY policy for the opt-in FPGA tri-speed profile.
  * Standard full-duplex 10/100/1000 advertisement, no pause or EEE; verify
  * RTL8211F identity, RGMII delay RMWs, advertisements and page restoration.
  * Poll BMSR twice (latched-low link), partner capabilities and two PHY status
  * samples, then debounce complete polls before reporting a usable link.
  *
  * Command/response ownership is external so the production Clause22 engine
  * and a separately tested register oracle can both drive this controller.
  * lock spans each complete page sequence, including its restore/readback.
  * A failed transaction invalidates link immediately and retries initialization
  * after a bounded pause. The engine must eventually return a response; the
  * outer MDIO implementation has a fixed transaction bound, not an external ACK.
  */
class Rtl8211fPhyManager(clockHz: Int = 100000000, phyAddress: Int = 1,
    startupCycles: Int = 2000000, pollCycles: Int = 10000000, debouncePolls: Int = 2) extends Module {
    require(clockHz > 0 && phyAddress >= 0 && phyAddress < 32)
    require(startupCycles > 0 && pollCycles > 0 && debouncePolls >= 2 && debouncePolls <= 15)
    val io = IO(new Bundle {
        val command = Decoupled(new MdioCommand)
        val response = Flipped(Decoupled(new MdioResponse))
        val restart = Input(Bool())
        val lock = Output(Bool())
        val initialized = Output(Bool())
        val linkUp = Output(Bool())
        val requestedSpeed = Output(UInt(2.W))
        val rawStatus = Output(UInt(16.W))
        val fault = Output(UInt(4.W))
        val noAckCount = Output(UInt(32.W))
        val verifyErrorCount = Output(UInt(32.W))
        val unsupportedCount = Output(UInt(32.W))
        val linkChangeCount = Output(UInt(32.W))
        val pollCount = Output(UInt(32.W))
    })
    private val operations = Enum(39)
    val basePage = operations(0)
    val baseCheck = operations(1)
    val id1 = operations(2)
    val id2 = operations(3)
    val delayPage = operations(4)
    val delayCheck = operations(5)
    val txRead = operations(6)
    val txWrite = operations(7)
    val txCheck = operations(8)
    val rxRead = operations(9)
    val rxWrite = operations(10)
    val rxCheck = operations(11)
    val restore = operations(12)
    val restoreCheck = operations(13)
    val eeeDev = operations(14)
    val eeeAddress = operations(15)
    val eeeMode = operations(16)
    val eeeWrite = operations(17)
    val eeeCheck = operations(18)
    val advertise = operations(19)
    val advertiseCheck = operations(20)
    val gigRead = operations(21)
    val gigWrite = operations(22)
    val gigCheck = operations(23)
    val bmcrRead = operations(24)
    val bmcrWrite = operations(25)
    val bmcrCheck = operations(26)
    val pollPage = operations(27)
    val pollPageCheck = operations(28)
    val bmsrFirst = operations(29)
    val bmsrSecond = operations(30)
    val partnerRead = operations(31)
    val partnerGigRead = operations(32)
    val statusPage = operations(33)
    val statusPageCheck = operations(34)
    val statusFirst = operations(35)
    val statusSecond = operations(36)
    val pollRestore = operations(37)
    val pollRestoreCheck = operations(38)
    val waitStartup :: issue :: awaitReply :: idle :: Nil = Enum(4)
    val state = RegInit(waitStartup)
    val operation = RegInit(basePage)
    val timer = RegInit(0.U(log2Ceil(startupCycles.max(pollCycles) + 1).W))
    val restartPending = RegInit(false.B)
    when(io.restart) { restartPending := true.B }
    val initialized = RegInit(false.B)
    val link = RegInit(false.B)
    val speed = RegInit(EthernetSpeed.Mbps1000.U(2.W))
    val fault = RegInit(0.U(4.W))
    val noAcks = RegInit(0.U(32.W))
    val verifyErrors = RegInit(0.U(32.W))
    val unsupported = RegInit(0.U(32.W))
    val changes = RegInit(0.U(32.W))
    val polls = RegInit(0.U(32.W))
    val rawStatus = RegInit(0.U(16.W))
    val txValue = Reg(UInt(16.W))
    val rxValue = Reg(UInt(16.W))
    val gigValue = Reg(UInt(16.W))
    val bmcrValue = Reg(UInt(16.W))
    val bmsr = Reg(UInt(16.W))
    val partner = Reg(UInt(16.W))
    val partnerGig = Reg(UInt(16.W))
    val firstStatus = Reg(UInt(16.W))
    val sampledStatus = Reg(UInt(16.W))
    val candidateSpeed = RegInit(3.U(2.W))
    val stablePolls = RegInit(0.U(4.W))
    val oldLink = RegNext(link, false.B)
    val oldSpeed = RegNext(speed, EthernetSpeed.Mbps1000.U)
    when(link =/= oldLink || (link && speed =/= oldSpeed)) { changes := changes + 1.U }
    io.initialized := initialized
    io.linkUp := link && initialized && !restartPending
    io.requestedSpeed := speed
    io.rawStatus := rawStatus
    io.fault := fault
    io.noAckCount := noAcks
    io.verifyErrorCount := verifyErrors
    io.unsupportedCount := unsupported
    io.linkChangeCount := changes
    io.pollCount := polls
    io.lock := state === issue || state === awaitReply
    io.command.valid := state === issue
    io.command.bits.phy := phyAddress.U
    io.command.bits.register := 31.U
    io.command.bits.write := false.B
    io.command.bits.data := 0.U
    io.response.ready := state === awaitReply
    def read(register: Int): Unit = { io.command.bits.register := register.U }
    def write(register: Int, value: UInt): Unit = {
        io.command.bits.register := register.U
        io.command.bits.write := true.B
        io.command.bits.data := value
    }
    switch(operation) {
        is(basePage, restore, pollPage, pollRestore) { write(31, 0.U) }
        is(id1) { read(2) }
        is(id2) { read(3) }
        is(delayPage) { write(31, "h0d08".U) }
        is(txRead, txCheck) { read(17) }
        is(txWrite) { write(17, txValue) }
        is(rxRead, rxCheck) { read(21) }
        is(rxWrite) { write(21, rxValue) }
        is(eeeDev) { write(13, 7.U) }
        is(eeeAddress) { write(14, 60.U) }
        is(eeeMode) { write(13, "h4007".U) }
        is(eeeWrite) { write(14, 0.U) }
        is(eeeCheck) { read(14) }
        // Selector=802.3, 10BASE-T full, 100BASE-TX full. No half/pause/T4.
        is(advertise) { write(4, "h0141".U) }
        is(advertiseCheck) { read(4) }
        is(gigRead, gigCheck) { read(9) }
        is(gigWrite) { write(9, gigValue) }
        is(bmcrRead, bmcrCheck) { read(0) }
        is(bmcrWrite) { write(0, bmcrValue) }
        is(bmsrFirst, bmsrSecond) { read(1) }
        is(partnerRead) { read(5) }
        is(partnerGigRead) { read(10) }
        is(statusPage) { write(31, "h0a43".U) }
        is(statusFirst, statusSecond) { read(26) }
    }
    val response = io.response.bits.data
    val badVerify = WireDefault(false.B)
    val faultCode = WireDefault(2.U(4.W))
    switch(operation) {
        is(baseCheck, restoreCheck, pollPageCheck, pollRestoreCheck) { badVerify := response =/= 0.U }
        is(id1) { badVerify := response =/= "h001c".U; faultCode := 3.U }
        is(id2) { badVerify := response =/= "hc916".U; faultCode := 3.U }
        is(delayCheck) { badVerify := response =/= "h0d08".U }
        is(txCheck) { badVerify := response =/= txValue; faultCode := 4.U }
        is(rxCheck) { badVerify := response =/= rxValue; faultCode := 5.U }
        is(eeeCheck) { badVerify := response =/= 0.U; faultCode := 6.U }
        is(advertiseCheck) { badVerify := response =/= "h0141".U; faultCode := 7.U }
        is(gigCheck) { badVerify := response =/= gigValue; faultCode := 7.U }
        // Restart self-clears. Require AN enabled, power-down/isolate disabled.
        is(bmcrCheck) { badVerify := (response & "h1c00".U) =/= "h1000".U; faultCode := 8.U }
        is(statusPageCheck) { badVerify := response =/= "h0a43".U }
    }
    when(state === waitStartup) {
        when(timer === (startupCycles - 1).U) { timer := 0.U; state := issue }
            .otherwise { timer := timer + 1.U }
    }
    when(io.command.fire) { state := awaitReply }
    when(io.response.fire) {
        state := issue
        operation := operation + 1.U
        when(io.response.bits.noAck || badVerify) {
            when(io.response.bits.noAck) { noAcks := noAcks + 1.U; fault := 1.U }
                .otherwise { verifyErrors := verifyErrors + 1.U; fault := faultCode }
            initialized := false.B
            link := false.B
            stablePolls := 0.U
            timer := 0.U
            // A retry starts by restoring page zero. Never leave a failed
            // transaction marked initialized or report a stale negotiated rate.
            operation := basePage
            state := idle
        }.otherwise {
            switch(operation) {
                is(txRead) { txValue := response & "hfeff".U }
                is(rxRead) { rxValue := response | "h0008".U }
                is(gigRead) { gigValue := (response & "hfcff".U) | "h0200".U }
                is(bmcrRead) { bmcrValue := "h1340".U }
                is(bmcrCheck) {
                    initialized := true.B
                    fault := 0.U
                    operation := pollPage
                    timer := 0.U
                    state := idle
                }
                is(bmsrSecond) {
                    bmsr := response
                    when(!response(2) || !response(5) || response(4)) { link := false.B; stablePolls := 0.U }
                }
                is(partnerRead) { partner := response }
                is(partnerGigRead) { partnerGig := response }
                is(statusFirst) { firstStatus := response }
                is(statusSecond) {
                    sampledStatus := response
                    rawStatus := response
                    when(!response(2) || !response(3) || response(5, 4) === 3.U ||
                        response(5, 2) =/= firstStatus(5, 2)) { link := false.B; stablePolls := 0.U }
                }
                is(pollRestoreCheck) {
                    polls := polls + 1.U
                    val selected = sampledStatus(5, 4)
                    val partnerSupports = Mux(selected === 2.U,
                        partnerGig(11) && !partnerGig(15), Mux(selected === 1.U, partner(8), partner(6)))
                    val qualified = bmsr(2) && bmsr(5) && !bmsr(4) && sampledStatus(2) &&
                        sampledStatus(3) && EthernetSpeed.legal(selected) &&
                        firstStatus(5, 2) === sampledStatus(5, 2) && partnerSupports
                    when(qualified) {
                        val same = candidateSpeed === selected
                        val next = Mux(same, Mux(stablePolls < debouncePolls.U, stablePolls + 1.U,
                            stablePolls), 1.U)
                        stablePolls := next
                        candidateSpeed := selected
                        when(link && speed =/= selected) { link := false.B }
                        when(next >= debouncePolls.U) { speed := selected; link := true.B }
                    }.otherwise {
                        link := false.B
                        stablePolls := 0.U
                        candidateSpeed := 3.U
                        when(sampledStatus(2) && (!sampledStatus(3) || !EthernetSpeed.legal(selected))) {
                            unsupported := unsupported + 1.U
                        }
                    }
                    operation := pollPage
                    state := idle
                    timer := 0.U
                }
            }
        }
    }
    when(state === idle) {
        when(timer === (pollCycles - 1).U || restartPending) {
            timer := 0.U
            state := issue
            when(restartPending) {
                restartPending := false.B
                initialized := false.B
                link := false.B
                stablePolls := 0.U
                operation := basePage
            }
        }.otherwise { timer := timer + 1.U }
    }
    assert(!io.linkUp || (initialized && EthernetSpeed.legal(speed)), "PHY reported an unverified rate")
}
