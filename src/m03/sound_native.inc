; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; The native sound driver (sound_driver.inc) in the game, instead of the
; sound program (docs/SOUND-DRIVER.md). The program's start-up handshake
; is done in the scheduler's frame work (sound_start_step, interrupts off);
; its ticks, two a VRTC as the board's 120 Hz NMI, and the conversion to
; the OPN (m03_sound_update) in the VRTC handler (sound_vrtc), so that the
; tempo follows real time however late the game runs. While the sound NMI
; latch (6822h bit 0) is set there are no ticks. The F10 screen, while
; open, stops the ticks unless its sound test plays. Every other OPN
; access runs with interrupts off (new_frame, service.inc).

SD_OFF		equ	0		; sub and sound held in reset
SD_WAIT		equ	1		; FFh written to 8A01h, main to clear it
SD_RUN		equ	2

; Sub and sound out of reset (6823h bit 0 set); DS = CS.
sound_start_step:
		cmp	byte [sd_state],SD_RUN
		je	.ret
		push	ds
		push	es
		mov	ax,ZSEG
		mov	ds,ax
		cmp	byte [cs:sd_state],SD_OFF
		jne	.wait
		mov	byte [6822h],1		; as the program: its NMI off, then
		mov	byte [8a01h],0ffh	; its checksum passed
		mov	byte [cs:sd_state],SD_WAIT
		jmp	.done
.wait:		cmp	byte [8a01h],0		; main has seen it
		jne	.done
		mov	ax,SSEG
		mov	es,ax
		call	sd_reset
		mov	byte [6822h],0		; NMI on
		mov	byte [cs:sd_state],SD_RUN
.done:		pop	es
		pop	ds
.ret:		ret

; VRTC handler: two ticks and the OPN update.
sound_vrtc:
		cmp	byte [cs:sd_state],SD_RUN
		jne	.ret
%ifdef SERVICE_MENU
		cmp	byte [cs:svc_on],0
		je	.run
		cmp	byte [cs:svc_test_on],0
		je	.ret
.run:
%endif
		pusha
		push	ds
		push	es
		cld
		mov	ax,ZSEG
		mov	ds,ax
		mov	ax,SSEG
		mov	es,ax
		test	byte [6822h],1		; NMI disabled
		jnz	.update
		call	sd_tick
		call	sd_tick
		add	word [cs:m03_nmi_delivered],2
.update:	pop	es
		pop	ds
		popa
		call	m03_sound_update
.ret:		ret

sd_state	db	SD_OFF
