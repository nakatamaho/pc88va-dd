; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Packed source cache and clipped transparent BITBLT probe. Standard RAM:
; pens 4000, protected Z80 banks 5000/6000, pixels 7000, list 3900.
%define KEEP_FIRST_BANK 7
%define KEEP_PACKED 1
%include "retained.inc"
packed_probe:
        mov ax,4000h
        mov es,ax
        xor di,di
        mov si,P_PENS
.unpack:
        lodsb
        xor cx,cx
        mov cl,al
        jcxz .unpacked
        lodsb
        rep stosb
        jmp .unpack
.unpacked:
        call keep_reset
        call p_guard_init
        ; Save the packed background at the start of G1's region.
        push ds
        mov ax,0a000h
        mov ds,ax
        mov ax,0c000h
        mov es,ax
        xor si,si
        xor di,di
        mov cx,4600h
        rep movsw
        pop ds
        ; Guard everything outside the two fronts and background template.
        mov bx,0a8c0h
        call p_guard_vram
        mov bx,0c8c0h
        call p_guard_vram
        mov dx,0100h
        in ax,dx
        or ax,0800h
        out dx,ax
        mov dx,0102h
        mov ax,1111h
        out dx,ax
        mov dx,010ch
        mov ax,01a0h
        out dx,ax
        mov dx,0204h
        mov ax,160
        out dx,ax
        add dx,2
        mov ax,447
        out dx,ax
        mov word [p_case],0
.case:  mov word [p_page],0
        cmp word [p_case],2
        jne .reset
        mov word [p_page],8c00h
.reset: push ds
        mov ax,0c000h
        mov ds,ax
        mov ax,0a000h
        cmp word [cs:p_case],2
        jne .dest
        mov ax,0a8c0h
.dest:  mov es,ax
        xor si,si
        xor di,di
        mov cx,4600h
        rep movsw
        pop ds
        mov ax,[p_case]
packed_begin:
        call p_draw
packed_end:
        nop
        call p_guard_check
        mov dx,020eh
        mov ax,[p_page]
        out dx,ax
        add dx,2
        xor ax,ax
        out dx,ax
        inc word [p_case]
        cmp word [p_case],3
        jb packed_probe.case
        ret

p_draw:
        mov word [p_hits],0
        mov word [p_misses],0
        mov word [r_keep_probes],0
        mov word [p_cursor],P_RECORDS
        mov word [p_remaining],P_COUNT
.next:  push cs
        pop es
        mov si,[p_cursor]
        lodsw
        mov [r_key],ax
        mov di,p_source
        mov cx,10
        rep movsw
        mov [p_cursor],si
        cmp word [p_case],2
        jne .lookup
        xor word [p_fy],1         ; back-page replay reuses keys with opposite Y
.lookup:
        call keep_lookup
        jnc .hit
        cmp ax,0ffffh
        je p_failed
        inc word [p_misses]
        call p_convert
        jmp .paint
.hit:   inc word [p_hits]
.paint: call p_list
        call p_run
        dec word [p_remaining]
        jnz .next
        mov bx,[p_hits]
        mov dx,[p_misses]
        mov si,[r_keep_used]
        mov bp,[r_keep_probes]
        ret

; Cache a complete tile, X reflected if requested, Y unreflected. Packing
; includes transparent zero and maps original opaque black to nibble one.
p_convert:
        push ds
        mov ax,[r_cache_segment]
        mov es,ax
        mov di,[r_cache_offset]
        mov ax,4000h
        mov ds,ax
        xor bp,bp
.row:   mov si,bp
        shl si,4
        add si,[cs:p_source]
        mov dx,1
        cmp word [cs:p_fx],0
        je .forward
        add si,15
        mov dx,-1
.forward:
        mov bx,[cs:p_lookup]
        mov cx,8
.pair:  mov al,[si]
        cs xlatb
        inc al
        and al,15
        shl al,4
        mov ah,al
        add si,dx
        mov al,[si]
        cs xlatb
        inc al
        and al,15
        or al,ah
        stosb
        add si,dx
        loop .pair
        inc bp
        cmp bp,16
        jb .row
        pop ds
        ret

p_list:
        mov ax,3900h
        mov es,ax
        xor di,di
        mov ax,3
        stosw
        mov ax,p_work
        stosw
        mov ax,2
        stosw
        mov ax,4
        stosw
        mov ax,[p_left]
        and ax,3
        shl ax,4
        or ax,1                  ; four pixels per word, packed 4bpp
        stosw
        mov ax,[p_width]
        stosw
        mov ax,[p_height]
        stosw
        mov ax,8
        cmp word [p_fy],0
        je .pitch
        mov ax,0fff6h            ; vaeg encoding of -8 source bytes/row
.pitch: stosw
        mov ax,[p_top]
        cmp word [p_fy],0
        je .sy
        xor ax,15
.sy:    shl ax,3
        add ax,[r_cache_offset]
        mov bx,[p_left]
        shr bx,1
        add ax,bx
        and ax,0fffeh
        stosw
        mov ax,[d_source_high]
        stosw
        mov ax,5
        stosw
        mov ax,[p_dest]
        and ax,1
        shl ax,1
        add ax,[p_dot]
        add ax,[p_left]
        and ax,3
        shl ax,4
        or ax,1
        stosw
        mov ax,[p_width]
        stosw
        mov ax,[p_height]
        stosw
        mov ax,160
        stosw
        mov ax,[p_top]
        imul ax,ax,160
        add ax,[p_dest]
        mov bx,[p_left]
        add bx,[p_dot]
        shr bx,1
        add ax,bx
        mov dx,20h
        add ax,[p_page]
        adc dx,0                 ; front B crosses the 64 KiB boundary
        and ax,0fffeh
        stosw
        mov ax,dx
        stosw
        mov ax,7
        stosw
        mov ax,0105h
        stosw
        mov ax,1
        stosw
        ret
p_run:
        call p_wait
        mov dx,0580h
        mov al,10h
        out dx,al
        mov dx,0500h
        mov ax,9000h
        out dx,ax
        add dx,2
        mov ax,3                 ; command list at physical 39000h
        out dx,ax
        mov dx,0504h
        xor al,al
        out dx,al
        mov dx,0506h
        mov al,1
        out dx,al
p_wait: mov dx,0506h
        mov bx,256
.outer: mov cx,0ffffh
.poll:  in al,dx
        test al,1
        jz .ready
        loop .poll
        dec bx
        jnz .outer
        jmp p_failed
.ready: ret

p_guard_vram:
        mov es,bx
        xor di,di
        mov ax,5a5ah
        mov cx,8000h
        rep stosw
        add bx,1000h
        mov es,bx
        xor di,di
        mov cx,3a00h
        rep stosw
        ret
p_guard_init:
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
        ret
p_guard_check:
        pusha
        push es
        mov bx,5000h
        mov dx,2
.bank:  mov es,bx
        xor di,di
        mov ax,0a55ah
        mov cx,8000h
        repe scasw
        jne p_failed
        add bx,1000h
        dec dx
        jnz .bank
        pop es
        popa
packed_guard_passed:
        ret
p_failed:
        hlt
        jmp p_failed

p_case dw 0
p_page dw 0
p_cursor dw 0
p_remaining dw 0
p_hits dw 0
p_misses dw 0
; Ten words, loaded from each request after its key.
p_source dw 0
p_lookup dw 0
p_fx dw 0
p_fy dw 0
p_dest dw 0
p_dot dw 0
p_left dw 0
p_top dw 0
p_width dw 0
p_height dw 0
d_source_high dw 7
p_work times 29 dw 0
