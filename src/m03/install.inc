; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Start-up checks of the installed data (tools/ddpayload.py, install_roms.py).
;
; The IPL loads the patched programs after the code (CS:ZIMG) and the staged
; area to 7000:0000: a header, the tables, the RLE pens and, at FM_SLOT, an
; optional FMVOICE.DAT. Both are built on a PC from the user's ROM files;
; the boot disk itself holds none. Here they are only checked (CRC-32) and
; used: no FM fitting or other ROM processing happens on this machine.

CRC_SEG		equ	3b00h		; 1 KiB table, free until rendering starts
STAGE_SEG	equ	7000h

; CF = 1 when the staged area or the programs are missing or damaged.
; DS = ES = CS.
install_check:
		push	es
		call	crc_table
		mov	ax,STAGE_SEG
		mov	es,ax
		cmp	word [es:0],'DD'
		jne	.bad
		cmp	word [es:2],'GA'
		jne	.bad
		cmp	word [es:4],1		; version
		jne	.bad
		cmp	word [es:6],STAGE_HEADER
		jne	.bad
		cmp	word [es:8],L_TABLE_BYTES
		jne	.bad
		mov	cx,[es:10h]		; end
		cmp	cx,FM_SLOT
		ja	.bad
		cmp	cx,STAGE_HEADER + L_TABLE_BYTES
		jbe	.bad
		sub	cx,STAGE_HEADER
		push	ds
		mov	ax,STAGE_SEG
		mov	ds,ax
		mov	si,STAGE_HEADER
		call	crc32
		pop	ds
		cmp	ax,[es:14h]
		jne	.bad
		cmp	dx,[es:16h]
		jne	.bad
		mov	si,ZIMG			; the programs, still in place
		mov	cx,PROGRAM_BYTES
		call	crc32
		cmp	ax,[es:18h]
		jne	.bad
		cmp	dx,[es:1ah]
		jne	.bad
		mov	al,[es:12h]		; revision, for the start message
		add	al,'0'
		mov	[s_revision],al
		pop	es
		clc
		ret
.bad:		pop	es
		stc
		ret

%ifdef M03_FM
; FMVOICE.DAT in the staged area (DS = 7000h, ES = CS): when it checks,
; copy its voices to N_FM_VOICES and allow FM in the service screen;
; with fitted voices (method 2) the game starts with FM, else with SSG.
install_fm:
		cmp	word [FM_SLOT],'DD'
		jne	.none
		cmp	word [FM_SLOT + 2],'FM'
		jne	.none
		cmp	word [FM_SLOT + 4],1	; version
		jne	.none
		mov	ax,[FM_SLOT + 6]	; method: 1 quick, 2 fit
		cmp	ax,1
		jb	.none
		cmp	ax,2
		ja	.none
		cmp	word [FM_SLOT + 8],15b4h	; the waveform PROM's CRC-32
		jne	.none
		cmp	word [FM_SLOT + 10],7a28h
		jne	.none
		cmp	word [FM_SLOT + 12],FM_BYTES
		jne	.none
		push	ax
		mov	si,FM_SLOT + 20
		mov	cx,FM_BYTES
		call	crc32
		cmp	ax,[FM_SLOT + 16]
		jne	.bad
		cmp	dx,[FM_SLOT + 18]
		jne	.bad
		pop	ax
		dec	al
		mov	[cs:m03_fm_fit],al
		or	al,al
		jz	.ready
		mov	byte [cs:m03_use_fm],1	; fitted voices: FM by default
.ready:		mov	byte [cs:m03_fm_ready],1
		mov	si,FM_SLOT + 20
		mov	di,N_FM_VOICES
		mov	cx,FM_BYTES
		rep	movsb
		ret
.bad:		pop	ax
.none:		mov	byte [cs:m03_fm_ready],0
		mov	byte [cs:m03_use_fm],0
		ret
%endif

; The CRC-32 table (reflected, polynomial EDB88320h) at CRC_SEG:0000.
crc_table:
		push	es
		push	di
		mov	ax,CRC_SEG
		mov	es,ax
		xor	di,di
		xor	bx,bx
.entry:		mov	ax,bx
		xor	dx,dx
		mov	cx,8
.bit:		shr	dx,1
		rcr	ax,1
		jnc	.next
		xor	ax,8320h
		xor	dx,0edb8h
.next:		loop	.bit
		mov	[es:di],ax
		mov	[es:di + 2],dx
		add	di,4
		inc	bx
		cmp	bx,256
		jb	.entry
		pop	di
		pop	es
		ret

; DX:AX = CRC-32 of CX (1..65535) bytes at DS:SI. Keeps ES.
crc32:
		push	es
		push	bx
		push	di
		mov	bx,CRC_SEG
		mov	es,bx
		mov	bx,0ffffh		; DX:BX: the running value
		mov	dx,bx
.byte:		lodsb
		xor	al,bl
		xor	ah,ah
		mov	di,ax
		shl	di,2
		mov	bl,bh
		mov	bh,dl
		mov	dl,dh
		xor	dh,dh
		xor	bx,[es:di]
		xor	dx,[es:di + 2]
		loop	.byte
		mov	ax,bx
		not	ax
		not	dx
		pop	di
		pop	bx
		pop	es
		ret

%ifdef DIST
; Found by install_roms.py in the code sectors.
dist_signature	db	'DD-PC88VA BOOT DISK 1', 0
%endif
s_not_installed	db	'The Game DD: the game data is not installed or is damaged.', 13, 10
		db	'Add it again with install_roms.py on a PC;', 13, 10
		db	'see DD.TXT.', 13, 10, 0
s_installed	db	'Programs revision '
s_revision	db	'?', '.', 13, 10, 0
