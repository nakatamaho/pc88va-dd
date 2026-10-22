; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Native sound driver (docs/SOUND-DRIVER.md): does what the sound program's
; NMI does, in V30 code, instead of running the program. Its state stays at
; the program's addresses in the Z80 segment (9A80h-9B3Ch, which main and
; sub read and write), its tables are read from the program's image in its
; segment, and it writes the sound registers 6800h-681Fh as the program,
; which m03_sound_update then converts. Model: tools/sound_driver.py.
;
; sd_tick: one tick (the program ticks at 120 Hz). DS = Z80 segment, ES =
; the sound program's segment; every general register is changed.

SD_REQ		equ	9a80h		; request a sound
SD_ACTIVE	equ	9a96h		; a sound plays
SD_DURATION	equ	9aach		; per track: ticks into the note
SD_POSITION	equ	9adbh		; per track: offset of the note
SD_TEMPO	equ	9b0ah		; per sound: ticks per length unit
SD_SHADOW	equ	9b20h		; image of 6810h-681Fh, waveforms 9B30h-9B32h
SD_COINS	equ	9b33h		; added to sound 00h's counter (main)
SD_CURRENT	equ	9b34h
SD_TRACK	equ	9b35h
SD_COUNT	equ	9b36h
SD_VOICE	equ	9b37h
SD_ENDED	equ	9b38h
SD_NOTE		equ	9b39h		; word: the note's address
SD_DELAY	equ	9b3bh
SD_BUSY		equ	9b3ch
ST_TRACKS	equ	0700h		; tables in the program
ST_SOUNDS	equ	0754h
ST_WAVE		equ	0793h
ST_PITCH_SET	equ	07bdh
ST_TEMPO	equ	07e7h
ST_ENVELOPE	equ	07fch		; its address, not its contents: see sd_step
ST_DECAY	equ	0826h
ST_END		equ	040dh
ST_PITCH0	equ	0631h
ST_PITCH1	equ	064bh
ST_PITCH2	equ	0665h

; State after the program's start-up, before its first tick.
sd_reset:
		xor	ax,ax
		push	es
		push	ds
		pop	es
		mov	di,8a40h
		mov	cx,4
		rep	stosw
		mov	di,SD_REQ
		mov	cx,80h
		rep	stosw
		pop	es
		mov	di,SD_TEMPO		; 21 tempo bytes from the program
		mov	si,ST_TEMPO
		mov	cx,21
.tempo:		mov	al,[es:si]
		mov	[di],al
		inc	si
		inc	di
		loop	.tempo
		ret

sd_tick:
%ifdef SOUND_LOG
		call	sd_log
%endif
		mov	byte [SD_BUSY],1
		push	es
		push	ds
		pop	es
		mov	di,SD_SHADOW
		xor	ax,ax
		mov	cx,8
		rep	stosw
		test	byte [8657h],2		; attract mode
		jz	.play
		test	byte [87cfh],10h	; and no sound in attract mode
		jz	.attract
		mov	di,SD_REQ
		mov	cx,14h
		rep	stosw
		pop	es
		jmp	sd_output
.attract:	mov	di,SD_REQ
		mov	cx,5
		rep	stosw
		mov	di,SD_ACTIVE
		mov	cx,5
		rep	stosw
		mov	[9a8eh],al
		mov	[9aa4h],al
		mov	di,9a90h
		stosw
		stosb
		mov	di,9aa6h
		stosw
		stosb
		mov	[9a94h],al
		mov	[9aaah],al
		pop	es
		jmp	.second
.play:		pop	es
		mov	al,[SD_COINS]
		or	al,al
		jz	.first
		add	[SD_REQ],al
		mov	byte [SD_COINS],0
.first:		xor	bx,bx
		mov	si,sd_first
.find:		mov	bl,[cs:si]
		inc	si
		cmp	byte [SD_REQ + bx],0
		jne	.found
		cmp	si,sd_first + 8
		jb	.find
		cmp	byte [SD_REQ + 11h],0
		je	.delay
		mov	al,11h
		call	sd_play
		mov	byte [SD_DELAY],50h
		jmp	.second
.delay:		dec	byte [SD_DELAY]
		jnz	.second
		mov	byte [SD_DELAY],1
		cmp	byte [SD_REQ + 12h],0
		je	.second
		mov	al,12h
		call	sd_play
		jmp	.second
