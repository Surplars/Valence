package soc.ip.debug

import chisel3._
import chisel3.util.HasBlackBoxResource

/** Optional existing-FPGA-JTAG USER-chain endpoint. Chain allocation is explicit;
  * this custom USER protocol is neither a nested TAP nor a SiFive BSCAN tunnel.
  */
class BscanRamTransport(chain: Int) extends BlackBox(Map("ENABLE" -> BigInt(1), "JTAG_CHAIN" -> BigInt(chain)))
    with HasBlackBoxResource {
    require(chain >= 1 && chain <= 4, "Select a verified free BSCAN USER chain")
    override def desiredName: String = "ValenceBscanDebugPort"
    val io = IO(new Bundle {
        val debug_clk = Input(Clock())
        val debug_por_n = Input(Bool())
        val dmi_reset_n = Output(Bool())
        val dmi_req_valid = Output(Bool())
        val dmi_req_ready = Input(Bool())
        val dmi_req_op = Output(UInt(2.W))
        val dmi_req_address = Output(UInt(7.W))
        val dmi_req_data = Output(UInt(32.W))
        val dmi_rsp_valid = Input(Bool())
        val dmi_rsp_ready = Output(Bool())
        val dmi_rsp_status = Input(UInt(2.W))
        val dmi_rsp_data = Input(UInt(32.W))
    })
    addResource("/debug/ValenceBscanDebugPort.sv")
    addResource("/debug/ValenceJtagDebugPort.sv") // shared bundled-data mailbox
}
