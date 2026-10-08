package soc.core.ooo

import chisel3._
import chisel3.util._

/** Asynchronous distributed-RAM candidate: one data bank per write lane and a
  * narrow register-based last-writer table. Each data bank has ONE write port
  * and explicit address reads; never expose a full array of values.
  * No data reset or write-through: pre-edge reads see old data; post-edge reads
  * see the winning write. Higher lane wins collisions, as in legacy last-connect
  * updates. Physical zero and unwritten/reset locations read zero via metadata.
  * Memory inference is an opportunity, not a measured area/timing claim.
  */
class OwnerBankedPhysicalRegisterFile(entries: Int, readPorts: Int, writePorts: Int = 2) extends Module {
    require(entries > 32 && entries <= 256)
    require(readPorts >= 1)
    require(writePorts == 2, "only the two-completion-lane topology is currently supported")
    val addressBits = log2Ceil(entries)
    val io = IO(new Bundle {
        val write = Input(Vec(writePorts, Valid(new Bundle {
            val address = UInt(addressBits.W)
            val data = UInt(64.W)
        })))
        val address = Input(Vec(readPorts, UInt(addressBits.W)))
        val data = Output(Vec(readPorts, UInt(64.W)))
    })
    val initialized = RegInit(VecInit(Seq.fill(entries)(false.B)))
    val owner = RegInit(VecInit(Seq.fill(entries)(false.B)))
    val banks = Seq.fill(writePorts)(Mem(entries, UInt(64.W)))
    for (lane <- 0 until writePorts) {
        val port = io.write(lane)
        val live = port.valid && port.bits.address =/= 0.U && port.bits.address < entries.U
        val safeAddress = Mux(live, port.bits.address, 0.U)
        when(port.valid) {
            assert(port.bits.address < entries.U, "PRF write address outside physical capacity")
        }
        when(live) {
            banks(lane).write(safeAddress, port.bits.data)
            initialized(safeAddress) := true.B
            owner(safeAddress) := (lane == 1).B
        }
    }
    for (port <- 0 until readPorts) {
        val inRange = io.address(port) < entries.U
        val safeAddress = Mux(inRange, io.address(port), 0.U)
        val data0 = banks(0).read(safeAddress)
        val data1 = banks(1).read(safeAddress)
        io.data(port) := Mux(inRange && safeAddress =/= 0.U && initialized(safeAddress),
            Mux(owner(safeAddress), data1, data0), 0.U)
    }
}
