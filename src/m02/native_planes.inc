; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Native packed-4bpp G1 background + alternating G0 fronts. No scheduler.
; Cache 7000, histories 3800:0600/0A00, SGP list 3900. Z80 5000/6000 untouched.
; GVRAM: front A 00000h, front B PLANES_FRONT_B, G1 20000h. Eight blank
; lines (and 8 bytes) are kept after each front and G1, and before them at
; the top of each 128 KiB region (1FB00h, 3FB00h, where a negative DSA
; wraps), so that the picture can be moved by DSA (alignment screen)
; without showing anything else.
PLANES_FRONT_B equ 9100h
PLANES_FRONT_B_SEG equ PLANES_FRONT_B / 16
PLANES_FRONT_C equ 12400h       ; TRIPLE_FRONTS only (margin to 1B800h)
%define KEEP_FIRST_BANK 7
%define KEEP_PACKED 1
%include "retained.inc"
%ifdef RECT_SPRITES
%define FRONT_BATCH 1             ; rect_sprites.inc: whole pieces, batched
; TRIPLE_FRONTS (live builds, m01test.asm): a third front (C at 12400h),
; so that a page can be drawn while the previous one waits for the SGP and
; its VRTC (live_video.inc).
%endif
%ifdef LIVE_VIDEO
%ifdef FRONT_HYBRID
%define ASYNC_LIST 1              ; damage-mode pieces batched too (planes_list)
%endif
%endif
%ifdef FRONT_FULL
%define FRONT_BATCH 1
%elifdef FRONT_HYBRID
%define FRONT_BATCH 1
%define CPU_RUN_CLEAR 1
%ifndef FRONT_THRESHOLD
%define FRONT_THRESHOLD 16
%endif
%endif
planes_init:
        call keep_reset
%ifdef RECT_SPRITES
        call rect_init            ; opaque boxes of the sprite images
%endif
        ; Canaries cover every unused GVRAM byte; checker verifies holes.
        mov bx,0a000h
        mov dx,4
.bank:  mov es,bx
        xor di,di
        mov ax,5a5ah
        mov cx,8000h
        rep stosw
        add bx,1000h
        dec dx
        jnz .bank
        mov ax,0a000h
        mov es,ax
        xor di,di
        xor ax,ax
        mov cx,8000h
        rep stosw                ; first 64 KiB of the two front pages
        ; The rest up to 12400h without wrapping a string operation.
        mov ax,0b000h
        mov es,ax
        xor di,di
        xor ax,ax
%ifdef TRIPLE_FRONTS
        mov cx,0b800h / 2        ; to 1B800h: front C and its margin
%else
        mov cx,1200h
%endif
        rep stosw
        mov di,0fb00h            ; above front A (1FB00h)
        mov cx,280h
        rep stosw
        mov ax,0c000h
        mov es,ax
        xor di,di
        xor ax,ax
        mov cx,4900h
        rep stosw                ; black background/margins, to 29200h
        mov ax,0d000h
        mov es,ax
        xor ax,ax
        mov di,0fb00h            ; above G1 (3FB00h)
        mov cx,280h
        rep stosw
        mov ax,3800h
        mov es,ax
        mov di,600h
        xor ax,ax
        mov cx,400h
        rep stosw                ; two 1024-byte history maps
        ; Reapply palette after BIOS setup. Current vaeg adjusts low DAC
        ; bits after each byte write; a first low/high pair may retain one
        ; red low bit from the old BIOS palette. A second pair settles it.
        mov dx,0300h
%ifdef LIVE_VIDEO
        mov si,N_PALETTE
%else
        mov si,CODE_BYTES
%endif
        mov cx,32
.palette:
        lodsw
        out dx,ax
        add dx,2
        loop .palette
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
        mov dx,0106h
        mov ax,00bah
        out dx,ax
        mov dx,0124h
        mov ax,1
        out dx,ax
        add dx,2
        xor ax,ax
        out dx,ax
        mov dx,0200h
        mov si,l_frames
        mov cx,32
