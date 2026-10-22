; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; M03-A: three native SSG square tones, not wavetable timbre emulation.
; WSG waveform rate = 96000*F/2^20. YM2203 SSG tone = 3993600/(32*TP)
; (vaeg's np2 and ymfm; prescaler set by register 2Dh below).
; TP=floor(1363148/F), clamped to 1..4095. No floating point or assets.
m03_sound_init:
        mov al,2dh
        xor ah,ah
        call m03_opn_write
        mov al,7
        call m03_opn_wait
        jc .failed
        out 44h,al
        call m03_opn_wait
        jc .failed
        in al,45h
        and al,0c0h              ; preserve port A/B direction, never write data
        or al,38h                ; tones on, noise off
        mov ah,al
        mov al,7
        call m03_opn_write
        mov bx,8
.off:   mov ax,bx
        xor ah,ah
        call m03_opn_write
        inc bx
        cmp bx,11
        jb .off
        xor bx,bx
.fm_off:
        mov al,28h
        mov ah,bl
        call m03_opn_write
        inc bx
        cmp bx,3
        jb .fm_off
%ifdef M03_FM
        call m03_fm_init
%endif
        ret
.failed:
        mov byte [m03_error],1
.done:  ret

; Preserve every CPU/context register at the sound-program yield boundary.
m03_sound_update:
        pusha
        push ds
        push es
        mov word [cs:m03_writes],0
        cmp byte [cs:m03_error],0
        jne .done
        mov ax,ZSEG
        mov ds,ax
        push cs
        pop es
        cmp byte [cs:m03_force],0
        jne .changed
        mov si,6800h
        mov di,m03_raw
        mov cx,16
        repe cmpsw
        jne .changed
        inc word [cs:m03_updates]
        jmp .done                ; same request: no pitch work or register writes
.changed:
        mov al,[cs:m03_force]     ; forced: every voice, else changed ones
        mov [cs:m03_all],al
        mov byte [cs:m03_force],0
        push ds
        push cs
        pop ds
        mov si,m03_raw
        mov di,m03_prev
        mov cx,16
        rep movsw
        pop ds
        mov si,6800h
        mov di,m03_raw
        mov cx,16
        rep movsw
        push cs
        pop ds
        mov word [m03_voice],0
.voice: cmp byte [m03_all],0
        jne .process
        mov bx,[m03_voice]        ; skip a voice whose registers are as before
        mov si,[m03_voice_start+bx]
        mov di,si
        add si,m03_raw
        add di,m03_prev
        mov cx,[m03_voice_length+bx]
        repe cmpsb
        jne .process
        mov si,[m03_voice_wave+bx]
        mov al,[m03_raw+si]
        cmp al,[m03_prev+si]
        jne .process
        jmp .next
.process:
        mov bx,[m03_voice]
        mov si,[m03_frequency_ends+bx]
        mov cx,4
        cmp bx,0
        jne .nibbles
        inc cx
.nibbles:
        xor ax,ax
        xor dx,dx
.nibble:
        shl ax,1
        rcl dx,1
        shl ax,1
        rcl dx,1
        shl ax,1
        rcl dx,1
        shl ax,1
        rcl dx,1
        xor bx,bx
        mov bl,[si]
        and bl,15
        or ax,bx
        dec si
        loop .nibble
        cmp word [m03_voice],0
        je .frequency
        shl ax,1
        rcl dx,1
        shl ax,1
        rcl dx,1
        shl ax,1
        rcl dx,1
        shl ax,1
        rcl dx,1
.frequency:
        mov [m03_f_low],ax
        mov [m03_f_high],dx
        mov bx,[m03_voice]
        mov si,[m03_frequency_ends+bx]
        mov bl,[si+1]
        and bx,15
%ifdef M03_FM
        cmp byte [m03_use_fm],0
        je .ssg_voice
        mov cl,bl
        call m03_fm_voice
        jmp .next
.ssg_voice:
%endif
        mov cl,[m03_volume+bx]
        mov [m03_level],cl
        mov bx,ax
        or bx,dx
        jnz .nonzero
        mov byte [m03_level],0
        jmp .level
.nonzero:
        cmp cl,0
        je .level
        call m03_period
        mov bx,[m03_voice]
        cmp ax,[m03_periods+bx]
        je .level
        mov [m03_periods+bx],ax
        mov dx,ax
        mov ah,al
        mov al,bl
        call m03_opn_write
        mov ax,dx
        mov al,bl
        inc al
        call m03_opn_write
.level: mov bx,[m03_voice]
        shr bx,1
        mov ah,[m03_level]
        cmp ah,[m03_levels+bx]
        je .next
        mov [m03_levels+bx],ah
        mov al,bl
        add al,8
        call m03_opn_write
.next:  add word [m03_voice],2
        cmp word [m03_voice],6
        jb .voice
        inc word [m03_updates]
.done:  pop es
        pop ds
        popa
        ret

; Silence every voice, forget what was written and force the next update
; to write everything again (backend switch, pause, restart).
m03_silence:
        pusha
        push es
        mov al,8
.level: xor ah,ah
        call m03_opn_write
        inc al
        cmp al,11
        jb .level
        xor bx,bx
.key:   mov al,28h
        mov ah,bl
        call m03_opn_write
        inc bx
        cmp bx,3
        jb .key
        push cs
        pop es
        mov di,m03_periods
        mov ax,0ffffh
        mov cx,3
        rep stosw
        mov di,m03_levels
        xor al,al
        mov cx,3
        rep stosb
%ifdef M03_FM
        mov di,m03_fm_periods
        mov ax,0ffffh
        mov cx,3
        rep stosw
        mov di,m03_fm_profiles
        mov cx,6
        rep stosb                ; profiles and volumes: FFh
        mov di,m03_fm_keys
        xor al,al
        mov cx,3
        rep stosb
%endif
        mov byte [cs:m03_force],1
        pop es
        popa
        ret

; Exact division for all 20-bit frequencies. For F>=65536, the quotient
; is at most ten: subtract 20-bit F from K. Smaller F uses a safe DIV.
m03_period:
        or dx,dx
        jnz .wide
        cmp ax,333
        jb .max
        mov bx,ax
        mov dx,14h               ; 1363148
        mov ax,0cccch
        div bx
        ret
.max:   mov ax,0fffh
        ret
.wide:  xor cx,cx
        mov dx,14h
        mov ax,0cccch
.loop:  cmp dx,[m03_f_high]
        jb .quotient
        ja .subtract
        cmp ax,[m03_f_low]
        jb .quotient
.subtract:
        sub ax,[m03_f_low]
        sbb dx,[m03_f_high]
        inc cx
        jmp .loop
.quotient:
        mov ax,cx
        or ax,ax
        jnz .done
        inc ax
.done:  ret

; AL=register, AH=data. Bounded busy checks; timeout disables further audio.
; Preserve the caller's AX/DX. CF reports a busy timeout. No unbounded I/O loop.
m03_opn_write:
        push ax
        push dx
        cmp byte [cs:m03_error],0
        jne .failed
        call m03_opn_wait
        jc .failed
        out 44h,al
        xchg al,ah
        call m03_opn_wait
        jc .failed
        out 45h,al
        inc word [cs:m03_writes]
        xchg al,ah
        push bx
        xor bx,bx
        mov bl,al
        mov [cs:m03_registers+bx],ah
        pop bx
.ready: clc
        jmp .return
.failed:
        mov byte [cs:m03_error],1
.return:
        pop dx
        pop ax
        ret
m03_opn_wait:
        push ax
        push cx
        mov cx,4096
.poll:  in al,44h
        test al,80h
        jz .ready
        loop .poll
        stc
        jmp .done
.ready: clc
.done:  pop cx
        pop ax
        ret
m03_frequency_ends dw m03_raw+14h,m03_raw+19h,m03_raw+1eh
; Each voice's frequency and volume registers, and its waveform register.
m03_voice_start dw 10h,16h,1bh
m03_voice_length dw 6,5,5
m03_voice_wave dw 5,0ah,0fh
m03_voice dw 0
m03_f_low dw 0
m03_f_high dw 0
m03_level db 0
m03_periods times 3 dw 0ffffh
m03_levels times 3 db 0
m03_raw times 32 db 0
m03_prev times 32 db 0
m03_all db 0
m03_registers times 256 db 0
m03_error db 0
m03_updates dw 0
m03_writes dw 0
m03_force db 0
m03_nmi_delivered dw 0
m03_nmi_dropped dw 0
; Approximate linear WSG amplitude using logarithmic SSG levels.
m03_volume db 0,6,8,9,10,11,11,12,12,13,13,13,14,14,15,15
