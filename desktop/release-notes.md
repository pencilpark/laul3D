## What's new

Berria Craft is now open source, under the MIT license. The repository's README and THIRD_PARTY_NOTICES.md are in
English, and both installers carry the license and the notices.

3D exports (3D software, Games, Web) are of higher quality:
- Tangents in the GLB and FBX files, so three.js and game engines read the normal map in the frame it was baked in.
- Web textures saved at JPEG quality 90 (color) and 95 (normal map) instead of 75, or in WebP.
- The scan's own roughness is baked when it has one (Object Capture at High resolution); otherwise a Finish setting
  gives matte (0.9), satin (0.6) or glossy (0.3), instead of Blender's 0.5.
- The normal map can come from the scan's fine relief instead of the smoothed model (Relief setting, Auto by default).
- Games: `_normal_dx.png`, the normal map in DirectX convention, for Unreal with the FBX.
- Web: a meshopt-compressed GLB beside the Draco one, whose UVs keep 14 bits.
- Textures are antialiased (4 rays per texel by default, up to 16), areas no photo shows take the color of their
  surroundings instead of black, and the UV islands fill 62 % of the texture instead of 55 % on the test bust. The
  textured OBJ for color print services gets the same improvements.
- A Real height setting gives the exports the object's true size, instead of the printed one.
- Each zip has a README.txt, in the app's language, that describes its files.

For computers from 8 GB up: every baked texture now comes down to what free memory allows, counted at 240 bytes per
texel after a measured 235 (before, only Max resolution was checked, at 150), and its size can be set from 1024 to 8192.
The Mesh setting scales the export face counts from half to four times.

HEIC photos are now decoded by pi-heif, the decoding-only build of pillow-heif, which leaves out the GPL-licensed x265
encoder.

After the update, results computed with exports or the textured OBJ show as to recompute: computing them again gives
the new textures.

## Install

- Windows 10 or 11, 64-bit: `Berria.Craft_0.5.3_x64-setup.exe`. The installer is not signed: SmartScreen asks once for
  More info, then Run anyway. Updating keeps the projects and their scans.
- Mac (Apple silicon, macOS 14 or later): `Berria.Craft_0.5.3_aarch64.dmg`, added to this release once built on a Mac.
  The app is not notarized: at first launch, allow it in System Settings > Privacy & Security > Open Anyway.
