; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Runtime bridge: consume transient staged assets, snapshot shared video RAM,
; render after all three CPUs yield, present without changing scheduler IRQs.
live_video_init:
        mov dx,01cbh
        in al,dx
        test al,8
        jnz live_bad_monitor
        mov ax,1702h
        int 83h
        mov ah,0
        mov bh,0a0h
        mov bl,0ah
        mov cx,0404h
        xor dx,dx
        int 8fh
        or ax,ax
        jnz live_init_failed
        mov di,live_fb
        mov ax,0100h
        mov cx,1
        int 8fh
        or ax,ax
        jnz live_init_failed
        mov ax,0b01h
        int 8fh
        mov ah,16h
        int 84h
        mov ax,0500h
        xor bx,bx
        xor cx,cx
        xor dx,dx
        int 8fh
        mov ax,0b01h
        int 8fh
        push cs
        pop ds
        mov dx,0153h
        in al,dx
        and al,0f0h
        or al,4
        out dx,al
        mov dx,0580h
        mov al,10h
        out dx,al
        mov dx,0108h
        xor ax,ax
        out dx,ax
        add dx,2
        out dx,ax
        ; Program images have already moved to 5000/6000. Reclaim their
        ; initial CS staging area for lookup tables and the video snapshot.
        ; The staged area was checked by install_check (header, CRC-32).
        push ds
        mov ax,7000h
        mov ds,ax
        push cs
        pop es
        mov si,STAGE_HEADER
        mov di,ZIMG
        mov cx,L_TABLE_BYTES
        rep movsb
%ifdef M03_FM
        call install_fm             ; FMVOICE.DAT, if installed
%endif
        mov ax,3000h
        mov es,ax
        xor di,di
        mov si,[0ah]                ; character pens
        call native_unpack
        mov di,4000h
        mov si,[0ch]                ; background pens
        call native_unpack
        mov ax,4000h
        mov es,ax
        xor di,di
        mov si,[0eh]                ; sprite pens
        call native_unpack
        pop ds
        ; Only now may the retained cache overwrite the staged source bank.
        mov si,N_PALETTE
        mov dx,0300h
        mov cx,32
.palette:
        lodsw
        out dx,ax
        add dx,2
        loop .palette
        call planes_init          ; LIVE_VIDEO retains the scheduler's ISR
%ifdef BACKGROUND_CACHE
        call background_cache_init
%endif
%ifdef M03_AUDIO
        pushf
        cli
        call m03_sound_init
        popf
%endif
        push cs
        pop es
        ret
live_bad_monitor:
        mov si,live_monitor_message
        jmp live_error
live_init_failed:
        mov si,live_init_message
live_error:
        call puts
.halt:  hlt
        jmp .halt

live_video_frame:
%ifdef SERVICE_MENU
        call diag_draw            ; the load display (F9), when due
%endif
        ; Pending back page is immutable until the ISR has presented it.
%ifdef TRIPLE_FRONTS
        cmp byte [live_pending2],0 ; two pages waiting: no free page
        jne .skip
%else
        cmp byte [live_pending],0
        jne .skip
%endif
        cmp byte [n_pending],0    ; background rows still to draw: every frame
        jne .due
        mov ax,[frames]
        sub ax,[live_next_draw]
        js .skip
.due:
        mov ax,[frames]
        mov [live_drawn_frame],ax ; (g_sched: RENDER_STARVE)
        add ax,[live_render_period]
        mov [live_next_draw],ax
        jmp .draw
.skip:  ret
.draw:
        ; Native scheduler context only; CPU frames live on its other stack.
        pusha
        push ds
        push es
        push cs
        pop es
%ifdef TRIPLE_FRONTS
        cmp byte [live_pending],0 ; the waiting page's SGP work must end
        je .free                  ; before this render's (one SGP)
        call planes_wait
        mov byte [live_pending_ready],1
.free:
%endif
%ifdef SERVICE_MENU
        cmp byte [cs:svc_on],0
        je .game_state
        push cs
        pop ds
        call service_build        ; the screen's own video state
        mov byte [n_tiles_same],0 ; its tiles are not the game's
        mov byte [n_shadow_tiles],0
        jmp live_state_ready
