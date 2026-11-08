param([string]$InputPath,[string]$OutputPath,[string]$OwnerFile,[switch]$CleanupOnly)
$ErrorActionPreference = 'Stop'
$OwnerFile = [IO.Path]::GetFullPath($OwnerFile)
if ($CleanupOnly) {
    if (Test-Path -LiteralPath $OwnerFile) {
        $owner = Get-Content -LiteralPath $OwnerFile -Raw | ConvertFrom-Json
        $ownedProcess = Get-Process -Id ([int]$owner.processId) -ErrorAction SilentlyContinue
        if ($ownedProcess -and $ownedProcess.ProcessName -eq 'WINWORD' -and $ownedProcess.StartTime.ToUniversalTime().Ticks -eq [long]$owner.startTicks) {
            Stop-Process -Id $ownedProcess.Id -Force
        }
    }
    exit 0
}
$InputPath = [IO.Path]::GetFullPath($InputPath)
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$priorProcesses = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$word = $null; $document = $null; $automationOwned = $false; $oldSecurity = $null; $oldLinks = $null; $stage = 'create_word'; $dontSave = 0
try {
    $word = New-Object -ComObject Word.Application
    if ($word.Documents.Count -ne 0) { throw 'Automation instance contains existing documents.' }
    $automationOwned = $true
    $newProcesses = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Where-Object { $priorProcesses -notcontains $_.Id })
    if ($newProcesses.Count -eq 1) {
        $ownedProcess = $newProcesses[0]
        @{ processId = $ownedProcess.Id; startTicks = $ownedProcess.StartTime.ToUniversalTime().Ticks } | ConvertTo-Json | Set-Content -LiteralPath $OwnerFile -Encoding UTF8
    }
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $oldSecurity = $word.AutomationSecurity; $word.AutomationSecurity = 3
    $oldLinks = $word.Options.UpdateLinksAtOpen; $word.Options.UpdateLinksAtOpen = $false
    $notProvided = [guid]::NewGuid().ToString('N')
    $missing = [Type]::Missing; $yes = $true; $no = $false
    $stage = 'open_document'
    $document = $word.Documents.OpenNoRepairDialog([ref]$InputPath,[ref]$no,[ref]$yes,[ref]$no,[ref]$notProvided,[ref]$notProvided,[ref]$no,[ref]$notProvided,[ref]$notProvided,[ref]$missing,[ref]$missing,[ref]$no,[ref]$no,[ref]$missing,[ref]$yes)
    $stage = 'export_pdf'
    $document.ExportAsFixedFormat($OutputPath,17,$false,0,0,1,1,0,$false)
    if (-not (Test-Path -LiteralPath $OutputPath)) { throw 'No converted PDF.' }
} catch {
    [Console]::Error.WriteLine('WORD_CONVERSION_FAILED:'+$stage+':'+$_.Exception.HResult)
    exit 1
} finally {
    if ($automationOwned) {
        if ($document) { try { $document.Close([ref]$dontSave) } catch {} }
        if ($null -ne $oldLinks) { try { $word.Options.UpdateLinksAtOpen = $oldLinks } catch {} }
        if ($null -ne $oldSecurity) { try { $word.AutomationSecurity = $oldSecurity } catch {} }
        if ($word) {
            try {
                if ($word.Documents.Count -eq 0) { $word.Quit([ref]$dontSave) }
                elseif (Test-Path -LiteralPath $OwnerFile) { Remove-Item -LiteralPath $OwnerFile }
            } catch {}
        }
    }
    if ($document) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) }
    if ($word) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
