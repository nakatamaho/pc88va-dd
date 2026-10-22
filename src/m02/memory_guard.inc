; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Snapshot-test only. Guard the complete future Z80 context banks against
; renderer writes; also guard the reserved third GVRAM page. Never enable
; this initializer in the live scheduler.
video_guard_init:
        pusha
        push es
        mov bx,5000h
        mov dx,2
.bank:  mov es,bx
        xor di,di
        mov ax,0a55ah
        mov cx,8000h
        rep stosw
        add bx,1000h
        dec dx
        jnz .bank
%ifndef NATIVE_PLANES
        mov ax,0c300h            ; reserved third GVRAM page: 23000h..347FFh
        mov es,ax
        xor di,di
        mov ax,0a55ah
        mov cx,8000h
        rep stosw
        mov ax,0d300h
        mov es,ax
        xor di,di
        mov ax,0a55ah
        mov cx,0c00h
        rep stosw
%endif
        pop es
        popa
        ret
video_guard_check:
        pusha
        push es
        mov bx,5000h
        mov dx,2
.bank:  mov es,bx
        xor di,di
        mov ax,0a55ah
        mov cx,8000h
        repe scasw
        jne video_guard_failed
        add bx,1000h
        dec dx
        jnz .bank
%ifndef NATIVE_PLANES
        mov ax,0c300h
        mov es,ax
        xor di,di
        mov ax,0a55ah
        mov cx,8000h
        repe scasw
        jne video_guard_failed
        mov ax,0d300h
        mov es,ax
        xor di,di
        mov ax,0a55ah
        mov cx,0c00h
        repe scasw
        jne video_guard_failed
%endif
        pop es
        popa
video_guard_passed:
        ret
video_guard_failed:
        hlt
        jmp video_guard_failed