.game_state:
%endif
        mov ax,ZSEG
        mov ds,ax
        ; Tile RAM rarely changes: compare it with the last snapshot and
        ; copy only from the first difference. When it is the same, the
        ; renderer neither compares nor saves it again (n_tiles_same).
        mov si,8000h
        mov di,N_VRAM
        mov cx,512
        repe cmpsw
        mov al,[cs:n_shadow_tiles] ; same, and the shadow holds them too
        mov [cs:n_tiles_same],al
        je .tiles_kept
        mov byte [cs:n_tiles_same],0
        mov byte [cs:n_shadow_tiles],0
        sub si,2
        sub di,2
        inc cx
        rep movsw
.tiles_kept:
        mov si,8b80h
        mov di,N_VRAM + 1024
        mov cx,64
        rep movsw
        mov si,9380h
        mov cx,64
        rep movsw
        mov si,9b80h
        mov cx,64
        rep movsw
        mov si,0a000h
        mov cx,8
        rep movsb
        push cs
        pop ds
        and word [N_LATCH],0101h  ; latch bits only
        and word [N_LATCH + 2],0101h
        and word [N_LATCH + 4],0101h
        and word [N_LATCH + 6],0101h
live_state_ready:
        cmp byte [N_LATCH+7],0
        jne live_unsupported
        mov ax,[frames]
live_render_begin:
        call native_render
live_render_end:
        mov [live_tiles],ax
        mov [live_hits],bx
        mov [live_misses],cx
        mov [live_fallbacks],dx
        mov [live_resident],si
        mov [live_cleared],bp
        mov [live_page],di
        inc word [live_updates]
        call planes_present
        jmp live_take_sample
live_unsupported:
        inc word [live_flip_rejections]
live_take_sample:
%ifdef LIVE_CAPTURE
        call planes_wait          ; the export pairs the state with finished GVRAM
        ; Diagnostic-only RAM export, not a game asset or normal video area.
        ; The checker reconstructs the exact state paired with this GVRAM.
%ifdef TRIPLE_FRONTS
        mov ax,0bb80h            ; diagnostics (1B800h) after front C's margin
%elifdef BACKGROUND_CACHE
        mov ax,0b240h            ; diagnostics (12400h) after front B's margin
%else
        mov ax,0d000h
%endif
        mov es,ax
        xor di,di
        mov si,N_VRAM
        mov cx,708
        rep movsw
        mov si,frames
        movsw
        mov si,tick
        movsw
        mov si,live_tiles
        mov cx,9
        rep movsw
%ifdef M03_AUDIO
        mov di,600h
        mov si,m03_raw
        mov cx,16
        rep movsw
        mov si,m03_registers
%ifdef M03_FM
        mov cx,128
%else
        mov cx,8
%endif
        rep movsw
        mov al,[m03_error]
        stosb
%ifdef M03_FM
        mov si,m03_fm_keys
        mov cx,3
        rep movsb
%endif
        mov di,750h
        mov si,m03_nmi_delivered
        mov cx,2
        rep movsw
%endif
        mov di,760h               ; background rows still to be drawn
        mov si,n_pending_rows
        mov cx,28
        rep movsb
%ifdef BACKGROUND_CACHE
        mov di,740h
        mov si,bc_used
        mov cx,6
        rep movsw
%endif
%endif
        mov ax,[frames]
        mov bx,[tick]
        mov cx,[lost_frames]
        mov dx,[late_frames]
        mov si,[live_updates]
        mov di,[live_page]
        mov bp,[live_resident]
live_sample:
        nop
        pop es
        pop ds
        popa
        ret

; Reserve the completed page; only the VRTC ISR changes the displayed
; start address and chooses the next write target. Commit flag is last.
live_present:
        cmp byte [l_reuse],0
        jne .done
..@live_present_new:           ; (a new page; for tools/play_rate.py)
%ifdef SERVICE_MENU
        inc word [diag_pages]
%endif
%ifdef TRIPLE_FRONTS
        mov ax,[l_output_page]
        mov bl,[l_target]
        cli
        cmp byte [live_pending],0
        jne .second
        mov [live_pending_page],ax
        mov [live_pending_index],bl
        mov byte [live_pending_ready],0
        mov byte [live_pending],1
        sti
        ret
.second:
        mov [live_pending2_page],ax
        mov [live_pending2_index],bl
        mov byte [live_pending2],1
        sti
        ret
%else
        mov ax,[l_output_page]
        mov [live_pending_page],ax
        mov byte [live_pending],1