.found:		mov	al,bl
		call	sd_play
		jmp	sd_sound0
.second:	mov	al,0fh			; triggered: 0Fh, else 10h
		call	sd_triggered
		jc	.s0a
		mov	al,10h
		call	sd_triggered
.s0a:		mov	al,0ah			; 0Ah, else the first of 0Bh-0Dh
		call	sd_triggered
		jc	.s0e
		mov	al,0bh
.s0b:		xor	bx,bx
		mov	bl,al
		cmp	byte [SD_REQ + bx],0
		je	.s0b_next
		call	sd_play
		jmp	.s0e
.s0b_next:	inc	al
		cmp	al,0eh
		jb	.s0b
.s0e:		mov	al,0eh
		call	sd_triggered
		cmp	byte [SD_REQ + 09h],0	; 09h, while 8646h bit 0 is clear
		je	.s06
		test	byte [8646h],1
		jz	.play09
		mov	byte [SD_REQ + 09h],0
		mov	byte [SD_ACTIVE + 09h],0
		jmp	.s06
.play09:	mov	al,09h
		call	sd_play
		jmp	.s13
.s06:		cmp	byte [SD_REQ + 06h],0	; 06h, while 8646h bit 0 and 8401h
		je	.s13			; bit 7 are clear
		test	byte [8646h],1
		jnz	.clear06
		test	byte [8401h],80h
		jnz	.clear06
		mov	al,06h
		call	sd_play
		jmp	.s13
.clear06:	mov	byte [SD_REQ + 06h],0
		mov	byte [SD_ACTIVE + 06h],0
.s13:		cmp	byte [SD_REQ + 13h],0	; 13h, in attract mode or while
		je	sd_sound0		; 8401h bit 5 is set
		test	byte [8657h],2
		jnz	.play13
		test	byte [8401h],20h
		jnz	.play13
		mov	byte [SD_REQ + 13h],0
		mov	byte [SD_ACTIVE + 13h],0
		jmp	sd_sound0
.play13:	mov	al,13h
		call	sd_play
sd_sound0:	cmp	byte [SD_REQ],0
		je	sd_output
		xor	al,al
		call	sd_play
sd_output:	push	es			; the registers, as the program
		push	ds
		pop	es
		mov	si,SD_SHADOW
		mov	di,6810h
		mov	cx,8
		rep	movsw
		mov	al,[9b30h]
		mov	[6805h],al
		mov	al,[9b31h]
		mov	[680ah],al
		mov	al,[9b32h]
		mov	[680fh],al
		mov	byte [SD_BUSY],0
		pop	es
		ret

%ifdef SOUND_LOG
; Test only: 48-byte records in a ring of 1024 at GVRAM 13000h: scheduler
; frame, VRTC count, requests 9A80h-9A94h, marks 9A96h-9AAAh, 8401h,
; 8646h, 8657h, then 1 if main was interrupted (not yielded).
sd_log:		pusha
		push	es
		mov	ax,0b300h
		mov	es,ax
		mov	di,[cs:sd_log_at]
		mov	ax,[cs:frames]
		stosw
		mov	ax,[cs:tick]
		stosw
		mov	si,SD_REQ
		mov	cx,15h
		rep	movsb
		mov	si,SD_ACTIVE
		mov	cx,15h
		rep	movsb
		mov	al,[8401h]
		stosb
		mov	al,[8646h]
		stosb
		mov	al,[8657h]
		stosb
		mov	al,[cs:cur]
		stosb
		add	word [cs:sd_log_at],48
		cmp	word [cs:sd_log_at],48 * 1024
		jb	.r
		mov	word [cs:sd_log_at],0
.r:		pop	es
		popa
		ret
sd_log_at	dw	0
%endif

; Request-driven sounds checked first, in this order (0117h).
sd_first	db	01h, 08h, 02h, 03h, 14h, 07h, 04h, 05h

; Triggered sound AL: (re)start if requested, else go on if it plays;
; CF = 1 if either.
sd_triggered:	mov	[SD_CURRENT],al
		xor	bx,bx
		mov	bl,al
		cmp	byte [SD_REQ + bx],0
		je	.playing
		mov	byte [SD_REQ + bx],0
		inc	byte [SD_ACTIVE + bx]	; restart
		call	sd_load
		call	sd_reset_tracks
		call	sd_finish
		stc
		ret
