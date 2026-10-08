package soc.ip.debug

import chisel3._
import chisel3.util._

/** Debug 1.0 JTAG DTM wire format; the default ID is an unassigned test value,
  * never a claim to a registered JEDEC identity. Enabled transport has no DM.
  */
case class JtagDebugParams(
    enabled: Boolean = false,
    externalDmi: Boolean = false,
    addressBits: Int = 7,
    idcode: BigInt = 1,
    idleHint: Int = 7
) {
    require(addressBits >= 1 && addressBits <= 32)
    require(idcode >= 0 && idcode < (BigInt(1) << 32) && idcode.testBit(0))
    require(idleHint >= 0 && idleHint <= 7)
    require(!externalDmi || enabled, "An external DMI endpoint requires an enabled transport")
}

class DmiRequest(addressBits: Int) extends Bundle {
    val op = UInt(2.W) // Only 1 (read) and 2 (write) are delivered.
    val address = UInt(addressBits.W)
    val data = UInt(32.W)
}
class DmiResponse extends Bundle {
    val status = UInt(2.W) // 0 success, 2 failure, 3 busy; 1 is rejected as failure.
    val data = UInt(32.W)
}
class DebugDmiPort(addressBits: Int) extends Bundle {
    val request = Decoupled(new DmiRequest(addressBits))
    val response = Flipped(Decoupled(new DmiResponse))
}

/** Future architectural hart adapter: declaration only, NOT connected to the CPU.
  * Halt must stop at a precise retirement boundary; resume must acknowledge once.
  * dcsr/dpc access requires debug mode, privilege checks, and a real response.
  * Defining this bundle does not implement Sdext, triggers, step or abstract commands.
  */
class HartDebugRegisterRequest extends Bundle {
    val dpc = Bool() // false selects dcsr, true selects dpc
    val write = Bool()
    val data = UInt(64.W)
}
class HartDebugRegisterResponse extends Bundle {
    val data = UInt(64.W)
    val error = Bool()
}
class HartDebugReservationPort extends Bundle {
    val haltRequest = Output(Bool())
    val resumeRequest = Output(Bool())
    val halted = Input(Bool())
    val resumeAck = Input(Bool())
    val resetAck = Input(Bool())
    val registers = Decoupled(new HartDebugRegisterRequest)
    val registerResponse = Flipped(Decoupled(new HartDebugRegisterResponse))
}

private class JtagDebugTransportBlackBox(config: JtagDebugParams)
    extends BlackBox(Map(
        "ENABLE" -> BigInt(1),
        "EXTERNAL_DMI" -> BigInt(if (config.externalDmi) 1 else 0),
        "ABITS" -> BigInt(config.addressBits),
        "IDCODE" -> config.idcode,
        "IDLE_HINT" -> BigInt(config.idleHint)
    )) with HasBlackBoxResource {
    override def desiredName: String = "ValenceJtagDebugPort"
    val io = IO(new Bundle {
        val tck = Input(Clock())
        val tms = Input(Bool())
        val tdi = Input(Bool())
        val trst_n = Input(Bool())
        val debug_clk = Input(Clock())
        val debug_por_n = Input(Bool())
        val tdo = Output(Bool())
        val tdo_oe = Output(Bool())
        val dmi_reset_n = Output(Bool())
        val dmi_req_valid = Output(Bool())
        val dmi_req_ready = Input(Bool())
        val dmi_req_op = Output(UInt(2.W))
        val dmi_req_address = Output(UInt(config.addressBits.W))
        val dmi_req_data = Output(UInt(32.W))
        val dmi_rsp_valid = Input(Bool())
        val dmi_rsp_ready = Output(Bool())
        val dmi_rsp_status = Input(UInt(2.W))
        val dmi_rsp_data = Input(UInt(32.W))
    })
    addResource("/debug/ValenceJtagDebugPort.sv")
}

/** Compile-time optional, separately reset debug island. There is intentionally
  * no CPU reset or CPU halt input/output: warm CPU resets must not reset a DTM.
  * External transaction interfaces MUST use dmiResetN and debugClock, not CPU warm reset.
  * This reset cancels interface work, not the future DM's persistent architectural state.
  * Request and response are single-outstanding, held stable under backpressure.
  */
class JtagDebugReservation(config: JtagDebugParams = JtagDebugParams()) extends RawModule {
    val tck = IO(Input(Clock()))
    val tms = IO(Input(Bool()))
    val tdi = IO(Input(Bool()))
    val trstN = IO(Input(Bool()))
    val debugClock = IO(Input(Clock()))
    val debugPorN = IO(Input(Bool()))
    val tdo = IO(Output(Bool()))
    val tdoOe = IO(Output(Bool()))
    val dmiResetN = IO(Output(Bool()))
    val dmi = IO(new DebugDmiPort(config.addressBits))
    if (config.enabled) {
        val transport = Module(new JtagDebugTransportBlackBox(config))
        transport.io.tck := tck
        transport.io.tms := tms
        transport.io.tdi := tdi
        transport.io.trst_n := trstN
        transport.io.debug_clk := debugClock
        transport.io.debug_por_n := debugPorN
        tdo := transport.io.tdo
        tdoOe := transport.io.tdo_oe
        dmiResetN := transport.io.dmi_reset_n
        dmi.request.valid := transport.io.dmi_req_valid
        dmi.request.bits.op := transport.io.dmi_req_op
        dmi.request.bits.address := transport.io.dmi_req_address
        dmi.request.bits.data := transport.io.dmi_req_data
        transport.io.dmi_req_ready := dmi.request.ready
        transport.io.dmi_rsp_valid := dmi.response.valid
        transport.io.dmi_rsp_status := dmi.response.bits.status
        transport.io.dmi_rsp_data := dmi.response.bits.data
        dmi.response.ready := transport.io.dmi_rsp_ready
    } else {
        tdo := false.B
        tdoOe := false.B
        dmiResetN := false.B
        dmi.request.valid := false.B
        dmi.request.bits := 0.U.asTypeOf(dmi.request.bits)
        dmi.response.ready := false.B
    }
}
