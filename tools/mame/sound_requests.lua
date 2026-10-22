-- Copyright (c) 2026 Nakata Maho
-- SPDX-License-Identifier: BSD-2-Clause
-- Log main/sub CPU writes to the sound program's shared input RAM, and the
-- WSG voice volumes each frame. Reads RAM only. Output: DD_OUT text file.
local m = manager.machine
local out = assert(io.open(assert(os.getenv("DD_OUT")), "w"))
local frames = tonumber(os.getenv("DD_FRAMES") or "6000")
local frame = 0
taps = {}
for _, tag in ipairs({":maincpu", ":sub", ":sub2"}) do
    local dev = m.devices[tag]
    taps[#taps + 1] = dev.spaces["program"]:install_write_tap(0x9a80, 0x9a9f, "req_" .. tag,
        function(offset, data, mask)
            out:write(string.format("W %d %s %04x %02x\n", frame, tag, offset, data & 0xff))
        end)
end
local function set(port, name, value)
    local field = m.ioport.ports[port].fields[name]
    if field then field:set_value(value) end
end
emu.register_frame_done(function()
    frame = frame + 1
    set(":IN1", "Coin 1", (frame >= 900 and frame < 905) and 1 or 0)
    set(":IN1", "1 Player Start", (frame >= 1000 and frame < 1005) and 1 or 0)
    local dirs = {"P1 Up", "P1 Right", "P1 Down", "P1 Left"}
    for i, name in ipairs(dirs) do
        set(":IN0", name, (frame > 1100 and math.floor(frame / 45) % 4 + 1 == i) and 1 or 0)
    end
    set(":IN1", "P1 Button 1", (frame > 1100 and frame % 20 < 3) and 1 or 0)
    if frame >= frames then out:close(); m:exit() end
end)
