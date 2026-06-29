# Run AFTER Cloud SQL instances finish creating (state=RUNNABLE).
# Creates the database, user, and applies the initial migration.
# Usage: .\migrations\post_sql_setup.ps1 -Env test
#        .\migrations\post_sql_setup.ps1 -Env prod

param(
    [ValidateSet("test","prod")]
    [string]$Env = "test"
)

$config = @{
    test = @{ project = "signfinder-cab-test"; instance = "signfinder-cab-test:europe-west1:signfinder-db" }
    prod = @{ project = "signfinder-c1163";    instance = "signfinder-c1163:europe-west1:signfinder-db"    }
}

$project  = $config[$Env].project
$instance = $config[$Env].instance
$dbName   = "signfinder"
$dbUser   = "signfinder"
$port     = 5432

# ── Step 1: verify instance is RUNNABLE ──────────────────────────────────────
Write-Host "Checking Cloud SQL instance state..."
$state = (gcloud sql instances describe signfinder-db --project=$project --format="value(state)" 2>&1).Trim()
if ($state -ne "RUNNABLE") {
    Write-Error "Instance not RUNNABLE (state=$state). Wait and retry."
    exit 1
}
Write-Host "  OK: $state"

# ── Step 2: create DB and user ────────────────────────────────────────────────
Write-Host "Creating database '$dbName'..."
gcloud sql databases create $dbName --instance=signfinder-db --project=$project --quiet 2>&1

Write-Host "Creating user '$dbUser'..."
$pw = Read-Host "Enter DB password for '$dbUser'" -AsSecureString
$pwPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
gcloud sql users create $dbUser --instance=signfinder-db --project=$project --password=$pwPlain --quiet 2>&1

# ── Step 3: store password in Secret Manager ──────────────────────────────────
Write-Host "Storing password in Secret Manager..."
$pwPlain | gcloud secrets versions add db-password --data-file=- --project=$project --quiet 2>&1
Write-Host "  Stored in: projects/$project/secrets/db-password"

# ── Step 4: apply migration via Cloud SQL Auth Proxy ─────────────────────────
Write-Host "Starting Cloud SQL Auth Proxy..."
$proxy = Start-Process -FilePath "cloud-sql-proxy" `
    -ArgumentList "--port=$port $instance" `
    -PassThru -NoNewWindow
Start-Sleep -Seconds 4

Write-Host "Applying 001_init.sql..."
$env:PGPASSWORD = $pwPlain
$migDir = Join-Path $PSScriptRoot "."
Get-ChildItem "$migDir\*.sql" | Sort-Object Name | ForEach-Object {
    Write-Host "  -> $($_.Name)"
    psql -h 127.0.0.1 -p $port -U $dbUser -d $dbName -f $_.FullName
    if ($LASTEXITCODE -ne 0) { Write-Error "Migration failed: $($_.Name)"; $proxy | Stop-Process; exit 1 }
}

$proxy | Stop-Process
Write-Host ""
Write-Host "M0 post-SQL setup complete for '$Env'."
Write-Host "Next: fill in .env.$Env with:"
Write-Host "  DATABASE_URL=postgresql+asyncpg://${dbUser}:<password>@/signfinder?host=/cloudsql/$instance"
Write-Host "  CLOUD_SQL_INSTANCE=$instance"
