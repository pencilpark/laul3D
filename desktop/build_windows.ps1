# Builds the Berria Craft installer for Windows x64 (NSIS): stages Python, uv, the core wheels and the engine
# into src-tauri\resources, then runs the Tauri bundler.
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Root = Split-Path $Here
$Res = Join-Path $Here "src-tauri\resources"
$PyVersion = "3.11.14"
$UvVersion = "0.13.5"
$UvSha256 = "a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a"
$env:CARGO_TARGET_DIR = Join-Path $Here "src-tauri\target"

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what a échoué (code $LASTEXITCODE)" } }

if (Test-Path $Res) { Remove-Item -Recurse -Force $Res }
New-Item -ItemType Directory -Force "$Res\bin", "$Res\wheels", "$Res\app\desktop" | Out-Null

Write-Host "Python $PyVersion"
uv python install $PyVersion; Check "uv python install"
$pyDir = Join-Path (uv python dir) "cpython-$PyVersion-windows-x86_64-none"
Copy-Item -Recurse $pyDir "$Res\python"

Write-Host "uv $UvVersion"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("uv-" + [guid]::NewGuid())
New-Item -ItemType Directory $tmp | Out-Null
Invoke-WebRequest "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile "$tmp\uv.zip"
$hash = (Get-FileHash "$tmp\uv.zip" -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $UvSha256) { throw "SHA-256 uv incorrect : $hash" }
Expand-Archive "$tmp\uv.zip" -DestinationPath "$tmp\uv"
Copy-Item "$tmp\uv\uv.exe" "$Res\bin\uv.exe"
Remove-Item -Recurse -Force $tmp

Write-Host "Roues du socle (win_amd64)"
uvx pip download --quiet --only-binary=:all: --platform win_amd64 --python-version 3.11 `
  --implementation cp --abi cp311 -r "$Root\requirements-core.txt" -d "$Res\wheels"; Check "pip download"

Write-Host "Moteur et interface"
foreach ($d in "app", "engine", "vendor") {
  robocopy "$Root\$d" "$Res\app\$d" /E /XD __pycache__ /XF .DS_Store /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "copie de $d impossible (robocopy $LASTEXITCODE)" }
}
$global:LASTEXITCODE = 0
Copy-Item "$Root\requirements-core.txt", "$Root\requirements-ai.txt" "$Res\app\"
Copy-Item "$Here\boot.py" "$Res\app\desktop\"

Push-Location $Here
try {
  if (-not (Test-Path node_modules)) { npm ci; Check "npm ci" }
  npx tauri build --bundles nsis; Check "tauri build"
} finally { Pop-Location }
Get-ChildItem "$env:CARGO_TARGET_DIR\release\bundle\nsis\*.exe" | ForEach-Object { "{0}  {1:N0} Mo" -f $_.FullName, ($_.Length / 1MB) }
