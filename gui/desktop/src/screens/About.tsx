// 关于 & 命令 — 系统信息 + 模块 + Telegram 命令速查 + ASCII 数据流。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { COMMANDS } from '../lib/data';
import type { UpdateStatus } from '../lib/backend';
import { appConfirm } from '../lib/dialog';
import { useToastStore } from '../store/toast';

const DATA_FLOW = `  ┌─────────────────┐
  │  Telegram Bot   │ ◄── 用户命令 (/punch_in 等)
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐      ┌──────────────────┐
  │ AttendanceSystem│ ───► │  TaskManager     │ (schedule)
  └────────┬────────┘      └──────────────────┘
           │
     ┌─────┴─────┬─────────────┐
     ▼           ▼             ▼
 Selenium     PyAutoGUI    EmailService
  Login      + OCR Recog    (SMTP/QQ)
     │           │             │
     └─────┬─────┘             │
           ▼                   ▼
   ┌──────────────┐      ┌──────────────┐
   │ RecordManager│      │  Telegram    │
   │   JSON 持久化 │      │  通知 + 截图  │
   └──────────────┘      └──────────────┘`;

const MODULES = [
  { m: 'attendance_system.py', d: '核心调度类', lines: '3,551' },
  { m: 'telegram_bot.py', d: 'Telegram 远程控制', lines: '3,320' },
  { m: 'selenium_login.py', d: 'Selenium WebDriver', lines: '—' },
  { m: 'browser_controller.py', d: 'PyAutoGUI 备选自动化', lines: '—' },
  { m: 'image_recognizer.py', d: 'OCR 与模板匹配', lines: '—' },
  { m: 'email_service.py', d: 'SMTP 通知（带重试）', lines: '—' },
  { m: 'record_manager.py', d: '打卡记录 JSON 持久化', lines: '95' },
  { m: 'schedule_manager.py', d: '工作日检测 & 调度', lines: '—' },
  { m: 'task_manager.py', d: '任务调度封装', lines: '—' },
  { m: 'config.py', d: '配置中心 .env + dynamic', lines: '181' },
];

