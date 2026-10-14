`timescale 1ns/1ps
module convert_tb;
 reg [63:0] bits; reg d,sgn;reg [2:0] rm;
 wire [63:0] n,w,rn,rw;wire [2:0] nf,wf,rnf,rwf;
 ConvertHarness dut(.clock(1'b0),.reset(1'b0),.io_bits(bits),.io_double(d),.io_signed(sgn),.io_rm(rm),.io_narrow(n),.io_wide(w),.io_nf(nf),.io_wf(wf),.io_referenceNarrow(rn),.io_referenceWide(rw),.io_rnf(rnf),.io_rwf(rwf));
 integer f,rc,count=0,di,si,mi;reg [63:0] en,ew;reg [2:0] enf,ewf;reg [1023:0] path;
 initial begin
  if(!$value$plusargs("vectors=%s",path))$fatal(1,"MISSING_VECTOR_PATH");f=$fopen(path,"r");if(!f)$fatal(1,"MISSING_VECTORS");
  while(!$feof(f))begin
   rc=$fscanf(f,"%d %d %d %h %h %h %h %h\n",di,si,mi,bits,en,enf,ew,ewf);
   if(rc!=8)$fatal(1,"BAD_VECTOR");d=di;sgn=si;rm=mi;#1;
   if({rn,rnf,rw,rwf}!=={en,enf,ew,ewf})$fatal(1,"ORACLE_BASELINE_MISMATCH count=%0d d=%0d signed=%0d rm=%0d bits=%h n=%h/%h flags=%h/%h wide=%h/%h wf=%h/%h",count,d,sgn,rm,bits,rn,en,rnf,enf,rw,ew,rwf,ewf);
   if({n,nf,w,wf}!=={rn,rnf,rw,rwf})$fatal(1,"CANDIDATE_MISMATCH count=%0d d=%0d signed=%0d rm=%0d bits=%h n=%h/%h flags=%h/%h",count,d,sgn,rm,bits,n,rn,nf,rnf);
   count=count+1;
  end
  if(count<120000)$fatal(1,"COVERAGE");$display("PASS_CONVERT_COMPONENT vectors=%0d raw_hardfloat_reference=1 independent_exact_integer_oracle=1",count);$finish;
 end
endmodule
