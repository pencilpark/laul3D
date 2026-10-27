# Third-party notices

Berria Craft is released under the MIT license (see [LICENSE](LICENSE)). Its installers also contain software by
others, listed below with their licenses. Other tools are downloaded by the app at first launch, from their official
sources, and run as separate programs; they are listed at the end.

## Bundled in the installers

| Component | Version | License | In the installed app |
|---|---|---|---|
| Python, standalone build by Astral (python-build-standalone) | 3.11.14 | PSF License 2.0, plus the licenses of the libraries it contains | `python/`, with its `LICENSE.txt` |
| uv | 0.13.5 | MIT OR Apache-2.0, Copyright (c) 2025 Astral Software Inc. | `bin/uv` |
| HelloPhotogrammetry (macOS only) | built from Apple's sample code "Creating a photogrammetry command-line app" | MIT-style license, Copyright © 2025 Apple Inc. (text below); contains Swift Argument Parser, Apache-2.0 | `bin/HelloPhotogrammetry` |
| Python packages | see below | see below | `wheels/`, each wheel with its license files |
| three.js | r160 | MIT, Copyright © 2010-2023 three.js authors | `app/app/static/vendor/three/LICENSE` |
| Jost typeface | 2020 | SIL Open Font License 1.1 | `app/app/static/vendor/jost/LICENSE.txt` |
| TripoSR (source code) | commit 107cefd, 2026-06-04 | MIT, Copyright (c) 2024 Tripo AI & Stability AI | `app/vendor/TripoSR/LICENSE` |
| Tauri and the Rust crates of the app executable | Tauri 2.12.5 | MIT OR Apache-2.0 for Tauri; crates listed below | the Berria Craft executable |

The paths are relative to the app's resources: `Berria Craft.app/Contents/Resources` on macOS, the installation folder
on Windows. This file and the MIT license are copied there too, in `app/`.

### Python packages

Installed at first launch from the wheels shipped with the app (`requirements-core.txt`). Each wheel carries its own
license files in its `.dist-info` folder.