export function AboutScreen() {
  // 当前运行的代码版本（瘦壳 + OTA）：经 Electron preload 的 AAS_UPDATE 拉取主进程实际加载的代码包版本。
  // 纯浏览器 / 旧 preload 下 AAS_UPDATE 为 undefined，回退显示静态 'v3.0.1'。
  const [verLabel, setVerLabel] = React.useState('v3.0.1');
  const [shellVersion, setShellVersion] = React.useState('—');
  const [updateStatus, setUpdateStatus] = React.useState<UpdateStatus>({ status: 'idle' });
  const [availableVersion, setAvailableVersion] = React.useState<string | null>(null);
  const [updateBusy, setUpdateBusy] = React.useState(false);
  // 主进程 push 是权威实时状态。异步 getStatus/check/apply 只能在请求期间没有收到新 push 时回写，
  // 防止旧快照晚到后把 staged/error 等新状态覆盖回 idle/available。
  const pushedStatusRevision = React.useRef(0);
  React.useEffect(() => {
    let alive = true;
    const update = window.AAS_UPDATE;
    if (!update) return () => { alive = false; };
    update.getInfo().then(info => {
      if (!alive || !info) return;
      // ota/env 来源标注代码来源便于排障；builtin/dev 只显版本号
      const tag = info.source === 'ota' ? ' · 已更新' : info.source === 'env' ? ' · 外部' : '';
      setVerLabel(`v${info.codeVersion}${tag}`);
      setShellVersion(info.shellVersion);
    }).catch(() => { /* 拉取失败保留默认 */ });
    const acceptStatus = (s: UpdateStatus) => {
      if (!alive) return;
      setUpdateStatus(s);
      // availableVersion 只描述一次 check 的 idle 结果；任何实际更新状态都应取代它。
      if (s.status !== 'idle') setAvailableVersion(null);
    };
    const off = update.onStatus(s => {
      pushedStatusRevision.current += 1;
      acceptStatus(s);
    });
    const snapshotRevision = pushedStatusRevision.current;
    void update.getStatus().then(s => {
      if (pushedStatusRevision.current === snapshotRevision) acceptStatus(s);
    }).catch(() => { /* ignore */ });
    return () => { alive = false; off(); };
  }, []);

  const checkUpdate = async () => {
    const update = window.AAS_UPDATE;
    if (!update) return;
    setUpdateBusy(true);
    setAvailableVersion(null);
    setUpdateStatus({ status: 'checking' });
    const requestRevision = pushedStatusRevision.current;
    try {
      const result = await update.check();
      if (pushedStatusRevision.current !== requestRevision) return;
      if (result.status === 'error') {
        setUpdateStatus({ status: 'error', error: result.error });
      } else if (result.status === 'available') {
        setAvailableVersion(result.latest);
        setUpdateStatus({ status: 'idle' });
        useToastStore.getState().push('ok', `发现新版本 ${result.latest}`);
      } else if (result.status === 'shell-outdated') {
        setUpdateStatus(result);
        useToastStore.getState().push('err', `版本 ${result.version} 需要先升级客户端壳到 ${result.requiredShell}`);
      } else if (result.status === 'dependencies-outdated') {
        setUpdateStatus(result);
        useToastStore.getState().push('err', `版本 ${result.version} 修改了 Python 依赖，需先升级客户端并更新 Python 环境`);
      } else {
        setUpdateStatus({ status: 'up-to-date', currentVersion: result.currentVersion });
        useToastStore.getState().push('ok', '当前已经是最新版本');
      }
    } catch (e) {
      if (pushedStatusRevision.current !== requestRevision) return;
      const error = e instanceof Error ? e.message : String(e);
      setUpdateStatus({ status: 'error', error });
      useToastStore.getState().push('err', error);
    } finally {
      setUpdateBusy(false);
    }
  };

  const applyUpdate = async () => {
    const update = window.AAS_UPDATE;
    if (!update) return;
    setUpdateBusy(true);
    // 一旦开始应用更新，后续文案和操作都以 apply/onStatus 的真实状态为准。
    setAvailableVersion(null);
    const requestRevision = pushedStatusRevision.current;
    try {
      const result = await update.apply();
      if (pushedStatusRevision.current === requestRevision) setUpdateStatus(result);
      if (result.status === 'error') useToastStore.getState().push('err', result.error);
    } catch (e) {
      if (pushedStatusRevision.current !== requestRevision) return;
      const error = e instanceof Error ? e.message : String(e);
      setAvailableVersion(null);
      setUpdateStatus({ status: 'error', error });
      useToastStore.getState().push('err', error);
    } finally {
      setUpdateBusy(false);
    }
  };

  const relaunchForUpdate = async () => {
    const update = window.AAS_UPDATE;
    if (!update) return;
    if (!(await appConfirm('应用将立即重启并加载已验证的新版本，是否继续？', {
      title: '重启应用更新', confirmText: '立即重启', cancelText: '取消',
    }))) return;
    const result = await update.relaunch();
    if (!result.ok) useToastStore.getState().push('err', result.error || '重启失败');
  };

  const canApplyAvailableUpdate = updateStatus.status === 'idle' && availableVersion !== null;
  const updateText = updateStatus.status === 'checking' ? '正在从 GitHub 检查并验证更新…'
    : updateStatus.status === 'up-to-date' ? '当前已经是最新版本'
      : updateStatus.status === 'staged' ? `版本 ${updateStatus.version} 已下载并验签，等待重启`
        : updateStatus.status === 'shell-outdated' ? `版本 ${updateStatus.version} 需要客户端壳 ${updateStatus.requiredShell} 或更高版本`
          : updateStatus.status === 'dependencies-outdated' ? `版本 ${updateStatus.version} 修改了 Python 依赖，需先升级客户端并更新 Python 环境`
            : updateStatus.status === 'error' ? `更新失败：${updateStatus.error}`
              : canApplyAvailableUpdate ? `发现新版本 ${availableVersion}，尚未下载`
                : window.AAS_UPDATE ? '尚未手动检查；系统每 6 小时自动检查' : '当前运行环境不支持应用内更新';
  return (
    <div className="col gap-6">
      <div className="grid" style={{ gridTemplateColumns: '1fr 1.4fr', gap: 16 }}>
        <div className="card">
          <div className="card-body">
            <div className="row gap-4" style={{ alignItems: 'flex-start' }}>
              <div className="app-mark" style={{ width: 44, height: 44, borderRadius: 10, fontSize: 22 }}>
                A
              </div>
              <div>
                <div className="h1">AAS</div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  Auto Attendance System · {verLabel}
                </div>
                <div className="row gap-2" style={{ marginTop: 12 }}>
                  <span className="pill pill-info"><span className="dot" />Python 3.12</span>
                  <span className="pill pill-success"><span className="dot" />Selenium 4.x</span>
                </div>
              </div>
            </div>
            <div className="divider" />
            <div className="col gap-2" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              <div className="spread"><span>构建模块</span><span className="mono">10 个</span></div>
              <div className="spread"><span>累计代码行</span><span className="mono">~8,000</span></div>
              <div className="spread"><span>启动时间</span><span className="mono">2026-05-19 08:00:00</span></div>
              <div className="spread"><span>已运行</span><span className="mono">45m 12s</span></div>
              <div className="spread"><span>看门狗重启</span><span className="mono">0 次</span></div>
            </div>
            <div className="divider" />
            <div className="col gap-2" style={{ fontSize: 12 }}>
              <div className="spread">
                <span style={{ fontWeight: 600 }}>代码更新</span>
                <span className="mono muted">壳 v{shellVersion}</span>
              </div>
              <div
                className="muted"
                style={updateStatus.status === 'error' || updateStatus.status === 'shell-outdated' || updateStatus.status === 'dependencies-outdated' ? { color: 'var(--danger)' } : undefined}
              >
                {updateText}
              </div>
              <div className="row gap-2" style={{ flexWrap: 'wrap', marginTop: 4 }}>
                <button className="btn" disabled={!window.AAS_UPDATE || updateBusy || updateStatus.status === 'checking' || updateStatus.status === 'staged'} onClick={() => { void checkUpdate(); }}>
                  {updateBusy || updateStatus.status === 'checking' ? '处理中…' : '检查更新'}
                </button>
                {canApplyAvailableUpdate && (
                  <button className="btn btn-primary" disabled={updateBusy} onClick={() => { void applyUpdate(); }}>
                    下载并验证 v{availableVersion}
                  </button>
                )}
                {updateStatus.status === 'staged' && (
                  <button className="btn btn-primary" onClick={() => { void relaunchForUpdate(); }}>重启生效</button>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">系统组件</div>
              <div className="card-sub">modules/ 目录下的核心模块</div>
            </div>
          </div>
          <table className="table">
            <tbody>
              {MODULES.map(r => (
                <tr key={r.m}>
                  <td className="mono" style={{ fontSize: 11 }}>{r.m}</td>
                  <td>{r.d}</td>
                  <td className="mono muted" style={{ fontSize: 11, textAlign: 'right' }}>{r.lines}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Telegram 命令速查</div>
            <div className="card-sub">所有 GUI 操作均与 Telegram Bot 命令一一对应</div>
          </div>
          <span className="pill pill-info"><Icon.Bot size={11} />{COMMANDS.length} 条命令</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          <div className="grid grid-2" style={{ gap: 0 }}>
            {COMMANDS.map((c, i) => (
              <div
                key={c.cmd}
                style={{
                  padding: '12px 16px',
                  borderBottom: '1px solid var(--border-soft)',
                  borderRight: i % 2 === 0 ? '1px solid var(--border-soft)' : 'none',
                  display: 'flex',
                  gap: 12,
                }}
              >
                <span
                  className="mono"
                  style={{
                    background: 'var(--bg-inset)',
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 11,
                    fontWeight: 500,
                    color: 'var(--accent-fg)',
                    alignSelf: 'flex-start',
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                  }}
                >
                  {c.cmd}
                </span>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{c.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">数据流</div>
            <div className="card-sub">模块协作关系</div>
          </div>
        </div>
        <div className="card-body">
          <div
            style={{
              padding: 20,
              background: 'var(--bg-inset)',
              borderRadius: 6,
              fontFamily: 'var(--font-mono)',
              fontSize: 11.5,
              color: 'var(--text-secondary)',
              lineHeight: 1.8,
              whiteSpace: 'pre',
            }}
          >
            {DATA_FLOW}
          </div>
        </div>
      </div>
    </div>
  );
}
