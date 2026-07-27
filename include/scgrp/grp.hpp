// scgrp/grp.hpp — StarCraft classic GRP + StarCraft: Remastered DDS GRP.
//
// Two container formats live behind the .grp extension:
//
//   Classic GRP (1998):
//     u16 frameCount, u16 maxW, u16 maxH
//     frameCount * { u8 x, u8 y, u8 w, u8 h, u32 dataOffset }
//     per-frame RLE: for each row a u16 line offset (relative to dataOffset),
//       then opcodes:  b>=0x80 -> skip (b-0x80) transparent px
//                      b>=0x40 -> run  (b-0x40) of next byte
//                      else    -> copy b literal bytes
//     Pixels are palette indices; index 0 is transparent.
//     Exception: some files (game\icons.grp) are NOT RLE but flat bitmaps --
//     see classic_is_flat().
//
//   DDS GRP (Remastered HD, *_dds.grp):
//     12-byte header { u32 fileSize (self-referential), u16 frameCount,
//                      u16 flags(0x1002), u32 unused }
//     frameCount * { u16 w, u16 h, u32 ddsSize } + ddsSize bytes of a
//       standalone DXT1/DXT5 .dds + u32 trailer. No per-frame x/y offsets.
//       No palette needed (true colour + alpha).
//
// Verified against retail SC:R assets; the DDS GRP layout was corrected
// 2026-07-21 after measuring 627 frames (see CLAUDE.md).
#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <array>
#include <cmath>
#include <algorithm>
#include "image.hpp"
#include "dxt.hpp"

namespace scgrp {

using Palette = std::array<uint8_t, 768>;  // 256 * RGB

inline Palette grayscale_palette() {
    Palette p{};
    for (int i = 0; i < 256; ++i) { p[i*3] = p[i*3+1] = p[i*3+2] = static_cast<uint8_t>(i); }
    return p;
}

struct Frame {
    int x = 0, y = 0, w = 0, h = 0;
    Image image;             // decoded RGBA
};

struct Sprite {
    enum class Kind { ClassicGRP, DdsGRP, AnimHD };
    Kind kind = Kind::ClassicGRP;
    int frameCount = 0, maxW = 0, maxH = 0;
    std::vector<Frame> frames;
    std::string label;

