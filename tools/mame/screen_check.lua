-- Copyright (c) 2026 Nakata Maho
-- SPDX-License-Identifier: BSD-2-Clause
-- Capture unrotated RGB pixels and matching main memory for host checks.
-- DD_OUT must name an existing private output directory. All outputs contain
-- user assets and must remain outside version control.
local m = manager.machine
local space = m.devices[":maincpu"].spaces["program"]
local screen = m.screens[":screen"]
local palette = m.palettes[":palette"]
local out = assert(os.getenv("DD_OUT"))
local frames = tonumber(os.getenv("DD_FRAMES") or "1800")
local period = tonumber(os.getenv("DD_PERIOD") or "60")
local first = tonumber(os.getenv("DD_FIRST")) or period
local latch = {0, 0, 0, 0, 0, 0, 0, 0}
-- Retain taps until exit; any of the three processors can write the bus.
taps = {}
for _, tag in ipairs({":maincpu", ":sub", ":sub2"}) do
    local dev = m.devices[tag]
    if dev then
        taps[#taps + 1] = dev.spaces["program"]:install_write_tap(
            0xa000, 0xa007, "video_latches", function(offset, data, mask)
                latch[offset - 0xa000 + 1] = data & 1
            end)
    end
end
local function write(name, data)
    local f = assert(io.open(out .. "/" .. name, "wb"))
    f:write(data)
    f:close()
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
    if frame >= first and (frame - first) % period == 0 then
        local memory = {}
        for addr = 0, 65535 do
            -- Do not read I/O addresses: reads can advance chip protocols.
            -- Only the renderer's RAM windows are captured; the rest is zero.
            local value = 0
            if (addr >= 0x8000 and addr <= 0x83ff)
                or (addr >= 0x8b80 and addr <= 0x8bff)
                or (addr >= 0x9380 and addr <= 0x93ff)
                or (addr >= 0x9b80 and addr <= 0x9bff) then
                value = space:read_u8(addr)
            end
            if addr >= 0xa000 and addr <= 0xa007 then value = latch[addr - 0xa000 + 1] end
            memory[#memory + 1] = string.char(value)
        end
        write(string.format("%06d.memory", frame), table.concat(memory))
    end
    -- This MAME build swaps m_curbitmap in update_quads before frame_done.
    -- screen:pixels() therefore exposes the preceding frame's bitmap.
    -- Pair it with memory captured at the preceding frame_done callback.
    if frame - 1 >= first and (frame - 1 - first) % period == 0 then
        local raw, w, h = screen:pixels()
        assert(w == 288 and h == 224, "unexpected raster size")
        local function rgb(value)
            return string.char((value >> 16) & 255, (value >> 8) & 255, value & 255)
        end
        local pixels, colours = {}, {}
        for pos = 1, #raw, 4 do
            pixels[#pixels + 1] = rgb(string.unpack("I4", raw, pos))
        end
        for i = 0, 31 do colours[#colours + 1] = rgb(palette:indirect_color(i)) end
        local stem = string.format("%06d", frame - 1)
        write(stem .. ".rgb", table.concat(pixels))
        write(stem .. ".palette", table.concat(colours))
    end
    if frame >= frames + 1 then m:exit() end
end)
