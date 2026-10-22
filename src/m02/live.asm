; Copyright (c) 2026 Nakata Maho
; SPDX-License-Identifier: BSD-2-Clause
; Retain the M01 scheduler and protocols; select native two-screen output.
%define LIVE_VIDEO 1
%define NATIVE_PLANES 1
%ifndef BG_MIN_ROWS
%define BG_MIN_ROWS 2
%endif
%define l_ticks tick
%include "../m01/m01test.asm"
