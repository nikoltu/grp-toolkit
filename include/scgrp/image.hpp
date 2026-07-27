// scgrp/image.hpp — tiny RGBA8 image container + dependency-free PNG writer.
#include <algorithm>
// The PNG writer uses stored (uncompressed) DEFLATE blocks so it needs no
// zlib. Fine for tooling / debugging exports; not size-optimised.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace scgrp {

struct Image {
    int w = 0, h = 0;
    std::vector<uint8_t> rgba;  // w*h*4, row-major, straight alpha

    Image() = default;
    Image(int W, int H) : w(W), h(H), rgba(static_cast<size_t>(W) * H * 4, 0) {}

    uint8_t* px(int x, int y) { return &rgba[(static_cast<size_t>(y) * w + x) * 4]; }
    const uint8_t* px(int x, int y) const { return &rgba[(static_cast<size_t>(y) * w + x) * 4]; }

    // Alpha-composite `src` onto this image at (ox, oy).
    void blit(const Image& src, int ox, int oy) {
        for (int y = 0; y < src.h; ++y) {
            int dy = oy + y; if (dy < 0 || dy >= h) continue;
            for (int x = 0; x < src.w; ++x) {
                int dx = ox + x; if (dx < 0 || dx >= w) continue;
                const uint8_t* s = src.px(x, y);
                uint8_t* d = px(dx, dy);
                uint32_t sa = s[3];
                if (sa == 0) continue;
                if (sa == 255) { std::memcpy(d, s, 4); continue; }
                for (int i = 0; i < 3; ++i)
                    d[i] = static_cast<uint8_t>((s[i] * sa + d[i] * (255 - sa)) / 255);
                d[3] = static_cast<uint8_t>(sa + d[3] * (255 - sa) / 255);
            }
        }
    }
};

namespace detail {

inline uint32_t crc32(const uint8_t* data, size_t len, uint32_t crc = 0xFFFFFFFFu) {
    static uint32_t table[256];
    static bool init = false;
    if (!init) {
        for (uint32_t n = 0; n < 256; ++n) {
            uint32_t c = n;
            for (int k = 0; k < 8; ++k) c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
            table[n] = c;
        }
        init = true;
    }
    for (size_t i = 0; i < len; ++i) crc = table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    return crc;
}

inline uint32_t adler32(const uint8_t* data, size_t len) {
    uint32_t a = 1, b = 0;
    for (size_t i = 0; i < len; ++i) { a = (a + data[i]) % 65521; b = (b + a) % 65521; }
    return (b << 16) | a;
}

inline void put32be(std::vector<uint8_t>& v, uint32_t x) {
    v.push_back(x >> 24); v.push_back((x >> 16) & 0xFF);
    v.push_back((x >> 8) & 0xFF); v.push_back(x & 0xFF);
}

inline void chunk(std::vector<uint8_t>& out, const char* type, const std::vector<uint8_t>& data) {
    put32be(out, static_cast<uint32_t>(data.size()));
    size_t start = out.size();
    out.insert(out.end(), type, type + 4);
    out.insert(out.end(), data.begin(), data.end());
    uint32_t crc = crc32(out.data() + start, out.size() - start) ^ 0xFFFFFFFFu;
    put32be(out, crc);
}

} // namespace detail

// Write RGBA8 image as PNG. Returns true on success.
inline bool write_png(const std::string& path, const Image& img) {
    using namespace detail;
    std::vector<uint8_t> out = {0x89,'P','N','G',0x0D,0x0A,0x1A,0x0A};

    std::vector<uint8_t> ihdr;
    put32be(ihdr, img.w); put32be(ihdr, img.h);
    ihdr.push_back(8);   // bit depth
    ihdr.push_back(6);   // colour type RGBA
    ihdr.push_back(0); ihdr.push_back(0); ihdr.push_back(0);
    chunk(out, "IHDR", ihdr);

    // raw scanlines with filter byte 0
    std::vector<uint8_t> raw;
    raw.reserve(static_cast<size_t>(img.h) * (img.w * 4 + 1));
    for (int y = 0; y < img.h; ++y) {
        raw.push_back(0);
        const uint8_t* row = img.px(0, y);
        raw.insert(raw.end(), row, row + static_cast<size_t>(img.w) * 4);
    }

    // zlib stream: header + stored DEFLATE blocks + adler32
    std::vector<uint8_t> z;
    z.push_back(0x78); z.push_back(0x01);
    size_t off = 0;
    while (off < raw.size()) {
        size_t n = std::min<size_t>(65535, raw.size() - off);
        bool last = (off + n >= raw.size());
        z.push_back(last ? 1 : 0);
        z.push_back(n & 0xFF); z.push_back((n >> 8) & 0xFF);
        uint16_t nn = static_cast<uint16_t>(~n);
        z.push_back(nn & 0xFF); z.push_back((nn >> 8) & 0xFF);
        z.insert(z.end(), raw.begin() + off, raw.begin() + off + n);
        off += n;
    }
    uint32_t ad = adler32(raw.data(), raw.size());
    put32be(z, ad);
    chunk(out, "IDAT", z);
    chunk(out, "IEND", {});

    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    std::fwrite(out.data(), 1, out.size(), f);
    std::fclose(f);
    return true;
}

} // namespace scgrp
