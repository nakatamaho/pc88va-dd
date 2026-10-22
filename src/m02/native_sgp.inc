; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Retained 8bpp sprites over the native compositor's damage/background pass.
; Pixels: standard RAM 70000h..7FFFFh plus GVRAM tail 34800h..3FFFFh.
; Lists: 38600h. No expansion RAM, no writes to Z80 contexts 5000/6000.
%define KEEP_FIRST_BANK 7
%define KEEP_VRAM_TAIL 1
%ifndef KEEP_CAPACITY
%define KEEP_CAPACITY 440
%endif
%if KEEP_CAPACITY < 1 || KEEP_CAPACITY > 440
%error "native sprite cache must fit standard RAM and the GVRAM tail"
%endif
%include "retained.inc"

; BP = clipped top within the source piece. CF=1 requests CPU fallback.
native_sgp_sprite:
        mov [s_top],bp
        mov ax,[n_lookup]
        sub ax,N_SPRLOOKUP
        shl ax,6                 ; colour*4 -> colour*256
        mov bx,[n_sprite]
        shr bx,8
        or ax,bx
        cmp byte [n_fx],0
        je .key
        or ax,4000h
.key:   mov [r_key],ax
        call keep_lookup
        jnc .hit
        cmp ax,0ffffh
        jne .new
        inc word [s_fallbacks]
        stc
        ret
.new:   inc word [s_misses]
        call native_sgp_convert
        jmp .list
.hit:   inc word [s_hits]
.list:  mov ax,3800h
        mov es,ax
        mov di,600h
        mov ax,3
        stosw
        mov ax,s_work
        stosw
        mov ax,2
        stosw
        mov word [s_commands],0
        mov ax,[s_top]
        mov [s_y],ax
        cmp byte [n_full],0
        je .bands
        mov ax,[n_left]
        mov [s_x],ax
        mov ax,[n_right]
        sub ax,[n_left]
        mov [s_width],ax
        mov ax,[n_bottom]
        sub ax,[s_top]
        mov [s_height],ax
        call native_sgp_emit
        jmp .submit
.bands:
        mov ax,[s_y]
        add ax,[n_ybase]
        and ax,7
        mov bx,8
        sub bx,ax
        mov ax,[n_bottom]
        sub ax,[s_y]
        cmp bx,ax
        jbe .height
        mov bx,ax
.height:
        mov [s_height],bx
        mov ax,[n_left]
        mov [s_x],ax
.cell:  mov ax,[s_x]
        add ax,[n_xbase]
        mov dx,ax
        and ax,7
        mov bx,8
        sub bx,ax
        mov ax,[n_right]
        sub ax,[s_x]
        cmp bx,ax
        jbe .width
        mov bx,ax
.width: mov [s_width],bx
        shr dx,3
        mov bx,[s_y]
        add bx,[n_ybase]
        shr bx,3
        imul bx,bx,36
        add bx,dx
        cmp byte [n_damage + bx],0
        je .next_cell
        call native_sgp_emit
.next_cell:
        mov ax,[s_width]
        add [s_x],ax
        mov ax,[s_x]
        cmp ax,[n_right]
        jb .cell
        mov ax,[s_height]
        add [s_y],ax
        mov ax,[s_y]
        cmp ax,[n_bottom]
        jb .bands
.submit:
        cmp word [s_commands],0
        je .done
        mov ax,1
        stosw
        call native_sgp_run
.done:  clc
        ret

native_sgp_convert:
        push ds
        mov ax,[r_cache_segment]
        mov es,ax
        mov di,[r_cache_offset]
        mov ax,4000h
        mov ds,ax
        xor bp,bp
.row:   mov si,bp
        shl si,4
        add si,[cs:n_sprite]
        mov dx,1
        cmp byte [cs:n_fx],0
        je .forward
        add si,15
        mov dx,-1
.forward:
        mov bx,[cs:n_lookup]
        mov cx,16
.pixel: mov al,[si]
        cs xlatb
        and al,15
        cmp al,15
        jne .opaque
        xor al,al
        jmp .store
.opaque:
        or al,16
.store: stosb
        add si,dx
        loop .pixel
        inc bp
        cmp bp,16
        jb .row
        pop ds
        ret

; Emit one clipped rectangle. The source's X flip is already materialized;
; Y is reflected by source start and pitch. Destination crosses 64 KiB.
native_sgp_emit:
        inc word [s_commands]
        mov ax,[s_y]
        mov word [s_pitch],16
        cmp byte [n_fy],0
        je .y
        xor ax,15
        mov word [s_pitch],0ffeeh
.y:     shl ax,4
        add ax,[r_cache_offset]
        add ax,[s_x]
        mov si,ax
        mov ax,4
        stosw
        mov ax,si
        and ax,1
        shl ax,4
        or ax,2
        stosw
        mov ax,[s_width]
        stosw
        mov ax,[s_height]
        stosw
        mov ax,[s_pitch]
        stosw
        mov ax,si
        and ax,0fffeh
        stosw
        mov ax,[d_source_high]
        stosw
        mov ax,[s_y]
        add ax,[n_ybase]
        mov dx,320
        mul dx
        add ax,[n_xbase]
        adc dx,0
        add ax,[s_x]
        adc dx,0
        add ax,16
        adc dx,0
        add dx,20h
        mov si,ax
        mov ax,5
        stosw
        mov ax,si
        and ax,1
        shl ax,4
        or ax,2
        stosw
        mov ax,[s_width]
        stosw
        mov ax,[s_height]
        stosw
        mov ax,320
        stosw
        mov ax,si
        and ax,0fffeh
        stosw
        mov ax,dx
        stosw
        mov ax,7
        stosw
        mov ax,0105h
        stosw
        ret
native_sgp_run:
        call native_sgp_wait
        mov dx,0580h
        mov al,10h
        out dx,al
        mov dx,0500h
        mov ax,8600h
        out dx,ax
        add dx,2
        mov ax,3
        out dx,ax
        mov dx,0504h
        xor al,al
        out dx,al
        mov dx,0506h
        mov al,1
        out dx,al
native_sgp_wait:
        mov dx,0506h
        mov bx,256
.outer: mov cx,0ffffh
.poll:  in al,dx
        test al,1
        jz .ready
        loop .poll
        dec bx
        jnz .outer
        mov byte [s_error],1
        ; Do not draw or reuse source RAM after a timed-out SGP operation.
.failed:
        hlt
        jmp .failed
.ready: ret
s_hits dw 0
s_misses dw 0
s_fallbacks dw 0
s_error db 0
s_top dw 0
s_x dw 0
s_y dw 0
s_width dw 0
s_height dw 0
s_pitch dw 0
s_commands dw 0
d_source_high dw 7
s_work times 29 dw 0
