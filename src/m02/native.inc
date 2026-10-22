; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Correctness-first native compositor of a frozen video-state snapshot.
; Pens: characters at 3000:0000, background at 3000:4000, sprites at 4000:0000.
; Character and sprite damage tracking; latch changes still redraw fully.
; Not yet suitable for the live scheduler.
native_unpack:
        lodsb
        xor cx,cx
        mov cl,al
        jcxz .end
        lodsb
        rep stosb
        jmp native_unpack
.end:   ret
%ifndef LIVE_VIDEO
native_init:
        mov ax,3000h
        mov es,ax
        xor di,di
        mov si,N_CHARS
        call native_unpack
        mov di,4000h
        mov si,N_BG
        call native_unpack
        mov ax,4000h
        mov es,ax
        xor di,di
        mov si,N_SPRITES
        call native_unpack
%ifdef NATIVE_SGP
        call keep_reset
%endif
%ifdef NATIVE_PLANES
        call planes_init
        ret
%endif
        ; Clear both image margins, including the part beyond 64 KiB.
        mov ax,0a000h
        mov es,ax
        xor di,di
        xor ax,ax
        mov cx,8000h
        rep stosw
        mov ax,0b000h
        mov es,ax
        xor ax,ax
        mov cx,0c00h
        rep stosw
        ret
%endif
native_render:
%ifdef NATIVE_PLANES
        call planes_begin
%endif
%ifdef NATIVE_SGP
        mov word [s_hits],0
        mov word [s_misses],0
        mov word [s_fallbacks],0
        mov word [r_keep_probes],0
%endif
        ; Shadow video state in 3800:0000. Restore old/new sprite footprints
        ; as well as changed character cells; latch changes redraw fully.
        mov word [n_redrawn],0
        mov byte [n_full],1
        cmp byte [n_valid],0
        je .scan
        mov ax,3800h
        mov es,ax
        mov si,N_LATCH
        mov di,1408
        mov cx,8
        repe cmpsb
        jne .scan
        mov byte [n_full],0
        mov si,N_VRAM
        xor di,di
        mov cx,708
%ifdef LIVE_VIDEO
        cmp byte [n_tiles_same],0 ; tile RAM as in the shadow: sprites only
        je .compare
%ifdef NATIVE_PLANES
        cmp byte [l_reuse],0      ; planes_begin found the sprites as in the
        jne .same                 ; shadow, and the latches are too
%endif
        mov si,N_VRAM + 1024
        mov di,1024
        mov cx,708 - 512
.compare:
%endif
        repe cmpsw
        jne .damage
.same:
%ifdef NATIVE_PLANES
        cmp byte [n_pending],0    ; background rows left by an earlier call
        je .unchanged
        call native_clear_dirty
        jmp .scan
.unchanged:
%endif
        xor ax,ax                 ; no video state changed; keep the image
%ifdef NATIVE_PLANES
        jmp native_planes_report
%elifdef NATIVE_SGP
        jmp native_report
%else
        ret
%endif
.damage:
%ifdef NATIVE_PLANES
        ; The first mismatch already tells whether character RAM changed:
        ; SI is past it. Sprite damage maps are built per front later.
        mov [n_first_diff],si
        push cs
        pop es
        mov di,n_dirty_rows
        xor ax,ax
        mov cx,14
        rep stosw
        cmp word [n_first_diff],N_VRAM+1024
        ja .chars_checked
        mov ax,3800h
        mov es,ax
        mov si,[n_first_diff]     ; resume exactly as after REPE CMPSW
        mov di,si
        sub di,N_VRAM
        mov cx,N_VRAM+1024
        sub cx,si
        shr cx,1
        call native_character_damage
        jmp .chars_checked
%endif
        push cs
        pop es
        mov di,n_damage
        xor ax,ax
        mov cx,504
        rep stosw
        mov di,n_dirty_rows
        mov cx,14
        rep stosw
        mov ax,3800h
        mov es,ax
        mov si,N_VRAM
        xor di,di
        mov cx,512
        repe cmpsw
        je .chars_checked
        call native_character_damage
