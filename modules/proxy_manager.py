"""
内置网络加速管理（mihomo / Clash.Meta）

把一个 mihomo 核心当子进程拉起，监听本地专属端口（默认 7899），**只代理本程序**：
- 不设系统代理、不走 TUN/全局 —— 与系统 VPN/代理状态解耦。
- 本程序只连 127.0.0.1:<port>（回环永不经系统 VPN）。
- 由 Python 侧管理，GUI / 控制台 / watchdog 三种模式下都生效。

诚实边界：mihomo 自身连机场节点的出站仍走 OS 网络栈；若系统是全局 TUN VPN 会双跳。

二进制随安装包打包于项目根 bin/ （国内无代理时无法运行时下载）。
"""

import os
import json
import time
import shutil
import logging
import subprocess

import requests

from modules.config import config

logger = logging.getLogger(__name__)

# Telegram 走代理的规则（订阅模式自生成；仅域名/IP，不依赖 geo 数据库）
_TELEGRAM_RULES = [
    'DOMAIN-SUFFIX,telegram.org,{group}',
    'DOMAIN-SUFFIX,t.me,{group}',
    'DOMAIN-SUFFIX,telegram.me,{group}',
    'DOMAIN-SUFFIX,telegram.dog,{group}',
    'DOMAIN-SUFFIX,tdesktop.com,{group}',
    'IP-CIDR,149.154.160.0/20,{group},no-resolve',
    'IP-CIDR,91.108.4.0/22,{group},no-resolve',
    'IP-CIDR,91.108.8.0/22,{group},no-resolve',
    'IP-CIDR,91.108.12.0/22,{group},no-resolve',
    'IP-CIDR,91.108.16.0/22,{group},no-resolve',
    'IP-CIDR,91.108.56.0/22,{group},no-resolve',
    'IP-CIDR,95.161.64.0/20,{group},no-resolve',
    'MATCH,DIRECT',
]

_HEALTH_URL = 'https://www.gstatic.com/generate_204'


