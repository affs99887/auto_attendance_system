#!/usr/bin/env bash
# 下载 mihomo（Clash.Meta）内核与 geo 数据到 项目根/bin/ —— macOS 版。
# 与 scripts/fetch-mihomo.ps1（Windows 版）等价：目标用户运行时可能没有任何代理，
# 无法在用户机器上现下内核，所以必须在【构建/打包前】把内核放进 bin/ 随安装包分发。
# bin/ 不入库（.gitignore），由本脚本在 mac 构建机上准备；electron-builder 会把它
# 打进 .app 的 resources/backend/bin/。
#
# 用法：
#   ./scripts/fetch-mihomo.sh                                    # 默认版本，直连 GitHub
#   ./scripts/fetch-mihomo.sh --mirror https://mirror.ghproxy.com/   # GitHub 加速前缀
#   ./scripts/fetch-mihomo.sh --version v1.19.25 --no-geo
#
# 参数：
#   --version <tag>   mihomo 版本 tag（默认 v1.19.25，与 ps1 版及 modules/proxy_manager.py
#                     的 _MIHOMO_VERSION 保持一致）
#   --mirror <前缀>   GitHub 下载加速前缀（拼在完整 URL 前面），默认直连
#   --no-geo          跳过 geo 数据库下载（自生成的订阅规则只用域名/IP，不需要 geo；
#                     仅当"粘贴的完整 Clash 配置"里用到 GEOIP/GEOSITE 时才需要）
set -euo pipefail

VERSION="v1.19.25"
MIRROR=""
NO_GEO=0

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --mirror)  MIRROR="$2";  shift 2 ;;
    --no-geo)  NO_GEO=1;     shift ;;
    *) echo "未知参数: $1（支持 --version/--mirror/--no-geo）" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")
BIN_DIR="$REPO_ROOT/bin"
mkdir -p "$BIN_DIR"

# 按当前机器判架构：Apple Silicon -> arm64，Intel -> amd64
case "$(uname -m)" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64)  ARCH="amd64" ;;
  *) echo "不支持的 CPU 架构: $(uname -m)" >&2; exit 1 ;;
esac

# 下载一个 URL 到指定路径；配了 --mirror 就把前缀拼在完整 URL 前面（与 ps1 版一致）
fetch() {
  url="$1"; out="$2"
  if [ -n "$MIRROR" ]; then
    url="${MIRROR%/}/$url"
  fi
  echo "下载: $url"
  curl -fL --retry 3 --connect-timeout 15 -o "$out" "$url"
}

# ---- mihomo 内核 ----
# macOS 的 release 资产没有 -compatible 变体（那是给老 CPU 的 Windows/Linux 包），
# 资产名与 modules/proxy_manager.py 的 _core_asset() 一致：mihomo-darwin-<arch>-<版本>.gz
ASSET="mihomo-darwin-$ARCH-$VERSION.gz"
CORE_URL="https://github.com/MetaCubeX/mihomo/releases/download/$VERSION/$ASSET"
TMP_GZ=$(mktemp "${TMPDIR:-/tmp}/mihomo-dl.XXXXXX")
trap 'rm -f "$TMP_GZ"' EXIT

fetch "$CORE_URL" "$TMP_GZ"
gunzip -c "$TMP_GZ" > "$BIN_DIR/mihomo"
chmod +x "$BIN_DIR/mihomo"
echo "已放置 bin/mihomo ($VERSION, darwin-$ARCH)"

# ---- geo 数据（可选；单个失败只告警，不中断）----
if [ "$NO_GEO" -eq 0 ]; then
  GEO_BASE="https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest"
  for f in geoip.metadb geosite.dat; do
    tmp="$BIN_DIR/$f.download"
    if fetch "$GEO_BASE/$f" "$tmp"; then
      mv -f "$tmp" "$BIN_DIR/$f"
      echo "已放置 bin/$f"
    else
      rm -f "$tmp"
      echo "警告: geo 文件 $f 下载失败（订阅模式不依赖 geo，可忽略）" >&2
    fi
  done
fi

echo ""
echo "完成。bin/ 内容："
ls -l "$BIN_DIR"
