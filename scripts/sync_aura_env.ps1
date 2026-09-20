$ErrorActionPreference = "Stop"

param(
    [string]$TemplatePath = ".env.example",
    [string]$LocalPath = ".env.local"
)

$TemplatePath = (Resolve-Path $TemplatePath).Path

if (-not (Test-Path $LocalPath)) {
    Copy-Item -LiteralPath $TemplatePath -Destination $LocalPath
    Write-Host "Created .env.local from latest template." -ForegroundColor Green
    exit 0
}

$existing = @{}
Get-Content -LiteralPath $LocalPath | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $index = $line.IndexOf("=")
    if ($index -le 0) { return }
    $name = $line.Substring(0, $index).Trim()
    if ($name -match "^[A-Za-z_][A-Za-z0-9_]*$") {
        $existing[$name] = $true
    }
}

$missing = New-Object System.Collections.Generic.List[string]
Get-Content -LiteralPath $TemplatePath | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $index = $line.IndexOf("=")
    if ($index -le 0) { return }
    $name = $line.Substring(0, $index).Trim()
    if (
        $name -match "^[A-Za-z_][A-Za-z0-9_]*$" -and
        -not $existing.ContainsKey($name)
    ) {
        $missing.Add($line)
        $existing[$name] = $true
    }
}

if ($missing.Count -eq 0) {
    Write-Host ".env.local already contains every current AURA setting."
    exit 0
}

Add-Content -LiteralPath $LocalPath -Value ""
Add-Content -LiteralPath $LocalPath -Value "# -------------------- Added by AURA env sync --------------------"
foreach ($line in $missing) {
    Add-Content -LiteralPath $LocalPath -Value $line
}

Write-Host ("Added " + $missing.Count + " missing setting(s) to .env.local without changing existing values.") -ForegroundColor Green
