; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; G0: two packed-4bpp front pages in lower 128 KiB. G1: background in
; upper 128 KiB. Palette mode 2 gives each screen a separate 16-colour bank.
two_planes:
        mov ax,0a8c0h
        mov es,ax
        xor di,di
        mov si,T_FRONT_B
        call two_unpack
        mov ax,0c000h
        mov es,ax
        xor di,di
        mov si,T_BACKGROUND
        call two_unpack
        mov dx,0100h
        in ax,dx
        or ax,0800h              ; documented two-screen, 128 KiB per screen
        out dx,ax
        mov dx,0102h
        mov ax,1111h             ; both screens: 320 dots, packed 4bpp
        out dx,ax
        mov dx,010ch
        mov ax,01a0h             ; mode 2, palette bank 1 assigned to G0
        out dx,ax
        mov dx,0126h
        xor ax,ax                ; G1 background is entirely opaque
        out dx,ax
        mov dx,0200h
        mov si,t_fb0
        mov cx,32
.reg:   lodsw
        out dx,ax
        add dx,2
        loop .reg
        xor ax,ax
        mov es,ax
        mov word [es:0ah*4],two_vrtc
        mov [es:0ah*4+2],cs
        mov dx,018ah
        mov al,0fbh
        out dx,al
        sti
        mov word [t_phase],0
.phase:
        mov ax,[t_ticks]
.vblank:
        cmp ax,[t_ticks]
        je .vblank
        mov bx,[t_phase]
        shl bx,1
        mov dx,0106h
        mov ax,[t_priority+bx]
        out dx,ax
        mov dx,0124h
        mov ax,[t_transparent+bx]
        out dx,ax
        mov dx,020eh
        mov ax,[t_dsa_low+bx]
        out dx,ax
        add dx,2
        mov ax,[t_dsa_high+bx]
        out dx,ax
        mov bx,[t_ticks]
        add bx,[t_delay]        ; settle the final mixer, not just GVRAM
        dec bx                  ; the next phase also waits one VRTC
.wait:  mov ax,[t_ticks]
        sub ax,bx
        js .wait
        mov ax,[t_phase]
two_shown:
        nop
        inc word [t_phase]
        cmp word [t_phase],5
        jb two_planes.phase
        ; After diagnostic phases, alternate the two front pages once
        ; per 60 VRTCs for interactive viewing. The background never moves.
        mov word [t_delay],60
        mov word [t_phase],3
        jmp two_planes.phase
two_unpack:
        lodsb
        xor cx,cx
        mov cl,al
        jcxz .done
        lodsb
.pixel: stosb
        or di,di
        jnz .next
        mov bx,es
        add bx,1000h
        mov es,bx
.next:  loop .pixel
        jmp two_unpack
.done:  ret
two_vrtc:
        push ax
        push dx
        inc word [cs:t_ticks]
        mov dx,0188h
        mov al,20h
        out dx,al
        pop dx
        pop ax
        iret
t_phase dw 0
t_ticks dw 0
t_delay dw 4
t_priority dw 00bah,00abh,00bah,00bah,00bah
t_transparent dw 1,1,0,1,1
t_dsa_low dw 0,0,0,8c00h,0
t_dsa_high dw 0,0,0,0,0
t_fb0 dw 0,0,160,447,0,0,0,0,0,224,0,0,0,0,0,0
; FB1 has no FSA/FBL/OFX/OFY; zero its reserved words. DSA zero
; addresses the start of G1's fixed upper 128 KiB region.
t_fb1 dw 0,0,160,0,0,0,0,0,0,224,0,0,0,0,0,0
