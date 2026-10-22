-- Copyright (c) 2026 Nakata Maho
--
-- Redistribution and use in source and binary forms, with or without
-- modification, are permitted provided that the following conditions
-- are met:
-- 1. Redistributions of source code must retain the above copyright
--    notice, this list of conditions and the following disclaimer.
-- 2. Redistributions in binary form must reproduce the above copyright
--    notice, this list of conditions and the following disclaimer in the
--    documentation and/or other materials provided with the distribution.
--
-- THIS SOFTWARE IS PROVIDED BY THE AUTHOR "AS IS" AND ANY EXPRESS OR
-- IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
-- OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
-- IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
-- INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
-- BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
-- USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
-- ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
-- (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
-- THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-- MAME autoboot script for tools/check_sub.py.
--
-- DD_VIEW (optional): a file whose bytes the sub CPU reads at 0000h-5FFFh
-- instead of its own ROM (the relocated program at 4000h). DD_OUT: one
-- line per frame with hashes of tile RAM (8000h-83FFh) and of the sprite
-- registers (8B80h-8BFFh, 9380h-93FFh), and the sub CPU's PC. The inputs
-- are the same in every run: a coin and a start every 3000 frames, the
-- joystick turning every 45 frames and the button every 20 frames.

local m = manager.machine
local nframes = tonumber(os.getenv("DD_FRAMES") or "6000")
local out = io.open(os.getenv("DD_OUT"), "w")
local mainsp = m.devices[":maincpu"].spaces["program"]
local view = os.getenv("DD_VIEW")
if view and view ~= "" then
	local f = io.open(view, "rb")
	local data = f:read("a")
	f:close()
	local bytes = { string.byte(data, 1, #data) }
	local subsp = m.devices[":sub"].spaces["program"]
	tap = subsp:install_read_tap(0x0000, #bytes - 1, "view",
		function(offset, value, mask) return bytes[offset + 1] end)
end

local function set(port, name, v)
	local field = m.ioport.ports[port].fields[name]
	if field then field:set_value(v) end
end

local frame = 0
emu.register_frame_done(function()
	frame = frame + 1
	local f = frame
	set(":IN1", "Coin 1", (f % 3000 >= 900 and f % 3000 < 905) and 1 or 0)
	set(":IN1", "1 Player Start", (f % 3000 >= 1000 and f % 3000 < 1005) and 1 or 0)
	local dirs = { "P1 Up", "P1 Right", "P1 Down", "P1 Left" }
	local d = math.floor(f / 45) % 4 + 1
	for i, n in ipairs(dirs) do set(":IN0", n, (f > 1100 and i == d) and 1 or 0) end
	set(":IN1", "P1 Button 1", (f > 1100 and f % 20 < 3) and 1 or 0)
	local h1, h2 = 0, 0
	for a = 0x8000, 0x83ff do h1 = (h1 * 31 + mainsp:read_u8(a)) % 4294967291 end
	for a = 0x8b80, 0x8bff do h2 = (h2 * 31 + mainsp:read_u8(a)) % 4294967291 end
	for a = 0x9380, 0x93ff do h2 = (h2 * 31 + mainsp:read_u8(a)) % 4294967291 end
	out:write(string.format("%d %08x %08x %04X\n", f, h1, h2, m.devices[":sub"].state["PC"].value))
	if f >= nframes then
		out:close()
		m:exit()
	end
end)
