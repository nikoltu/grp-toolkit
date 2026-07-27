// scgrp/anim.hpp — StarCraft: Remastered ".anim" sprite files.
//
// Format VALIDATED byte-exact against a retail HD anim (main_000.anim,
// version 0x0204). Layout (little-endian):
//
//   Header (0x0C bytes):
//     0x00  char[4]  "ANIM"
//     0x04  u16      version        (0x0204 HD)
//     0x06  u16      unused
//     0x08  u16      layerCount     (e.g. 7)
//     0x0A  u16      entryCount     (number of sprite entries; per-image = 1)
//   Layer-name table: 10 slots x 32 bytes = 320 bytes (0x0C .. 0x14C).
//     Names in use: diffuse, bright, teamcolor, emissive, normal, specular,
//     ao_depth (unused slots zeroed).
//   Entry table: entryCount x 12 bytes, starting at 0x14C:
//     u16 frameCount, u16 unused(0xFFFF), u16 refWidth, u16 refHeight,
//     u32 frameTableOffset   (absolute file offset, usually near EOF)
//   TexRef table: layerCount x 12 bytes {u32 ddsOffset, u32 ddsSize,
//     u16 width, u16 height}. ddsOffset 0 => layer absent for this file.
//   ... embedded DDS blobs (DXT1/DXT5) ...
//   Frame table (at frameTableOffset): frameCount x 16 bytes:
//     u16 atlasX, u16 atlasY, i16 xOffset, i16 yOffset, u16 w, u16 h,
//     u32 flags/pageIndex   (=1 in observed files)
//
// Every layer shares the same frame rects; only the source atlas differs.
// The DXT decode path is the same one validated for DDS GRP.
#pragma once
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "grp.hpp"
#include "dxt.hpp"

