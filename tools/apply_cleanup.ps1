param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$cleanupWorkspace = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path.TrimEnd('\')
$cleanupPlan = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($cleanupPlan.workspace).TrimEnd('\') -ne $cleanupWorkspace) { throw 'Manifest belongs to another workspace.' }
function Assert-CleanupPath([string]$Candidate) {
    $absolute = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    if (-not $absolute.StartsWith($cleanupWorkspace + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe cleanup target: $absolute" }
    return $absolute
}
function Assert-Unprotected([string]$Candidate) {
    foreach ($protected in $cleanupPlan.protected_directories) {
        $safe = [IO.Path]::GetFullPath($protected).TrimEnd('\')
        if ($Candidate -eq $safe -or $Candidate.StartsWith($safe + '\', [StringComparison]::OrdinalIgnoreCase) -or $safe.StartsWith($Candidate + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Protected path: $Candidate" }
    }
    foreach ($protected in $cleanupPlan.protected_files) {
        $safe = [IO.Path]::GetFullPath($protected)
        if ($Candidate -eq $safe -or $safe.StartsWith($Candidate + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Protected reference: $Candidate" }
    }
}
# Validate every resolved absolute target and nested reparse point before mutation.
$allowedExtensions = @('.mp4','.mkv','.webm','.mov','.avi','.m4v','.wav','.mp3','.flac','.aac','.m4a','.png','.jpg','.jpeg','.gif','.npy','.npz','.part','.ytdl','.aria2')
foreach ($item in $cleanupPlan.delete_files) {
    $target = Assert-CleanupPath $item
    Assert-Unprotected $target
    if ([IO.Path]::GetExtension($target).ToLowerInvariant() -notin $allowedExtensions) { throw 'Only generated media/cache files may be individually deleted.' }
}
foreach ($item in $cleanupPlan.delete_trees) {
    $target = Assert-CleanupPath $item
    Assert-Unprotected $target
    $allowed = $target.StartsWith($cleanupWorkspace + '\data\', [StringComparison]::OrdinalIgnoreCase) -or $target -in @("$cleanupWorkspace\.venv-gpu", "$cleanupWorkspace\.pytest_cache", "$cleanupWorkspace\__pycache__", "$cleanupWorkspace\reel_engine\__pycache__", "$cleanupWorkspace\tests\__pycache__", "$cleanupWorkspace\tools\__pycache__")
    if (-not $allowed) { throw "Unapproved recursive target: $target" }
    if (Test-Path -LiteralPath $target) {
        $links = @(Get-Item -LiteralPath $target -Force; Get-ChildItem -LiteralPath $target -Recurse -Force) | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
        if ($links) { throw "Refusing recursive operation containing reparse points: $target" }
    }
}
foreach ($move in $cleanupPlan.archive_moves) {
    $source = Assert-CleanupPath $move.source
    $destination = Assert-CleanupPath $move.destination
    if (-not $source.StartsWith("$cleanupWorkspace\workflow\jobs\", [StringComparison]::OrdinalIgnoreCase) -or -not $destination.StartsWith("$cleanupWorkspace\workflow\history\", [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid job archive move.' }
    if (Test-Path -LiteralPath $destination) { throw 'Archive destination already exists.' }
    $record = Get-Content -LiteralPath (Join-Path $source 'job.json') -Raw | ConvertFrom-Json
    if ($record.publishing -or $record.post_id -or (Split-Path -Leaf $source) -eq 'web3approved') { throw 'Published/pending/reference jobs are protected.' }
}
$deleted = 0
foreach ($item in $cleanupPlan.delete_files) { if (Test-Path -LiteralPath $item) { Remove-Item -LiteralPath $item -Force; $deleted++ } }
foreach ($item in $cleanupPlan.delete_trees) { if (Test-Path -LiteralPath $item) { Remove-Item -LiteralPath $item -Recurse -Force } }
foreach ($move in $cleanupPlan.archive_moves) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $move.destination) -Force | Out-Null
    Move-Item -LiteralPath $move.source -Destination $move.destination
}
$notice = @{ cleanup_id=$cleanupPlan.cleanup_id; old_media_removed=$true; resumable=$false; note='Historical records only. Old sources/previews were removed by user request. Fresh analysis creates new active jobs; no prior preview approval carries over.' }
$notice | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $cleanupPlan.history 'ARCHIVE-NOTICE.json') -Encoding UTF8
@{ deleted_media_files=$deleted; removed_trees=@($cleanupPlan.delete_trees).Count; archived_jobs=@($cleanupPlan.archive_moves).Count; planned_deleted_bytes=$cleanupPlan.bytes_to_delete; published=$false } | ConvertTo-Json
