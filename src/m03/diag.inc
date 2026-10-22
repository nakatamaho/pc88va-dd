; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Load display (F9, as in the sister ports), in G1's margins (above and
; below the game in its orientation), read upwards like the game's own
; text. Left: five values over the last 60 VRTCs, each after its letter:
; F game frames (60 at full speed), D VRTCs dropped (frames skipped: more
; than FRAME_DEBT behind), R new pictures (60: every frame), T sound ticks
; (120), I idle time in percent of the elapsed VRTCs, from the idle loop's
; count of an empty frame measured at start (idle_calib), so right on a VA
; and a VA2. Right, in hex: K the keys read (K_* bits), M the 51xx's mode
; (high digit) and remap flag (low), S the sound (bit 0 stopped after the
; sound chip timed out, bit 1 FM voices loaded, bit 2 FM in use). G1 is
; not paged: the margins are drawn once a second, by the render
; (interrupts on), and cleared when the display is turned off. Nothing
; else draws there.

DIAG_COLOUR	equ	2		; G1 palette entry 2: near white
DIAG_VALUES	equ	5
DIAG_RIGHT	equ	152		; the right margin's first byte (dot 304)

; In service_frame (DS = ES = CS, interrupts disabled): the window.
diag_tick:	mov	ax,[tick]
		sub	ax,[diag_tick0]
		cmp	ax,60
		jb	.r
		add	[diag_tick0],ax
		mov	cx,ax			; CX: VRTCs in the window
		mov	ax,[frames]
		mov	dx,ax
		sub	ax,[diag_frames0]
		mov	[diag_frames0],dx
		mov	[diag_values],ax
		xor	ax,ax
		xchg	ax,[diag_dropped]
		mov	[diag_values + 2],ax
		xor	ax,ax
		xchg	ax,[diag_pages]
		mov	[diag_values + 4],ax
		xor	ax,ax
%ifdef M03_AUDIO
		mov	ax,[m03_nmi_delivered]
		mov	dx,ax
		sub	ax,[diag_sound0]
		mov	[diag_sound0],dx
%endif
		mov	[diag_values + 6],ax
		mov	ax,[idle_calib]		; an empty window: idle_calib x CX
		mul	cx			; passes; percent = passes / (that
		mov	bx,100			; / 100)
		div	bx
		mov	bx,ax
		mov	ax,999
		or	bx,bx
		jz	.idle
		mov	ax,[diag_idle]
		mov	dx,[diag_idle + 2]
		cmp	dx,bx
		jae	.full
		div	bx
		jmp	.idle
.full:		mov	ax,999
.idle:		mov	[diag_values + 8],ax
		xor	ax,ax
		mov	[diag_idle],ax
		mov	[diag_idle + 2],ax
		mov	byte [diag_dirty],1
.r:		ret

; F9 just pressed (from service_frame).
diag_toggle:	xor	byte [diag_on],1
		mov	byte [diag_clear],1
		mov	byte [diag_dirty],1
		ret

; At the start of live_video_frame (interrupts on).
diag_draw:	cmp	byte [cs:diag_on],0
		jne	.on
		cmp	byte [cs:diag_clear],0
		je	.r
		mov	byte [cs:diag_clear],0
		push	ax
		push	cx
		push	di
		push	es
		mov	ax,0c000h		; G1: dots 0-15 and 304-319
		mov	es,ax
		xor	di,di
		mov	cx,224
		xor	ax,ax
.clear:		stosw
		stosw
		stosw
		stosw
		add	di,DIAG_RIGHT - 8
		stosw
		stosw
		stosw
		stosw
		loop	.clear
		pop	es
		pop	di
		pop	cx
		pop	ax
.r:		ret
.on:		cmp	byte [cs:diag_dirty],0
		je	.r
		mov	byte [cs:diag_dirty],0
		pusha
		push	ds
		push	es
		push	cs
		pop	ds
		mov	word [diag_col],DIAG_RIGHT	; the hex values
		mov	al,'K'
		mov	dx,4
		call	diag_glyph
		mov	al,[keys]
		mov	dx,3
		call	diag_hex
		mov	al,'M'
		mov	dx,9
		call	diag_glyph
		mov	al,[m51_mode]
		shl	al,4
		or	al,[m51_remap]
		mov	dx,8
		call	diag_hex
		mov	al,'S'
		mov	dx,14
		call	diag_glyph
		xor	al,al