.chars_checked:
%ifndef NATIVE_PLANES
        call native_sprite_damage
%endif
.scan:
%ifdef NATIVE_PLANES
        ; First call or changed latches: every background row is redrawn,
        ; in this call or, in the live game, over several (see .next_row).
        mov byte [n_rows_done],0
        mov byte [n_row_visited],0
        cmp byte [n_full],0
        je .rows_set
        mov byte [n_full],0
        call native_clear_dirty
        push cs
        pop es
        mov di,n_pending_rows
        mov al,1
        mov cx,28
        rep stosb
        mov byte [n_pending],28
%ifdef LIVE_VIDEO
        mov byte [n_start_row],0  ; a wipe from the top
%endif
.rows_set:
%endif
        ; Per-call latch values: map page offset and colour bank bits.
        xor ax,ax
        mov al,[N_LATCH]
        mov ah,[N_LATCH + 1]
        shl ah,1
        or al,ah
        xor ah,ah
        shl ax,10
        mov [n_map_page],ax
        mov al,[N_LATCH + 4]
        shl al,4
        mov ah,[N_LATCH + 5]
        shl ah,5
        or al,ah
        mov [n_bank],al
        mov byte [n_row],0
        mov word [n_screen],0
        mov word [n_map],N_INDEX
%if %isdef(NATIVE_PLANES) && %isdef(LIVE_VIDEO)
        ; The walk starts after the row where the last one stopped and goes
        ; round all 28: rows changing every frame near the top (blinking
        ; text) must not take every render's few rows, leaving the rows
        ; below pending for good.
        mov byte [n_walked],0
        xor ax,ax
        mov al,[n_start_row]
        mov [n_row],al
        imul bx,ax,36
        mov [n_screen],bx
        imul bx,ax,72
        add bx,N_INDEX
        mov [n_map],bx
%endif
%ifdef NATIVE_PLANES
        ; No background row pending or dirty (sprites changed only): no walk.
        cmp byte [n_pending],0
        jne .row
        push cs
        pop es
        mov di,n_dirty_rows
        mov cx,28
        xor al,al
        repe scasb
        jne .row
        jmp native_planes_sprites
%endif
.row:
%ifdef NATIVE_PLANES
        xor bx,bx
        mov bl,[n_row]
        mov al,[n_pending_rows + bx]
        mov [n_row_forced],al
        or al,[n_dirty_rows + bx]
        jnz .visit_row
%else
        cmp byte [n_full],0
        jne .visit_row
        xor bx,bx
        mov bl,[n_row]
        cmp byte [n_dirty_rows + bx],0
        jne .visit_row
%endif
        add word [n_screen],36
        add word [n_map],72
        jmp .next_row
.visit_row:
%ifdef NATIVE_PLANES
        mov byte [n_row_visited],1
%endif
        mov byte [n_col],0
.tile:  mov si,[n_map]
        lodsw
        mov [n_map],si
        mov bx,ax
        mov di,[n_screen]
%ifdef NATIVE_PLANES
        cmp byte [n_row_forced],0
%else
        cmp byte [n_full],0
%endif
        jne .redraw
        mov ax,3800h
        mov es,ax
        mov al,[N_VRAM + bx]
        cmp al,[es:bx]
        jne .redraw
%ifdef NATIVE_PLANES
        jmp .next_tile
%else
        cmp byte [n_damage + di],0
        je .next_tile
        ; Only a sprite footprint changed: restore the already-composited
        ; background/character tile instead of decoding its 64 pixels again.
        inc word [n_redrawn]
        mov ax,0b180h
        mov dx,0a000h
        call native_copy_tile
        jmp .next_tile
