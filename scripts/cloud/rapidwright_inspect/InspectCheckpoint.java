import com.xilinx.rapidwright.util.FileTools;
import com.xilinx.rapidwright.device.*;
import com.xilinx.rapidwright.design.*;
import com.xilinx.rapidwright.edif.*;
import java.nio.file.*;
import java.io.*;
import java.util.*;

/** Read-only checkpoint inspection. Never writes a checkpoint or changes routing. */
public final class InspectCheckpoint {
  static String s(Object x) {return x==null ? "" : x.toString().replace("\\","\\\\").replace("\t","\\t").replace("\r","\\r").replace("\n","\\n");}
  static void row(PrintWriter w, Object... x) {for(int i=0;i<x.length;i++){if(i>0)w.print('\t');w.print(s(x[i]));}w.println();}
  static PrintWriter out(String name) throws Exception {return new PrintWriter(Files.newBufferedWriter(Path.of(name)));}
  static void pin(PrintWriter w,String net,String role, SitePinInst p) {
    if(p==null){row(w,net,role,"","","","","","","","");return;}
    Tile t=p.getTile();
    row(w,net,role,p.getName(),p.getSiteInstName(),p.getSite()==null?null:p.getSite().getName(),
      t==null?null:t.getName(),t==null?null:t.getTileXCoordinate(),t==null?null:t.getTileYCoordinate(),p.isRouted(),p.getSitePinName());
  }
  public static void main(String[] a) throws Exception {
    FileTools.setOverrideDataFileDownload(true);
    Design.setAutoGenerateReadableEdif(false);
    if(a.length==1 && a[0].equals("--api-check")) {
      System.out.println(Design.class.getMethod("readCheckpoint",String.class,String.class));
      System.out.println(Net.class.getMethod("getSinkPins"));
      System.out.println("API_CHECK_PASS version="+Device.RAPIDWRIGHT_VERSION+" autoDownload=false autoVivado=false");return;
    }
    if(a.length!=4)throw new IllegalArgumentException("Expected DCP EDIF critical-net-list expected-part");
    String headerPart=Design.getPartNameFromDCP(a[0]);
    if(!headerPart.equals(a[3]))throw new IllegalStateException("DCP part mismatch: "+headerPart);
    Design d=Design.readCheckpoint(a[0],a[1]);
    if(!d.getPartName().equals(a[3]) || d.getNetlist()==null || d.getNetlist().getTopCell()==null)
      throw new IllegalStateException("Missing netlist/top or part mismatch");
    List<String> names=Files.readAllLines(Path.of(a[2]));
    for(String name:names)if(d.getNet(name)==null)throw new IllegalStateException("Report net absent from physical design: "+name);
    try(PrintWriter w=out("summary.tsv")) {
      row(w,"key","value");row(w,"scope","Read-only physical inspection; no WNS, hold, Fmax, route or implementation qualification");
      row(w,"rapidwright",Device.RAPIDWRIGHT_VERSION);row(w,"part",d.getPartName());row(w,"design",d.getName());
      row(w,"top",d.getNetlist().getTopCell().getName());row(w,"physical_cells",d.getCells().size());
      row(w,"physical_nets",d.getNets().size());row(w,"site_instances",d.getSiteInsts().size());
      row(w,"critical_nets",names.size());row(w,"auto_download",false);row(w,"auto_vivado",false);
    }
    Set<String> relevantSites=new HashSet<>();
    try(PrintWriter nw=out("nets.tsv"); PrintWriter pw=out("pins.tsv"); PrintWriter rw=out("pips.tsv"); PrintWriter ew=out("logical_endpoints.tsv")) {
      row(nw,"net","stored_site_pin_fanout_not_logical","sink_site_pins","all_site_pins","pips","site_instances");
      row(pw,"net","role","pin","site_instance","site","tile","tile_x","tile_y","routed_flag","site_pin");
      row(rw,"net","pip_index","pip");
      row(ew,"net","direction","logical_cell","logical_pin","physical_cell","site","bel","tile","tile_x","tile_y");
      for(String name:names) {
        Net n=d.getNet(name);row(nw,name,n.getFanOut(),n.getSinkPins().size(),n.getPins().size(),n.getPIPs().size(),n.getSiteInsts().size());
        pin(pw,name,"source",n.getSource());
        for(SitePinInst p:n.getPins())if(p.isOutPin() && p!=n.getSource())pin(pw,name,"alternate_output",p);
        for(SitePinInst p:n.getSinkPins())pin(pw,name,"sink",p);
        int index=0;for(PIP p:n.getPIPs())row(rw,name,index++,p);
        for(SitePinInst p:n.getPins())if(p.getSite()!=null)relevantSites.add(p.getSite().getName());
        for(SiteInst si:n.getSiteInsts())if(si.getSite()!=null)relevantSites.add(si.getSite().getName());
        List<EDIFHierPortInst> endpoints=d.getNetlist().getPhysicalPins(n);
        if(endpoints==null || endpoints.isEmpty())throw new IllegalStateException("No EDIF physical endpoints for "+name);
        for(EDIFHierPortInst ep:endpoints) {
          Cell c=ep.getPhysicalCell(d); Tile t=c==null?null:c.getTile();
          row(ew,name,ep.isOutput()?"source":ep.isInput()?"sink":"inout",ep.getFullHierarchicalInstName(),ep.getPortInst().getName(),
            c==null?null:c.getName(),c==null?null:c.getSiteName(),c==null?null:c.getBELName(),
            t==null?null:t.getName(),t==null?null:t.getTileXCoordinate(),t==null?null:t.getTileYCoordinate());
        }
      }
    }
    try(PrintWriter w=out("site_cells.tsv")) {
      row(w,"cell","site","bel","tile","tile_x","tile_y","scope");
      for(Cell c:d.getCells())if(relevantSites.contains(c.getSiteName())) {
        Tile t=c.getTile();row(w,c.getName(),c.getSiteName(),c.getBELName(),t==null?null:t.getName(),
          t==null?null:t.getTileXCoordinate(),t==null?null:t.getTileYCoordinate(),"cell in endpoint site; connectivity not implied");
      }
    }
    if(!FileTools.overrideDataFileDownload() || Design.isAutoGenerateReadableEdif())throw new IllegalStateException("Automatic behavior changed");
    System.out.println("READ_ONLY_INSPECTION_PASS");
  }
}
