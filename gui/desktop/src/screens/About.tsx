// 关于 & 命令 — 系统信息 + 模块 + Telegram 命令速查 + ASCII 数据流。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { COMMANDS } from '../lib/data';
import { api, ApiError } from '../lib/api';
import { useSystemStore } from '../store/system';
import { useServiceStore } from '../store/service';

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
  const snapshot = useSystemStore(s => s.snapshot);
  // 后端服务（main.py）运行/可控状态：驱动启动/重启/终止按钮互斥
  const running = useServiceStore(s => s.running);
  const available = useServiceStore(s => s.available);
  const [confirmStop, setConfirmStop] = React.useState(false);
  const [reconnecting, setReconnecting] = React.useState(false);
  const [toast, setToast] = React.useState<string | null>(null);

  const showToast = (text: string) => {
    setToast(text);
    window.setTimeout(() => setToast(null), 4000);
  };

  // 重启：优先 Electron 桥；无桥回退 REST systemRestart
  const handleRestart = async () => {
    if (window.AAS_SERVICE) {
      const r = await window.AAS_SERVICE.restart();
      showToast(r?.message ?? '已发送重启指令');
      return;
    }
    try {
      const r = await api.systemRestart();
      showToast(r.note ?? '已发出重启信号（由 Electron 处理）');
    } catch (e) {
      showToast(`请求失败: ${e instanceof ApiError ? e.status : (e as Error).message}`);
    }
  };

  // 启动服务（仅未运行时显示）
  const handleStart = async () => {
    const r = await window.AAS_SERVICE?.start();
    showToast(r?.message ?? '已发送启动指令');
  };

  // 重连 Telegram bot（不重启进程，本地防抖）
  const handleReconnect = async () => {
    if (reconnecting) return;
    setReconnecting(true);
    try {
      const r = await api.botReconnect();
      showToast(r.success ? (r.message ?? 'Bot 已重连') : (r.error ?? '重连失败'));
    } catch (e) {
      showToast(`重连失败: ${e instanceof ApiError ? e.status : (e as Error).message}`);
    } finally {
      setReconnecting(false);
    }
  };

  const heartbeatMs = snapshot?.heartbeat?.last
    ? new Date(snapshot.heartbeat.last).getTime()
    : null;
  const runMins = heartbeatMs ? Math.max(0, Math.round((Date.now() - heartbeatMs) / 60_000)) : null;

  return (
    <div className="col gap-6">
      {toast && (
        <div
          style={{
            position: 'fixed', top: 80, right: 24, zIndex: 200,
            background: 'var(--bg-card)',
            border: '1px solid var(--accent-border)',
            borderLeft: '3px solid var(--accent)',
            borderRadius: 'var(--radius)',
            padding: '10px 16px',
            boxShadow: 'var(--shadow-lg)',
            fontSize: 13,
            maxWidth: 360,
          }}
        >
          {toast}
        </div>
      )}
      {confirmStop && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1500,
          }}
          onClick={() => setConfirmStop(false)}
        >
          <div className="card" style={{ width: 400 }} onClick={e => e.stopPropagation()}>
            <div className="card-body">
              <div className="h2" style={{ marginBottom: 8 }}>终止后端服务？</div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 16 }}>
                终止后端服务？将停止 main.py（含 Telegram bot），可在此页重新启动。
              </div>
              <div className="row gap-2" style={{ justifyContent: 'flex-end' }}>
                <button className="btn" onClick={() => setConfirmStop(false)}>取消</button>
                <button
                  className="btn btn-danger"
                  onClick={async () => {
                    setConfirmStop(false);
                    const r = await window.AAS_SERVICE?.stop();
                    showToast(r?.message ?? '已发送终止指令');
                  }}
                >
                  确认终止
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      <div className="grid" style={{ gridTemplateColumns: '1fr 1.4fr', gap: 16 }}>
        <div className="card">
          <div className="card-body">
            <div className="row gap-4" style={{ alignItems: 'flex-start' }}>
              <div className="app-mark" style={{ width: 44, height: 44, borderRadius: 10, fontSize: 22 }}>
                A
              </div>
              <div>
                <div className="h1">自动打卡系统</div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  Auto Attendance System · v2.0
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
            {/* 服务状态 pill + 按钮组（启动/重启互斥）*/}
            <div className="row gap-2" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
              {!available ? (
                <span className="pill pill-neutral"><span className="dot" />浏览器模式</span>
              ) : running ? (
                <span className="pill pill-success"><span className="dot" />服务运行中</span>
              ) : (
                <span className="pill pill-danger"><span className="dot" />服务已停止</span>
              )}

              {!running ? (
                // 未运行：仅「启动服务」（无桥时禁用）
                <button className="btn" disabled={!available} onClick={handleStart}>
                  <Icon.Power size={12} />启动服务
                </button>
              ) : (
                // 运行中：重启 / 终止 / 重连 Bot
                <>
                  <button className="btn" onClick={handleRestart}>
                    <Icon.Refresh size={12} />重启服务
                  </button>
                  <button className="btn btn-danger" onClick={() => setConfirmStop(true)}>
                    <Icon.Power size={12} />终止服务
                  </button>
                  <button className="btn" disabled={reconnecting} onClick={handleReconnect}>
                    <Icon.Bot size={12} />{reconnecting ? '重连中…' : '重连 Bot'}
                  </button>
                </>
              )}

              {runMins !== null && (
                <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
                  上次心跳：{runMins} 分钟前
                </span>
              )}
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
