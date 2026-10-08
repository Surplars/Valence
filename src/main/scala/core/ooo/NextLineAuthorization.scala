package soc.core.ooo

import chisel3._
import chisel3.util._

/** Independent whole-line authorization at the checked request boundary.
  * Never trust an incoming hint, and never reinterpret it using a later privilege.
  * Input is already physical: a successful virtual-page translation grants the
  * same PTE read/PBMT context throughout this 4KiB subpage. The adapter supplies
  * its captured effective privilege; this check independently qualifies PMP.
  */
class NextLineAuthorization(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val request = Input(new DataRequest)
        val privilege = Input(UInt(2.W))
        val pmpState = Input(new PmpState)
        val fault = Input(Bool())
        val allowed = Output(Bool())
        val address = Output(UInt(64.W))
    })
    // Refuse a page crossing before forming a page-local increment. This
    // avoids an XLEN carry chain in the additional checked metadata path.
    val nextIndex = io.request.address(11, 6) + 1.U(6.W)
    val next = Cat(io.request.address(63, 12), nextIndex, 0.U(6.W))
    val last = Cat(0.U(1.W), next(63, 6), 63.U(6.W))
    val checker = Module(new PmpChecker(p.pmpEntries))
    checker.io.state := io.pmpState
    checker.io.address := next
    checker.io.size := 6.U(3.W)
    checker.io.privilege := io.privilege
    checker.io.access := PmpAccess.read
    io.address := next
    io.allowed := !io.fault && !io.request.write && !io.request.atomic && !io.request.uncached &&
        !io.request.virtualized && SpeculativeRamRange.contains(p, io.request.address, io.request.size) &&
        io.request.address(11, 6) =/= 63.U &&
        next >= p.speculativeRamBase.U(65.W) &&
        last < (p.speculativeRamBase + p.speculativeRamBytes).U(65.W) && !checker.io.denied
}