.reg:   lodsw
        out dx,ax
        add dx,2
        loop .reg
        mov si,sync224
        mov al,10h
        call tsp_cmd
        mov cx,14
.sync:  lodsb
        call tsp_prm
        loop .sync
%ifndef LIVE_VIDEO
        xor ax,ax
        mov es,ax
        mov word [es:0ah*4],planes_vrtc
        mov [es:0ah*4+2],cs
        mov dx,018ah
        mov al,0fbh
        out dx,al
%endif
        sti
        ret
planes_begin:
%ifdef FRONT_BATCH
        mov byte [l_batch_mode],0
%endif
%ifdef BACKGROUND_CACHE
        call background_cache_begin
%endif
        mov word [l_hits],0
        mov word [l_misses],0
        mov word [l_fallbacks],0
        mov word [l_cleared],0
        mov word [r_keep_probes],0
        mov byte [l_same],0
        mov byte [l_reuse],0
        cmp byte [n_valid],0
        je .select
        mov ax,3800h
        mov es,ax
        mov di,1024
        mov si,N_OBJECT
        mov cx,192
        repe cmpsw
        jne .select
        mov byte [l_same],1
        mov byte [l_reuse],1       ; unchanged sprites: keep displayed front
        mov ax,[l_display_page]
%ifdef TRIPLE_FRONTS
        ; The newest picture is a page still waiting to be shown, if any:
        ; report that one (the shadow is its state).
        pushf
        cli
        cmp byte [live_pending2],0
        je .pending
        mov ax,[live_pending2_page]
        jmp .newest
.pending:
        cmp byte [live_pending],0
        je .newest
        mov ax,[live_pending_page]
.newest:
        popf
%endif
        mov [l_output_page],ax
        ret
.select:
%ifdef TRIPLE_FRONTS
        ; The first page neither shown nor waiting to be shown.
        xor bx,bx
.free:  cmp bl,[l_display_index]
        je .taken
        cmp bl,[live_pending_index]
        jne .chosen
.taken: inc bx
        jmp .free
.chosen:
        mov [l_target],bl
%endif
        xor bx,bx
        mov bl,[l_target]
        shl bx,1
        mov ax,[l_page_offsets + bx]
        mov [l_page],ax
        mov ax,[l_page_highs + bx]
        mov [l_page_hi],ax
        mov ax,[l_page_paras + bx]
        mov [l_output_page],ax
        mov di,[l_page_records + bx]
        shr bx,1
        cmp byte [l_valid + bx],0
        je .different
        mov ax,3800h
        mov es,ax
.compare:
        mov si,N_OBJECT
        mov cx,192
        repe cmpsw
        jne .different
        mov byte [l_same],1       ; background changes need no front repaint
.different:
        ret

; Background tile decoded once directly into G1. Same native lookup/code
; setup as the 8bpp path, but two pixels are written per byte.
planes_background_tile:
%ifdef BACKGROUND_CACHE
        call background_cache_tile
        jc .convert
        ret
.convert:
%endif
        push ds
        xor ax,ax
        mov al,[n_row]
        imul ax,ax,80
        add ax,0c000h
        mov es,ax
        xor di,di
        mov al,[n_col]
        xor ah,ah
        shl ax,2
        add ax,8
        mov di,ax
        mov si,[n_bg]
        mov bp,[n_fg]
        mov bx,[n_lookup]
        mov dl,[n_colour]
        mov ax,3000h
        mov ds,ax
        mov dh,8
.row:   mov cx,4
.pair:  lodsb
        cs xlatb
        and al,15
        cmp byte [ds:bp],0
        je .first
        mov al,dl
.first: inc bp
        shl al,4
        mov ah,al
        lodsb
        cs xlatb
        and al,15
        cmp byte [ds:bp],0
        je .second
        mov al,dl
