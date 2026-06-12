# test_async.ps1
# Zapusk: .\test_async.ps1 -PdfPath "contract.pdf"

param(
    [string]$PdfPath = "contract.pdf",
    [string]$ApiKey = "test_key_123",
    [string]$BaseUrl = "http://localhost:8000"
)

$headers = @{ Authorization = "Bearer $ApiKey" }

function Invoke-Multipart {
    param(
        [string]$Uri,
        [string]$ApiKey,
        [string]$PdfPath,
        [hashtable]$ExtraFields = @{}
    )

    $boundary = [System.Guid]::NewGuid().ToString()
    $LF = "`r`n"

    $pdfBytes = [System.IO.File]::ReadAllBytes($PdfPath)
    $fileName = [System.IO.Path]::GetFileName($PdfPath)

    $bodyStream = New-Object System.IO.MemoryStream

    # PDF part
    $partHeader  = "--$boundary$LF"
    $partHeader += "Content-Disposition: form-data; name=`"file`"; filename=`"$fileName`"$LF"
    $partHeader += "Content-Type: application/pdf$LF$LF"
    $headerBytes = [System.Text.Encoding]::UTF8.GetBytes($partHeader)
    $bodyStream.Write($headerBytes, 0, $headerBytes.Length)
    $bodyStream.Write($pdfBytes, 0, $pdfBytes.Length)
    $bodyStream.Write([System.Text.Encoding]::UTF8.GetBytes($LF), 0, 2)

    # Extra fields
    foreach ($key in $ExtraFields.Keys) {
        $fieldPart  = "--$boundary$LF"
        $fieldPart += "Content-Disposition: form-data; name=`"$key`"$LF$LF"
        $fieldPart += "$($ExtraFields[$key])$LF"
        $fieldBytes = [System.Text.Encoding]::UTF8.GetBytes($fieldPart)
        $bodyStream.Write($fieldBytes, 0, $fieldBytes.Length)
    }

    # Close boundary
    $closing = "--$boundary--$LF"
    $closingBytes = [System.Text.Encoding]::UTF8.GetBytes($closing)
    $bodyStream.Write($closingBytes, 0, $closingBytes.Length)

    $bodyBytes = $bodyStream.ToArray()
    $bodyStream.Dispose()

    return Invoke-RestMethod -Uri $Uri -Method POST `
        -Headers @{ Authorization = "Bearer $ApiKey" } `
        -ContentType "multipart/form-data; boundary=$boundary" `
        -Body $bodyBytes
}

# 1. Sync analyze
Write-Host "`n=== 1. Sync analyze ===" -ForegroundColor Cyan
try {
    $r = Invoke-Multipart -Uri "$BaseUrl/v1/analyze" -ApiKey $ApiKey -PdfPath $PdfPath
    Write-Host "OK - traffic_light: $($r.traffic_light)" -ForegroundColor Green
} catch {
    Write-Host "FAIL: $_" -ForegroundColor Red
}

# 2. Async analyze
Write-Host "`n=== 2. Async analyze ===" -ForegroundColor Cyan
$jobId = $null
try {
    $r = Invoke-Multipart -Uri "$BaseUrl/v1/analyze" -ApiKey $ApiKey -PdfPath $PdfPath -ExtraFields @{ async = "true" }
    Write-Host "OK - job_id: $($r.job_id), status: $($r.status)" -ForegroundColor Green
    $jobId = $r.job_id
} catch {
    Write-Host "FAIL: $_" -ForegroundColor Red
    exit 1
}

# 3. Job status
Write-Host "`n=== 3. Job status ===" -ForegroundColor Cyan
try {
    $r = Invoke-RestMethod -Uri "$BaseUrl/v1/jobs/$jobId" -Method GET -Headers $headers
    Write-Host "OK - status: $($r.status)" -ForegroundColor Green
    if ($r.status -eq "completed") {
        Write-Host "     traffic_light: $($r.result.traffic_light)" -ForegroundColor Green
    }
    if ($r.status -eq "failed") {
        Write-Host "     error: $($r.error)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "FAIL: $_" -ForegroundColor Red
}

# 4. List jobs
Write-Host "`n=== 4. List jobs ===" -ForegroundColor Cyan
try {
    $r = Invoke-RestMethod -Uri "$BaseUrl/v1/jobs" -Method GET -Headers $headers
    Write-Host "OK - total: $($r.total)" -ForegroundColor Green
} catch {
    Write-Host "FAIL: $_" -ForegroundColor Red
}

# 5. Internal not in Swagger
Write-Host "`n=== 5. Internal hidden from Swagger ===" -ForegroundColor Cyan
try {
    $spec = Invoke-RestMethod -Uri "$BaseUrl/openapi.json" -Method GET
    $paths = $spec.paths.PSObject.Properties.Name
    $internal = $paths | Where-Object { $_ -like "*internal*" }
    if ($internal) {
        Write-Host "FAIL - internal visible in Swagger: $internal" -ForegroundColor Red
    } else {
        Write-Host "OK - internal endpoints hidden" -ForegroundColor Green
    }
} catch {
    Write-Host "FAIL: $_" -ForegroundColor Red
}

# 6. PDF cleanup
Write-Host "`n=== 6. Temp PDF cleanup ===" -ForegroundColor Cyan
$jobDir = ".\signfinder_jobs\$jobId"
if (Test-Path "$jobDir\input.pdf") {
    Write-Host "FAIL - input.pdf not deleted!" -ForegroundColor Red
} else {
    Write-Host "OK - input.pdf deleted" -ForegroundColor Green
}
if (Test-Path "$jobDir\job.json") {
    Write-Host "OK - job.json exists" -ForegroundColor Green
} else {
    Write-Host "WARN - job.json not found (GCS mode?)" -ForegroundColor Yellow
}

Write-Host "`nDone." -ForegroundColor Cyan
