package soc.core.inorder

import chisel3._
import chisel3.util._

/** H 1.0 additional instruction decode and execution permission, before CPU integration.
  * Pure combinational classification: II=1, no owner, storage or side effect.
  * Caller supplies architectural U/S/M privilege and V (always zero in M).
  * A recognized trap has cause 2 or 22; other encodings belong to the base decoder.
  */
class I1HypervisorDecode(xlen: Int) extends Module {
    require(xlen == 32 || xlen == 64)
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val privilege = Input(UInt(2.W))
        val virtualized = Input(Bool())
        val hu = Input(Bool())
        val tvm = Input(Bool())
        val recognized = Output(Bool())
        val allowed = Output(Bool())
        val load = Output(Bool())
        val store = Output(Bool())
        val executePermission = Output(Bool())
        val unsigned = Output(Bool())
        val size = Output(UInt(2.W))
        val fenceVs = Output(Bool())
        val fenceGuest = Output(Bool())
        val exception = Output(Bool())
        val cause = Output(UInt(6.W))
    })
    val inst = io.instruction
    val system = inst(6, 0) === "h73".U
    val size = inst(27, 26)
    val variant = inst(24, 20)
    val memory = system && inst(14, 12) === 4.U && inst(31, 28) === 6.U
    // HLVX.WU exists on RV32 too. HLV.WU, HLV.D and HSV.D require RV64.
    val loadVariant = MuxLookup(size, false.B)(Seq(
        0.U -> (variant === 0.U || variant === 1.U),
        1.U -> (variant === 0.U || variant === 1.U || variant === 3.U),
        2.U -> (variant === 0.U || variant === 3.U || (xlen == 64).B && variant === 1.U),
        3.U -> ((xlen == 64).B && variant === 0.U)))
    val load = memory && !inst(25) && loadVariant
    val store = memory && inst(25) && inst(11, 7) === 0.U && ((xlen == 64).B || size =/= 3.U)
    val fence = system && inst(14, 12) === 0.U && inst(11, 7) === 0.U
    val fenceVs = fence && inst(31, 25) === "h11".U
    val fenceGuest = fence && inst(31, 25) === "h31".U
    val recognized = load || store || fenceVs || fenceGuest
    val machine = io.privilege === 3.U
    val supervisor = io.privilege === 1.U
    val host = machine || supervisor
    val memoryPermission = host || (io.privilege === 0.U && io.hu)
    // TVM constrains HFENCE.GVMA in HS only. It never constrains HFENCE.VVMA.
    val fencePermission = host && (!fenceGuest || machine || !io.tvm)
    val allowed = recognized && !io.virtualized && Mux(load || store, memoryPermission, fencePermission)
    io.recognized := recognized; io.allowed := allowed
    io.load := load; io.store := store; io.size := size
    io.unsigned := load && variant =/= 0.U
    io.executePermission := load && variant === 3.U
    io.fenceVs := fenceVs; io.fenceGuest := fenceGuest
    // Both VS and VU attempts of valid H encodings raise virtual instruction.
    // Invalid encodings remain the responsibility of ordinary illegal decode.
    io.exception := recognized && !allowed
    io.cause := Mux(io.virtualized, 22.U, 2.U)
}
