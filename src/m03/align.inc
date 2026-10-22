; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Alignment screen, as in the sister port: before the programs start, a
; white outline of the 288x224 game picture (dots 16-303) with ticks on its
; left edge every 8 lines (longer every 32) and, while the picture is not
; moved sideways, a white outline of the whole 320x224 raster for the
; monitor's automatic adjustment. (Moved sideways, DSA shows the
; neighbouring line's dots at the edges, so the raster outline would appear
; at the wrong side.) The picture is moved with the numeric keypad or the
; cursor keys, in the game's orientation (monitor turned clockwise): up and
; down by 8 dots of the raster width (at most 16), left and right by one
; line (at most 8). It ends after ALIGN_FRAMES frames without a key, or with
; RETURN or SPACE. The position moves both screens' DSA (align_offset) and
; is kept for the game; the margins in GVRAM are blank (native_planes.inc).
; Drawn on G1, with its colour 1 white meanwhile; G1 is cleared afterwards
; (N_DRAWN expects colour 0) and the palette entry restored.
%ifndef ALIGN_FRAMES
ALIGN_FRAMES equ 300                ; about 5 s, restarted by every key
%endif
ALIGN_WHITE equ 11h                 ; colour 1 in both pixels of a byte
ALIGN_LINES equ 224
ALIGN_PITCH equ 160
SHIFT_X_MAX equ 16                  ; dots, in steps of 8 (DSA is in 4 bytes)
SHIFT_Y_MAX equ 8                   ; lines
ALIGN_GO equ 80h                    ; RETURN or SPACE, in align_keys

live_align:
        push es
        mov dx,0302h
        mov ax,0f3deh             ; white, written twice to settle (planes_init)
        out dx,ax
        out dx,ax
        call align_draw
        mov word [align_left],ALIGN_FRAMES
        call align_keys
        mov [align_prev],al
.frame: mov ax,[tick]             ; wait for a VRTC
.wait:  cmp ax,[tick]
        je .wait
        call align_keys
        mov ah,[align_prev]
        mov [align_prev],al
        not ah
        and al,ah                 ; AL: keys just pressed
        test al,ALIGN_GO
        jnz .done
        test al,K_UP | K_DOWN | K_LEFT | K_RIGHT
        jz .count
        mov word [align_left],ALIGN_FRAMES
        test al,K_UP              ; game up: raster left
        jz .k2
        cmp word [align_x],-SHIFT_X_MAX
        jle .k2
        sub word [align_x],8
.k2:    test al,K_DOWN            ; game down: raster right
        jz .k4
        cmp word [align_x],SHIFT_X_MAX
        jge .k4
        add word [align_x],8
.k4:    test al,K_LEFT            ; game left: raster down
        jz .k6
        cmp word [align_y],SHIFT_Y_MAX
        jge .k6
        inc word [align_y]
.k6:    test al,K_RIGHT           ; game right: raster up
        jz .show
        cmp word [align_y],-SHIFT_Y_MAX
        jle .show
        dec word [align_y]
.show:  call align_draw
        jmp .frame
.count: dec word [align_left]
        jnz .frame
.done:  call align_clear
        mov dx,0302h
        mov ax,[N_PALETTE + 2]
        out dx,ax
        out dx,ax
        mov byte [key_latch],0    ; presses here are not the game's
%ifdef SERVICE_MENU
        mov word [svc_latch],0    ; nor the service screen's
%endif
        pop es
        ret

; Draw the outlines for the current position on G1 and move both screens.
align_draw:
        call align_clear
        mov ax,[align_y]          ; picture down: DSA - lines * 160
        imul ax,ax,ALIGN_PITCH
        mov dx,[align_x]          ; picture right: DSA - dots / 2
        sar dx,1
        add ax,dx
        neg ax
        mov [align_offset],ax
        mov ax,0c000h
        mov es,ax
        mov bx,8                  ; the game picture: bytes 8-151
        mov dx,151
        call align_outline
        cmp word [align_x],0
        jne .show
        xor bx,bx                 ; the raster: bytes 0-159
        mov dx,ALIGN_PITCH - 1
        call align_outline
.show:  pushf
        cli
        mov ax,[l_display_page]
        call live_front_dsa
        mov dx,022eh              ; FB1 (G1)
        xor ax,ax
        call live_dsa
        popf
        ret

align_clear:
        mov ax,0c000h
        mov es,ax
        xor di,di
        xor ax,ax
        mov cx,ALIGN_LINES * ALIGN_PITCH / 2
        rep stosw
        ret

; Outline of bytes BX to DX of lines 0-223 in ES, ticks inside the left
; edge every 8 lines (longer every 32).
align_outline:
        mov cx,dx                 ; lines 0 and 223
        sub cx,bx
        inc cx
        push cx
        mov di,bx
        mov al,ALIGN_WHITE
        rep stosb
        pop cx
        mov di,(ALIGN_LINES - 1) * ALIGN_PITCH
        add di,bx
        rep stosb
        xor si,si                 ; SI: line
.line:  imul di,si,ALIGN_PITCH    ; (MUL would change DX)
        add di,bx
        push di
        add di,dx
        sub di,bx
        mov byte [es:di],ALIGN_WHITE
        pop di
        mov byte [es:di],ALIGN_WHITE
        inc di
        mov cx,3                  ; tick: 6 dots
        test si,1fh
        jnz .short
        mov cx,7                  ; long tick: 14 dots
.short: test si,07h
        jnz .next
        mov al,ALIGN_WHITE
        rep stosb
.next:  inc si
        cmp si,ALIGN_LINES
        jb .line
        ret

; AL = the game keys (scan_keys) for the directions, ALIGN_GO for RETURN
; (port 01h bit 7) or SPACE.
align_keys:
        call scan_keys
        mov ah,al
        and al,K_UP | K_DOWN | K_LEFT | K_RIGHT
        test ah,K_FIRE
        jnz .go
        push ax
        in al,01h
        test al,80h
        pop ax
        jnz .done
.go:    or al,ALIGN_GO
.done:  ret

%ifdef ALIGN_TEST_X                ; test only: a preset position
align_x dw ALIGN_TEST_X
align_y dw ALIGN_TEST_Y
%else
align_x dw 0
align_y dw 0
%endif
align_left dw 0
align_prev db 0
        align 2
align_offset dw 0
