package soc.core.inorder

import chisel3._
import chisel3.experimental.IntParam
import chisel3.util.HasBlackBoxResource

/** Optional existing-FPGA-JTAG USER-chain endpoint. Chain allocation is explicit;
  * this custom USER protocol is neither a nested TAP nor a SiFive BSCAN tunnel.
  */
object I1BscanRamTransport {
    def validateScanBits(bits: Int): Unit =
        require(bits >= 64 && bits <= 127, "USER DR frame64 plus 0..63 external BYPASS bits")
}

class I1BscanRamTransport(chain: Int, timingCuts: Boolean, scanBits: Int = 64) extends BlackBox(
    Map("ENABLE" -> IntParam(1), "JTAG_CHAIN" -> IntParam(chain)) ++
        (if (timingCuts || scanBits != 64) Map("SCAN_BITS" -> IntParam(scanBits)) else Map.empty))
    with HasBlackBoxResource {
    require(chain >= 1 && chain <= 4, "Select a verified free BSCAN USER chain")
    I1BscanRamTransport.validateScanBits(scanBits)
    private val privateTransport = timingCuts || scanBits != 64
    override def desiredName: String = if (privateTransport) "ValenceI1BscanDebugPort" else "ValenceBscanDebugPort"
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
    if (privateTransport) {
        addResource("/inorder/ValenceI1BscanDebugPort.sv")
        addResource("/inorder/ValenceI1DmiCdc.sv")
    } else {
        addResource("/debug/ValenceBscanDebugPort.sv")
        addResource("/debug/ValenceJtagDebugPort.sv")
    }
}
