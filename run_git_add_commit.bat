@echo off
cd /d "%~dp0"
git add -A
git status
if exist .git\MERGE_HEAD (
    git commit --no-edit
) else (
    git commit -m "Knowledge graph: traverse filters, postprocess merge duplicates, no DataSource in paths"
)
