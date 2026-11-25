param(
    [string]$ChiakiSource = (Join-Path $PSScriptRoot '../../../chiaki-ng'),
    [string]$BuildDirectory = 'build-release',
    [string]$MsysPrefix = 'C:/msys64/ucrt64',
    [switch]$Package
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $repo
try {
    $python = Join-Path $repo '.venv/Scripts/python.exe'
    if (!(Test-Path $python)) { throw 'Create .venv with Windows Python 3.13 x64 and install tools/remoteplay/requirements.txt first.' }
    $env:PATH = "$MsysPrefix/bin;C:/Program Files/nodejs;" + $env:PATH
    $env:BRANCH = 'remoteplay-host-prototype'
    $env:BUILD_VERSION = '0.3.1'
    & $python tools/remoteplay/build_windows.py $ChiakiSource --prefix $MsysPrefix
    if ($LASTEXITCODE) { throw 'Native dependency build failed' }
    $pythonRoot = & $python -c 'import sys; print(sys.base_prefix)'
    cmake -S . -B $BuildDirectory -G Ninja '-DCMAKE_POLICY_VERSION_MINIMUM=3.5' '-DCMAKE_BUILD_TYPE=Release' '-DBUILD_TESTS=OFF' '-DBUILD_DOCS=OFF' '-DAPOLLO_REMOTEPLAY=ON' "-DPython3_ROOT_DIR=$pythonRoot" '-DSUNSHINE_PUBLISHER_NAME=mamogaaa' '-DSUNSHINE_PUBLISHER_WEBSITE=https://github.com/mamogaaa/Apollo-RemotePlay' '-DSUNSHINE_PUBLISHER_ISSUE_URL=https://github.com/mamogaaa/Apollo-RemotePlay/issues'
    if ($LASTEXITCODE) { throw 'Configure failed' }
    cmake --build $BuildDirectory -j4
    if ($LASTEXITCODE) { throw 'Apollo build failed' }
    & $python tools/remoteplay/stage_embedded.py $BuildDirectory
    if ($LASTEXITCODE) { throw 'Runtime staging failed' }
    if ($Package) {
        $vendor = Join-Path (Resolve-Path $BuildDirectory) 'vendor'
        New-Item -ItemType Directory -Force $vendor | Out-Null
        $installer = Join-Path $vendor 'Apollo-upstream-0.3.0.exe'
        if (!(Test-Path $installer)) { Invoke-WebRequest 'https://github.com/ClassicOldSong/Apollo/releases/download/v0.3.0/Apollo.exe' -OutFile $installer }
        if ((Get-FileHash $installer -Algorithm SHA256).Hash -ne 'EAF6FB615B92FD4A0B6EB226B680A876B05F2BBFDE8716D7B5701ACBF2BD2791') { throw 'Upstream driver distribution hash mismatch' }
        $sevenZip = 'C:/Program Files/7-Zip/7z.exe'
        & $sevenZip x $installer "-o$vendor/upstream" 'drivers/sudovda/*' -y | Out-Null
        if ($LASTEXITCODE) { throw 'Signed driver extraction failed' }
        cmake -S . -B $BuildDirectory "-DAPOLLO_SUDOVDA_DIRECTORY=$vendor/upstream/drivers/sudovda"
        if ($LASTEXITCODE) { throw 'Packaging configure failed' }
        # NSIS cannot open long input paths even when Windows long paths are enabled.
        $packageWork = Join-Path $env:LOCALAPPDATA 'ApolloRP-pack'
        cpack --config "$BuildDirectory/CPackConfig.cmake" -G NSIS -B $packageWork -D CPACK_PACKAGE_FILE_NAME=ApolloRemotePlay
        if ($LASTEXITCODE) { throw 'Packaging failed' }
    }
} finally { Pop-Location }