.second:
        inc bp
        or al,ah
        stosb
        loop .pair
        add di,156
        dec dh
        jnz .row
        pop ds
%ifdef BACKGROUND_CACHE
        call background_cache_store
%endif
        ret

; Compare against this front's previous sprite state, not the last frame.
planes_damage:
        xor bx,bx
        mov bl,[l_target]
        mov byte [n_full],1
        cmp byte [l_valid + bx],0
        je .done
        mov byte [n_full],0
        push cs
        pop es
        xor ax,ax                 ; clear only the damage rows used before
        xor bx,bx
.used:  cmp byte [n_damage_used + bx],0
        je .unused
        mov byte [n_damage_used + bx],0
        imul di,bx,36
        add di,n_damage
        mov cx,18
        rep stosw
.unused:
        inc bx
        cmp bx,28
        jb .used
        mov di,n_dirty_rows
        mov cx,14
        rep stosw
        push ds
        mov ax,3800h
        mov ds,ax
        mov es,ax
        mov si,1800h
        cmp byte [cs:l_target],0
        je .copy
        add si,180h
.copy:  mov di,1024
        mov cx,192
        rep movsw
        pop ds
        call native_sprite_damage
.done:  ret
; Clear old/new damage cells on this exact front; a never-used page is
; already transparent. History maps remain a verification aid.
planes_clear:
        mov word [l_history],600h
        mov word [l_page],0
        cmp byte [l_target],0
        je .selected
        mov word [l_history],0a00h
        mov word [l_page],PLANES_FRONT_B
.selected:
        cmp byte [n_full],0
        jne .done
%ifdef CPU_RUN_CLEAR
        ; Merge horizontal runs of damaged cells; one REP STOSW per run line.
        ; Runs are found with REPE/REPNE SCASB over the damage row.
        xor bp,bp
.run_row:
        cmp byte [n_dirty_rows + bp],0
        je .run_next_row
        mov si,bp
        imul si,si,36
        add si,n_damage
        mov bx,si
        add bx,36                 ; BX: end of this damage row
.find:  mov cx,bx
        sub cx,si
        jbe .run_next_row
        push cs
        pop es
        mov di,si
        xor al,al
        repe scasb                ; skip clean cells
        je .run_next_row          ; the rest of the row is clean
        lea dx,[di - 1]           ; DX: first damaged cell of the run
        jcxz .end_row
        repne scasb               ; to the next clean cell
        jne .end_row
        lea si,[di - 1]           ; SI: the clean cell after the run
        jmp .clear
.end_row:
        mov si,bx
.clear: push bx
        push si
        mov cx,si
        sub cx,dx                 ; cells in run
        add [l_cleared],cx
        shl cx,1                  ; words per scan line
        mov [l_run_words],cx
        mov ax,bp
        imul ax,ax,80
        add ax,0a000h
        cmp byte [l_target],0
        je .run_segment
        add ax,PLANES_FRONT_B_SEG
.run_segment:
        mov es,ax
        mov di,dx
        sub di,n_damage
        mov ax,bp
        imul ax,ax,36
        sub di,ax                 ; column
        shl di,2
        add di,8
        mov dx,[l_run_words]
        shl dx,1
        mov bx,160
        sub bx,dx                 ; BX: line skip after the run
        xor ax,ax
        mov dx,8
.run_line:
        mov cx,[l_run_words]
        rep stosw
        add di,bx
        dec dx
        jnz .run_line
        pop si
        pop bx
        jmp .find
.run_next_row:
        inc bp
        cmp bp,28
        jb .run_row
        ret
%endif
        xor bp,bp
.row:   cmp byte [n_dirty_rows + bp],0
        je .next_row
        xor bx,bx