class ProxyManager:
    """mihomo 子进程 + external-controller API 客户端。"""

    def __init__(self, project_root=None):
        # 项目根：modules/.. → dev 与打包（resources/backend）一致
        self.project_root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.runtime_dir = os.path.join(self.project_root, 'proxy_runtime')
        self.proc = None
        self._last_traffic = None  # (ts, up_total, down_total)

    # ------------------------------------------------------------------ 路径
    def _bin_dir(self):
        return os.path.join(self.project_root, 'bin')

    def mihomo_path(self):
        name = 'mihomo.exe' if os.name == 'nt' else 'mihomo'
        return os.path.join(self._bin_dir(), name)

    def binary_available(self):
        return os.path.isfile(self.mihomo_path())

    def _config_path(self):
        return os.path.join(self.runtime_dir, 'config.yaml')

    def _source_config_path(self):
        # 用户"粘贴的完整 Clash 配置"原文
        return os.path.join(self.runtime_dir, 'source_config.yaml')

    def _pid_path(self):
        return os.path.join(self.runtime_dir, 'mihomo.pid')

    def _log_path(self):
        return os.path.join(self.runtime_dir, 'mihomo.log')

    # ------------------------------------------------------------------ 配置生成
    def _ensure_runtime(self):
        os.makedirs(self.runtime_dir, exist_ok=True)
        # 若打包附带 geo 数据库，复制到运行目录（mihomo 在 -d 目录查找），仅一次
        for fn in ('geoip.metadb', 'geoip.dat', 'geosite.dat', 'GeoIP.dat', 'GeoSite.dat', 'Country.mmdb'):
            src = os.path.join(self._bin_dir(), fn)
            dst = os.path.join(self.runtime_dir, fn)
            if os.path.isfile(src) and not os.path.isfile(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    logger.warning('复制 geo 数据库失败: %s', fn, exc_info=True)

    def _build_subscription_config(self, cfg):
        """订阅模式：手工拼 YAML（用 json.dumps 安全地引用字符串，无需 PyYAML）。"""
        group = cfg['group']
        sub_url = cfg.get('subscription_url') or ''
        lines = [
            f"mixed-port: {int(cfg['local_port'])}",
            "allow-lan: false",
            "bind-address: 127.0.0.1",
            "mode: rule",
            "log-level: warning",
            "ipv6: false",
            f"external-controller: 127.0.0.1:{int(cfg['api_port'])}",
            f"secret: {json.dumps(cfg['secret'])}",
            "proxy-providers:",
            "  AAS:",
            "    type: http",
            f"    url: {json.dumps(sub_url)}",
            "    interval: 86400",
            "    path: ./providers/AAS.yaml",
            "    health-check:",
            "      enable: true",
            f"      url: {json.dumps(_HEALTH_URL)}",
            "      interval: 300",
            "proxy-groups:",
            f"  - name: {json.dumps(group)}",
            "    type: select",
            "    use:",
            "      - AAS",
            "rules:",
        ]
        for r in _TELEGRAM_RULES:
            lines.append(f"  - {r.format(group=group)}")
        return "\n".join(lines) + "\n"

    def _build_config_from_text(self, cfg):
        """粘贴模式：解析用户 Clash 配置，强制覆盖关键字段；返回 (yaml_text, group_name)。"""
        try:
            import yaml  # 懒导入：仅粘贴模式需要 PyYAML
        except ImportError as e:
            raise RuntimeError("粘贴配置需要 PyYAML（pip install pyyaml），或改用订阅 URL 模式") from e

        if not os.path.isfile(self._source_config_path()):
            raise RuntimeError("尚未提供 Clash 配置文本")
        with open(self._source_config_path(), 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise RuntimeError("Clash 配置解析失败：根节点不是映射")

        # 强制覆盖本程序需要的控制字段
        data['mixed-port'] = int(cfg['local_port'])
        data['allow-lan'] = False
        data['bind-address'] = '127.0.0.1'
        data['external-controller'] = f"127.0.0.1:{int(cfg['api_port'])}"
        data['secret'] = cfg['secret']
        data.pop('socks-port', None)
        data.pop('port', None)
        data.pop('tun', None)  # 禁用 TUN（不接管系统）

        # 找一个可切换节点的 select 分组供 GUI 使用
        group = 'GLOBAL'
        groups = data.get('proxy-groups')
        if isinstance(groups, list):
            for g in groups:
                if isinstance(g, dict) and g.get('type') == 'select' and g.get('name'):
                    group = g['name']
                    break
            else:
                for g in groups:
                    if isinstance(g, dict) and g.get('name'):
                        group = g['name']
                        break
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False), group

    def _write_config(self):
        """根据当前配置生成 config.yaml，返回最新（可能更新了 group 的）配置 dict。"""
        self._ensure_runtime()
        cfg = config.get_proxy_config()
        if cfg.get('source') == 'config':
            text, group = self._build_config_from_text(cfg)
            if group != cfg.get('group'):
                cfg = config.set_proxy_config({'group': group})
        else:
            text = self._build_subscription_config(cfg)
        with open(self._config_path(), 'w', encoding='utf-8') as f:
            f.write(text)
        return cfg

    # ------------------------------------------------------------------ 进程
    def _kill_orphan(self):
        """按 pid 文件清理上一次遗留的 mihomo（watchdog 重启等场景）。"""
        pid_file = self._pid_path()
        if not os.path.isfile(pid_file):
            return
        try:
            with open(pid_file, 'r') as f:
                pid = int((f.read() or '').strip())
        except Exception:
            pid = 0
        if pid > 0:
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                                   capture_output=True, timeout=8)
                else:
                    os.kill(pid, 9)
            except Exception:
                pass
        try:
            os.remove(pid_file)
        except OSError:
            pass

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, ready_timeout=12.0):
        """生成配置 + 拉起 mihomo + 等 external-controller 就绪。返回 (ok, message)。

        同步方法（subprocess 即时 + time.sleep 轮询）；从 async 处调用建议 asyncio.to_thread。
        """
        if not config.get_proxy_enabled():
            return False, '内置加速未启用'
        if not self.binary_available():
            return False, f'未找到 mihomo 二进制：{self.mihomo_path()}（请确认 bin/ 已打包）'
        if self.is_running():
            return True, '已在运行'

        try:
            self._write_config()
        except Exception as e:
            logger.error('生成 mihomo 配置失败: %s', e, exc_info=True)
            return False, f'生成代理配置失败：{e}'

        self._kill_orphan()

        creationflags = 0
        if os.name == 'nt':
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            logf = open(self._log_path(), 'a', encoding='utf-8', errors='replace')
            self.proc = subprocess.Popen(
                [self.mihomo_path(), '-d', self.runtime_dir, '-f', self._config_path()],
                cwd=self.runtime_dir,
                stdout=logf, stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except Exception as e:
            logger.error('启动 mihomo 失败: %s', e, exc_info=True)
            return False, f'启动 mihomo 失败：{e}'

        try:
            with open(self._pid_path(), 'w') as f:
                f.write(str(self.proc.pid))
        except OSError:
            pass

        # 等 external-controller 就绪
        deadline = time.time() + ready_timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False, f'mihomo 进程提前退出（code={self.proc.returncode}），请查看 {self._log_path()}'
            try:
                r = requests.get(f'{self._api_base()}/version', headers=self._headers(), timeout=1.5)
                if r.status_code == 200:
                    logger.info('mihomo 已就绪：本地端口 %s', config.get_proxy_local_port())
                    return True, '已启动'
            except Exception:
                pass
            time.sleep(0.3)
        return False, 'mihomo 启动超时（external-controller 未响应），请查看日志'

    def stop(self):
        if self.proc is not None:
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(self.proc.pid), '/T', '/F'],
                                   capture_output=True, timeout=8)
                else:
                    self.proc.terminate()
            except Exception:
                logger.warning('停止 mihomo 失败', exc_info=True)
            self.proc = None
        try:
            os.remove(self._pid_path())
        except OSError:
            pass

    def reload(self):
        """重写配置并热重载（失败则重启）。"""
        try:
            self._write_config()
        except Exception as e:
            return False, f'生成配置失败：{e}'
        if not self.is_running():
            return self.start()
        try:
            r = requests.put(
                f'{self._api_base()}/configs',
                headers=self._headers(),
                params={'force': 'true'},
                json={'path': self._config_path()},
                timeout=5,
            )
            if r.status_code in (200, 204):
                return True, '已重载'
        except Exception:
            logger.warning('热重载失败，改为重启', exc_info=True)
        self.stop()
        return self.start()

    # ------------------------------------------------------------------ API 客户端
    def _api_base(self):
        return f'http://127.0.0.1:{config.get_proxy_api_port()}'

    def _headers(self):
        secret = config.get_proxy_config().get('secret') or ''
        return {'Authorization': f'Bearer {secret}'} if secret else {}

    def list_nodes(self):
        """返回控制分组内的节点列表 + 当前选中。"""
        cfg = config.get_proxy_config()
        group = cfg.get('group') or 'AAS-Proxy'
        r = requests.get(f'{self._api_base()}/proxies', headers=self._headers(), timeout=5)
        r.raise_for_status()
        proxies = (r.json() or {}).get('proxies', {})
        g = proxies.get(group) or {}
        names = g.get('all') or []
        selected = g.get('now')
        nodes = []
        for name in names:
            info = proxies.get(name) or {}
            history = info.get('history') or []
            delay = history[-1].get('delay') if history else None
            nodes.append({
                'name': name,
                'type': info.get('type', ''),
                'delay': delay if delay else None,
            })
        return {'group': group, 'selected': selected, 'nodes': nodes}

    def select_node(self, name):
        cfg = config.get_proxy_config()
        group = cfg.get('group') or 'AAS-Proxy'
        r = requests.put(
            f'{self._api_base()}/proxies/{group}',
            headers=self._headers(),
            json={'name': name},
            timeout=5,
        )
        if r.status_code in (200, 204):
            config.set_proxy_config({'selected_node': name})
            return True
        r.raise_for_status()
        return False

    def test_delay(self, name, url=_HEALTH_URL, timeout_ms=5000):
        r = requests.get(
            f'{self._api_base()}/proxies/{name}/delay',
            headers=self._headers(),
            params={'url': url, 'timeout': timeout_ms},
            timeout=(timeout_ms / 1000.0) + 3,
        )
        if r.status_code == 200:
            return (r.json() or {}).get('delay')
        return None

    def get_traffic(self):
        """用 /connections 的累计上下行计算速率（bytes/s）。"""
        try:
            r = requests.get(f'{self._api_base()}/connections', headers=self._headers(), timeout=3)
            r.raise_for_status()
            data = r.json() or {}
        except Exception:
            return {'up': 0, 'down': 0, 'up_total': 0, 'down_total': 0}
        up_total = int(data.get('uploadTotal', 0) or 0)
        down_total = int(data.get('downloadTotal', 0) or 0)
        now = time.time()
        up = down = 0
        if self._last_traffic:
            lt, lu, ld = self._last_traffic
            dt = max(0.001, now - lt)
            up = max(0, int((up_total - lu) / dt))
            down = max(0, int((down_total - ld) / dt))
        self._last_traffic = (now, up_total, down_total)
        return {'up': up, 'down': down, 'up_total': up_total, 'down_total': down_total}

    def status(self):
        """供 GUI 展示的状态快照（不含 secret 明文）。"""
        cfg = config.get_proxy_config()
        sub = cfg.get('subscription_url') or ''
        return {
            'enabled': bool(cfg.get('enabled')),
            'running': self.is_running(),
            'binary_available': self.binary_available(),
            'source': cfg.get('source', 'subscription'),
            'local_port': cfg.get('local_port'),
            'api_port': cfg.get('api_port'),
            'group': cfg.get('group'),
            'selected_node': cfg.get('selected_node'),
            'subscription_url': sub,
            'has_config_text': os.path.isfile(self._source_config_path()),
        }

    # ------------------------------------------------------------------ 配置写入（供 web_server 调用）
    def set_subscription(self, url):
        config.set_proxy_config({'source': 'subscription', 'subscription_url': url})

    def set_config_text(self, text):
        self._ensure_runtime()
        with open(self._source_config_path(), 'w', encoding='utf-8') as f:
            f.write(text or '')
        config.set_proxy_config({'source': 'config'})
