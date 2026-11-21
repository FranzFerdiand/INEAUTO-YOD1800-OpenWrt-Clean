$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
docker build -f (Join-Path $PSScriptRoot 'Dockerfile.ram') -t yod1800-ram-builder $root
if ($LASTEXITCODE -ne 0) { throw 'Docker build failed' }
docker run --rm -v "${root}:/work" yod1800-ram-builder
if ($LASTEXITCODE -ne 0) { throw 'RAM image build failed' }