.cell:  mov ax,3800h
        mov es,ax
        mov di,bp
        imul di,di,36
        add di,bx
        add di,[l_history]
        sub di,[l_history]
        cmp byte [n_damage + di],0
        je .next
        add di,[l_history]
        mov byte [es:di],0
        inc word [l_cleared]
        push bx
        mov ax,bp
        imul ax,ax,80
        add ax,0a000h
        cmp byte [l_target],0
        je .segment
        add ax,PLANES_FRONT_B_SEG
.segment:
        mov es,ax
        mov di,bx
        shl di,2
        add di,8
        xor ax,ax
        mov dx,8
.erase: stosw
        stosw
        add di,156
        dec dx
        jnz .erase
        pop bx
.next:  inc bx
        cmp bx,36
        jb .cell
.next_row:
        inc bp
        cmp bp,28
        jb .row
.done:  ret
planes_clear_done equ planes_clear.done

; BP = source clipped top; native culling already computed other bounds.
%ifdef RECT_SPRITES
planes_sprite_keyed:              ; AX = the piece's key, BP = top (batched)
        mov [l_top],bp
        jmp planes_sprite.key
%endif
planes_sprite:
        mov [l_top],bp
%ifdef FRONT_BATCH
        cmp byte [l_batch_mode],0
        jne .lookup              ; whole front is cleared: no footprint maps
%endif
        ; Mark this front's current clipped footprint for its next reuse.
        mov ax,[n_xbase]
        add ax,[n_left]
        shr ax,3
        mov [l_first_col],ax
        mov dx,[n_xbase]
        add dx,[n_right]
        dec dx
        shr dx,3
        sub dx,ax
        inc dx
        mov [l_columns],dx
        mov ax,[n_ybase]
        add ax,bp
        shr ax,3
        mov bx,[n_ybase]
        add bx,[n_bottom]
        dec bx
        shr bx,3
        sub bx,ax
        inc bx
        mov dx,bx
        imul ax,ax,36
        add ax,[l_first_col]
        add ax,[l_history]
        mov di,ax
        mov ax,3800h
        mov es,ax
.mark:  push di
        mov cx,[l_columns]
        mov al,1
        rep stosb
        pop di
        add di,36
        dec dx
        jnz .mark
.lookup:
        mov ax,[n_lookup]
        sub ax,N_SPRLOOKUP
        shl ax,6
        mov bx,[n_sprite]
        shr bx,8
        or ax,bx
        cmp byte [n_fx],0
        je .fy
        or ax,4000h
.fy:    cmp byte [n_fy],0         ; Y flip also stored flipped: a negative
        je .key                   ; source pitch garbles on the VA and VA2
        or ax,8000h
.key:   mov [r_key],ax
        call keep_lookup
        jnc .hit
        cmp ax,0ffffh
        jne .new
        ; No eviction. Render this one request using uncached CPU pixels.
        inc word [l_fallbacks]
        call planes_cpu_sprite
        ret
.new:   inc word [l_misses]
        call planes_convert
        jmp .paint
.hit:   inc word [l_hits]
.paint:
%ifdef FRONT_BATCH
        cmp byte [l_batch_mode],0
        jne planes_batch_add
%endif
        call planes_list
        ret
planes_convert:
        push ds
        mov ax,7000h
        mov es,ax
        mov di,[r_cache_offset]
        mov ax,4000h
        mov ds,ax
        xor bp,bp
.row:   mov si,bp
        cmp byte [cs:n_fy],0      ; Y flip: rows in reverse
        je .rows
        xor si,15
.rows:  shl si,4
        add si,[cs:n_sprite]
        mov dx,1
        cmp byte [cs:n_fx],0
        je .forward
        add si,15
        mov dx,-1
.forward:
        mov bx,[cs:n_lookup]
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
planes_cpu_sprite:
%ifdef FRONT_BATCH
        call planes_batch_flush  ; keep priority order and finish the CLS
%endif
        push ds
        mov ax,4000h
        mov ds,ax
        mov bp,[cs:l_top]