%endif
.redraw:
        mov byte [n_damage + di],1
        inc word [n_redrawn]
        mov al,[N_VRAM + bx]
        and ax,007fh
        shl ax,6
        mov [n_fg],ax
        mov al,[N_VRAM + bx]       ; colour uses the original full code
        cmp byte [N_LATCH + 2],0
        jne .low_colour
        mov ah,al
        shr al,4
        and al,14
        shr ah,3
        and ah,2
        or al,ah
        jmp .colour
.low_colour:
        and al,15
.colour:
        mov [n_colour],al
        add bx,[n_map_page]
        mov al,[N_MAPS + bx]
        xor ah,ah
        mov bx,ax
        shl bx,6
        add bx,4000h
        mov [n_bg],bx
        shr al,4
        cmp byte [N_LATCH + 3],0
        je .bank
        mov al,15
.bank:  or al,[n_bank]
        xor ah,ah
        shl ax,2
        add ax,N_BGLOOKUP
        mov [n_lookup],ax
%ifdef NATIVE_PLANES
        call planes_background_tile
        jmp .next_tile
%endif
        xor ax,ax
        mov al,[n_row]
        imul ax,ax,160
        add ax,0a000h
        mov es,ax
        mov si,[n_bg]
        mov bp,[n_fg]
        mov bx,[n_lookup]
        mov dl,[n_colour]
        mov byte [n_lines],8
        mov ax,3000h
        mov ds,ax
.line:  xor ax,ax
        mov al,[cs:n_col]
        shl ax,3
        add ax,16
        mov di,ax
        mov cx,8
.pixel: lodsb
        cs xlatb
        and al,15
        cmp byte [ds:bp],0
        je .store
        mov al,dl
.store: stosb
        inc bp
        loop .pixel
        mov ax,es
        add ax,20
        mov es,ax
        dec byte [cs:n_lines]
        jnz .line
        push cs
        pop ds
        ; Save the sprite-free tile in the second 70 KiB GVRAM area.
        mov ax,0a000h
        mov dx,0b180h
        call native_copy_tile
.next_tile:
        inc word [n_screen]
        inc byte [n_col]
        cmp byte [n_col],36
        jb .tile
.next_row:
%ifdef NATIVE_PLANES
        cmp byte [n_row_visited],0
        je .advance
        mov byte [n_row_visited],0
        xor bx,bx
        mov bl,[n_row]
        cmp byte [n_pending_rows + bx],0
        je .row_done
        mov byte [n_pending_rows + bx],0
        dec byte [n_pending]
.row_done:
        inc byte [n_rows_done]
%ifdef LIVE_VIDEO
        ; The live game must not stall on a big background change: once the
        ; next frame is due, stop after MIN_ROWS rows; the rest are drawn by
        ; the next calls (a short top-to-bottom wipe), while the programs
        ; and sound keep running.
        cmp byte [n_rows_done],BG_MIN_ROWS
        jb .advance
        cmp byte [live_forced],0  ; a render the scheduler forces (a program
        jne .stop                 ; busy in its own loop): no more rows
        mov ax,[tick]
        cmp ax,[seen]
        je .advance
.stop:  jmp native_background_stop
%endif
.advance:
%endif
        inc byte [n_row]
%if %isdef(NATIVE_PLANES) && %isdef(LIVE_VIDEO)
        cmp byte [n_row],28
        jb .walked
        mov byte [n_row],0        ; round to the first row
        mov word [n_screen],0
        mov word [n_map],N_INDEX
.walked:
        inc byte [n_walked]
        cmp byte [n_walked],28
        jb .row
%else
        cmp byte [n_row],28
        jb .row
%endif
%ifdef NATIVE_PLANES
native_planes_sprites:
        cmp byte [l_same],0
        jne native_finish
%ifdef RECT_SPRITES
        call rect_sprites
        jmp native_finish
%endif
%ifdef FRONT_FULL
        call planes_full_begin
%elifdef FRONT_HYBRID
        call planes_hybrid
