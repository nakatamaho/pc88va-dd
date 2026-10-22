; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Sprite fronts by rectangle lists (RECT_SPRITES), in place of the 8x8
; damage maps (planes_hybrid, planes_damage, planes_clear, native_sprite).
;
; Each front keeps the list of the pieces last drawn into it (a piece: one
; visible 16x16 part of a sprite entry, or its copy 256 dots right). A new
; list is built from the video state in the entries' priority order and
; compared position by position with the front's old one:
;   - an old piece not equal to the new piece at its position (key, x, y)
;     is cleared by the CPU (its rectangle widened to whole words);
;   - a new piece is drawn when it changed, or overlaps a cleared
;     rectangle, or overlaps an earlier (lower-priority) piece being drawn;
; drawn pieces go whole, one SGP command each, into the asynchronous batch.
; An unchanged piece above a redrawn one stays: the redrawn one is drawn
; first. A piece's rectangle is its clip within its image's opaque box
; (RECT_BBOX, from the pens, when the entry's lookup makes pen 0 transparent,
; as all the game's do); a blank piece is neither recorded nor drawn. With more than RECT_MAX pieces or RECT_CLEARS clears, the front is
; cleared whole and every piece drawn; the list then counts as unknown.
;
; Lists in 3800h: front A at 0600h, B at 0E00h (RECT_MAX records of 16
; bytes: key, x base, y base, x0, x1, y0, y1 (screen dots, x1/y1 exclusive),
; flag 1 = draw); cleared rectangles at 3800h (8 bytes each), followed
; in rect_overlaps by the rectangles of the pieces to draw.

RECT_MAX	equ	128
RECT_CLEARS	equ	64
RECT_LIST_A	equ	0600h
RECT_LIST_B	equ	0e00h
RECT_LIST_C	equ	3000h		; (3A00:1000h: the batch list ends below)
RECT_CLEARED	equ	3800h		; then the flagged pieces' (rect_overlaps)
RECT_BBOX	equ	4000h		; 1 KiB: the images' opaque boxes (rect_init)

; Opaque boxes of the 256 sprite images (pens at 4000:0000, 256 bytes
; each), at 3800:RECT_BBOX (ES in rect_piece): x0, x1, y0, y1 of the
; pixels with a nonzero pen, x1/y1 exclusive; x0 >= x1 for a blank image.
; Once, after the pens are unpacked.
rect_init:	pusha
		push	ds
		push	es
		mov	ax,3800h
		mov	es,ax
		mov	di,RECT_BBOX
		mov	ax,4000h
		mov	ds,ax
		xor	si,si
		mov	bp,256
.code:		mov	bx,0010h		; BL x0, BH x1, DL y0, DH y1
		mov	dx,0010h
		xor	ch,ch			; CH: y, CL: x
.row:		xor	cl,cl
.pixel:		lodsb
		or	al,al
		jz	.next
		cmp	cl,bl
		jae	.x1
		mov	bl,cl
.x1:		mov	al,cl
		inc	al
		cmp	al,bh
		jbe	.y0
		mov	bh,al
.y0:		cmp	ch,dl
		jae	.y1
		mov	dl,ch
.y1:		mov	al,ch
		inc	al
		cmp	al,dh
		jbe	.next
		mov	dh,al
.next:		inc	cl
		cmp	cl,16
		jb	.pixel
		inc	ch
		cmp	ch,16
		jb	.row
		mov	ax,bx
		stosw
		mov	ax,dx
		stosw
		dec	bp
		jnz	.code
		pop	es
		pop	ds
		popa
		ret

rect_sprites:
		xor	bx,bx
		mov	bl,[l_target]
		mov	[r_front],bx
		shl	bx,1
		mov	ax,[r_lists + bx]
		mov	[r_list],ax
		mov	ax,[r_counts + bx]	; FFFFh: unknown contents
		mov	[r_old],ax
		mov	word [r_count],0
		mov	word [r_cleared],0
		mov	byte [r_overflow],0
		mov	byte [r_mode],0		; 0: build the list
		mov	byte [l_batch_mode],1	; whole pieces into the batch
		call	rect_entries
		cmp	byte [r_overflow],0
		jne	.full
		cmp	word [r_old],0ffffh
		je	.full
		; Old pieces past the new list are cleared.
		mov	ax,3800h
		mov	es,ax
		mov	cx,[r_count]
.tail:		cmp	cx,[r_old]
		jae	.marked
		mov	si,cx
		shl	si,4
		add	si,[r_list]
		call	rect_clear_old
		jc	.full
		inc	cx
		jmp	.tail
.marked:	call	rect_overlaps
		call	rect_clear_all
		call	rect_draw_flagged
		mov	ax,[r_count]
		jmp	.done
.full:		call	rect_clear_front	; whole front, every piece
		mov	byte [r_mode],1
		mov	word [r_count],0
		mov	byte [r_overflow],0
		call	rect_entries		; record (up to RECT_MAX) and draw
		mov	ax,[r_count]
		cmp	byte [r_overflow],0
		je	.done
		mov	ax,0ffffh
.done:		mov	bx,[r_front]
		shl	bx,1
		mov	[r_counts + bx],ax
		mov	ax,[r_cleared]
		mov	[l_cleared],ax
		ret

; Every visible piece in priority order to rect_piece (as
; native_planes_sprites walks them). ES = 3800h throughout (rect_piece).
rect_entries:
		mov	ax,3800h
		mov	es,ax
		xor	bx,bx
		; Y first: entries above the raster (unused ones) are passed over
		; here. AL = 257 - y (less 16 for a large entry); sy = AL - 32 is
		; visible above -16, or, large, above -32.
.scan:		mov	ah,[N_OBJECT + bx]	; size: bit 7
		mov	al,[N_POSITION + bx]
		neg	al
		inc	al
		or	ah,ah
		js	.y_large
		cmp	al,16
		ja	.visible
.pass:		add	bx,2
		cmp	bx,128
		jb	.scan
		ret
.y_large:	sub	al,16
		jz	.pass
.visible:	mov	[n_off],bx
		xor	ah,ah
		sub	ax,32			; sy: -32 .. 223
		mov	[n_sy],ax
		mov	al,[N_POSITION + bx + 1]
		xor	ah,ah
		sub	ax,39
		mov	[n_sx],ax
		mov	al,[N_OBJECT + bx + 1]
		and	ax,003fh
		mov	dl,[N_FLIP + bx]
		and	dl,3
		ror	dl,1
		ror	dl,1
		or	dl,al
		mov	[r_key_high],dl		; key: lookup, X flip 40h, Y flip 80h
		shl	ax,2
		add	ax,N_SPRLOOKUP
		mov	[n_lookup],ax
		mov	si,ax			; pen 0 transparent: opaque boxes apply
		mov	al,[si]
		and	al,15
		cmp	al,15
		mov	byte [r_boxed],0
		jne	.flips
		mov	byte [r_boxed],1
.flips:		mov	al,[N_FLIP + bx]
		mov	ah,al
		and	al,1
		mov	[n_fx],al
		shr	ah,1
		and	ah,1
		mov	[n_fy],ah
		mov	al,[N_OBJECT + bx]
		xor	ah,ah
		test	al,80h
		jnz	.large
		mov	byte [n_size],0		; one piece: no part loops
		mov	ah,al
		xor	al,al
		mov	[n_sprite],ax
		mov	ax,[n_sx]
		and	ax,255
		mov	[n_xbase],ax
		mov	ax,[n_sy]
		mov	[n_ybase],ax
		call	rect_piece
		cmp	word [n_xbase],16	; the copy 256 dots right
		jae	.next_object
		add	word [n_xbase],256
		call	rect_piece
		jmp	.next_object
.large:		mov	byte [n_size],1
		mov	dx,ax
		and	dx,0c0h
		and	ax,3fh
		shl	ax,2
		or	ax,dx
		mov	[n_code],ax
		mov	byte [n_ty],0
.part_y:	mov	byte [n_tx],0
.part_x:	xor	ax,ax
		mov	al,[n_ty]
		and	al,1
		xor	al,[n_fy]
		shl	ax,1
		mov	bl,[n_tx]
		xor	bl,[n_fx]
		xor	bh,bh
		add	ax,bx
		add	ax,[n_code]
		shl	ax,8
		mov	[n_sprite],ax
		xor	ax,ax
		mov	al,[n_tx]
		shl	ax,4
		add	ax,[n_sx]
		and	ax,255
		mov	[n_xbase],ax
		xor	ax,ax
		mov	al,[n_ty]
		shl	ax,4
		add	ax,[n_sy]
		mov	[n_ybase],ax
		call	rect_piece
		cmp	word [n_xbase],16	; the copy 256 dots right
		jae	.no_wrap
		add	word [n_xbase],256
		call	rect_piece
.no_wrap:	inc	byte [n_tx]
		cmp	byte [n_tx],1
		jbe	.part_x
		inc	byte [n_ty]
		cmp	byte [n_ty],1
		jbe	.part_y
.next_object:	mov	bx,[n_off]
		jmp	.pass

; The piece at n_sprite, n_xbase, n_ybase with the entry's r_key_high
; (and, for drawing, n_lookup, n_fx, n_fy). Clipped as native_sprite, in
; registers: AX x base, BX left, CX right, DX y base, BP top, SI bottom.
rect_piece:	mov	al,[n_sprite + 1]
		mov	ah,[r_key_high]
		mov	[r_new_key],ax
		cmp	byte [r_boxed],0
		je	.clip
		xor	ah,ah			; DI: the image's box, kept to .bottom
		shl	ax,2
		mov	di,ax
		mov	ax,[es:RECT_BBOX + di]	; x0, x1: a blank image leaves at once
		cmp	al,ah
		jae	.ret
.clip:		mov	ax,[n_xbase]
		cmp	ax,272
		jae	.ret
		or	ax,ax
		jz	.ret
		mov	bx,16
		sub	bx,ax
		jns	.left
		xor	bx,bx
.left:		mov	cx,272
		sub	cx,ax
		cmp	cx,16
		jbe	.right
		mov	cx,16
.right:		mov	dx,[n_ybase]
		cmp	dx,224
		jge	.ret
		cmp	dx,-16
		jle	.ret
		xor	bp,bp
		or	dx,dx
		jns	.top
		sub	bp,dx
.top:		mov	si,224
		sub	si,dx
		cmp	si,16
		jle	.bottom
		mov	si,16
.bottom:	cmp	byte [r_boxed],0
		je	.boxed
		push	ax
		push	dx
		mov	ax,[es:RECT_BBOX + di]	; x0, x1
		cmp	byte [n_fx],0
		je	.x_box
		mov	dl,16			; mirrored: 16 - x1, 16 - x0
		sub	dl,ah
		mov	ah,16
		sub	ah,al
		mov	al,dl
.x_box:		xor	dh,dh
		mov	dl,al
		cmp	bx,dx
		jge	.x0_kept
		mov	bx,dx
.x0_kept:	mov	dl,ah
		cmp	cx,dx
		jle	.x1_kept
		mov	cx,dx
.x1_kept:	cmp	bx,cx
		jge	.blank
		mov	ax,[es:RECT_BBOX + di + 2]	; y0, y1
		cmp	byte [n_fy],0
		je	.y_box
		mov	dl,16
		sub	dl,ah
		mov	ah,16
		sub	ah,al
		mov	al,dl
.y_box:		xor	dh,dh
		mov	dl,al
		cmp	bp,dx
		jge	.y0_kept
		mov	bp,dx
.y0_kept:	mov	dl,ah
		cmp	si,dx
		jle	.y1_kept
		mov	si,dx
.y1_kept:	cmp	bp,si
		jge	.blank
		pop	dx
		pop	ax
.boxed:		cmp	byte [r_mode],0
		jne	.full
		mov	di,[r_count]
		cmp	di,RECT_MAX
		jae	.overflow
		shl	di,4
		add	di,[r_list]
		cmp	word [r_old],0ffffh	; unknown front: all redrawn anyway
		je	.draw
		push	ax
		mov	ax,[r_count]
		cmp	ax,[r_old]
		pop	ax
		jae	.draw
		cmp	ax,[es:di + 2]		; same piece as the old one here?
		jne	.changed
		cmp	dx,[es:di + 4]
		jne	.changed
		push	ax
		mov	ax,[r_new_key]
		cmp	ax,[es:di]
		pop	ax
		jne	.changed
		mov	word [es:di + 14],0	; kept: the rest of the record holds
		inc	word [r_count]
.ret:		ret
.changed:	push	ax			; the old one is cleared
		push	si
		mov	si,di
		call	rect_clear_old
		pop	si
		pop	ax
		jc	.overflow		; too many clears: whole front
.draw:		mov	[es:di + 2],ax		; x base, y base, x0, x1, y0, y1
		mov	[es:di + 4],dx
		add	ax,16
		add	bx,ax
		mov	[es:di + 6],bx
		add	cx,ax
		mov	[es:di + 8],cx
		add	bp,dx
		mov	[es:di + 10],bp
		add	si,dx
		mov	[es:di + 12],si
		mov	ax,[r_new_key]
		mov	[es:di],ax
		mov	word [es:di + 14],1
		inc	word [r_count]
		ret
.overflow:	mov	byte [r_overflow],1
		ret
.blank:		pop	dx			; nothing opaque is visible
		pop	ax
		ret
.full:		mov	[n_left],bx		; full mode: draw at once
		mov	[n_right],cx
		mov	[n_bottom],si
		push	bp
		call	planes_sprite
		pop	bp
		cmp	word [r_count],RECT_MAX
		jae	.overflow
		mov	ax,3800h
		mov	es,ax
		mov	di,[r_count]
		shl	di,4
		add	di,[r_list]
		mov	ax,[n_xbase]
		mov	dx,[n_ybase]
		mov	bx,[n_left]
		mov	cx,[n_right]
		mov	si,[n_bottom]
		jmp	.draw

; Queue the old record ES:SI's rectangle, widened to whole words (4 dots),
; for clearing; CF = 1 if the list is full. Keeps DI.
rect_clear_old:	push	di
		call	.queue
		pop	di
		ret
.queue:		mov	di,[r_cleared]
		cmp	di,RECT_CLEARS
		jae	.full
		inc	word [r_cleared]
		shl	di,3
		add	di,RECT_CLEARED
		mov	ax,[es:si + 6]
		and	ax,0fffch
		mov	[es:di],ax
		mov	ax,[es:si + 8]
		add	ax,3
		and	ax,0fffch
		mov	[es:di + 2],ax
		mov	ax,[es:si + 10]
		mov	[es:di + 4],ax
		mov	ax,[es:si + 12]
		mov	[es:di + 6],ax
		clc
		ret
.full:		stc
		ret

; Flag the kept pieces that overlap a cleared rectangle or an earlier
; flagged piece (ES = 3800h). The rectangles tested are one array: the
; cleared ones, then each flagged piece's as the walk passes it. A kept
; piece's x0, x1, y0 are held in DX, BX, BP; rectangles meet when
; x0 < x1', x0' < x1, y0 < y1' and y0' < y1.
rect_overlaps:	mov	ax,3800h
		mov	es,ax
		mov	di,[r_list]
		mov	cx,[r_count]
		or	cx,cx
		jnz	.start
		ret
.start:		mov	ax,[r_cleared]
		shl	ax,3
		add	ax,RECT_CLEARED
		mov	[r_tested_end],ax
.piece:		cmp	byte [es:di + 14],0
		jne	.append
		push	cx
		mov	dx,[es:di + 6]
		mov	bx,[es:di + 8]
		mov	bp,[es:di + 10]
		mov	si,RECT_CLEARED
		mov	cx,[r_tested_end]
		cmp	si,cx
		jae	.kept
.test:		mov	ax,[es:si]
		cmp	ax,bx
		jge	.no
		cmp	dx,[es:si + 2]
		jge	.no
		mov	ax,[es:si + 4]
		cmp	ax,[es:di + 12]
		jge	.no
		cmp	bp,[es:si + 6]
		jl	.flag
.no:		add	si,8
		cmp	si,cx
		jb	.test
.kept:		pop	cx
		jmp	.next
.flag:		mov	byte [es:di + 14],1
		pop	cx
.append:	mov	si,[r_tested_end]	; x0, x1, y0, y1 of a piece drawn
		mov	ax,[es:di + 6]
		mov	[es:si],ax
		mov	ax,[es:di + 8]
		mov	[es:si + 2],ax
		mov	ax,[es:di + 10]
		mov	[es:si + 4],ax
		mov	ax,[es:di + 12]
		mov	[es:si + 6],ax
		add	si,8
		mov	[r_tested_end],si
.next:		add	di,16
		dec	cx
		jnz	.piece
		ret

; Clear the queued rectangles on the target front (CPU, word writes).
; DS = 3800h for the rectangles meanwhile. A rectangle is at most five
; words wide: one unrolled line loop per width (STOSW 3 clocks, against 4
; more for MOV CX and REP STOSW on a line), two lines a pass for 4 and 5.
rect_clear_all:	mov	cx,[r_cleared]
		or	cx,cx
		jnz	.start
		ret
.start:		call	rect_front_segment
		push	ds
		mov	ax,3800h
		mov	ds,ax
		mov	si,RECT_CLEARED
.rect:		push	cx
		lodsw				; x0 (dots, multiple of 4)
		mov	bx,ax
		lodsw
		sub	ax,bx
		shr	ax,2
		mov	dx,ax			; DX: words a line
		lodsw				; y0
		mov	di,ax
		lodsw
		sub	ax,di
		jle	.empty
		mov	bp,ax			; BP: lines
		or	dx,dx
		jnz	.lines
.empty:		jmp	.skip
.lines:		imul	di,di,160
		shr	bx,1
		add	di,bx
		mov	bx,160
		sub	bx,dx
		sub	bx,dx			; BX: skip after a line
		xor	ax,ax
		cmp	dx,5
		ja	.wide
		push	si
		mov	si,dx
		shl	si,1
		mov	cx,[cs:.widths - 2 + si]
		pop	si
		jmp	cx
.wide:		mov	cx,dx			; (not reached: rectangles are narrower)
		rep	stosw
		add	di,bx
		dec	bp
		jnz	.wide
		jmp	.skip
.w1:		stosw
		add	di,bx
		dec	bp
		jnz	.w1
		jmp	.skip
.w2:		stosw
		stosw
		add	di,bx
		dec	bp
		jnz	.w2
		jmp	.skip
.w3:		stosw
		stosw
		stosw
		add	di,bx
		dec	bp
		jnz	.w3
		jmp	.skip
.w4:		test	bp,1
		jz	.w4_pairs
		stosw
		stosw
		stosw
		stosw
		add	di,bx
.w4_pairs:	shr	bp,1
		jz	.skip
.w4_pair:	stosw
		stosw
		stosw
		stosw
		add	di,bx
		stosw
		stosw
		stosw
		stosw
		add	di,bx
		dec	bp
		jnz	.w4_pair
		jmp	.skip
.w5:		test	bp,1
		jz	.w5_pairs
		stosw
		stosw
		stosw
		stosw
		stosw
		add	di,bx
.w5_pairs:	shr	bp,1
		jz	.skip
.w5_pair:	stosw
		stosw
		stosw
		stosw
		stosw
		add	di,bx
		stosw
		stosw
		stosw
		stosw
		stosw
		add	di,bx
		dec	bp
		jnz	.w5_pair
.skip:		pop	cx
		dec	cx
		jnz	.rect
		pop	ds
		ret
.widths:	dw	.w1, .w2, .w3, .w4, .w5

rect_clear_front:
		call	rect_front_segment
		xor	di,di
		xor	ax,ax
		mov	cx,35840 / 2
		rep	stosw
		mov	word [r_cleared],1008	; (all cells, for the statistics)
		ret

; ES = the target front's segment (a front crosses 64 KiB from 0A000h).
rect_front_segment:
		push	ax
		mov	ax,[l_output_page]	; paragraphs
		add	ax,0a000h
		mov	es,ax
		pop	ax
		ret

; Draw the flagged pieces in order.
rect_draw_flagged:
		xor	cx,cx
.piece:		cmp	cx,[r_count]
		jae	.done
		push	cx
		mov	si,cx
		shl	si,4
		add	si,[r_list]
		mov	ax,3800h
		mov	es,ax
		cmp	byte [es:si + 14],0
		je	.next
		mov	ax,[es:si]		; key -> sprite, lookup, flips
		mov	bx,ax
		xor	bh,bh
		shl	bx,8
		mov	[n_sprite],bx
		mov	bl,ah
		and	bx,63
		shl	bx,2
		add	bx,N_SPRLOOKUP
		mov	[n_lookup],bx
		mov	bl,ah
		shr	bl,6
		mov	bh,bl
		and	bl,1
		mov	[n_fx],bl
		shr	bh,1
		mov	[n_fy],bh
		mov	ax,[es:si + 2]		; the clip, from the record
		mov	[n_xbase],ax
		add	ax,16
		mov	bx,[es:si + 6]
		sub	bx,ax
		mov	[n_left],bx
		mov	bx,[es:si + 8]
		sub	bx,ax
		mov	[n_right],bx
		mov	dx,[es:si + 4]
		mov	[n_ybase],dx
		mov	bp,[es:si + 10]
		sub	bp,dx
		mov	bx,[es:si + 12]
		sub	bx,dx
		mov	[n_bottom],bx
		mov	ax,[es:si]
		call	planes_sprite_keyed
.next:		pop	cx
		inc	cx
		jmp	.piece
.done:		ret

		align	2
r_counts	dw	0, 0, 0		; pieces in each front's list (FFFFh unknown)
r_lists		dw	RECT_LIST_A, RECT_LIST_B, RECT_LIST_C
r_front		dw	0
r_list		dw	0
r_old		dw	0
r_count		dw	0
r_cleared	dw	0
r_new_key	dw	0
r_tested_end	dw	0
r_key_high	db	0
r_overflow	db	0
r_boxed		db	0
r_mode		db	0