.row:   mov ax,bp
        cmp byte [cs:n_fy],0
        je .sy
        xor ax,15
.sy:    shl ax,4
        add ax,[cs:n_sprite]
        mov si,ax
        mov ax,bp
        add ax,[cs:n_ybase]
        imul ax,ax,10
        add ax,0a000h
        cmp byte [cs:l_target],0
        je .segment
        add ax,PLANES_FRONT_B_SEG
.segment:
        mov es,ax
        mov dx,[cs:n_left]
.pixel:
        cmp byte [cs:n_full],0
        jne .paint
        mov ax,[cs:n_ybase]
        add ax,bp
        shr ax,3
        imul ax,ax,36
        mov bx,[cs:n_xbase]
        add bx,dx
        shr bx,3
        add bx,ax
        cmp byte [cs:n_damage + bx],0
        je .skip
.paint: mov bx,dx
        cmp byte [cs:n_fx],0
        je .sx
        xor bx,15
.sx:    mov al,[si+bx]
        mov bx,[cs:n_lookup]
        cs xlatb
        inc al
        and al,15
        jz .skip
        mov ah,al
        mov bx,[cs:n_xbase]
        add bx,dx
        add bx,16
        mov di,bx
        shr di,1
        test bl,1
        jnz .low
        shl ah,4
        mov al,[es:di]
        and al,15
        jmp .store
.low:   mov al,[es:di]
        and al,0f0h
.store: or al,ah
        mov [es:di],al
.skip:  inc dx
        cmp dx,[cs:n_right]
        jb .pixel
        inc bp
        cmp bp,[cs:n_bottom]
        jb .row
        pop ds
        ret
planes_list:
%ifdef ASYNC_LIST
        ; The live game: every piece goes into the render's one batch list
        ; (3A000h), submitted without waiting at the end (planes_ready), so
        ; the SGP draws while the programs run. Room for nine commands.
        mov ax,3a00h
        mov es,ax
        mov di,[l_batch_ptr]
        cmp di,6000h - 9 * 24 - 8
        jb .room
        call planes_batch_flush
        mov ax,3a00h
        mov es,ax
        xor di,di
.room:  or di,di
        jnz .listed
        mov ax,3
        stosw
        mov ax,l_work
        stosw
        mov ax,2
        stosw
.listed:
%else
        mov ax,3900h
        mov es,ax
        xor di,di
        mov ax,3
        stosw
        mov ax,l_work
        stosw
        mov ax,2
        stosw
%endif
        mov word [l_commands],0
        mov ax,[n_left]
        mov [l_left],ax
        cmp byte [n_full],0
%ifdef SPRITE_COALESCE
        jne .whole
        call planes_whole_damage
        jc .bands
%else
        je .bands
%endif
.whole: mov ax,[n_right]
        sub ax,[n_left]
        mov [l_width],ax
        mov ax,[n_bottom]
        sub ax,[l_top]
        mov [l_height],ax
        call planes_emit
        jmp .submit
.bands:
        mov ax,[l_top]
        add ax,[n_ybase]
        and ax,7
        mov bx,8
        sub bx,ax
        mov ax,[n_bottom]
        sub ax,[l_top]
        cmp bx,ax
        jbe .height
        mov bx,ax
.height:
        mov [l_height],bx
        mov ax,[n_left]
        mov [l_left],ax
.cell:  mov ax,[l_left]
        add ax,[n_xbase]
        mov dx,ax
        and ax,7
        mov bx,8
        sub bx,ax
        mov ax,[n_right]
        sub ax,[l_left]
        cmp bx,ax
        jbe .width
        mov bx,ax
.width: mov [l_width],bx
        shr dx,3
        mov bx,[l_top]
        add bx,[n_ybase]
        shr bx,3
        imul bx,bx,36
        add bx,dx
        cmp byte [n_damage + bx],0
        je .next_cell
        call planes_emit
