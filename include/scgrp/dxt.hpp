// scgrp/dxt.hpp — DXT1 (BC1) / DXT3 (BC2) / DXT5 (BC3) block decoder.
// Header-only, C++17, no external dependencies. Little-endian assumed
// (matches every SC:R asset; the code reads bytes explicitly so it is
// endian-safe regardless of host).
#pragma once
#include <cstdint>
#include <cstddef>
#include <vector>

namespace scgrp {

enum class DxtFormat { BC1, BC2, BC3, Unknown };

// Decode a DXT-compressed block stream into a tightly packed RGBA8 buffer.
// `src` points at the raw compressed data (i.e. past the DDS header).
// Returns w*h*4 bytes. Dimensions need not be multiples of 4; edge blocks
// are clipped.
inline std::vector<uint8_t> decode_dxt(const uint8_t* src, size_t srcLen,
                                       int w, int h, DxtFormat fmt) {
    std::vector<uint8_t> out(static_cast<size_t>(w) * h * 4, 0);
    const int blocksX = (w + 3) / 4;
    const int blocksY = (h + 3) / 4;
    const int blkSize = (fmt == DxtFormat::BC1) ? 8 : 16;

    auto rd16 = [](const uint8_t* p) -> uint16_t {
        return static_cast<uint16_t>(p[0] | (p[1] << 8));
    };
    auto expand565 = [](uint16_t c, uint8_t& r, uint8_t& g, uint8_t& b) {
        int r5 = (c >> 11) & 0x1F, g6 = (c >> 5) & 0x3F, b5 = c & 0x1F;
        r = static_cast<uint8_t>((r5 << 3) | (r5 >> 2));
        g = static_cast<uint8_t>((g6 << 2) | (g6 >> 4));
        b = static_cast<uint8_t>((b5 << 3) | (b5 >> 2));
    };

    size_t p = 0;
    for (int by = 0; by < blocksY; ++by) {
        for (int bx = 0; bx < blocksX; ++bx) {
            if (p + blkSize > srcLen) return out;  // truncated: bail safely
            const uint8_t* blk = src + p;

            uint8_t alpha[16];
            const uint8_t* colBlk = blk;

            if (fmt == DxtFormat::BC3) {
                uint8_t a0 = blk[0], a1 = blk[1];
                uint8_t at[8]; at[0] = a0; at[1] = a1;
                if (a0 > a1) {
                    for (int k = 1; k <= 6; ++k)
                        at[k + 1] = static_cast<uint8_t>(((7 - k) * a0 + k * a1) / 7);
                } else {
                    for (int k = 1; k <= 4; ++k)
                        at[k + 1] = static_cast<uint8_t>(((5 - k) * a0 + k * a1) / 5);
                    at[6] = 0; at[7] = 255;
                }
                uint64_t bits = 0;
                for (int k = 0; k < 6; ++k) bits |= static_cast<uint64_t>(blk[2 + k]) << (8 * k);
                for (int k = 0; k < 16; ++k) alpha[k] = at[(bits >> (3 * k)) & 7];
                colBlk = blk + 8;
            } else if (fmt == DxtFormat::BC2) {
                for (int k = 0; k < 16; ++k) {
                    int nib = (blk[k >> 1] >> ((k & 1) * 4)) & 0xF;
                    alpha[k] = static_cast<uint8_t>(nib * 17);
                }
                colBlk = blk + 8;
            } else {
                for (int k = 0; k < 16; ++k) alpha[k] = 255;
            }

            uint16_t c0 = rd16(colBlk), c1 = rd16(colBlk + 2);
            uint8_t pal[4][3];
            expand565(c0, pal[0][0], pal[0][1], pal[0][2]);
            expand565(c1, pal[1][0], pal[1][1], pal[1][2]);
            bool bc1punch = (fmt == DxtFormat::BC1 && c0 <= c1);
            if (bc1punch) {
                for (int i = 0; i < 3; ++i) {
                    pal[2][i] = static_cast<uint8_t>((pal[0][i] + pal[1][i]) / 2);
                    pal[3][i] = 0;
                }
            } else {
                for (int i = 0; i < 3; ++i) {
                    pal[2][i] = static_cast<uint8_t>((2 * pal[0][i] + pal[1][i]) / 3);
                    pal[3][i] = static_cast<uint8_t>((pal[0][i] + 2 * pal[1][i]) / 3);
                }
            }
            uint32_t idx = static_cast<uint32_t>(colBlk[4]) | (colBlk[5] << 8) |
                           (colBlk[6] << 16) | (static_cast<uint32_t>(colBlk[7]) << 24);

            for (int k = 0; k < 16; ++k) {
                int ci = (idx >> (2 * k)) & 3;
                int lx = bx * 4 + (k & 3), ly = by * 4 + (k >> 2);
                if (lx >= w || ly >= h) continue;
                size_t di = (static_cast<size_t>(ly) * w + lx) * 4;
                out[di + 0] = pal[ci][0];
                out[di + 1] = pal[ci][1];
                out[di + 2] = pal[ci][2];
                uint8_t a = 255;
                if (bc1punch && ci == 3) a = 0;
                else if (fmt == DxtFormat::BC2 || fmt == DxtFormat::BC3) a = alpha[k];
                out[di + 3] = a;
            }
            p += blkSize;
        }
    }
    return out;
}

// Parse a raw DDS blob (starting at the "DDS " magic) and decode to RGBA8.
// Fills out w/h. Returns empty on failure.
inline std::vector<uint8_t> decode_dds(const uint8_t* dds, size_t len, int& w, int& h) {
    if (len < 128 || dds[0] != 'D' || dds[1] != 'D' || dds[2] != 'S' || dds[3] != ' ')
        return {};
    auto rd32 = [&](size_t o) {
        return static_cast<uint32_t>(dds[o] | (dds[o + 1] << 8) | (dds[o + 2] << 16) |
                                     (static_cast<uint32_t>(dds[o + 3]) << 24));
    };
    h = static_cast<int>(rd32(12));
    w = static_cast<int>(rd32(16));
    char fcc[5] = { (char)dds[84], (char)dds[85], (char)dds[86], (char)dds[87], 0 };
    DxtFormat fmt = DxtFormat::Unknown;
    if (fcc[0]=='D'&&fcc[1]=='X'&&fcc[2]=='T') {
        if (fcc[3]=='1') fmt = DxtFormat::BC1;
        else if (fcc[3]=='3') fmt = DxtFormat::BC2;
        else if (fcc[3]=='5') fmt = DxtFormat::BC3;
    }
    if (fmt == DxtFormat::Unknown) return {};
    return decode_dxt(dds + 128, len - 128, w, h, fmt);
}

} // namespace scgrp
