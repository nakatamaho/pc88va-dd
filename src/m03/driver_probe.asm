; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Native sound driver probe (tools/check_sound_driver.py --vaeg): runs
; sd_tick on P_COUNT states and exports each result to GVRAM. Self-booting,
; isolated; the disk holds the user's sound program (test only).
;
; 2000:1000 the sound program (its tables). 7000:0000 the states, D_STRIDE
; bytes each: 9A80h-9B3Ch, then 8401h, 8646h, 8657h, 87CFh. Result i at
; GVRAM i * R_STRIDE: 9A80h-9B3Ch, then 6800h-681Fh.
        cpu 186
        org 0

ZSEG equ 5000h
SOUND_SEG equ 2100h
STATES equ 7000h
D_BYTES equ 0bdh
D_STRIDE equ 196
R_STRIDE equ 256
start:  cli
        mov ax,cs
        mov ds,ax
        mov es,ax
        mov ss,ax
        mov sp,0fffeh
        cld
        mov dx,0153h
        in al,dx
        and al,0f0h
        or al,4                  ; CPU aperture onto GVRAM for the export
        out dx,al
        mov word [p_case],0
        mov word [p_source],0
        mov word [p_result],0
        mov word [p_result_seg],0a000h
p_next: mov ax,ZSEG		; clear the Z80 segment's areas, load a state
        mov es,ax
        xor ax,ax
        mov di,6800h
        mov cx,10h
        rep stosw
        mov di,9a80h
        mov cx,80h
        rep stosw
        push ds
        mov ax,STATES
        mov ds,ax
        mov si,[cs:p_source]
        mov di,9a80h
        mov cx,D_BYTES
        rep movsb
        lodsb
        mov [es:8401h],al
        lodsb
        mov [es:8646h],al
        lodsb
        mov [es:8657h],al
        lodsb
        mov [es:87cfh],al
        pop ds
        add word [p_source],D_STRIDE
        mov ax,ZSEG
        mov ds,ax
        mov ax,SOUND_SEG
        mov es,ax
        mov ax,[cs:p_case]
driver_begin:
        call sd_tick
driver_end:
        nop
        mov ax,[cs:p_result_seg]  ; export
        mov es,ax
        mov di,[cs:p_result]
        mov si,9a80h
        mov cx,D_BYTES
        rep movsb
        mov si,6800h
        mov cx,32
        rep movsb
        push cs
        pop ds
        add word [p_result],R_STRIDE
        jnc .same
        add word [p_result_seg],1000h
.same:  inc word [p_case]
        mov ax,[p_case]
        cmp ax,P_COUNT
        jb p_next
driver_done:
        nop
.halt:  hlt
        jmp .halt
p_case dw 0
p_source dw 0
p_result dw 0
p_result_seg dw 0
%include "sound_driver.inc"
        times 4096-($-$$) db 0
