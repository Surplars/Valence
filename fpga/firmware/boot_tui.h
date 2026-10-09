#ifndef VALENCE_BOOT_TUI_H
#define VALENCE_BOOT_TUI_H
/* Small, allocation-free 80x24 UART frontend. No terminal query/negotiation:
 * a switches ANSI/plain, k toggles color. Never called in VLD1 receive mode. */
#ifdef BOOT_MENU
#ifndef BOOT_TUI_DEFAULT
#define BOOT_TUI_DEFAULT 1
#endif
static unsigned menu_color=1, menu_selected, menu_escape, menu_escape_bytes, menu_last_cr, menu_escape_timedout;
static uint64_t menu_escape_at, menu_progress_at;
static const char *menu_result="Choose a download; verified images start automatically.";
static unsigned menu_screen, menu_binary, menu_log_pending;
enum { MENU_NONE=-1, MENU_UP=256, MENU_DOWN, MENU_ENTER, MENU_ESC };
struct menu_item { unsigned char key; const char *label; };
static const struct menu_item menu_items[]={
#ifdef BOARD_NETBOOT
    {'n',"n/1  Network download + boot (TFTP)"},
#endif
    {'d',"d/2  UART download + boot (VLD1)"},
#ifdef BOARD_JTAG_DOWNLOAD
    {'j',"j    JTAG download + boot (host COMMIT)"},
#endif
    {'v',"v/3  Verify RAM image (read-only)"},
    {'C',"c/C/5  CoreMark formal (measured >10 seconds, all CRCs)"},
    {'b',"b/6  CPU bandwidth"},
    {'m',"m/7  Memory DMA bandwidth"},
    {'t',"t    Short bandwidth selftest"},
    {'u',"u/9  S-mode Bare / Sv39 MMU bandwidth"},
    {'i',"i/8  Hardware / firmware information"}
};
#define MENU_COUNT (sizeof(menu_items)/sizeof(menu_items[0]))
_Static_assert(MENU_COUNT<=10,"menu exceeds 80x24 action rows");
static void tui_number(unsigned n) {
    char b[10];unsigned k=0;do{b[k++]=(char)('0'+n%10);n/=10;}while(n);
    while(k)putc_uart((uint8_t)b[--k]);
}
static void tui_at(unsigned row) {puts_uart("\033[");tui_number(row);puts_uart(";1H");}
static void tui_line(const char *s) {
    unsigned n=0;putc_uart('|');
    while(*s&&n<76){unsigned char c=(unsigned char)*s++;putc_uart(c>=32&&c<127?c:' ');++n;}
    while(n++<76)putc_uart(' ');
    putc_uart('|');
}
static void tui_result(const char *s) {menu_result=s;}
static void tui_leave(void) {
    if(menu_ansi && menu_screen){menu_log_pending=1;puts_uart("\033[0m\033[r\033[?25h");tui_at(24);puts_uart("\r\n");}
    menu_screen=0;menu_escape=menu_escape_bytes=0;
}
static void show_menu(void) {
    static const char border[]="+----------------------------------------------------------------------------+";
    if(!menu_ansi){
        puts_uart("\r\nValence monitor | verified downloads auto-boot\r\n");
        for(unsigned i=0;i<MENU_COUNT;++i){puts_uart(menu_items[i].label);puts_uart("\r\n");}
        puts_uart("a ANSI TUI | h menu | g/r/4 retired (no manual launch)\r\n");
        puts_uart(menu_result);puts_uart("\r\n");
        if(external_state_untrusted)external_state_message();
        return;
    }
    /* Preserve the complete action transcript before clearing its viewport.
     * Standard CR/LF works on VT100; no alternate-screen scrollback assumption. */
    if(menu_log_pending){for(unsigned i=0;i<24;++i)puts_uart("\r\n");menu_log_pending=0;}
    puts_uart("\033[0m\033[r\033[2J\033[H\033[?25l");menu_screen=1;
    puts_uart(border);tui_at(2);
    if(menu_color)puts_uart("\033[36;1m");
    tui_line(" Valence BootROM | download, verify, boot");puts_uart("\033[0m");
    tui_at(3);tui_line(external_state_untrusted?" LOCKED: external application returned; board reset required":" READY: every new download invalidates the previous image");
    tui_at(4);puts_uart(border);
    for(unsigned i=0;i<10;++i){
        tui_at(5+i);
        if(i<MENU_COUNT){
            if(i==menu_selected)puts_uart(menu_color?"\033[44;37;1m":"\033[7m");
            tui_line(menu_items[i].label);puts_uart("\033[0m");
        }else tui_line("");
    }
    tui_at(15);puts_uart(border);
    tui_at(16);tui_line(" Up/Down: select   Enter: open   Esc/h: menu   shortcuts work directly");
    tui_at(17);tui_line(" a: plain terminal / ANSI   k: color on/off   Esc/Ctrl-C: cancel TFTP/JTAG");
    tui_at(18);puts_uart(border);
    tui_at(19);tui_line(" Last result:");
    tui_at(20);tui_line(menu_result);
    tui_at(21);tui_line(external_state_untrusted?" Only i/h/a/k remain available; peripheral ownership is unknown.":" UART binary transfer suppresses all TUI redraws and progress.");
    tui_at(22);tui_line(" Transfer and diagnostic detail remains in the terminal scrollback.");
    tui_at(23);tui_line(" No image is trusted after reset. No separate Run Image action.");
    tui_at(24);puts_uart(border);
}
static void tui_selection(unsigned previous) {
    if(!menu_ansi){show_menu();return;}
    tui_at(5+previous);tui_line(menu_items[previous].label);
    tui_at(5+menu_selected);puts_uart(menu_color?"\033[44;37;1m":"\033[7m");
    tui_line(menu_items[menu_selected].label);puts_uart("\033[0m");
}
/* Bound both the idle gap and sequence length; fragmented CSI/SS3 are accepted.
 * Unknown escape sequences are swallowed, never reinterpreted as shortcuts. */