.next_cell:
        mov ax,[l_width]
        add [l_left],ax
        mov ax,[l_left]
        cmp ax,[n_right]
        jb .cell
        mov ax,[l_height]
        add [l_top],ax
        mov ax,[l_top]
        cmp ax,[n_bottom]
        jb .bands
.submit:
%ifdef ASYNC_LIST
        mov [l_batch_ptr],di      ; END is added when the batch is submitted
        ret
%else
        cmp word [l_commands],0
        je .done
        mov ax,1
        stosw
        call planes_run
.done:  ret
%endif
planes_list_built equ planes_list.submit
%ifdef SPRITE_COALESCE
; CF=0 only if every damage cell intersecting this clipped sprite is dirty.
; A single full-piece blit then replaces up to nine cell-fragment commands.
planes_whole_damage:
        mov ax,[n_xbase]
        add ax,[n_left]
        shr ax,3
        mov dx,[n_xbase]
        add dx,[n_right]
        dec dx
        shr dx,3
        sub dx,ax
        inc dx
        mov si,[n_ybase]
        add si,[l_top]
        shr si,3
        mov bp,[n_ybase]
        add bp,[n_bottom]
        dec bp
        shr bp,3
        sub bp,si
        inc bp
        imul si,si,36
        add si,ax
.row:   mov bx,si
        mov cx,dx
.cell:  cmp byte [n_damage+bx],0
        je .partial
        inc bx
        loop .cell
        add si,36
        dec bp
        jnz .row
        clc
        ret
.partial:
        stc
        ret
%endif
planes_emit:
        inc word [l_commands]
        mov ax,4
        stosw
        mov ax,[l_left]
        and ax,3
        shl ax,4
        or ax,1
        stosw
        mov ax,[l_width]
        stosw
        mov ax,[l_height]
        stosw
        mov ax,8                  ; the cached image is already flipped
        stosw
        mov ax,[l_top]
        shl ax,3
        add ax,[r_cache_offset]
        mov bx,[l_left]
        shr bx,1
        add ax,bx
        and ax,0fffeh
        stosw
        mov ax,7
        stosw
        mov ax,5
        stosw
        mov ax,[n_xbase]
        add ax,[l_left]
        add ax,16
        mov bx,ax
        and ax,3
        shl ax,4
        or ax,1
        stosw
        mov ax,[l_width]
        stosw
        mov ax,[l_height]
        stosw
        mov ax,160
        stosw
        mov ax,[n_ybase]
        add ax,[l_top]
        imul ax,ax,160
        shr bx,1
        add ax,bx
        mov dx,20h
        add ax,[l_page]
        adc dx,[l_page_hi]
        and ax,0fffeh
        stosw
        mov ax,dx
        stosw
        mov ax,7
        stosw
        mov ax,0105h
        stosw
        ret
%ifdef FRONT_BATCH
%ifdef FRONT_HYBRID
; Cheap estimate before building any damage map: count 16x16 pieces of
; entries that differ from this front's previous state, old and new sizes.
; At or above FRONT_THRESHOLD, or for an unused page: whole-front policy.
; Otherwise page-local damage with merged CPU runs.
planes_hybrid:
        xor bx,bx
        mov bl,[l_target]
        cmp byte [l_valid + bx],0
        je planes_full_begin
        mov di,1800h
        or bx,bx
        jz .record
        add di,180h
.record:
        mov ax,3800h
        mov es,ax
        xor bx,bx                 ; entry offset
        xor dx,dx                 ; weighted changed pieces
.entry: mov ax,[N_OBJECT+bx]
        cmp ax,[es:di+bx]
        jne .changed
        mov ax,[N_POSITION+bx]
        cmp ax,[es:di+bx+128]
        jne .changed
        mov ax,[N_FLIP+bx]
        cmp ax,[es:di+bx+256]
        je .next
.changed:
        mov al,[N_OBJECT+bx]
        mov cl,1
        test al,80h
        jz .new
        mov cl,4
