package soc.core.ooo
import chisel3._
/** Test-only exact recovery predicate queries; no new admission authority or state. */
class QueriedRecoveryAdmission(p: OooParams) extends ParallelRecoveryAdmission(p) {
    override def desiredName: String = "ParallelRecoveryAdmission"
    val queries = IO(new Bundle {
        val age = Input(Vec(p.completionWidth, UInt(p.robBits.W)))
        val survives = Output(Vec(p.completionWidth, Bool()))
    })
    for (lane <- 0 until p.completionWidth) {
        val retainedByNewBoundary = Mux(externalWins,
            queries.age(lane) < externalKeep, queries.age(lane) < localKeep)
        queries.survives(lane) := Mux(accepted, retainedByNewBoundary,
            !io.recovering || queries.age(lane) < io.keepCount)
    }
}
