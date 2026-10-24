package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Isolated combinational permission contract. Raw PMP is supplied by the host;
  * the independent host oracle decodes it and checks every byte, not DUT regions.
  * This module alone makes no flush/drain or accepted-request ownership claim.
  */
class M2DataPermissionGsim extends Module {
    val p = CommonA1RebuildProfile.FullM2.config.coreParams
    require(p.fpEnabled && p.fpConfig.d && p.pmpEntries == 16 && p.virtualMemoryLevels == 3)
    require(p.speculativeRamBase == BigInt("80200000", 16) && p.speculativeRamBytes == BigInt(2).pow(31))
    require(p.dataNextLinePrefetch && !p.dataStoreNextLinePrefetch && !p.factorCheckedNextAllowed)
    val io = IO(new Bundle {
        val result = Input(new TranslatedDataRequest(p))
        val authorization = Input(new DataAuthorizationContext)
        // Flat top-level pins avoid the simulator's unsupported Vec input setters.
        val cfg0 = Input(UInt(8.W))
        val cfg1 = Input(UInt(8.W))
        val cfg2 = Input(UInt(8.W))
        val cfg3 = Input(UInt(8.W))
        val cfg4 = Input(UInt(8.W))
        val cfg5 = Input(UInt(8.W))
        val cfg6 = Input(UInt(8.W))
        val cfg7 = Input(UInt(8.W))
        val cfg8 = Input(UInt(8.W))
        val cfg9 = Input(UInt(8.W))
        val cfg10 = Input(UInt(8.W))
        val cfg11 = Input(UInt(8.W))
        val cfg12 = Input(UInt(8.W))
        val cfg13 = Input(UInt(8.W))
        val cfg14 = Input(UInt(8.W))
        val cfg15 = Input(UInt(8.W))
        val addr0 = Input(UInt(54.W))
        val addr1 = Input(UInt(54.W))
        val addr2 = Input(UInt(54.W))
        val addr3 = Input(UInt(54.W))
        val addr4 = Input(UInt(54.W))
        val addr5 = Input(UInt(54.W))
        val addr6 = Input(UInt(54.W))
        val addr7 = Input(UInt(54.W))
        val addr8 = Input(UInt(54.W))
        val addr9 = Input(UInt(54.W))
        val addr10 = Input(UInt(54.W))
        val addr11 = Input(UInt(54.W))
        val addr12 = Input(UInt(54.W))
        val addr13 = Input(UInt(54.W))
        val addr14 = Input(UInt(54.W))
        val addr15 = Input(UInt(54.W))
        val hintRequest = Input(new DataRequest)
        val hintPrivilege = Input(UInt(2.W))
        val hintBypassFault = Input(Bool())
        val fault = Output(Bool())
        val pmpDenied = Output(Bool())
        val access = Output(UInt(2.W))
        val nextAllowed = Output(Bool())
        val canonical = Output(Valid(new CanonicalStoreCertificate(p)))
    })
    val state = WireDefault(0.U.asTypeOf(new PmpState))
    state.cfg(0) := io.cfg0
    state.cfg(1) := io.cfg1
    state.cfg(2) := io.cfg2
    state.cfg(3) := io.cfg3
    state.cfg(4) := io.cfg4
    state.cfg(5) := io.cfg5
    state.cfg(6) := io.cfg6
    state.cfg(7) := io.cfg7
    state.cfg(8) := io.cfg8
    state.cfg(9) := io.cfg9
    state.cfg(10) := io.cfg10
    state.cfg(11) := io.cfg11
    state.cfg(12) := io.cfg12
    state.cfg(13) := io.cfg13
    state.cfg(14) := io.cfg14
    state.cfg(15) := io.cfg15
    state.addr(0) := io.addr0
    state.addr(1) := io.addr1
    state.addr(2) := io.addr2
    state.addr(3) := io.addr3
    state.addr(4) := io.addr4
    state.addr(5) := io.addr5
    state.addr(6) := io.addr6
    state.addr(7) := io.addr7
    state.addr(8) := io.addr8
    state.addr(9) := io.addr9
    state.addr(10) := io.addr10
    state.addr(11) := io.addr11
    state.addr(12) := io.addr12
    state.addr(13) := io.addr13
    state.addr(14) := io.addr14
    state.addr(15) := io.addr15
    PmpState.decodeRegions(state)
    val dut = Module(new DataPhysicalPermissionEvaluator(p))
    dut.io.result := io.result
    dut.io.authorization := io.authorization
    dut.io.pmpState := state
    dut.io.hintRequest := io.hintRequest
    dut.io.hintPrivilege := io.hintPrivilege
    dut.io.hintBypassFault := io.hintBypassFault
    io.fault := dut.io.fault
    io.pmpDenied := dut.io.pmpDenied
    io.access := dut.io.access
    io.nextAllowed := dut.io.nextAllowed
    io.canonical := dut.io.canonical
}
object M2DataPermissionGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new M2DataPermissionGsim, Array("--target-dir", args.head))
}