static int menu_key(int c,uint64_t now) {
    /* Explicit recovery from a damaged/unclosed terminal control string. */
    if(c==3){menu_escape=menu_escape_bytes=menu_escape_timedout=0;return MENU_ESC;}
    if(menu_escape && !menu_escape_timedout && now-menu_escape_at>=CPU_HZ/5){
        if(menu_escape==1)menu_escape=0;
        else if(menu_escape==2||menu_escape==3)menu_escape=4;
        /* Incomplete CSI/control strings remain discard-only until terminated.
         * A timeout must not turn their payload into download shortcuts. */
        menu_escape_at=now;menu_escape_timedout=1;
        if(c<0)return MENU_ESC;
    }
    if(c<0)return MENU_NONE;
    if(menu_escape){
        menu_escape_at=now;menu_escape_timedout=0;
        if(menu_escape==5||menu_escape==6){
            if(c==7 || (menu_escape==6&&c=='\\'))menu_escape=0;
            else menu_escape=c==27?6:5;
            return MENU_NONE;
        }
        if(menu_escape==4){
            if(c>=0x40&&c<=0x7e)menu_escape=0;
            return MENU_NONE;
        }
        if(menu_escape==1){
            menu_escape=c=='['?2:c=='O'?3:(c==']'||c=='P'||c=='^'||c=='_')?5:
                (c>=0x20&&c<=0x2f)?4:0;
            return MENU_NONE;
        }
        if(++menu_escape_bytes>12){menu_escape=4;return MENU_NONE;}
        if(c=='A'||c=='B'){menu_escape=0;return c=='A'?MENU_UP:MENU_DOWN;}
        if(menu_escape==2 && c>=0x30&&c<=0x3f)return MENU_NONE;
        if(c>=0x40&&c<=0x7e)menu_escape=0;
        else menu_escape=4;
        return MENU_NONE;
    }
    if(c=='\n'&&menu_last_cr){menu_last_cr=0;return MENU_NONE;}
    menu_last_cr=c=='\r';
    if(c==27){menu_escape_timedout=0;menu_escape=1;menu_escape_at=now;menu_escape_bytes=0;return MENU_NONE;}
    if(c=='\r'||c=='\n')return MENU_ENTER;
    return c;
}
static void tui_progress(unsigned complete,unsigned total) {
    if(!menu_ansi||menu_binary||!total)return;
    uint64_t now=cycles();
    /* One short line per second, independent of payload block/packet count.
     * Called only after DMA is quiet, never from the network receive loop. */
    if(complete<total && now-menu_progress_at<CPU_HZ)return;
    menu_progress_at=now;
    puts_uart("\rVerify RAM [");unsigned bars=(unsigned)((uint64_t)complete*24/total);
    for(unsigned i=0;i<24;++i)putc_uart(i<bars?'#':'-');
    puts_uart("] ");tui_number((unsigned)((uint64_t)complete*100/total));puts_uart("%");
    if(complete==total)puts_uart("\r\n");
}
#else
#define tui_result(s) ((void)0)
#define tui_leave() ((void)0)
#define tui_progress(n,total) ((void)0)
#endif
#endif