.new:   add dl,cl
        mov al,[es:di+bx]
        mov cl,1
        test al,80h
        jz .old
        mov cl,4
.old:   add dl,cl
        adc dh,0
        cmp dx,FRONT_THRESHOLD
        jae planes_full_begin
.next:  add bx,2
        cmp bx,128
        jb .entry
        inc word [l_dirty_frames]
        call planes_damage
        jmp planes_clear
l_dirty_frames dw 0
l_full_frames dw 0
%endif
; Whole-front policy: one asynchronous CLS of the reused front, then every
; visible piece in one transfer list. No damage map or per-cell clearing.
; Lists: CLS at physical 39B00h, sprite batch 3A000h..3FFFFh.
planes_full_begin:
%ifdef FRONT_HYBRID
        inc word [l_full_frames]
%endif
        mov byte [l_batch_mode],1
        mov byte [n_full],1
        mov word [l_batch_ptr],0
        xor bx,bx
        mov bl,[l_target]
        cmp byte [l_valid + bx],0
        jne .used
        mov word [l_cleared],0    ; never-drawn front is still transparent
        ret
.used:  mov word [l_cleared],1008
%ifdef FRONT_CPU_CLEAR
        ; Comparison variant: synchronous CPU fill of the whole reused front.
        mov ax,0a000h
        cmp byte [l_target],0
        je .cpu
        mov ax,0a000h + PLANES_FRONT_B_SEG
.cpu:   mov es,ax
        xor di,di
        xor ax,ax
        mov cx,35840/2
        rep stosw
        ret
%endif
        mov ax,39b0h
        mov es,ax
        xor di,di
        mov ax,3
        stosw
        mov ax,l_work
        stosw
        mov ax,2
        stosw
        mov ax,6                  ; SET_COLOR 0: transparent packed pixels
        stosw
        xor ax,ax
        stosw
        mov ax,0ah                ; CLS: start address, word count
        stosw
        mov ax,[l_page]
        stosw
        mov ax,20h
        stosw
        mov ax,35840/2
        stosw
        xor ax,ax
        stosw
        mov ax,1
        stosw
        mov ax,9b00h
        jmp planes_submit         ; CPU continues while the SGP clears
planes_batch_add:
        mov ax,3a00h
        mov es,ax
        mov di,[l_batch_ptr]
        or di,di
        jnz .append
        mov ax,3
        stosw
        mov ax,l_work
        stosw
        mov ax,2
        stosw
.append:
        mov ax,[n_left]
        mov [l_left],ax
        mov ax,[n_right]
        sub ax,[n_left]
        mov [l_width],ax
        mov ax,[n_bottom]
        sub ax,[l_top]
        mov [l_height],ax
        call planes_emit
        mov [l_batch_ptr],di
%if %isdef(TRIPLE_FRONTS) || %isdef(RECT_SPRITES)
        cmp di,1000h-40           ; 3A00:1000h on: the rectangle lists' areas
%else
        cmp di,6000h-40
%endif
        jb .done
        call planes_batch_flush
.done:  ret
; Submit queued pieces after any CLS completes, then wait for completion.
planes_batch_flush:
        mov di,[l_batch_ptr]
        or di,di
        jz planes_wait
        mov ax,3a00h
        mov es,ax
        mov ax,1
        stosw
        mov word [l_batch_ptr],0
        mov ax,0a000h
        call planes_submit
        jmp planes_wait
%ifdef LIVE_VIDEO
; The last list of a render: submit it and return without waiting. Every
; later SGP use waits first (planes_submit), the VRTC handler shows the page
; only when the SGP is idle, and no render starts while a page waits to be
; shown. A pending CLS with no list is likewise left to finish.
planes_batch_finish:
        mov di,[l_batch_ptr]
        or di,di
        jz .done
        mov ax,3a00h
        mov es,ax
        mov ax,1
        stosw
        mov word [l_batch_ptr],0
        mov ax,0a000h
        jmp planes_submit
