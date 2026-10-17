package soc.core.ooo

import chisel3._
import chisel3.util._

/** Combinational static-register wake/reserve reduction. No new storage/latency,
  * all ports accepted each cycle, allocation-clear wins over any completion-set.
  * Data writes and liveness/exception authorization remain outside this module.
  */
class PhysicalReadyUpdate(registers: Int, wakePorts: Int, reservePorts: Int) extends Module {
    require(registers > 32 && registers <= 256 && wakePorts >= 1 && reservePorts >= 1)
    val io = IO(new Bundle {
        val current = Input(UInt(registers.W))
        val wake = Input(Vec(wakePorts, Valid(UInt(log2Ceil(registers).W))))
        val reserve = Input(Vec(reservePorts, Valid(UInt(log2Ceil(registers).W))))
        val next = Output(UInt(registers.W))
    })
    val next = Wire(Vec(registers, Bool()))
    for (r <- 0 until registers) {
        val waking = VecInit(io.wake.map(w => w.valid && w.bits === r.U)).asUInt.orR
        val reserving = VecInit(io.reserve.map(a => a.valid && a.bits === r.U)).asUInt.orR
        next(r) := (io.current(r) || waking) && !reserving
    }
    io.next := next.asUInt
}
