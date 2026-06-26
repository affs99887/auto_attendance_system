// 关于 & 命令 — 系统信息 + 模块 + Telegram 命令速查 + ASCII 数据流。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { COMMANDS } from '../lib/data';
import { ServiceControls } from '../components/ServiceControls';

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
            {/* 服务控制（启动/重启/终止/重连 + 心跳）— 统一走 ServiceControls bar 形态 */}
            <ServiceControls variant="bar" />
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
