; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Live-only packed 8x8 composited background/character tile cache.
; 2048 pixels slots (64 KiB) at GVRAM 29200h..391FFh, after G1's image
; and its blank margin.
; Full 32-bit tags + slot indices occupy reclaimed CS:9000h..EFFFh.
; No eviction: capacity exhaustion falls back to the reference conversion.
; N_DRAWN (1008 words) records what each G1 tile holds: a slot, 8000h|colour
; for a uniform tile, or FFFFh (unknown). A tile already holding its new
; content is skipped; uniform tiles (blank glyph over one colour) are filled
; directly, without hashing or copying.
BC_LO equ 9000h
BC_HI equ 0b000h
BC_SLOT equ 0d000h
BC_PIXELS equ 0c920h
background_cache_init:
        push cs
        pop es
        mov di,BC_LO
        mov ax,0ffffh
        mov cx,4096
        rep stosw
        mov di,N_DRAWN            ; planes_init cleared G1 to colour 0
        mov ax,8000h
        mov cx,1008
        rep stosw
        mov word [bc_used],0
        ret
background_cache_begin:
        mov word [bc_hits],0
        mov word [bc_misses],0
        mov word [bc_full],0
        mov word [bc_filled],0
        mov word [bc_skipped],0
        ret
; CF=0: G1 already holds the tile (skipped, filled or copied); CF=1: the
; caller must convert it, then call background_cache_store.
background_cache_tile:
        mov word [bc_offset],0ffffh
        mov ax,[n_fg]
        shr ax,6
        mov bx,ax
        xor cx,cx
        cmp byte [N_EMPTY + bx],0
        je .nonempty
        mov bx,[n_lookup]         ; blank glyph: one colour if the lookup is
        mov al,[bx]               ; uniform
        and al,15
        mov ah,[bx+1]
        and ah,15
        cmp al,ah
        jne .empty_pattern
        mov ah,[bx+2]
        and ah,15
        cmp al,ah
        jne .empty_pattern
        mov ah,[bx+3]
        and ah,15
        cmp al,ah
        jne .empty_pattern
        jmp background_fill
.empty_pattern:
        mov ax,128               ; reserved tag for all empty glyphs
        jmp .glyph
.nonempty:
        mov cl,[n_colour]
.glyph: shl ax,8
        mov [bc_key_lo],ax
        shl cx,6
        mov [bc_key_hi],cx
        mov bx,[n_lookup]
        mov al,[bx]
        and al,15
        mov ah,[bx+1]
        and ah,15
        cmp al,ah
        jne .pattern
        mov ah,[bx+2]
        and ah,15
        cmp al,ah
        jne .pattern
        mov ah,[bx+3]
        and ah,15
        cmp al,ah
        jne .pattern
        xor ah,ah
        or ax,0800h              ; uniform palette: code/map irrelevant
        or [bc_key_hi],ax
        jmp .hash
.pattern:
        mov ax,[n_bg]
        sub ax,4000h
        shr ax,6
        or [bc_key_lo],ax
        mov ax,[n_lookup]
        sub ax,N_BGLOOKUP
        shr ax,2
        or [bc_key_hi],ax
.hash:  mov ax,[bc_key_lo]
        mov dx,ax
        shr dx,7
        xor ax,dx
        xor ax,[bc_key_hi]
        and ax,4095
        mov bx,ax
        shl bx,1
        mov cx,4096
.probe: mov ax,[BC_LO+bx]
        cmp ax,0ffffh
        je .new
        cmp ax,[bc_key_lo]
        jne .next
        mov ax,[BC_HI+bx]
        cmp ax,[bc_key_hi]
        je .hit
.next:  add bx,2
        and bx,1fffh
        loop .probe
        jmp .full
.new:   mov ax,[bc_used]
        cmp ax,2048
        jae .full
        inc word [bc_used]
        mov [BC_SLOT+bx],ax
        shl ax,5
        mov [bc_offset],ax
        mov ax,[bc_key_hi]
        mov [BC_HI+bx],ax
        mov ax,[bc_key_lo]
        mov [BC_LO+bx],ax
        mov ax,[BC_SLOT+bx]       ; G1 holds this slot once it is stored
        mov bx,[n_screen]
        shl bx,1
        mov [N_DRAWN+bx],ax
        inc word [bc_misses]
        stc
        ret
.full:  inc word [bc_full]
        mov bx,[n_screen]         ; drawn without a slot: content unknown
        shl bx,1
        mov word [N_DRAWN+bx],0ffffh
        stc
        ret
.hit:   mov ax,[BC_SLOT+bx]
        mov bx,[n_screen]
        shl bx,1
        cmp ax,[N_DRAWN+bx]
        je .same
        mov [N_DRAWN+bx],ax
        shl ax,5
        mov [bc_offset],ax
        inc word [bc_hits]
        call background_cache_load
        clc
        ret
.same:  inc word [bc_skipped]
        clc
        ret

; AL = the colour of a uniform tile: skip it if G1 already holds it, else
; fill it (CF = 0).
background_fill:
        xor ah,ah
        or ah,80h
        mov bx,[n_screen]
        shl bx,1
        cmp ax,[N_DRAWN+bx]
        je .same
        mov [N_DRAWN+bx],ax
        inc word [bc_filled]
        mov ah,al                 ; packed: both pixels of a byte
        shl ah,4
        or al,ah
        mov ah,al
        mov dx,ax
        xor ax,ax
        mov al,[n_row]
        imul ax,ax,80
        add ax,0c000h
        mov es,ax
        xor ax,ax
        mov al,[n_col]
        shl ax,2
        add ax,8
        mov di,ax
        mov ax,dx
        mov dx,8
.row:   stosw
        stosw
        add di,156
        dec dx
        jnz .row
        clc
        ret
.same:  inc word [bc_skipped]
        clc
        ret
background_cache_load:
        push ds
        xor ax,ax
        mov al,[n_row]
        imul ax,ax,80
        add ax,0c000h
        mov es,ax
        xor ax,ax
        mov al,[n_col]
        shl ax,2
        add ax,8
        mov di,ax
        mov si,[bc_offset]
        mov ax,BC_PIXELS
        mov ds,ax
        mov dx,8
.row:   movsw
        movsw
        add di,156
        dec dx
        jnz .row
        pop ds
        ret
background_cache_store:
        cmp word [bc_offset],0ffffh
        je .done
        push ds
        xor ax,ax
        mov al,[n_row]
        imul ax,ax,80
        add ax,0c000h
        mov bx,ax
        xor ax,ax
        mov al,[n_col]
        shl ax,2
        add ax,8
        mov si,ax
        mov di,[bc_offset]
        mov ds,bx
        mov ax,BC_PIXELS
        mov es,ax
        mov dx,8
.row:   movsw
        movsw
        add si,156
        dec dx
        jnz .row
        pop ds
.done:  ret
bc_used dw 0
bc_hits dw 0
bc_misses dw 0
bc_full dw 0
bc_filled dw 0
bc_skipped dw 0
bc_offset dw 0
bc_key_lo dw 0
bc_key_hi dw 0
