Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Assert-SafeRoot([string]$Path) {
    $p = FullPath $Path
    $live = 'C:\Users\gabot\agentic-os'
    $deploy = 'C:\Users\gabot\agentic-os-deploy'
    if ($p -ieq $live -or $p.StartsWith($live + '\', 'OrdinalIgnoreCase') -or
        $p -ieq $deploy -or $p.StartsWith($deploy + '\', 'OrdinalIgnoreCase')) {
        throw "Refused protected live/deploy path: $p"
    }
    if ($p -eq [IO.Path]::GetPathRoot($p).TrimEnd('\')) { throw 'Refused filesystem root' }
    $cursor = $p
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -Force -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refused reparse point: $cursor"
            }
        }
        $parent = Split-Path -Parent $cursor
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $p
}

function Read-Json([string]$Path) {
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Write-Json([string]$Path, $Value) {
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    $utf8 = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 30), $utf8)
    Move-Item -Force -LiteralPath $temporary -Destination $Path
}

function Assert-Package([string]$Root, [switch]$Installed) {
    $manifest = Read-Json (Join-Path $Root 'package-manifest.json')
    if ($manifest.schema_version -ne 1 -or $manifest.version -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$' -or
        $manifest.version.EndsWith('.')) { throw 'Invalid package version/schema' }
    $expected = @{}
    foreach ($file in $manifest.files) {
        $relative = [string]$file.path
        if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[/\\])\.\.([/\\]|$)|:' -or $expected.ContainsKey($relative)) {
            throw "Unsafe/duplicate manifest path: $relative"
        }
        $path = FullPath (Join-Path $Root $relative)
        if (-not $path.StartsWith((FullPath $Root) + '\', 'OrdinalIgnoreCase')) { throw 'Path escapes package' }
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing package file: $relative" }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
        $wanted = $file.sha256
        if ($Installed -and $relative -eq 'runtime/venv/pyvenv.cfg') {
            $runtimeManifest = Read-Json (Join-Path $Root 'runtime/runtime-manifest.json')
            $entry = @($runtimeManifest.files | Where-Object { $_.path -eq 'venv/pyvenv.cfg' })
            if ($entry.Count -ne 1 -or $entry[0].hash_encoding -ne 'runtime-path-template') { throw 'Invalid normalized runtime config hash' }
            $text = [IO.File]::ReadAllText($path)
            $prefix = 'home = ' + (Join-Path $Root 'runtime/cpython') + "`n"
            if (-not $text.StartsWith($prefix)) { throw 'Installed runtime home changed' }
            $normalized = 'home = ${RUNTIME}/cpython' + "`n" + $text.Substring($prefix.Length)
            $hash = [Security.Cryptography.SHA256]::Create()
            try { $actual = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)))).Replace('-','') }
            finally { $hash.Dispose() }
            $wanted = $entry[0].sha256
        }
        if ($actual -ine $wanted) { throw "Package hash mismatch: $relative" }
        $expected[$relative] = $true
    }
    foreach ($item in Get-ChildItem -Force -Recurse -LiteralPath $Root) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Package reparse point: $item" }
        if (-not $item.PSIsContainer) {
            $relative = $item.FullName.Substring((FullPath $Root).Length + 1).Replace('\', '/')
            if ($relative -ne 'package-manifest.json' -and -not ($Installed -and $relative -eq 'install.json') -and -not $expected.ContainsKey($relative)) { throw "Unexpected package file: $relative" }
        }
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Root 'runtime/runtime-manifest.json')).Hash -ine $manifest.runtime_manifest_sha256) {
        throw 'Runtime manifest hash mismatch'
    }
    return $manifest
}

function Set-AppAccess([string]$Path, [bool]$Writable) {
    # Per-user prototype: read-only files, reversible by their owner for removal.
    # No elevation or WRITE_DAC privilege is needed. This is not an ACL boundary.
    foreach ($file in Get-ChildItem -Force -Recurse -File -LiteralPath $Path) {
        $file.IsReadOnly = -not $Writable
    }
}

function Stop-App($Current) {
    $null = Assert-SafeRoot $Current.app_root
    $null = Assert-SafeRoot $Current.state_root
    $status = Join-Path $Current.state_root 'runtime/dispatch/layer_supervisor/status.json'
    if (Test-Path -LiteralPath $status) {
        & (Join-Path $Current.app_root 'AgenticOS.cmd') stop
        if ($LASTEXITCODE -notin @(0, 3)) { throw "Supervisor stop failed: $LASTEXITCODE; app retained" }
    }
}

function Update-LogonTask($Current) {
    if (-not $Current.task_name) { return }
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument ('/c ""' + $Current.app_root + '\AgenticOS.cmd""')
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $Current.task_name -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
}
