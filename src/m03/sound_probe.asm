; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Synthetic WSG->OPN request replay. No Z80 game program and no graphics.
        cpu 186
        org 0
%include "patch.inc"
ZSEG equ 5000h
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
        or al,4                  ; CPU aperture onto GVRAM for diagnostic export
        out dx,al
        call m03_sound_init
        mov word [p_source],P_STATES
        mov word [p_case],0
.next:  mov ax,ZSEG
        mov es,ax
        mov di,6800h
        mov si,[p_source]
        mov cx,16
        rep movsw
        mov [p_source],si
        mov ax,[p_case]
sound_begin:
        call m03_sound_update
sound_end:
        nop
        mov ax,0d000h
        mov es,ax
        xor di,di
        mov si,m03_raw
        mov cx,16
        rep movsw
        mov si,m03_registers
        mov cx,128
        rep movsw
        mov al,[m03_error]
        stosb
%ifdef M03_FM
        mov si,m03_fm_keys
        mov cx,3
        rep movsb
%else
        xor ax,ax
        stosb
        stosb
        stosb
%endif
        mov ax,[p_case]
        mov bx,[m03_writes]
sound_exported:
        nop
        inc word [p_case]
        cmp word [p_case],P_COUNT
        jb start.next
.halt:  hlt
        jmp .halt
p_source dw 0
p_case dw 0
%include "sound_ssg.inc"
%ifdef M03_FM
%include "sound_fm.inc"
%endif
        times 4096-($-$$) db 0
