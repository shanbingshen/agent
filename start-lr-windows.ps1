Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = if ($env:ARTHRA_ROOT) { $env:ARTHRA_ROOT } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$LrPython = if ($env:LR_PY) { $env:LR_PY } else { Join-Path $Root ".venv\Scripts\python.exe" }
$Pnpm = if ($env:PNPM) { $env:PNPM } else { "pnpm" }
$NodeBin = if ($env:NODE_BIN) { $env:NODE_BIN } else { "" }

$ApiHost = if ($env:API_HOST) { $env:API_HOST } else { "127.0.0.1" }
$ApiPort = if ($env:API_PORT) { [int]$env:API_PORT } else { 18089 }
$WebHost = if ($env:WEB_HOST) { $env:WEB_HOST } else { "127.0.0.1" }
$WebPort = if ($env:WEB_PORT) { [int]$env:WEB_PORT } else { 18090 }
$OpenBrowser = if ($env:OPEN_BROWSER) { $env:OPEN_BROWSER } else { "1" }
$IndustrialDataProvider = if ($env:INDUSTRIAL_DATA_PROVIDER) { $env:INDUSTRIAL_DATA_PROVIDER } else { "mock" }
$ThingsBoardUrl = if ($env:THINGSBOARD_URL) { $env:THINGSBOARD_URL } else { "http://127.0.0.1:9090" }
$ThingsBoardUsername = if ($env:THINGSBOARD_USERNAME) { $env:THINGSBOARD_USERNAME } else { "tenant@thingsboard.org" }
$ThingsBoardPassword = if ($env:THINGSBOARD_PASSWORD) { $env:THINGSBOARD_PASSWORD } else { "tenant" }
$BrowserApiHost = if ($ApiHost -eq "0.0.0.0") { "localhost" } else { $ApiHost }
$CorsOrigins = if ($env:CORS_ORIGINS) {
  $env:CORS_ORIGINS
} else {
  "http://${WebHost}:$WebPort,http://localhost:$WebPort,http://127.0.0.1:$WebPort"
}
$NoProxy = if ($env:NO_PROXY) { $env:NO_PROXY } else { "127.0.0.1,localhost" }

$LogDir = Join-Path $Root ".local-dev\logs"
$RunDir = Join-Path $Root ".local-dev\run"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$DbFile = if ($env:DB_FILE) { $env:DB_FILE } else { Join-Path $RunDir "arthra-lr-$Timestamp.db" }
$ApiLog = Join-Path $LogDir "api-lr-windows.log"
$WebLog = Join-Path $LogDir "web-lr-windows.log"
$script:ApiJob = $null
$script:WebJob = $null

function Say-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Message"
}

function Fail {
  param([string]$Message)
  throw "启动失败：$Message"
}

function Resolve-Executable {
  param(
    [string]$Candidate,
    [string]$Name
  )
  if ([string]::IsNullOrWhiteSpace($Candidate)) {
    Fail "没有指定 $Name 可执行文件。"
  }
  if (Test-Path -LiteralPath $Candidate) {
    return (Resolve-Path -LiteralPath $Candidate).Path
  }
  $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
  if ($null -ne $Command) {
    return $Command.Source
  }
  Fail "找不到 $Name：$Candidate"
}

function Test-PortInUse {
  param([int]$Port)
  try {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
  } catch {
    $Pattern = "[:.]$Port\s+.*LISTENING"
    return [bool](netstat -ano -p tcp | Select-String -Pattern $Pattern)
  }
}

function Wait-ForUrl {
  param(
    [string]$Url,
    [string]$Name,
    [string]$LogFile,
    $Job = $null
  )
  for ($Attempt = 1; $Attempt -le 60; $Attempt++) {
    try {
      $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
      if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500) {
        Say-Step "$Name 已就绪：$Url"
        return
      }
    } catch {
      Start-Sleep -Seconds 1
    }
    if ($null -ne $Job -and $Job.State -ne "Running") {
      Write-Host ""
      Write-Host "$Name 启动日志："
      if (Test-Path -LiteralPath $LogFile) {
        Get-Content -LiteralPath $LogFile -Tail 80
      }
      Fail "$Name 已退出，未能就绪"
    }
  }
  Write-Host ""
  Write-Host "$Name 启动日志："
  if (Test-Path -LiteralPath $LogFile) {
    Get-Content -LiteralPath $LogFile -Tail 80
  }
  Fail "$Name 未能在 60 秒内就绪"
}

function Stop-JobIfRunning {
  param($Job)
  if ($null -ne $Job) {
    Stop-Job -Job $Job -ErrorAction SilentlyContinue
    Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
  }
}

