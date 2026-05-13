@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title SisacademiChat - Consola

set "CHAT_BAT=%~f0"
set "CHAT_INITIAL_QUESTION=%*"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$path=$env:CHAT_BAT; $raw=Get-Content -LiteralPath $path -Raw -Encoding UTF8; $marker='::'+'POWERSHELL'+'::'; $script=($raw -split [regex]::Escape($marker),2)[1]; Invoke-Expression $script"
exit /b %ERRORLEVEL%

::POWERSHELL::
$ErrorActionPreference = "Stop"

try {
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

# Configuracion hardcoded — chat.bat es autosuficiente, no lee config.env.
# Si rotas la API_KEY, actualiza tambien este archivo.
$ApiKey = "uoemm2mEzkGwxVS_6T7WPvOdgwB5kyyHScOdssq-zfI"
$ServerUrl = "http://62.146.182.204:8090"
$BaseUrl = "$ServerUrl/api/v1"
$ChatUrl = "$BaseUrl/chat"
$HealthUrl = "$BaseUrl/health"
$Headers = @{ "X-API-Key" = $ApiKey }

function ConvertFrom-Utf8Response {
    param($Response)

    $stream = $Response.RawContentStream
    if ($stream -and $stream.CanSeek) {
        $stream.Position = 0
    }

    if ($stream) {
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
        try {
            return $reader.ReadToEnd()
        } finally {
            $reader.Dispose()
        }
    }

    if ($Response.Content -is [byte[]]) {
        return [System.Text.Encoding]::UTF8.GetString($Response.Content)
    }

    return [string]$Response.Content
}

function Invoke-JsonUtf8 {
    param(
        [string]$Uri,
        [string]$Method = "Get",
        [hashtable]$Headers = @{},
        [byte[]]$Body,
        [string]$ContentType,
        [int]$TimeoutSec = 30
    )

    $params = @{
        Uri = $Uri
        Method = $Method
        TimeoutSec = $TimeoutSec
        UseBasicParsing = $true
    }

    if ($Headers.Count -gt 0) {
        $params.Headers = $Headers
    }
    if ($PSBoundParameters.ContainsKey("Body")) {
        $params.Body = $Body
    }
    if ($ContentType) {
        $params.ContentType = $ContentType
    }

    $rawResponse = Invoke-WebRequest @params
    $json = ConvertFrom-Utf8Response -Response $rawResponse
    if (-not $json) {
        return $null
    }

    return $json | ConvertFrom-Json
}

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
}

function Test-Service {
    try {
        return Invoke-JsonUtf8 -Uri $HealthUrl -Method Get -TimeoutSec 8
    } catch {
        return $null
    }
}

function Write-HttpError {
    param($ErrorRecord)

    $response = $ErrorRecord.Exception.Response
    if ($response) {
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream(), [System.Text.Encoding]::UTF8, $true)
            $body = $reader.ReadToEnd()
            $reader.Close()
            if ($body) {
                Write-Host "Detalle: $body" -ForegroundColor DarkYellow
                return
            }
        } catch {
        }
    }

    Write-Host $ErrorRecord.Exception.Message -ForegroundColor DarkYellow
}

$script:CurrentConversationId = $null

