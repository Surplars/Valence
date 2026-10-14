package ooo
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
object ResponseStateOnlyConfigMain extends App {
    val p = TaggedLoadPublishConfig.params(true)
    var rejected = 0
    def reject(f: => Unit): Unit = {
        var caught = false
        try { f } catch { case _: IllegalArgumentException => caught = true }
        require(caught); rejected += 1
    }
    reject { ChiselStage.elaborate(new LoadStoreUnit(p.copy(localTaggedResponseReady = false), responseStateOnly = true)); () }
    reject { ChiselStage.elaborate(new LoadStoreUnit(p, registerStart = true, responseStateOnly = true)); () }
    val generic = ChiselStage.elaborate(new LoadStoreUnit(p))
    val candidate = ChiselStage.elaborate(new LoadStoreUnit(p, responseStateOnly = true))
    println(s"PASS_RESPONSE_STATE_CONSTRUCTORS negative=$rejected generic_default_preserved=true")
}
