-- Copyright (c) 2026 Nakata Maho
-- SPDX-License-Identifier: BSD-2-Clause
-- Record the sound program's state around each NMI it acts on (120 Hz):
-- 'T', frame (u32), disturbed (u8: main or sub wrote 9A80h-9B7Fh meanwhile),
-- 9A80h-9B7Fh before, 8401h 8646h 8657h 87CFh, 9A80h-9B7Fh after, then
-- 6800h-681Fh (write-only on the board: reads give 0). The entry is its
-- write of 1 to 9B3Ch, the end its write of 0 after writing 680Fh.
-- Scripted play (as sound_requests.lua) repeats every 7000 frames;
-- DD_INJECT=1 also writes random requests, DD_INJECT=2 each sound in turn;
-- DD_DEMO_OFF=1 turns the Demo Sounds switch off. Output: DD_OUT. ROM-derived
-- state: keep it under build/.
local m = manager.machine
local snd = m.devices[":sub2"].spaces["program"]
local mainsp = m.devices[":maincpu"].spaces["program"]
local out = assert(io.open(assert(os.getenv("DD_OUT")), "wb"))
local frames = tonumber(os.getenv("DD_FRAMES") or "6000")
local inject = os.getenv("DD_INJECT") == "1"
local each = os.getenv("DD_INJECT") == "2"      -- each sound in turn, every 240 frames
if os.getenv("DD_DEMO_OFF") == "1" then          -- the Demo Sounds DIP switch off
    local field = m.ioport.ports[":DSWB"].fields["Demo Sounds"]
    field.user_value = field.defvalue ~ 0x10
end
local frame, active, end_armed, disturbed, before = 0, false, false, 0, nil
local count = 0
local function block(space, a, n)
    local t = {}
    for i = 0, n - 1 do t[#t + 1] = string.char(space:read_u8(a + i)) end
    return table.concat(t)
end
taps = {}
taps[#taps + 1] = snd:install_write_tap(0x9b3c, 0x9b3c, "tick", function(offset, data, mask)
    data = data & 0xff
    if data == 1 then
        active, end_armed, disturbed = true, false, 0
        before = block(snd, 0x9a80, 0x100) .. string.char(snd:read_u8(0x8401), snd:read_u8(0x8646),
                                                         snd:read_u8(0x8657), snd:read_u8(0x87cf))
    elseif data == 0 and active and end_armed then
        -- the write itself is not yet in RAM: 9B3C reads 1 here
        local after = block(snd, 0x9a80, 0x100)
        out:write(string.pack("<c1I4B", "T", frame, disturbed), before, after, block(snd, 0x6800, 0x20))
        count = count + 1
        active = false
    end
end)
taps[#taps + 1] = snd:install_write_tap(0x680f, 0x680f, "end", function() end_armed = true end)
for _, tag in ipairs({":maincpu", ":sub"}) do
    taps[#taps + 1] = m.devices[tag].spaces["program"]:install_write_tap(0x9a80, 0x9b7f, "w" .. tag,
        function() if active then disturbed = 1 end end)
end
local function set(port, name, value)
    local field = m.ioport.ports[port].fields[name]
    if field then field:set_value(value) end
end
local rng = 88
local function rand(n) rng = (rng * 1103515245 + 12345) % 2147483648; return rng % n end
emu.register_frame_done(function()
    frame = frame + 1
    local t = frame % 7000
    set(":IN1", "Coin 1", (t >= 900 and t < 905) and 1 or 0)
    set(":IN1", "1 Player Start", (t >= 1000 and t < 1005) and 1 or 0)
    local dirs = {"P1 Up", "P1 Right", "P1 Down", "P1 Left"}
    for i, name in ipairs(dirs) do
        set(":IN0", name, (t > 1100 and math.floor(frame / 45) % 4 + 1 == i) and 1 or 0)
    end
    set(":IN1", "P1 Button 1", (t > 1100 and frame % 20 < 3) and 1 or 0)
    if inject and frame > 700 and rand(40) == 0 then
        mainsp:write_u8(0x9a80 + rand(0x15), 1 + rand(2))
    end
    if each and frame > 1100 and frame % 240 == 0 then
        mainsp:write_u8(0x9a80 + (frame // 240) % 0x15, 1)
    end
    if frame >= frames then out:close(); print("ticks", count); m:exit() end
end)