%ifdef M03_AUDIO
		mov	al,[m03_error]
		and	al,1
%ifdef M03_FM
		mov	ah,[m03_fm_ready]
		shl	ah,1
		or	al,ah
		mov	ah,[m03_use_fm]
		shl	ah,2
		or	al,ah
%endif
%endif
		mov	dx,13
		call	diag_hex
		mov	word [diag_col],0	; the numbers
		xor	si,si
.value:		mov	dx,si			; the value's letter at cell row
		shr	dx,1			; 4 + 5 i, its digits above it
		imul	dx,dx,5
		add	dx,4
		push	dx
		mov	bx,si
		shr	bx,1
		mov	al,[diag_letters + bx]
		call	diag_glyph
		pop	dx
		dec	dx
		mov	ax,[diag_values + si]
		cmp	ax,999
		jbe	.digits
		mov	ax,999
.digits:	mov	bl,10			; units first
		div	bl
		mov	[diag_digits],ah
		xor	ah,ah
		div	bl
		mov	[diag_digits + 1],ah
		mov	[diag_digits + 2],al
		mov	bx,2
.digit:		mov	al,[diag_digits + bx]	; hundreds at the bottom
		add	al,'0'
		push	bx
		push	dx
		call	diag_glyph
		pop	dx
		pop	bx
		dec	dx
		dec	bx
		jns	.digit
		add	si,2
		cmp	si,DIAG_VALUES * 2
		jb	.value
		pop	es
		pop	ds
		popa
		ret

; Byte AL as two hex digits, the high one at cell row DX, the low one
; above it (upwards).
diag_hex:	push	ax
		shr	al,4
		call	.char
		push	dx
		call	diag_glyph
		pop	dx
		dec	dx
		pop	ax
		and	al,0fh
		call	.char
		jmp	diag_glyph
.char:		add	al,'0'
		cmp	al,'9'
		jbe	.c
		add	al,'A' - '9' - 1
.c:		ret

; ASCII digit or capital AL at cell row DX of a margin, from byte diag_col
; of the line: the font's 0-9 are tile codes 10h-19h, A-Z 1Ah-33h; their
; pens at 3000:code x 64, nonzero in DIAG_COLOUR.
diag_glyph:	sub	al,'0' - 10h
		cmp	al,1ah
		jb	.code
		sub	al,'A' - '9' - 1
.code:		push	si
		push	ds
		mov	bx,0c000h
		mov	es,bx
		imul	di,dx,8 * 160
		add	di,[cs:diag_col]
		xor	ah,ah
		shl	ax,6
		mov	si,ax
		mov	bx,3000h
		mov	ds,bx
		mov	ch,8
.row:		mov	cl,4
.pair:		xor	ah,ah
		lodsb
		or	al,al
		jz	.second
		mov	ah,DIAG_COLOUR << 4
.second:	lodsb
		or	al,al
		jz	.store
		or	ah,DIAG_COLOUR
.store:		mov	al,ah
		stosb
		dec	cl
		jnz	.pair
		add	di,160 - 4
		dec	ch
		jnz	.row
		pop	ds
		pop	si
		ret

		align	2
diag_values	dw	0, 0, 0, 0, 0
diag_dropped	dw	0		; VRTCs dropped in the window (g_sched)
diag_idle	dw	0, 0		; idle loop passes in the window
diag_tick0	dw	0
diag_frames0	dw	0
diag_sound0	dw	0
diag_pages	dw	0		; new pictures in the window
diag_col	dw	0
diag_digits	db	0, 0, 0
diag_letters	db	'FDRTI'
diag_on:
%ifdef DIAG
		db	1		; (tests: on from the start)
%else
		db	0
%endif
diag_clear	db	0
diag_dirty	db	0
