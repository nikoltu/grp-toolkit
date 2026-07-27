// grp2png — decode a .grp (classic or SC:R DDS) or .anim to PNG.
// Usage:
//   grp2png <input> [output.png] [--pal file] [--sheet|--frame N|--all outdir]
//   grp2png <input.grp>  --dump-idx  <out.grpi>   palette indices, no colour
//   grp2png <input>      --dump-argb <out.argb> [--frame N] [--layer N]
// Default: writes a padded sprite-sheet PNG next to the input.
// The --dump-* modes emit neutral, diffable artefacts for comparison against
// an independent decoder; follow the independence rule.
#include "scgrp/grp.hpp"
#include "scgrp/anim.hpp"
#include "scgrp/dump.hpp"
#include <cstdio>
#include <fstream>
#include <string>
#include <cmath>

using namespace scgrp;

static std::vector<uint8_t> slurp(const std::string& p) {
    std::ifstream f(p, std::ios::binary);
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), {});
}

static Palette load_palette_file(const std::string& p) {
    auto b = slurp(p);
    Palette pal{};
    if (b.size() >= 8 && std::string((char*)b.data(),8) == "JASC-PAL") {
        // text JASC-PAL
        std::string s((char*)b.data(), b.size());
        size_t pos = 0; int line = 0, idx = 0;
        while (pos < s.size() && idx < 256) {
            size_t nl = s.find('\n', pos); std::string ln = s.substr(pos, nl-pos);
            pos = (nl==std::string::npos)? s.size() : nl+1;
            if (++line <= 3) continue;
            int r,g,bl; if (std::sscanf(ln.c_str(), "%d %d %d", &r,&g,&bl)==3) {
                pal[idx*3]=r; pal[idx*3+1]=g; pal[idx*3+2]=bl; ++idx;
            }
        }
        return pal;
    }
    // Tileset .wpe: 256 RGBA quads, not RGB triples. Reading the first 768
    // bytes straight would shear every colour by the alpha bytes.
    if (b.size() == 1024) {
        for (int i = 0; i < 256; ++i) {
            pal[i*3] = b[i*4]; pal[i*3+1] = b[i*4+1]; pal[i*3+2] = b[i*4+2];
        }
        return pal;
    }
    // PCX with a VGA palette in the trailer (0x0C marker + 768 bytes): this is
    // where ticon.pcx / twire.pcx / tunit.pcx keep their colours.
    if (b.size() > 769 && b[b.size()-769] == 0x0C) {
        for (int i = 0; i < 768; ++i) pal[i] = b[b.size()-768+i];
        return pal;
    }
    if (b.size() == 772) { for (int i=0;i<768;++i) pal[i]=b[i]; return pal; }   // .act
    if (b.size() >= 768) { for (int i=0;i<768;++i) pal[i]=b[i]; return pal; }   // raw
    return grayscale_palette();
}

