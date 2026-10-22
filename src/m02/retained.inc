; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Shared no-eviction directory. CF=0 hit, CF=1 insertion, AX=FFFFh full.
; The caller converts new pixels before submission and handles capacity.
%ifndef KEEP_FIRST_BANK
%define KEEP_FIRST_BANK 5
%endif
%ifndef KEEP_CAPACITY
%define KEEP_CAPACITY 512
%endif
keep_reset:
        push cs
        pop es
        mov di,r_keep_tags
        mov ax,0ffffh
        mov cx,1024
        rep stosw
        mov word [r_keep_used],0
        mov word [r_keep_probes],0
        ret
keep_lookup:
        cmp word [r_key],0ffffh   ; the empty tag: not cacheable
        je .full
        mov bx,[r_key]
        mov ax,bx
        shr ax,7
        xor bx,ax
        and bx,1023
        shl bx,1
        mov cx,1024
.probe: inc word [r_keep_probes]
        mov ax,[r_keep_tags + bx]
        cmp ax,[r_key]
        je .hit
        cmp ax,0ffffh
        je .new
        add bx,2
        and bx,2047
        loop .probe
        jmp .full
.new:   mov ax,[r_keep_used]
        cmp ax,KEEP_CAPACITY
        jae .full
        inc word [r_keep_used]
        mov [r_keep_slots + bx],ax
        mov dx,[r_key]
        mov [r_keep_tags + bx],dx
        call keep_address
        stc
        ret
.hit:   mov ax,[r_keep_slots + bx]
        call keep_address
        clc
        ret
.full:  mov ax,0ffffh
        stc
        ret
keep_address:
%ifdef KEEP_PACKED
        mov word [d_source_high],KEEP_FIRST_BANK
        mov word [r_cache_segment],KEEP_FIRST_BANK << 12
        shl ax,7                 ; 512 packed tiles fit in one 64 KiB bank
        mov [r_cache_offset],ax
        ret
%else
%ifdef KEEP_VRAM_TAIL
        cmp ax,256
        jb .ram
        sub ax,256
        shl ax,8
        add ax,4800h              ; GVRAM tail starts at offset 34800h
        mov [r_cache_offset],ax
        mov word [r_cache_segment],0d000h
        mov word [d_source_high],23h
        ret
.ram:
%endif
        mov dx,ax
        shr dx,8
        add dx,KEEP_FIRST_BANK
        mov [d_source_high],dx
        shl dx,12
        mov [r_cache_segment],dx
        shl ax,8
        mov [r_cache_offset],ax
        ret
%endif
%ifdef KEEP_PACKED
        align 2
%endif
r_keep_used dw 0
r_keep_probes dw 0
r_keep_tags times 1024 dw 0ffffh
r_keep_slots times 1024 dw 0
r_key dw 0
r_cache_offset dw 0
r_cache_segment dw 9000h
