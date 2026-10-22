; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Static 320x224 indexed graphics probes. No game scheduler.
; Palette at CODE_BYTES; following assets depend on the selected probe.
        cpu 186
        org 0
%ifndef CODE_BYTES
%define CODE_BYTES 1000h
%endif
%ifdef NATIVE_RENDER
%include "patch.inc"
%elifdef SGP_CACHE
%include "patch.inc"
%elifdef TWO_PLANES
%include "patch.inc"
%elifdef PACKED_PROBE
%include "patch.inc"
%endif
start:  cli
        mov ax,cs
        mov ds,ax
        mov es,ax
        mov ss,ax
        mov sp,0fffeh
        cld
        sti
        mov dx,01cbh
        in al,dx
        test al,8
        jnz wrong_monitor
        mov ax,1702h
        int 83h
        ; Use the established single-plane BIOS setup, then select 8bpp.
        mov ah,0
        mov bh,0a0h
        mov bl,0ah
        mov cx,0404h
        xor dx,dx
        int 8fh
        or ax,ax
        jnz failed
        mov di,fb_desc
        mov ax,0100h
        mov cx,1
        int 8fh
        or ax,ax
        jnz failed
        mov ax,0b01h
        int 8fh
        mov ah,16h
        int 84h
        mov ax,0500h
        xor cx,cx
        xor bx,bx
        xor dx,dx
        int 8fh
        mov ax,0b01h
        int 8fh
        cli
        push cs
        pop ds
        mov dx,0153h
        in al,dx
        and al,0f0h
        or al,4
        out dx,al
        mov dx,0580h
        mov al,10h
        out dx,al
        mov dx,0102h
        in ax,dx
        and ax,0fffch
        or ax,2                 ; G0: 8bpp, preserve 320-dot selection
        out dx,ax
        mov dx,0106h
        mov ax,000ah            ; G0 only, palette-indexed composition
        out dx,ax
        mov dx,0108h
        xor ax,ax               ; no direct-colour screens
        out dx,ax
        mov dx,010ah
        out dx,ax
        mov dx,0124h            ; G0 transparency mask: none
        out dx,ax
        mov dx,010ch
        mov ax,01c0h            ; palette mode 3, no blink
        out dx,ax
        mov dx,0200h            ; FB0 descriptor, all word writes
        mov si,fb_regs
        mov cx,16
.regs:  lodsw
        out dx,ax
        add dx,2
        loop .regs
        mov dx,0300h
        mov si,CODE_BYTES
        mov cx,32
.pal:   lodsw
        out dx,ax
        add dx,2
        loop .pal
%ifdef NATIVE_RENDER
%ifdef VIDEO_GUARDS
        call video_guard_init
%endif
        call native_init
native_begin:
        call native_render
native_end:
%ifdef NATIVE_PLANES
        call planes_present
%endif
%ifdef VIDEO_GUARDS
        call video_guard_check
%endif
%ifdef NEXT_STATE
        mov word [next_source],N_NEXT
        mov word [next_left],NEXT_COUNT
native_load_next:
        push cs
        pop es
        mov si,[next_source]
%ifdef NEXT_DELTA
.delta: lodsw
        cmp ax,0ffffh
        je .ready
        mov bx,ax
        lodsb
        mov [N_VRAM + bx],al
        jmp .delta
.ready:
%else
        mov di,N_VRAM
        mov cx,708
        rep movsw
%endif
        mov [next_source],si
native_next_begin:
        call native_render
native_next_end:
%ifdef NATIVE_PLANES
        call planes_present
%endif
%ifdef VIDEO_GUARDS
        call video_guard_check
%endif
        dec word [next_left]
        jnz native_load_next
%endif
        jmp screen_drawn
%else
        mov ax,0a000h
        mov es,ax
        xor di,di
        ; A 320x224 byte image crosses a 64 KiB segment boundary.
.run:   lodsb
        xor cx,cx
        mov cl,al
        jcxz screen_drawn
        lodsb
.pixel: stosb
        or di,di
        jnz .next
        mov bx,es
        add bx,1000h
        mov es,bx
.next:  loop .pixel
        jmp .run
%endif
screen_drawn:
        mov si,sync224
        mov al,10h
        call tsp_cmd
        mov cx,14
.param: lodsb
        call tsp_prm
        loop .param
%ifdef PACKED_PROBE
        call packed_probe
%endif
%ifdef TWO_PLANES
        call two_planes
%endif
%ifdef SGP_BENCH
        call sgp_benchmark
%endif
%ifdef SGP_DIRECTION
        call sgp_direction
