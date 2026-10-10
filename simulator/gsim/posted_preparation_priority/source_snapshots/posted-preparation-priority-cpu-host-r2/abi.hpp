#pragma once
// Generated GSIM folds startEviction to _startEviction_T_3 when WB=2.
// Both pinned FIRs prove: T4=and(side,0), T5=and(T4,retiring),
// T6=eq(T5,0), startEviction=and(T3,T6). This alias changes no check.
#define board$platform$privateCache$startEviction board$platform$privateCache$_startEviction_T_3
// No fake coherentHome$ownedLines alias: missing DMA4 is a profile blocker.