%endif
.done:  ret
; Called after tick increment with AX/BX/DX/DS already saved by the ISR.
; No BIOS call, source conversion, busy wait or scheduler call in this hook.
live_video_vrtc:
        ; Sample the keys at every VRTC: a short press (vaeg holds one for
        ; about two VRTCs) must not be lost while a long render or a busy
        ; frame delays the scheduler's own reading. Kept until it reads them.
        push bx
        call scan_keys
        or [cs:key_latch],al
%ifdef SERVICE_MENU
        call scan_service
        or [cs:svc_latch],ax
%endif
        pop bx
        cmp byte [cs:live_pending],0
        je .done
%ifdef TRIPLE_FRONTS
        cmp byte [cs:live_pending_ready],0 ; its SGP work seen finished
        jne .show
%endif
        mov dx,0506h              ; the page is drawn by the SGP: show it
        in al,dx                  ; only once the SGP has finished
        test al,1
        jnz .done
.show:  mov ax,[cs:live_pending_page]
        mov [cs:l_display_page],ax
        call live_front_dsa
%ifdef TRIPLE_FRONTS
        mov al,[cs:live_pending_index]
        mov [cs:l_display_index],al
        mov byte [cs:live_pending],0
        mov byte [cs:live_pending_index],0ffh
        cmp byte [cs:live_pending2],0 ; the next page moves up
        je .done
        mov ax,[cs:live_pending2_page]
        mov [cs:live_pending_page],ax
        mov al,[cs:live_pending2_index]
        mov [cs:live_pending_index],al
        mov byte [cs:live_pending_ready],0
        mov byte [cs:live_pending2],0
        mov byte [cs:live_pending],1
%else
        xor byte [cs:l_target],1
        mov byte [cs:live_pending],0
%endif
.done:  ret

; FB0 DSA = front page AX moved by the alignment offset. Word writes
; only (byte writes to a DSA can hang the hardware). Addresses wrap within
; the screen's 128 KiB region, as the display does.
live_front_dsa:                   ; AX = page in paragraphs
        push ax
        push bx
        push cx
        push dx
        mov bx,ax
        shl ax,4                  ; BX:AX = the page's offset
        shr bx,12
        mov cx,ax
        mov ax,[cs:align_offset]
        cwd
        add ax,cx
        adc dx,bx
        and dx,1
        mov cx,dx
        mov dx,020eh
        out dx,ax
        add dx,2
        mov ax,cx
        out dx,ax
        pop dx
        pop cx
        pop bx
        pop ax
        ret
; DX = the screen's DSA port, AX = page offset in its region.
live_dsa:
        push ax
        push bx
        push cx
        mov bx,dx
        mov cx,ax
        mov ax,[cs:align_offset]
        cwd
        add ax,cx
        adc dx,0
        and dx,1
        mov cx,dx
        mov dx,bx
        out dx,ax
        add dx,2
        mov ax,cx
        out dx,ax
        pop cx
        pop bx
        pop ax
        ret

; Shared TSP commands; no BIOS calls occur from the running renderer.
tsp_cmd:
        mov ah,al
        mov dx,0142h
.wait:  in al,dx
        test al,5
        jnz .wait
        mov al,ah
        out dx,al
        ret
tsp_prm:
        mov ah,al
        mov dx,0142h
.wait:  in al,dx
        test al,1
        jnz .wait
        mov al,ah
        mov dx,0146h
        out dx,al
        ret
sync224 db 0c1h,57h,1ch,0,9fh,0,10h,0fh,25h,0,0e0h,0,2,4
live_fb dw 4,320,224,0,0,0
live_monitor_message db 'The Game DD M02: select 15 kHz before boot.',13,10,0
live_init_message db 'The Game DD M02: graphics initialization failed.',13,10,0
live_tiles dw 0
live_hits dw 0
live_misses dw 0
live_fallbacks dw 0
live_resident dw 0
live_cleared dw 0
live_page dw 0
live_updates dw 0
live_flip_rejections dw 0
live_pending db 0
live_pending_page dw 0
%ifdef TRIPLE_FRONTS
live_pending_index db 0ffh
live_pending_ready db 0
live_pending2 db 0
live_pending2_index db 0
live_pending2_page dw 0
%endif
live_next_draw dw 0
live_drawn_frame dw 0          ; the scheduler frame of the last render
RENDER_STARVE equ 2             ; frames without one: g_sched draws anyway
live_forced db 0                ; set during such a render (native.inc)
live_render_period dw L_RENDER_PERIOD   ; scheduler frames a render (F10 FPS)
