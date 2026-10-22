; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
;
; DD.COM: MS-DOS loader of the game (docs/DIST.md).
;
;   DD [directory]
;
; Holds the game's native code and no data from the arcade ROMs. It reads
; DDGAME.DAT, which install_roms.py builds on a PC from the user's ROM
; files (the patched programs, then the staged area: header, tables and
; graphics), and the optional FMVOICE.DAT, from the directory (by default
; the current one), puts everything where the self-booting disk's IPL
; puts it, and starts the game, which never returns (ESC restarts the
; machine). The game checks the data (CRC-32) itself.
;
; Memory, as after the IPL: code 2000:0000-5FFF, programs 2000:6000,
; staged area 7000:0000 with FMVOICE.DAT at 7000:FC00. MS-DOS 4.0 loads
; this program at 1DDBh on the PC-88VA: the loader part must end below
; 2000h, and DOS must leave memory up to 8000h (the standard 512 KiB).
;
; game.inc (tools/build_dist.py): GAME_BIN, CODE_BYTES, PROGRAM_BYTES,
; FM_SLOT.

		cpu	186
		org	100h

%include "game.inc"

GAME_SEG	equ	2000h
STAGE_SEG	equ	7000h
MEMORY_TOP	equ	8000h

start:		mov	sp,stack_top
		cld
		mov	dx,s_banner
		call	print
		mov	dx,01cbh		; 15 kHz only: port 1CBh bit 3 is 1
		in	al,dx			; at 24.8 kHz
		test	al,08h
		jz	.khz15
		mov	dx,s_24khz
		jmp	fail
.khz15:		mov	ax,loader_end		; the loader must end below 2000h
		add	ax,15
		shr	ax,4
		mov	bx,cs
		add	ax,bx
		cmp	ax,GAME_SEG
		ja	.memory
		cmp	word [0002h],MEMORY_TOP	; and DOS leave memory to 8000h
		jae	.room
.memory:	mov	dx,s_memory
		jmp	fail
.room:		call	parse
		mov	si,n_game
		call	open
		jnc	.game
		mov	dx,s_missing
		jmp	fail
.game:		push	ds			; the programs at 2000:6000
		mov	cx,GAME_SEG
		mov	ds,cx
		mov	dx,CODE_BYTES
		mov	cx,PROGRAM_BYTES
		mov	ah,3fh
		int	21h
		pop	ds
		jc	.bad
		cmp	ax,PROGRAM_BYTES
		jne	.bad
		push	ds			; the staged area at 7000:0000
		mov	cx,STAGE_SEG
		mov	ds,cx
		xor	dx,dx
		mov	cx,FM_SLOT
		mov	ah,3fh
		int	21h
		pop	ds
		jc	.bad
		cmp	ax,32			; at least its header (checked later)
		jb	.bad
		call	close
		push	es			; no FMVOICE.DAT unless one is read
		mov	ax,STAGE_SEG
		mov	es,ax
		mov	di,FM_SLOT
		mov	cx,(10000h - FM_SLOT) / 2
		xor	ax,ax
		rep	stosw
		pop	es
		mov	si,n_voices
		call	open
		jc	.code
		push	ds
		mov	cx,STAGE_SEG
		mov	ds,cx
		mov	dx,FM_SLOT
		mov	cx,10000h - FM_SLOT
		mov	ah,3fh
		int	21h
		pop	ds
		call	close
.code:		mov	si,game_code		; the game's code to 2000:0000; the
		mov	ax,GAME_SEG		; copy here may overlap it, so copy
		mov	es,ax			; backwards when it starts below
		xor	di,di
		mov	cx,CODE_BYTES
		mov	ax,cs
		add	ax,(game_code - $$ + 100h) / 16
		cmp	ax,GAME_SEG
		jae	.forward
		add	si,CODE_BYTES - 1
		mov	di,CODE_BYTES - 1
		std
.forward:	rep	movsb
		cld
		cli
		jmp	GAME_SEG:0000h
.bad:		mov	dx,s_damaged
		jmp	fail

; The optional directory in the command tail, as a prefix of the names.
parse:		mov	si,81h
		mov	di,path
.skip:		lodsb
		cmp	al,' '
		je	.skip
		cmp	al,9
		je	.skip
.copy:		cmp	al,' '
		jbe	.end
		cmp	di,path + 64
		jae	.end
		stosb
		lodsb
		jmp	.copy
.end:		cmp	di,path
		je	.done
		mov	al,[di - 1]
		cmp	al,'\'
		je	.done
		cmp	al,':'
		je	.done
		mov	al,'\'
		stosb
.done:		mov	[path_end],di
		ret

; Open file SI (name) in the directory: CF = 1 if not found; BX = handle.
open:		mov	di,[path_end]
.name:		lodsb
		stosb
		or	al,al
		jnz	.name
		mov	dx,path
		mov	ax,3d00h
		int	21h
		mov	bx,ax
		ret

close:		mov	ah,3eh
		int	21h
		ret

print:		mov	ah,09h
		int	21h
		ret

fail:		call	print
		mov	ax,4c01h
		int	21h

s_banner	db	'The Game DD (dd-pc88va)', 13, 10, '$'
s_24khz		db	'Start the machine in 15 kHz mode (CRT DIP switch SW1 off).', 13, 10, '$'
s_memory	db	'Not enough memory: DD needs DOS to load it below segment 2000h', 13, 10
		db	'and to leave memory up to 8000h (512 KB).', 13, 10, '$'
s_missing	db	'DDGAME.DAT not found: add the game data with install_roms.py', 13, 10
		db	'on a PC (see DD.TXT), or give its directory: DD directory', 13, 10, '$'
s_damaged	db	'DDGAME.DAT is damaged: install it again with install_roms.py.', 13, 10, '$'
n_game		db	'DDGAME.DAT', 0
n_voices	db	'FMVOICE.DAT', 0
path_end	dw	path
path		times	64 + 16 db 0
		times	128 db 0
stack_top:
loader_end:

		align	16
game_code:	incbin	GAME_BIN
