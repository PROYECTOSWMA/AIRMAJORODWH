$ErrorActionPreference = "Stop"
$out = Join-Path $PSScriptRoot "..\dist"
New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host "Publicando SqlGateway.exe (win-x64, self-contained)..."
dotnet publish $PSScriptRoot -c Release -o $out --self-contained true -r win-x64 /p:PublishSingleFile=true

# Dejar solo lo necesario para entregar
@(
  "appsettings.Development.json",
  "SqlGateway.pdb",
  "SqlGateway.staticwebassets.endpoints.json",
  "web.config"
) | ForEach-Object {
  $p = Join-Path $out $_
  if (Test-Path $p) { Remove-Item $p -Force }
}

$readme = Join-Path $PSScriptRoot "..\LEEME.txt"
if (Test-Path $readme) {
  Copy-Item $readme (Join-Path $out "LEEME.txt") -Force
}

Write-Host ""
Write-Host "Listo. Entrega estos archivos de la carpeta dist:"
Write-Host "  - SqlGateway.exe"
Write-Host "  - appsettings.json  (editar ConnectionString, puerto y ApiKey)"
Write-Host "  - LEEME.txt"
Write-Host ""
Write-Host "Salida: $out"
