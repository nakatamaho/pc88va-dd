; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Exhaustive ROM-free test of the native 20-bit SSG period conversion.
        cpu 186
        org 0
ZSEG equ 5000h
start:  cli
        mov ax,cs
        mov ds,ax
        mov es,ax
        mov ss,ax
        mov sp,0fffeh
        mov word [m03_f_low],1
        mov word [m03_f_high],0
.next:  mov ax,[m03_f_low]
        mov dx,[m03_f_high]
%ifdef MATH_FM
        call m03_fm_pitch
%else
        call m03_period
%endif
        add [sum_low],ax
        adc word [sum_high],0
        xor [parity],ax
        inc word [m03_f_low]
        jnz .next
        inc word [m03_f_high]
        cmp word [m03_f_high],16
        jb .next
        mov ax,[sum_low]
        mov dx,[sum_high]
        mov bx,[parity]
        mov si,[m03_f_high]
math_done:
        hlt
        jmp math_done
sum_low dw 0
sum_high dw 0
parity dw 0
%include "sound_ssg.inc"
%ifdef MATH_FM
%define N_FM_VOICES 0
%include "sound_fm.inc"
%endif
        times 4096-($-$$) db 0