namespace scgrp {

namespace detail {
inline int16_t rd16s(const uint8_t* d, size_t o){ return static_cast<int16_t>(rd16(d,o)); }
} // namespace detail

// crop an atlas image to (x,y,w,h) into a fresh RGBA image
inline Image crop_image(const Image& atlas, int x, int y, int w, int h) {
    Image out(w, h);
    if (x < 0 || y < 0 || x + w > atlas.w || y + h > atlas.h) return out;
    for (int ry = 0; ry < h; ++ry)
        std::memcpy(out.px(0, ry), atlas.px(x, y + ry), static_cast<size_t>(w) * 4);
    return out;
}

// Fallback for unexpected files: locate textures by scanning the "DDS " magic.
inline std::vector<size_t> find_dds_blocks(const std::vector<uint8_t>& d) {
    std::vector<size_t> offs;
    for (size_t i = 0; i + 4 <= d.size(); ++i)
        if (d[i]=='D'&&d[i+1]=='D'&&d[i+2]=='S'&&d[i+3]==' ') offs.push_back(i);
    return offs;
}

inline Sprite load_anim(const std::vector<uint8_t>& d) {
    using namespace detail;
    Sprite s; s.kind = Sprite::Kind::AnimHD;
    const uint8_t* b = d.data();
    uint16_t version   = d.size() >= 6  ? rd16(b, 4) : 0;
    uint16_t layerCount= d.size() >= 10 ? rd16(b, 8) : 0;
    uint16_t entryCount= d.size() >= 12 ? rd16(b, 10) : 0;
    s.label = "SC:R ANIM v" + std::to_string(version >> 8) + "." + std::to_string(version & 0xFF);

    const size_t NAME_TABLE = 0x0C;
    const size_t nameSlots = 10;
    size_t entryOff = NAME_TABLE + nameSlots * 32;              // 0x14C
    size_t texRefOff = entryOff + static_cast<size_t>(entryCount) * 12;

    // sanity: if the layout looks wrong, fall back to a raw texture dump
    bool ok = layerCount > 0 && layerCount <= nameSlots && entryCount > 0 &&
              texRefOff + static_cast<size_t>(layerCount) * 12 <= d.size();
    if (!ok) {
        auto offs = find_dds_blocks(d);
        for (size_t o : offs) {
            int w=0,h=0; auto rgba = decode_dds(b + o, d.size() - o, w, h);
            if (rgba.empty()) continue;
            Frame f; f.w=w; f.h=h; f.image=Image(w,h); f.image.rgba=std::move(rgba);
            s.maxW=std::max(s.maxW,w); s.maxH=std::max(s.maxH,h); s.frames.push_back(std::move(f));
        }
        s.frameCount = static_cast<int>(s.frames.size());
        s.label += " (raw atlas view — unexpected layout)";
        return s;
    }

    // layer names
    std::vector<std::string> names;
    for (size_t i = 0; i < layerCount; ++i) {
        const char* p = reinterpret_cast<const char*>(b + NAME_TABLE + i * 32);
        names.emplace_back(p, ::strnlen(p, 32));
    }
    // texture refs -> decode each present layer's atlas
    for (uint16_t i = 0; i < layerCount; ++i) {
        size_t o = texRefOff + static_cast<size_t>(i) * 12;
        uint32_t ddsOff = rd32(b, o), ddsSize = rd32(b, o + 4);
        if (ddsOff == 0 || ddsSize == 0 || ddsOff + 4 > d.size()) continue;
        int w=0,h=0; auto rgba = decode_dds(b + ddsOff, ddsSize, w, h);
        if (rgba.empty()) continue;
        Image atlas(w, h); atlas.rgba = std::move(rgba);
        s.layers.push_back(names[i]);
        s.layerAtlas.push_back(std::move(atlas));
    }
    if (s.layerAtlas.empty()) { s.label += " (no decodable layers)"; return s; }
    const Image& diffuse = s.layerAtlas.front();

    // entries -> frame rects (all entries concatenated)
    for (uint16_t e = 0; e < entryCount; ++e) {
        size_t eo = entryOff + static_cast<size_t>(e) * 12;
        uint16_t frameCount = rd16(b, eo);
        uint32_t ft = rd32(b, eo + 8);
        if (ft + static_cast<size_t>(frameCount) * 16 > d.size()) continue;
        for (uint16_t i = 0; i < frameCount; ++i) {
            size_t o = ft + static_cast<size_t>(i) * 16;
            Sprite::Rect r;
            r.ax = rd16(b, o);      r.ay = rd16(b, o + 2);
            r.xoff = rd16s(b, o + 4); r.yoff = rd16s(b, o + 6);
            r.w = rd16(b, o + 8);   r.h = rd16(b, o + 10);
            if (r.w <= 0 || r.h <= 0 || r.ax + r.w > diffuse.w || r.ay + r.h > diffuse.h) continue;
            Frame f; f.x = r.xoff; f.y = r.yoff; f.w = r.w; f.h = r.h;
            f.image = crop_image(diffuse, r.ax, r.ay, r.w, r.h);
            s.rects.push_back(r);
            s.maxW = std::max(s.maxW, r.xoff + r.w);
            s.maxH = std::max(s.maxH, r.yoff + r.h);
            s.frames.push_back(std::move(f));
        }
    }
    s.frameCount = static_cast<int>(s.frames.size());
    if (s.maxW <= 0) s.maxW = diffuse.w;
    if (s.maxH <= 0) s.maxH = diffuse.h;

    std::string layerList;
    for (size_t i = 0; i < s.layers.size(); ++i) layerList += (i?",":"") + s.layers[i];
    s.label += " \xC2\xB7 " + std::to_string(s.layers.size()) + " layers [" + layerList + "] \xC2\xB7 "
             + std::to_string(s.frameCount) + " frames \xC2\xB7 atlas "
             + std::to_string(diffuse.w) + "x" + std::to_string(diffuse.h);
    return s;
}

// Slice frame `frameIdx` from a specific layer atlas (e.g. teamcolor, normal).
inline Image anim_layer_frame(const Sprite& s, size_t layerIdx, size_t frameIdx) {
    if (layerIdx >= s.layerAtlas.size() || frameIdx >= s.rects.size()) return {};
    const auto& r = s.rects[frameIdx];
    return crop_image(s.layerAtlas[layerIdx], r.ax, r.ay, r.w, r.h);
}

} // namespace scgrp
