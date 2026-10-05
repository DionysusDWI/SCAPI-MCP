param([string]$Python='python', [string]$Venv=(Join-Path $PSScriptRoot '../.venv'))
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$checksum=Join-Path $root 'SHA256SUMS.txt'
if(Test-Path -LiteralPath $checksum){
    foreach($row in Get-Content -LiteralPath $checksum){
        if($row -notmatch '^([0-9a-fA-F]{64})  (.+)$'){throw 'Invalid checksum manifest'}
        $expected=$Matches[1];$relative=$Matches[2]
        $file=[IO.Path]::GetFullPath((Join-Path $root $relative))
        if(-not $file.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Checksum path outside release'}
        if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $expected){throw "Checksum mismatch: $relative"}
    }
}
& $Python -m venv $Venv
if($LASTEXITCODE -ne 0){throw 'Virtual environment creation failed'}
$venvPython=Join-Path $Venv 'Scripts/python.exe'
if(Test-Path -LiteralPath (Join-Path $root 'wheels')){
    & $venvPython -m pip install --no-cache-dir --no-index --find-links (Join-Path $root 'wheels') 'sc-bridge==0.5.0' 'sc-mcp==0.5.0'
}else{
    & $venvPython -m pip install --no-cache-dir -e (Join-Path $root 'packages/sc-bridge') -e (Join-Path $root 'packages/sc-mcp')
}
if($LASTEXITCODE -ne 0){throw 'Package installation failed'}
& $venvPython -m pip check
if($LASTEXITCODE -ne 0){throw 'Dependency verification failed'}
Write-Output "Installed. Entry: $(Join-Path $Venv 'Scripts/scapi-mcp.exe') --config <local.json> serve"
