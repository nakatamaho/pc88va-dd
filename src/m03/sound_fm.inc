; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; FM-lite: additive profiles, F*443/256 pitch. FM-fit: offline fitted
; low/high voices and exact F*45/26 pitch: the YM2203 plays F-number x
; 2^(block-1) x 55466 / 2^20 Hz (3993600 / 72; vaeg's np2 and ymfm), the
; WSG 96000 x F / 2^20 Hz. No target-side fitting/search.
; The method is a run-time byte (m03_fm_fit), so one build can load either.
m03_fm_init:
        xor bx,bx
.channel:
        mov al,28h
        mov ah,bl
        call m03_opn_write
        xor si,si
.operator:
        mov dl,[m03_op_offsets+si]
        add dl,bl
        mov al,dl
        add al,30h
        mov ah,1
        call m03_opn_write
        mov al,dl
        add al,40h
        mov ah,127
        call m03_opn_write
        mov al,dl
        add al,50h
        mov ah,31
        call m03_opn_write
        mov al,dl
        add al,60h
        xor ah,ah
        call m03_opn_write
        mov al,dl
        add al,70h
        call m03_opn_write
        mov al,dl
        add al,80h
        mov ah,15
        call m03_opn_write
        mov al,dl
        add al,90h
        xor ah,ah
        call m03_opn_write
        inc si
        cmp si,4
        jb .operator
        inc bx
        cmp bx,3
        jb .channel
        ret

; DX:AX=F, CL=linear volume nibble. All scratch is native, DS=CS.
m03_fm_voice:
        mov [m03_fm_volume_now],cl
        mov bx,[m03_voice]
        shr bx,1
        cmp cl,0
        je .off
        mov si,ax
        or si,dx
        jz .off
        imul si,bx,5
        mov ch,[m03_raw+5+si]
        and ch,7
        shl ch,1
        cmp byte [m03_fm_fit],0
        je .range
        or dx,dx
        jnz .high
        cmp ax,6292
        jb .range
.high:  inc ch
.range:
        mov [m03_fm_want],ch
        call m03_fm_pitch
        mov bx,[m03_voice]
        cmp ax,[m03_fm_periods+bx]
        je .same_pitch
        mov [m03_fm_periods+bx],ax
        mov dx,ax
        shr bx,1
        mov al,0a4h
        add al,bl
        mov ah,dh
        call m03_opn_write
        mov al,0a0h
        add al,bl
        mov ah,dl
        call m03_opn_write
.same_pitch:
        mov bx,[m03_voice]
        shr bx,1
        mov al,[m03_fm_want]
        cmp al,[m03_fm_profiles+bx]
        je .volume
        mov [m03_fm_profiles+bx],al
        call m03_fm_load
        jmp .levels
.volume:
        mov al,[m03_fm_volume_now]
        cmp al,[m03_fm_volumes+bx]
        je .key
.levels:
        mov al,[m03_fm_volume_now]
        mov [m03_fm_volumes+bx],al
        call m03_fm_levels
.key:   cmp byte [m03_fm_keys+bx],0
        jne .done
        mov byte [m03_fm_keys+bx],1
        mov al,28h
        mov ah,bl
        or ah,0f0h
        call m03_opn_write
.done:  ret
.off:   cmp byte [m03_fm_keys+bx],0
        je .done
        mov byte [m03_fm_keys+bx],0
        mov al,28h
        mov ah,bl
        call m03_opn_write
        ret

m03_fm_pitch:
        mov si,dx
        cmp byte [cs:m03_fm_fit],0
        jne .exact
        mov di,443
        mul di
        push ax
        push dx
        mov ax,si
        mul di
        pop dx
        add dx,ax
        pop ax
        mov cx,8
.shift: shr dx,1
        rcr ax,1
        loop .shift
        jmp .normalize
.exact: mov di,45
        mul di
        push ax
        push dx
        mov ax,si
        mul di
        pop dx
        add dx,ax
        pop ax
        mov si,ax
        mov ax,dx
        xor dx,dx
        mov di,26
        div di
        push ax                 ; high quotient; second division cannot overflow
        mov ax,si
        div di
        pop dx
.normalize:
        mov cl,1
.block: or dx,dx
        jnz .up
        cmp ax,2048
        jb .fnum
.up:    shr dx,1
        rcr ax,1
        inc cl
        jmp .block
.fnum:  cmp cl,7
        jbe .pack
        mov cl,7
        mov ax,2047
.pack:  shl cl,3
        or ah,cl
        ret
m03_fm_ptr:
        xor ax,ax
        mov al,[m03_fm_profiles+bx]
        imul si,ax,9
        add si,N_FM_VOICES
        ret
m03_fm_load:
        call m03_fm_ptr
        mov al,0b0h
        add al,bl
        mov ah,[si]
        call m03_opn_write
        xor di,di
.operator:
        mov al,30h
        add al,[m03_op_offsets+di]
        add al,bl
        mov ah,[si+1]
        call m03_opn_write
        add si,2
        inc di
        cmp di,4
        jb .operator
        ret
m03_fm_levels:
        call m03_fm_ptr
        mov al,[si]
        and ax,7
        mov di,ax
        mov dl,[m03_carriers+di]
        xor di,di
.operator:
        mov al,[si+2]
        add si,2
        test dl,1
        jz .write
        push bx
        xor bx,bx
        mov bl,[m03_fm_volume_now]
        add al,[m03_fm_attenuation+bx]
        pop bx
        cmp al,127
        jbe .write
        mov al,127
.write: mov ah,al
        mov al,40h
        add al,[m03_op_offsets+di]
        add al,bl
        call m03_opn_write
        shr dl,1
        inc di
        cmp di,4
        jb .operator
        ret
m03_op_offsets db 0,8,4,12
m03_carriers db 8,8,8,8,10,14,14,15
m03_fm_attenuation db 127,31,23,19,15,13,11,9,7,6,5,4,3,2,1,0
m03_fm_periods times 3 dw 0ffffh
m03_fm_profiles times 3 db 0ffh
m03_fm_volumes times 3 db 0ffh
m03_fm_keys times 3 db 0
m03_fm_want db 0
m03_fm_volume_now db 0
%ifdef M03_FM_FIT
m03_fm_fit db 1
%else
m03_fm_fit db 0
%endif
%ifdef LIVE_VIDEO
m03_fm_ready db 0              ; set when FMVOICE.DAT checks (install_fm)
%else
m03_fm_ready db 1
%endif
%ifdef DIST
m03_use_fm db 0                ; SSG is the primary backend
%else
m03_use_fm db 1
%endif
