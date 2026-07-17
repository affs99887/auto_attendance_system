// 关于 — 系统信息 + 核心模块 + ASCII 数据流。

const DATA_FLOW = `  ┌──────────────────┐
  │   Electron 壳    │  窗口 / 托盘 / 后端进程管理
  └────────┬─────────┘
           │ spawn python main.py --gui
           ▼
  ┌──────────────────┐    REST /api/v1（Bearer 鉴权）
  │ Flask web_server │ ◄─────────────────────────────┐
  └────────┬─────────┘                               │
           │                                         │
     ┌─────┴─────┬─────────────┐                     │
     ▼           ▼             ▼                     │
  彩云天气     汇率服务      代理(mihomo)             │
  (weather)  (exchange)   仅代理本程序                │
     │           │             │                     │
     └─────┬─────┴─────────────┘                     │
           ▼                                         │
  ┌──────────────────┐  log:stream / proxy:status    │
  │  WebSocket 总线  │  exchange_rate / wechat_bark:* │
  └────────┬─────────┘                               │
           ▼                                         │
  ┌──────────────────┐                               │
  │   React 渲染层   │ ──────────────────────────────┘
  └──────────────────┘`;

const MODULES = [
  { m: 'main.py', d: '后端入口（--gui 模式）' },
  { m: 'web_server.py', d: 'Flask REST + WebSocket 推送（含彩云天气代调）' },
  { m: 'exchange_rate_service.py', d: 'CNY/JPY 汇率抓取与缓存' },
  { m: 'proxy_manager.py', d: '内置 mihomo 网络加速管理' },
  { m: 'wechat_bark_service.py', d: '微信通知转发 Bark（监听仅 macOS 生效）' },
  { m: 'calendar_info_service.py', d: '日历/假期信息服务' },
  { m: 'schedule_manager.py', d: '工作日检测（chinese_calendar）' },
  { m: 'services/log_service.py', d: '日志读取与错误分组' },
  { m: 'config.py', d: '配置中心 .env + dynamic_config' },
  { m: 'electron/main.cjs', d: 'Electron 主进程（窗口 / 托盘 / 服务控制）' },
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
                  桌面工作台 · v2.0
                </div>
                <div className="row gap-2" style={{ marginTop: 12 }}>
                  <span className="pill pill-info"><span className="dot" />Python 3.12</span>
                  <span className="pill pill-success"><span className="dot" />Electron + React</span>
                </div>
              </div>
            </div>
            <div className="divider" />
            <div className="col gap-2" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              <div className="spread"><span>桌面壳</span><span className="mono">Electron</span></div>
              <div className="spread"><span>渲染层</span><span className="mono">React + TS</span></div>
              <div className="spread"><span>后端</span><span className="mono">Flask（本机）</span></div>
              <div className="spread"><span>实时推送</span><span className="mono">WebSocket</span></div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">系统组件</div>
              <div className="card-sub">后端与桌面壳的核心模块</div>
            </div>
          </div>
          <table className="table">
            <tbody>
              {MODULES.map(r => (
                <tr key={r.m}>
                  <td className="mono" style={{ fontSize: 11 }}>{r.m}</td>
                  <td>{r.d}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
