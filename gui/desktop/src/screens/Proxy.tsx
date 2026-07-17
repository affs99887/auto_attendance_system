// 网络加速页 —— 内置 mihomo（仅代理本程序）的配置界面：
// 开关 / 多配置文件管理（仿 Clash「配置」页）/ 节点列表 / 选节点 / 测延迟 / 实时流量
import * as React from 'react';
import { api, ApiError, type ProxyProfile } from '../lib/api';
import { useProxyStore } from '../store/proxy';
import { useToastStore } from '../store/toast';
import { Icon } from '../lib/icons';
import { appConfirm } from '../lib/dialog';

function fmtRate(bytesPerSec: number): string {
  const u = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  let v = bytesPerSec;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

// 字节 → 友好容量（B/KB/MB/GB/TB），用于流量「已用 / 总量」
function fmtBytes(bytes: number): string {
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = Math.max(0, bytes);
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i <= 1 ? 0 : 2)} ${u[i]}`;
}

// epoch 秒 → 相对时间「刚刚 / X 分钟 / X 小时 / X 天前更新」
function fmtRelative(epochSec: number | null): string {
  if (!epochSec) return '从未更新';
  const diff = Date.now() / 1000 - epochSec;
  if (diff < 60) return '刚刚更新';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前更新`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前更新`;
  return `${Math.floor(diff / 86400)} 天前更新`;
}

// epoch 秒 → YY-MM-DD（付费过期日期）
function fmtDate(epochSec: number | null): string {
  if (!epochSec) return '—';
  const d = new Date(epochSec * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${String(d.getFullYear()).slice(2)}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
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
  const profiles = useProxyStore(s => s.profiles);
  const refreshConfig = useProxyStore(s => s.refreshConfig);
  const refreshNodes = useProxyStore(s => s.refreshNodes);
  const refreshTraffic = useProxyStore(s => s.refreshTraffic);
  const refreshProfiles = useProxyStore(s => s.refreshProfiles);

  const toast = (type: 'ok' | 'err', text: string) => useToastStore.getState().push(type, text);
  const errText = (e: unknown) =>
    e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;

  const [busy, setBusy] = React.useState(false);
  const [testing, setTesting] = React.useState<string | null>(null);
  // 「测全部延迟」运行态：禁用按钮防重入；ref 标志用于在卸载/再次点击时中断循环
  const [testingAll, setTestingAll] = React.useState(false);
  const testingAllRef = React.useRef(false);
  const unmountedRef = React.useRef(false);
  const [dragOver, setDragOver] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  // 导入订阅：内联 URL + 可选名称输入
  const [showSubForm, setShowSubForm] = React.useState(false);
  const [subUrl, setSubUrl] = React.useState('');
  const [subName, setSubName] = React.useState('');

  // 粘贴配置：内联 名称 + YAML 文本（复用 addLocalProfile，无新 API）
  const [showPasteForm, setShowPasteForm] = React.useState(false);
  const [pasteName, setPasteName] = React.useState('');
  const [pasteText, setPasteText] = React.useState('');

  // 编辑本地配置弹层：当前编辑的配置 id / 名称 / 内容
  const [editing, setEditing] = React.useState<{ id: string; name: string; content: string } | null>(null);
  const [editLoading, setEditLoading] = React.useState(false);

  React.useEffect(() => {
    // 重置卸载标志（兼容 StrictMode 卸载→重挂、以及正常切回本页）
    unmountedRef.current = false;
    void refreshConfig();
    void refreshNodes();
    void refreshProfiles();
    const id = window.setInterval(() => {
      void refreshTraffic();
      void refreshNodes();
    }, 3000);
    return () => {
      window.clearInterval(id);
      // 卸载（切页）后置位，testAll 循环据此中断，不再向后端发请求
      unmountedRef.current = true;
      testingAllRef.current = false;
    };
  }, [refreshConfig, refreshNodes, refreshTraffic, refreshProfiles]);

  // 增删改 / 切换后统一刷新：配置文件 + 状态 + 节点
  const refreshAll = async () => {
    await refreshProfiles();
    await refreshConfig();
    await refreshNodes();
  };

  const toggleEnabled = async (v: boolean) => {
    if (v && config && !config.binary_available) {
      toast('err', '请先下载 mihomo 内核');
      return;
    }
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

  // 导入订阅配置
  const addSubscription = async () => {
    if (!subUrl.trim()) { toast('err', '请填写订阅 URL'); return; }
    setBusy(true);
    try {
      const r = await api.addProxyProfile({
        type: 'subscription',
        url: subUrl.trim(),
        name: subName.trim() || undefined,
      });
      if (r.success) {
        toast('ok', `订阅已导入${r.profile?.node_count != null ? `，节点 ${r.profile.node_count} 个` : ''}`);
        setSubUrl(''); setSubName(''); setShowSubForm(false);
        await refreshAll();
      } else { toast('err', r.error || '导入失败'); }
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  // 导入本地配置：读取文件文本后以文件名作为配置名提交
  const addLocalProfile = async (name: string, content: string) => {
    setBusy(true);
    try {
      const r = await api.addProxyProfile({ type: 'local', name, content });
      if (r.success) {
        toast('ok', `本地配置已导入${r.profile?.node_count != null ? `，节点 ${r.profile.node_count} 个` : ''}`);
        await refreshAll();
      } else { toast('err', r.error || '导入失败'); }
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  // 读取本地 yaml 文本（拖拽 / input 降级共用）：校验扩展名与大小，文件名作配置名
  const readCfgFile = (file: File) => {
    if (!/\.(ya?ml)$/i.test(file.name)) { toast('err', '仅支持 .yaml / .yml 文件'); return; }
    if (file.size > 2 * 1024 * 1024) { toast('err', '配置文件过大（>2MB）'); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const name = file.name.replace(/\.(ya?ml)$/i, '');
      void addLocalProfile(name, String(reader.result || ''));
    };
    reader.onerror = () => toast('err', '读取文件失败');
    reader.readAsText(file);
  };

  // 选择本地配置文件：Electron 走系统对话框，纯浏览器回退隐藏 <input type=file>
  const pickConfigFile = async () => {
    const bridge = window.AAS_FILES;
    if (bridge) {
      try {
        const r = await bridge.pickConfigFile();
        if (r) { await addLocalProfile(r.name.replace(/\.(ya?ml)$/i, ''), r.content); }
      } catch (e) { toast('err', errText(e)); }
    } else {
      fileInputRef.current?.click();
    }
  };

  // 刷新某个订阅配置（重拉远端、更新流量/节点）
  const refreshProfile = async (p: ProxyProfile) => {
    setBusy(true);
    try {
      const r = await api.refreshProxyProfile(p.id);
      if (r.success) { toast('ok', `「${p.name}」已刷新`); await refreshAll(); }
      else toast('err', r.error || '刷新失败');
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  // 切换激活配置（点击非激活卡片）
  const selectProfile = async (p: ProxyProfile) => {
    if (p.active) return;
    setBusy(true);
    try {
      const r = await api.selectProxyProfile(p.id);
      if (r.success) { toast('ok', `已切换到「${p.name}」`); await refreshAll(); }
      else toast('err', r.error || '切换失败');
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  // 删除配置（二次确认）
  const deleteProfile = async (p: ProxyProfile) => {
    if (!(await appConfirm(`确定删除配置「${p.name}」？`, { danger: true, confirmText: '删除' }))) return;
    setBusy(true);
    try {
      const r = await api.deleteProxyProfile(p.id);
      if (r.success) { toast('ok', `「${p.name}」已删除`); await refreshAll(); }
      else toast('err', r.error || '删除失败');
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  // 打开本地配置编辑弹层：先拉原文
  const openEdit = async (p: ProxyProfile) => {
    setEditLoading(true);
    setEditing({ id: p.id, name: p.name, content: '' });
    try {
      const r = await api.getProxyProfileContent(p.id);
      if (r.error) { toast('err', r.error); setEditing(null); return; }
      setEditing({ id: p.id, name: p.name, content: r.content || '' });
    } catch (e) { toast('err', errText(e)); setEditing(null); }
    finally { setEditLoading(false); }
  };

  // 保存本地配置编辑
  const saveEdit = async () => {
    if (!editing) return;
    if (!editing.content.trim()) { toast('err', '配置内容不能为空'); return; }
    setBusy(true);
    try {
      const r = await api.updateProxyProfile(editing.id, {
        name: editing.name.trim() || undefined,
        content: editing.content,
      });
      if (r.success) { toast('ok', '配置已保存'); setEditing(null); await refreshAll(); }
      else toast('err', r.error || '保存失败');
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

  // silent=true 时不逐节点弹 toast（批量模式由 testAll 汇总），返回是否测得有效延迟
  const testDelay = async (name: string, silent = false): Promise<boolean> => {
    setTesting(name);
    try {
      const r = await api.testProxyDelay(name);
      if (!silent) {
        toast(r.delay != null ? 'ok' : 'err', r.delay != null ? `${name}: ${r.delay}ms` : `${name}: 超时`);
      }
      await refreshNodes();
      return r.delay != null;
    } catch (e) {
      if (!silent) toast('err', errText(e));
      return false;
    }
    finally { setTesting(null); }
  };

  const testAll = async () => {
    // 重入保护：已在测全部时直接忽略，避免两轮循环交叉执行、testing 状态互相覆盖
    if (testingAllRef.current) return;
    testingAllRef.current = true;
    setTestingAll(true);
    let ok = 0;
    let total = 0;
    try {
      for (const n of nodes) {
        // 卸载或被再次触发时中断循环，停止继续向后端发请求
        if (!testingAllRef.current || unmountedRef.current) break;
        total++;
        // eslint-disable-next-line no-await-in-loop
        if (await testDelay(n.name, true)) ok++;
      }
      // 批量模式汇总一条 toast，避免逐节点 toast 轰炸
      if (!unmountedRef.current) toast('ok', `测速完成：${ok}/${total} 个节点可用`);
    } finally {
      testingAllRef.current = false;
      if (!unmountedRef.current) setTestingAll(false);
    }
  };

  // 下载 mihomo 内核（运行时缺内核时自助下载）
  const downloadCore = async () => {
    setBusy(true);
    toast('ok', '正在下载内核，请稍候…（数十 MB，国内可能较慢）');
    try {
      const r = await api.fetchProxyCore();
      if (r.success) { toast('ok', r.message || '内核已就绪'); await refreshConfig(); }
      else toast('err', r.error || r.message || '下载失败');
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  const enabled = !!config?.enabled;

  return (
    <div className="col gap-6">
      {/* 状态卡 */}
      <div className="card">
        <div className="card-header">
          <div className="col">
            <div className="card-title">网络加速（仅本程序）</div>
            <div className="card-sub">内置 mihomo · 仅代理本程序的汇率、天气等联网功能，不影响系统其它网络</div>
          </div>
          <div
            className={`toggle ${enabled ? 'on' : ''}`}
            style={config && !config.binary_available ? { opacity: 0.5 } : undefined}
            onClick={() => !busy && toggleEnabled(!enabled)}
          />
        </div>
        <div className="card-body">
          {config && !config.binary_available && (
            <div className="row gap-2" style={{ marginBottom: 12, alignItems: 'center' }}>
              <span className="pill pill-warning">未找到 mihomo 内核（bin/mihomo.exe）</span>
              <button className="btn btn-sm btn-primary" disabled={busy} onClick={downloadCore}>下载内核</button>
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

      {/* 配置文件卡片区 */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">配置文件（{profiles.length}）</div>
          <div className="row gap-2">
            <button className="btn btn-sm" disabled={busy} onClick={() => setShowSubForm(v => !v)}>
              <Icon.Globe size={13} /> 导入订阅
            </button>
            <button className="btn btn-sm" disabled={busy} onClick={pickConfigFile}>
              <Icon.Download size={13} /> 导入本地配置
            </button>
            <button className="btn btn-sm" disabled={busy} onClick={() => setShowPasteForm(v => !v)}>
              <Icon.Plus size={13} /> 粘贴配置
            </button>
          </div>
        </div>
        <div className="card-body">
          {/* 导入订阅：内联 URL + 可选名称 */}
          {showSubForm && (
            <div className="col gap-2" style={{ marginBottom: 16, paddingBottom: 16, borderBottom: '1px solid var(--border)' }}>
              <div className="field-label">机场 Clash 订阅链接</div>
              <input
                className="input mono"
                value={subUrl}
                onChange={e => setSubUrl(e.target.value)}
                placeholder="https://.../subscribe?clash"
              />
              <div className="field-label">名称（可选）</div>
              <input
                className="input"
                value={subName}
                onChange={e => setSubName(e.target.value)}
                placeholder="留空则自动命名"
              />
              <div className="row gap-2">
                <button className="btn btn-primary btn-sm" disabled={busy} onClick={addSubscription}>导入</button>
                <button className="btn btn-sm" disabled={busy} onClick={() => { setShowSubForm(false); setSubUrl(''); setSubName(''); }}>取消</button>
              </div>
            </div>
          )}

          {/* 粘贴配置：内联 名称 + YAML 文本（复用 addLocalProfile）*/}
          {showPasteForm && (
            <div className="col gap-2" style={{ marginBottom: 16, paddingBottom: 16, borderBottom: '1px solid var(--border)' }}>
              <div className="field-label">名称（可选）</div>
              <input
                className="input"
                value={pasteName}
                onChange={e => setPasteName(e.target.value)}
                placeholder="留空则命名为「粘贴配置」"
              />
              <div className="field-label">完整 Clash 配置（YAML）</div>
              <textarea
                className="input mono"
                style={{ minHeight: 200, fontFamily: 'var(--font-mono)' }}
                value={pasteText}
                onChange={e => setPasteText(e.target.value)}
                placeholder={'proxies:\n  - name: ...'}
              />
              <div className="row gap-2">
                <button
                  className="btn btn-primary btn-sm"
                  disabled={busy}
                  onClick={async () => {
                    if (!pasteText.trim()) { toast('err', '配置内容不能为空'); return; }
                    await addLocalProfile(pasteName.trim() || '粘贴配置', pasteText);
                    setPasteName(''); setPasteText(''); setShowPasteForm(false);
                  }}
                >
                  导入
                </button>
                <button className="btn btn-sm" disabled={busy} onClick={() => { setShowPasteForm(false); setPasteName(''); setPasteText(''); }}>取消</button>
              </div>
            </div>
          )}

          {/* 隐藏文件 input（纯浏览器回退）+ 拖拽区 */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".yaml,.yml"
            style={{ display: 'none' }}
            onChange={e => {
              const f = e.target.files?.[0];
              if (f) readCfgFile(f);
              e.target.value = ''; // 允许重选同名文件
            }}
          />

          <div
            className="col gap-2"
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) readCfgFile(f);
            }}
            style={dragOver ? { outline: '2px dashed var(--accent)', outlineOffset: 4, borderRadius: 8 } : undefined}
          >
            {profiles.length === 0 ? (
              <div className="empty-state">暂无配置 — 点上方「导入订阅」或「导入本地配置」，也可把 .yaml 文件拖到此处</div>
            ) : (
              profiles.map(p => (
                <ProfileCard
                  key={p.id}
                  profile={p}
                  busy={busy}
                  onSelect={() => selectProfile(p)}
                  onRefresh={() => refreshProfile(p)}
                  onEdit={() => openEdit(p)}
                  onDelete={() => deleteProfile(p)}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {/* 节点列表 */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">节点（{nodes.length}）· 分组 {config?.group || '-'}</div>
          <button className="btn btn-sm" disabled={!running || nodes.length === 0 || testingAll} onClick={testAll}>{testingAll ? '测试中…' : '测全部延迟'}</button>
        </div>
        <table className="table">
          <thead>
            <tr><th style={{ width: 40 }} /><th>名称</th><th>类型</th><th>延迟</th><th style={{ width: 90 }} /></tr>
          </thead>
          <tbody>
            {nodes.length === 0 ? (
              <tr><td colSpan={5} className="empty-state">{running ? '暂无节点 — 先导入订阅或本地配置' : '加速未运行 — 启用并配置节点'}</td></tr>
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

      {/* 本地配置编辑弹层 */}
      {editing && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 50,
            background: 'rgba(0,0,0,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
          }}
          onClick={() => !busy && setEditing(null)}
        >
          <div
            className="card"
            style={{ width: 'min(760px, 100%)', maxHeight: '85vh', display: 'flex', flexDirection: 'column' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="card-header">
              <div className="card-title">编辑本地配置</div>
              <button className="btn-ico" onClick={() => !busy && setEditing(null)}><Icon.Close size={14} /></button>
            </div>
            <div className="card-body col gap-2" style={{ overflow: 'auto' }}>
              <div className="field-label">名称</div>
              <input
                className="input"
                value={editing.name}
                onChange={e => setEditing(s => s && { ...s, name: e.target.value })}
              />
              <div className="field-label">完整 Clash 配置（YAML）</div>
              <textarea
                className="input mono"
                style={{ minHeight: 280, fontFamily: 'var(--font-mono)' }}
                value={editing.content}
                disabled={editLoading}
                onChange={e => setEditing(s => s && { ...s, content: e.target.value })}
                placeholder={editLoading ? '加载中…' : 'proxies:\n  - name: ...'}
              />
              <div className="row gap-2">
                <button className="btn btn-primary" disabled={busy || editLoading} onClick={saveEdit}>保存并应用</button>
                <button className="btn" disabled={busy} onClick={() => setEditing(null)}>取消</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// 单张配置卡片：名称 / 来源 / 更新时间 / 流量（订阅）/ 过期 / 操作；激活态左侧绿色强调条
function ProfileCard({
  profile, busy, onSelect, onRefresh, onEdit, onDelete,
}: {
  profile: ProxyProfile;
  busy: boolean;
  onSelect: () => void;
  onRefresh: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { name, type, url, updated_at, traffic, active } = profile;
  const used = traffic ? traffic.upload + traffic.download : 0;
  const total = traffic?.total ?? 0;
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  // 过期：已过期或 7 天内临近标红
  const expire = traffic?.expire ?? null;
  const expireSoon = expire != null && expire - Date.now() / 1000 < 7 * 86400;

  return (
    <div
      onClick={() => !busy && !active && onSelect()}
      style={{
        position: 'relative',
        border: `1px solid ${active ? 'var(--success-border)' : 'var(--border)'}`,
        background: active ? 'var(--success-bg)' : 'var(--bg-inset)',
        borderRadius: 'var(--radius)',
        padding: '12px 14px 12px 16px',
        cursor: active || busy ? 'default' : 'pointer',
      }}
    >
      {/* 激活态左侧绿色强调条 */}
      {active && (
        <div style={{
          position: 'absolute', left: 0, top: 0, bottom: 0, width: 3,
          background: 'var(--success)', borderRadius: 'var(--radius) 0 0 var(--radius)',
        }} />
      )}

      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div className="col" style={{ gap: 4, minWidth: 0, flex: 1 }}>
          {/* 名称 + 激活标记 */}
          <div className="row gap-2" style={{ alignItems: 'center' }}>
            <span style={{ fontWeight: 600 }}>{name}</span>
            {active && <span className="pill pill-success"><span className="dot" />已激活</span>}
          </div>
          {/* 来源行 */}
          <div className="kicker mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {type === 'subscription' ? (url || '订阅') : '本地文件'}
          </div>
          {/* 更新时间 */}
          <div className="kicker">{fmtRelative(updated_at)}</div>
        </div>

        {/* 右上角操作 */}
        <div className="row gap-2" onClick={e => e.stopPropagation()}>
          {type === 'subscription' ? (
            <button className="btn btn-sm" disabled={busy} onClick={onRefresh} title="刷新订阅"><Icon.Refresh size={13} /></button>
          ) : (
            <button className="btn btn-sm" disabled={busy} onClick={onEdit} title="编辑"><Icon.Settings size={13} /></button>
          )}
          <button className="btn btn-sm btn-danger" disabled={busy} onClick={onDelete} title="删除"><Icon.Trash size={13} /></button>
        </div>
      </div>

      {/* 订阅：流量条 + 过期 */}
      {type === 'subscription' && traffic && (
        <div className="col gap-1" style={{ marginTop: 10 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="kicker">用 {fmtBytes(used)} {total > 0 ? `/ 总 ${fmtBytes(total)}` : ''}</span>
            <span className="kicker" style={expireSoon ? { color: 'var(--danger)' } : undefined}>
              付费过期 {fmtDate(expire)}
            </span>
          </div>
          {total > 0 && (
            <div style={{ height: 6, background: 'var(--bg-active)', borderRadius: 999, overflow: 'hidden' }}>
              <div style={{
                width: `${pct}%`, height: '100%',
                background: pct >= 90 ? 'var(--danger)' : 'var(--accent)',
              }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