%else
        call planes_damage
        call planes_clear
%endif
%else
        cmp word [n_redrawn],0
        je native_finish
%endif
        ; Sprite entries are composited in ascending order.
        mov word [n_off],0
.object:
        mov bx,[n_off]
        mov al,[N_OBJECT + bx]
        xor ah,ah
        mov dx,ax
        shr dx,7
        mov [n_size],dl
        or dl,dl
        jz .small
        mov dx,ax
        and dx,0c0h
        and ax,3fh
        shl ax,2
        or ax,dx
.small: mov [n_code],ax
        mov al,[N_OBJECT + bx + 1]
        and ax,003fh
        shl ax,2
        add ax,N_SPRLOOKUP
        mov [n_lookup],ax
        mov al,[N_POSITION + bx + 1]
        xor ah,ah
        sub ax,39
        mov [n_sx],ax
        mov al,[N_POSITION + bx]
        xor ah,ah
        neg ax
        add ax,257
        cmp byte [n_size],0
        je .sy
        sub ax,16
.sy:    and ax,255
        sub ax,32
        mov [n_sy],ax
        ; Reject an entry wholly above the raster before splitting it into
        ; pieces and wraps (unused entries sit there). Y never exceeds 223.
        cmp byte [n_size],0
        jne .large_y
        cmp ax,-16
        jle .next_object
        jmp .visible_y
.large_y:
        cmp ax,-32
        jle .next_object
.visible_y:
        mov al,[N_FLIP + bx]
        mov ah,al
        and al,1
        mov [n_fx],al
        shr ah,1
        and ah,1
        mov [n_fy],ah
        mov byte [n_ty],0
.part_y:
        mov byte [n_tx],0
.part_x:
        xor ax,ax
        mov al,[n_ty]
        mov bl,[n_size]
        and bl,[n_fy]
        xor al,bl
        shl ax,1
        mov bl,[n_size]
        and bl,[n_fx]
        xor bl,[n_tx]
        xor bh,bh
        add ax,bx
        add ax,[n_code]
        shl ax,8
        mov [n_sprite],ax
        xor ax,ax
        mov al,[n_tx]
        shl ax,4
        add ax,[n_sx]
        and ax,255
        mov [n_xbase],ax
        xor ax,ax
        mov al,[n_ty]
        shl ax,4
        add ax,[n_sy]
        mov [n_ybase],ax
        call native_sprite
        cmp word [n_xbase],16     ; the copy 256 dots right is visible only
        jae .no_wrap              ; when the piece starts left of 16
        add word [n_xbase],256
        call native_sprite
.no_wrap:
        inc byte [n_tx]
        mov al,[n_tx]
        cmp al,[n_size]
        jbe .part_x
        inc byte [n_ty]
        mov al,[n_ty]
        cmp al,[n_size]
        jbe .part_y
.next_object:
        add word [n_off],2
        cmp word [n_off],128
        jb .object
native_finish:
%ifdef NATIVE_PLANES
        call planes_ready
%endif
        mov ax,3800h
        mov es,ax
        xor di,di
        mov si,N_VRAM
        mov cx,708                ; tile RAM + sprite windows + latches
%ifdef LIVE_VIDEO
        cmp byte [n_tiles_same],0 ; the shadow's tiles are these already
        mov byte [n_shadow_tiles],1
        je .save
        mov si,N_VRAM + 1024
        mov di,1024
        mov cx,708 - 512
.save:
%endif
        rep movsw
        mov byte [n_valid],1
        mov ax,[n_redrawn]
%ifdef NATIVE_SGP
native_report:
        mov bx,[s_hits]
        mov cx,[s_misses]
        mov dx,[s_fallbacks]
        mov si,[r_keep_used]
        mov bp,[r_keep_probes]
%elifdef NATIVE_PLANES
native_planes_report:
        mov bx,[l_hits]
        mov cx,[l_misses]
        mov dx,[l_fallbacks]
        mov si,[r_keep_used]
        mov bp,[l_cleared]
        mov di,[l_output_page]
