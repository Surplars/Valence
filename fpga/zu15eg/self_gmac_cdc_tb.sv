`timescale 1ns/1ps
// User-authorized CDC-only RTL check. Clock-pause model is TESTBENCH ONLY;
// production gating must use a dedicated glitchless clock resource.
module self_gmac_cdc_tb;
  reg controlClock=0, txRaw=0, rxRaw=0, commonReset=1;
  real controlHalf=5, txHalf=4, rxHalf=4;
  reg txGate=1, rxGate=1, controlPause=0, rxPause=0;
  wire clockEnable;
  wire txClock=txRaw && txGate, rxClock=rxRaw && rxGate;
  initial forever begin #(controlHalf); if (!controlPause) controlClock=~controlClock; end
  initial begin #1.125; forever #(txHalf) txRaw=~txRaw; end
  initial begin #2.375; forever #(rxHalf) rxRaw=~rxRaw; end
  always @(negedge txRaw) txGate=clockEnable;
  always @(negedge rxRaw) rxGate=!rxPause;
  reg txIn_valid=0, txOut_ready=0, rxIn_valid=0, rxOut_ready=0;
  wire txIn_ready, txOut_valid, rxIn_ready, rxOut_valid;
  reg [31:0] txIn_bits_data=0, rxIn_bits_data=0;
  reg [3:0] txIn_bits_keep=0, rxIn_bits_keep=0;
  reg txIn_bits_last=0, txIn_bits_bad=0, rxIn_bits_last=0, rxIn_bits_bad=0;
  wire [31:0] txOut_bits_data, rxOut_bits_data;
  wire [3:0] txOut_bits_keep, rxOut_bits_keep;
  wire txOut_bits_last, txOut_bits_bad, rxOut_bits_last, rxOut_bits_bad;
  reg configIn_valid=0, configTx_ready=0, configRx_ready=0;
  wire configIn_ready, configTx_valid, configRx_valid;
  reg [47:0] configIn_bits_macAddress=0;
  reg configIn_bits_txEnable=0, configIn_bits_rxEnable=0;
  reg configIn_bits_promiscuous=0, configIn_bits_broadcastEnable=0;
  wire [47:0] configTx_bits_macAddress, configRx_bits_macAddress;
  wire configTx_bits_txEnable, configTx_bits_rxEnable, configTx_bits_promiscuous, configTx_bits_broadcastEnable;
  wire configRx_bits_txEnable, configRx_bits_rxEnable, configRx_bits_promiscuous, configRx_bits_broadcastEnable;
  reg [15:0] txIncrement=0, rxIncrement=0;
  reg txDelta_ready=0, rxDelta_ready=0;
  wire txDelta_valid, rxDelta_valid;
  wire [15:0] txDelta_bits, rxDelta_bits;
  reg stopRequest=0, wake=0, clearFault=0, localIdle=1;
  wire quiesce, stopAdmission, isolate, allowAdmission, stopped, fault;
  wire txSourceIdle, txDestinationIdle;
  SelfGmacCdcTop dut(.*);
  integer phase=0, epoch=1, controlCycles=0, txCycles=0, rxCycles=0;
  integer txSent=0, txReceived=0, rxSent=0, rxReceived=0;
  integer configSent=0, txConfigured=0, rxConfigured=0;
  integer txTarget=2048, rxTarget=2048, configTarget=64;
  integer txTotal=0, rxTotal=0, txCounted=0, rxCounted=0;
  integer fullStalls=0, outputStalls=0, cfgStalls=0, eventStalls=0;
  integer txEdges=0, txHoldCycles=0;
  reg txHeld=0, rxHeld=0, cfgTxHeld=0, cfgRxHeld=0, txEventHeld=0, rxEventHeld=0;
  reg [37:0] txPrevious, rxPrevious;
  reg [51:0] cfgTxPrevious, cfgRxPrevious;
  reg [15:0] txEventPrevious, rxEventPrevious;
  string injection;
  bit eventInjected=0;
  function automatic [31:0] dataOf(input integer n, input bit receivePath);
    dataOf=32'hc123abcd ^ (32'h01020305*n) ^ (epoch*32'h10200400) ^ (receivePath ? 32'hace01234 : 0);
  endfunction
  function automatic [3:0] keepOf(input integer n);
    keepOf=n%11==10 ? ((1 << (n%4+1))-1) : 4'hf;
  endfunction
  function automatic [37:0] beatOf(input integer n, input bit receivePath);
    beatOf={dataOf(n,receivePath),keepOf(n),1'(n%11==10),1'(n%11==10 && n%3==0)};
  endfunction
  function automatic [51:0] configOf(input integer n);
    configOf={48'h021122334455 ^ (48'h010305070911*n) ^ 48'(epoch),4'(n%16)};
  endfunction
  always @(negedge controlClock) begin
    txIn_valid=!commonReset && controlCycles>8 && txSent<txTarget && phase!=0;
    {txIn_bits_data,txIn_bits_keep,txIn_bits_last,txIn_bits_bad}=beatOf(txSent,0);
    rxOut_ready=!commonReset && (phase!=1 || (controlCycles>100 && controlCycles%101>=25 && controlCycles%5!=1));
    configIn_valid=!commonReset && controlCycles>8 && configSent<configTarget && phase==1;
    {configIn_bits_macAddress,configIn_bits_txEnable,configIn_bits_rxEnable,
      configIn_bits_promiscuous,configIn_bits_broadcastEnable}=configOf(configSent);
    txDelta_ready=!commonReset && (phase!=1 || controlCycles%191>100);
    rxDelta_ready=!commonReset && (phase!=1 || controlCycles%211>130);
  end
  always @(negedge txClock) begin
    txOut_ready=!commonReset && (phase==2 ? 0 : (phase!=1 || (txCycles>100 && txCycles%97>=24 && txCycles%5!=0)));
    configTx_ready=!commonReset && (phase!=1 || txCycles%13>=4);
    txIncrement=!commonReset && txCycles>8 && phase==1 ? (txCycles%5==0 ? 147 : 31) : 0;
  end
  always @(negedge rxClock) begin
    rxIn_valid=!commonReset && rxCycles>8 && rxSent<rxTarget && phase==1;
    {rxIn_bits_data,rxIn_bits_keep,rxIn_bits_last,rxIn_bits_bad}=beatOf(rxSent,1);
    configRx_ready=!commonReset && (phase!=1 || rxCycles%199>130);
    rxIncrement=!commonReset && rxCycles>8 && phase==1 ? (rxCycles%7==0 ? 129 : 17) : 0;
  end
  always @(posedge controlClock or posedge commonReset) begin
    if (commonReset) begin
      controlCycles=0; txSent=0; rxReceived=0; configSent=0; txCounted=0; rxCounted=0;
      rxHeld=0; txEventHeld=0; rxEventHeld=0; fullStalls=0; eventStalls=0; eventInjected=0;
    end else begin
      controlCycles++;
      if (rxHeld && (!rxOut_valid || {rxOut_bits_data,rxOut_bits_keep,rxOut_bits_last,rxOut_bits_bad}!==rxPrevious))
        $fatal(1,"native RX CDC changed under backpressure");
      rxHeld=rxOut_valid && !rxOut_ready;
      rxPrevious={rxOut_bits_data,rxOut_bits_keep,rxOut_bits_last,rxOut_bits_bad};
      if (txEventHeld && (!txDelta_valid || txDelta_bits!==txEventPrevious)) $fatal(1,"event delta unstable");
      if (rxEventHeld && (!rxDelta_valid || rxDelta_bits!==rxEventPrevious)) $fatal(1,"event delta unstable");
      txEventHeld=txDelta_valid && !txDelta_ready; txEventPrevious=txDelta_bits;
      rxEventHeld=rxDelta_valid && !rxDelta_ready; rxEventPrevious=rxDelta_bits;
      if (txIn_valid && txIn_ready) txSent++;
      if (txIn_valid && !txIn_ready) fullStalls++;
      if (configIn_valid && configIn_ready) configSent++;
      if (rxOut_valid && rxOut_ready) begin
        if (rxReceived>=rxSent || rxPrevious!==beatOf(rxReceived,1)) $fatal(1,"native RX CDC independent scoreboard mismatch");
        rxReceived++;
      end
      if (txDelta_valid && txDelta_ready) begin
        txCounted+=txDelta_bits;
        if (injection=="event" && !eventInjected) begin txCounted++; eventInjected=1; end
        if (txCounted>txTotal) $fatal(1,"event accumulation independent scoreboard mismatch");
      end
      if (rxDelta_valid && rxDelta_ready) begin
        rxCounted+=rxDelta_bits;
        if (rxCounted>rxTotal) $fatal(1,"event accumulation independent scoreboard mismatch");
      end
      if (txEventHeld || rxEventHeld) eventStalls++;
      if (!clockEnable && (!quiesce || !isolate || allowAdmission)) $fatal(1,"clock stop isolation/admission invariant");
    end
  end
  always @(posedge txClock or posedge commonReset) begin
    if (commonReset) begin
      txCycles=0; txReceived=0; txConfigured=0; txTotal=0; txHeld=0; cfgTxHeld=0;
      txEdges=0; outputStalls=0; cfgStalls=0;
    end else begin
      txCycles++; txEdges++;
      txTotal+=txIncrement;
      if (txHeld && (!txOut_valid || {txOut_bits_data,txOut_bits_keep,txOut_bits_last,txOut_bits_bad}!==txPrevious))
        $fatal(1,"native TX CDC changed under backpressure");
      txHeld=txOut_valid && !txOut_ready;
      txPrevious={txOut_bits_data,txOut_bits_keep,txOut_bits_last,txOut_bits_bad};
      if (cfgTxHeld && (!configTx_valid || {configTx_bits_macAddress,configTx_bits_txEnable,configTx_bits_rxEnable,
          configTx_bits_promiscuous,configTx_bits_broadcastEnable}!==cfgTxPrevious)) $fatal(1,"atomic config unstable");
      cfgTxHeld=configTx_valid && !configTx_ready;
      cfgTxPrevious={configTx_bits_macAddress,configTx_bits_txEnable,configTx_bits_rxEnable,
        configTx_bits_promiscuous,configTx_bits_broadcastEnable};
      if (txOut_valid && txOut_ready) begin
        if (txReceived>=txSent || txPrevious!==(beatOf(txReceived,0) ^
            (injection=="frame" && txReceived==31 ? 38'h1 : 38'h0)))
          $fatal(1,"native TX CDC independent scoreboard mismatch");
        txReceived++;
      end
      if (configTx_valid && configTx_ready) begin
        if (txConfigured>=configSent || cfgTxPrevious!==(configOf(txConfigured) ^
            (injection=="config" && txConfigured==3 ? 52'h10 : 52'h0)))
          $fatal(1,"atomic config independent scoreboard mismatch");
        txConfigured++;
      end
      if (txHeld) outputStalls++;
      if (cfgTxHeld) cfgStalls++;
    end
  end
  always @(posedge rxClock or posedge commonReset) begin
    if (commonReset) begin
      rxCycles=0; rxSent=0; rxConfigured=0; rxTotal=0; cfgRxHeld=0;
    end else begin
      rxCycles++; rxTotal+=rxIncrement;
      if (rxIn_valid && rxIn_ready) rxSent++;
      if (cfgRxHeld && (!configRx_valid || {configRx_bits_macAddress,configRx_bits_txEnable,configRx_bits_rxEnable,
          configRx_bits_promiscuous,configRx_bits_broadcastEnable}!==cfgRxPrevious)) $fatal(1,"atomic config unstable");
      cfgRxHeld=configRx_valid && !configRx_ready;
      cfgRxPrevious={configRx_bits_macAddress,configRx_bits_txEnable,configRx_bits_rxEnable,
        configRx_bits_promiscuous,configRx_bits_broadcastEnable};
      if (configRx_valid && configRx_ready) begin
        if (rxConfigured>=configSent || cfgRxPrevious!==configOf(rxConfigured))
          $fatal(1,"atomic config independent scoreboard mismatch");
        rxConfigured++;
      end
    end
  end
  task automatic controlWait(input integer cycles);
    repeat(cycles) @(negedge controlClock);
  endtask
  task automatic resetEpoch(input integer nextEpoch);
    phase=0; stopRequest=0; wake=0; clearFault=0; localIdle=1;
    controlPause=0; rxPause=0; commonReset=1; epoch=nextEpoch;
    #120; @(negedge controlClock); commonReset=0;
    controlWait(10);
  endtask
  task automatic waitDrain;
    integer budget;
    begin
      budget=0;
      while (txReceived!=txTarget || rxReceived!=rxTarget || txConfigured!=configTarget || rxConfigured!=configTarget) begin
        controlWait(1); budget++;
        if (budget>100000) $fatal(1,"CDC transfer drain timeout");
      end
      phase=0;
      controlWait(20);
      budget=0;
      while (txCounted!=txTotal || rxCounted!=rxTotal) begin
        controlWait(1); budget++;
        if (budget>5000) $fatal(1,"event accumulation independent scoreboard mismatch");
      end
      if (!fullStalls || !outputStalls || !cfgStalls || !eventStalls || txTotal<65536 || rxTotal<65536)
        $fatal(1,"CDC coverage missing stalls or counter wrap");
    end
  endtask
  task automatic waitStopped;
    integer budget;
    begin
      budget=0;
      while (!stopped) begin controlWait(1); budget++; if (budget>220) $fatal(1,"clock stop timeout"); end
      controlWait(10);
      txHoldCycles=txEdges;
      controlWait(25);
      if (txEdges!=txHoldCycles || clockEnable || !isolate || allowAdmission || injection=="clock")
        $fatal(1,"clock stop independent scoreboard mismatch");
    end
  endtask
  task automatic wakeDomain;
    integer budget;
    begin
      wake=1; stopRequest=0;
      budget=0;
      while (!allowAdmission) begin controlWait(1); budget++; if (budget>220) $fatal(1,"clock wake timeout"); end
      if (!clockEnable || isolate) $fatal(1,"clock wake did not release isolation");
      wake=0;
      controlWait(10);
      if (txEdges<=txHoldCycles) $fatal(1,"wake did not restore actual domain edges");
    end
  endtask
  integer n;
  initial begin
    injection="";
    if ($test$plusargs("inject_frame")) injection="frame";
    if ($test$plusargs("inject_config")) injection="config";
    if ($test$plusargs("inject_event")) injection="event";
    if ($test$plusargs("inject_clock")) injection="clock";
    for (n=0;n<4;n++) begin
      case(n)
        0: begin controlHalf=5; txHalf=4; rxHalf=4.5; end
        1: begin controlHalf=3; txHalf=11; rxHalf=7; end
        2: begin controlHalf=11; txHalf=3; rxHalf=4; end
        3: begin controlHalf=7; txHalf=4; rxHalf=13; end
      endcase
      txTarget=2048; rxTarget=2048; configTarget=64;
      resetEpoch(n+1); phase=1;
      controlWait(140);
      // Stop destination control edges while media events keep accumulating.
      @(negedge controlClock); controlPause=1; #1000; controlPause=0;
      rxPause=1; #500; rxPause=0;
      waitDrain();
      $display("CDC_CASE_PASS case=%0d tx=%0d rx=%0d configs=%0d/%0d totals=%0d/%0d",n,txReceived,rxReceived,txConfigured,rxConfigured,txTotal,rxTotal);
    end
    // Pointer-empty is insufficient: hold a prefetched destination beat while
    // requesting stop. Clock must remain running until its output is consumed.
    phase=2; txTarget=2049;
    wait(txOut_valid); controlWait(15);
    if (!txSourceIdle || txDestinationIdle) $fatal(1,"prefetch/held-output idle coverage missing");
    stopRequest=1; localIdle=1;
    controlWait(30);
    if (!clockEnable || stopped || allowAdmission) $fatal(1,"clock stopped with held FIFO output");
    phase=3;
    waitStopped(); wakeDomain();
    // Drain busy engine, cancellation, watchdog and held STOP retry inhibition.
    localIdle=0; stopRequest=1; controlWait(30);
    if (!clockEnable || !quiesce) $fatal(1,"busy engine was clock-gated");
    wake=1; stopRequest=0; controlWait(15); wake=0;
    if (!allowAdmission || !clockEnable) $fatal(1,"wake did not cancel draining");
    stopRequest=1; controlWait(160);
    if (!fault || !clockEnable || !allowAdmission || quiesce) $fatal(1,"drain timeout did not fail open");
    clearFault=1; controlWait(1); clearFault=0; controlWait(150);
    if (fault || quiesce || !allowAdmission) $fatal(1,"held STOP retried after timeout");
    stopRequest=0; localIdle=1; controlWait(15); stopRequest=1;
    waitStopped(); wakeDomain();
    // Common cold reset cancels FIFO/mailbox/counter epochs, including a
    // destination stalled with a held output. Never reset one endpoint alone.
    resetEpoch(9); phase=2; txTarget=256; rxTarget=0; configTarget=0;
    wait(txOut_valid); controlWait(25);
    resetEpoch(10); txTarget=2048; rxTarget=2048; configTarget=64; phase=1;
    waitDrain();
    $display("SELF_GMAC_CDC_PASS clock_cases=4 bidirectional_beats=20480 config_copies=640 counter_wrap=1 paused_clocks=1 held_output_drain=1 stop_wake_timeout=1 coordinated_reset=1");
    $finish;
  end
  initial begin #20000000; $fatal(1,"CDC global timeout"); end
endmodule
