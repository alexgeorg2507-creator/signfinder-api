# Apply SQL migrations against a Cloud SQL instance via Cloud SQL Auth Proxy.
# Usage: .\migrations\apply.ps1 -Env test   (or prod)

param(
    [ValidateSet("test","prod")]
    [string]$Env = "test"
)

$projects = @{
    test = "signfinder-cab-test"
    prod = "signfinder-c1163"
}
$instances = @{
    test = "signfinder-cab-test:europe-west1:signfinder-db"
    prod = "signfinder-c1163:europe-west1:signfinder-db"
}

$project  = $projects[$Env]
$instance = $instances[$Env]
$port     = 5432
$dbName   = "signfinder"
$dbUser   = "signfinder"

Write-Host "Starting Cloud SQL Auth Proxy for $instance ..."
$proxy = Start-Process -FilePath "cloud_sql_proxy" `
    -ArgumentList "-instances=${instance}=tcp:${port}" `
    -PassThru -NoNewWindow

Start-Sleep -Seconds 3

Write-Host "Applying migrations to $dbName on $Env ..."
$migrations = Get-ChildItem "$PSScriptRoot\*.sql" | Sort-Object Name
foreach ($f in $migrations) {
    Write-Host "  -> $($f.Name)"
    $env:PGPASSWORD = $dbUser  # set actual password or read from Secret Manager
    psql -h localhost -p $port -U $dbUser -d $dbName -f $f.FullName
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Migration $($f.Name) FAILED"
        $proxy | Stop-Process
        exit 1
    }
}

$proxy | Stop-Process
Write-Host "All migrations applied successfully."