.playing:	cmp	byte [SD_ACTIVE + bx],0
		je	.none
		call	sd_load
		call	sd_finish
		stc
		ret
.none:		clc
		ret

; Step the current triggered sound; at its end clear its mark and run its
; end routine.
sd_finish:	call	sd_tracks
		jnc	.ret
		xor	bx,bx
		mov	bl,[SD_CURRENT]
		mov	byte [SD_ACTIVE + bx],0
		jmp	sd_end
.ret:		ret

; Request-driven sound AL (0391h).
sd_play:	mov	[SD_CURRENT],al
		call	sd_load
		xor	bx,bx
		mov	bl,al
		cmp	byte [SD_ACTIVE + bx],0
		jne	.step
		inc	byte [SD_ACTIVE + bx]
		call	sd_reset_tracks
.step:		call	sd_tracks
		jnc	.ret
		xor	bx,bx
		mov	bl,[SD_CURRENT]
		mov	byte [SD_ACTIVE + bx],0
		or	bl,bl			; counters: one play less
		jz	.count
		cmp	bl,14h
		je	.count
		mov	byte [SD_REQ + bx],0
		jmp	sd_end
.count:		dec	byte [SD_REQ + bx]
.ret:		ret

; Track, count and voice of sound AL (kept).
sd_load:	xor	bx,bx
		mov	bl,al
		imul	bx,bx,3
		mov	dx,[es:ST_SOUNDS + bx]
		mov	[SD_TRACK],dx
		mov	dl,[es:ST_SOUNDS + bx + 2]
		mov	[SD_VOICE],dl
		ret

sd_reset_tracks:
		push	ax
		push	es
		push	ds
		pop	es
		xor	cx,cx
		mov	cl,[SD_COUNT]
		xor	bx,bx
		mov	bl,[SD_TRACK]
		xor	al,al
		lea	di,[SD_POSITION + bx]
		push	cx
		rep	stosb
		pop	cx
		lea	di,[SD_DURATION + bx]
		rep	stosb
		pop	es
		pop	ax
		ret

; Step every track of the current sound; CF = 1 if one ended.
sd_tracks:	call	sd_step
		dec	byte [SD_COUNT]
		jz	.done
		inc	byte [SD_TRACK]
		inc	byte [SD_VOICE]
		jmp	sd_tracks
.done:		cmp	byte [SD_ENDED],0
		je	.none
		mov	byte [SD_ENDED],0
		stc
		ret
.none:		clc
		ret

; One track on its voice (04D5h).
sd_step:	xor	bx,bx
		mov	bl,[SD_TRACK]
		inc	byte [SD_DURATION + bx]
		mov	si,bx
		shl	si,1
		mov	si,[es:ST_TRACKS + si]
		xor	ax,ax
		mov	al,[SD_POSITION + bx]
		add	si,ax
		mov	[SD_NOTE],si
		xor	di,di			; DI: voice 0, 1, 2+ -> 0, 5, 10
		mov	al,[SD_VOICE]
		or	al,al
		jz	.voice
		mov	di,5
		dec	al
		jz	.voice
		mov	di,10
.voice:		mov	al,[es:si]		; AL: the note
		cmp	al,0ffh
		jne	.note
		mov	byte [SD_SHADOW + 5 + di],0	; end mark: voice off
		mov	byte [SD_ENDED],1
		ret
.note:		mov	dx,ST_PITCH0		; pitch set of the track
		mov	ah,[es:ST_PITCH_SET + bx]
		or	ah,ah
		jz	.set
		mov	dx,ST_PITCH1
		dec	ah
		jz	.set
		mov	dx,ST_PITCH2