function Test-FrontendToolchain {
  param(
    [string]$PnpmExe,
    [string]$NodeDirectory,
    [string]$WebRoot
  )
  $OldPath = $env:PATH
  try {
    if (-not [string]::IsNullOrWhiteSpace($NodeDirectory)) {
      $env:PATH = "$NodeDirectory;$env:PATH"
    }
    & $PnpmExe --dir $WebRoot exec vite --version *> $null
    if ($LASTEXITCODE -ne 0) {
      Fail "前端 Vite 无法执行。请先执行：pnpm --dir `"$WebRoot`" install"
    }
  } finally {
    $env:PATH = $OldPath
  }
}

function Ensure-PythonEnvironment {
  param([string]$ProjectRoot)
  if (Test-Path -LiteralPath $LrPython) { return }
  $Uv = Get-Command uv -ErrorAction SilentlyContinue
  if ($null -eq $Uv) {
    Fail "找不到项目 Python 环境。请安装 uv，或设置 LR_PY 指向可用的 python.exe"
  }
  Say-Step "未找到项目 Python 环境，正在执行 uv sync --dev"
  $BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  $PythonCandidate = if ($env:UV_PYTHON) {
    $env:UV_PYTHON
  } elseif (Test-Path -LiteralPath $BundledPython) {
    $BundledPython
  } else {
    $null
  }
  if ($PythonCandidate) {
    & $Uv.Source sync --dev --project $ProjectRoot --python $PythonCandidate
  } else {
    & $Uv.Source sync --dev --project $ProjectRoot
  }
  if ($LASTEXITCODE -ne 0) {
    Fail "uv sync --dev 执行失败"
  }
}

try {
  Set-Location -LiteralPath $Root
  New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
  New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

  Say-Step "检查 LR 环境和前端工具链"
  Ensure-PythonEnvironment -ProjectRoot $Root
  $LrPython = Resolve-Executable -Candidate $LrPython -Name "LR Python"
  $Pnpm = Resolve-Executable -Candidate $Pnpm -Name "pnpm"
  if (-not [string]::IsNullOrWhiteSpace($NodeBin)) {
    if (-not (Test-Path -LiteralPath (Join-Path $NodeBin "node.exe"))) {
      Fail "NODE_BIN 中找不到 node.exe：$NodeBin"
    }
  } else {
    $NodeCommand = Get-Command node -ErrorAction SilentlyContinue
    if ($null -eq $NodeCommand) {
      Fail "找不到 Node.js。请安装 Node.js，或设置 NODE_BIN 指向 node.exe 所在目录。"
    }
    $NodeBin = Split-Path -Parent $NodeCommand.Source
  }

  & $LrPython -c "import fastapi, sqlalchemy, langgraph, psycopg, uvicorn"
  if ($LASTEXITCODE -ne 0) {
    Fail "LR 环境缺少后端依赖。请先在 LR 环境安装 pyproject.toml 中的运行依赖。"
  }

  $WebNodeModules = Join-Path $Root "apps\web\node_modules"
  if (-not (Test-Path -LiteralPath $WebNodeModules)) {
    Say-Step "未找到前端依赖，正在执行 pnpm install"
    & $Pnpm --dir (Join-Path $Root "apps\web") install
    if ($LASTEXITCODE -ne 0) {
      Fail "pnpm install 执行失败"
    }
  }
  $WebRoot = Join-Path $Root "apps\web"
  Test-FrontendToolchain -PnpmExe $Pnpm -NodeDirectory $NodeBin -WebRoot $WebRoot

  if (Test-PortInUse -Port $ApiPort) {
    Fail "后端端口 $ApiPort 已被占用，请先关闭占用该端口的进程。"
  }
  if (Test-PortInUse -Port $WebPort) {
    Fail "前端端口 $WebPort 已被占用，请先关闭占用该端口的进程。"
  }

  $PythonPaths = @(
    Join-Path $Root "apps\api"
    Join-Path $Root "apps\arthra-gateway\src"
    Join-Path $Root "apps\arthra-orchestrator\src"
    Join-Path $Root "apps\arthra-scheduler\src"
    Join-Path $Root "agents\main-agent\src"
    Join-Path $Root "agents\power-agent\src"
    Join-Path $Root "agents\compressor-agent\src"
    Join-Path $Root "packages\core\src"
    Join-Path $Root "packages\rag\src"
    Join-Path $Root "packages\memory\src"
    Join-Path $Root "packages\tools\src"
    Join-Path $Root "packages\mcp-client\src"
    Join-Path $Root "packages\evaluation\src"
    Join-Path $Root "packages\observability\src"
    Join-Path $Root "mcp-servers\energy-data\src"
  )
  $PythonPath = $PythonPaths -join ";"
  $DbUrlPath = $DbFile -replace "\\", "/"
  $DatabaseUrl = "sqlite:///$DbUrlPath"

  Say-Step "初始化本地调试数据库：$DbFile"
  $env:DATABASE_URL = $DatabaseUrl
  $env:LANGGRAPH_DATABASE_URL = ""
  $env:INDUSTRIAL_DATA_PROVIDER = $IndustrialDataProvider
  $env:THINGSBOARD_URL = $ThingsBoardUrl
  $env:THINGSBOARD_USERNAME = $ThingsBoardUsername
  $env:THINGSBOARD_PASSWORD = $ThingsBoardPassword
  $env:DAILY_SUMMARY_ENABLED = "false"
  $env:CORS_ORIGINS = $CorsOrigins
  $env:NO_PROXY = $NoProxy
  $env:no_proxy = $NoProxy
  $env:PYTHONPATH = $PythonPath
  & $LrPython -c "from arthra.db import Base, engine; import arthra.models; Base.metadata.create_all(engine)"
  if ($LASTEXITCODE -ne 0) {
    Fail "本地调试数据库初始化失败。"
  }

  Say-Step "启动后端 API：http://${ApiHost}:$ApiPort"
  $script:ApiJob = Start-Job -Name "arthra-api-lr" -ArgumentList $LrPython, $ApiHost, $ApiPort, $DatabaseUrl, $CorsOrigins, $NoProxy, $PythonPath, $ApiLog, $IndustrialDataProvider, $ThingsBoardUrl, $ThingsBoardUsername, $ThingsBoardPassword -ScriptBlock {
    param($Python, $HostName, $Port, $DbUrl, $Cors, $NoProxyValue, $PyPath, $LogFile, $DataProvider, $TbUrl, $TbUsername, $TbPassword)
    $env:DATABASE_URL = $DbUrl
    $env:LANGGRAPH_DATABASE_URL = ""
    $env:INDUSTRIAL_DATA_PROVIDER = $DataProvider
    $env:THINGSBOARD_URL = $TbUrl
    $env:THINGSBOARD_USERNAME = $TbUsername
    $env:THINGSBOARD_PASSWORD = $TbPassword
    $env:DAILY_SUMMARY_ENABLED = "false"
    $env:SUPERVISOR_SEMANTIC_ROUTING_ENABLED = "false"
    $env:COMPRESSOR_EXPERT_LLM_ENABLED = "false"
    $env:POWER_EXPERT_LLM_ENABLED = "false"
    $env:CORS_ORIGINS = $Cors
    $env:NO_PROXY = $NoProxyValue
    $env:no_proxy = $NoProxyValue
    $env:PYTHONPATH = $PyPath
    & $Python -m uvicorn arthra.main:app --host $HostName --port $Port *> $LogFile
  }

  Wait-ForUrl -Url "http://${ApiHost}:$ApiPort/api/v1/health" -Name "后端 API" -LogFile $ApiLog -Job $script:ApiJob

  Say-Step "启动前端控制台：http://${WebHost}:$WebPort"
  $ApiBaseUrl = "http://${BrowserApiHost}:$ApiPort/api/v1"
  $script:WebJob = Start-Job -Name "arthra-web-lr" -ArgumentList $Pnpm, $NodeBin, $WebRoot, $WebHost, $WebPort, $ApiBaseUrl, $WebLog -ScriptBlock {
    param($PnpmExe, $NodeDirectory, $AppDir, $HostName, $Port, $ApiUrl, $LogFile)
    if (-not [string]::IsNullOrWhiteSpace($NodeDirectory)) {
      $env:PATH = "$NodeDirectory;$env:PATH"
    }
    $env:VITE_API_BASE_URL = $ApiUrl
    & $PnpmExe --dir $AppDir exec vite --host $HostName --port $Port *> $LogFile
  }

  Wait-ForUrl -Url "http://${WebHost}:$WebPort/" -Name "前端控制台" -LogFile $WebLog -Job $script:WebJob

  Write-Host ""
  Write-Host "Arthra LR Windows 本地调试环境已启动。"
  Write-Host ""
  Write-Host "控制台： http://${WebHost}:$WebPort"
  Write-Host "API：    http://${ApiHost}:$ApiPort"
  Write-Host "账号：   admin@arthra.local"
  Write-Host "密码：   Arthra@123456"
  Write-Host ""
  Write-Host "当前工业数据源：$IndustrialDataProvider"
  Write-Host ""
  Write-Host "日志："
  Write-Host "- $ApiLog"
  Write-Host "- $WebLog"
  Write-Host ""
  Write-Host "关闭这个窗口或按 Ctrl+C 会停止本次启动的服务。"

  if ($OpenBrowser -eq "1") {
    try {
      Start-Process "http://${WebHost}:$WebPort" | Out-Null
    } catch {
      Write-Host "无法自动打开浏览器，请手动访问：http://${WebHost}:$WebPort"
    }
  }

  while ($true) {
    Start-Sleep -Seconds 2
    if ($script:ApiJob.State -ne "Running") {
      if (Test-Path -LiteralPath $ApiLog) { Get-Content -LiteralPath $ApiLog -Tail 80 }
      Fail "后端 API 已退出。"
    }
    if ($script:WebJob.State -ne "Running") {
      if (Test-Path -LiteralPath $WebLog) { Get-Content -LiteralPath $WebLog -Tail 80 }
      Fail "前端控制台已退出。"
    }
  }
} finally {
  Say-Step "正在停止本次启动的服务..."
  Stop-JobIfRunning -Job $script:ApiJob
  Stop-JobIfRunning -Job $script:WebJob
}
