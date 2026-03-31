# Creates a git tag v<pVersion> from xAutoDungeonRotation.py and optionally a GitHub Release.
# Usage (from repo root):
#   .\tools\create_release_from_pversion.ps1
# With API release (needs repo scope token):
#   $env:GITHUB_TOKEN = "ghp_..." ; .\tools\create_release_from_pversion.ps1

$ErrorActionPreference = "Stop"
# tools/ -> repo root
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root "xAutoDungeonRotation.py"
$m = Select-String -Path $py -Pattern "^\s*pVersion\s*=\s*['`"]([^'`"]+)['`"]" | Select-Object -First 1
if (-not $m) { throw "Could not find pVersion in xAutoDungeonRotation.py" }
$ver = $m.Matches[0].Groups[1].Value
$tag = "v$ver"

$existing = git tag -l $tag
if ($existing) {
    Write-Host "Tag $tag already exists locally. Skip tag creation or delete tag first."
    exit 1
}

git tag -a $tag -m "xAutoDungeonRotation $ver (pVersion)"
Write-Host "Created annotated tag $tag"
git push origin $tag
Write-Host "Pushed $tag to origin"

if ($env:GITHUB_TOKEN) {
    $owner = "maherbkh"
    $repo = "xAutoDungeonRotation"
    $uri = "https://api.github.com/repos/$owner/$repo/releases"
    $body = @{
        tag_name         = $tag
        name             = "xAutoDungeonRotation $ver"
        body             = "Release **$ver** - matches pVersion in xAutoDungeonRotation.py."
        generate_release_notes = $true
    } | ConvertTo-Json
    $headers = @{
        Authorization = "Bearer $($env:GITHUB_TOKEN)"
        Accept          = "application/vnd.github+json"
        "User-Agent"    = "xAutoDungeonRotation-release-script"
    }
    Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $body -ContentType "application/json; charset=utf-8"
    Write-Host "GitHub Release created for $tag"
} else {
    Write-Host ""
    Write-Host "Optional: set GITHUB_TOKEN and re-run to create the GitHub Release via API,"
    Write-Host "or open: https://github.com/maherbkh/xAutoDungeonRotation/releases/new?tag=$tag"
}
