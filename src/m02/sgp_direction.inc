; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Asymmetric 16x16 source: distinguish copy traversal from reflection.
; Reuses benchmark's bounded command runner and background reset.
sgp_direction:
        mov ax,0a000h
        mov dx,0b180h
        call bench_copy_page
        mov ax,9000h
        mov es,ax
        xor di,di
        xor bx,bx
.source:
        mov ax,bx
        shr ax,4                  ; y
        mov cx,bx
        and cx,15                 ; x
        test cx,3
        jnz .colour
        test ax,1
        jz .zero
.colour:
        imul ax,ax,3
        add ax,cx
        xor dx,dx
        mov cx,31
        div cx
        mov ax,dx
        inc ax
        jmp .pixel
.zero:  xor ax,ax
.pixel: stosb
        inc bx
        cmp bx,256
        jb .source
        mov word [d_case],0
.case:  call bench_reset
        mov ax,[d_case]
dir_begin:
        call direction_list
dir_submit:
        call bench_run
dir_end:
        nop
        cmp byte [b_error],0
        jne bench_failed
        inc word [d_case]
        cmp word [d_case],8
        jb sgp_direction.case
        ret
direction_list:
        mov ax,8000h
        mov es,ax
        xor di,di
        mov ax,3
        stosw
        mov ax,b_work
        stosw
        mov ax,2
        stosw
        mov word [d_source],0
        mov word [d_source_high],9
        mov word [d_dest],16*320+17
        mov word [d_width],16
        mov word [d_pitch],16
        mov word [d_mode],5
        mov ax,[d_case]
        cmp ax,4
        jae .transparent
        test ax,1                 ; HD: both source and destination start right
        jz .vertical
        add word [d_source],15
        add word [d_dest],15
        or word [d_mode],0400h
.vertical:
        test ax,2                 ; VD: both start on the bottom row
        jz .one
        add word [d_source],15*16
        add word [d_dest],15*320
        or word [d_mode],0800h
        jmp .one
.transparent:
        mov word [d_mode],0105h
        cmp ax,5
        jb .one                   ; baseline: normal transparent copy
        cmp ax,6
        je .columns
        mov word [d_source],15*16
        mov word [d_pitch],0ffeeh  ; vaeg decoding: -18 + 2 = -16 bytes
        cmp ax,5
        je .one
.columns:
        ; HD reverses both traversals, not one side. Reorder columns using
        ; width-one forward BITBLTs, retaining documented transparency mode.
        mov word [d_width],1
        add word [d_source],15
        mov word [d_remaining],16
.column:
        call direction_emit
        dec word [d_source]
        inc word [d_dest]
        dec word [d_remaining]
        jnz .column
        jmp .end
.one:   call direction_emit
.end:   mov ax,1
        stosw
        ret
direction_emit:
        mov ax,4
        stosw
        mov ax,[d_source]
        and ax,1
        shl ax,4
        or ax,2
        stosw
        mov ax,[d_width]
        stosw
        mov ax,16
        stosw
        mov ax,[d_pitch]
        stosw
        mov ax,[d_source]
        and ax,0fffeh
        stosw
        mov ax,[d_source_high]
        stosw
        mov ax,5
        stosw
        mov ax,[d_dest]
        and ax,1
        shl ax,4
        or ax,2
        stosw
        mov ax,[d_width]
        stosw
        mov ax,16
        stosw
        mov ax,320
        stosw
        mov ax,[d_dest]
        and ax,0fffeh
        stosw
        mov ax,20h
        stosw
        mov ax,7
        stosw
        mov ax,[d_mode]
        stosw
        ret
d_case dw 0
d_source dw 0
d_source_high dw 9
d_dest dw 0
d_width dw 0
d_pitch dw 0
d_mode dw 0
d_remaining dw 0