static Sprite make_sheet(const Sprite& s, Image& sheet) {
    int cols = static_cast<int>(std::ceil(std::sqrt((double)s.frameCount)));
    int rows = (s.frameCount + cols - 1) / cols;
    int cw = std::max(1, s.maxW), ch = std::max(1, s.maxH);
    sheet = Image(cols*cw, rows*ch);
    for (int i = 0; i < s.frameCount; ++i) {
        const Frame& f = s.frames[i];
        sheet.blit(f.image, (i%cols)*cw + f.x, (i/cols)*ch + f.y);
    }
    return s;
}

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: grp2png <in> [out.png] [--pal p] [--frame N] [--sheet]\n"); return 1; }
    std::string in = argv[1], out; std::string palPath; int frameN = -1; bool sheet = true; int layerN = -1;
    std::string dumpIdx, dumpArgb;
    for (int i = 2; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--pal" && i+1 < argc) palPath = argv[++i];
        else if (a == "--frame" && i+1 < argc) { frameN = std::atoi(argv[++i]); sheet = false; }
        else if (a == "--layer" && i+1 < argc) layerN = std::atoi(argv[++i]);
        else if (a == "--dump-idx" && i+1 < argc) dumpIdx = argv[++i];
        else if (a == "--dump-argb" && i+1 < argc) dumpArgb = argv[++i];
        else if (a == "--sheet") sheet = true;
        else if (out.empty()) out = a;
    }
    if (out.empty()) out = in.substr(0, in.find_last_of('.')) + ".png";

    auto data = slurp(in);
    if (data.empty()) { std::fprintf(stderr, "cannot read %s\n", in.c_str()); return 1; }

    // ---- neutral index dump: decoding stops before any palette is applied ----
    if (!dumpIdx.empty()) {
        if (sniff(data) != GrpKind::Classic) {
            std::fprintf(stderr, "--dump-idx needs a classic .grp (indices); this is not one\n");
            return 1;
        }
        IndexSprite ix = load_classic_indices(data);
        if (!ix.ok) { std::fprintf(stderr, "invalid classic GRP header\n"); return 1; }
        dump::print_index_report(ix);
        if (!dump::write_grpi(dumpIdx, ix)) { std::fprintf(stderr, "cannot write %s\n", dumpIdx.c_str()); return 1; }
        std::printf("wrote %s\n", dumpIdx.c_str());
        return 0;
    }

    Sprite s;
    switch (sniff(data)) {
        case GrpKind::Dds:     s = load_dds_grp(data); break;
        case GrpKind::Anim:    s = load_anim(data); break;
        case GrpKind::Classic: {
            Palette pal = palPath.empty() ? auto_palette(classic_used_indices(data))
                                          : load_palette_file(palPath);
            s = load_classic_grp(data, pal);
            break;
        }
        default: std::fprintf(stderr, "unknown format\n"); return 1;
    }
    std::printf("[%s] %s  frames=%d  canvas=%dx%d\n",
                s.label.c_str(), in.c_str(), s.frameCount, s.maxW, s.maxH);

    // for ANIM, optionally re-slice all frames from a non-diffuse layer
    if (s.kind == Sprite::Kind::AnimHD && layerN > 0 && layerN < (int)s.layerAtlas.size()) {
        for (size_t i = 0; i < s.frames.size(); ++i)
            s.frames[i].image = anim_layer_frame(s, layerN, i);
        std::printf("using layer %d (%s)\n", layerN, s.layers[layerN].c_str());
    }

    // ---- neutral true-colour dump: the decoded texture BEFORE any rescale ----
    if (!dumpArgb.empty()) {
        const Image* src = nullptr;
        if (s.kind == Sprite::Kind::AnimHD) {
            const int li = layerN > 0 ? layerN : 0;      // atlas, not a sliced frame
            if (li >= (int)s.layerAtlas.size()) { std::fprintf(stderr, "no layer %d\n", li); return 1; }
            src = &s.layerAtlas[li];
            std::printf("dumping .anim atlas, layer %d (%s)\n", li, s.layers[li].c_str());
        } else {
            const int fi = frameN >= 0 ? frameN : 0;
            if (fi >= s.frameCount) { std::fprintf(stderr, "no frame %d\n", fi); return 1; }
            src = &s.frames[fi].image;
            std::printf("dumping frame %d\n", fi);
        }
        if (!dump::write_argb(dumpArgb, *src)) { std::fprintf(stderr, "cannot write %s\n", dumpArgb.c_str()); return 1; }
        std::printf("wrote %s (%dx%d)\n", dumpArgb.c_str(), src->w, src->h);
        return 0;
    }

    if (!sheet && frameN >= 0 && frameN < s.frameCount) {
        write_png(out, s.frames[frameN].image);
        std::printf("wrote frame %d -> %s\n", frameN, out.c_str());
    } else {
        Image sh; make_sheet(s, sh);
        write_png(out, sh);
        std::printf("wrote sheet %dx%d -> %s\n", sh.w, sh.h, out.c_str());
    }
    return 0;
}
