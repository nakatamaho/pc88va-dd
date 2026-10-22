-- Copyright (c) 2026 Nakata Maho
-- SPDX-License-Identifier: BSD-2-Clause
-- Compact per-frame sprite-state trace. Read RAM only, never custom I/O.
-- Record: little-endian frame u32, three 128-byte RAM windows, flip byte.
local m = manager.machine
local space = m.devices[":maincpu"].spaces["program"]
local frames = tonumber(os.getenv("DD_FRAMES") or "6000")
local out = assert(io.open(assert(os.getenv("DD_OUT")), "wb"))
local flip = 0
cache_taps = {}
for _, tag in ipairs({":maincpu", ":sub", ":sub2"}) do
    local dev = m.devices[tag]
    if dev then
        cache_taps[#cache_taps + 1] = dev.spaces["program"]:install_write_tap(
            0xa007, 0xa007, "cache_flip", function(offset, data, mask) flip = data & 1 end)
    end
end
local function set(port, name, value)
    local field = m.ioport.ports[port].fields[name]
    if field then field:set_value(value) end
end
local frame = 0
emu.register_frame_done(function()
    frame = frame + 1
    set(":IN1", "Coin 1", (frame >= 900 and frame < 905) and 1 or 0)
    set(":IN1", "1 Player Start", (frame >= 1000 and frame < 1005) and 1 or 0)
    local dirs = {"P1 Up", "P1 Right", "P1 Down", "P1 Left"}
    for i, name in ipairs(dirs) do
        set(":IN0", name, (frame > 1100 and math.floor(frame / 45) % 4 + 1 == i) and 1 or 0)
    end
    set(":IN1", "P1 Button 1", (frame > 1100 and frame % 20 < 3) and 1 or 0)
    local record = {string.pack("<I4", frame)}
    for _, base in ipairs({0x8b80, 0x9380, 0x9b80}) do
        local data = {}
        for address = base, base + 127 do data[#data + 1] = string.char(space:read_u8(address)) end
        record[#record + 1] = table.concat(data)
    end
    record[#record + 1] = string.char(flip)
    out:write(table.concat(record))
    if frame >= frames then out:close(); m:exit() end
end)
