[CmdletBinding()]
param(
    [string]$PackageRoot,
    [string]$AppRoot = "$env:LOCALAPPDATA\Programs\AgenticOS",
    [string]$StateRoot = "$env:LOCALAPPDATA\AgenticOS\state",
    [string]$ProjectsRoot = "$env:USERPROFILE\Documents\Agentic OS\Projects",
    [switch]$Rollback,
    [switch]$RegisterLogonTask
)
if (-not $PackageRoot) { $PackageRoot = $PSScriptRoot }
. "$PSScriptRoot\Package-Common.ps1"
try {
    $AppRoot = Assert-SafeRoot $AppRoot
    $StateRoot = Assert-SafeRoot $StateRoot
    $ProjectsRoot = Assert-SafeRoot $ProjectsRoot
    foreach ($pair in @(@($AppRoot,$StateRoot), @($AppRoot,$ProjectsRoot), @($StateRoot,$ProjectsRoot))) {
        if ($pair[0] -ieq $pair[1] -or $pair[0].StartsWith($pair[1] + '\','OrdinalIgnoreCase') -or $pair[1].StartsWith($pair[0] + '\','OrdinalIgnoreCase')) {
            throw 'App, state and projects roots must be separate, non-nested directories'
        }
    }
    $currentPath = Join-Path $AppRoot 'current.json'
    $old = $null
    if (Test-Path -LiteralPath $currentPath) { $old = Read-Json $currentPath }
    if ($old) {
        $oldApp = Assert-SafeRoot $old.app_root
        if ((Split-Path -Parent $oldApp) -ine $AppRoot) { throw 'Invalid active version path' }
    }
    if ($Rollback) {
        if (-not $old -or -not $old.previous) { throw 'No previous version available' }
        $previous = Assert-SafeRoot $old.previous
        if ((Split-Path -Parent $previous) -ine $AppRoot -or -not (Test-Path -LiteralPath "$previous\install.json")) { throw 'Invalid rollback target' }
        $null = Assert-Package $previous -Installed
        Stop-App $old
        $record = Read-Json "$previous\install.json"
        $null = Assert-SafeRoot $record.state_root
        $null = Assert-SafeRoot $record.projects_root
        $active = @{app_root=$previous; version=$record.version; previous=$old.app_root; state_root=$record.state_root; projects_root=$record.projects_root; task_name=$old.task_name}
        Update-LogonTask $active
        Write-Json $currentPath $active
        Write-Output "Rolled back to $previous"
        exit 0
    }
    $manifest = Assert-Package (FullPath $PackageRoot)
    $destination = Join-Path $AppRoot $manifest.version
    if (Test-Path -LiteralPath $destination) { throw "Version already installed: $destination" }
    if ($old) {
        if ($old.state_root -ine $StateRoot -or $old.projects_root -ine $ProjectsRoot) { throw 'Upgrade must preserve state/projects roots' }
        Stop-App $old
    }
    New-Item -ItemType Directory -Force -Path $AppRoot | Out-Null
    $stage = Join-Path $AppRoot ('.staging-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    Get-ChildItem -Force -LiteralPath $PackageRoot | Copy-Item -Recurse -Destination $stage
    $null = Assert-Package $stage
    foreach ($folder in @($StateRoot, "$StateRoot\runtime", "$StateRoot\tasks", "$StateRoot\logs", $ProjectsRoot)) {
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
    }
    # The manifest uses a normalized runtime-home hash; rebind only this audited path.
    $cfg = Join-Path $stage 'runtime/venv/pyvenv.cfg'
    $lines = [IO.File]::ReadAllLines($cfg)
    $lines[0] = 'home = ' + (Join-Path $destination 'runtime/cpython')
    [IO.File]::WriteAllText($cfg, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
    $record = @{version=$manifest.version; state_root=$StateRoot; projects_root=$ProjectsRoot; code_sha=$manifest.code_sha}
    Write-Json (Join-Path $stage 'install.json') $record
    Move-Item -LiteralPath $stage -Destination $destination
    Set-AppAccess $destination $false
    $previous = if ($old) { $old.app_root } else { $null }
    $taskName = if ($old) { $old.task_name } else { $null }
    if ($RegisterLogonTask) {
        $hash = [Security.Cryptography.SHA256]::Create()
        try { $suffix = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($AppRoot.ToLowerInvariant())))).Replace('-','').Substring(0,16) }
        finally { $hash.Dispose() }
        $taskName = 'AgenticOS-PerUser-' + $suffix
    }
    $active = @{app_root=$destination; version=$manifest.version; previous=$previous; state_root=$StateRoot; projects_root=$ProjectsRoot; task_name=$taskName}
    Update-LogonTask $active
    Write-Json $currentPath $active
    if ($old -and $old.previous -and $old.previous -ine $previous) {
        $retired = Assert-SafeRoot $old.previous
        if ((Split-Path -Parent $retired) -ine $AppRoot) { throw 'Invalid retired version path' }
        Set-AppAccess $retired $true
        Remove-Item -Recurse -Force -LiteralPath $retired
    }
    Write-Output "Installed $destination"
    exit 0
} catch {
    Write-Error -ErrorAction Continue (($_ | Out-String) + $_.ScriptStackTrace)
    exit 1
}
