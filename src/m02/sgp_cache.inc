; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Real-source 16x16 requests: CPU direct conversion vs SGP with 1/16/64/128
; direct-mapped cache slots. Key includes glyph, colour and X flip only.
; Y flip uses negative source pitch; source bytes in cache are unflipped Y.
sgp_cache_test:
        ; Expand build-time source pens once, outside the timed passes.
        mov ax,4000h
        mov es,ax
        xor di,di
        mov si,R_PENS
.unpack:
        lodsb
        xor cx,cx
        mov cl,al
        jcxz .unpacked
        lodsb
        rep stosb
        jmp .unpack
.unpacked:
        mov ax,0a000h
        mov dx,0b180h
        call bench_copy_page
        mov word [r_case],0
.case:  call bench_reset
        mov bx,[r_case]
        cmp bx,0
        je .ready
        cmp bx,9
        jb .direct
        cmp bx,10
        je .ready
        push cs
        pop es
        mov di,r_keep_tags
        mov ax,0ffffh
        mov cx,1024
        rep stosw
        mov word [r_keep_used],0
        jmp .ready
.direct:
        mov al,[r_masks + bx]
        xor ah,ah
        mov [r_mask],ax
        test bx,1
        jz .ready                 ; warm pass retains prior cache
        push cs
        pop es
        mov di,r_tags
        mov ax,0ffffh
        mov cx,128
        rep stosw
.ready: mov ax,[r_case]
cache_begin:
        call real_draw
cache_end:
        nop
        inc word [r_case]
        cmp word [r_case],11
        jb sgp_cache_test.case
        ret
real_draw:
        mov word [r_keep_probes],0
        mov word [r_hits],0
        mov word [r_misses],0
        mov word [r_ptr],R_RECORDS
        mov word [r_left],R_COUNT
.next:  mov si,[r_ptr]
        lodsw
        mov [r_key],ax
        lodsw
        mov [r_source],ax
        lodsw
        mov [r_lookup],ax
        lodsw
        mov [r_fx],ax
        lodsw
        mov [r_fy],ax
        lodsw
        mov [r_dest],ax
        mov [r_ptr],si
        cmp word [r_case],0
        jne .sgp
        mov ax,0a000h
        mov es,ax
        mov di,[r_dest]
        mov ax,[r_fy]
        mov [r_do_y],ax
        mov word [r_pitch],320
        mov byte [r_store_zero],0
        call real_convert
        jmp .done
.sgp:   cmp word [r_case],9
        jb .mapped
        call keep_lookup
        jnc .hit
        cmp ax,0ffffh
        je bench_failed
        jmp .convert
.mapped:
        mov word [r_cache_segment],9000h
        mov word [d_source_high],9
        mov bx,[r_key]
        mov ax,bx
        shr ax,8
        xor bl,al                 ; hash glyph, colour and X flip together
        and bx,[r_mask]
        mov ax,bx
        shl ax,8
        mov [r_cache_offset],ax
        shl bx,1
        mov ax,[r_key]
        cmp ax,[r_tags + bx]
        je .hit
        mov [r_tags + bx],ax
.convert:
        inc word [r_misses]
        mov ax,[r_cache_segment]
        mov es,ax
        mov di,[r_cache_offset]
        mov word [r_do_y],0
        mov word [r_pitch],16
        mov byte [r_store_zero],1
        call real_convert
        jmp .blit
.hit:   inc word [r_hits]
.blit:  mov ax,8000h
        mov es,ax
        xor di,di
        mov ax,3
        stosw
        mov ax,b_work
        stosw
        mov ax,2
        stosw
        mov ax,[r_cache_offset]
        mov word [d_pitch],16
        cmp word [r_fy],0
        je .source
        add ax,240
        mov word [d_pitch],0ffeeh ; vaeg's encoded -16-byte pitch
.source:
        mov [d_source],ax
        mov ax,[r_dest]
        mov [d_dest],ax
        mov word [d_width],16
        mov word [d_mode],0105h
        call direction_emit
        mov ax,1
        stosw
        call bench_run
        cmp byte [b_error],0
        jne bench_failed
.done:  dec word [r_left]
        jnz .next
        mov bx,[r_hits]
        mov dx,[r_misses]
        mov si,[r_keep_used]
        mov bp,[r_keep_probes]
        ret
; Append-only cache: 1024 buckets, 512 pixel slots. Collisions probe the
; next bucket; existing pixel slots are never replaced. CF=1 on insertion.
%include "retained.inc"
; DS=CS, raw source pens already decoded as in the native renderer.
; Include palette lookup, transparent-index remapping and X/Y selection.
real_convert:
        push ds
        mov ax,4000h
        mov ds,ax
        xor bp,bp
.row:   mov ax,bp
        cmp word [cs:r_do_y],0
        je .y
        xor ax,15
.y:     shl ax,4
        add ax,[cs:r_source]
        mov si,ax
        mov dx,1
        cmp word [cs:r_fx],0
        je .x
        add si,15
        mov dx,-1
.x:     mov bx,[cs:r_lookup]
        mov cx,16
.pixel: mov al,[si]
        cs xlatb
        and al,15
        cmp al,15
        jne .opaque
        xor al,al
        cmp byte [cs:r_store_zero],0
        je .skip
        jmp .write
.opaque:
        or al,16                 ; opaque black remains index 16, not zero
.write: mov [es:di],al
.skip:  inc di
        add si,dx
        loop .pixel
        add di,[cs:r_pitch]
        sub di,16
        inc bp
        cmp bp,16
        jb .row
        pop ds
        ret
r_case dw 0
r_masks db 0,0,0,15,15,63,63,127,127
r_mask dw 0
r_tags times 128 dw 0ffffh
r_hits dw 0
r_misses dw 0
r_ptr dw 0
r_left dw 0
r_source dw 0
r_lookup dw 0
r_fx dw 0
r_fy dw 0
r_dest dw 0
r_do_y dw 0
r_pitch dw 0
r_store_zero db 0
