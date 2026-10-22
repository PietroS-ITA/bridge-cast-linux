#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$UsbPcapCmd,
    [string]$RootHub,
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'This script must run on Windows.'
}
if ($Host.Name -ne 'ConsoleHost') {
    throw 'Run this script from Windows Terminal or a console PowerShell window so q can stop the capture.'
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run PowerShell as Administrator, then run this script again.'
}

function Resolve-UsbPcapCmd {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        $command = Get-Command -Name $ExplicitPath -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
        if (Test-Path -LiteralPath $ExplicitPath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $ExplicitPath).Path
        }
        throw "USBPcapCMD.exe was not found at '$ExplicitPath'."
    }

    $candidates = @()
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles 'USBPcap\USBPcapCMD.exe')
        $candidates += (Join-Path $env:ProgramFiles 'Wireshark\extcap\USBPcapCMD.exe')
    }
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} 'USBPcap\USBPcapCMD.exe')
        $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Wireshark\extcap\USBPcapCMD.exe')
    }

    $fromPath = Get-Command -Name 'USBPcapCMD.exe' -ErrorAction SilentlyContinue
    if ($fromPath) {
        $candidates += $fromPath.Source
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw 'USBPcapCMD.exe was not found. Install Wireshark with USBPcap, or pass -UsbPcapCmd.'
}

function Invoke-UsbPcapQuery {
    param([string[]]$Arguments)

    $lines = @(& $script:UsbPcapPath @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    $exitCode = $LASTEXITCODE
    [pscustomobject]@{
        ExitCode = $exitCode
        Lines = $lines
    }
}

$script:UsbPcapPath = Resolve-UsbPcapCmd -ExplicitPath $UsbPcapCmd

$interfaceResult = Invoke-UsbPcapQuery -Arguments @('--extcap-interfaces')
if ($interfaceResult.ExitCode -ne 0) {
    throw "USBPcapCMD could not enumerate capture interfaces: $($interfaceResult.Lines -join ' ')"
}

$interfaces = @(
    foreach ($line in $interfaceResult.Lines) {
        if ($line -match '^interface \{value=(?<value>[^}]+)\}\{display=(?<display>[^}]+)\}') {
            [pscustomobject]@{
                Value = $Matches.value
                Display = $Matches.display
            }
        }
    }
)
if ($interfaces.Count -eq 0) {
    throw 'No USBPcap root hubs were found. Check that USBPcap is installed and Windows has been restarted.'
}

if ($RootHub) {
    if ($RootHub -match '^\d+$') {
        $requestedRootHub = "\\.\USBPcap$RootHub"
    }
    elseif ($RootHub -like '\\.\*') {
        $requestedRootHub = $RootHub
    }
    else {
        $requestedRootHub = "\\.\$RootHub"
    }

    $selectedInterface = $interfaces | Where-Object { $_.Value -ieq $requestedRootHub -or $_.Display -ieq $RootHub } | Select-Object -First 1
    if (-not $selectedInterface) {
        throw "Root hub '$RootHub' was not found. Available hubs: $($interfaces.Display -join ', ')"
    }
}
else {
    $matchingInterfaces = @(
        foreach ($interface in $interfaces) {
            $config = Invoke-UsbPcapQuery -Arguments @('--extcap-interface', $interface.Value, '--extcap-config')
            if ($config.ExitCode -eq 0 -and (($config.Lines -join "`n") -match 'BRIDGE[\s_-]*CAST')) {
                $interface
            }
        }
    )

    if ($matchingInterfaces.Count -eq 1) {
        $selectedInterface = $matchingInterfaces[0]
    }
    else {
        Write-Host ''
        if ($matchingInterfaces.Count -gt 1) {
            Write-Host 'The BRIDGE CAST appears on multiple USBPcap root hubs:'
            $choices = $matchingInterfaces
        }
        else {
            Write-Host 'Automatic detection did not find the BRIDGE CAST. Available root hubs:'
            $choices = $interfaces
        }

        for ($index = 0; $index -lt $choices.Count; $index++) {
            Write-Host ("  {0}. {1}" -f ($index + 1), $choices[$index].Display)
        }

        $selection = 0
        $answer = Read-Host 'Enter the number of the root hub to capture'
        if (-not [int]::TryParse($answer, [ref]$selection) -or $selection -lt 1 -or $selection -gt $choices.Count) {
            throw 'Invalid root hub selection.'
        }
        $selectedInterface = $choices[$selection - 1]
    }
}

if (-not $OutputPath) {
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $OutputPath = Join-Path $env:SystemDrive "bridgecast-usb-$timestamp.pcap"
}
elseif ([IO.Path]::GetExtension($OutputPath) -ine '.pcap') {
    throw 'OutputPath must use the .pcap extension.'
}

$OutputPath = [IO.Path]::GetFullPath($OutputPath)
if ($OutputPath -match '[^\x20-\x7E]') {
    throw 'Use an ASCII-only output path; USBPcapCMD expects a Windows ANSI path.'
}
if (Test-Path -LiteralPath $OutputPath) {
    throw "The output file already exists: $OutputPath"
}
$outputDirectory = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw "The output directory does not exist: $outputDirectory"
}

Write-Host ''
Write-Host ("USBPcapCMD: {0}" -f $script:UsbPcapPath)
Write-Host ("Root hub:     {0}" -f $selectedInterface.Display)
Write-Host ("Output file:  {0}" -f $OutputPath)
Write-Host ''
Write-Host 'Before capture, close apps that use BRIDGE CAST audio.'
Write-Host 'When capture starts:'
Write-Host '  1. Unplug and reconnect the BRIDGE CAST once to capture its USB descriptors.'
Write-Host '  2. In BRIDGE CAST Driver Settings, change 96 kHz to 48 kHz, then back to 96 kHz.'
Write-Host '  3. Return to this console and press lowercase q to stop and close the capture.'
Write-Host 'Do not play or record audio during capture.'
Write-Host ''
$null = Read-Host 'Press Enter to start capture, or Ctrl+C to cancel'

& $script:UsbPcapPath -d $selectedInterface.Value -o $OutputPath --capture-from-new-devices
$captureExitCode = $LASTEXITCODE

if ($captureExitCode -ne 0) {
    throw "USBPcapCMD exited with code $captureExitCode. Check its output above."
}
if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
    throw "USBPcapCMD did not create the capture file: $OutputPath"
}

$capture = Get-Item -LiteralPath $OutputPath
if ($capture.Length -le 24) {
    throw "The capture is empty or incomplete: $OutputPath"
}

Write-Host ''
Write-Host ("Capture saved: {0} ({1} bytes)" -f $capture.FullName, $capture.Length)
Write-Host 'The file may contain USB serial numbers. Keep it private and do not commit it to Git.'
