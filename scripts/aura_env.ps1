function Import-AuraEnv {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line) { return }
        if ($line.StartsWith("#")) { return }

        $match = [regex]::Match($line, "^[A-Za-z_][A-Za-z0-9_]*=(.*)$")
        if (-not $match.Success) {
            throw ("Invalid AURA env line: " + $line)
        }

        $name = $line.Substring(0, $line.IndexOf("="))
        $value = $match.Groups[1].Value

        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}
