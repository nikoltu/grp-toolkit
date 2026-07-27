// viewer — SDL2 viewer for StarCraft classic GRP, SC:R DDS GRP and .anim.
//
//   viewer <file.grp|file.anim> [more files...] [--pal palette.pal]
//
// Keys:
//   Left / Right   previous / next frame
//   Space          play / pause animation
//   + / -          zoom in / out
//   [ / ]          slower / faster playback
//   b              cycle background (checker / black / white / magenta)
//   g              toggle grid overview <-> single-frame view
//   Tab            next loaded file
//   o              use frame X/Y offset when compositing (on by default)
//   Esc / q        quit
#include "scgrp/grp.hpp"
#include "scgrp/anim.hpp"
#include <SDL2/SDL.h>
#include <fstream>
#include <vector>
#include <string>
#include <cmath>

using namespace scgrp;

static std::vector<uint8_t> slurp(const std::string& p) {
    std::ifstream f(p, std::ios::binary);
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), {});
}
static Palette load_pal(const std::string& p) {
    auto b = slurp(p); Palette pal{};
    if (b.size() >= 768) { for (int i = 0; i < 768; ++i) pal[i] = b[i]; return pal; }
    return grayscale_palette();
}

static SDL_Texture* to_texture(SDL_Renderer* r, const Image& img) {
    if (img.w <= 0 || img.h <= 0) return nullptr;
    SDL_Texture* t = SDL_CreateTexture(r, SDL_PIXELFORMAT_ABGR8888,
                                       SDL_TEXTUREACCESS_STATIC, img.w, img.h);
    SDL_SetTextureBlendMode(t, SDL_BLENDMODE_BLEND);
    SDL_UpdateTexture(t, nullptr, img.rgba.data(), img.w * 4);
    return t;
}

struct Loaded { std::string name; Sprite sprite; std::vector<SDL_Texture*> tex; };

