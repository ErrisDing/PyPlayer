# PyPlayer - PowerShell Frontend
# Music/Video Player Command Line Interface

$Host.UI.RawUI.WindowTitle = "PyPlayer v1.0"

function Get-SupportedFormats {
    $formats = @{
        "Audio"  = @("MP3", "WAV", "FLAC", "OGG", "M4A", "AAC")
        "Video"  = @("AVI", "MP4", "MKV", "MOV", "WMV")
    }

    Write-Host "`nSupported Formats:`n" -ForegroundColor Cyan
    foreach ($k in $formats.Keys) {
        Write-Host "$k : $($formats[$k] -join ', ')"
    }
}

function Get-FileList {
    param([string]$Path = ".")

    $supported = @('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.avi', '.mp4', '.mkv', '.mov', '.wmv')

    if (-not (Test-Path $Path)) {
        Write-Host "Path does not exist: $Path" -ForegroundColor Red
        return
    }

    $files = @()
    Get-ChildItem -Path $Path -Recurse -File | ForEach-Object {
        if ($supported -contains $_.Extension.ToLower()) {
            $files += $_.FullName
        }
    }

    Write-Host "`nFound Media Files:`n" -ForegroundColor Cyan
    for ($i = 0; $i -lt [Math]::Min($files.Count, 20); $i++) {
        Write-Host "$($i+1). $($files[$i])"
    }
    if ($files.Count -gt 20) {
        Write-Host "... and $($files.Count - 20) more files"
    }

    return $files
}

function Start-PythonPlayer {
    param([string]$File)

    # Find Python command
    $pythonCmd = Get-Command python, py -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pythonCmd) {
        Write-Host "Error: Python not found. Please install Python first." -ForegroundColor Red
        return
    }

    Write-Host "`nPlaying: $($File)" -ForegroundColor Green

    # Build command arguments using & call operator properly
    $py = $pythonCmd.Source
    Start-Process -FilePath $py -ArgumentList "-u", (Join-Path $PSScriptRoot "player.py"), $File -Wait

    Write-Host "`nDone." -ForegroundColor Cyan
}

function Show-Usage {
    Write-Host "`nUsage:`n" -ForegroundColor Yellow
    Write-Host "  powershell frontend.ps1 [options]" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Options:" -ForegroundColor Cyan
    Write-Host "  -f, --file PATH    Play specified media file" -ForegroundColor White
    Write-Host "  -l, --list         List media files in current directory" -ForegroundColor White
    Write-Host "  -i, --info         Show supported formats info" -ForegroundColor White

    # Display help when no file argument provided
    Get-SupportedFormats
}

# Parse command-line arguments using simple if statements for compatibility
$file = $null
$listMode = $false
$infoMode = $false

for ($i = 1; $i -lt $args.Length; $i++) {
    switch ($args[$i]) {
        "-f" { $file = $args[++$i]; break }
        "--file" { $file = $args[++$i]; break }
        "-l" { $listMode = $true; break }
        "--list" { $listMode = $true; break }
        "-i" { $infoMode = $true; break }
        "--info" { $infoMode = $true; break }
        default { Write-Host "Unknown parameter: $($args[$i])"; break }
    }
}

# Execute based on mode
if ($listMode) {
    Get-FileList -Path (Get-Location).Path
} elseif ($infoMode) {
    Show-Usage
} elseif ($file) {
    Start-PythonPlayer -File $file
} else {
    Show-Usage
}
