import com.xilinx.rapidwright.util.FileTools;
import com.xilinx.rapidwright.device.*;
import com.xilinx.rapidwright.design.Design;
public class RapidWrightSmoke {
  public static void main(String[] args) {
    FileTools.setOverrideDataFileDownload(true);
    Design.setAutoGenerateReadableEdif(false);
    String name="xczu15eg-ffvb1156-2-i";
    Part p=PartNameTools.getPart(name);
    if (!p.getName().equals(name)) throw new RuntimeException("Wrong part");
    System.out.println("RapidWright="+Device.RAPIDWRIGHT_VERSION+" part="+p.getName()+" autoDownload="+!FileTools.overrideDataFileDownload()+" autoVivado="+Design.isAutoGenerateReadableEdif());
    if (args.length>0 && args[0].equals("device")) {
      Device d=Device.getDevice(p);
      if(d==null) throw new RuntimeException("Device missing");
      if (!d.getName().equals("xczu15eg") || d.getRows()!=435 || d.getColumns()!=455)
        throw new RuntimeException("Unexpected device name or geometry");
      System.out.println("DEVICE_LOAD_PASS name="+d.getName()+" rows="+d.getRows()+" cols="+d.getColumns());
    }
  }
}