function Send-ChatQuestion {
    param([string]$Question)

    if (-not $Question.Trim()) {
        return
    }

    # Reutilizar conversation_id de la pregunta anterior para que el servidor
    # mantenga memoria conversacional (sino genera UUID nuevo y pierde contexto).
    $payloadObj = @{ message = $Question.Trim() }
    if ($script:CurrentConversationId) {
        $payloadObj.conversation_id = $script:CurrentConversationId
    }
    $payload = $payloadObj | ConvertTo-Json -Depth 5
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($payload)

    Write-Host ""
    Write-Host "Consultando..." -ForegroundColor DarkGray
    $timer = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $response = Invoke-JsonUtf8 `
            -Uri $ChatUrl `
            -Method Post `
            -Headers $Headers `
            -ContentType "application/json; charset=utf-8" `
            -Body $bodyBytes `
            -TimeoutSec 180
    } catch {
        $timer.Stop()
        Write-Host ""
        Write-Host "No pude consultar el chat." -ForegroundColor Red
        Write-HttpError -ErrorRecord $_
        return
    }

    $timer.Stop()

    # Guardar conversation_id para el proximo turno (memoria conversacional).
    if ($response.conversation_id) {
        $script:CurrentConversationId = $response.conversation_id
    }

    Write-Section "Respuesta"
    if ($response.answer) {
        Write-Host $response.answer
    } else {
        Write-Host "Sin respuesta." -ForegroundColor Yellow
    }

    $sources = @($response.sources)
    if ($sources.Count -gt 0) {
        Write-Section "Fuentes"
        $i = 1
        foreach ($source in ($sources | Select-Object -First 6)) {
            $page = ""
            if ($null -ne $source.page_number -and "$($source.page_number)" -ne "") {
                $page = ", pagina $($source.page_number)"
            }

            $section = ""
            if ($source.section) {
                $section = ", seccion: $($source.section)"
            }

            $score = "0.000"
            if ($null -ne $source.score) {
                $score = "{0:N3}" -f [double]$source.score
            }

            Write-Host ("  {0}. {1}{2}{3} (score {4})" -f $i, $source.source_name, $page, $section, $score) -ForegroundColor Gray

            if ($source.chunk_text) {
                $snippet = (($source.chunk_text -replace "\s+", " ").Trim())
                if ($snippet.Length -gt 180) {
                    $snippet = $snippet.Substring(0, 180) + "..."
                }
                Write-Host "     $snippet" -ForegroundColor DarkGray
            }

            $i++
        }
    }

    if ($response.latency_ms) {
        Write-Host ""
        Write-Host ("Tiempo: {0} ms" -f $response.latency_ms) -ForegroundColor DarkGray
    } else {
        Write-Host ""
        Write-Host ("Tiempo local: {0:N1} s" -f $timer.Elapsed.TotalSeconds) -ForegroundColor DarkGray
    }
}

Write-Host "============================================"
Write-Host "  SisacademiChat - Consola de preguntas"
Write-Host "============================================"
Write-Host ""
Write-Host "Endpoint: $ChatUrl"

$health = Test-Service
if (-not $health) {
    Write-Host ""
    Write-Host "El servicio no responde en $HealthUrl" -ForegroundColor Red
    Write-Host "Abre otra ventana y ejecuta run.bat; luego vuelve a abrir chat.bat." -ForegroundColor Yellow
    exit 1
}

Write-Host ("Base: {0} fuentes, {1} fragmentos. Ollama: {2}" -f $health.knowledge_sources, $health.knowledge_chunks, $health.ollama) -ForegroundColor Gray
Write-Host ""

$initialQuestion = $env:CHAT_INITIAL_QUESTION
if ($null -ne $initialQuestion) {
    $initialQuestion = $initialQuestion.Trim()
}

if ($initialQuestion) {
    Send-ChatQuestion -Question $initialQuestion
    exit 0
}

Write-Host "Escribe una pregunta y presiona Enter."
Write-Host "Comandos: salir/exit/q, cls/limpiar, nueva (resetear memoria conversacional)"

while ($true) {
    Write-Host ""
    if ($script:CurrentConversationId) {
        $prompt = "Tu pregunta [conv: $($script:CurrentConversationId.Substring(0,8))...]"
    } else {
        $prompt = "Tu pregunta [conv: nueva]"
    }
    $question = Read-Host $prompt

    if ($null -eq $question) {
        continue
    }

    $command = $question.Trim().ToLowerInvariant()
    if ($command -in @("salir", "exit", "q", "quit")) {
        break
    }

    if ($command -in @("cls", "clear", "limpiar")) {
        Clear-Host
        continue
    }

    if ($command -in @("nueva", "new", "reset")) {
        $script:CurrentConversationId = $null
        Write-Host "Sesion reseteada. La proxima pregunta empieza una conversacion nueva." -ForegroundColor Yellow
        continue
    }

    Send-ChatQuestion -Question $question
}
