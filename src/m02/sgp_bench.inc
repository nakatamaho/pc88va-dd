; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Synchronous 8bpp CPU/SGP comparison, inspired by the sibling emulator's
; pseudo-sprite demo. No ROM assets. All restores precede all sprite draws.
; RAM: 8000 command list, 9000 prepared 32x32 source. GVRAM page 1 is cache.
sgp_benchmark:
        ; Cache the synthetic background outside the measured interval.
        mov ax,0a000h
        mov dx,0b180h
        call bench_copy_page
        mov ax,9000h
        mov es,ax
        xor di,di
        xor bx,bx
.source:
        mov ax,bx
        shr ax,5
        mov dx,bx
        and dx,31
        xor dx,ax
        test dl,3
        jz .zero
        mov dx,bx
        and dx,31
        add ax,dx
        and al,7
        or al,16
        jmp .pixel
.zero:  xor al,al
.pixel: stosb
        inc bx
        cmp bx,1024
        jb .source
        ; Destinations include odd byte positions and overlapping 32x32s.
        push cs
        pop es
        mov di,b_records
        xor bx,bx
.record:
        mov ax,bx
        shr ax,4
        imul ax,ax,40
        add ax,16
        imul ax,ax,320
        mov dx,bx
        and dx,15
        imul dx,dx,18
        add ax,dx
        mov dx,bx
        and dx,1
        add ax,dx
        add ax,16
        stosw
        inc bx
        cmp bx,64
        jb .record
        mov word [b_case],0
.case:  mov bx,[b_case]
        mov al,[b_counts + bx]
        xor ah,ah
        mov [b_count],ax
        mov ax,16
        cmp bx,4
        jb .size
        mov ax,32
.size:  mov [b_size],ax
        call bench_reset
bench_cpu_begin:
        call bench_cpu
bench_cpu_end:
        nop
        call bench_reset
bench_sgp_begin:
        call bench_list
bench_sgp_submit:
        call bench_run
bench_sgp_end:
        nop
        cmp byte [b_error],0
        jne bench_failed
        inc word [b_case]
        cmp word [b_case],8
        jb sgp_benchmark.case
        ret
bench_failed:
        cli
        hlt
        jmp bench_failed
bench_reset:
        mov ax,0b180h
        mov dx,0a000h
; AX source and DX destination segments, exactly 71680 bytes.
bench_copy_page:
        push ds
        mov ds,ax
        mov es,dx
        xor si,si
        xor di,di
        mov cx,8000h
        rep movsw
        add ax,1000h
        add dx,1000h
        mov ds,ax
        mov es,dx
        mov cx,0c00h
        rep movsw
        pop ds
        ret
bench_cpu:
        mov word [cs:b_index],0
.restore:
        mov bx,[cs:b_index]
        mov si,[cs:b_records + bx]
        mov di,si
        mov ax,0b180h
        mov ds,ax
        mov ax,0a000h
        mov es,ax
        mov bp,[cs:b_size]
        mov dx,320
        sub dx,bp
.row:   mov cx,[cs:b_size]
        shr cx,1
        rep movsw
        add si,dx
        add di,dx
        dec bp
        jnz .row
        add word [cs:b_index],2
        mov ax,[cs:b_index]
        shr ax,1
        cmp ax,[cs:b_count]
        jb .restore
        mov word [cs:b_index],0
.sprite:
        mov bx,[cs:b_index]
        mov di,[cs:b_records + bx]
        xor si,si
        mov ax,9000h
        mov ds,ax
        mov bp,[cs:b_size]
.line:  mov cx,[cs:b_size]
.pixel: lodsb
        or al,al
        jz .transparent
        mov [es:di],al
.transparent:
        inc di
        loop .pixel
        add si,32
        sub si,[cs:b_size]
        add di,320
        sub di,[cs:b_size]
        dec bp
        jnz .line
        add word [cs:b_index],2
        mov ax,[cs:b_index]
        shr ax,1
        cmp ax,[cs:b_count]
        jb .sprite
        push cs
        pop ds
        ret
bench_list:
        mov ax,8000h
        mov es,ax
        xor di,di
        mov ax,3                  ; SET_WORK, writable main RAM
        stosw
        mov ax,b_work
        stosw
        mov ax,2                  ; physical address = 20000h + offset
        stosw
        mov byte [b_phase],0
.phase: mov word [b_index],0
.entry: mov bx,[b_index]
        mov bx,[b_records + bx]
        mov ax,4                  ; SET_SOURCE
        stosw
        mov ax,2                  ; 8bpp
        cmp byte [b_phase],0
        jne .source_mode
        mov ax,bx
        and ax,1
        shl ax,4
        or ax,2
.source_mode:
        stosw
        mov ax,[b_size]
        stosw
        stosw
        mov ax,32                 ; main RAM sprite pitch
        cmp byte [b_phase],0
        jne .source_pitch
        mov ax,320
.source_pitch:
        stosw
        xor ax,ax
        mov dx,9                  ; source bitmap at physical 90000h
        cmp byte [b_phase],0
        jne .source_addr
        mov ax,bx
        and ax,0fffeh
        add ax,1800h              ; cache at SGP 211800h
        mov dx,21h
.source_addr:
        stosw
        mov ax,dx
        stosw
        mov ax,5                  ; SET_DESTINATION
        stosw
        mov ax,bx
        and ax,1
        shl ax,4
        or ax,2
        stosw
        mov ax,[b_size]
        stosw
        stosw
        mov ax,320
        stosw
        mov ax,bx
        and ax,0fffeh
        stosw
        mov ax,20h                ; output at SGP 200000h
        stosw
        mov ax,7                  ; BITBLT
        stosw
        mov ax,0005h              ; opaque copy for restoration
        cmp byte [b_phase],0
        je .mode
        mov ax,0105h              ; source zero transparent
.mode:  stosw
        add word [b_index],2
        mov ax,[b_index]
        shr ax,1
        cmp ax,[b_count]
        jb .entry
        inc byte [b_phase]
        cmp byte [b_phase],2
        jb .phase
        mov ax,1                  ; END
        stosw
        ret
bench_run:
        call bench_wait
        jc .error
        mov dx,0580h
        mov al,10h                ; CPU-data write mode, as in the demo
        out dx,al
        mov dx,0500h
        xor ax,ax
        out dx,ax
        add dx,2
        mov ax,8                  ; command list at physical 80000h
        out dx,ax
        mov dx,0504h
        xor al,al
        out dx,al
        mov dx,0506h
        mov al,1
        out dx,al
        call bench_wait
        jnc .done
.error: mov byte [b_error],1
.done:  ret
bench_wait:
        mov dx,0506h
        mov bx,256                ; bounded wait even for stress cases
.outer: mov cx,0ffffh
.poll:  in al,dx
        test al,1
        jz .ready
        loop .poll
        dec bx
        jnz .outer
        stc
        ret
.ready: clc
        ret
b_case dw 0
b_size dw 0
b_count dw 0
b_index dw 0
b_phase db 0
b_error db 0
b_counts db 1,8,32,64,1,8,32,64
b_records times 64 dw 0
b_work times 29 dw 0
