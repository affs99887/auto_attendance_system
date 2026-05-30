<#
.SYNOPSIS
    下载 mihomo（Clash.Meta）内核与 geo 数据到 项目根/bin/，供内置网络加速使用。

.DESCRIPTION
    内置网络加速的核心是 mihomo 子进程。由于目标用户在中国、运行时可能没有任何代理，
    无法在运行时从 GitHub 下载，因此必须在【构建/打包前】把内核随安装包打包。
    本脚本在开发/构建机上运行一次，把 mihomo.exe（及可选 geo 数据库）放入 bin/。
    bin/ 已在 .gitignore 中（不入库），由本脚本或 CI 准备；electron-builder 会将其打进 resources/backend/bin/。

    若开发机访问 GitHub 受阻，用 -Mirror 指定一个 GitHub 加速前缀，例如：
        ./scripts/fetch-mihomo.ps1 -Mirror "https://mirror.ghproxy.com/"

.PARAMETER Version
    mihomo 版本 tag（默认 v1.19.25）。
.PARAMETER Mirror
    GitHub 下载加速前缀（拼在完整 URL 前面）。默认直连 GitHub。
.PARAMETER NoGeo
    跳过 geo 数据库下载（自生成的订阅规则只用域名/IP，不需要 geo；
    仅当“粘贴的完整 Clash 配置”里用到 GEOIP/GEOSITE 时才需要）。
.PARAMETER Compatible
    下载 compatible 版本（兼容较老 CPU，默认开启）。
#>
param(
    [string]$Version = "v1.19.25",
    [string]$Mirror = "",
    [switch]$NoGeo,
    [switch]$Compatible = $true
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repoRoot = Split-Path -Parent $PSScriptRoot
$binDir = Join-Path $repoRoot "bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

function Get-File($url, $outPath) {
    $full = if ($Mirror) { $Mirror.TrimEnd('/') + '/' + $url } else { $url }
    Write-Host "下载: $full"
    Invoke-WebRequest -Uri $full -OutFile $outPath -UseBasicParsing
}

# ---- mihomo 内核 ----
$variant = if ($Compatible) { "mihomo-windows-amd64-compatible" } else { "mihomo-windows-amd64" }
$zipName = "$variant-$Version.zip"
$zipUrl = "https://github.com/MetaCubeX/mihomo/releases/download/$Version/$zipName"
$tmpZip = Join-Path $env:TEMP $zipName
$tmpDir = Join-Path $env:TEMP "mihomo_extract_$([System.Guid]::NewGuid().ToString('N'))"

try {
    Get-File $zipUrl $tmpZip
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force
    $exe = Get-ChildItem -Path $tmpDir -Filter "mihomo*.exe" -Recurse | Select-Object -First 1
    if (-not $exe) { throw "解压后未找到 mihomo*.exe" }
    Copy-Item $exe.FullName (Join-Path $binDir "mihomo.exe") -Force
    Write-Host "✓ 已放置 bin/mihomo.exe ($Version)" -ForegroundColor Green
} finally {
    Remove-Item $tmpZip -ErrorAction SilentlyContinue
    Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ---- geo 数据（可选）----
if (-not $NoGeo) {
    $geoBase = "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest"
    foreach ($f in @("geoip.metadb", "geosite.dat")) {
        try {
            Get-File "$geoBase/$f" (Join-Path $binDir $f)
            Write-Host "✓ 已放置 bin/$f" -ForegroundColor Green
        } catch {
            Write-Warning "geo 文件 $f 下载失败（订阅模式不依赖 geo，可忽略）：$($_.Exception.Message)"
        }
    }
}

Write-Host ""
Write-Host "完成。bin/ 内容：" -ForegroundColor Cyan
Get-ChildItem $binDir | Format-Table Name, Length -AutoSize
