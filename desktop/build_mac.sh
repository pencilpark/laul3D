#!/bin/zsh
# Builds "Berria Craft.app" and its DMG (Apple silicon, macOS 14+): stages Python, uv, the core wheels, the
# Object Capture helper and the engine into src-tauri/resources, then runs the Tauri bundler.
set -euo pipefail

HERE=${0:A:h}
ROOT=${HERE:h}
RES=$HERE/src-tauri/resources
# a CARGO_TARGET_DIR set for another project would receive this build
export CARGO_TARGET_DIR=$HERE/src-tauri/target
PY_VERSION=3.11.14
UV_VERSION=0.13.5
UV_SHA256=743f85035a1996ecb350659e01cd9faea9709829be09b1b4b03c73eaf3c9cd73
HELPER=${LOWPOLY_HELPER:-$HOME/.local/bin/HelloPhotogrammetry}

rm -rf "$RES"
mkdir -p "$RES/bin" "$RES/wheels" "$RES/app/desktop"

echo "Python $PY_VERSION"
uv python install "$PY_VERSION"
cp -R "$(uv python dir)/cpython-$PY_VERSION-macos-aarch64-none" "$RES/python"

echo "uv $UV_VERSION"
TMP=$(mktemp -d)
curl -fsSL -o "$TMP/uv.tar.gz" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-aarch64-apple-darwin.tar.gz"
echo "$UV_SHA256  $TMP/uv.tar.gz" | shasum -a 256 -c -
tar -xzf "$TMP/uv.tar.gz" -C "$TMP"
cp "$TMP/uv-aarch64-apple-darwin/uv" "$RES/bin/uv"
rm -rf "$TMP"

echo "Roues du socle (macOS 14 arm64)"
uvx pip download --quiet --only-binary=:all: --platform macosx_14_0_arm64 --python-version 3.11 \
  --implementation cp --abi cp311 -r "$ROOT/requirements-core.txt" -d "$RES/wheels"

echo "Object Capture"
cp "$HELPER" "$RES/bin/HelloPhotogrammetry"

echo "Moteur et interface"
rsync -a --exclude __pycache__ --exclude .DS_Store "$ROOT/app" "$ROOT/engine" "$ROOT/vendor" "$RES/app/"
cp "$ROOT/requirements-core.txt" "$ROOT/requirements-ai.txt" "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$RES/app/"
cp "$HERE/boot.py" "$RES/app/desktop/"

cd "$HERE"
[[ -d node_modules ]] || npm ci
npx tauri build --bundles app,dmg
ls -lh "$HERE"/src-tauri/target/release/bundle/dmg/*.dmg
