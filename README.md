# Berria Craft

Desktop app for macOS and Windows: drop in photos of an object and get back a watertight STL sized for the Creality
Ender-3 V3 (build volume 220 × 220 × 250 mm), turning a faceted Low-Poly look into a detailed model. It also writes colour
files for multi-filament printers and colour print services, and cleaned-up models for 3D software, game engines and the
web. It opens in its own window, without a browser. Everything is computed on the computer, and no photo goes online;You download 
only the tools and the optional AI module once from their official sites.

The interface is in English, French, Spanish, German, Brazilian Portuguese, Simplified Chinese and Japanese.

## Install

The installers are attached to each [GitHub release](https://github.com/pencilpark/laul3D/releases), where GitHub
replaces the space in the file name with a dot (`Berria.Craft_…`).

- macOS (Apple Silicon, macOS 14 Sonoma or later): open `Berria Craft_0.5.3_aarch64.dmg` and drag Berria Craft into
  Applications. The app is not notarised: downloaded on a Mac, it has to be allowed once in System Settings > Privacy &
  Security > Open Anyway. Built on the same Mac, it opens directly.
- Windows 10 or 11, 64-bit: run `Berria Craft_0.5.3_x64-setup.exe`. The installer is not signed: SmartScreen asks once
  for More info, then Run anyway. It installs for the current user, without administrator rights.

At first launch, the app prepares its computing environment (a minute at most), then offers the missing tools in a
window: Blender (required), OrcaSlicer, and on Windows the COLMAP + OpenMVS photogrammetry. The One photo (AI) module
installs separately from the header. On Windows, COLMAP, OpenMVS and the AI module need the Microsoft Visual C++
runtime, which Windows asks permission to install.

## Engines

Several photos (20 or more, 50 for a faithful bust): the shape comes from the photos; nothing is invented.
- macOS: Apple Object Capture, through the `HelloPhotogrammetry` tool shipped with the app.
- Windows: COLMAP 4.2.1 places the photos; OpenMVS 2.4.0 builds the mesh and its texture on the CPU. TextureMesh's
  seam levelling is turned off: in 2.4.0 it blackens textures (OpenMVS issue #1257). COLMAP extracts features from as
  many photos at once as free memory allows (about 0.8, 1.2 and 3.1 GB per photo at Low, Medium and High resolution),
  instead of one per core, so that High resolution does not make Windows page on 8 GB; the features found stay the
  same. COLMAP and OpenMVS run at low priority. Since COLMAP works in an arbitrary frame, the app stands the model up
  from the photos: their average "up" gives the vertical, the first photo gives the front.

One photo: the TripoSR AI (Stability AI and Tripo, MIT license) estimates the shape and colours from the main photo,
cut out by rembg. The back is guessed. The module is optional and weighs about 2.2 GB (4 to 4.7 GB on a PC with an
NVIDIA card, where torch comes in its CUDA build).

Engines ruled out:
- Hunyuan3D: the Tencent Hunyuan 3D license grants no rights in the EU, the UK or South Korea (section 1.l,
  "Territory"), even for private use.
- TRELLIS: its Mac port recommends 24 GB of unified memory or more.
- Tripo, Rodin, Meshy and Hunyuan through MCP for Blender: paid or Premium-only.

## From LowPoly to detailed

Each project is refined in three levels. Reconstructions already made stay in cache.

| Level | Object Capture | Target triangles | Watertight voxel | Use |
|---|---|---|---|---|
| LowPoly | `-d preview` | 200 to 5,000 (1,000 by default) | size / 300 | check shape and orientation quickly, faceted look |
| Medium | `-d medium` | about 20,000 | size / 400 | everyday printing |
| Detailed | `-d full` | up to 300,000 | size / 650 | best quality, slower |

The voxel stays between 0.2 and 0.5 mm. Suggested workflow: start in LowPoly, straighten the model with quarter turns
if needed, then generate Medium or Detailed.

### Photo resolution

The Photo resolution setting, under the level of detail and in Adjust this model, picks the size of the photos the
photogrammetry uses, independently of the level. Auto, the default, follows the level: Low for LowPoly, Medium for
Medium, High for Detailed. Low, Medium, High or Max apply to every level, which then share the same scan. It has no
effect on One Photo (AI).

| Resolution | macOS: Object Capture | Windows: COLMAP, then OpenMVS | Scan texture (Windows) |
|---|---|---|---|
| Low | `-d preview` | photos reduced to 1600 px, depth maps at 800 px | 4096 |
| Medium | `-d medium` | 2000 px, then 1000 px | 4096 |
| High | `-d full` | 3200 px, then 1600 px | 4096 |
| Max | `-d raw` | the photos' full size, fitted to free memory | 8192 |

Max:
- macOS: Object Capture's `raw` detail, which Apple's documentation describes as made "at the highest resolution
  possible from the source images" (up to 30 million triangles and 16 textures of 8192). macOS does not tell in advance
  whether memory suffices: if `raw` fails, the app makes the scan again in `full` (High) and the log says so; the
  project no longer tries `raw` afterwards (`scan_raw.failed` file in its work folder).
- Windows: COLMAP and OpenMVS work on the whole photos (OpenMVS resolution level 0), with a scan texture up to 8192.
  Before computing, the app estimates the memory of each step for the size and number of photos (see `MEMORY_MODEL` in
  `engine/photogrammetry_win.py`) and lowers the size in 10 % steps until it fits in free memory, minus 1.5 GB left to
  Windows. If the size kept is no larger than High's, the scan is made at High. The log gives the size kept and the
  free memory; so do the model's technical details.
- Blender: the textured OBJ's texture and those of the 3D software profile go from 4096 to 8192, brought down to 6144
  or less when free memory is short (see Baked textures); LowPoly keeps 2048.
- The printable STL stays capped by the level (300,000 triangles and a voxel of at least 0.2 mm in Detailed): Max
  first refines the scan, the colors and the textures. Computing takes much longer.

Save the raw scan, under Other files, copies the photogrammetry mesh to Downloads as it came out, before cleanup, for
Blender: Object Capture's `.usdz` on macOS, OpenMVS's textured OBJ zipped with its MTL and textures on Windows, stood
up like the printable model and Y up.

Smoothing (None, Light, Medium, Strong): blur of the model's volume over 2 to 4 voxels (about 0.4 to 0.8 mm for an
80 mm bust). It removes grain and small bumps; at Strong, the fine details of a face soften too.

Render: the viewer opens in Render mode when the model has colors, those of the photos (one color per facet in
LowPoly); the Solid / Render buttons switch between both. It is a preview: the printed STL stays one color. Unusable
colors (black, unreadable texture, faces no photo shows) are dropped and the Technical log gives the reason.

## What the preparation does (headless Blender)

`engine/blender_lowpoly.py` runs with `--factory-startup`, so without the user's add-ons: no second MCP server starts
on port 9876.

1. Import of USDZ, OBJ, GLB, PLY or STL, merge into one object, requested rotation, scaling in mm.
2. Watertightness: holes filled, then voxel remesh. If the scan leaks too much, morphological closing (dilation in
   Geometry Nodes, outer shell, shrink back).
3. One shell kept by default. The Keep separate parts option keeps pieces above 2 %.
4. Optional smoothing (OpenVDB SDF nodes), then decimation to the level's triangle count. If self-intersections
   appear, the target goes up by 40 % and the app tries again, up to 3 times.
5. Flat base: cut at the bottom (3 % by default) and closing of the section.
6. Checks: non-manifold edges, self-intersections, shells, walls thinner than 2 × the nozzle, overhangs beyond 45°,
   volume.
7. The scan's colors projected by Cycles onto the final mesh, exported as a preview GLB and, depending on the boxes
   checked, as a painted 3MF, a colored OBJ and a textured OBJ (see Color printing).
8. STL export in mm, checked by reading back the number of triangles written, plus a `.blend` and 4 PNG previews.
9. If 3D exports beyond printing are checked, a second Blender redoes the import, watertightness, shell sorting and
   smoothing, without the decimation or the base, and produces the profiles (see 3D exports): a profile that fails
   leaves the print files untouched. It keeps the scan beside the solid to bake its colors, its roughness and, if
   chosen, its relief.

## Taking good photos

Still subject, even light without flash, first photo from the front, a full turn with about 70 % overlap between two
neighboring photos, two or three heights, the whole subject in every frame. iPhone HEIC or JPG. Blurry photos are
dropped automatically (sharpness below 35 % of the median).

## Printing

Prepare the print in OrcaSlicer, then:
- Creality Ender-3 V3 profile;
- tree supports if the report flags overhangs (chin, nose, ears);
- base flat on the bed.

## Color printing

In Advanced settings, and in Recompute with these settings for a model already computed, three boxes choose the color
files computed on top of the STL. They are checked by default; unchecked, the computation and the files stay as before
(STL, `.blend`, colored preview). The files only exist when the photos give usable colors.

- Painted 3MF, for a printer with several spools (the Ender-3 V3 alone has one). Each face carries a filament number
  (OrcaSlicer and Bambu Studio's `paint_color` attribute), not a color: in OrcaSlicer, first set as many filaments as
  the palette, in the same order and colors, then open the file. Opened with fewer filaments, the faces of the missing
  numbers show with filament 1 and lose their paint when filaments are added later. File > Import adds the missing
  filaments itself, with colors to correct.
- Colored OBJ (OBJ and MTL side by side, in mm, Z up like the STL), for the same printer. On opening, OrcaSlicer 2.1 or
  later shows a window that adds the palette's colors as new filaments, after those already set. Faces keep exactly
  their filament, but OrcaSlicer recomputes the colors: they can differ by a few units from the codes shown, and the
  order of the added filaments can differ from the palette's. The `.mtl` has to stay beside the `.obj`: from a zip,
  OrcaSlicer only reads the OBJ and opens it without color. Save the colored OBJ therefore copies both files to
  Downloads.
- Zipped textured OBJ (OBJ, MTL and PNG, in mm, Z up), for a true-color print service (Sculpteo, i.materialise...).
  The texture is 2048 px in LowPoly and 4096 px in Medium and Detailed, or the size chosen in Baked textures; areas no
  photo shows (under the model, holes in the scan) take the color of their surroundings instead of black. It adds a
  few seconds to a minute to the computation.

For the first two, the photo colors are grouped into 4 hues by default, from 2 to 8 with the Filaments for color
printing setting. A color island smaller than (4 × nozzle)², about 2.6 mm² with a 0.4 nozzle, takes the closest
neighboring color; two hues too close to each other (Lab distance below 12) do not take two spools. The palette shows
each color's number and code.

The colors come from the photos, shadows and reflections included.

## 3D exports

Three boxes in Advanced settings, and in Recompute with these settings, produce the cleaned-up model for uses other than
printing. They are unchecked by default: without them, the computation stays as before. Each profile gives a zip in
meters, base centered on the origin, Y up in the GLB and FBX files, with a `README.txt` in the app's language that
describes its files and their conventions.

- 3D software (Blender, sculpting, animation): about 20,000 quads by QuadriFlow, Blender's remesher, PNG textures of
  4096, `.blend` (textures beside it, relative paths), FBX and OBJ files. If QuadriFlow refuses the model, the profile
  comes out in triangles and the log says so. To animate a character, a manual retopology is still useful: QuadriFlow
  follows the shape, not the joints.
- Games (Unity, Unreal, Godot): 50,000 triangles and two levels of detail at 50 and 25 %, as GLB and FBX, color in JPEG
  (quality 95), normal map and roughness in PNG, 2048 px. `_normal_dx.png` is the normal map with green flipped, for
  Unreal with the FBX: Unreal 5.7's glTF import flips green itself (`InterchangeGltfTranslator.cpp`), its FBX import
  does not.
- Web (three.js, model-viewer): a GLB of 50,000 triangles, JPEG textures (color at quality 90, normal map at 95) or
  WebP, 2048 px: 3.0 MB on the 507,000-face test bust. A Draco-compressed version (UVs on 14 bits instead of 12, which
  round them to half a texel of a 2048 texture) and a meshopt-compressed version are added, 1.6 and 2.0 MB on the same
  scan, when the installed Blender has their libraries, as the official Blender 5.2 does. Each file is checked:
  Blender's export succeeds without the library but then writes nothing compressed.

For each profile: detached pieces removed, surface closed and smoothed as for printing, reduction, then UV unwrap by
Smart UV Project and packing of the islands by their real outline, at any angle (on the test bust, 62 % of the texture
used instead of 55 %, and 8.7 texels between islands at the first percentile instead of 4.6, which mipmaps need).
Cycles then bakes, with several rays per texel (Antialiasing setting):
- the photos' colors; areas no photo shows (under the bust, holes in the scan) take the color of their surroundings
  instead of black;
- the relief, into a MikkTSpace tangent-space normal map, from the scan or from the smoothed model (Relief setting);
- the scan's roughness when it has one (Object Capture at High), otherwise a fixed value (Finish setting), without
  metal.

The GLB and FBX files carry the tangents of the bake. Without them, three.js r160 derives its own frame from screen
derivatives (`GLTFLoader.js`); on a close-up of the test bust, the measured difference stays small (at most 16/255, on
0.04 % of the pixels). The GLB files are single-sided (no `doubleSided`), the solid being closed. FBX has no slot for
roughness: Blender's exporter puts it in the Phong shininess slot, which Unreal 5.7's FBX import (Interchange, ufbx)
treats as such. The FBX therefore gets the map's mean, and `_roughness.png` stays beside it to plug in by hand; the GLB
carries it. Without usable colors, only the normal map is delivered.

Times measured on an M2 Ultra with 24 cores, after 9 s of import and cleanup: on the test bust (507,000 faces, 8192
texture, Max resolution), 6 s for Web, 7 s for Games and 48 s for 3D software at 8192; on the small scan of the
end-to-end test (Suzanne photos), 4, 5 and 18 s.

### 3D export settings

Under the profile boxes, once a profile is checked:

| Setting | Choices | Effect |
|---|---|---|
| Real height | empty, or 0.1 to 100,000 cm | size of the object in the exports; empty, the printed height (80 mm gives an 8 cm GLB). COLMAP works in a frame without scale, and Object Capture only finds one when the HEIC photos carry depth: the real size comes from the user |
| Mesh | Light (×0.5), Standard, Dense (×2), Very dense (×4) | face count of each profile |
| Relief | Auto, Fine (scan), Smooth (model) | source of the normal map; Auto takes the scan for photogrammetry, the smoothed model for the AI or with Medium or Strong smoothing |
| Finish | Auto, Matte (0.9), Satin (0.6), Glossy (0.3) | roughness; Auto bakes the scan's if it has one, otherwise 0.9, Object Capture's value for a scan without a map |
| Web profile images | JPEG, WebP | WebP makes the GLB lighter (`EXT_texture_webp` extension, read by three.js and model-viewer) |

### Baked textures

Once the textured OBJ or a profile is checked, for color printing as for the exports:

| Setting | Choices | Effect |
|---|---|---|
| Size | Auto, 1024, 2048, 4096, 8192 px | Auto: 2048 in LowPoly and for Web and Games, 4096 otherwise, 8192 at Max resolution. Any size is brought down to the largest one free memory can bake, and the log says so |
| Antialiasing | 1, 4 or 16 rays per texel | Cycles spreads the rays over the texel, which softens edges; 4 by default. On the test bust, the Web profile takes 5.7 s with 1 ray, 6.0 s with 4 and 7.4 s with 16 (M2 Ultra) |

The memory of a bake was measured with Blender 5.2.2 on the 3D software profile of the test bust: peaks of 3.3 GB at
1024, 4.0 at 2048, 7.0 at 4096 and 18.8 at 8192, so 235 more bytes per texel. The app counts 240 bytes per texel and
leaves 1.5 GiB to the system: about 18 GB free for 8192, 6 for 4096 and 3 for 2048. On an 8 GB Mac, 4096 therefore
needs more than 5.6 GB free. `LOWPOLY_FREE_MEMORY_GB` (in GiB) replaces the measured free memory, to try on a large
machine what a small one would do (`LOWPOLY_FREE_MEMORY_GB=3`) or to keep memory for other work.

## Languages

The app comes in English (the default), French, Spanish, German, Brazilian Portuguese, Simplified Chinese and
Japanese. At first launch it takes the system's interface language, read by the Python engine (on Windows, the built-in
browser does not report it reliably); a language outside the list gives English, and so does Traditional Chinese. The
menu at the top right changes the language; the choice is kept in `data/prefs.json`. The Windows installer shows in the
system language among the seven.

The texts live in `app/static/i18n/<language>.json`, shared by the interface (`tr()`) and the engine
(`engine/i18n.py`, `srv.` keys). The start page keeps a copy of its own: after changing `splash.` keys, run
`python desktop/splash_strings.py`. `tests/i18n_test.py` checks that the seven files have the same keys and
placeholders, and that the code only uses existing keys. Messages already saved in a project (steps, errors, log) stay
in the language they were written in.

Output files have English names for everyone since 0.5.0 (`_colors.glb`, `_colors_orca.obj`, `_colors_texture.zip`,
views `_front`, `_right`, `_back`, `_three_quarter`, profiles `_software`, `_game`, `_web`); those of projects computed
earlier keep their names.

## Folders of the installed app

Data in `~/Library/Application Support/com.pencilpark.berriacraft` (macOS) or
`%LOCALAPPDATA%\com.pencilpark.berriacraft` (Windows):
- `runtime`, `venv`: the app's private Python and its libraries;
- `data/tools`: Blender, COLMAP, OpenMVS, OrcaSlicer (Windows) installed by the app; `data/models`: the AI module's
  models;
- `Projects/<date>-<name>`: photos received, cached reconstructions, exports per level (the `Projets` folder of earlier
  versions is renamed at the first launch of 0.5.0);
- `logs/serveur.log`: the engine's log.

Saved files go to Downloads. A project is deleted from the project list (trash icon, with confirmation): its folder is
erased, except during a computation; files already saved to Downloads stay.

## Build from source

### macOS

Requires an Apple silicon Mac with macOS 14 or later, Xcode, Rust, Node.js and uv.

1. Build Apple's sample code [Creating a photogrammetry command-line app](https://developer.apple.com/documentation/realitykit/creating-a-photogrammetry-command-line-app)
   in Release with Xcode, and copy its `HelloPhotogrammetry` executable to `~/.local/bin` (or point `LOWPOLY_HELPER` at
   it). `HelloPhotogrammetry --help` must list the `-d` option with `raw`.
2. Run `zsh desktop/build_mac.sh`. It gathers Python 3.11.14, uv 0.13.5 (SHA-256 checked), the core wheels for macOS 14
   arm64, `HelloPhotogrammetry`, the engine, `LICENSE` and `THIRD_PARTY_NOTICES.md`, then Tauri builds the app and the
   DMG in `desktop/src-tauri/target/release/bundle/`.

The DMG step lays out its window through the Finder, so the terminal app needs the Automation permission for Finder
(System Settings > Privacy & Security > Automation). While macOS waits for that consent, the build fails with
`AppleEvent timed out (-1712)`. `CI=true zsh desktop/build_mac.sh` skips the window layout.

### Windows

The `windows-installer` workflow builds the installer on every push, installs it silently, checks that the engine
starts and stops and that the window loads, then uploads it as the `berria-craft-windows` artifact. On a Windows
machine with Rust (MSVC toolchain), Node.js and uv: `desktop\build_windows.ps1`.

### Releasing a version

1. Bump the version in `desktop/src-tauri/tauri.conf.json`, `desktop/src-tauri/Cargo.toml` and
   `desktop/src-tauri/Cargo.lock`, and write `desktop/release-notes.md`.
2. Run the `windows-installer` workflow by hand on `dev` (Actions > windows-installer > Run workflow, with "release"
   ticked), or push a `vX.Y.Z` tag. The workflow creates the GitHub release `vX.Y.Z` with the tested installer, and the
   tag if it is missing.
3. Build the DMG on a Mac and add it to the release:
   `gh release upload vX.Y.Z "desktop/src-tauri/target/release/bundle/dmg/Berria Craft_X.Y.Z_aarch64.dmg"`.

## Development

```sh
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r requirements-core.txt   # add -r requirements-ai.txt for the AI module
./start.command                                                     # then http://127.0.0.1:8642
```

The engine looks for Blender 5.0 or later in the app's tools folder, then in `/Applications` and `~/Applications`
(macOS) or Program Files (Windows), and for `HelloPhotogrammetry` in `~/.local/bin`.

| Variable | Effect |
|---|---|
| `LOWPOLY_BLENDER` | Blender executable to use |
| `LOWPOLY_PHOTOGRAMMETRY` | Object Capture tool (`HelloPhotogrammetry`) |
| `LOWPOLY_ORCA` | OrcaSlicer |
| `LOWPOLY_DATA`, `LOWPOLY_PROJECTS`, `LOWPOLY_DOWNLOADS` | data, projects and saved-files folders |
| `LOWPOLY_HOME` | root of the installed app's data (launcher) |
| `LOWPOLY_LANG` | language: `en`, `fr`, `es`, `de`, `pt-BR`, `zh-CN` or `ja` |
| `LOWPOLY_FREE_MEMORY_GB` | free memory to assume, in GiB |
| `LOWPOLY_PREVIEW_ENGINE` | `cycles` renders the previews on the CPU |
| `LOWPOLY_DEVICE` | TripoSR device: `cuda`, `mps` or `cpu` |
| `LOWPOLY_TRIPOSR_WEIGHTS`, `LOWPOLY_DINO_CONFIG` | local AI model files |
| `LOWPOLY_HELPER` | `HelloPhotogrammetry` to bundle (`desktop/build_mac.sh`) |

### Command line

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
$B -b --factory-startup --python-exit-code 1 -P engine/blender_lowpoly.py -- \
  --input scan.usdz --outdir out --name bust --level lowpoly --height-mm 80 --previews --colors --smooth 1
# same options plus --profiles-only software,game,web: the export profiles only
.venv/bin/python engine/cli.py photos/ --niveau medium --resolution max --exports game,web
.venv/bin/python engine/cli.py photos/ --exports web --hauteur-reelle 30 --textures 4096 --anticrenelage 16 --images-web webp
.venv/bin/python engine/triposr_infer.py photo.jpg out/raw.obj
```

`engine/cli.py --help` lists every option, in the app's language.

### Tests

`tests/setup_ai_test.py`, `tests/setup_tools_test.py`, `tests/orientation_test.py`, `tests/photogrammetry_win_test.py`,
`tests/boot_test.py`, `tests/save_race_test.py`, `tests/delete_project_test.py`, `tests/couleurs_test.py`,
`tests/photo_res_test.py`, `tests/i18n_test.py`, `tests/preview_fallback_test.py`, `tests/exports_test.py` (needs
Blender) and `tests/smoke_test.py` (end to end on the fixture photos; `--max` for a full run at Max resolution). The
Windows workflow runs all of them on every push except `tests/save_race_test.py` and `tests/preview_fallback_test.py`.

### Layout

- `app/`: the local server (`server.py`, FastAPI) and the interface (`static/index.html`, a three.js viewer,
  translations in `static/i18n/`).
- `engine/`: the pipeline (`pipeline.py`), the headless Blender step (`blender_lowpoly.py`), the Windows photogrammetry
  (`photogrammetry_win.py`), the tool and AI installers, the command line.
- `desktop/`: the Tauri shell (`src-tauri/`), the launcher (`boot.py`), the start page (`ui/`), the build scripts.
- `vendor/TripoSR/`: the TripoSR source, unmodified.
- `tests/`: the tests and their fixtures.

## Contributing

Issues and pull requests are welcome. Run `python tests/i18n_test.py` and the tests that match your change; the Windows
workflow runs most of them on every push.

## License

MIT, see [LICENSE](LICENSE). The installers bundle, and the app downloads, third-party software under its own
licenses: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Berria Craft is made by Frédéric BERRIA (Pencil Park).
