# Run from repo root: .\run_git_add_commit.ps1
# Adds all changes and commits (or completes merge if in progress).
Set-Location $PSScriptRoot

# Resolve merge conflicts first: fail if any file has conflict markers
$conflicted = Get-ChildItem -Recurse -File -Include *.py,*.js,*.jsx,*.ts,*.tsx,*.json,*.yml,*.yaml,*.md | 
    Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.FullName -notmatch '\\node_modules\\' } |
    ForEach-Object {
        $c = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
        if ($c -match '<<<<<<< |>>>>>>> ') { $_.FullName }
    }
if ($conflicted) {
    Write-Host "Merge conflict markers found in:" -ForegroundColor Red
    $conflicted
    exit 1
}

git add -A
git status

if (Test-Path .git\MERGE_HEAD) {
    Write-Host "Completing merge commit..."
    git commit --no-edit
} else {
    git commit -m "Knowledge graph: traverse filters, postprocess merge duplicates, no DataSource in paths"
}