.done:  ret
%endif
l_batch_ptr dw 0
l_batch_mode db 0
%endif
planes_run:
        mov ax,9000h
        call planes_submit
        jmp planes_wait
; Start the list at physical 3xxxxh, AX = low word. Does not wait for it.
planes_submit:
        push ax
        call planes_wait
        mov dx,0580h
        mov al,10h
        out dx,al
        mov dx,0500h
        pop ax
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
        ret
planes_wait:
        mov dx,0506h
        mov bx,256
.outer: mov cx,0ffffh
.poll:  in al,dx
        test al,1
        jz .ready
        loop .poll
        dec bx
        jnz .outer
.failed:
        hlt
        jmp .failed
.ready: ret
planes_run_done equ planes_wait.ready
planes_ready:
%ifdef FRONT_BATCH
%ifdef LIVE_VIDEO
        call planes_batch_finish ; the SGP finishes while the programs run
%else
        call planes_batch_flush  ; also completes a CLS with no sprites
%endif
%endif
        cmp byte [l_reuse],0
        jne .done
        mov ax,3800h
        mov es,ax
        xor bx,bx
        mov bl,[l_target]
        shl bx,1
        mov di,[l_page_records + bx]
        shr bx,1
        mov byte [l_valid + bx],1
        mov si,N_OBJECT
        mov cx,192
        rep movsw
.done:  ret
planes_present:
%ifdef LIVE_VIDEO
        jmp live_present
%endif
        pusha
        cmp byte [l_reuse],0
        jne .settle
        mov ax,[l_ticks]
.wait:  cmp ax,[l_ticks]
        je .wait
        mov dx,020eh
        mov ax,[l_output_page]
        mov [l_display_page],ax
        mov ax,[l_page]
        out dx,ax
        add dx,2
        xor ax,ax
        out dx,ax
        xor byte [l_target],1
.settle:
%ifdef VIDEO_GUARDS
        ; Test-only final-mixer settling. Never included in renderer clocks.
        mov ax,[l_ticks]
        add ax,2
.settle_wait:
        mov dx,[l_ticks]
        sub dx,ax
        js .settle_wait
%endif
        mov di,[l_display_page]
planes_shown:
        popa
        ret
planes_vrtc:
        push ax
        push dx
        inc word [cs:l_ticks]
        mov dx,0188h
        mov al,20h
        out dx,al
        pop dx
        pop ax
        iret
l_frames dw 0,0,160,447,0,0,0,0,0,224,0,0,0,0,0,0
         dw 0,0,160,0,0,0,0,0,0,224,0,0,0,0,0,0
l_hits dw 0
l_misses dw 0
l_fallbacks dw 0
l_cleared dw 0
l_run_words dw 0
l_top dw 0
l_left dw 0
l_commands dw 0
l_width dw 0
l_height dw 0
l_history dw 600h
l_page dw 0
l_target db 0
l_same db 0
l_reuse db 0
l_display_page dw 0        ; paragraphs of GVRAM (offset / 16)
l_output_page dw 0
l_page_hi dw 0             ; bit 16 of the target page's offset
l_valid db 0,0,0
l_display_index db 0
        align 2
l_page_offsets dw 0, PLANES_FRONT_B, PLANES_FRONT_C & 0ffffh
l_page_highs dw 0, 0, PLANES_FRONT_C >> 16
l_page_paras dw 0, PLANES_FRONT_B / 16, PLANES_FRONT_C / 16
l_page_records dw 1800h, 1980h, 1b00h   ; in 3800h: each front's last state
%ifndef LIVE_VIDEO
l_ticks dw 0
%endif
l_first_col dw 0
l_columns dw 0
d_source_high dw 7
l_work times 29 dw 0
%ifdef RECT_SPRITES
%include "rect_sprites.inc"
%endif
