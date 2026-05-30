// 网络加速页 —— 内置 mihomo（仅代理本程序）的配置界面：
// 开关 / 订阅或粘贴配置 / 节点列表 / 选节点 / 测延迟 / 实时流量
import * as React from 'react';
import { api, ApiError } from '../lib/api';
import { useProxyStore } from '../store/proxy';
import { useToastStore } from '../store/toast';

function fmtRate(bytesPerSec: number): string {
  const u = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  let v = bytesPerSec;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

function delayColor(d: number | null): string {
  if (d == null) return 'var(--text-muted)';
  if (d < 200) return 'var(--success)';
  if (d < 500) return 'var(--warning)';
  return 'var(--danger)';
}

export function ProxyScreen() {
  const config = useProxyStore(s => s.config);
  const nodes = useProxyStore(s => s.nodes);
  const selected = useProxyStore(s => s.selected);
  const running = useProxyStore(s => s.running);
  const traffic = useProxyStore(s => s.traffic);
  const refreshConfig = useProxyStore(s => s.refreshConfig);
  const refreshNodes = useProxyStore(s => s.refreshNodes);
  const refreshTraffic = useProxyStore(s => s.refreshTraffic);

  const toast = (type: 'ok' | 'err', text: string) => useToastStore.getState().push(type, text);
  const errText = (e: unknown) =>
    e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;

  const [tab, setTab] = React.useState<'subscription' | 'config'>('subscription');
  const [subUrl, setSubUrl] = React.useState('');
  const [cfgText, setCfgText] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [testing, setTesting] = React.useState<string | null>(null);

  React.useEffect(() => {
    void refreshConfig();
    void refreshNodes();
    const id = window.setInterval(() => {
      void refreshTraffic();
      void refreshNodes();
    }, 3000);
    return () => window.clearInterval(id);
  }, [refreshConfig, refreshNodes, refreshTraffic]);

  const cfgSubUrl = config?.subscription_url;
  const cfgSource = config?.source;
  React.useEffect(() => {
    if (cfgSubUrl !== undefined) setSubUrl(cfgSubUrl || '');
    if (cfgSource) setTab(cfgSource === 'config' ? 'config' : 'subscription');
  }, [cfgSubUrl, cfgSource]);

  const toggleEnabled = async (v: boolean) => {
    setBusy(true);
    try {
      const r = await api.setProxyConfig({ enabled: v });
      if (r.success) {
        toast('ok', r.note || (v ? '已启用' : '已停用'));
        await refreshConfig();
        await refreshNodes();
      } else {
        toast('err', r.error || '操作失败');
      }
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  const saveSubscription = async () => {
    if (!subUrl.trim()) { toast('err', '请填写订阅 URL'); return; }
    setBusy(true);
    try {
      const r = await api.setProxySubscription(subUrl.trim());
      if (r.success) {
        toast('ok', `订阅已保存${r.node_count != null ? `，节点 ${r.node_count} 个` : ''}`);
        await refreshConfig();
        await refreshNodes();
      } else { toast('err', r.error || '保存失败'); }
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  const saveConfigText = async () => {
    if (!cfgText.trim()) { toast('err', '请粘贴 Clash 配置'); return; }
    setBusy(true);
    try {
      const r = await api.setProxyConfigText(cfgText);
      if (r.success) {
        toast('ok', `配置已保存${r.node_count != null ? `，节点 ${r.node_count} 个` : ''}`);
        await refreshConfig();
        await refreshNodes();
      } else { toast('err', r.error || '保存失败'); }
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  const selectNode = async (name: string) => {
    try {
      const r = await api.selectProxyNode(name);
      if (r.success) { toast('ok', `已切换到 ${name}`); await refreshNodes(); }
      else toast('err', r.error || '切换失败');
    } catch (e) { toast('err', errText(e)); }
  };

  const testDelay = async (name: string) => {
    setTesting(name);
    try {
      const r = await api.testProxyDelay(name);
      toast(r.delay != null ? 'ok' : 'err', r.delay != null ? `${name}: ${r.delay}ms` : `${name}: 超时`);
      await refreshNodes();
    } catch (e) { toast('err', errText(e)); }
    finally { setTesting(null); }
  };

  const testAll = async () => {
    for (const n of nodes) {
      // eslint-disable-next-line no-await-in-loop
      await testDelay(n.name);
    }
  };

  const enabled = !!config?.enabled;

  return (
    <div className="col gap-6">
      {/* 状态卡 */}
      <div className="card">
        <div className="card-header">
          <div className="col">
            <div className="card-title">网络加速（仅本程序）</div>
            <div className="card-sub">内置 mihomo · 只代理本程序的 Telegram，不影响系统其它网络</div>
          </div>
          <div className={`toggle ${enabled ? 'on' : ''}`} onClick={() => !busy && toggleEnabled(!enabled)} />
        </div>
        <div className="card-body">
          {config && !config.binary_available && (
            <div className="pill pill-warning" style={{ marginBottom: 12 }}>
              未找到 mihomo 内核（bin/mihomo.exe）— 请重新安装或放置内核
            </div>
          )}
          <div className="row gap-6">
            <div>
              <div className="kicker">运行状态</div>
              <span className={`pill ${running ? 'pill-success' : 'pill-warning'}`}>{running ? '运行中' : '未运行'}</span>
            </div>
            <div>
              <div className="kicker">本地端口</div>
              <div className="mono">{config?.local_port ?? '-'}</div>
            </div>
            <div>
              <div className="kicker">当前节点</div>
              <div className="mono">{selected || '未选择'}</div>
            </div>
            <div>
              <div className="kicker">下行 / 上行</div>
              <div className="mono">↓ {fmtRate(traffic.down)} · ↑ {fmtRate(traffic.up)}</div>
            </div>
          </div>
        </div>
      </div>

      {/* 来源卡 */}
      <div className="card">
        <div className="card-header">
          <div className="row gap-2">
            <button className={`btn btn-sm ${tab === 'subscription' ? 'btn-primary' : ''}`} onClick={() => setTab('subscription')}>订阅 URL</button>
            <button className={`btn btn-sm ${tab === 'config' ? 'btn-primary' : ''}`} onClick={() => setTab('config')}>粘贴配置</button>
          </div>
        </div>
        <div className="card-body">
          {tab === 'subscription' ? (
            <div className="col gap-2">
              <div className="field-label">机场 Clash 订阅链接</div>
              <input
                className="input mono"
                value={subUrl}
                onChange={e => setSubUrl(e.target.value)}
                placeholder="https://.../subscribe?clash"
              />
              <div className="row gap-2">
                <button className="btn btn-primary" disabled={busy} onClick={saveSubscription}>保存并应用</button>
              </div>
            </div>
          ) : (
            <div className="col gap-2">
              <div className="field-label">完整 Clash 配置（YAML，需后端安装 PyYAML）</div>
              <textarea
                className="input mono"
                style={{ minHeight: 160, fontFamily: 'var(--font-mono)' }}
                value={cfgText}
                onChange={e => setCfgText(e.target.value)}
                placeholder={'proxies:\n  - name: ...\nproxy-groups:\n  - name: ...\n    type: select'}
              />
              <div className="row gap-2">
                <button className="btn btn-primary" disabled={busy} onClick={saveConfigText}>保存并应用</button>
                {config?.has_config_text && <span className="kicker">已存在配置</span>}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 节点列表 */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">节点（{nodes.length}）· 分组 {config?.group || '-'}</div>
          <button className="btn btn-sm" disabled={!running || nodes.length === 0} onClick={testAll}>测全部延迟</button>
        </div>
        <table className="table">
          <thead>
            <tr><th style={{ width: 40 }} /><th>名称</th><th>类型</th><th>延迟</th><th style={{ width: 90 }} /></tr>
          </thead>
          <tbody>
            {nodes.length === 0 ? (
              <tr><td colSpan={5} className="empty-state">{running ? '暂无节点 — 先导入订阅或粘贴配置' : '加速未运行 — 启用并配置节点'}</td></tr>
            ) : nodes.map(n => (
              <tr key={n.name}>
                <td><input type="radio" name="proxy-node" checked={n.name === selected} onChange={() => selectNode(n.name)} /></td>
                <td>{n.name}</td>
                <td className="mono">{n.type}</td>
                <td style={{ color: delayColor(n.delay) }}>{n.delay != null ? `${n.delay}ms` : '—'}</td>
                <td><button className="btn btn-sm" disabled={testing === n.name} onClick={() => testDelay(n.name)}>{testing === n.name ? '测试中' : '测延迟'}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="kicker" style={{ lineHeight: 1.7 }}>
        基于 mihomo（Clash.Meta，GPL-3.0）· 仅代理本程序，不改系统网络；系统即使开了 VPN 也不影响这里。
        若系统启用了全局 TUN VPN，内核连节点的流量会经其再出网（多一跳）。
      </div>
    </div>
  );
}
