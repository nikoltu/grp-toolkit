// scgrp/dump.hpp — neutral, diffable dumps for cross-implementation checking.
//
// These formats exist so two independent decoders can be compared with `fc /b`
// or a hash instead of by eye. Nothing here applies a palette or rescales:
// GRPI carries raw palette indices, ARGB carries the decoded texture *before*
// any downscale. Full spec (and why we do not share decoder code across
// implementations): see CLAUDE.md §7.5
#pragma once
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include "grp.hpp"
#include "image.hpp"

namespace scgrp {
namespace dump {

namespace detail {
inline void put16(std::vector<uint8_t>& v, uint16_t x) {
    v.push_back(static_cast<uint8_t>(x & 0xff));
    v.push_back(static_cast<uint8_t>(x >> 8));
}
inline void put32(std::vector<uint8_t>& v, uint32_t x) {
    v.push_back(static_cast<uint8_t>(x & 0xff));
    v.push_back(static_cast<uint8_t>((x >> 8) & 0xff));
    v.push_back(static_cast<uint8_t>((x >> 16) & 0xff));
    v.push_back(static_cast<uint8_t>(x >> 24));
}
inline bool spill(const std::string& path, const std::vector<uint8_t>& v) {
    std::FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    const bool ok = v.empty() || std::fwrite(v.data(), 1, v.size(), f) == v.size();
    std::fclose(f);
    return ok;
}
} // namespace detail

// GRPI v1 — every frame as an expanded index grid (not the RLE stream: that
// would compare normalisation policy rather than content).
inline bool write_grpi(const std::string& path, const IndexSprite& s) {
    using namespace detail;
    std::vector<uint8_t> v;
    v.insert(v.end(), {'G', 'R', 'P', 'I'});
    put16(v, 1);
    put16(v, static_cast<uint16_t>(s.frames.size()));
    put16(v, static_cast<uint16_t>(s.canvasW));
    put16(v, static_cast<uint16_t>(s.canvasH));
    put32(v, 0);
    for (const IndexFrame& f : s.frames) {
        put16(v, static_cast<uint16_t>(f.x));
        put16(v, static_cast<uint16_t>(f.y));
        put16(v, static_cast<uint16_t>(f.w));
        put16(v, static_cast<uint16_t>(f.h));
        put16(v, f.flags);
        put16(v, 0);
        v.insert(v.end(), f.idx.begin(), f.idx.end());
    }
    return spill(path, v);
}

// ARGB v1 — one decoded texture, mip 0, no rescale. RGB of transparent pixels
// is written as the block decoder produced it: zeroing it would hide real
// disagreements in the BC1 transparent-black case.
inline bool write_argb(const std::string& path, const Image& img) {
    using namespace detail;
    std::vector<uint8_t> v;
    v.insert(v.end(), {'A', 'R', 'G', 'B'});
    put16(v, 1);
    put16(v, 0);
    put32(v, static_cast<uint32_t>(img.w));
    put32(v, static_cast<uint32_t>(img.h));
    v.reserve(v.size() + static_cast<size_t>(img.w) * img.h * 4);
    for (size_t i = 0, n = static_cast<size_t>(img.w) * img.h; i < n; ++i) {
        const uint8_t* p = img.rgba.data() + i * 4;      // r,g,b,a
        v.push_back(p[2]); v.push_back(p[1]); v.push_back(p[0]); v.push_back(p[3]);
    }
    return spill(path, v);
}

// Human-readable companion to a GRPI dump: what a diff would be about.
inline void print_index_report(const IndexSprite& s) {
    std::vector<int> hist(256, 0);
    int clamped = 0, bad = 0, shortRow = 0, flat = 0;
    for (const IndexFrame& f : s.frames) {
        if (f.flags & kRowClamped) ++clamped;
        if (f.flags & kOffsetBad)  ++bad;
        if (f.flags & kRowShort)   ++shortRow;
        if (f.flags & kFlatFrame)  ++flat;
        for (uint8_t x : f.idx) ++hist[x];
    }
    std::printf("frames=%zu canvas=%dx%d storage=%s\n",
                s.frames.size(), s.canvasW, s.canvasH, s.flat ? "flat" : "RLE");
    if (clamped || bad || shortRow)
        std::printf("anomalies: clamped=%d badOffset=%d shortRow=%d flat=%d\n",
                    clamped, bad, shortRow, flat);
    std::printf("indices used:");
    int shown = 0;
    for (int i = 1; i < 256; ++i) {
        if (!hist[i]) continue;
        if (shown++ < 24) std::printf(" %d(%d)", i, hist[i]);
    }
    if (shown > 24) std::printf(" ... +%d more", shown - 24);
    std::printf("\n  distinct=%d  transparent px=%d\n", shown, hist[0]);
}

} // namespace dump
} // namespace scgrp