.set:		push	bx
		xor	bx,bx
		mov	bl,al
		shr	bl,4
		shl	bx,1
		add	bx,dx
		mov	dx,[es:bx]
		mov	cl,al
		and	cl,15
		shr	dx,cl			; octaves down
		pop	bx
		mov	ah,dl			; frequency nibbles 1-4
		rol	ah,4
		mov	[SD_SHADOW + 1 + di],dl
		mov	[SD_SHADOW + 2 + di],ah
		mov	ah,dh
		rol	ah,4
		mov	[SD_SHADOW + 3 + di],dh
		mov	[SD_SHADOW + 4 + di],ah
		mov	ah,[SD_DURATION + bx]	; AH: ticks into the note
		cmp	al,0c0h			; rest
		je	.silent
		; The program means to choose the envelope from a per-track table
		; but tests the low byte of the entry's address: track 4 decays,
		; track 5 rises, every other starts at 15 - ticks.
		cmp	bl,4
		je	.decay
		cmp	ah,6
		jae	.decay
		mov	al,ah
		cmp	bl,5
		jne	.cpl
		add	al,al			; rise: 2 x ticks
		jmp	.volume
.cpl:		not	al			; 15 - ticks in the low nibble
		jmp	.volume
.decay:		mov	dl,[es:ST_DECAY + bx]	; 10 until the hold time, then down
		or	dl,dl			; over 10 ticks (none: 10)
		jz	.ten
		mov	al,ah
		sub	al,dl
		jb	.ten
		sub	al,10
		jae	.silent
		neg	al
		jmp	.volume
.ten:		mov	al,10
		jmp	.volume
.silent:	xor	al,al
.volume:	mov	[SD_SHADOW + 5 + di],al
		mov	al,[es:ST_WAVE + bx]	; waveform
		xor	dx,dx
		mov	dl,[SD_VOICE]
		mov	di,dx
		mov	[9b30h + di],al
		xor	dx,dx			; length: tempo x units, 8 bits
		mov	dl,[SD_CURRENT]
		mov	di,dx
		mov	al,[SD_TEMPO + di]
		mul	byte [es:si + 1]
		cmp	al,[SD_DURATION + bx]
		jne	.ret
		add	byte [SD_POSITION + bx],2	; next note
		mov	byte [SD_DURATION + bx],0
.ret:		ret

; End routine of the current sound (word table 040Dh), by its address.
sd_end:		xor	bx,bx
		mov	bl,[SD_CURRENT]
		shl	bx,1
		mov	ax,[es:ST_END + bx]
		mov	si,sd_ends
.find:		cmp	si,sd_ends_end
		jae	.ret
		cmp	ax,[cs:si]
		je	.found
		add	si,4
		jmp	.find
.found:		xor	ax,ax
		jmp	[cs:si + 2]
.ret:		ret

sd_ends		dw	0437h, sd_end_none
		dw	0438h, sd_end_0438
		dw	0440h, sd_end_0440
		dw	0448h, sd_end_0448
		dw	045fh, sd_end_045f
		dw	0463h, sd_end_0463
		dw	046eh, sd_end_046e
		dw	0490h, sd_end_0490
		dw	04abh, sd_end_04ab
		dw	04c6h, sd_end_04c6
sd_ends_end:

sd_end_none:	ret
sd_end_0438:	mov	[9a94h],al
		mov	[9aaah],al
		ret
sd_end_0440:	mov	[9a8dh],al
		mov	[9aa3h],al
		ret
sd_end_0448:	mov	[9a86h],al
		mov	[9a89h],al
		mov	[9a9ch],al
		mov	[9a9fh],al
		mov	[9a93h],al
		mov	[9aa9h],al
		mov	al,10h
		jmp	sd_end_tempo
sd_end_045f:	mov	al,0ah
		jmp	sd_end_tempo
sd_end_0463:	mov	al,0ch
sd_end_tempo:	mov	[SD_TEMPO + 11h],al
		xor	al,al
		mov	[9aa7h],al
		mov	cx,9
		jmp	sd_end_clear
sd_end_04c6:	mov	[9a86h],al
		mov	[9a89h],al
		mov	[9a9ch],al
		mov	[9a9fh],al
sd_end_046e:	mov	[9a93h],al
		mov	[9aa9h],al
		mov	cx,9
		jmp	sd_end_clear
sd_end_0490:	mov	cx,4
		jmp	sd_end_clear
sd_end_04ab:	mov	cx,7
; Clear CX requests from 0Ah and the same marks.
sd_end_clear:	push	es
		push	ds
		pop	es
		xor	al,al
		mov	di,9a8ah
		push	cx
		rep	stosb
		pop	cx
		mov	di,9aa0h
		rep	stosb
		pop	es
		ret