int main(int argc, char** argv) {
    if (argc < 2) { SDL_Log("usage: viewer <file> [files...] [--pal p]"); return 1; }
    std::vector<std::string> inputs; std::string palPath;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--pal" && i + 1 < argc) palPath = argv[++i];
        else inputs.push_back(a);
    }

    if (SDL_Init(SDL_INIT_VIDEO) != 0) { SDL_Log("SDL init: %s", SDL_GetError()); return 1; }
    SDL_Window* win = SDL_CreateWindow("GRP Viewer",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 1100, 720,
        SDL_WINDOW_RESIZABLE);
    SDL_Renderer* ren = SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED);
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "0");  // nearest — pixel art

    std::vector<Loaded> files;
    for (auto& in : inputs) {
        auto data = slurp(in);
        if (data.empty()) { SDL_Log("skip (unreadable): %s", in.c_str()); continue; }
        Sprite s;
        switch (sniff(data)) {
            case GrpKind::Dds:     s = load_dds_grp(data); break;
            case GrpKind::Anim:    s = load_anim(data); break;
            case GrpKind::Classic: {
                Palette pal = palPath.empty() ? auto_palette(classic_used_indices(data))
                                              : load_pal(palPath);
                s = load_classic_grp(data, pal); break;
            }
            default: SDL_Log("skip (unknown): %s", in.c_str()); continue;
        }
        Loaded L; L.name = in; L.sprite = std::move(s);
        for (auto& f : L.sprite.frames) L.tex.push_back(to_texture(ren, f.image));
        files.push_back(std::move(L));
        SDL_Log("loaded %s [%s] frames=%d", in.c_str(), files.back().sprite.label.c_str(),
                files.back().sprite.frameCount);
    }
    if (files.empty()) { SDL_Log("nothing to show"); return 1; }

    int cur = 0, frame = 0, zoom = 3, bgMode = 0, delayMs = 83; // ~12 fps
    bool playing = false, grid = true, useOffset = true;
    Uint32 lastTick = SDL_GetTicks();

    auto setBg = [&](int m) {
        switch (m) {
            case 0: SDL_SetRenderDrawColor(ren, 13, 20, 32, 255); break;   // dark
            case 1: SDL_SetRenderDrawColor(ren, 0, 0, 0, 255); break;
            case 2: SDL_SetRenderDrawColor(ren, 255, 255, 255, 255); break;
            case 3: SDL_SetRenderDrawColor(ren, 255, 0, 255, 255); break;  // chroma
        }
    };

    bool run = true;
    while (run) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) run = false;
            else if (e.type == SDL_KEYDOWN) {
                Sprite& sp = files[cur].sprite;
                switch (e.key.keysym.sym) {
                    case SDLK_ESCAPE: case SDLK_q: run = false; break;
                    case SDLK_RIGHT: frame = (frame + 1) % sp.frameCount; break;
                    case SDLK_LEFT:  frame = (frame - 1 + sp.frameCount) % sp.frameCount; break;
                    case SDLK_SPACE: playing = !playing; break;
                    case SDLK_PLUS: case SDLK_EQUALS: zoom = std::min(zoom + 1, 12); break;
                    case SDLK_MINUS: zoom = std::max(zoom - 1, 1); break;
                    case SDLK_LEFTBRACKET:  delayMs = std::min(delayMs + 10, 500); break;
                    case SDLK_RIGHTBRACKET: delayMs = std::max(delayMs - 10, 20); break;
                    case SDLK_b: bgMode = (bgMode + 1) % 4; break;
                    case SDLK_g: grid = !grid; break;
                    case SDLK_o: useOffset = !useOffset; break;
                    case SDLK_TAB: cur = (cur + 1) % (int)files.size(); frame = 0; break;
                }
            }
        }
        if (playing && SDL_GetTicks() - lastTick >= (Uint32)delayMs) {
            frame = (frame + 1) % files[cur].sprite.frameCount;
            lastTick = SDL_GetTicks();
        }

        setBg(bgMode); SDL_RenderClear(ren);
        Loaded& L = files[cur]; Sprite& sp = L.sprite;
        int winW, winH; SDL_GetWindowSize(win, &winW, &winH);

        if (grid) {
            int cw = std::max(1, sp.maxW), ch = std::max(1, sp.maxH);
            int z = std::max(1, std::min(4, zoom));
            int cellW = cw * z + 8, cellH = ch * z + 8;
            int cols = std::max(1, winW / cellW);
            for (int i = 0; i < sp.frameCount; ++i) {
                if (!L.tex[i]) continue;
                Frame& f = sp.frames[i];
                int gx = (i % cols) * cellW + 4, gy = (i / cols) * cellH + 4;
                SDL_Rect dst{ gx + f.x * z, gy + f.y * z, f.image.w * z, f.image.h * z };
                SDL_RenderCopy(ren, L.tex[i], nullptr, &dst);
                if (i == frame) {  // highlight selected
                    SDL_SetRenderDrawColor(ren, 79, 227, 196, 255);
                    SDL_Rect box{ gx - 1, gy - 1, cw * z + 2, ch * z + 2 };
                    SDL_RenderDrawRect(ren, &box);
                }
            }
        } else {
            if (L.tex[frame]) {
                Frame& f = sp.frames[frame];
                int ox = useOffset ? f.x : (sp.maxW - f.image.w) / 2;
                int oy = useOffset ? f.y : (sp.maxH - f.image.h) / 2;
                int baseX = (winW - sp.maxW * zoom) / 2;
                int baseY = (winH - sp.maxH * zoom) / 2;
                SDL_Rect dst{ baseX + ox * zoom, baseY + oy * zoom,
                              f.image.w * zoom, f.image.h * zoom };
                SDL_RenderCopy(ren, L.tex[frame], nullptr, &dst);
            }
        }

        // title bar telemetry
        char title[256];
        std::snprintf(title, sizeof(title), "GRP Viewer  |  %s  |  frame %d/%d  |  %s  |  zoom %dx  %s",
                      L.name.c_str(), frame, sp.frameCount - 1, sp.label.c_str(), zoom,
                      playing ? "[PLAY]" : "");
        SDL_SetWindowTitle(win, title);

        SDL_RenderPresent(ren);
        SDL_Delay(8);
    }

    for (auto& L : files) for (auto* t : L.tex) if (t) SDL_DestroyTexture(t);
    SDL_DestroyRenderer(ren); SDL_DestroyWindow(win); SDL_Quit();
    return 0;
}