%endif
        ret
; Copy an 8x8 byte tile between two GVRAM areas (AX source, DX dest).
; Normalize each tile row's segment so no string operation crosses 64 KiB.
native_copy_tile:
        push ds
        mov bx,ax
        xor ax,ax
        mov al,[n_row]
        imul ax,ax,160
        add bx,ax
        add dx,ax
        xor ax,ax
        mov al,[n_col]
        shl ax,3
        add ax,16
        mov si,ax
        mov di,ax
        mov ds,bx
        mov es,dx
        mov bp,8
.row:   mov cx,4
        rep movsw
        add si,312
        add di,312
        dec bp
        jnz .row
        pop ds
        ret
%ifdef NATIVE_PLANES
native_clear_dirty:
        push cs
        pop es
        mov di,n_dirty_rows
        xor ax,ax
        mov cx,14
        rep stosw
        ret
%ifdef LIVE_VIDEO
; Rows after the current one still due (pending, or with changed cells)
; become pending: the video state shadow is updated below regardless.
native_background_stop:
        ; The rows the walk has not reached (after this one, round to the
        ; first): changed ones become pending; the next walk starts there.
        xor bx,bx
        mov bl,[n_row]
        mov cl,27
        sub cl,[n_walked]         ; rows left
        inc bx
        cmp bx,28
        jb .start
        xor bx,bx
.start: mov [n_start_row],bl
        or cl,cl
        jz .done
.row:   cmp byte [n_pending_rows + bx],0
        jne .next
        cmp byte [n_dirty_rows + bx],0
        je .next
        mov byte [n_pending_rows + bx],1
        inc byte [n_pending]
.next:  inc bx
        cmp bx,28
        jb .left
        xor bx,bx
.left:  dec cl
        jnz .row
.done:  jmp native_planes_sprites
%endif
%endif
; Mark only rows containing changed character cells. N_ROWS is the inverse
; board-raster mapping; FFh marks source cells outside the visible raster.
native_character_damage:
        ; Continue the caller's REPE CMPSW after its first mismatch. Both
        ; cells of a mismatched word are conservatively marked; matching
        ; spans are skipped without visiting every board-raster cell.
.word:  mov bx,di
        sub bx,2
        mov ax,[N_ROWS + bx]
        xor bx,bx
        cmp al,255
        je .odd
        mov bl,al
        mov byte [n_dirty_rows + bx],1
.odd:   cmp ah,255
        je .next
        mov bl,ah
        mov byte [n_dirty_rows + bx],1
.next:  jcxz .done
        repe cmpsw
        jne .word
.done:  ret
; Compare each six-byte sprite state, then mark its old and new bounds.
; Ignored register bits may cause extra damage but never hide a change.
native_sprite_damage:
        mov word [n_mark_count],0
        mov word [n_mark_off],0
.entry: mov bx,[n_mark_off]
        mov ax,3800h
        mov es,ax
        mov ax,[N_OBJECT + bx]
        cmp ax,[es:1024 + bx]
        jne .changed
        mov ax,[N_POSITION + bx]
        cmp ax,[es:1152 + bx]
        jne .changed
        mov ax,[N_FLIP + bx]
        cmp ax,[es:1280 + bx]
        je .next
.changed:
        add bx,N_OBJECT
        call native_mark_object
        mov bx,[n_mark_off]
        add bx,1024
        push ds
        mov ax,3800h
        mov ds,ax
        call native_mark_object
        pop ds
.next:  add word [n_mark_off],2
        cmp word [n_mark_off],128
        jb .entry
        ret