    // ANIM-only extras (empty for GRP formats):
    struct Rect { int ax = 0, ay = 0, w = 0, h = 0, xoff = 0, yoff = 0; }; // atlas rect + draw offset
    std::vector<std::string> layers;   // present layer names (e.g. "diffuse","teamcolor")
    std::vector<Image> layerAtlas;     // decoded atlas per layer (parallel to `layers`)
    std::vector<Rect> rects;           // per-frame rect into the atlas (parallel to `frames`)
};

namespace detail {
inline uint16_t rd16(const uint8_t* d, size_t o){ return static_cast<uint16_t>(d[o] | (d[o+1]<<8)); }
inline uint32_t rd32(const uint8_t* d, size_t o){
    return static_cast<uint32_t>(d[o] | (d[o+1]<<8) | (d[o+2]<<16) | (static_cast<uint32_t>(d[o+3])<<24));
}
} // namespace detail

// ---- classic GRP: palette indices are the primary currency -------------------
//
// Decoding stops at indices. Colour is applied later, by whoever knows which
// palette applies (tileset .wpe, ticon.pcx trailer, twire.pcx ramp, ...). This
// is also what makes the output diffable against another implementation — see
// see CLAUDE.md §7.5.

enum FrameFlag : uint16_t {
    kRowClamped   = 1u << 0,  // a run would have written past the frame width
    kOffsetBad    = 1u << 1,  // dataOffset out of range -> frame left empty
    kRowShort     = 1u << 2,  // a row ended before reaching the frame width
    kFlatFrame    = 1u << 3,  // read as a flat bitmap, not RLE (see below)
};

struct IndexFrame {
    int x = 0, y = 0, w = 0, h = 0;
    uint16_t flags = 0;
    std::vector<uint8_t> idx;  // w*h palette indices, row-major; 0 = transparent
    uint8_t at(int px, int py) const { return idx[static_cast<size_t>(py) * w + px]; }
};

struct IndexSprite {
    bool ok = false;
    int canvasW = 0, canvasH = 0;
    std::vector<IndexFrame> frames;
    bool flat = false;         // whole file is flat (non-RLE), e.g. game\icons.grp
};

// Not every .grp is RLE: game\icons.grp holds flat uncompressed bitmaps, one
// byte per pixel, with no row table. Discriminator (same one OpenBW uses at
// ui.h:4593): the second frame's data begins exactly w0*h0 after the first.
inline bool classic_is_flat(const std::vector<uint8_t>& d) {
    using namespace detail;
    const size_t N = d.size();
    if (N < 6 + 16) return false;
    int fc = rd16(d.data(), 0);
    if (fc < 2 || 6 + static_cast<size_t>(fc) * 8 > N) return false;
    int w0 = d[6 + 2], h0 = d[6 + 3];
    if (w0 <= 0 || h0 <= 0) return false;
    uint32_t off0 = rd32(d.data(), 6 + 4);
    uint32_t off1 = rd32(d.data(), 6 + 8 + 4);
    return off1 == off0 + static_cast<uint32_t>(w0) * h0;
}

inline IndexSprite load_classic_indices(const std::vector<uint8_t>& d) {
    using namespace detail;
    const size_t N = d.size();
    auto u16 = [&](size_t o)->uint16_t { return (o + 2 <= N) ? rd16(d.data(), o) : 0; };
    auto u32 = [&](size_t o)->uint32_t { return (o + 4 <= N) ? rd32(d.data(), o) : 0; };

    IndexSprite s;
    int fc = u16(0);
    s.canvasW = u16(2); s.canvasH = u16(4);
    if (fc == 0 || 6 + static_cast<size_t>(fc) * 8 > N) return s;   // not a classic GRP
    s.flat = classic_is_flat(d);
    s.frames.reserve(fc);

    for (int i = 0; i < fc; ++i) {
        const size_t o = 6 + static_cast<size_t>(i) * 8;
        IndexFrame f;
        f.x = d[o]; f.y = d[o+1]; f.w = d[o+2]; f.h = d[o+3];
        const uint32_t foff = u32(o+4);
        f.idx.assign(static_cast<size_t>(f.w) * f.h, 0);

        const size_t need = static_cast<size_t>(f.w) * f.h;
        if (foff == 0 || foff >= N || (s.flat && foff + need > N)) {
            f.flags |= kOffsetBad;
            s.frames.push_back(std::move(f));
            continue;
        }
        if (s.flat) {
            f.flags |= kFlatFrame;
            std::copy(d.begin() + foff, d.begin() + foff + need, f.idx.begin());
            s.frames.push_back(std::move(f));
            continue;
        }
        for (int row = 0; row < f.h; ++row) {
            size_t p = foff + u16(foff + static_cast<size_t>(row) * 2);
            int x = 0;
            while (x < f.w && p < N) {
                const uint8_t c = d[p++];
                if (c >= 0x80) {                       // transparent run
                    int n = c - 0x80;
                    if (n > f.w - x) { n = f.w - x; f.flags |= kRowClamped; }
                    x += n;
                } else if (c >= 0x40) {                // repeat one index
                    int n = c - 0x40;
                    if (p >= N) break;
                    const uint8_t v = d[p++];
                    if (n > f.w - x) { n = f.w - x; f.flags |= kRowClamped; }
                    for (int k = 0; k < n; ++k, ++x) f.idx[static_cast<size_t>(row) * f.w + x] = v;
                } else {                               // literal run
                    int n = c;
                    if (n > f.w - x) { n = f.w - x; f.flags |= kRowClamped; }
                    for (int k = 0; k < n && p < N; ++k, ++x) f.idx[static_cast<size_t>(row) * f.w + x] = d[p++];
                }
            }
            if (x < f.w) f.flags |= kRowShort;
        }
        s.frames.push_back(std::move(f));
    }
    s.ok = true;
    return s;
}

inline Sprite load_classic_grp(const std::vector<uint8_t>& d, const Palette& pal) {
    IndexSprite ix = load_classic_indices(d);
    Sprite s; s.kind = Sprite::Kind::ClassicGRP;
    s.label = ix.flat ? "Classic GRP (flat, non-RLE)" : "Classic GRP (RLE indexed)";
    if (!ix.ok) {
        s.label = "Classic GRP (invalid header — size " + std::to_string(d.size()) + ")";
        return s;
    }
    s.frameCount = static_cast<int>(ix.frames.size());
    s.maxW = ix.canvasW; s.maxH = ix.canvasH;
    s.frames.reserve(ix.frames.size());
    int bad = 0, clamped = 0;
    for (const IndexFrame& in : ix.frames) {
        if (in.flags & kOffsetBad) ++bad;
        if (in.flags & kRowClamped) ++clamped;
        Frame f; f.x = in.x; f.y = in.y; f.w = in.w; f.h = in.h;
        f.image = Image(in.w, in.h);
        for (int y = 0; y < in.h; ++y) for (int x = 0; x < in.w; ++x) {
            const uint8_t v = in.at(x, y);
            if (!v) continue;                      // index 0 is transparent
            uint8_t* q = f.image.px(x, y);
            q[0] = pal[v*3]; q[1] = pal[v*3+1]; q[2] = pal[v*3+2]; q[3] = 255;
        }
        s.frames.push_back(std::move(f));
    }
    if (bad)     s.label += " \xC2\xB7 " + std::to_string(bad) + " bad frame(s)";
    if (clamped) s.label += " \xC2\xB7 " + std::to_string(clamped) + " clamped row(s)";
    return s;
}

// Collect the set of palette indices a classic GRP actually uses (index 0
// excluded). Handy for building an "auto" high-contrast debug palette.
inline std::vector<int> classic_used_indices(const std::vector<uint8_t>& d) {
    std::vector<bool> seen(256, false);
    for (const IndexFrame& f : load_classic_indices(d).frames)
        for (uint8_t v : f.idx) if (v) seen[v] = true;
    std::vector<int> out;
    for (int i = 1; i < 256; ++i) if (seen[i]) out.push_back(i);
    return out;
}

inline void hsl_to_rgb(double h, double s, double l, uint8_t& R, uint8_t& G, uint8_t& B) {
    auto f = [&](double n) {
        double k = std::fmod(n + h / 30.0, 12.0);
        double a = s * std::min(l, 1.0 - l);
        return l - a * std::max(-1.0, std::min({k - 3.0, 9.0 - k, 1.0}));
    };
    R = static_cast<uint8_t>(f(0)   * 255.0 + 0.5);
    G = static_cast<uint8_t>(f(8)   * 255.0 + 0.5);
    B = static_cast<uint8_t>(f(4)   * 255.0 + 0.5);
}

inline Palette auto_palette(const std::vector<int>& used) {
    Palette p{}; int n = static_cast<int>(used.size()); if (n == 0) n = 1;
    for (int k = 0; k < static_cast<int>(used.size()); ++k) {
        double hue = (double)k / n * 300.0;
        uint8_t r,g,b; hsl_to_rgb(hue, 0.72, 0.60, r, g, b);
        int idx = used[k]; p[idx*3]=r; p[idx*3+1]=g; p[idx*3+2]=b;
    }
    return p;
}

// ---- DDS GRP ---------------------------------------------------------------
// 12-byte header, then per frame {u16 w, u16 h, u32 ddsSize} + blob + u32
// trailer. Frames carry NO x/y offset — placement comes from the caller (icon
// box, wireframe cell), never from the container.
inline Sprite load_dds_grp(const std::vector<uint8_t>& d) {
    using namespace detail;
    const size_t N = d.size();
    Sprite s; s.kind = Sprite::Kind::DdsGRP; s.label = "SC:R DDS GRP (DXT1/DXT5)";
    if (N < 12) return s;
    s.frameCount = rd16(d.data(), 4);
    s.frames.reserve(s.frameCount);
    size_t o = 12;
    for (int i = 0; i < s.frameCount; ++i) {
        if (o + 8 > N) { s.frameCount = static_cast<int>(s.frames.size()); break; }
        Frame f;
        f.w = rd16(d.data(), o); f.h = rd16(d.data(), o+2);
        const uint32_t size = rd32(d.data(), o+4);
        o += 8;
        if (o + size > N) { s.frameCount = static_cast<int>(s.frames.size()); break; }
        int dw = 0, dh = 0;
        auto rgba = decode_dds(d.data() + o, size, dw, dh);
        f.image = Image(dw ? dw : f.w, dh ? dh : f.h);
        if (!rgba.empty()) f.image.rgba = std::move(rgba);
        o += size;
        o += 4;                                  // per-frame trailer (observed 0)
        s.maxW = std::max(s.maxW, f.image.w);
        s.maxH = std::max(s.maxH, f.image.h);
        s.frames.push_back(std::move(f));
    }
    return s;
}

// ---- format sniff ----------------------------------------------------------
enum class GrpKind { Classic, Dds, Anim, Unknown };

inline GrpKind sniff(const std::vector<uint8_t>& d) {
    if (d.size() >= 4 && d[0]=='A'&&d[1]=='N'&&d[2]=='I'&&d[3]=='M') return GrpKind::Anim;
    if (d.size() >= 8) {
        uint32_t first = detail::rd32(d.data(), 0);
        if (first == d.size()) return GrpKind::Dds;   // fileSize field self-references
        return GrpKind::Classic;
    }
    return GrpKind::Unknown;
}

} // namespace scgrp
