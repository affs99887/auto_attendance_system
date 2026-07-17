#!/usr/bin/env bash
# 一键构建 macOS 安装包（dmg + zip），产物落在 <项目根>/release/。
#
# 流程：
#   1. 关掉本项目正在跑的客户端/后端/mihomo（gui/desktop/scripts/kill-running-client.ps1
#      的 mac 等价物；安全规则相同——只按"命令行里带本项目绝对路径"匹配，
#      绝不误伤用户自己跑的其它 Electron / python / mihomo）
#   2. 前端 npm run build（tsc + vite）
#   3. electron-builder --mac（按当前机器架构出包，可传 --x64 / --arm64 覆盖）
#
# 签名（默认不签）：
#   AAS_MAC_CODESIGN_IDENTITY="Developer ID Application: xxx" ./scripts/build-mac.sh
#   设了该环境变量 → 经 CSC_NAME 交给 electron-builder 用钥匙串里的这张证书签名；
#   没设 → 完全跳过签名（arm64 上 electron-builder 自动补 ad-hoc 签名，本机可运行）。
#
# 前置条件：
#   - 只能在 macOS 上跑（dmg 目标依赖系统的 hdiutil）
#   - gui/desktop 已 npm install（有 node_modules）
#   - 建议先跑 ./scripts/fetch-mihomo.sh 把 mac 版 mihomo 放进 bin/
#     （没有也能出包，只是安装包不内置网络加速内核，用户要在界面里点"下载内核"）
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(dirname "$SCRIPT_DIR")
DESKTOP_DIR="$ROOT_DIR/gui/desktop"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "错误：本脚本只能在 macOS 上运行（dmg 打包依赖 hdiutil）" >&2
  exit 1
fi

# ---- 架构：默认当前机器，可用第一个参数 --x64 / --arm64 覆盖 ----
case "$(uname -m)" in
  arm64)  ARCH_FLAG="--arm64" ;;
  x86_64) ARCH_FLAG="--x64" ;;
  *) echo "错误：不支持的 CPU 架构 $(uname -m)" >&2; exit 1 ;;
esac
if [ "${1:-}" = "--x64" ] || [ "${1:-}" = "--arm64" ]; then
  ARCH_FLAG="$1"
fi

# ---- 1) 关掉本项目正在跑的进程（全部按项目内绝对路径匹配，找不到就跳过）----
echo "[build-mac] 清理本项目正在运行的进程..."
kill_by_pattern() {
  # pkill -f 按整条命令行匹配；模式里带 $ROOT_DIR 绝对路径，保证只命中本项目的进程
  if pkill -f "$1" 2>/dev/null; then
    echo "[build-mac] 已结束: $2"
    KILLED=1
  fi
}
KILLED=0
kill_by_pattern "$ROOT_DIR/release/mac.*AutoAttendance"           "打包版客户端（release/mac*/AutoAttendance.app）"
kill_by_pattern "$ROOT_DIR/main.py --gui"                         "开发态后端 python（main.py --gui）"
kill_by_pattern "$DESKTOP_DIR/node_modules/electron"              "开发态 electron"
kill_by_pattern "$ROOT_DIR/bin/mihomo"                            "孤儿 mihomo（项目 bin/ 下的内核）"
if [ "$KILLED" -eq 1 ]; then
  sleep 0.5   # 给系统一点时间释放文件句柄
else
  echo "[build-mac] 没有需要清理的进程"
fi

# ---- 2) 构建前检查 ----
if [ ! -d "$DESKTOP_DIR/node_modules" ]; then
  echo "错误：$DESKTOP_DIR/node_modules 不存在，请先在 gui/desktop 下执行 npm install" >&2
  exit 1
fi
if [ ! -f "$ROOT_DIR/bin/mihomo" ]; then
  echo "[build-mac] 警告：bin/mihomo 不存在，安装包将不内置网络加速内核。" >&2
  echo "[build-mac]       建议先执行 ./scripts/fetch-mihomo.sh（GitHub 受阻可加 --mirror 前缀）" >&2
fi
if [ -f "$ROOT_DIR/bin/mihomo.exe" ]; then
  echo "[build-mac] 警告：bin/mihomo.exe（Windows 内核）也会被打进 mac 包，白占约 30MB，建议先移走" >&2
fi

# ---- 3) 签名开关（缺省不签名，见文件头说明）----
if [ -n "${AAS_MAC_CODESIGN_IDENTITY:-}" ]; then
  export CSC_NAME="$AAS_MAC_CODESIGN_IDENTITY"
  echo "[build-mac] 使用签名身份: $AAS_MAC_CODESIGN_IDENTITY"
else
  export CSC_IDENTITY_AUTO_DISCOVERY=false
  echo "[build-mac] 未设置 AAS_MAC_CODESIGN_IDENTITY，跳过签名"
fi

# ---- 4) 前端构建 + electron-builder ----
cd "$DESKTOP_DIR"
echo "[build-mac] 前端构建（tsc + vite）..."
npm run build
echo "[build-mac] electron-builder --mac $ARCH_FLAG ..."
npx electron-builder --mac "$ARCH_FLAG"

echo ""
echo "[build-mac] 完成。产物在 $ROOT_DIR/release/："
ls -l "$ROOT_DIR/release" | grep -Ei '\.(dmg|zip)$' || true
