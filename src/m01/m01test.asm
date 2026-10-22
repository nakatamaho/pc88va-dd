; Copyright (c) 2026 Nakata Maho
;
; Redistribution and use in source and binary forms, with or without
; modification, are permitted provided that the following conditions
; are met:
; 1. Redistributions of source code must retain the above copyright
;    notice, this list of conditions and the following disclaimer.
; 2. Redistributions in binary form must reproduce the above copyright
;    notice, this list of conditions and the following disclaimer in the
;    documentation and/or other materials provided with the distribution.
;
; THIS SOFTWARE IS PROVIDED BY THE AUTHOR "AS IS" AND ANY EXPRESS OR
; IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
; OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
; IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
; INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
; BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
; USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
; ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
; (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
;
; M01TEST: feasibility tests for running the arcade game's three Z80
; programs, one at a time, in the uPD9002's Z80-compatible mode
; (docs/DESIGN.md).
;
; Loaded by src/boot/ipl.asm to 2000:0000. tools/build_m01.py appends the
; patched main segment image (main, relocated sub, stubs) and the sound
; segment image (tools/patches.py), and assembles this file with the
; generated patch.inc.
;
;   1  compatible-mode probes for the switching method
;   2  the game, keys: three programs, tile RAM as text, load statistics
;   3  the game with an automatic coin, start and moves
;
; Switching. A Z80 program is entered by IRET with a frame built from its
; saved context (PS, PC and a PSW with MD = 0); it leaves by CALLN (yield
; or a service) or by the VRTC interrupt (preemption), both of which push
; such a frame. The native code therefore always runs inside a native call
; made from compatible mode, where RETI may restore MD = 0 (BRKEM must not
; be nested). The first entry is a BRKEM to a stub that yields at once.

		cpu	186
		org	0

%include "patch.inc"

CODE_BYTES	equ	6000h
ZIMG		equ	CODE_BYTES		; main segment image in this segment
SIMG		equ	ZIMG + MAIN_SEGMENT_BYTES
ZSEG		equ	5000h			; main and sub programs, shared RAM
SSEG		equ	6000h			; sound program
SCHED_TOP	equ	0f800h			; native stack while Z80 code runs
NATIVE_TOP	equ	0f600h			; the scheduler's own stack
VRTC_VEC	equ	0ah
ICU0		equ	188h
ICU1		equ	18ah
VEC_PCALLN	equ	74h			; probe: CALLN target
VEC_PENTER	equ	75h			; probe: entry after BRKEM
PROBE_PC	equ	7000h			; Z80 address of the probe snippets
RETEM_PC	equ	7ff0h			; Z80 address of a RETEM
VIEW_FRAMES	equ	60
AUTO_COIN	equ	900			; automatic coin and start (frames)
AUTO_START	equ	1000
AUTO_MOVE	equ	1100
DSWA		equ	99h			; the game's default DIP switches
DSWB		equ	24h

; Saved Z80 context
C_AX		equ	0
C_BX		equ	2
C_CX		equ	4
C_DX		equ	6
C_SI		equ	8			; IX
C_DI		equ	10			; IY
C_BP		equ	12			; SP
C_DS		equ	14
C_IP		equ	16
C_CS		equ	18
C_PSW		equ	20
C_SIZE		equ	22

; Keys
K_UP		equ	01h
K_RIGHT		equ	02h
K_DOWN		equ	04h
K_LEFT		equ	08h
K_FIRE		equ	10h
K_COIN		equ	20h
K_START		equ	40h
K_ESC		equ	80h

%macro BRKEM 1
		db	0fh, 0ffh, %1
%endmacro

; Z80 JR cc,label in a snippet (position independent)
%macro ZJR 2
		db	%1, (%2 - ($ + 2)) & 0ffh
%endmacro

; Save the interrupted or calling Z80 program into [cur_ctx]; the frame
; (IP, CS, PSW) is on the stack and is removed.
%macro SAVE_CTX 0
		push	bx
		mov	bx,[cs:cur_ctx]
		mov	[cs:bx + C_AX],ax
		pop	ax
		mov	[cs:bx + C_BX],ax
		mov	[cs:bx + C_CX],cx
		mov	[cs:bx + C_DX],dx
		mov	[cs:bx + C_SI],si
		mov	[cs:bx + C_DI],di
		mov	[cs:bx + C_BP],bp
		mov	[cs:bx + C_DS],ds
		pop	ax
		mov	[cs:bx + C_IP],ax
		pop	ax
		mov	[cs:bx + C_CS],ax
		pop	ax
		mov	[cs:bx + C_PSW],ax
%endmacro

start:		cli
		mov	ax,cs
		mov	ds,ax
		mov	es,ax
		mov	ss,ax
		mov	sp,0fffeh
		cld
		call	install
		sti
%ifdef LIVE_VIDEO
%ifdef LIVE_AUTO
		jmp	game_auto
%else
		jmp	game
%endif
%elifdef AUTO_PROBES
		jmp	probes
%endif
%ifndef LIVE_VIDEO

menu:		mov	byte [vrtc_mode],0
		call	unmask
		call	text_init
		mov	si,s_title
		call	puts
		mov	si,s_menu
		call	puts
.key:		call	wait_key
		cmp	al,'1'
		je	probes
		cmp	al,'2'
		je	game
		cmp	al,'3'
		je	game_auto
		jmp	.key

%endif
; ---------------------------------------------------------------------------
; Interrupts and vectors

install:	xor	ax,ax
		mov	es,ax
		mov	ax,[es:VRTC_VEC * 4]
		mov	[old_vrtc],ax
		mov	ax,[es:VRTC_VEC * 4 + 2]
		mov	[old_vrtc + 2],ax
		mov	word [es:VRTC_VEC * 4],vrtc
		mov	[es:VRTC_VEC * 4 + 2],cs
		mov	bx,VEC_YIELD
		mov	ax,yield_h
		call	set_vec
		mov	bx,VEC_06XX_STEP
		mov	ax,io_step
		call	set_vec
		mov	bx,VEC_06XX_DONE
		mov	ax,io_done
		call	set_vec
		mov	bx,VEC_SPRITE_COPY
		mov	ax,sprite_copy_h
		call	set_vec
		mov	bx,VEC_SUB_POSITIONS
		mov	ax,sub_positions_h
		call	set_vec
		mov	bx,VEC_OBJECTS_A
		mov	ax,objects_a_h
		call	set_vec
		mov	bx,VEC_OBJECTS_B
		mov	ax,objects_b_h
		call	set_vec
		mov	bx,VEC_OBJECTS_C
		mov	ax,objects_c_h
		call	set_vec
		mov	bx,VEC_DIGITS
		mov	ax,digits_h
		call	set_vec
		mov	bx,VEC_TEXT10
		mov	ax,text10_h
		call	set_vec
		mov	bx,VEC_FILL12
		mov	ax,fill12_h
		call	set_vec
		mov	bx,VEC_NEAR
		mov	ax,near_h
		call	set_vec
		mov	bx,VEC_COPY3
		mov	ax,copy3_h
		call	set_vec
%ifndef LIVE_VIDEO
		mov	bx,VEC_PCALLN
		mov	ax,p_calln_h
		call	set_vec
		mov	bx,VEC_PENTER
		mov	ax,p_enter_h
		call	set_vec
%endif
		push	cs
		pop	es
		mov	dx,ICU1
		in	al,dx
		mov	[old_mask],al
		test	al,04h			; IR2 already enabled: the ROM
		jnz	.masked			; has a handler; chain to it
		mov	byte [chain],1
.masked:	and	al,0fbh
		mov	[old_mask_ir2],al
		out	dx,al
		ret

; Vector BX -> CS:AX (ES = 0)
set_vec:	shl	bx,2
		mov	[es:bx],ax
		mov	[es:bx + 2],cs
		ret

; Vector VEC_BRKEM -> ZSEG:AX
set_brkem:	push	es
		xor	bx,bx
		mov	es,bx
		mov	[es:VEC_BRKEM * 4],ax
		mov	word [es:VEC_BRKEM * 4 + 2],ZSEG
		pop	es
		ret

; While Z80 code runs only VRTC is enabled.
mask_others:	mov	al,0fbh
		mov	dx,ICU1
		out	dx,al
		ret

unmask:		mov	al,[cs:old_mask_ir2]
		mov	dx,ICU1
		out	dx,al
		ret

vrtc:		push	ax
		push	bx
		push	dx
		push	ds
		mov	bx,sp			; [bx+8] IP, [bx+10] CS, [bx+12] PSW
		inc	word [cs:tick]
%ifdef LIVE_VIDEO
		call	live_video_vrtc
%endif
%ifdef NATIVE_SOUND
		call	sound_vrtc
%endif
		mov	ax,[ss:bx + 10]
		cmp	ax,ZSEG
		je	.z80
		cmp	ax,SSEG
		je	.z80
		cmp	byte [cs:chain],0
		je	.eoi
		cmp	byte [cs:vrtc_mode],0
		jne	.eoi
		pop	ds
		pop	dx
		pop	bx
		pop	ax
		jmp	far [cs:old_vrtc]
.z80:		cmp	byte [cs:vrtc_mode],0
		je	.eoi
		mov	al,20h
		mov	dx,ICU0
		out	dx,al
		pop	ds
		pop	dx
		pop	bx
		pop	ax
		SAVE_CTX
		mov	sp,[cs:sched_sp]
		jmp	[cs:preempt_entry]
.eoi:		mov	al,20h
		mov	dx,ICU0
		out	dx,al
		pop	ds
		pop	dx
		pop	bx
		pop	ax
		iret

; CALLN VEC_YIELD
yield_h:	cli			; close native-entry IRQ window before fixed-stack work
		SAVE_CTX
		mov	sp,[cs:sched_sp]
		jmp	[cs:yield_entry]

; Enter the Z80 context at BX (interrupts disabled).
resume:		mov	[cs:cur_ctx],bx
		mov	sp,[cs:sched_sp]
		mov	ax,[cs:bx + C_PSW]
		and	ax,7fffh		; MD = 0: compatible mode
		push	ax
		push	word [cs:bx + C_CS]
		push	word [cs:bx + C_IP]
		mov	ax,[cs:bx + C_AX]
		mov	cx,[cs:bx + C_CX]
		mov	dx,[cs:bx + C_DX]
		mov	si,[cs:bx + C_SI]
		mov	di,[cs:bx + C_DI]
		mov	bp,[cs:bx + C_BP]
		mov	ds,[cs:bx + C_DS]
		mov	bx,[cs:bx + C_BX]
		iret

; Context at BX: start at AX in segment DX with PSW CX, registers 0.
ctx_init:	push	di
		push	es
		push	ax
		push	cs
		pop	es
		mov	di,bx
		xor	ax,ax
		push	cx
		mov	cx,C_SIZE / 2
		rep	stosw
		pop	cx
		pop	ax
		mov	[bx + C_IP],ax
		mov	[bx + C_CS],dx
		mov	[bx + C_DS],dx
		mov	[bx + C_PSW],cx
		pop	es
		pop	di
		ret

; ---------------------------------------------------------------------------
%ifndef LIVE_VIDEO			; M01 probes only (the live game has no room)
; Probes

; Run a probe: copy the snippet SI (CX bytes) to ZSEG:PROBE_PC, BRKEM to it
; with AX = probe scheduler, or 0 for a snippet that only ends in RETEM.
; Returns with the Z80 registers after RETEM: AL = A, CX = BC, DX = DE,
; BX = HL.
run_probe:	mov	[probe_sched],ax
		push	es
		mov	ax,ZSEG
		mov	es,ax
		mov	di,PROBE_PC
		rep	movsb
		mov	byte [es:RETEM_PC],0edh
		mov	byte [es:RETEM_PC + 1],0fdh
		pop	es
		mov	ax,PROBE_PC
		call	set_brkem
		cli
		call	mask_others
		mov	[brkem_sp],sp
		mov	ax,ZSEG
		mov	ds,ax
		xor	ax,ax
		xor	bx,bx
		xor	cx,cx
		xor	dx,dx
		BRKEM	VEC_BRKEM
		push	cs
		pop	ds
		push	ax
		push	dx
		call	unmask
		pop	dx
		pop	ax
		sti
		ret

; CALLN VEC_PENTER: the probe snippet hands over to its native scheduler.
p_enter_h:	add	sp,6
		mov	[cs:sched_sp],sp
		jmp	[cs:probe_sched]

; Leave the probe: IRET to a RETEM, which returns from run_probe's BRKEM.
p_finish:	cli
		mov	sp,[cs:brkem_sp]
		sub	sp,12
		mov	bx,sp
		mov	word [ss:bx],RETEM_PC
		mov	word [ss:bx + 2],ZSEG
		mov	word [ss:bx + 4],0002h
		mov	ax,ZSEG
		mov	ds,ax
		iret

; CALLN VEC_PCALLN: record the registers and the frame's PSW, change nothing.
p_calln_h:	push	bp
		mov	bp,sp
		mov	[cs:pc_ax],ax
		mov	[cs:pc_bx],bx
		mov	[cs:pc_cx],cx
		mov	[cs:pc_dx],dx
		mov	[cs:pc_si],si
		mov	[cs:pc_di],di
		mov	ax,[bp]
		mov	[cs:pc_bp],ax
		mov	ax,[bp + 6]
		mov	[cs:pc_psw],ax
		mov	ax,[cs:pc_ax]
		pop	bp
		iret

; Read a word of ZSEG (AX = address) -> AX
peek_z:		push	ds
		push	bx
		mov	bx,ax
		mov	ax,ZSEG
		mov	ds,ax
		mov	ax,[bx]
		pop	bx
		pop	ds
		ret

peek_s:		push	ds
		push	bx
		mov	bx,ax
		mov	ax,SSEG
		mov	ds,ax
		mov	ax,[bx]
		pop	bx
		pop	ds
		ret

; Copy CX bytes of snippet SI to segment AX at offset DI.
put_code:	push	es
		mov	es,ax
		rep	movsb
		pop	es
		ret

; Clear the probes' data in both segments (7F00h-7FEFh).
clear_data:	push	es
		push	di
		mov	ax,ZSEG
		call	.one
		mov	ax,SSEG
		call	.one
		pop	di
		pop	es
		ret
.one:		mov	es,ax
		mov	di,7f00h
		xor	ax,ax
		mov	cx,78h
		rep	stosw
		ret

%macro SNIPPET 1
		mov	si,%1
		mov	cx,%1_end - %1
%endmacro

probes:		call	text_init
		mov	si,s_probes
		call	puts
		call	clear_data

		; calln: registers and flags across CALLN and back
		mov	si,s_calln
		call	puts
		SNIPPET	z_calln
		xor	ax,ax
		call	run_probe
		mov	[r_cx],cx
		mov	[r_dx],dx
		mov	[r_bx],bx
		mov	ax,7f00h
		call	peek_z
		mov	[r_ax],ax
		mov	ax,7f02h
		call	peek_z
		mov	[r_ix],ax
		mov	ax,7f04h
		call	peek_z
		mov	[r_iy],ax
		mov	ax,7f06h
		call	peek_z
		mov	[r_sp],ax
		mov	cx,1
		cmp	byte [pc_ax],12h
		jne	.c_v
		cmp	word [pc_cx],3456h
		jne	.c_v
		cmp	word [pc_dx],789ah
		jne	.c_v
		cmp	word [pc_bx],0bcdeh
		jne	.c_v
		cmp	word [pc_si],1111h
		jne	.c_v
		cmp	word [pc_di],2222h
		jne	.c_v
		cmp	word [pc_bp],0fe00h
		jne	.c_v
		test	byte [pc_psw],01h	; CY
		jz	.c_v
		cmp	word [r_ax],0112h	; A after, carry after
		jne	.c_v
		cmp	word [r_cx],3456h
		jne	.c_v
		cmp	word [r_dx],789ah
		jne	.c_v
		cmp	word [r_bx],0bcdeh
		jne	.c_v
		cmp	word [r_ix],1111h
		jne	.c_v
		cmp	word [r_iy],2222h
		jne	.c_v
		cmp	word [r_sp],0fe00h
		jne	.c_v
		xor	cx,cx
.c_v:		call	verdict
		mov	si,s_psw
		call	puts
		mov	ax,[pc_psw]
		call	puthex16
		mov	si,s_bp
		call	puts
		mov	ax,[pc_bp]
		call	puthex16
		call	crlf

		; switch: two contexts in two segments, 1000 yields each
		mov	si,s_switch
		call	puts
		mov	ax,ZSEG
		mov	di,7100h
		SNIPPET	z_sw_a
		call	put_code
		mov	ax,SSEG
		mov	di,7100h
		SNIPPET	z_sw_b
		call	put_code
		mov	bx,ctx_a
		mov	ax,7100h
		mov	dx,ZSEG
		mov	cx,0002h
		call	ctx_init
		mov	bx,ctx_b
		mov	dx,SSEG
		call	ctx_init
		mov	word [rounds],1000
		mov	word [yield_entry],sw_next
		mov	byte [vrtc_mode],0
		SNIPPET	z_enter
		mov	ax,sw_first
		call	run_probe
		mov	ax,7f10h
		call	peek_z
		mov	[r_ax],ax
		mov	ax,7f10h
		call	peek_s
		mov	[r_cx],ax
		mov	ax,7f12h
		call	peek_z
		mov	[r_dx],ax
		mov	ax,7f12h
		call	peek_s
		mov	[r_bx],ax
		mov	cx,1
		cmp	word [r_ax],999
		jne	.s_v
		cmp	word [r_cx],999
		jne	.s_v
		cmp	word [r_dx],0
		jne	.s_v
		cmp	word [r_bx],0
		jne	.s_v
		xor	cx,cx
.s_v:		call	verdict
		mov	si,s_counts
		call	puts
		mov	ax,[r_ax]
		call	puthex16
		mov	al,' '
		call	putc
		mov	ax,[r_cx]
		call	puthex16
		mov	si,s_errors
		call	puts
		mov	ax,[r_dx]
		call	puthex16
		mov	al,' '
		call	putc
		mov	ax,[r_bx]
		call	puthex16
		call	crlf

		; preempt: two spinning contexts switched by VRTC, 20 frames each
		mov	si,s_preempt
		call	puts
		mov	ax,ZSEG
		mov	di,7200h
		SNIPPET	z_pre_a
		call	put_code
		mov	ax,SSEG
		mov	di,7200h
		SNIPPET	z_pre_b
		call	put_code
		mov	bx,ctx_a
		mov	ax,7200h
		mov	dx,ZSEG
		mov	cx,0002h
		call	ctx_init
		mov	bx,ctx_b
		mov	dx,SSEG
		call	ctx_init
		mov	word [rounds],20
		mov	word [preempt_entry],sw_next
		mov	byte [vrtc_mode],1
		mov	ax,[tick]
		mov	[r_ticks],ax
		SNIPPET	z_enter
		mov	ax,sw_first
		call	run_probe
		mov	byte [vrtc_mode],0
		mov	ax,[tick]
		sub	[r_ticks],ax
		neg	word [r_ticks]
		mov	ax,7f20h
		call	peek_z
		mov	[r_ax],ax
		mov	ax,7f20h
		call	peek_s
		mov	[r_cx],ax
		mov	ax,7f22h
		call	peek_z
		mov	[r_dx],ax
		mov	ax,7f22h
		call	peek_s
		mov	[r_bx],ax
		mov	cx,1
		cmp	word [r_ax],0
		je	.p_v
		cmp	word [r_cx],0
		je	.p_v
		cmp	word [r_dx],0
		jne	.p_v
		cmp	word [r_bx],0
		jne	.p_v
		xor	cx,cx
.p_v:		call	verdict
		mov	si,s_counts
		call	puts
		mov	ax,[r_ax]
		call	puthex16
		mov	al,' '
		call	putc
		mov	ax,[r_cx]
		call	puthex16
		mov	si,s_errors
		call	puts
		mov	ax,[r_dx]
		call	puthex16
		mov	al,' '
		call	putc
		mov	ax,[r_bx]
		call	puthex16
		mov	si,s_vrtcs
		call	puts
		mov	ax,[r_ticks]
		call	puthex16
		call	crlf

		; ldi-pv: P/V after LDI with BC 2 -> 1 (set) and 1 -> 0 (clear)
		mov	si,s_ldi
		call	puts
		SNIPPET	z_ldi
		xor	ax,ax
		call	run_probe
		mov	cx,1
		test	dl,04h
		jz	.l_v
		test	bl,04h
		jnz	.l_v
		xor	cx,cx
.l_v:		push	bx
		push	dx
		call	verdict
		mov	si,s_f
		call	puts
		pop	ax
		call	puthex8
		mov	al,' '
		call	putc
		pop	ax
		call	puthex8
		call	crlf

		; speed: loop iterations in 10 frames, for three loops
		mov	si,s_speed
		call	puts
		SNIPPET	z_spd1
		call	speed_run
		SNIPPET	z_spd2
		call	speed_run
		SNIPPET	z_spd3
		call	speed_run
		call	crlf

		mov	si,s_done
		call	puts
		call	wait_key
		jmp	menu

; Run the loop SI (CX bytes) at ZSEG:7300h for 10 VRTCs; print the count.
speed_run:	push	si
		push	cx
		call	clear_data
		pop	cx
		pop	si
		mov	ax,ZSEG
		mov	di,7300h
		call	put_code
		mov	bx,ctx_a
		mov	ax,7300h
		mov	dx,ZSEG
		mov	cx,0002h
		call	ctx_init
		mov	word [rounds],10
		mov	word [preempt_entry],sp_next
		mov	byte [vrtc_mode],1
		SNIPPET	z_enter
		mov	ax,sw_first
		call	run_probe
		mov	byte [vrtc_mode],0
		mov	ax,7f20h
		call	peek_z
		call	puthex16
		mov	al,' '
		jmp	putc

sp_next:	dec	word [cs:rounds]
		jz	.end
		mov	bx,ctx_a
		jmp	resume
.end:		jmp	p_finish

; Probe scheduler: alternate ctx_a and ctx_b, [rounds] times each.
sw_first:	mov	bx,ctx_a
		jmp	resume
sw_next:	cmp	word [cs:cur_ctx],ctx_a
		mov	bx,ctx_b
		je	.go
		dec	word [cs:rounds]
		jz	.end
		mov	bx,ctx_a
.go:		jmp	resume
.end:		jmp	p_finish

; CX = 0: PASS, else FAIL.
verdict:	mov	si,s_pass
		jcxz	.p
		mov	si,s_fail
.p:		jmp	puts

%endif
; ---------------------------------------------------------------------------
; The game

game_auto:	mov	byte [auto],1
		jmp	game.go
game:		mov	byte [auto],0
.go:		call	text_init
		mov	si,s_starting
		call	puts
%ifdef LIVE_VIDEO
		call	install_check		; the data built from the user's ROMs
		jnc	.installed
		mov	si,s_not_installed
		call	puts
.stop:		hlt
		jmp	.stop
.installed:	mov	si,s_installed
		call	puts
%endif
		; images: main segment and sound segment, the rest cleared
		push	es
		mov	ax,ZSEG
		mov	es,ax
		mov	si,ZIMG
		xor	di,di
		mov	cx,MAIN_SEGMENT_BYTES / 2
		rep	movsw
		xor	ax,ax
		mov	cx,(10000h - MAIN_SEGMENT_BYTES) / 2
		rep	stosw
		mov	ax,SSEG
		mov	es,ax
		mov	si,SIMG
		xor	di,di
		mov	cx,SOUND_SEGMENT_BYTES / 2
		rep	movsw
		xor	ax,ax
		mov	cx,(10000h - SOUND_SEGMENT_BYTES) / 2
		rep	stosw
		pop	es
%ifdef LIVE_VIDEO
		; Original images have been copied: their staging area can now hold
		; video lookup tables and state without touching the Z80 banks.
		call	live_video_init
		push	cs
		pop	es
		cmp	byte [auto],0		; scripted test runs start at once
		jne	.aligned
		call	live_align
.aligned:
%endif
		; native state
		mov	di,gstate
		mov	cx,gstate_end - gstate
		xor	al,al
		rep	stosb
		mov	byte [preempted],0ffh
		mov	byte [m51_remap],1
		; idle loop count of an empty frame, with the scheduler's loop
		mov	ax,[tick]
		mov	[seen],ax
		call	idle_spin
		mov	ax,[tick]
		mov	[seen],ax
		mov	word [idle_count],0
		call	idle_spin
		mov	ax,[idle_count]
		mov	[idle_calib],ax
		; main program at 0000h, sub and sound held in reset
		mov	bx,ctx_main
		xor	ax,ax
		mov	dx,ZSEG
		mov	cx,0002h
		call	ctx_init
		mov	byte [ready],1
		mov	word [yield_entry],g_yield
		mov	word [preempt_entry],g_preempt
		mov	word [sched_sp],SCHED_TOP
		mov	word [cur_ctx],ctx_boot
		mov	byte [cur],3
%ifndef LIVE_VIDEO
		call	text_init
%endif
		mov	ax,Z80_ENTER
		call	set_brkem
		cli
		call	mask_others
		mov	ax,[tick]
		mov	[seen],ax
		dec	ax
		mov	[seen_prev],ax
		call	new_frame
		mov	byte [vrtc_mode],1
		; Every CALLN and VRTC frame of the Z80 code lands at SCHED_TOP - 6,
		; where resume builds its IRET frame: also the first, from the stub
		; (BRKEM's own frame stays above SCHED_TOP). vaeg recognises the
		; return to compatible mode by that stack position.
		mov	sp,SCHED_TOP + 6
		mov	ax,ZSEG
		mov	ds,ax
		BRKEM	VEC_BRKEM		; to the stub, which yields at once
		jmp	$

ctxs		dw	ctx_main, ctx_sub, ctx_sound, ctx_boot

; CALLN VEC_YIELD in the game
g_yield:	xor	bh,bh
		mov	bl,[cs:cur]
		cmp	bl,3			; the entry stub
		jae	g_sched
		cmp	bl,2
		jne	.done
		call	sound_out
%ifdef M03_AUDIO
		call	m03_sound_update
%endif
		cmp	byte [cs:pend + 2],0	; another NMI this frame
		jne	.count
.done:		mov	byte [cs:done + bx],1
.count:		shl	bx,1
		inc	word [cs:yields + bx]
		jmp	g_sched

; VRTC while a program ran
g_preempt:	xor	bh,bh
		mov	bl,[cs:cur]
		cmp	bl,3
		jae	g_sched
		mov	[cs:preempted],bl
		cmp	bl,2
		jne	.count
		call	sound_out
%ifdef M03_AUDIO
		call	m03_sound_update
%endif
.count:		shl	bx,1
		inc	word [cs:preempts + bx]
		jmp	g_sched

; The scheduler runs on its own stack: an interrupt taken here must not
; push its frame where the Z80 code's frames go (vaeg takes an IRET at
; that position for the return to compatible mode).
g_sched:	cli
		mov	ax,cs
		mov	ds,ax
		mov	es,ax
		mov	sp,NATIVE_TOP
		mov	ax,[tick]
		cmp	ax,[seen]
		je	.pick
%ifdef FRAME_DEBT
		; A frame that overran is made up by starting the next ones at
		; once: seen advances one VRTC per frame while it is at most
		; FRAME_DEBT VRTCs behind; beyond that the excess is dropped.
		mov	dx,ax
		sub	dx,[seen]
		cmp	dx,FRAME_DEBT
		jbe	.one_vrtc
%ifdef SERVICE_MENU
		sub	dx,FRAME_DEBT		; dropped: for the load display (F9)
		add	[diag_dropped],dx
%endif
		sub	ax,FRAME_DEBT - 1
		mov	[seen],ax
		jmp	.frame
.one_vrtc:	inc	word [seen]
.frame:
%else
%ifdef SERVICE_MENU
		mov	dx,ax			; dropped: all but one (F9)
		sub	dx,[seen]
		dec	dx
		add	[diag_dropped],dx
%endif
		mov	[seen],ax
%endif
		call	new_frame
%ifdef LIVE_VIDEO
		; A program that waits in a loop of its own (not its idle loop:
		; the high score's tune, the boot RAM test) never lets the frame
		; end with every program done, where the picture is drawn. After
		; RENDER_STARVE frames without a picture, draw at the frame's
		; start, as there, with at most BG_MIN_ROWS background rows (a
		; big background change, such as the boot RAM test's, goes on in
		; the next ones): the program keeps most of its time.
		mov	ax,[frames]
		sub	ax,[live_drawn_frame]
		cmp	ax,RENDER_STARVE
		jb	.pick
		mov	byte [cur],3
		mov	word [cur_ctx],ctx_boot
		mov	byte [live_forced],1
		sti
		call	live_video_frame
		cli
		mov	byte [live_forced],0
		mov	ax,cs			; (as on entry)
		mov	ds,ax
		mov	es,ax
%endif
.pick:
%ifdef M03_AUDIO
%ifdef SOUND_PRIORITY
		cmp	byte [ready + 2],0
		je	.round_robin
		cmp	byte [done + 2],0
		jne	.round_robin
		mov	bx,2			; finish both sound NMIs before busy game CPUs
		jmp	run_cpu
.round_robin:
%endif
%endif
		mov	bl,[first]
		mov	cx,3
.try:		xor	bh,bh
		cmp	byte [ready + bx],0
		je	.next
		cmp	byte [done + bx],0
		je	run_cpu
.next:		inc	bl
		cmp	bl,3
		jb	.n
		xor	bl,bl
.n:		loop	.try
		; every program has finished its frame
		mov	byte [cur],3
		mov	word [cur_ctx],ctx_boot
		sti
%ifdef LIVE_VIDEO
		call	live_video_frame
		jmp	.spin
%else
		cmp	byte [view_due],0
		je	.spin
		mov	byte [view_due],0
		call	view
%endif
.spin:		call	idle_spin
		cli
		jmp	g_sched

; Count loop passes until the next VRTC (tick differs from seen).
idle_spin:
.wait:		inc	word [idle_count]
		mov	ax,[tick]
		cmp	ax,[seen]
		je	.wait
		ret

; Run program BX (0 main, 1 sub, 2 sound), delivering its interrupt.
run_cpu:	mov	[cur],bl
		mov	si,bx
		shl	si,1
		mov	di,[ctxs + si]		; DI: context
		cmp	bl,2
		je	.sound
		cmp	byte [pend + bx],0
		je	.go
		test	word [di + C_PSW],0200h	; IE
		jz	.go
		mov	byte [pend + bx],0
		mov	ax,MAIN_IRQ
		or	bl,bl
		jz	.irq
		mov	ax,SUB_IRQ
.irq:		call	inject
		and	word [di + C_PSW],0fdffh
		jmp	.go
.sound:		cmp	byte [pend + 2],0
		je	.in
%ifdef M03_AUDIO
		inc	word [m03_nmi_delivered]
%endif
		dec	byte [pend + 2]
		mov	ax,SOUND_NMI
		call	inject
.in:		call	sound_in
.go:		mov	bx,di
		jmp	resume

; Push the context DI's PC on its stack, PC = AX.
inject:		push	es
		push	bx
		mov	es,[di + C_DS]
		mov	bx,[di + C_BP]
		sub	bx,2
		mov	[di + C_BP],bx
		push	ax
		mov	ax,[di + C_IP]
		mov	[es:bx],ax
		pop	ax
		mov	[di + C_IP],ax
		pop	bx
		pop	es
		ret

%macro SYNC_RANGE 2
		mov	si,%1
		mov	di,%1
%if (%2) % 2
		mov	cx,%2
		rep	movsb
%else
		mov	cx,(%2) / 2		; words: half the transfers
		rep	movsw
%endif
%endmacro

sound_in:	push	ds
		push	es
		push	si
		push	di
		push	cx
		mov	ax,ZSEG
		mov	ds,ax
		mov	ax,SSEG
		mov	es,ax
		SOUND_SYNC_IN
		jmp	sound_sync_end

sound_out:	push	ds
		push	es
		push	si
		push	di
		push	cx
		mov	ax,SSEG
		mov	ds,ax
		mov	ax,ZSEG
		mov	es,ax
		SOUND_SYNC_OUT
sound_sync_end:	pop	cx
		pop	di
		pop	si
		pop	es
		pop	ds
		ret

; The frame's native work (DS = ES = CS, interrupts disabled).
new_frame:	inc	word [frames]
		mov	ax,[seen]		; VRTCs not seen by the scheduler (the
		sub	ax,[seen_prev]		; view was being written)
		mov	dx,[seen]
		mov	[seen_prev],dx
%ifdef SOUND_CATCHUP
		mov	[vrtcs_elapsed],ax
%endif
		dec	ax
		jz	.counted
		add	[lost_frames],ax
		mov	byte [skip_stats],1
.counted:	mov	ax,[idle_count]
%ifdef SERVICE_MENU
		add	[diag_idle],ax		; for the load display (F9)
		adc	word [diag_idle + 2],0
%endif
		cmp	byte [skip_stats],0
		jne	.skip
		add	[idle_sum],ax
		adc	word [idle_sum + 2],0
		inc	word [idle_n]
.skip:		mov	word [idle_count],0
		call	scan_keys
%ifdef LIVE_VIDEO
		or	al,[key_latch]		; presses seen by the VRTC handler
		mov	byte [key_latch],0	; since the last frame
%endif
		test	al,K_ESC
		jz	.noesc
		jmp	0ffffh:0000h
.noesc:
%if %isdef(TEST_ROUND) || %isdef(SERVICE_MENU)
		; Debug: start rounds at start_round (F10 ROUND, or TEST_ROUND).
		; The main program clears its round counters (840Dh, player 2
		; 840Eh) at a game start and increments them at each round start:
		; preset them whenever they are zero.
		mov	dl,[start_round]	; (AL holds the keys)
		or	dl,dl
		jz	.round_set
		dec	dl
		push	ds
		mov	bx,ZSEG
		mov	ds,bx
		cmp	byte [840dh],0
		jne	.round_p2
		mov	[840dh],dl
.round_p2:	cmp	byte [840eh],0
		jne	.round_done
		mov	[840eh],dl
.round_done:	pop	ds
.round_set:
%endif
%ifdef TEST_SCORE
		push	ds			; test only: player 1's score (BCD
						; 8414h-8416h) at least 50000
		mov	bx,ZSEG
		mov	ds,bx
		cmp	byte [8416h],05h
		jae	.score_ok
		mov	byte [8416h],05h
.score_ok:	pop	ds
%endif
%ifdef SERVICE_MENU
		call	service_frame		; AL: what the game sees
%endif
		cmp	byte [auto],0
		je	.keys
		call	auto_keys
.keys:		mov	ah,[keys]
		mov	[keys],al
		not	ah
		and	ah,al
		or	[keys_new],ah		; cleared when the 51xx reads them
		push	ds
		mov	ax,ZSEG
		mov	ds,ax
		mov	al,[6820h]
		mov	ah,[6821h]
		mov	dl,[6822h]
		mov	dh,[6823h]
		pop	ds
		test	al,1			; main IRQ enabled
		jz	.sub
		mov	byte [pend],1
.sub:		test	ah,1
		jz	.snd
		mov	byte [pend + 1],1
.snd:
%ifdef NATIVE_SOUND
		; The native driver ticks in the VRTC handler (sound_vrtc); the
		; sound program never runs.
		mov	byte [pend + 2],0
%else
%ifndef SOUND_CATCHUP
%ifdef M03_AUDIO
		cmp	byte [ready + 2],0
		je	.nmi_counted
		xor	bx,bx
		mov	bl,[pend + 2]
		add	[m03_nmi_dropped],bx
.nmi_counted:
%endif
%endif
%ifdef SOUND_CATCHUP
		; The sound program's tempo is its NMI count: two per VRTC. NMIs a
		; busy frame could not deliver, and those of VRTCs the scheduler
		; did not see (a long render), are kept, up to two frames' worth,
		; and delivered in the next frame, instead of being dropped.
		test	dl,1			; 0: sound NMI enabled
		jz	.nmi_on
		mov	byte [pend + 2],0
		jmp	.reset
.nmi_on:	mov	ax,[vrtcs_elapsed]
		shl	ax,1
		xor	bx,bx
		mov	bl,[pend + 2]
		add	ax,bx
		cmp	ax,SOUND_CATCHUP
		jbe	.nmi_store
%ifdef M03_AUDIO
		sub	ax,SOUND_CATCHUP
		add	[m03_nmi_dropped],ax
%endif
		mov	ax,SOUND_CATCHUP
.nmi_store:	mov	[pend + 2],al
%else
		mov	byte [pend + 2],0
		test	dl,1			; 0: sound NMI enabled
		jnz	.reset
		mov	byte [pend + 2],2
%endif
%endif
.reset:		test	dh,1			; 0: sub and sound held in reset
		jnz	.run
		mov	word [ready + 1],0
		mov	word [pend + 1],0
%ifdef NATIVE_SOUND
		mov	byte [sd_state],SD_OFF
%endif
		jmp	.round
.run:
%ifdef NATIVE_SOUND
		call	sound_start_step	; the program's start-up handshake
%endif
		cmp	byte [ready + 1],0
		jne	.round
		mov	bx,ctx_sub		; out of reset
		mov	ax,SUB_RESET
		mov	dx,ZSEG
		mov	cx,0002h
		call	ctx_init
%ifdef NATIVE_SOUND
		mov	byte [ready + 1],1
%else
		mov	bx,ctx_sound
		xor	ax,ax
		mov	dx,SSEG
		mov	cx,0202h		; IE = 1: the program never uses it
		call	ctx_init
		mov	word [ready + 1],0101h
%endif
.round:		mov	word [done],0
		mov	byte [done + 2],0
%ifdef SERVICE_MENU
		call	service_hold
%endif
		mov	al,[preempted]
		mov	byte [first],0
		cmp	al,3
		jae	.view
		inc	al			; start after the program preempted
		cmp	al,3
		jb	.f
		xor	al,al
.f:		mov	[first],al
		cmp	byte [skip_stats],0
		jne	.view
		inc	word [late_frames]
.view:		mov	byte [skip_stats],0
		mov	byte [preempted],0ffh
		dec	byte [view_count]
		jns	.r
		mov	byte [view_count],VIEW_FRAMES - 1
		mov	byte [view_due],1
.r:		ret

auto_keys:	xor	al,al
		mov	bx,[frames]
		cmp	bx,AUTO_COIN
		jb	.r
		cmp	bx,AUTO_COIN + 5
		jae	.s
		or	al,K_COIN
.s:		cmp	bx,AUTO_START
		jb	.r
		cmp	bx,AUTO_START + 5
		jae	.m
		or	al,K_START
.m:		cmp	bx,AUTO_MOVE
		jb	.r
		push	ax
		mov	ax,bx
		xor	dx,dx
		mov	cx,45
		div	cx
		and	ax,3
		mov	cx,ax
		pop	ax
		mov	ah,K_UP
		shl	ah,cl
		or	al,ah
		push	ax
		mov	ax,bx
		xor	dx,dx
		mov	cx,20
		div	cx
		pop	ax
		cmp	dx,3
		jae	.r
		or	al,K_FIRE
.r:		ret

; AL = keys held (K_*), from the key matrix (active low). Moves: keypad
; 8 6 2 4 or the cursor keys. Fire: SPACE or keypad 0. Coin: 5. Start: 1.
scan_keys:	push	bx
		push	dx
		xor	bl,bl
		in	al,00h			; keypad 0-7
		not	al
		test	al,01h
		jz	.k2
		or	bl,K_FIRE
.k2:		test	al,04h
		jz	.k4
		or	bl,K_DOWN
.k4:		test	al,10h
		jz	.k5
		or	bl,K_LEFT
.k5:		test	al,20h
		jz	.k6
		or	bl,K_COIN
.k6:		test	al,40h
		jz	.k8
		or	bl,K_RIGHT
.k8:		in	al,01h			; keypad 8
		test	al,01h
		jnz	.main
		or	bl,K_UP
.main:		in	al,06h			; 0-7
		not	al
		test	al,02h
		jz	.m5
		or	bl,K_START
.m5:		test	al,20h
		jz	.c8
		or	bl,K_COIN
.c8:		in	al,08h			; up (bit 1), right (bit 2)
		not	al
		test	al,02h
		jz	.c8r
		or	bl,K_UP
.c8r:		test	al,04h
		jz	.ca
		or	bl,K_RIGHT
.ca:		in	al,0ah			; down (bit 1), left (bit 2)
		not	al
		test	al,02h
		jz	.car
		or	bl,K_DOWN
.car:		test	al,04h
		jz	.sp
		or	bl,K_LEFT
.sp:		in	al,09h			; SPACE (bit 6), ESC (bit 7)
		not	al
		test	al,40h
		jz	.esc
		or	bl,K_FIRE
.esc:		test	al,80h
		jz	.done
		or	bl,K_ESC
.done:		mov	al,bl
		pop	dx
		pop	bx
		ret

; ---------------------------------------------------------------------------
; 06xx transfers and the custom I/O chips (51xx: coins, credits, controls;
; 53xx: DIP switches). The io06 stub calls VEC_06XX_STEP before each byte
; and VEC_06XX_DONE at the end. A byte read is placed at 7000h + n before
; the program's NMI routine copies it; a byte written is taken from
; 7000h + n after. A new transfer starts when the control byte or the
; program's transfer queue pointer (8900h) changes.

io_step:	cli
		pusha
		push	ds
		mov	ax,ZSEG
		mov	ds,ax
		mov	al,[7100h]
		mov	bx,[8900h]
		cmp	byte [cs:io_active],0
		je	.new
		cmp	al,[cs:io_ctrl]
		jne	.new
		cmp	bx,[cs:io_queue]
		jne	.new
		call	io_collect
		inc	byte [cs:io_n]
		jmp	.pre
.new:		call	io_collect
		mov	[cs:io_ctrl],al
		mov	[cs:io_queue],bx
		mov	byte [cs:io_n],0
		mov	byte [cs:io_active],1
		mov	byte [cs:m51_index],0
		mov	byte [cs:m53_index],0
		inc	word [cs:io_transfers]
.pre:		test	byte [cs:io_ctrl],10h	; read
		jz	.ret
		mov	al,0ffh
		test	byte [cs:io_ctrl],01h
		jz	.c2
		call	m51_read
.c2:		test	byte [cs:io_ctrl],02h
		jz	.put
		call	m53_read
.put:		xor	bh,bh
		mov	bl,[cs:io_n]
		mov	[7000h + bx],al
.ret:		pop	ds
		popa
		iret

; Main IRQ: the sprite RAM copy (tools/patches.py, sprite_copy): 9800h ->
; 8B80h and 9900h -> 9B80h, 128 bytes each. The Z80 registers (HL = BX,
; DE = DX, BC = CX) are left as the two LDIRs leave them.
sprite_copy_h:	cli
		push	si
		push	di
		push	ds
		push	es
		mov	cx,ZSEG
		mov	ds,cx
		mov	es,cx
		mov	si,9800h
		mov	di,8b80h
		mov	cx,64
		rep	movsw
		mov	si,9900h
		mov	di,9b80h
		mov	cx,64
		rep	movsw
		mov	bx,9980h
		mov	dx,9c00h
		pop	es
		pop	ds
		pop	di
		pop	si
		iret

; Sub 0E4Ch (tools/patches.py, sub_positions): 64 sprite positions from
; 9880h to 9380h, the second byte + 37h, or, with the screen flipped
; (8400h bits 1 and 2), F2h - first, 27h - second; nothing when 87F0h
; bit 3 is set. A, B (CH), DE and HL are left as the original leaves them.
sub_positions_h:
		cli
		push	si
		push	di
		push	ds
		push	es
		mov	si,ZSEG
		mov	ds,si
		mov	es,si
		mov	bx,9880h
		mov	dx,9380h
		mov	ch,40h
		mov	al,[87f0h]
		test	al,8
		jnz	.done
		mov	al,[8400h]
		mov	si,9880h
		mov	di,9380h
		and	al,6
		cmp	al,6
		je	.flipped
		mov	ch,16			; four pairs a pass
.normal:	lodsw
		add	ah,37h
		stosw
		lodsw
		add	ah,37h
		stosw
		lodsw
		add	ah,37h
		stosw
		lodsw
		add	ah,37h
		stosw
		dec	ch
		jnz	.normal
		mov	al,ah
		jmp	.end
.flipped:	lodsw				; AL = x, AH = y
		mov	bl,0f2h
		sub	bl,al
		mov	al,bl
		mov	bl,27h
		sub	bl,ah
		mov	ah,bl
		stosw
		dec	ch
		jnz	.flipped
		mov	al,ah
.end:		mov	bx,9900h
		mov	dx,9400h
.done:		pop	es
		pop	ds
		pop	di
		pop	si
		iret

; Main 1B90h, 1BADh, 16E3h (tools/patches.py, objects_a/b/c): object
; tables to sprite RAM. Memory only (Z80 registers kept); the stubs set
; the registers the routines leave.
objects_a_h:	cli
		push	cx
		push	si
		push	di
		push	ds
		push	es
		mov	si,ZSEG
		mov	ds,si
		mov	es,si
		mov	si,8465h		; 8 x 2 bytes, 8465h + 8n -> 98BCh + 2n
		mov	di,98bch
		mov	cx,8
.copy:		movsw
		add	si,6
		dec	cx
		jnz	.copy
		jmp	objects_end
objects_b_h:	cli
		push	cx
		push	si
		push	di
		push	ds
		push	es
		mov	si,ZSEG
		mov	ds,si
		mov	es,si
		mov	si,8529h		; 8 x 4 bytes from 8529h + 16n:
		mov	di,98e4h		; two to 98E4h + 2n, two to 9864h + 2n
		mov	cx,8
.copy:		movsw
		lodsw
		mov	[di - 2 - 80h],ax
		add	si,12
		dec	cx
		jnz	.copy
		jmp	objects_end
objects_c_h:	cli
		push	cx
		push	si
		push	di
		push	ds
		push	es
		mov	si,ZSEG
		mov	ds,si
		mov	es,si
		mov	si,8532h		; 8 bytes, 8532h + 16n -> 9964h + 2n
		mov	di,9964h
		mov	cx,8
.copy:		movsb
		add	si,15
		inc	di
		dec	cx
		jnz	.copy
objects_end:	pop	es
		pop	ds
		pop	di
		pop	si
		pop	cx
		iret

; Main 14FDh (tools/patches.py, digits): the three BCD bytes at DE (low
; digit first) to 841Dh-8422h; from 8422h down, at most four zeros become
; 8Ch (0Ch when 87CCh has bit 1 set and bit 2 clear); then the digits from
; 8422h down to IX, IX - 1, ... (+10h unless 8Ch or 0Ch), all but the last,
; which the stub does. Leaves DE + 3, HL = 841Dh; IX unchanged here.
digits_h:	cli
		push	cx
		push	si
		push	di
		push	ds
		push	es
		push	ax
		mov	di,ZSEG
		mov	ds,di
		mov	es,di
		mov	di,841dh
		mov	cx,3
.unpack:	mov	bx,dx
		mov	al,[bx]
		inc	dx
		mov	ah,al
		and	al,0fh
		shr	ah,4
		stosw
		dec	cx
		jnz	.unpack
		mov	bx,8422h
		mov	cx,4
.blank:		cmp	byte [bx],0
		jne	.copy
		mov	al,8ch
		mov	ah,[87cch]
		and	ah,6
		cmp	ah,2
		jne	.store
		mov	al,0ch
.store:		mov	[bx],al
		dec	bx
		dec	cx
		jnz	.blank
.copy:		mov	bx,8422h
		mov	cx,5
.digit:		mov	al,[bx]
		cmp	al,8ch
		je	.out
		cmp	al,0ch
		je	.out
		add	al,10h
.out:		mov	[si],al
		dec	bx
		dec	si
		dec	cx
		jnz	.digit
		pop	ax
		pop	es
		pop	ds
		pop	di
		pop	si
		pop	cx
		iret

; Main 1430h (tools/patches.py, text10): 10 bytes from IX (its table, set
; by the stub) to 83D4h down. Memory only.
text10_h:	cli
		push	ax
		push	bx
		push	cx
		push	si
		push	ds
		mov	ax,ZSEG
		mov	ds,ax
		mov	bx,83d4h
		mov	cx,10
.copy:		lodsb
		mov	[bx],al
		dec	bx
		dec	cx
		jnz	.copy
		pop	ds
		pop	si
		pop	cx
		pop	bx
		pop	ax
		iret

;; Main IRQ 0A52h (tools/patches.py, fill12): 05h to 9825h + 2n, n < 12,
; A to 6830h; leaves HL = 983Dh and B = 0 as the loop does.
fill12_h:	cli
		push	ds
		mov	bx,ZSEG
		mov	ds,bx
		mov	bx,9825h
		mov	ch,12
.fill:		mov	byte [bx],5
		inc	bx
		inc	bx
		dec	ch
		jnz	.fill
		mov	[6830h],al
		pop	ds
		iret

; Main 0D54h (copy3): 3 bytes from HL to DE, each also to 6830h; HL and
; DE end 3 on, B = 0, A = the last byte.
copy3_h:	cli
		push	si
		push	ds
		mov	si,ZSEG
		mov	ds,si
		mov	ch,3
.copy:		mov	al,[bx]
		mov	si,dx
		mov	[si],al
		inc	bx
		inc	dx
		dec	ch
		jnz	.copy
		mov	[6830h],al
		pop	ds
		pop	si
		iret

; Main 134Ch (near): for the 8 objects at 8529h + 16n, 85F6h = the
; object, 861Ah = |98A2h - x|, then |98A3h - y| added. At the first sum
; below 10 the routine goes on at 1393h (the stub's JP, CF set in the
; returned flags) with B = objects left, C = y, DE = |dy|, HL = sum, A = L.
; Otherwise as at its RET: B = 0, C = the last y, DE = 10h, HL = 85A9h, CF
; clear (A and the flags are not used by its caller).
near_h:		cli
		push	si
		push	ds
		mov	si,ZSEG
		mov	ds,si
		mov	bx,8529h
		mov	ch,8
.object:	mov	[85f6h],bx
		mov	al,[98a2h]
		sub	al,[bx]
		jae	.x
		neg	al
.x:		mov	[861ah],al
		mov	cl,[bx + 1]
		mov	ah,[98a3h]
		sub	ah,cl
		jae	.y
		neg	ah
.y:		mov	dl,ah
		xor	dh,dh
		xor	ah,ah
		add	ax,dx			; |dx| + |dy| < 10: near
		cmp	ax,10
		jb	.near
		add	bx,16
		dec	ch
		jnz	.object
		mov	dx,10h
		pop	ds
		pop	si
		push	bp
		mov	bp,sp
		and	byte [bp + 6],0feh	; CF clear: return
		pop	bp
		iret
.near:		mov	bx,ax
		pop	ds
		pop	si
		push	bp
		mov	bp,sp
		or	byte [bp + 6],1		; CF set: on at 1393h
		pop	bp
		iret

io_done:	cli
		pusha
		push	ds
		mov	ax,ZSEG
		mov	ds,ax
		call	io_collect
		mov	byte [cs:io_active],0
		pop	ds
		popa
		iret

; The byte written by the previous step, if the transfer is a write.
io_collect:	cmp	byte [cs:io_active],0
		je	.r
		test	byte [cs:io_ctrl],10h
		jnz	.r
		test	byte [cs:io_ctrl],01h
		jz	.r
		push	ax
		push	bx
		xor	bh,bh
		mov	bl,[cs:io_n]
		mov	al,[7000h + bx]
		call	m51_write
		pop	bx
		pop	ax
.r:		ret

; 51xx command byte AL
m51_write:	cmp	byte [cs:m51_args],0
		je	.cmd
		dec	byte [cs:m51_args]	; coinage: 1 coin 1 credit is assumed
		ret
.cmd:		cmp	al,01h
		jne	.c2
		mov	byte [cs:m51_args],4
		ret
.c2:		cmp	al,02h
		jne	.c3
		mov	byte [cs:m51_mode],1	; credits, start buttons enabled
		ret
.c3:		cmp	al,03h
		jne	.c4
		mov	byte [cs:m51_remap],0
		ret
.c4:		cmp	al,04h
		jne	.c5
		mov	byte [cs:m51_remap],1
		ret
.c5:		cmp	al,05h
		jne	.r
		mov	byte [cs:m51_mode],0	; switches
.r:		ret

; 51xx data byte -> AL. Switch mode: the raw switches (none emulated but
; the controls). Credit mode: credits (BCD), player 1, player 2; the
; players' bytes are FFh until a start button has been accepted.
m51_read:	push	bx
		mov	bl,[cs:m51_index]
		inc	byte [cs:m51_index]
		cmp	byte [cs:m51_mode],0
		jne	.credit
		mov	al,0ffh
		or	bl,bl
		jnz	.r
		call	raw_joy			; IN0: player 1 low nibble
		or	al,0f0h
		jmp	.r
.credit:	or	bl,bl
		jnz	.p1
		mov	al,[cs:keys_new]
		mov	byte [cs:keys_new],0
		test	al,K_COIN
		jz	.start
		cmp	byte [cs:m51_credits],99
		jae	.start
		inc	byte [cs:m51_credits]
.start:		cmp	byte [cs:m51_mode],1
		jne	.bcd
		test	byte [cs:keys],K_START
		jz	.bcd
		cmp	byte [cs:m51_credits],0
		je	.bcd
		dec	byte [cs:m51_credits]
		mov	byte [cs:m51_mode],2
.bcd:		mov	al,[cs:m51_credits]
		aam				; AH = tens, AL = units
		shl	ah,4
		or	al,ah
		jmp	.r
.p1:		mov	al,0ffh
		cmp	byte [cs:m51_mode],1
		je	.r
		cmp	bl,1
		jne	.p2
		call	raw_joy
		xor	bh,bh
		mov	bl,al
		mov	al,[cs:joy_map + bx]
		test	byte [cs:keys],K_FIRE
		jnz	.held
		or	al,20h
.held:		mov	bl,[cs:keys]
		and	bl,K_FIRE
		mov	bh,[cs:fire_prev]
		mov	[cs:fire_prev],bl
		not	bh
		and	bl,bh			; pressed since the last read
		jnz	.r
		or	al,10h
		jmp	.r
.p2:		mov	al,38h			; player 2: centred, no button
.r:		pop	bx
		ret

; Player 1's joystick as the arcade's IN0 low nibble (active low:
; bit 0 up, 1 right, 2 down, 3 left).
raw_joy:	mov	al,[cs:keys]
		and	al,0fh
		xor	al,0fh
		ret

; 53xx data byte -> AL: the DIP switches.
m53_read:	push	bx
		xor	bh,bh
		mov	bl,[cs:m53_index]
		inc	byte [cs:m53_index]
		and	bl,1
		mov	al,[cs:dsw + bx]
		pop	bx
		ret

; Remap of the raw joystick nibble to the direction code (0 up, 2 right,
; 4 down, 6 left, 8 centre).
joy_map		db	0fh, 0eh, 0dh, 05h, 0ch, 09h, 07h, 06h
		db	0bh, 03h, 0ah, 04h, 01h, 02h, 00h, 08h
dsw		db	DSWA, DSWB

; ---------------------------------------------------------------------------
%ifndef LIVE_VIDEO			; M01 text view only
; Game view: tile RAM as text in the game's orientation, rows 0-11, 12-23
; and 24-35 side by side (columns 1-26 of 28), then statistics on text
; rows 13-17 (the text screen has 20 rows).

VIEW_ROWS	equ	17

view:		pusha
		push	es
		mov	ax,[tick]
		mov	[view_start],ax
		mov	byte [to_buf],1
		xor	cx,cx			; CL: text row
.row:		mov	al,80
		mul	cl
		mov	[buf_pos],ax
		mov	ch,cl			; CH: game y
		call	view_line
		mov	al,' '
		call	putc
		add	ch,12
		call	view_line
		mov	al,' '
		call	putc
		add	ch,12
		call	view_line
		mov	al,' '
		call	putc
		call	putc
		inc	cl
		cmp	cl,12
		jb	.row
		mov	word [buf_pos],13 * 80
		mov	si,s_frames
		call	puts
		mov	ax,[frames]
		call	puthex16
		mov	si,s_late
		call	puts
		mov	ax,[late_frames]
		call	puthex16
		mov	si,s_lost
		call	puts
		mov	ax,[lost_frames]
		call	puthex16
		mov	si,s_idle
		call	puts
		mov	ax,[idle_sum]		; idle passes per frame
		mov	dx,[idle_sum + 2]
		mov	cx,[idle_n]
		jcxz	.noidle
		div	cx
.noidle:	mov	word [idle_sum],0
		mov	word [idle_sum + 2],0
		mov	word [idle_n],0
		push	ax
		call	puthex16
		mov	al,'/'
		call	putc
		mov	ax,[idle_calib]
		call	puthex16
		mov	si,s_load
		call	puts
		pop	ax			; load % = 100 - 100 * idle / calib
		mov	cx,100
		mul	cx
		mov	cx,[idle_calib]
		jcxz	.noload
		cmp	dx,cx
		jae	.noload
		div	cx
		mov	ah,100
		sub	ah,al
		mov	al,ah
		aam
		shl	ah,4
		or	al,ah
		call	puthex8
.noload:	mov	al,'%'
		call	putc
		mov	si,s_vt
		call	puts
		mov	al,[view_ticks]
		call	puthex8
		mov	word [buf_pos],14 * 80
		mov	si,s_io
		call	puts
		mov	ax,[io_transfers]
		call	puthex16
		mov	si,s_credits
		call	puts
		mov	al,[m51_credits]
		call	puthex8
		mov	al,' '
		call	putc
		mov	al,[m51_mode]
		call	puthex8
		mov	ax,15 * 80		; rows 15-17: the programs
		xor	bx,bx
.cpu:		mov	[buf_pos],ax
		push	ax
		push	bx
		mov	si,bx
		shl	si,2
		add	si,s_cpus
		call	puts
		shl	bx,1
		mov	si,s_yields
		call	puts
		mov	ax,[yields + bx]
		call	puthex16
		mov	si,s_preempts
		call	puts
		mov	ax,[preempts + bx]
		call	puthex16
		mov	di,[ctxs + bx]
		mov	si,s_pc
		call	puts
		mov	ax,[di + C_IP]
		call	puthex16
		mov	si,s_psw
		call	puts
		mov	ax,[di + C_PSW]
		call	puthex16
		pop	bx
		mov	si,s_ready
		call	puts
		mov	al,[ready + bx]
		call	puthex8
		pop	ax
		add	ax,80
		inc	bx
		cmp	bx,3
		jb	.cpu
		mov	byte [to_buf],0
		call	flush
		mov	ax,[tick]
		sub	ax,[view_start]
		mov	[view_ticks],al
		pop	es
		popa
		ret

; Write the characters of scr that differ from shown, rows 0-17.
flush:		xor	bx,bx			; BX: cell
		mov	byte [flush_at],0	; 1: the cursor is at BX
.cell:		mov	al,[scr + bx]
		or	al,al
		jnz	.c
		mov	al,' '
		mov	[scr + bx],al
.c:		cmp	al,[shown + bx]
		jne	.out
		mov	byte [flush_at],0
		jmp	.next
.out:		mov	[shown + bx],al
		cmp	byte [flush_at],0
		jne	.put
		push	ax
		mov	ax,bx
		mov	dl,80
		div	dl			; AL: row, AH: column
		mov	dx,ax			; DL: row, DH: column
		mov	ah,08h
		int	83h
		pop	ax
		mov	byte [flush_at],1
.put:		call	putc
.next:		inc	bx
		cmp	bx,(VIEW_ROWS + 1) * 80
		jb	.cell
		ret

; Game row CH, columns 1-26.
view_line:	mov	bl,1			; BL: game x
.x:		mov	al,27			; raster row r = 27 - x, column c = y
		sub	al,bl
		add	al,2			; rr = r + 2
		mov	ah,ch
		sub	ah,2			; cc = c - 2
		test	ah,20h
		jz	.low
		and	ah,1fh			; rr + (cc & 1Fh) * 32
		mov	dl,al
		mov	al,ah
		xor	ah,ah
		shl	ax,5
		add	al,dl
		adc	ah,0
		jmp	.read
.low:		mov	dl,ah			; cc + rr * 32
		xor	ah,ah
		shl	ax,5
		add	al,dl
		adc	ah,0
.read:		mov	si,ax
		push	ds
		mov	ax,ZSEG
		mov	ds,ax
		mov	al,[8000h + si]
		pop	ds
		push	bx
		mov	bx,charmap
		xlat
		pop	bx
		call	putc
		inc	bl
		cmp	bl,27
		jb	.x
		ret

%endif
; ---------------------------------------------------------------------------
; Text output (text BIOS INT 83h) and keyboard (INT 82h)

text_init:	mov	ah,2ah			; initialise the text screen
		int	83h
		mov	ax,1702h		; clear the whole split screen
		int	83h
		xor	dx,dx
		mov	ah,08h
		int	83h
		ret

putc:
%ifndef LIVE_VIDEO
		cmp	byte [cs:to_buf],0	; the text view's buffer
		jne	.buf
%endif
		pusha
		push	ds
		push	es
		xor	ah,ah
		mov	dx,ax
		int	83h
		pop	es
		pop	ds
		popa
		ret
%ifndef LIVE_VIDEO
.buf:		push	bx
		mov	bx,[cs:buf_pos]
		mov	[cs:scr + bx],al
		inc	word [cs:buf_pos]
		pop	bx
		ret
%endif

puts:		push	ax
.l:		mov	al,[cs:si]
		inc	si
		or	al,al
		jz	.r
		call	putc
		jmp	.l
.r:		pop	ax
		ret

crlf:		mov	si,s_crlf
		jmp	puts

puthex16:	push	ax
		mov	al,ah
		call	puthex8
		pop	ax
puthex8:	push	ax
		shr	al,4
		call	.digit
		pop	ax
		and	al,0fh
.digit:		push	ax
		add	al,'0'
		cmp	al,'9'
		jbe	.out
		add	al,7
.out:		call	putc
		pop	ax
		ret

wait_key:	mov	ah,0ch
		int	82h
		mov	ah,09h
		int	82h
		ret

; ---------------------------------------------------------------------------
%ifndef LIVE_VIDEO			; M01 probes only
; Z80 probe snippets (hand-assembled)

; Entry for the scheduled probes: hand over to the native scheduler.
z_enter:	db	0edh, 0edh, VEC_PENTER	; calln VEC_PENTER
z_enter_end:

z_calln:	db	31h, 00h, 0feh		; ld sp,0FE00h
		db	3eh, 12h		; ld a,12h
		db	01h, 56h, 34h		; ld bc,3456h
		db	11h, 9ah, 78h		; ld de,789Ah
		db	21h, 0deh, 0bch		; ld hl,0BCDEh
		db	0ddh, 21h, 11h, 11h	; ld ix,1111h
		db	0fdh, 21h, 22h, 22h	; ld iy,2222h
		db	37h			; scf
		db	0edh, 0edh, VEC_PCALLN	; calln VEC_PCALLN
		db	32h, 00h, 7fh		; ld (7F00h),a
		db	3eh, 00h		; ld a,0
		db	0ceh, 00h		; adc a,0
		db	32h, 01h, 7fh		; ld (7F01h),a   carry
		db	0ddh, 22h, 02h, 7fh	; ld (7F02h),ix
		db	0fdh, 22h, 04h, 7fh	; ld (7F04h),iy
		db	0edh, 73h, 06h, 7fh	; ld (7F06h),sp
		db	0edh, 0fdh		; retem
z_calln_end:

; Context A of the switch probe (main segment, 7100h): holds BC, DE, IX,
; IY and the alternate registers, checks them after every yield, counts
; the passes at 7F10h and sets 7F12h on a mismatch.
z_sw_a:		db	31h, 00h, 0fdh		; ld sp,0FD00h
		db	0d9h			; exx
		db	01h, 0a2h, 0a1h		; ld bc,0A1A2h
		db	11h, 0a4h, 0a3h		; ld de,0A3A4h
		db	21h, 0a6h, 0a5h		; ld hl,0A5A6h
		db	0d9h			; exx
		db	08h, 3eh, 0a7h, 08h	; ex af,af'; ld a,0A7h; ex af,af'
		db	01h, 0b2h, 0b1h		; ld bc,0B1B2h
		db	11h, 0b4h, 0b3h		; ld de,0B3B4h
		db	0ddh, 21h, 0c2h, 0c1h	; ld ix,0C1C2h
		db	0fdh, 21h, 0c4h, 0c3h	; ld iy,0C3C4h
.loop:		db	0edh, 0edh, VEC_YIELD	; calln VEC_YIELD
		db	21h, 0b2h, 0b1h		; ld hl,0B1B2h
		db	0b7h, 0edh, 42h		; or a; sbc hl,bc
		ZJR	20h, .err
		db	21h, 0b4h, 0b3h		; ld hl,0B3B4h
		db	0b7h, 0edh, 52h		; or a; sbc hl,de
		ZJR	20h, .err
		db	0ddh, 0e5h, 0e1h	; push ix; pop hl
		db	7ch, 0feh, 0c1h		; ld a,h; cp 0C1h
		ZJR	20h, .err
		db	7dh, 0feh, 0c2h		; ld a,l; cp 0C2h
		ZJR	20h, .err
		db	0fdh, 0e5h, 0e1h	; push iy; pop hl
		db	7ch, 0feh, 0c3h		; ld a,h; cp 0C3h
		ZJR	20h, .err
		db	7dh, 0feh, 0c4h		; ld a,l; cp 0C4h
		ZJR	20h, .err
		db	0d9h			; exx
		db	78h, 0feh, 0a1h		; ld a,b; cp 0A1h
		ZJR	20h, .errx
		db	79h, 0feh, 0a2h		; ld a,c; cp 0A2h
		ZJR	20h, .errx
		db	7ah, 0feh, 0a3h		; ld a,d; cp 0A3h
		ZJR	20h, .errx
		db	7bh, 0feh, 0a4h		; ld a,e; cp 0A4h
		ZJR	20h, .errx
		db	7ch, 0feh, 0a5h		; ld a,h; cp 0A5h
		ZJR	20h, .errx
		db	7dh, 0feh, 0a6h		; ld a,l; cp 0A6h
		ZJR	20h, .errx
		db	0d9h			; exx
		db	08h, 0feh, 0a7h		; ex af,af'; cp 0A7h
		ZJR	20h, .erra
		db	08h			; ex af,af'
		db	2ah, 10h, 7fh		; ld hl,(7F10h)
		db	23h			; inc hl
		db	22h, 10h, 7fh		; ld (7F10h),hl
		ZJR	18h, .loop
.erra:		db	08h			; ex af,af'
		ZJR	18h, .err
.errx:		db	0d9h			; exx
.err:		db	3eh, 01h		; ld a,1
		db	32h, 12h, 7fh		; ld (7F12h),a
.eloop:		db	0edh, 0edh, VEC_YIELD	; calln VEC_YIELD
		ZJR	18h, .eloop
z_sw_a_end:

; Context B (sound segment, 7100h): its own BC, DE, IX, IY; no alternate
; registers.
z_sw_b:		db	31h, 00h, 0fdh		; ld sp,0FD00h
		db	01h, 0d2h, 0d1h		; ld bc,0D1D2h
		db	11h, 0d4h, 0d3h		; ld de,0D3D4h
		db	0ddh, 21h, 0e2h, 0e1h	; ld ix,0E1E2h
		db	0fdh, 21h, 0e4h, 0e3h	; ld iy,0E3E4h
.loop:		db	0edh, 0edh, VEC_YIELD	; calln VEC_YIELD
		db	21h, 0d2h, 0d1h		; ld hl,0D1D2h
		db	0b7h, 0edh, 42h		; or a; sbc hl,bc
		ZJR	20h, .err
		db	21h, 0d4h, 0d3h		; ld hl,0D3D4h
		db	0b7h, 0edh, 52h		; or a; sbc hl,de
		ZJR	20h, .err
		db	0ddh, 0e5h, 0e1h	; push ix; pop hl
		db	7ch, 0feh, 0e1h		; ld a,h; cp 0E1h
		ZJR	20h, .err
		db	7dh, 0feh, 0e2h		; ld a,l; cp 0E2h
		ZJR	20h, .err
		db	0fdh, 0e5h, 0e1h	; push iy; pop hl
		db	7ch, 0feh, 0e3h		; ld a,h; cp 0E3h
		ZJR	20h, .err
		db	7dh, 0feh, 0e4h		; ld a,l; cp 0E4h
		ZJR	20h, .err
		db	2ah, 10h, 7fh		; ld hl,(7F10h)
		db	23h			; inc hl
		db	22h, 10h, 7fh		; ld (7F10h),hl
		ZJR	18h, .loop
.err:		db	3eh, 01h		; ld a,1
		db	32h, 12h, 7fh		; ld (7F12h),a
.eloop:		db	0edh, 0edh, VEC_YIELD	; calln VEC_YIELD
		ZJR	18h, .eloop
z_sw_b_end:

; Context A of the preempt probe (main segment, 7200h): spins with
; interrupts enabled, counting at 7F20h; checks the carry set just before
; and IX; sets 7F22h on a mismatch.
z_pre_a:	db	31h, 00h, 0fdh		; ld sp,0FD00h
		db	0ddh, 21h, 34h, 12h	; ld ix,1234h
		db	21h, 00h, 00h		; ld hl,0
		db	0fbh			; ei
.loop:		db	37h			; scf
		db	23h			; inc hl
		ZJR	30h, .err		; jr nc,err
		db	22h, 20h, 7fh		; ld (7F20h),hl
		db	0ddh, 0e5h, 0d1h	; push ix; pop de
		db	7ah, 0feh, 12h		; ld a,d; cp 12h
		ZJR	20h, .err
		db	7bh, 0feh, 34h		; ld a,e; cp 34h
		ZJR	20h, .err
		ZJR	18h, .loop
.err:		db	3eh, 01h		; ld a,1
		db	32h, 22h, 7fh		; ld (7F22h),a
.eloop:		ZJR	18h, .eloop
z_pre_a_end:

z_pre_b:	db	31h, 00h, 0fdh		; ld sp,0FD00h
		db	0ddh, 21h, 78h, 56h	; ld ix,5678h
		db	21h, 00h, 00h		; ld hl,0
		db	0fbh			; ei
.loop:		db	37h			; scf
		db	23h			; inc hl
		ZJR	30h, .err		; jr nc,err
		db	22h, 20h, 7fh		; ld (7F20h),hl
		db	0ddh, 0e5h, 0d1h	; push ix; pop de
		db	7ah, 0feh, 56h		; ld a,d; cp 56h
		ZJR	20h, .err
		db	7bh, 0feh, 78h		; ld a,e; cp 78h
		ZJR	20h, .err
		ZJR	18h, .loop
.err:		db	3eh, 01h		; ld a,1
		db	32h, 22h, 7fh		; ld (7F22h),a
.eloop:		ZJR	18h, .eloop
z_pre_b_end:

; Speed loops: INC HL; LD (7F20h),HL (34 T-states with the JR), plus
; PUSH IX; POP DE (25), or LD A,(IX+0) (19).
z_spd1:		db	31h, 00h, 0fdh, 21h, 00h, 00h, 0fbh	; ld sp; ld hl,0; ei
.loop:		db	23h, 22h, 20h, 7fh	; inc hl; ld (7F20h),hl
		ZJR	18h, .loop
z_spd1_end:
z_spd2:		db	31h, 00h, 0fdh, 21h, 00h, 00h, 0fbh
.loop:		db	23h, 22h, 20h, 7fh
		db	0ddh, 0e5h, 0d1h	; push ix; pop de
		ZJR	18h, .loop
z_spd2_end:
z_spd3:		db	31h, 00h, 0fdh, 21h, 00h, 00h, 0fbh
.loop:		db	23h, 22h, 20h, 7fh
		db	0ddh, 7eh, 00h		; ld a,(ix+0)
		ZJR	18h, .loop
z_spd3_end:

; P/V after LDI: E = F with BC 2 -> 1, L = F with BC 1 -> 0
z_ldi:		db	31h, 00h, 0feh		; ld sp,0FE00h
		db	21h, 30h, 7fh		; ld hl,7F30h
		db	11h, 38h, 7fh		; ld de,7F38h
		db	01h, 02h, 00h		; ld bc,2
		db	0afh			; xor a
		db	0edh, 0a0h		; ldi
		db	0f5h			; push af
		db	0edh, 0a0h		; ldi
		db	0f5h			; push af
		db	0e1h			; pop hl
		db	0d1h			; pop de
		db	0edh, 0fdh		; retem
z_ldi_end:

%endif
; ---------------------------------------------------------------------------
; Data

s_title		db	'pc88va-dd M01 feasibility test', 13, 10, 0
s_menu		db	13, 10
		db	'1  compatible-mode probes for the switching method', 13, 10
		db	'2  the game: three programs, tile RAM as text (keys)', 13, 10
		db	'3  the game with an automatic coin, start and moves', 13, 10
		db	13, 10, 'Keys: 8 6 2 4 or cursor, SPACE fire, 5 coin, 1 start,'
		db	' ESC restarts.', 13, 10, 0
s_probes	db	'Probes. One that never finishes hangs on its line.', 13, 10
		db	13, 10, 0
s_calln		db	'calln    ', 0
s_switch	db	'switch   ', 0
s_preempt	db	'preempt  ', 0
s_ldi		db	'ldi-pv   ', 0
s_speed		db	'speed    10 frames: plain, push ix, ld a,(ix) = ', 0
s_pass		db	'PASS ', 0
s_fail		db	'FAIL ', 0
s_psw		db	' PSW=', 0
s_bp		db	' SP=', 0
s_f		db	' F=', 0
s_counts	db	' counts=', 0
s_errors	db	' errors=', 0
s_vrtcs		db	' VRTCs=', 0
s_done		db	13, 10, 'Done. Press a key for the menu.', 13, 10, 0
s_starting	db	'Starting...', 13, 10, 0
s_frames	db	'F=', 0
s_late		db	' late=', 0
s_lost		db	' lost=', 0
s_vt		db	' view=', 0
s_load		db	' load=', 0
s_idle		db	' idle=', 0
s_io		db	' 06xx=', 0
s_credits	db	' cr/mode=', 0
s_cpus		db	'MN ', 0, 'SB ', 0, 'SD ', 0
s_yields	db	' yield=', 0
s_preempts	db	' preempt=', 0
s_pc		db	' PC=', 0
s_ready		db	' run=', 0
s_crlf		db	13, 10, 0

; Tile code -> character: 10h-19h digits, 1Ah-33h letters, 7Fh blank,
; other codes below 80h '.', the rest '#'.
charmap:
%assign c 0
%rep 256
 %if c >= 10h && c <= 19h
		db	c - 10h + '0'
 %elif c >= 1ah && c <= 33h
		db	c - 1ah + 'A'
 %elif c == 7fh
		db	' '
 %elif c < 80h
		db	'.'
 %else
		db	'#'
 %endif
 %assign c c + 1
%endrep

		align	2
old_vrtc	dd	0
%ifdef TEST_ROUND
start_round	db	TEST_ROUND	; 0: off (kept across restarts)
%else
start_round	db	0
%endif
tick		dw	0
cur_ctx		dw	0
sched_sp	dw	SCHED_TOP
yield_entry	dw	0
preempt_entry	dw	0
probe_sched	dw	0
brkem_sp	dw	0
rounds		dw	0
pc_ax		dw	0
pc_bx		dw	0
pc_cx		dw	0
pc_dx		dw	0
pc_si		dw	0
pc_di		dw	0
pc_bp		dw	0
pc_psw		dw	0
r_ax		dw	0
r_bx		dw	0
r_cx		dw	0
r_dx		dw	0
r_ix		dw	0
r_iy		dw	0
r_sp		dw	0
r_ticks		dw	0
old_mask	db	0
old_mask_ir2	db	0
chain		db	0
vrtc_mode	db	0
auto		db	0
		align	2
ctx_a		times	C_SIZE db 0
ctx_b		times	C_SIZE db 0

; Game state, cleared at the start
gstate:
ctx_main	times	C_SIZE db 0
ctx_sub		times	C_SIZE db 0
ctx_sound	times	C_SIZE db 0
ctx_boot	times	C_SIZE db 0
frames		dw	0
seen		dw	0
late_frames	dw	0
idle_count	dw	0
idle_sum	dd	0
idle_calib	dw	0
io_transfers	dw	0
io_queue	dw	0
yields		times	3 dw 0
preempts	times	3 dw 0
ready		times	4 db 0
done		times	4 db 0
pend		times	4 db 0
cur		db	0
first		db	0
preempted	db	0
view_count	db	0
view_due	db	0
keys		db	0
keys_new	db	0
fire_prev	db	0
io_active	db	0
io_ctrl		db	0
io_n		db	0
m51_mode	db	0
m51_remap	db	0
m51_args	db	0
m51_credits	db	0
m51_index	db	0
m53_index	db	0
to_buf		db	0
flush_at	db	0
skip_stats	db	0
view_ticks	db	0
		align	2
buf_pos		dw	0
view_start	dw	0
seen_prev	dw	0
key_latch	db	0
vrtcs_elapsed	dw	0
lost_frames	dw	0
idle_n		dw	0
%ifndef LIVE_VIDEO
scr		times	(VIEW_ROWS + 1) * 80 db 0
shown		times	(VIEW_ROWS + 1) * 80 db 0
%endif
gstate_end:

%ifdef LIVE_VIDEO
%ifdef RECT_SPRITES
%define TRIPLE_FRONTS 1          ; three sprite fronts (native_planes.inc)
%endif
%include "live_video.inc"
%include "native.inc"
%include "native_planes.inc"
%ifdef BACKGROUND_CACHE
%include "../m03/background_cache.inc"
%endif
%include "../m03/install.inc"
%include "../m03/align.inc"
%ifdef SERVICE_MENU
%include "../m03/service.inc"
%include "../m03/diag.inc"
%endif
%ifdef M03_AUDIO
%ifdef NATIVE_SOUND
%include "../m03/sound_driver.inc"
%include "../m03/sound_native.inc"
%endif
%include "../m03/sound_ssg.inc"
%ifdef M03_FM
%include "../m03/sound_fm.inc"
%endif
%endif
%endif

end_of_program:
		times	CODE_BYTES - ($ - $$) db 0	; fails if the program is too large
