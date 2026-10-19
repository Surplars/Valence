`timescale 1ns/1ps
// Independent Sv39/PMP oracle and fixed-latency, single-owner memory service.
// No instruction execution: all reported cycles are MMU-interface CPU clocks.
module tb;
`include "signals.svh"
    localparam [63:0] ROOT=64'h10000, L1=64'h11000, TABLES=64'h20000;
    localparam [63:0] DVA=64'h40000000, IVA=64'h60000000, DPA=64'h80000000, IPA=64'h81000000;
    reg [63:0] pageMemory [0:262143];
    reg [63:0] actualData [0:127];
    reg [63:0] expectedData [0:127];
    integer cycles=0, acceptsD=0, acceptsI=0, hitsD=0, hitsI=0, missesD=0, missesI=0;
    integer slowD=0, slowI=0, ptesD=0, ptesI=0, physicalD=0, physicalI=0;
    integer repliesD=0, repliesI=0, checks=0, maxDOwners=0;
    integer dueD=0, dueI=0, latency=2, stallMode=0;
    reg pendingD=0, pendingI=0;
    reg [63:0] returnD=0, returnI=0;
    reg returnErrorD=0, returnErrorI=0;
    reg outstandingD=0, outstandingI=0, offeredD=0, offeredI=0;
    reg [63:0] expectPaD, expectPaI, expectDataD, expectDataI;
    reg expectErrorD, expectErrorI, expectPageD, expectPageI;
    reg expectWriteD;
    reg [63:0] expectWriteDataD;
    reg [63:0] faultAddress=64'hffffffffffffffff;
    reg heldMemory=0, heldInstruction=0, heldReplyD=0, heldReplyI=0;
    reg [139:0] heldMemoryBits, heldInstructionBits;
    reg [66:0] heldReplyBitsD, heldReplyBitsI;
    integer workingPages=0, workingStride=0;
    integer t, n, stride, op, competition, k, rep, roundIndex, pageIndex, which;
    integer startCycles, startAD, startAI, startHD, startHI, startMD, startMI;
    integer startSD, startSI, startPD, startPI, startDD, startDI;
    reg [63:0] copyData, leafAddress;
    reg [63:0] tempPa;
    reg tempError, tempPage;
    reg negative=0;

    function automatic [63:0] pte(input [63:0] pa, input [7:0] flags);
        pte=(pa>>12<<10)|flags;
    endfunction
    function automatic [63:0] pattern(input [63:0] pa);
        pattern=(pa & ~64'd7)*64'h9e3779b97f4a7c15 ^ 64'hc0011234abcdfed0;
    endfunction
    function automatic integer dataIndex(input [63:0] pa);
        dataIndex=((pa-DPA)>>12)*2+((pa>>3)&1);
    endfunction
    function automatic [63:0] memoryRead(input [63:0] pa);
        if (pa < 64'h200000) memoryRead=pageMemory[pa>>3];
        else if (pa>=DPA && pa<DPA+64'h40000 && (pa&64'hff0)==0)
            memoryRead=actualData[dataIndex(pa)];
        else memoryRead=pattern(pa);
    endfunction
    function automatic bit pmpAllowed(input [63:0] pa,input integer size,input integer priv,
        input bit execute,input bit writing);
        reg [63:0] top,bytes;
        begin
            top={30'b0,io_pmpTop}<<2; bytes=64'd1<<size;
            if (pa>=64'h1000000000 || bytes>64'h1000000000-pa) pmpAllowed=0;
            else if (io_pmpConfig[4:3]==0 || pa>=top) pmpAllowed=(priv==3);
            else if (bytes>top-pa) pmpAllowed=0;
            else pmpAllowed=(priv==3 && !io_pmpConfig[7]) ||
                (execute ? io_pmpConfig[2] : writing ? io_pmpConfig[1] : io_pmpConfig[0]);
        end
    endfunction
    task automatic oracle(input [63:0] va,input bit writing,input bit instruction,
        output reg [63:0] pa,output reg error,output reg page);
        reg [63:0] tableAddress,at,v,ppn,pageMask;
        integer priv,level;
        bit finished,permission;
        begin
            priv=instruction ? io_privilege : io_dataPrivilege;
            pa=va; error=0; page=0; finished=0;
            if (priv!=3 && io_satp[63:60]==8) begin
                if (va[63:39] != {25{va[38]}}) begin error=1;page=1;finished=1;end
                tableAddress=(io_satp & 64'hfffffffffff)<<12;
                for(level=2;level>=0;level=level-1) if (!finished) begin
                    at=tableAddress+((va>>(12+9*level))&511)*8;
                    if (!pmpAllowed(at,3,1,0,0) || at==faultAddress) begin error=1;finished=1;end
                    else begin
                        v=pageMemory[at>>3];ppn=(v>>10)&64'hfffffffffff;
                        if (!v[0] || (!v[1] && v[2]) || (v>>54)!=0) begin error=1;page=1;finished=1;end
                        else if (v[1] || v[3]) begin
                            permission=instruction ? v[3] : writing ? v[2] : (v[1] || (io_mxr && v[3]));
                            if (!permission || !v[6] || (writing && !v[7]) ||
                                (priv==0 ? !v[4] : v[4] && (instruction || !io_sum)) ||
                                (ppn & ((64'd1<<(9*level))-1))!=0) begin error=1;page=1;end
                            pageMask=(64'd1<<(12+9*level))-1;
                            pa=(ppn<<12)|(va&pageMask);finished=1;
                        end else if (level==0 || (v&64'hd0)!=0) begin error=1;page=1;finished=1;end
                        else tableAddress=ppn<<12;
                    end
                end
            end
            if (!error && !pmpAllowed(pa,instruction?2:3,priv,instruction,writing)) error=1;
            if (!error && pa==faultAddress) error=1;
        end
    endtask
    task automatic fail(input string what);
        begin $display("I1_TLB_CAPACITY_FAIL cycle=%0d %s",cycles,what);$fatal(1);end
    endtask
    task automatic tick;
        reg fireD,fireI,replyD,replyI,memFire,iMemFire,memReply,iMemReply;
        reg [139:0] memoryBits,instructionBits;
        reg [66:0] responseBitsD,responseBitsI;
        begin
            clock=0;
            io_memory_request_ready=!pendingD && (!stallMode || cycles%5!=1);
            io_instructionMemory_request_ready=!pendingI && (!stallMode || cycles%4!=2);
            io_memory_response_valid=pendingD && cycles>=dueD;
            io_memory_response_bits_data=returnD;
            io_memory_response_bits_error=returnErrorD;
            io_memory_response_bits_pageFault=0;
            io_instructionMemory_response_valid=pendingI && cycles>=dueI;
            io_instructionMemory_response_bits_data=returnI;
            io_instructionMemory_response_bits_error=returnErrorI;
            io_instructionMemory_response_bits_pageFault=0;
            io_dResponse_ready=!stallMode || cycles%7>=3;
            io_iResponse_ready=!stallMode || cycles%6>=2;
            #4;
            fireD=io_dRequest_valid&&io_dRequest_ready;fireI=io_iRequest_valid&&io_iRequest_ready;
            replyD=io_dResponse_valid&&io_dResponse_ready;replyI=io_iResponse_valid&&io_iResponse_ready;
            memFire=io_memory_request_valid&&io_memory_request_ready;
            iMemFire=io_instructionMemory_request_valid&&io_instructionMemory_request_ready;
            memReply=io_memory_response_valid&&io_memory_response_ready;
            iMemReply=io_instructionMemory_response_valid&&io_instructionMemory_response_ready;
            memoryBits={io_memory_request_bits_address,io_memory_request_bits_data,
                io_memory_request_bits_mask,io_memory_request_bits_size,io_memory_request_bits_write,
                io_memory_request_bits_uncached};
            instructionBits={io_instructionMemory_request_bits_address,io_instructionMemory_request_bits_data,
                io_instructionMemory_request_bits_mask,io_instructionMemory_request_bits_size,
                io_instructionMemory_request_bits_write,io_instructionMemory_request_bits_uncached};
            responseBitsD={io_dResponse_bits_data,io_dResponse_bits_error,io_dResponse_bits_pageFault,io_dResponse_bits_fetchSpan};
            responseBitsI={io_iResponse_bits_data,io_iResponse_bits_error,io_iResponse_bits_pageFault,io_iResponse_bits_fetchSpan};
            if (!reset) begin
                if(heldMemory && (!io_memory_request_valid || memoryBits!==heldMemoryBits)) fail("D memory offer changed under backpressure");
                if(heldInstruction && (!io_instructionMemory_request_valid || instructionBits!==heldInstructionBits)) fail("I memory offer changed under backpressure");
                if(heldReplyD && (!io_dResponse_valid || responseBitsD!==heldReplyBitsD)) fail("D response changed under backpressure");
                if(heldReplyI && (!io_iResponse_valid || responseBitsI!==heldReplyBitsI)) fail("I response changed under backpressure");
                heldMemory=io_memory_request_valid&&!io_memory_request_ready;heldMemoryBits=memoryBits;
                heldInstruction=io_instructionMemory_request_valid&&!io_instructionMemory_request_ready;heldInstructionBits=instructionBits;
                heldReplyD=io_dResponse_valid&&!io_dResponse_ready;heldReplyBitsD=responseBitsD;
                heldReplyI=io_iResponse_valid&&!io_iResponse_ready;heldReplyBitsI=responseBitsI;
                if(fireD) begin if(outstandingD) fail("duplicate D translator owner");outstandingD=1;acceptsD=acceptsD+1;if(!io_dHit)slowD=slowD+1;end
                if(fireI) begin if(outstandingI) fail("duplicate I translator owner");outstandingI=1;acceptsI=acceptsI+1;if(!io_iHit)slowI=slowI+1;end
                hitsD=hitsD+io_dHit;hitsI=hitsI+io_iHit;missesD=missesD+io_dMiss;missesI=missesI+io_iMiss;
                if(io_dWalk)ptesD=ptesD+1;if(io_iWalk)ptesI=ptesI+1;
                if(io_dDemand)physicalD=physicalD+1;
                if(memReply) pendingD=0;
                if(iMemReply) pendingI=0;
                if(memFire)begin
                    if(pendingD)fail("more than one physical D owner");
                    if(io_dWalk||io_iWalk)begin
                        if(io_memory_request_bits_write || io_memory_request_bits_size!=3 ||
                            io_memory_request_bits_address[2:0]!=0 ||
                            !pmpAllowed(io_memory_request_bits_address,3,1,0,0))fail("PTW geometry/PMP oracle");
                    end else begin
                        if(!outstandingD || expectPageD ||
                            (expectErrorD && io_memory_request_bits_address!=faultAddress) ||
                            !pmpAllowed(io_memory_request_bits_address,3,io_dataPrivilege,0,io_memory_request_bits_write) ||
                            io_memory_request_bits_address!==expectPaD ||
                            io_memory_request_bits_write!==expectWriteD) fail($sformatf("independent D physical address/operation oracle got=%h expected=%h",io_memory_request_bits_address,expectPaD));
                        if(expectWriteD)begin
                            if(io_memory_request_bits_data!==expectWriteDataD || io_memory_request_bits_mask!=255)fail("store data/mask oracle");
                            if(io_memory_request_bits_address!=faultAddress)
                                actualData[dataIndex(io_memory_request_bits_address)]=io_memory_request_bits_data;
                        end
                    end
                    returnD=memoryRead(io_memory_request_bits_address);
                    returnErrorD=io_memory_request_bits_address==faultAddress;
                    pendingD=1;dueD=cycles+latency;maxDOwners=1;
                end
                if(iMemFire)begin
                    if(pendingI || !outstandingI || expectPageI ||
                        (expectErrorI && io_instructionMemory_request_bits_address!=faultAddress) ||
                        !pmpAllowed(io_instructionMemory_request_bits_address,2,io_privilege,1,0) ||
                        io_instructionMemory_request_bits_address!==expectPaI || io_instructionMemory_request_bits_write)
                        fail("independent I physical address/owner oracle");
                    returnI=memoryRead(io_instructionMemory_request_bits_address);
                    returnErrorI=io_instructionMemory_request_bits_address==faultAddress;
                    pendingI=1;dueI=cycles+latency;physicalI=physicalI+1;
                end
                if(replyD)begin
                    if(!outstandingD || io_dResponse_bits_error!==expectErrorD || io_dResponse_bits_pageFault!==expectPageD)
                        fail($sformatf("D exception oracle got=%b/%b expected=%b/%b va=%h",io_dResponse_bits_error,io_dResponse_bits_pageFault,expectErrorD,expectPageD,io_dRequest_bits_address));
                    if(!expectErrorD && !expectWriteD && io_dResponse_bits_data!==expectDataD)fail("D load/copy data oracle");
                    if(!expectErrorD && expectWriteD)expectedData[dataIndex(expectPaD)]=expectWriteDataD;
                    outstandingD=0;repliesD=repliesD+1;checks=checks+1;
                end
                if(replyI)begin
                    if(!outstandingI || io_iResponse_bits_error!==expectErrorI || io_iResponse_bits_pageFault!==expectPageI)
                        fail("I exception oracle");
                    if(!expectErrorI && io_iResponse_bits_data!==expectDataI)fail("I return data oracle");
                    outstandingI=0;repliesI=repliesI+1;checks=checks+1;
                end
            end
            #1;clock=1;#5;clock=0;cycles=cycles+1;
            if(fireD)begin io_dRequest_valid=0;offeredD=0;end
            if(fireI)begin io_iRequest_valid=0;offeredI=0;end
            if(cycles>3000000)fail("bounded trace timeout");
        end
    endtask
    task automatic invalidate;
        begin
            if(outstandingD||outstandingI||pendingD||pendingI)fail("idle invalidation expected");
            io_invalidate=1;tick();io_invalidate=0;
        end
    endtask
    task automatic offerD(input [63:0] va,input bit writing,input [63:0] data);
        begin
            if(outstandingD||offeredD)fail("software D ownership");
            oracle(va,writing,0,expectPaD,expectErrorD,expectPageD);
            expectWriteD=writing;expectWriteDataD=data;
            expectDataD=expectErrorD ? 0 : expectedData[dataIndex(expectPaD)];
            if(negative && !expectErrorD)expectPaD=expectPaD^64'h1000;
            io_dRequest_bits_address=va;io_dRequest_bits_write=writing;io_dRequest_bits_data=data;
            io_dRequest_valid=1;offeredD=1;
        end
    endtask
    task automatic offerI(input [63:0] va);
        begin
            if(outstandingI||offeredI)fail("software I ownership");
            oracle(va,0,1,expectPaI,expectErrorI,expectPageI);
            expectDataI=pattern(expectPaI);io_iRequest_bits_address=va;io_iRequest_valid=1;offeredI=1;
        end
    endtask
    task automatic drain;
        integer guard;
        begin guard=0;
            while(offeredD||offeredI||outstandingD||outstandingI||pendingD||pendingI)begin
                tick();guard=guard+1;if(guard>300)fail("transaction deadlock");end
        end
    endtask
    task automatic transactionD(input [63:0] va,input bit writing,input [63:0] data);
        begin offerD(va,writing,data);drain();end
    endtask
    task automatic transactionI(input [63:0] va);
        begin offerI(va);drain();end
    endtask
    task automatic mapPage(input [63:0] va,input [63:0] pa,input [7:0] flags);
        reg [63:0] vpn,tableAddress;
        begin
            vpn=va>>12;tableAddress=TABLES+((vpn>>9)&511)*4096;
            pageMemory[(ROOT+((vpn>>18)&511)*8)>>3]=pte(L1,1);
            pageMemory[(L1+((vpn>>9)&511)*8)>>3]=pte(tableAddress,1);
            pageMemory[(tableAddress+(vpn&511)*8)>>3]=pte(pa,flags);
        end
    endtask
    task automatic tables(input integer pages,input integer stepPages);
        integer j;
        begin
            for(j=0;j<262144;j=j+1)pageMemory[j]=0;
            for(j=0;j<128;j=j+1)begin
                actualData[j]=pattern(DPA+(j/2)*4096+(j%2)*8);expectedData[j]=actualData[j];end
            io_satp=64'h8000000000000000|(ROOT>>12);io_privilege=1;io_dataPrivilege=1;
            io_sum=0;io_mxr=0;io_pmpConfig=15;io_pmpTop=64'h90000000>>2;faultAddress=~64'd0;
            for(j=0;j<pages;j=j+1)begin
                mapPage(DVA+j*stepPages*4096,DPA+j*4096,8'hcf);
                mapPage(IVA+j*stepPages*4096,IPA+j*4096,8'hcf);
            end
            workingPages=pages;workingStride=stepPages;invalidate();
        end
    endtask
    task automatic snapshot;
        begin startCycles=cycles;startAD=acceptsD;startAI=acceptsI;startHD=hitsD;startHI=hitsI;
            startMD=missesD;startMI=missesI;startSD=slowD;startSI=slowI;startPD=ptesD;startPI=ptesI;
            startDD=physicalD;startDI=physicalI;end
    endtask
    task automatic row(input string phase,input integer pages,input integer stepPages,input integer operation,input integer compete);
        begin
            $display("CAPACITY,%s,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                phase,pages,stepPages,operation,compete,cycles-startCycles,acceptsD-startAD,acceptsI-startAI,
                hitsD-startHD,hitsI-startHI,missesD-startMD,missesI-startMI,slowD-startSD,slowI-startSI,
                ptesD-startPD,ptesI-startPI,physicalD-startDD,physicalI-startDI,latency);
        end
    endtask
    initial begin
        // Inputs unused by this scalar-only fixture are explicitly zeroed.
`include "initialize.svh"
        negative=$test$plusargs("negative");
        io_dRequest_bits_size=3;io_dRequest_bits_mask=255;
        io_iRequest_bits_size=2;io_iRequest_bits_mask=0;
        reset=1;tick();tick();reset=0;
        // Same fixed traces for every capacity and banking selection.
        for(competition=0;competition<2;competition=competition+1)
        for(stride=1;stride<=1024;stride=stride*1024)
        for(op=0;op<3;op=op+1)
        for(n=1;n<=64;n=(n==1?4:n*2))begin
            stallMode=0;tables(n,stride);
            for(rep=0;rep<2;rep=rep+1)begin
                snapshot();
                for(roundIndex=0;roundIndex<(rep==0?1:3);roundIndex=roundIndex+1)
                for(pageIndex=0;pageIndex<n;pageIndex=pageIndex+1)begin
                    if(competition)offerI(IVA+pageIndex*stride*4096);
                    offerD(DVA+pageIndex*stride*4096,op==1,64'h12340000+pageIndex+roundIndex);
                    drain();
                    if(op==2)begin
                        copyData=expectedData[pageIndex*2];
                        transactionD(DVA+((pageIndex+n/2)%n)*stride*4096+8,1,copyData);
                    end
                end
                row(rep==0?"cold":"warm",n,stride,op,competition);
            end
        end
        // Independent correctness oracles with request/response backpressure.
        stallMode=1;tables(4,1);
        transactionD(DVA,0,0);transactionI(IVA);
        // Permissions: R/W/X/U/A/D, SUM/MXR and non-canonical addresses.
        for(which=0;which<8;which=which+1)begin
            tables(4,1);
            case(which)
                0:mapPage(DVA,DPA,8'hc5); // reserved W without R
                1:mapPage(DVA,DPA,8'hc9); // execute-only, MXR off
                2:mapPage(DVA,DPA,8'h8f); // A clear
                3:mapPage(DVA,DPA,8'h4f); // D clear
                4:mapPage(DVA,DPA,8'hdf); // U page, SUM off
                5:begin mapPage(DVA,DPA,8'hc9);io_mxr=1;end
                6:begin mapPage(DVA,DPA,8'hdf);io_sum=1;end
                7:io_dataPrivilege=0;
            endcase
            invalidate();transactionD(DVA,which==3,64'h55);transactionD(DVA,which==3,64'h55);
        end
        tables(4,1);transactionD(64'h0000008000000000,0,0);
        mapPage(IVA,IPA,8'hc7);invalidate();transactionI(IVA);
        mapPage(IVA,IPA,8'hdf);invalidate();io_sum=1;transactionI(IVA);
        // Source replacement: page 0 and page 1024 share all tested indices.
        tables(2,1024);transactionD(DVA,0,0);transactionD(DVA+4194304,1,64'h55);
        transactionD(DVA,0,0);transactionD(DVA+4194304,0,0);
        transactionI(IVA);transactionI(IVA+4194304);transactionI(IVA);
        // SFENCE remap and context-root switch explicitly invalidate old proofs.
        tables(4,1);transactionD(DVA,0,0);mapPage(DVA,DPA+4096,8'hcf);invalidate();transactionD(DVA,0,0);
        pageMemory[64'h12008>>3]=pte(64'h13000,1);pageMemory[64'h13000>>3]=pte(64'h14000,1);
        pageMemory[64'h14000>>3]=pte(DPA+8192,8'hcf);
        io_satp=64'h8000000000000012;invalidate();transactionD(DVA,0,0);
        // A fence during a walk must not resurrect a cached translation afterward.
        tables(4,1);offerD(DVA,0,0);t=ptesD;
        while(ptesD==t)tick();io_invalidate=1;tick();io_invalidate=0;drain();
        t=ptesD;transactionD(DVA,0,0);if(ptesD-t!=3)fail("in-flight fence resurrected old proof");
        // Dynamic context permission checks do not require a fence.
        tables(4,1);mapPage(DVA,DPA,8'hdf);io_sum=1;transactionD(DVA,0,0);
        io_sum=0;transactionD(DVA,0,0);io_sum=1;transactionD(DVA,0,0);
        io_dataPrivilege=0;transactionD(DVA,0,0);io_dataPrivilege=1;
        mapPage(DVA,DPA,8'hc9);invalidate();io_mxr=1;transactionD(DVA,0,0);
        io_mxr=0;transactionD(DVA,0,0);io_mxr=1;transactionD(DVA,0,0);
        // PMP epoch revokes cached full-page write permissions; PTW remains readable.
        tables(4,1);transactionD(DVA,1,64'h1122);io_pmpConfig=13;invalidate();transactionD(DVA,1,64'h3344);
        io_pmpConfig=15;invalidate();transactionD(DVA,1,64'h5566);
        // PTE bus error and physical bus error must not report page fault.
        tables(4,1);faultAddress=ROOT+8;invalidate();transactionD(DVA,0,0);
        tables(4,1);faultAddress=DPA;invalidate();transactionD(DVA,0,0);
        // Concurrent I+D with full response stalls and conflict replacements.
        tables(8,1024);
        for(k=0;k<24;k=k+1)begin offerD(DVA+(k%8)*4194304,k%3==0,k);offerI(IVA+(k%8)*4194304);drain();end
        if(acceptsD!=repliesD || acceptsI!=repliesI || maxDOwners!=1)fail("final ownership accounting");
        $display("I1_TLB_CAPACITY_PASS checks=%0d cycles=%0d d=%0d i=%0d pteD=%0d pteI=%0d maxPhysicalDOwners=%0d",
            checks,cycles,repliesD,repliesI,ptesD,ptesI,maxDOwners);$finish;
    end
endmodule
