; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; F10 service screen: DIP switches, sound backend and sound test.
;
; F10 pauses the game: the main and sub programs get no time and no
; interrupts. Cursor keys or keypad 8 2 choose an item, 4 6 change it,
; RETURN or SPACE plays the selected sound, F10 returns. A changed DIP
; setting restarts the programs as a power cycle would (they read the
; switches at their start); settings are not saved.
;
; The screen is drawn by the native renderer from a made-up video state
; (blank background bank, the game's own font, no sprites), in the game's
; orientation. The sound test clears the 32 request flags at 9A80h, sets
; the selected one, and lets only the sound program run. In attract mode
; the sound program drops requests while 8657h is nonzero (measured on the
; reference emulator), so the test clears it and the screen restores it.
; Requests 0-18 and 20 sound; the others did not and are not offered.

K2_F10	equ 01h
K2_SOUND	equ 02h
K2_F9	equ 04h	; load display (diag.inc)
SVC_ITEMS	equ 11
SVC_SOUND	equ 7
SVC_TEST	equ 8
SVC_REPEAT_DELAY equ 20	; held direction: repeats after 20 frames,
SVC_REPEAT_RATE equ 2	; then every 2 (a power of two)
SVC_ROUND	equ 9	; debug: rounds start at N (start_round, m01test.asm)
SVC_FPS	equ 10	; drawing every frame (60, default) or every second frame (30)
SVC_ENTRY	equ 5	; switch bank, shift, mask, values table
SVC_TESTS	equ 32	; request flags saved and cleared
SVC_SOUNDS	equ 20	; sounds offered by the test
SVC_GATE	equ 8657h
SVC_REQUESTS	equ 9a80h
SVC_LABEL_X	equ 1
SVC_VALUE_X	equ 11
SVC_FIRST_Y	equ 5

; AL = the game's keys (K_*). Returns the keys the game may see: none
; while the screen is open (DS = ES = CS).
service_frame:
		push bx
		push cx
		push dx
		push si
		push di
		mov [svc_game_keys],al
		call scan_service	; AL = K2_*, AH = test-only directions
		or ax,[svc_latch]	; and what the VRTC handler saw since
		mov word [svc_latch],0
		or ah,[svc_game_keys]
		mov bx,ax
		mov cx,[svc_prev]
		mov [svc_prev],ax
		not cx
		and bx,cx
		mov [svc_new],bx	; newly pressed: low K2_*, high K_*
		test bl,K2_F9
		jz .diag
		call diag_toggle
.diag:	call diag_tick
		mov ax,[svc_prev]	; (diag_tick used AX and BX)
		mov bx,[svc_new]
		cmp byte [svc_on],0
		je .closed
		; Auto-repeat of a held direction on the open screen: after
		; SVC_REPEAT_DELAY frames, every SVC_REPEAT_RATE frames.
		and ah,K_UP | K_DOWN | K_LEFT | K_RIGHT
		jz .no_repeat
		cmp ah,[svc_rep_keys]
		jne .no_repeat
		inc word [svc_rep_count]
		mov cx,[svc_rep_count]
		sub cx,SVC_REPEAT_DELAY
		jb .open
		test cx,SVC_REPEAT_RATE - 1
		jnz .open
		or [svc_new + 1],ah
		jmp .open
.no_repeat:
		mov [svc_rep_keys],ah
		mov word [svc_rep_count],0
		jmp .open
.closed:
		test bl,K2_F10
		jz .game
		call service_open
		jmp .hide
.game:	mov al,[svc_game_keys]
		jmp .done
.open:	call service_keys
		cmp byte [svc_on],0
		je .hide	; just closed: no stale key this frame
		call service_test_step
.hide:	xor al,al
.done:	pop di
		pop si
		pop dx
		pop cx
		pop bx
		ret

; AL = K2_* held. AH = directions from test keys (TEST_KEYS only).
scan_service:
		push dx
		xor dx,dx
		in al,0dh	; F10: port 0Dh bit 4 (manual),
		test al,10h	; port 0Ch bit 4 (vaeg)
		jz .f10
		in al,0ch
		test al,10h
		jnz .ret_key
.f10:	or dl,K2_F10
.ret_key:
		in al,0dh	; F9: port 0Dh bit 3 (manual),
		test al,08h	; port 0Ch bit 3 (vaeg)
		jz .f9
		in al,0ch
		test al,08h
		jnz .no_f9
.f9:	or dl,K2_F9
.no_f9:
		in al,01h	; RETURN: keypad (bit 7)
		test al,80h
		jz .play
		in al,0eh	; or main (bits 0-1)
		and al,03h
		cmp al,03h
		je .test
.play:	or dl,K2_SOUND
.test:
%ifdef TEST_KEYS
		; vaeg tests type these through the debug script's input-line:
		; M = F10, P = play, U D L R = directions
		in al,03h
		test al,20h	; M
		jnz .t_l
		or dl,K2_F10
.t_l:	test al,10h	; L
		jnz .t_p
		or dh,K_LEFT
.t_p:	in al,04h
		test al,01h	; P
		jnz .t_r
		or dl,K2_SOUND
.t_r:	test al,04h	; R
		jnz .t_u
		or dh,K_RIGHT
.t_u:	test al,20h	; U
		jnz .t_d
		or dh,K_UP
.t_d:	in al,02h
		test al,10h	; D
		jnz .t_end
		or dh,K_DOWN
.t_end:
%endif
		mov ax,dx
		pop dx
		ret

service_open:
		mov byte [svc_on],1
		mov byte [svc_sel],0
		mov byte [svc_test_on],0
		mov byte [svc_dirty],1
		mov ax,[dsw]
		mov [svc_dsw],ax
		push ds
		mov ax,ZSEG	; keep the game's sound requests
		mov ds,ax
		mov si,SVC_REQUESTS
		mov di,svc_saved
		mov cx,SVC_TESTS / 2
		rep movsw
		mov al,[SVC_GATE]
		mov [cs:svc_saved_gate],al
		pop ds
%ifdef M03_AUDIO
		call m03_silence
%endif
		ret

service_close:
		mov byte [svc_on],0
		mov byte [svc_test_on],0
		push es
		mov ax,ZSEG
		mov es,ax
		mov di,SVC_REQUESTS
		mov si,svc_saved
		mov cx,SVC_TESTS / 2
		rep movsw
		mov al,[svc_saved_gate]
		mov [es:SVC_GATE],al
		pop es
%ifdef M03_AUDIO
		call m03_silence
%endif
		mov ax,[svc_dsw]
		cmp ax,[dsw]
		je .same
		mov [dsw],ax
		call service_restart
.same:	ret

; Keys [svc_new] on the open screen.
service_keys:
		mov bx,[svc_new]
		test bl,K2_F10
		jz .move
		jmp service_close
.move:	mov al,[svc_sel]
		test bh,K_UP
		jz .down
		dec al
		jns .down
		mov al,SVC_ITEMS - 1
.down:	test bh,K_DOWN
		jz .sel
		inc al
		cmp al,SVC_ITEMS
		jb .sel
		xor al,al
.sel:	cmp al,[svc_sel]
		je .item
		mov [svc_sel],al
		mov byte [svc_dirty],1
.item:	xor ah,ah
		mov si,ax
		cmp si,SVC_ROUND
		jne .not_round
		test word [svc_new],(K_FIRE << 8) | K2_SOUND
		jz .change
		add byte [start_round],10
		mov byte [svc_dirty],1
		jmp .change
.not_round:
		cmp si,SVC_TEST
		jne .change
		test word [svc_new],(K_FIRE << 8) | K2_SOUND
		jz .change
		call service_test_start
.change:
		test byte [svc_new + 1],K_LEFT | K_RIGHT
		jz .ret
		mov byte [svc_dirty],1
		cmp si,SVC_SOUND
		je .sound
		cmp si,SVC_TEST
		je .test
		cmp si,SVC_ROUND
		je .round
		cmp si,SVC_FPS
		je .fps
		imul si,si,SVC_ENTRY
		add si,svc_items
		xor bx,bx
		mov bl,[si]	; switch bank: 0 A, 1 B
		mov cl,[si + 1]	; shift
		mov dl,[si + 2]	; mask (values - 1)
		mov dh,[svc_dsw + bx]
		mov al,dh
		shr al,cl
		and al,dl
		test byte [svc_new + 1],K_RIGHT
		jz .left
		inc al
		jmp .wrap
.left:	dec al
.wrap:	and al,dl
		shl dl,cl	; replace the field
		not dl
		and dh,dl
		shl al,cl
		or dh,al
		mov [svc_dsw + bx],dh
.ret:	ret
.sound:
%ifdef M03_FM
		cmp byte [m03_fm_ready],0
		je .ret
		xor byte [m03_use_fm],1
		call m03_silence
%endif
		ret
.fps:	mov ax,1		; 60 (every frame) <-> 30
		cmp word [live_render_period],ax
		jne .fset
		inc ax
.fset:	mov [live_render_period],ax
		ret
.round: mov al,1
		test byte [svc_new + 1],K_RIGHT
		jnz .radd
		neg al
.radd:	add [start_round],al
		ret
.test:	mov al,[svc_test_sel]
		test byte [svc_new + 1],K_RIGHT
		jz .tleft
		inc al
		cmp al,SVC_SOUNDS
		jb .tset
		xor al,al
		jmp .tset
.tleft: dec al
		jns .tset
		mov al,SVC_SOUNDS - 1
.tset:	mov [svc_test_sel],al
		jmp service_test_start

service_test_start:
		mov byte [svc_test_on],1
		mov byte [svc_test_phase],0
		ret

; Phase 0 clears every request (the program stops its sounds), phase 1
; sets the selected one; then the program plays it.
service_test_step:
		cmp byte [svc_test_on],0
		je .ret
		cmp byte [svc_test_phase],1
		ja .ret
		push es
		mov ax,ZSEG
		mov es,ax
		je .set
		mov di,SVC_REQUESTS
		xor ax,ax
		mov cx,SVC_TESTS / 2
		rep stosw
		mov byte [es:SVC_GATE],0
		pop es
%ifdef M03_AUDIO
		call m03_silence
%endif
		inc byte [svc_test_phase]
.ret:	ret
.set:	xor bx,bx
		mov bl,[svc_test_sel]
		mov bl,[svc_test_flags + bx]
		mov byte [es:SVC_REQUESTS + bx],1
		pop es
		inc byte [svc_test_phase]
		ret

; After the round's state is reset: hold the programs while the screen is
; open; only the sound program runs, and only for the sound test.
service_hold:
		cmp byte [svc_on],0
		je .ret
		mov word [done],0101h
		mov word [pend],0
		cmp byte [svc_test_on],0
		je .silent
		cmp byte [ready + 2],0
		je .silent
		mov byte [pend + 2],2
.ret:	ret
.silent:
		mov byte [done + 2],1
		mov byte [pend + 2],0
		ret

; Power-cycle the programs with the new switches: Z80 RAM cleared as at
; the first start, the custom I/O state reset, the main program at 0000h,
; sub and sound held in reset until the main program releases them.
service_restart:
%ifdef M03_AUDIO
		call m03_silence
%endif
%ifdef NATIVE_SOUND
		mov byte [sd_state],SD_OFF	; until main releases the reset again
%endif
		push es
		xor ax,ax
		mov bx,ZSEG
		mov es,bx
		mov di,MAIN_SEGMENT_BYTES
		mov cx,(10000h - MAIN_SEGMENT_BYTES) / 2
		rep stosw
		mov bx,SSEG
		mov es,bx
		mov di,SOUND_SEGMENT_BYTES
		mov cx,(10000h - SOUND_SEGMENT_BYTES) / 2
		rep stosw
		pop es
		mov byte [io_active],0
		mov byte [io_ctrl],0
		mov byte [io_n],0
		mov byte [m51_mode],0
		mov byte [m51_args],0
		mov byte [m51_credits],0
		mov byte [m51_index],0
		mov byte [m53_index],0
		mov byte [m51_remap],1
		mov word [io_queue],0
		mov byte [keys],0
		mov byte [keys_new],0
		mov byte [fire_prev],0
		mov bx,ctx_main
		xor ax,ax
		mov dx,ZSEG
		mov cx,0002h
		call ctx_init
		mov byte [ready],1
		mov word [ready + 1],0
		mov word [pend],0
		mov byte [pend + 2],0
		mov word [done],0
		mov byte [done + 2],0
		mov byte [preempted],0ffh
		ret

; Write the screen's video state into N_VRAM.. when it changed (DS = ES = CS).
service_build:
		cmp byte [svc_dirty],0
		je .ret
		mov byte [svc_dirty],0
		mov di,N_VRAM
		mov al,7fh	; the font's blank
		mov cx,1024
		rep stosb
		xor al,al	; no sprites (Y 0 is above the screen)
		mov di,N_OBJECT
		mov cx,128
		rep stosb
		mov di,N_POSITION
		mov cx,128
		rep stosb
		mov di,N_FLIP
		mov cx,128
		rep stosb
		mov di,N_LATCH
		mov cx,8
		rep stosb
		mov byte [N_LATCH + 3],1	; background forced blank
		mov si,svc_fixed	; (gx, gy, attribute, text, 0)
.fixed: lodsb
		cmp al,0ffh
		je .items
		mov dl,al
		lodsb
		mov dh,al
		lodsb
		mov ah,al
		call svc_text
		jmp .fixed
.items: xor bx,bx
.item:	xor ah,ah
		cmp bl,[svc_sel]
		jne .attr
		mov ah,80h
.attr:	mov [svc_attr],ah
		mov dh,bl
		shl dh,1
		add dh,SVC_FIRST_Y
		mov si,bx
		shl si,1
		mov si,[svc_labels + si]
		mov dl,SVC_LABEL_X
		call svc_text
		call svc_value
		mov dl,SVC_VALUE_X
		mov ah,[svc_attr]
		call svc_text
		inc bx
		cmp bx,SVC_ITEMS
		jb .item
.ret:	ret

; SI = the value text of item BX.
svc_value:
		cmp bx,SVC_SOUND
		je .sound
		cmp bx,SVC_TEST
		je .test
		cmp bx,SVC_ROUND
		je .round
		cmp bx,SVC_FPS
		je .fps
		push bx
		imul si,bx,SVC_ENTRY
		add si,svc_items
		xor bx,bx
		mov bl,[si]
		mov al,[svc_dsw + bx]
		mov cl,[si + 1]
		shr al,cl
		and al,[si + 2]
		xor ah,ah
		shl ax,1
		mov bx,[si + 3]
		cmp bx,v_bonus	; with 5 lives the bonus table differs
		jne .table
		mov cl,[svc_dsw]
		and cl,0c0h
		cmp cl,0c0h
		jne .table
		mov bx,v_bonus5
.table: add bx,ax
		mov si,[bx]
		pop bx
		ret
.sound: mov si,s_ssg
%ifdef M03_FM
		cmp byte [m03_use_fm],0
		je .s
		mov si,s_fm_quick
		cmp byte [m03_fm_fit],0
		je .s
		mov si,s_fm_fit
.s:
%elifndef M03_AUDIO
		mov si,s_off
%endif
		ret
.fps:	mov si,s_fps30
		cmp word [live_render_period],1
		jne .f
		mov si,s_fps60
.f:		ret
.round: mov si,s_off
		mov al,[start_round]
		or al,al
		jz .r
		mov si,svc_round_text + 3	; decimal, right to left
.digit: xor ah,ah
		mov cl,10
		div cl
		add ah,'0'
		dec si
		mov [si],ah
		or al,al
		jnz .digit
.r:		ret
.test:	mov al,[svc_test_sel]
		inc al	; SOUND 01..20
		aam
		add ax,3030h
		mov [svc_number + 6],ah
		mov [svc_number + 7],al
		mov si,svc_number
		ret

; Text DS:SI (upper case, digits, spaces; ended by 0) at game column DL
; (0-27, left to right), game row DH (0-35, top to bottom), attribute AH
; (80h: the second colour). Board raster row = 27 - gx, column = gy.
; Leaves SI after the text.
svc_text:
		push ax
		push bx
		push cx
		push di
		mov bh,ah
.ch:	lodsb
		or al,al
		jz .done
		cmp al,' '
		je .blank
		cmp al,'9'
		ja .alpha
		sub al,'0' - 10h
		jmp .attr
.alpha: sub al,'A' - 1ah
.attr:	or al,bh
		jmp .put
.blank: mov al,7fh
.put:	mov cl,al
		mov al,27
		sub al,dl
		mov ch,36
		mul ch
		add al,dh
		adc ah,0
		shl ax,1
		mov di,ax
		mov di,[N_INDEX + di]
		mov [N_VRAM + di],cl
		inc dl
		jmp .ch
.done:	pop di
		pop cx
		pop bx
		pop ax
		ret

svc_on	db 0
svc_sel	db 0
svc_dirty	db 0
svc_attr	db 0
svc_game_keys	db 0
svc_test_on	db 0
svc_test_phase	db 0
svc_test_sel	db 0
		align 2
svc_prev	dw 0
svc_latch	dw 0
svc_new	dw 0
svc_rep_count	dw 0
svc_rep_keys	db 0
		align 2
svc_dsw	dw 0
svc_saved	times SVC_TESTS db 0
svc_saved_gate	db 0
svc_test_flags	db 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20
svc_number	db 'SOUND 01', 0
svc_round_text	db '000', 0

svc_items:	db 1, 6, 3
		dw v_coin_a
		db 0, 0, 7
		dw v_coin_b
		db 0, 6, 3
		dw v_lives
		db 0, 3, 7
		dw v_bonus
		db 1, 0, 3
		dw v_level
		db 1, 3, 1
		dw v_continue
		db 1, 4, 1
		dw v_demo
svc_labels	dw t_coin_a, t_coin_b, t_lives, t_bonus, t_level
		dw t_continue, t_demo, t_sound, t_test, t_round, t_fps

v_coin_a	dw s_1c1c, s_2c1c, s_1c2c, s_2c3c
v_coin_b	dw s_1c7c, s_1c1c, s_1c3c, s_2c1c, s_1c6c, s_2c3c, s_1c2c, s_3c1c
v_lives	dw s_1, s_2, s_3, s_5
v_bonus	dw s_none, s_b1, s_b2, s_b3, s_b4, s_b5, s_b6, s_b7
v_bonus5	dw s_none, s_c1, s_c2, s_c3, s_c4, s_c5, s_c6, s_c7
v_level	dw s_easy, s_hard, s_medium, s_hardest
v_continue	dw s_yes, s_no
v_demo	dw s_on, s_off

t_coin_a	db 'COIN A', 0
t_coin_b	db 'COIN B', 0
t_lives	db 'LIVES', 0
t_bonus	db 'BONUS', 0
t_level	db 'LEVEL', 0
t_continue	db 'CONTINUE', 0
t_demo	db 'DEMO SND', 0
t_sound	db 'SOUND', 0
t_test	db 'TEST', 0
t_round	db 'ROUND', 0
t_fps	db 'FPS', 0
s_fps30	db '30', 0
s_fps60	db '60', 0
s_1c1c	db '1 COIN 1 CREDIT', 0
s_2c1c	db '2 COINS 1 CREDIT', 0
s_1c2c	db '1 COIN 2 CREDITS', 0
s_2c3c	db '2 COINS 3 CREDITS', 0
s_1c3c	db '1 COIN 3 CREDITS', 0
s_1c6c	db '1 COIN 6 CREDITS', 0
s_1c7c	db '1 COIN 7 CREDITS', 0
s_3c1c	db '3 COINS 1 CREDIT', 0
s_1	db '1', 0
s_2	db '2', 0
s_3	db '3', 0
s_5	db '5', 0
s_none	db 'NONE', 0
s_b1	db '20K 70K EVERY 70K', 0
s_b2	db '10K 50K EVERY 50K', 0
s_b3	db '20K 60K', 0
s_b4	db '10K 40K EVERY 40K', 0
s_b5	db '10K 40K', 0
s_b6	db '20K 60K EVERY 60K', 0
s_b7	db '10K', 0
s_c1	db '20K 60K', 0
s_c2	db '30K 80K EVERY 80K', 0
s_c3	db '20K', 0
s_c4	db '20K 60K EVERY 60K', 0
s_c5	db '30K 70K', 0
s_c6	db '20K 50K', 0
s_c7	db '30K', 0
s_easy	db 'EASY', 0
s_medium	db 'MEDIUM', 0
s_hard	db 'HARD', 0
s_hardest	db 'HARDEST', 0
s_yes	db 'YES', 0
s_no	db 'NO', 0
s_on	db 'ON', 0
s_off	db 'OFF', 0
s_ssg	db 'SSG', 0
s_fm_quick	db 'FM QUICK', 0
s_fm_fit	db 'FM FIT', 0

svc_fixed:	db 8, 3, 80h, 'SERVICE MODE', 0
		db 1, 27, 0, 'UP DOWN     SELECT', 0
		db 1, 29, 0, 'LEFT RIGHT  CHANGE', 0
		db 1, 31, 0, 'RETURN      PLAY OR ADD 10', 0
		db 1, 33, 0, 'F10         BACK TO GAME', 0
		db 1, 35, 0, 'DIP CHANGES RESTART', 0
		db 0ffh