| Package | Version | License |
|---|---|---|
| fastapi | 0.162.0 | MIT |
| starlette | 1.9.0 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| pydantic-core | 2.50.1 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| pillow | 10.1.0 | HPND; the binary wheel bundles brotli, bzip2, FreeType, HarfBuzz, Little CMS, libjpeg-turbo, liblzma, libpng, libtiff, libwebp, OpenJPEG, raqm, libxau, libxcb, libxdmcp and zlib, whose license texts are in its LICENSE file |
| pi-heif | 0.22.0 | BSD-3-Clause; the binary wheel bundles libheif and libde265 as dynamic libraries under LGPL-3.0 (see its LICENSES_bundled.txt; sources at https://github.com/strukturag/libheif and https://github.com/strukturag/libde265) |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| anyio | 4.15.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| annotated-types | 0.8.0 | MIT |
| annotated-doc | 0.0.5 | MIT |
| opentelemetry-api | 1.45.1 | Apache-2.0 |

Versions before 0.5.3 shipped pillow-heif, whose binary wheel also bundles the x265 encoder under GPL-2.0. The app only
decodes HEIC photos: pi-heif, the decoding-only build of the same project, replaces it.

### Rust crates

Linked into the app executable, from `desktop/src-tauri/Cargo.lock` (macOS arm64 and Windows x64 builds together). The
five MPL-2.0 crates are used unmodified; their source is on crates.io.

- MIT OR Apache-2.0 (152): anyhow 1.0.104, base64 0.21.7, base64 0.23.1, bit-set 0.8.0, bit-vec 0.8.0, bitflags 1.3.2, bitflags 2.13.2, block-buffer 0.10.4, bs58 0.5.1, camino 1.2.6, cargo-platform 0.1.9, cfg-if 1.0.5, chrono 0.4.45, cookie 0.18.2, core-foundation 0.10.1, core-foundation-sys 0.8.7, core-graphics 0.25.0, core-graphics-types 0.2.0, cpufeatures 0.2.17, crc32fast 1.5.3, crossbeam-channel 0.5.17, crossbeam-utils 0.8.23, crypto-common 0.1.7, ctor 1.0.13, defmt 1.2.0, defmt-macros 1.2.0, defmt-parser 1.1.0, deranged 0.5.9, digest 0.10.7, dirs 7.0.0, dirs-sys 0.5.0, displaydoc 0.2.7, dtoa 1.0.11, dyn-clone 1.0.20, embed_plist 1.2.2, equivalent 1.0.3, erased-serde 0.4.10, fastrand 2.5.0, fdeflate 0.3.7, flate2 1.1.10, foreign-types 0.5.0, foreign-types-macros 0.2.4, foreign-types-shared 0.3.1, form_urlencoded 1.2.2, getrandom 0.3.4, getrandom 0.4.3, glob 0.3.4, hashbrown 0.12.3, hashbrown 0.17.1, heck 0.5.0, hex 0.4.3, html5ever 0.39.0, http 1.5.0, iana-time-zone 0.1.65, ident_case 1.0.1, idna 1.1.0, idna_adapter 1.2.2, indexmap 1.9.3, indexmap 2.14.2, itoa 1.0.18, json-patch 4.2.0, jsonptr 0.7.1, keyboard-types 0.8.3, libc 0.2.191, lock_api 0.4.14, log 0.4.34, markup5ever 0.39.0, mime 0.3.17, muda 0.20.0, num-conv 0.2.2, num-traits 0.2.19, once_cell 1.21.4, parking_lot 0.12.5, parking_lot_core 0.9.12, percent-encoding 2.3.2, pin-project-lite 0.2.17, png 0.18.1, powerfmt 0.2.1, proc-macro2 1.0.107, quote 1.0.47, ref-cast 1.0.27, ref-cast-impl 1.0.27, regex 1.13.1, regex-automata 0.4.18, regex-syntax 0.8.11, rustc-hash 2.1.3, scopeguard 1.2.0, semver 1.0.28, serde 1.0.229, serde-untagged 0.1.9, serde_core 1.0.229, serde_derive 1.0.229, serde_derive_internals 0.29.1, serde_json 1.0.154, serde_repr 0.1.21, serde_spanned 1.1.2, serde_with 3.24.0, serde_with_macros 3.24.0, serialize-to-javascript 0.1.2, serialize-to-javascript-impl 0.1.2, servo_arc 0.4.3, sha2 0.10.9, siphasher 1.0.4, smallvec 1.16.4, socket2 0.6.5, softbuffer 0.4.8, stable_deref_trait 1.2.1, string_cache 0.9.0, swift-rs 1.0.9, syn 2.0.119, syn 3.0.9, tauri 2.12.5, tauri-codegen 2.7.4, tauri-macros 2.7.4, tauri-plugin-single-instance 2.5.4, tauri-runtime 2.12.2, tauri-runtime-wry 2.12.3, tauri-utils 2.10.2, tendril 0.5.1, thiserror 2.0.21, thiserror-impl 2.0.21, time 0.3.55, time-core 0.1.9, time-macros 0.2.32, toml 1.1.8+spec-1.1.0, toml_datetime 1.1.2+spec-1.1.0, toml_parser 1.1.5+spec-1.1.0, toml_writer 1.1.3+spec-1.1.0, tray-icon 0.25.1, typeid 1.0.3, typenum 1.20.1, unicode-segmentation 1.13.3, url 2.5.8, utf8_iter 1.0.4, uuid 1.29.0, web-time 1.1.0, web_atoms 0.2.6, window-vibrancy 0.8.1, windows 0.62.2, windows-collections 0.3.2, windows-core 0.62.2, windows-future 0.3.2, windows-implement 0.60.2, windows-interface 0.59.3, windows-link 0.2.1, windows-numerics 0.3.1, windows-result 0.4.1, windows-strings 0.5.1, windows-sys 0.61.2, windows-threading 0.2.1, windows-version 0.1.7, wry 0.57.1
- MIT (42): block2 0.6.2, bytes 1.12.1, cargo_metadata 0.19.2, cfb 0.14.0, darling 0.24.1, darling_core 0.24.1, darling_macro 0.24.1, derive_more 2.1.1, derive_more-impl 2.1.1, dom_query 0.28.0, generic-array 0.14.7, ico 0.6.0, infer 0.22.0, mio 1.2.4, new_debug_unreachable 1.0.6, objc2 0.6.5, objc2-encode 4.1.0, objc2-foundation 0.3.2, phf 0.13.1, phf_generator 0.13.1, phf_macros 0.13.1, phf_shared 0.13.1, plist 1.10.3, precomputed-hash 0.1.1, quick-xml 0.42.0, schemars 0.8.22, schemars 0.9.0, schemars 1.2.3, schemars_derive 0.8.22, simd-adler32 0.3.10, strsim 0.11.1, synstructure 0.14.0, tokio 1.54.1, tracing 0.1.44, tracing-attributes 0.1.31, tracing-core 0.1.36, urlpattern 0.6.0, webview2-com 0.39.1, webview2-com-macros 0.8.1, webview2-com-sys 0.39.1, winnow 1.0.4, zmij 1.0.23
- Unicode-3.0 (18): icu_collections 2.4.0, icu_locale_core 2.4.0, icu_normalizer 2.4.0, icu_normalizer_data 2.4.0, icu_properties 2.4.0, icu_properties_data 2.4.0, icu_provider 2.4.0, litemap 0.8.3, potential_utf 0.1.6, tinystr 0.8.5, writeable 0.6.4, yoke 0.8.4, yoke-derive 0.8.4, zerofrom 0.1.8, zerofrom-derive 0.1.8, zerotrie 0.2.5, zerovec 0.11.9, zerovec-derive 0.11.7
- Unlicense OR MIT (10): aho-corasick 1.1.5, byteorder 1.5.0, jiff 0.2.38, jiff-core 0.1.1, jiff-tzdb 0.1.9, jiff-tzdb-platform 0.1.3, memchr 2.8.3, same-file 1.0.6, walkdir 2.5.0, winapi-util 0.1.11
- Zlib OR MIT OR Apache-2.0 (9): dispatch2 0.3.1, objc2-app-kit 0.3.2, objc2-core-foundation 0.3.2, objc2-core-graphics 0.3.2, objc2-exception-helper 0.1.1, objc2-io-surface 0.3.2, objc2-quartz-core 0.3.2, objc2-web-kit 0.3.2, tinyvec 1.13.3
- MPL-2.0 (5): cssparser 0.37.0, cssparser-macros 0.7.1, dtoa-short 0.3.5, option-ext 0.2.0, selectors 0.38.0
- BSD-3-Clause (2): alloc-no-stdlib 3.0.0, alloc-stdlib 0.3.0
- MIT OR Zlib OR Apache-2.0 (2): miniz_oxide 0.8.9, miniz_oxide 0.9.1
- Zlib (2): foldhash 0.2.0, zlib-rs 0.6.8
- (MIT OR Apache-2.0) AND Unicode-3.0 (1): unicode-ident 1.0.27
- 0BSD OR MIT OR Apache-2.0 (1): adler2 2.0.1
- Apache-2.0 (1): tao 0.37.2
- Apache-2.0  OR MIT (1): fnv 1.0.7
- Apache-2.0 AND MIT (1): dpi 0.1.2
- BSD-3-Clause AND MIT (1): brotli 9.0.0
- BSD-3-Clause OR MIT (1): brotli-decompressor 6.0.1
- CC0-1.0 OR MIT-0 OR Apache-2.0 (1): dunce 1.0.5
- MIT OR Apache-2.0 OR Zlib (1): raw-window-handle 0.6.2

### HelloPhotogrammetry license

Copyright © 2025 Apple Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Swift Argument Parser is licensed under the Apache License 2.0:
https://github.com/apple/swift-argument-parser/blob/main/LICENSE.txt

## Downloaded at first launch, not bundled

The app installs these on request, from their official download pages, with pinned versions and checksums
(`engine/setup_tools.py`, `engine/setup_ai.py`), and runs them as separate programs.

| Component | Version | License | Use |
|---|---|---|---|
| Blender | 5.2.3 | GNU GPL | required: watertight solid, decimation, bakes, exports |
| OrcaSlicer | 2.4.2 | AGPL-3.0 | optional: slicing |
| COLMAP (Windows) | 4.2.1 | BSD-3-Clause ("new BSD") | optional: photogrammetry |
| OpenMVS (Windows) | 2.4.0 | AGPL-3.0 | optional: photogrammetry |
| Microsoft Visual C++ Redistributable (Windows) | 14.51 or later | Microsoft software license terms | needed by COLMAP, OpenMVS and PyTorch |
| AI module: PyTorch 2.14.1, transformers 4.35.0, rembg 2.0.69, onnxruntime 1.31.0 and their dependencies (`requirements-ai.txt`) | | PyTorch: BSD-style; transformers: Apache-2.0; rembg: MIT; onnxruntime: MIT; the others under their own licenses | optional: "One photo (AI)" |
| TripoSR weights (stabilityai/TripoSR) | | MIT | optional: AI module |
| DINO ViT-B/16 configuration (facebook/dino-vitb16) | | Apache-2.0 | optional: AI module |
| U²-Net model (u2net.onnx, used by rembg) | | Apache-2.0 | optional: AI module, background removal |

On macOS, photogrammetry uses Apple's Object Capture (RealityKit), part of the operating system.