; DS:BX points to code/colour; position is 128 bytes further on.
native_mark_object:
        xor ax,ax
        mov al,[bx]
        shr ax,7
        mov [cs:n_mark_size],ax
        shl ax,4
        mov cx,ax
        add ax,16
        mov [cs:n_mark_height],ax
        mov al,[bx + 128]
        xor ah,ah
        neg ax
        add ax,257
        sub ax,cx
        and ax,255
        sub ax,32
        mov [cs:n_mark_y],ax
        mov al,[bx + 129]
        xor ah,ah
        sub ax,39
        mov [cs:n_mark_x],ax
        mov word [cs:n_mark_part],0
.part:  mov ax,[cs:n_mark_part]
        shl ax,4
        add ax,[cs:n_mark_x]
        and ax,255
        mov [cs:n_mark_wrapped],ax
        call native_mark_rect
        mov ax,[cs:n_mark_wrapped]
        add ax,256
        call native_mark_rect
        inc word [cs:n_mark_part]
        mov ax,[cs:n_mark_part]
        cmp ax,[cs:n_mark_size]
        jbe .part
        ret
; Mark an X-wrapped 16-by-height strip clipped to the sprite viewport.
; AX = left; Y/height in scratch. Damage indexes are board-raster tiles.
native_mark_rect:
        cmp ax,272
        jae .done
        mov dx,ax
        add dx,16
        cmp dx,16
        jbe .done
        cmp ax,16
        jae .left
        mov ax,16
.left:  cmp dx,272
        jbe .right
        mov dx,272
.right: shr ax,3
        dec dx
        shr dx,3
        sub dx,ax
        inc dx
        mov bp,dx                 ; tile columns to mark
        mov bx,[cs:n_mark_y]
        mov cx,bx
        add cx,[cs:n_mark_height]
        cmp bx,224
        jge .done
        cmp cx,0
        jle .done
        cmp bx,0
        jge .top
        xor bx,bx
.top:   cmp cx,224
        jle .bottom
        mov cx,224
.bottom:
        shr bx,3
        dec cx
        shr cx,3
        sub cx,bx
        inc cx
        mov dx,cx                 ; tile rows to mark
        mov [cs:n_mark_row],bx
        imul bx,bx,36
        add bx,ax
        add bx,n_damage
        push cs
        pop es
.row:   add [cs:n_mark_count],bp      ; cells marked, overlaps counted again
        mov si,[cs:n_mark_row]
        mov byte [cs:n_dirty_rows + si],1
%ifdef NATIVE_PLANES
        mov byte [cs:n_damage_used + si],1   ; for planes_damage's clearing
%endif
        inc word [cs:n_mark_row]
        mov di,bx
        mov cx,bp
        mov al,1
        rep stosb
        add bx,36
        dec dx
        jnz .row
.done:  ret
native_sprite:
        ; Cull and clip once per 16x16 tile, not once per pixel. Wrapped
        ; copies are treated separately by the caller, before this test.
        mov ax,[n_xbase]
        cmp ax,272
        jae .reject
        or ax,ax                 ; x=0 ends exactly at the left clip edge
        jz .reject
        mov bx,16
        sub bx,ax
        jns .left
        xor bx,bx
.left:  mov [n_left],bx
        mov bx,272
        sub bx,ax
        cmp bx,16
        jbe .right
        mov bx,16
.right: mov [n_right],bx
        mov ax,[n_ybase]
        cmp ax,224
        jge .reject
        cmp ax,-16
        jle .reject
        xor bp,bp
        or ax,ax
        jns .top
        sub bp,ax
.top:   mov bx,224
        sub bx,ax
        cmp bx,16
        jle .bottom
        mov bx,16
.bottom:
        mov [n_bottom],bx
        cmp byte [n_full],0
        jne .draw
        ; Reject tiles that miss every changed 8x8 cell. Drawing below is
        ; also masked per cell: otherwise a lower-priority sprite could
        ; overwrite an unchanged higher-priority one outside the damage.
        mov dx,[n_xbase]
        add dx,[n_left]
        shr dx,3
        mov cx,[n_xbase]
        add cx,[n_right]
        dec cx
        shr cx,3
        sub cx,dx
        inc cx
        mov si,[n_ybase]
        add si,bp
        shr si,3
        mov ax,[n_ybase]
        add ax,[n_bottom]
        dec ax
        shr ax,3
        sub ax,si
        inc ax
        imul si,si,36
        add si,dx
        mov dx,cx
