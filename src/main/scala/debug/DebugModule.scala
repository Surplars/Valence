package soc.debug

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

class DebugModule(params: TLParams, sbaParams: TLParams = TLParams()) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
        val sba = new TLBundle(sbaParams)
        val dmi_valid = Input(Bool())
        val dmi_addr  = Input(UInt(7.W))
        val dmi_wdata = Input(UInt(32.W))
        val dmi_write = Input(Bool())
        val dmi_rdata = Output(UInt(32.W))
        val dmi_resp_op = Output(UInt(2.W))

        val haltreq = Output(Bool())
        val resumereq = Output(Bool())
        val dmactive = Output(Bool())
        val hart_halted = Input(Bool())
        val hart_pc = Input(UInt(64.W))
        val gpr_addr = Output(UInt(5.W))
        val gpr_rdata = Input(UInt(64.W))
        val gpr_write = Output(Bool())
        val gpr_wdata = Output(UInt(64.W))
        val csr_addr = Output(UInt(12.W))
        val csr_rdata = Input(UInt(64.W))
        val csr_valid = Input(Bool())
        val csr_writable = Input(Bool())
        val csr_write = Output(Bool())
        val csr_wdata = Output(UInt(64.W))
        val cache = new DebugCacheControl
    })
    TLBundle.tieoffSlaveCoherence(io.tl)
    TLBundle.tieoffMasterCoherence(io.sba)

    private val beatBytes = params.dataWidth / 8
    val dmcontrol = RegInit(0.U(32.W))
    val data0 = RegInit(0.U(32.W))
    val data1 = RegInit(0.U(32.W))
    val command = RegInit(0.U(32.W))
    val cmderr = RegInit(0.U(3.W))
    val gprWriteReg = RegInit(false.B)
    val gprAddrReg = RegInit(0.U(5.W))
    val gprWdataReg = RegInit(0.U(64.W))
    val csrWriteReg = RegInit(false.B)
    val csrAddrReg = RegInit(0.U(12.W))
    val csrWdataReg = RegInit(0.U(64.W))
    val dcsr = RegInit("h40000003".U(32.W))
    val dpc = RegInit(0.U(64.W))
    val dscratch0 = RegInit(0.U(64.W))
    val resumeAck = RegInit(false.B)
    val hartHaveReset = RegInit(true.B)
    val hartHaltedPrev = RegNext(io.hart_halted, false.B)
    val sbAddress = RegInit(0.U(64.W))
    val sbData = RegInit(0.U(64.W))
    val sbAccess = RegInit(2.U(3.W)) // 32-bit access by default; OpenOCD probes this path first.
    val sbReadOnAddr = RegInit(false.B)
    val sbReadOnData = RegInit(false.B)
    val sbAutoIncrement = RegInit(false.B)
    val sbError = RegInit(0.U(3.W))
    val sbBusyError = RegInit(false.B)
    val dmiRespOp = RegInit(0.U(2.W))
    val dcacheDone = RegInit(false.B)
    val icacheDone = RegInit(false.B)
    val dcacheErrSticky = RegInit(false.B)
    val icacheErrSticky = RegInit(false.B)
    val haltreqPulse = WireDefault(false.B)
    val resumereqPulse = WireDefault(false.B)

    when(io.hart_halted && !hartHaltedPrev) {
        dpc := io.hart_pc
        dcsr := (dcsr & ~("h000001c0".U(32.W))) | (3.U(32.W) << 6) // cause=haltreq
    }
    when(io.cache.dcacheAck) {
        dcacheDone := true.B
        dcacheErrSticky := dcacheErrSticky || io.cache.dcacheErr
    }
    when(io.cache.icacheAck) {
        icacheDone := true.B
        icacheErrSticky := icacheErrSticky || io.cache.icacheErr
    }

    private val progbuf = RegInit(VecInit(Seq.fill(DebugModuleConstants.BackingProgBufWords)(0.U(32.W))))
    private val abstractcs = Cat(
        DebugModuleConstants.AdvertisedProgBufWords.U(5.W),
        0.U(11.W),
        false.B,
        0.U(1.W),
        cmderr,
        0.U(4.W),
        2.U(4.W)
    )
    private val hartinfo = Cat(0.U(8.W), 1.U(4.W), 0.U(4.W), 0.U(3.W), 0.U(1.W), 0.U(4.W), 0.U(4.W), 0.U(4.W))
    val abstractauto = RegInit(0.U(32.W))
    val (sbaIdle :: sbaReq :: sbaWait :: Nil) = Enum(3)
    val sbaState = RegInit(sbaIdle)
    val sbaIsWrite = RegInit(false.B)
    val sbaAddr = RegInit(0.U(sbaParams.addrWidth.W))
    val sbaSize = RegInit(2.U(sbaParams.sizeBits.W))
    val sbaWriteData = RegInit(0.U(sbaParams.dataWidth.W))
    private val sbaBeatBytes = sbaParams.dataWidth / 8
    val sbaMask = RegInit(0.U(sbaBeatBytes.W))
    val sbaLaneShift = RegInit(0.U(log2Ceil(sbaParams.dataWidth).W))
    val sbaHasNext = RegInit(false.B)
    val sbaNextAddr = RegInit(0.U(sbaParams.addrWidth.W))
    val sbaNextWriteData = RegInit(0.U(sbaParams.dataWidth.W))
    val sbaNextMask = RegInit(0.U(sbaBeatBytes.W))
    val sbaNextLaneShift = RegInit(0.U(log2Ceil(sbaParams.dataWidth).W))
    val sbaReadPartial = RegInit(0.U(64.W))
    val sbaReadMergeShift = RegInit(0.U(6.W))
    val sbaBytes = Wire(UInt(4.W))
    sbaBytes := 1.U << sbAccess
    val sbaBusy = sbaState =/= sbaIdle
    private val sbcs =
        (1.U(3.W) << 29) |
            (sbBusyError.asUInt << 22) |
            (sbaBusy.asUInt << 21) |
            (sbReadOnAddr.asUInt << 20) |
            (sbAccess << 17) |
            (sbAutoIncrement.asUInt << 16) |
            (sbReadOnData.asUInt << 15) |
            (sbError << 12) |
            (sbaParams.addrWidth.U(7.W) << 5) |
            "b01111".U(32.W) // 8/16/32/64-bit accesses are accepted when beat-aligned.
    private val hartsel = Cat(dmcontrol(25, 16), dmcontrol(15, 6))
    private val hartSelected = hartsel === 0.U

    private def accessSupported: Bool = sbAccess <= 3.U
    private def accessBytes: UInt = 1.U << sbAccess
    private def accessLane(address: UInt): UInt = address(log2Ceil(sbaBeatBytes) - 1, 0)
    private def accessCrossesBeat(address: UInt): Bool = (accessLane(address) +& accessBytes) > sbaBeatBytes.U
    private def bytesMask(bytes: UInt): UInt =
        ((1.U((sbaBeatBytes + 1).W) << bytes) - 1.U)(sbaBeatBytes - 1, 0)
    private def accessShift(address: UInt): UInt = Cat(accessLane(address), 0.U(3.W))

    val sbaStartRead = WireDefault(false.B)
    val sbaStartWrite = WireDefault(false.B)
    val sbaStartWriteData = WireDefault(sbData)
    val sbaStartAddress = WireDefault(sbAddress)

    private def requestSba(isWrite: Bool, address: UInt, data: UInt): Unit = {
        val lane = accessLane(address)
        val crossesBeat = accessCrossesBeat(address)
        val firstBytes = Mux(crossesBeat, sbaBeatBytes.U - lane, accessBytes)
        val secondBytes = accessBytes - firstBytes
        val firstMask = bytesMask(firstBytes) << lane
        val secondMask = bytesMask(secondBytes)
        val firstShift = Cat(lane, 0.U(3.W))
        val secondDataShift = Cat(firstBytes, 0.U(3.W))
        val firstWriteData = Wire(UInt(sbaParams.dataWidth.W))
        val secondWriteData = Wire(UInt(sbaParams.dataWidth.W))
        firstWriteData := data << firstShift
        secondWriteData := data >> secondDataShift
        when(sbaBusy) {
            sbBusyError := true.B
        }.elsewhen(!accessSupported) {
            sbError := 3.U
        }.otherwise {
            sbaIsWrite := isWrite
            sbaAddr := address(sbaParams.addrWidth - 1, 0)
            sbaSize := sbAccess(sbaParams.sizeBits - 1, 0)
            sbaWriteData := firstWriteData
            sbaMask := firstMask
            sbaLaneShift := firstShift
            sbaHasNext := crossesBeat
            sbaNextAddr := (address + firstBytes)(sbaParams.addrWidth - 1, 0)
            sbaNextWriteData := secondWriteData
            sbaNextMask := secondMask
            sbaNextLaneShift := 0.U
            sbaReadPartial := 0.U
            sbaReadMergeShift := Mux(crossesBeat, secondDataShift, 0.U)
            sbaState := sbaReq
        }
    }

    private def statusBit(index: Int, value: Bool): UInt = Mux(value, (BigInt(1) << index).U(32.W), 0.U)
    private val dmstatus =
        2.U(32.W) | // Debug spec v0.13
            statusBit(7, true.B) | // authenticated
            statusBit(8, hartSelected && io.hart_halted) |
            statusBit(9, hartSelected && io.hart_halted) |
            statusBit(10, hartSelected && !io.hart_halted) |
            statusBit(11, hartSelected && !io.hart_halted) |
            statusBit(14, !hartSelected) |
            statusBit(15, !hartSelected) |
            statusBit(16, hartSelected && resumeAck) |
            statusBit(17, hartSelected && resumeAck) |
            statusBit(18, hartSelected && hartHaveReset) |
            statusBit(19, hartSelected && hartHaveReset)

    private def readReg(addr: UInt): UInt = {
        val ionCacheCtl =
            statusBit(0, io.cache.dcacheBusy) |
                statusBit(1, io.cache.icacheBusy) |
                statusBit(8, dcacheDone) |
                statusBit(9, icacheDone) |
                statusBit(16, dcacheErrSticky) |
                statusBit(17, icacheErrSticky)
        MuxLookup(addr, 0.U(32.W))(
            Seq(
                DebugModuleMap.DMControl.U  -> dmcontrol,
                DebugModuleMap.DMStatus.U   -> dmstatus,
                DebugModuleMap.HartInfo.U   -> hartinfo,
                DebugModuleMap.AbstractCS.U -> abstractcs,
                DebugModuleMap.AbstractAuto.U -> abstractauto,
                DebugModuleMap.Command.U    -> command,
                DebugModuleMap.Data0.U      -> data0,
                DebugModuleMap.Data1.U      -> data1,
                DebugModuleMap.ProgBuf0.U   -> progbuf(0),
                DebugModuleMap.ProgBuf1.U   -> progbuf(1),
                DebugModuleMap.HaltSum0.U   -> Mux(io.hart_halted, 1.U(32.W), 0.U(32.W)),
                DebugModuleMap.SBCS.U       -> sbcs,
                DebugModuleMap.SBAddress0.U -> sbAddress(31, 0),
                DebugModuleMap.SBAddress1.U -> sbAddress(63, 32),
                DebugModuleMap.SBData0.U    -> sbData(31, 0),
                DebugModuleMap.SBData1.U    -> sbData(63, 32),
                DebugModuleMap.IonCacheCtl.U -> ionCacheCtl
            )
        )
    }

    def commandRegNo(cmd: UInt): UInt = cmd(15, 0)
    def commandIsAccessReg(cmd: UInt): Bool = cmd(31, 24) === 0.U
    def commandTransfer(cmd: UInt): Bool = cmd(17)
    def commandWrite(cmd: UInt): Bool = cmd(16)
    def commandPostexec(cmd: UInt): Bool = cmd(18)
    def commandAarSize(cmd: UInt): UInt = cmd(22, 20)
    def commandSize32(cmd: UInt): Bool = commandAarSize(cmd) === 2.U
    def commandSize64(cmd: UInt): Bool = commandAarSize(cmd) === 3.U
    def commandSupportedSize(cmd: UInt): Bool = commandSize32(cmd) || commandSize64(cmd)
    def commandCsr(cmd: UInt): Bool = commandRegNo(cmd) < "h1000".U
    def commandCsrAddr(cmd: UInt): UInt = commandRegNo(cmd)(11, 0)
    def commandDebugCsr(cmd: UInt): Bool =
        commandRegNo(cmd) === "h7b0".U || commandRegNo(cmd) === "h7b1".U || commandRegNo(cmd) === "h7b2".U
    def commandCoreCsr(cmd: UInt): Bool = commandCsr(cmd) && !commandDebugCsr(cmd)
    def commandGpr(cmd: UInt): Bool = commandRegNo(cmd) >= "h1000".U && commandRegNo(cmd) < "h1020".U
    def commandGprAddr(cmd: UInt): UInt = commandRegNo(cmd)(4, 0)
    def progbufIsEbreak(instr: UInt): Bool = instr === "h00100073".U
    def progbufIsNop(instr: UInt): Bool = instr === "h00000013".U
    def progbufIsFence(instr: UInt): Bool = instr(6, 0) === "b0001111".U && instr(14, 12) === "b000".U
    def progbufIsFenceI(instr: UInt): Bool = instr === "h0000100f".U
    def progbufSafeNonTerminating(instr: UInt): Bool = progbufIsNop(instr) || progbufIsFence(instr) || progbufIsFenceI(instr)
    private def progbufInterpretable(prog0: UInt, prog1: UInt): Bool = {
        val prog0Ends = progbufIsEbreak(prog0)
        val prog1Ends = !prog0Ends && progbufIsEbreak(prog1)
        // Interpreter subset for the advertised backing program buffer. This
        // keeps OpenOCD fence/postexec flows working without pretending to
        // execute arbitrary load/store helper snippets on the hart.
        (progbufIsEbreak(prog0) || progbufSafeNonTerminating(prog0)) &&
            Mux(prog0Ends, true.B, progbufIsEbreak(prog1) || progbufSafeNonTerminating(prog1)) &&
            (prog0Ends || prog1Ends)
    }

    private val HartselMask = "h03ffffc0".U(32.W)
    private val DmcontrolWriteOnePulseMask = ((BigInt(1) << 28) | (BigInt(1) << 30)).U(32.W)
    private def legalizeDmcontrol(data: UInt): UInt = data & ~HartselMask & ~DmcontrolWriteOnePulseMask

    val tlCommandWrite = WireDefault(false.B)
    val tlCommandData = WireDefault(0.U(32.W))
    val dmiCommandWrite = io.dmi_valid && io.dmi_write && io.dmi_addr === DebugModuleMap.Command.U
    val commandInFlight = dmiCommandWrite || tlCommandWrite
    val commandDataInFlight = Mux(dmiCommandWrite, io.dmi_wdata, tlCommandData)
    val gprAddrCommand = Mux(commandInFlight && commandGpr(commandDataInFlight), commandDataInFlight, command)
    val csrAddrCommand = Mux(commandInFlight && commandCsr(commandDataInFlight), commandDataInFlight, command)

    io.gpr_addr := Mux(gprWriteReg, gprAddrReg, commandGprAddr(gprAddrCommand))
    io.gpr_write := gprWriteReg
    io.gpr_wdata := gprWdataReg
    gprWriteReg := false.B
    io.csr_addr := Mux(csrWriteReg, csrAddrReg, commandCsrAddr(csrAddrCommand))
    io.csr_write := csrWriteReg
    io.csr_wdata := csrWdataReg
    csrWriteReg := false.B

    private def executeCommand(cmd: UInt, data0Value: UInt, data1Value: UInt, prog0Value: UInt, prog1Value: UInt): Unit = {
        command := cmd
        val supportedReg = commandGpr(cmd) || commandCsr(cmd)
        val postexecOnly = commandPostexec(cmd) && !commandTransfer(cmd)
        val postexecOk = !commandPostexec(cmd) || progbufInterpretable(prog0Value, prog1Value)
        val writeData = Mux(commandSize32(cmd), Cat(0.U(32.W), data0Value), Cat(data1Value, data0Value))
        val readData64 = Wire(UInt(64.W))
        readData64 := MuxLookup(commandRegNo(cmd), io.csr_rdata)(
            Seq(
                "h7b0".U -> Cat(0.U(32.W), dcsr),
                "h7b1".U -> dpc,
                "h7b2".U -> dscratch0
            )
        )
        val readData = Mux(commandSize32(cmd), Cat(0.U(32.W), readData64(31, 0)), readData64)
        when(cmderr =/= 0.U) {
            ()
        }.elsewhen(!io.hart_halted || !commandIsAccessReg(cmd) || !commandSupportedSize(cmd) || !postexecOk) {
            cmderr := 2.U
        }.elsewhen(postexecOnly) {
            cmderr := 0.U
        }.elsewhen(!commandTransfer(cmd) || !supportedReg) {
            cmderr := 2.U
        }.elsewhen(commandCoreCsr(cmd) && (!io.csr_valid || (commandWrite(cmd) && !io.csr_writable))) {
            cmderr := 2.U
        }.elsewhen(commandWrite(cmd) && commandGpr(cmd)) {
            gprWriteReg := true.B
            gprAddrReg := commandGprAddr(cmd)
            gprWdataReg := writeData
            cmderr := 0.U
        }.elsewhen(commandWrite(cmd) && commandDebugCsr(cmd)) {
            switch(commandRegNo(cmd)) {
                is("h7b0".U) { dcsr := Cat("h4".U(4.W), writeData(27, 0)) }
                is("h7b1".U) { dpc := writeData }
                is("h7b2".U) { dscratch0 := writeData }
            }
            cmderr := 0.U
        }.elsewhen(commandWrite(cmd) && commandCsr(cmd)) {
            csrWriteReg := true.B
            csrAddrReg := commandCsrAddr(cmd)
            csrWdataReg := writeData
            cmderr := 0.U
        }.elsewhen(commandGpr(cmd)) {
            data0 := io.gpr_rdata(31, 0)
            data1 := Mux(commandSize32(cmd), 0.U, io.gpr_rdata(63, 32))
            cmderr := 0.U
        }.otherwise {
            data0 := readData(31, 0)
            data1 := Mux(commandSize32(cmd), 0.U, readData(63, 32))
            cmderr := 0.U
        }
    }

    private def autoexecFor(addr: UInt): Bool =
        (addr === DebugModuleMap.Data0.U && abstractauto(0)) ||
            (addr === DebugModuleMap.Data1.U && abstractauto(1)) ||
            (addr === DebugModuleMap.ProgBuf0.U && abstractauto(16)) ||
            (addr === DebugModuleMap.ProgBuf1.U && abstractauto(17))

    private val AbstractAutoWritableMask =
        ((BigInt(1) << 0) | (BigInt(1) << 1) | (BigInt(1) << 16) | (BigInt(1) << 17)).U(32.W)

    private def writeReg(addr: UInt, data: UInt): Unit = {
        when(addr === DebugModuleMap.DMControl.U) {
            val legal = legalizeDmcontrol(data)
            dmcontrol := Mux(data(30), legal & ~(1.U(32.W) << 31), legal)
            haltreqPulse := data(31) && data(0) && hartSelected
            resumereqPulse := data(30) && data(0) && hartSelected
            when(data(31)) {
                resumeAck := false.B
            }.elsewhen(data(30) && data(0) && hartSelected) {
                resumeAck := true.B
            }
            when(data(28) && data(0) && hartSelected) {
                hartHaveReset := false.B
            }
        }.elsewhen(addr === DebugModuleMap.Data0.U) {
            data0 := data
            when(autoexecFor(addr)) {
                executeCommand(command, data, data1, progbuf(0), progbuf(1))
            }
        }.elsewhen(addr === DebugModuleMap.Data1.U) {
            data1 := data
            when(autoexecFor(addr)) {
                executeCommand(command, data0, data, progbuf(0), progbuf(1))
            }
        }.elsewhen(addr === DebugModuleMap.AbstractCS.U) {
            cmderr := cmderr & ~data(10, 8)
        }.elsewhen(addr === DebugModuleMap.AbstractAuto.U) {
            abstractauto := data & AbstractAutoWritableMask
        }.elsewhen(addr === DebugModuleMap.ProgBuf0.U) {
            progbuf(0) := data
            when(autoexecFor(addr)) {
                executeCommand(command, data0, data1, data, progbuf(1))
            }
        }.elsewhen(addr === DebugModuleMap.ProgBuf1.U) {
            progbuf(1) := data
            when(autoexecFor(addr)) {
                executeCommand(command, data0, data1, progbuf(0), data)
            }
        }.elsewhen(addr === DebugModuleMap.SBCS.U) {
            when(data(22)) { sbBusyError := false.B }
            when(data(14, 12).orR) { sbError := 0.U }
            sbReadOnAddr := data(20)
            sbAccess := data(19, 17)
            sbAutoIncrement := data(16)
            sbReadOnData := data(15)
        }.elsewhen(addr === DebugModuleMap.SBAddress0.U) {
            val nextAddress = Cat(sbAddress(63, 32), data)
            sbAddress := nextAddress
            when(sbReadOnAddr) {
                sbaStartRead := true.B
                sbaStartAddress := nextAddress
            }
        }.elsewhen(addr === DebugModuleMap.SBAddress1.U) {
            val nextAddress = Cat(data, sbAddress(31, 0))
            sbAddress := nextAddress
        }.elsewhen(addr === DebugModuleMap.SBData0.U) {
            val nextData = Cat(sbData(63, 32), data)
            sbData := nextData
            when(sbAccess =/= 3.U) {
                sbaStartWrite := true.B
                sbaStartWriteData := nextData
            }
        }.elsewhen(addr === DebugModuleMap.SBData1.U) {
            val nextData = Cat(data, sbData(31, 0))
            sbData := nextData
            when(sbAccess === 3.U) {
                sbaStartWrite := true.B
                sbaStartWriteData := nextData
            }
        }.elsewhen(addr === DebugModuleMap.Command.U) {
            executeCommand(data, data0, data1, progbuf(0), progbuf(1))
        }.elsewhen(addr === DebugModuleMap.IonCacheCtl.U) {
            when(data(8)) { dcacheDone := false.B }
            when(data(9)) { icacheDone := false.B }
            when(data(16)) { dcacheErrSticky := false.B }
            when(data(17)) { icacheErrSticky := false.B }
        }
    }

    io.cache.dcacheReq := false.B
    io.cache.icacheReq := false.B

    when(io.dmi_valid) {
        val busySbaData = sbaBusy && (
            io.dmi_addr === DebugModuleMap.SBAddress0.U ||
                io.dmi_addr === DebugModuleMap.SBAddress1.U ||
                io.dmi_addr === DebugModuleMap.SBData0.U ||
                io.dmi_addr === DebugModuleMap.SBData1.U
        )
        dmiRespOp := Mux(busySbaData, 3.U, 0.U)
        when(io.dmi_write) {
            when(!busySbaData) {
                writeReg(io.dmi_addr, io.dmi_wdata)
                when(io.dmi_addr === DebugModuleMap.IonCacheCtl.U) {
                    io.cache.dcacheReq := io.dmi_wdata(0)
                    io.cache.icacheReq := io.dmi_wdata(1)
                }
            }
        }.otherwise {
            when(!busySbaData && io.dmi_addr === DebugModuleMap.SBData0.U && sbReadOnData) {
                sbaStartRead := true.B
            }
            when(!busySbaData && autoexecFor(io.dmi_addr)) {
                executeCommand(command, data0, data1, progbuf(0), progbuf(1))
            }
        }
    }
    io.dmi_rdata := readReg(io.dmi_addr)
    io.dmi_resp_op := dmiRespOp

    val respValid = RegInit(false.B)
    val respOpcode = RegInit(TLOpcode.AccessAck)
    val respParam = RegInit(0.U(3.W))
    val respSize = RegInit(0.U(params.sizeBits.W))
    val respSource = RegInit(0.U(params.sourceBits.W))
    val respData = RegInit(0.U(params.dataWidth.W))
    val respDenied = RegInit(false.B)

    io.tl.a.ready := !respValid

    when(io.tl.a.fire) {
        val isRead = io.tl.a.bits.opcode === TLOpcode.Get
        val isWrite = io.tl.a.bits.opcode === TLOpcode.PutFullData || io.tl.a.bits.opcode === TLOpcode.PutPartialData
        val wordAddr = io.tl.a.bits.address(9, 2)
        val lane = io.tl.a.bits.address(log2Ceil(beatBytes) - 1, 0)
        val writeData = (io.tl.a.bits.data >> Cat(lane, 0.U(3.W)))(31, 0)
        val readData32 = readReg(wordAddr)

        respValid := true.B
        respOpcode := TLOpcode.responseOpcodeForA(io.tl.a.bits.opcode)
        respParam := TLOpcode.responseParamForA(io.tl.a.bits.opcode, io.tl.a.bits.param)
        respSize := io.tl.a.bits.size
        respSource := io.tl.a.bits.source
        respDenied := !(isRead || isWrite)
        respData := Mux(isRead, readData32 << Cat(lane, 0.U(3.W)), 0.U)

        when(isWrite) {
            when(wordAddr === DebugModuleMap.Command.U) {
                tlCommandWrite := true.B
                tlCommandData := writeData
            }
            writeReg(wordAddr, writeData)
            when(wordAddr === DebugModuleMap.IonCacheCtl.U) {
                io.cache.dcacheReq := writeData(0)
                io.cache.icacheReq := writeData(1)
            }
        }.elsewhen(isRead && wordAddr === DebugModuleMap.SBData0.U && sbReadOnData) {
            sbaStartRead := true.B
        }.elsewhen(isRead && autoexecFor(wordAddr)) {
            executeCommand(command, data0, data1, progbuf(0), progbuf(1))
        }
    }

    when(sbaStartRead) {
        requestSba(false.B, sbaStartAddress, 0.U)
    }.elsewhen(sbaStartWrite) {
        requestSba(true.B, sbaStartAddress, sbaStartWriteData)
    }

    io.sba.a.valid := sbaState === sbaReq
    io.sba.a.bits.opcode := Mux(sbaIsWrite, TLOpcode.PutPartialData, TLOpcode.Get)
    io.sba.a.bits.param := 0.U
    io.sba.a.bits.size := sbaSize
    io.sba.a.bits.source := 0.U
    io.sba.a.bits.address := sbaAddr
    io.sba.a.bits.mask := sbaMask
    io.sba.a.bits.data := sbaWriteData
    io.sba.a.bits.corrupt := false.B
    io.sba.d.ready := sbaState === sbaWait

    when(sbaState === sbaReq && io.sba.a.fire) {
        sbaState := sbaWait
    }
    when(sbaState === sbaWait && io.sba.d.fire) {
        val segmentReadData = (io.sba.d.bits.data >> sbaLaneShift)(63, 0)
        when(io.sba.d.bits.denied || io.sba.d.bits.corrupt) {
            sbError := 2.U
            sbaHasNext := false.B
            sbaState := sbaIdle
        }.elsewhen(sbaHasNext) {
            when(!sbaIsWrite) {
                sbaReadPartial := segmentReadData
            }
            sbaAddr := sbaNextAddr
            sbaWriteData := sbaNextWriteData
            sbaMask := sbaNextMask
            sbaLaneShift := sbaNextLaneShift
            sbaHasNext := false.B
            sbaState := sbaReq
        }.otherwise {
            when(!sbaIsWrite) {
                sbData := sbaReadPartial | (segmentReadData << sbaReadMergeShift)
            }
            when(sbAutoIncrement) {
                sbAddress := sbAddress + accessBytes
            }
            sbaState := sbaIdle
        }
    }

    io.tl.d.valid := respValid
    io.tl.d.bits.opcode := respOpcode
    io.tl.d.bits.param := respParam
    io.tl.d.bits.size := respSize
    io.tl.d.bits.source := respSource
    io.tl.d.bits.sink := 0.U
    io.tl.d.bits.denied := respDenied
    io.tl.d.bits.data := respData
    io.tl.d.bits.corrupt := false.B

    when(io.tl.d.fire) {
        respValid := false.B
    }

    io.dmactive := dmcontrol(0)
    io.haltreq := (dmcontrol(31) && dmcontrol(0)) || haltreqPulse
    io.resumereq := resumereqPulse
}