%endif
%ifdef SGP_CACHE
        call sgp_cache_test
%endif
%ifdef PAGE_TEST
        call page_test
%endif
halt:   hlt
        jmp halt
wrong_monitor:
        mov si,s_monitor
        jmp message
failed: mov si,s_fail
message:
        lodsb
        or al,al
        jz halt
        xor ah,ah
        mov dx,ax
        int 83h
        jmp message

tsp_cmd:
        mov ah,al
        mov dx,0142h
.wait:  in al,dx
        test al,5
        jnz .wait
        mov al,ah
        out dx,al
        ret
tsp_prm:
        mov ah,al
        mov dx,0142h
.wait:  in al,dx
        test al,1
        jnz .wait
        mov al,ah
        mov dx,0146h
        out dx,al
        ret
%ifdef NATIVE_RENDER
%include "native.inc"
%ifdef VIDEO_GUARDS
%include "memory_guard.inc"
%endif
%ifdef NATIVE_SGP
%include "native_sgp.inc"
%endif
%ifdef NATIVE_PLANES
%include "native_planes.inc"
%endif
%endif
%ifdef SGP_BENCH
%include "sgp_bench.inc"
%elifdef SGP_DIRECTION
%include "sgp_bench.inc"
%elifdef SGP_CACHE
%include "sgp_bench.inc"
%endif
%ifdef SGP_DIRECTION
%include "sgp_direction.inc"
%elifdef SGP_CACHE
%include "sgp_direction.inc"
%include "sgp_cache.inc"
%endif
%ifdef TWO_PLANES
%include "two_planes.inc"
%endif
%ifdef PACKED_PROBE
%include "packed_probe.inc"
%endif
%ifdef PAGE_TEST
; Three 71680-byte areas: 00000h, 11800h, 23000h. Only G0 is enabled.
; REP MOVSW crosses neither source nor destination segment in each chunk.
copy_page:
        push ds
        xor si,si
        xor di,di
        mov ax,0a000h
        mov ds,ax
        mov cx,8000h
        rep movsw
        mov ax,0b000h
        mov ds,ax
        mov ax,es
        add ax,1000h
        mov es,ax
        mov cx,0c00h
        rep movsw
        pop ds
        ret
page_test:
        ; Extend the virtual framebuffer to contain all three pages.
        mov dx,0206h
        mov ax,672
        out dx,ax
        xor ax,ax
        mov es,ax
        mov word [es:0ah * 4],page_vrtc
        mov [es:0ah * 4 + 2],cs
        mov dx,018ah
        mov al,0fbh
        out dx,al
        sti
        mov ax,0b180h
        mov es,ax
copy_begin:
        call copy_page
copy_end:
        mov ax,0c300h
        mov es,ax
        call copy_page
        ; Distinguish pages without relying on palette entries being unique.
        mov ax,0b180h
        mov es,ax
        mov di,321
        mov ax,0101h
        stosw
        mov ax,0c300h
        mov es,ax
        mov di,321
        mov ax,0202h
        stosw
        mov word [next_flip],0
page_loop:
        mov ax,[ticks]
        sub ax,[next_flip]
        js page_loop
        mov ax,[ticks]
        add ax,60
        mov [next_flip],ax
        xor bx,bx
        mov bl,[page]
        shl bx,2
        cli
        mov dx,020eh
        mov ax,[page_dsa + bx]
        out dx,ax
        mov dx,0210h
        mov ax,[page_dsa + bx + 2]
        out dx,ax
        sti
page_shown:
        inc byte [page]
        cmp byte [page],3
        jb page_loop
        mov byte [page],0
        jmp page_loop
page_vrtc:
        push ax
        push dx
        inc word [cs:ticks]
        mov dx,0188h
        mov al,20h
        out dx,al
        pop dx
        pop ax
        iret
ticks dw 0
next_flip dw 0
page db 0
page_dsa dd 0,11800h,23000h
%endif
%ifdef NEXT_STATE
next_source dw 0
next_left dw 0
%endif
sync224 db 0c1h,57h,1ch,0,9fh,0,10h,0fh,25h,0,0e0h,0,2,4
fb_desc dw 4,320,224,0,0,0
; FSA low/high, FBW, FBL, reserved, OFX, OFY, DSA low/high,
; DSH, reserved, DSP, remaining reserved words
fb_regs dw 0,0,320,224,0,0,0,0,0,224,0,0,0,0,0,0
s_monitor db 'The Game DD M02: select 15 kHz before boot.',13,10,0
s_fail db 'The Game DD M02: graphics BIOS error.',13,10,0
        times CODE_BYTES-($-$$) db 0