.damage_row:
        mov bx,si
        mov cx,dx
.damage_col:
        cmp byte [n_damage + bx],0
        jne .draw
        inc bx
        loop .damage_col
        add si,36
        dec ax
        jnz .damage_row
        ret
.draw:
%ifdef NATIVE_PLANES
        call planes_sprite
        jmp .reject
%endif
%ifdef NATIVE_SGP
        push bp
        call native_sgp_sprite
        pop bp
        jnc .reject
%endif
        push ds
        mov ax,4000h
        mov ds,ax
.y:     mov ax,[cs:n_ybase]
        add ax,bp
        mov bx,ax
        shr bx,3
        imul bx,bx,36
        mov [cs:n_damage_row],bx
        imul ax,ax,20
        add ax,0a000h
        mov es,ax
        mov ax,bp
        cmp byte [cs:n_fy],0
        je .source_y
        xor ax,15
.source_y:
        shl ax,4
        add ax,[cs:n_sprite]
        mov si,[cs:n_left]
        mov dx,1
        cmp byte [cs:n_fx],0
        je .source_x
        xor si,15
        mov dx,-1
.source_x:
        add si,ax
        mov di,[cs:n_xbase]
        add di,[cs:n_left]
        add di,16                ; centre the board raster in 320 dots
        mov cx,[cs:n_right]
        sub cx,[cs:n_left]
        mov bx,[cs:n_lookup]
.x:     cmp byte [cs:n_full],0
        jne .paint
        mov ax,di
        sub ax,16
        shr ax,3
        mov bx,[cs:n_damage_row]
        add bx,ax
        cmp byte [cs:n_damage + bx],0
        je .transparent
.paint: mov bx,[cs:n_lookup]
        mov al,[si]
        cs xlatb
        and al,15
        cmp al,15
        je .transparent
        or al,16
        mov [es:di],al
.transparent:
        inc di
        add si,dx
        loop .x
        inc bp
        cmp bp,[cs:n_bottom]
        jl .y
        pop ds
.reject:
        ret
n_full db 0
n_valid db 0
n_redrawn dw 0
n_row db 0
n_col db 0
n_colour db 0
n_lines db 0
n_map dw 0
n_fg dw 0
n_bg dw 0
n_lookup dw 0
n_off dw 0
n_code dw 0
n_size db 0
n_fx db 0
n_fy db 0
n_tx db 0
n_ty db 0
n_sx dw 0
n_sy dw 0
n_sprite dw 0
n_xbase dw 0
n_tiles_same db 0          ; live: tile RAM unchanged since the last snapshot
n_shadow_tiles db 0        ; live: the shadow's tiles equal the snapshot's
n_ybase dw 0
n_left dw 0
n_right dw 0
n_bottom dw 0
n_screen dw 0
n_damage_row dw 0
n_mark_row dw 0
n_dirty_rows times 28 db 0
n_mark_off dw 0
n_mark_size dw 0
n_mark_height dw 0
n_mark_y dw 0
n_mark_x dw 0
n_mark_part dw 0
n_mark_wrapped dw 0
n_mark_count dw 0
n_first_diff dw 0
n_map_page dw 0
n_pending db 0
n_rows_done db 0
n_walked db 0                  ; live: rows walked in this render
n_start_row db 0               ; live: where the next walk starts
n_row_forced db 0
n_row_visited db 0
n_pending_rows times 28 db 0
n_bank db 0
n_damage times 1008 db 0
%ifdef NATIVE_PLANES
n_damage_used times 28 db 0     ; rows of n_damage that may hold marks
%endif
