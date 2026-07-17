// 微信转发页 —— 把 macOS 微信通知按「时段 + 中国节假日」规则转发到 iPhone 的 Bark App。
// 区块：运行状态 / 应用行为 / Bark 与微信配置 / 转发时间 / 通知来源 / 运行日志。
// 监听本身只在 macOS 生效；Windows 上可正常改配置、测 Bark 推送、看时段判定。
// 状态与日志放在 store/wechatBark.ts（WS 推送为主，本页 3 秒轮询兜底）；
// 配置表单只有本页用，留在组件本地 state。
import * as React from 'react';
import { api, ApiError, type WechatBarkApp, type WechatBarkConfig } from '../lib/api';
import { useWechatBarkStore } from '../store/wechatBark';
import { useToastStore } from '../store/toast';
import { Icon } from '../lib/icons';

// ---------------------------------------------------------------------------
// 表单状态：textarea/number 输入天然产出字符串，所以多行列表字段在表单里存成
// 「一行一条」的字符串、数字字段存成字符串，保存时再统一转回 WechatBarkConfig。
// ---------------------------------------------------------------------------
interface FormState {
  bark_server: string;
  bark_device_key: string;
  bark_group: string;
  bark_sound: string;
  bark_level: string;
  bark_url: string;
  bark_icon: string;
  bark_use_post: boolean;

  wechat_bundle_ids: string;
  wechat_title_prefix: string;
  wechat_show_sender: boolean;
  wechat_sender_label: string;
  wechat_ignore_title: string;
  wechat_ignore_body: string;

  listener_poll: string;
  listener_send_existing: boolean;
  listener_state_file: string;
  listener_db_path: string;
  listener_max_body: string;

  desktop_auto_start: boolean;
  desktop_launch_login: boolean;

  schedule_enabled: boolean;
  schedule_timezone: string;
  schedule_start: string;
  schedule_end: string;
  schedule_weekends: boolean;
  schedule_holiday_urls: string;
  schedule_cache_dir: string;
  schedule_cache_ttl: string;
  schedule_allow_on_error: boolean;
}

const listToText = (items: string[]) => (items || []).join('\n');
const textToList = (text: string) => text.split('\n').map(s => s.trim()).filter(Boolean);

// 数字输入转回 number：空串/非数字回退到默认值（与后端默认一致），不把 0 误发出去
const toNum = (s: string, fallback: number) => {
  const n = Number(s);
  return s.trim() !== '' && Number.isFinite(n) ? n : fallback;
};

function configToForm(cfg: WechatBarkConfig): FormState {
  return {
    bark_server: cfg.bark.server,
    bark_device_key: cfg.bark.device_key,
    bark_group: cfg.bark.group,
    bark_sound: cfg.bark.sound,
    bark_level: cfg.bark.level,
    bark_url: cfg.bark.url,
    bark_icon: cfg.bark.icon,
    bark_use_post: cfg.bark.use_post,

    wechat_bundle_ids: listToText(cfg.wechat.bundle_ids),
    wechat_title_prefix: cfg.wechat.title_prefix,
    wechat_show_sender: cfg.wechat.show_sender_in_body,
    wechat_sender_label: cfg.wechat.sender_label,
    wechat_ignore_title: listToText(cfg.wechat.ignore_title_patterns),
    wechat_ignore_body: listToText(cfg.wechat.ignore_body_patterns),

    listener_poll: String(cfg.listener.poll_interval_seconds),
    listener_send_existing: cfg.listener.send_existing_on_start,
    listener_state_file: cfg.listener.state_file,
    listener_db_path: cfg.listener.db_path,
    listener_max_body: String(cfg.listener.max_body_chars),

    desktop_auto_start: cfg.desktop.auto_start_listener,
    desktop_launch_login: cfg.desktop.launch_at_login,

    schedule_enabled: cfg.schedule.enabled,
    schedule_timezone: cfg.schedule.timezone,
    schedule_start: cfg.schedule.start_time,
    schedule_end: cfg.schedule.end_time,
    schedule_weekends: cfg.schedule.weekends_are_holidays,
    schedule_holiday_urls: listToText(cfg.schedule.holiday_source_urls),
    schedule_cache_dir: cfg.schedule.holiday_cache_dir,
    schedule_cache_ttl: String(cfg.schedule.holiday_cache_ttl_hours),
    schedule_allow_on_error: cfg.schedule.allow_on_holiday_fetch_error,
  };
}

// base = 最近一次 GET 拿到的完整配置：后端保存时「未知字段原样保留」，
// 这里先铺 base 再覆盖表单字段，避免把用户手改配置文件加的额外键丢掉
function formToConfig(form: FormState, base: WechatBarkConfig | null): WechatBarkConfig {
  return {
    ...(base ?? {}),
    bark: {
      ...(base?.bark ?? {}),
      server: form.bark_server.trim(),
      device_key: form.bark_device_key.trim(),
      group: form.bark_group.trim(),
      sound: form.bark_sound.trim(),
      level: form.bark_level,
      url: form.bark_url.trim(),
      icon: form.bark_icon.trim(),
      use_post: form.bark_use_post,
    },
    wechat: {
      ...(base?.wechat ?? {}),
      bundle_ids: textToList(form.wechat_bundle_ids),
      title_prefix: form.wechat_title_prefix.trim(),
      show_sender_in_body: form.wechat_show_sender,
      sender_label: form.wechat_sender_label.trim(),
      ignore_title_patterns: textToList(form.wechat_ignore_title),
      ignore_body_patterns: textToList(form.wechat_ignore_body),
    },
    listener: {
      ...(base?.listener ?? {}),
      poll_interval_seconds: toNum(form.listener_poll, 2),
      send_existing_on_start: form.listener_send_existing,
      state_file: form.listener_state_file.trim(),
      db_path: form.listener_db_path.trim(),
      max_body_chars: toNum(form.listener_max_body, 800),
    },
    desktop: {
      ...(base?.desktop ?? {}),
      auto_start_listener: form.desktop_auto_start,
      launch_at_login: form.desktop_launch_login,
    },
    schedule: {
      ...(base?.schedule ?? {}),
      enabled: form.schedule_enabled,
      timezone: form.schedule_timezone.trim(),
      start_time: form.schedule_start,
      end_time: form.schedule_end,
      weekends_are_holidays: form.schedule_weekends,
      holiday_source_urls: textToList(form.schedule_holiday_urls),
      holiday_cache_dir: form.schedule_cache_dir.trim(),
      holiday_cache_ttl_hours: toNum(form.schedule_cache_ttl, 168),
      allow_on_holiday_fetch_error: form.schedule_allow_on_error,
    },
  };
}

// 错误转文案：保存配置校验失败时后端回 HTTP 400 {error:中文文案}，优先取它
function errText(e: unknown): string {
  if (e instanceof ApiError) {
    const p = e.payload as { error?: string } | null;
    if (p && typeof p.error === 'string' && p.error) return p.error;
    return `${e.status} ${e.message}`;
  }
  return (e as Error).message;
}

// ISO 时间串（带时区偏移）→ 「YYYY-MM-DD HH:MM:SS」。直接截字符串而不过 Date，
// 保证显示的就是后端时区（北京时间）下的钟点，不被本机时区二次换算
const fmtIso = (iso: string) => iso.replace('T', ' ').slice(0, 19);

// ---------------------------------------------------------------------------
// 小组件：表单字段 / 开关行
// ---------------------------------------------------------------------------
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <div className="field-label">{label}</div>
      {children}
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  );
}

function ToggleRow({
  title, desc, on, onToggle,
}: {
  title: string;
  desc?: string;
  on: boolean;
  onToggle: (v: boolean) => void;
}) {
  return (
    <div className="toggle-row">
      <div className="toggle-row-info">
        <div className="toggle-row-title">{title}</div>
        {desc && <div className="toggle-row-desc">{desc}</div>}
      </div>
      <div className={`toggle ${on ? 'on' : ''}`} onClick={() => onToggle(!on)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 页面
// ---------------------------------------------------------------------------
export function WechatBarkScreen() {
  const running = useWechatBarkStore(s => s.running);
  const stopping = useWechatBarkStore(s => s.stopping);
  const platformSupported = useWechatBarkStore(s => s.platformSupported);
  const configPath = useWechatBarkStore(s => s.configPath);
  const logs = useWechatBarkStore(s => s.logs);
  const schedule = useWechatBarkStore(s => s.schedule);
  const scheduleError = useWechatBarkStore(s => s.scheduleError);
  const hasStatus = useWechatBarkStore(s => s.hasStatus);
  const refreshStatus = useWechatBarkStore(s => s.refreshStatus);
  const refreshSchedule = useWechatBarkStore(s => s.refreshSchedule);

  const toast = (type: 'ok' | 'err', text: string) => useToastStore.getState().push(type, text);

  // 配置表单（本地 state）+ 最近一次 GET 的完整配置（保存时铺底，保留未知字段）
  const [form, setForm] = React.useState<FormState | null>(null);
  const [configError, setConfigError] = React.useState<string | null>(null);
  const baseCfgRef = React.useRef<WechatBarkConfig | null>(null);

  const [busy, setBusy] = React.useState(false);
  // 状态区四个按钮的操作结果消息条（保存/载入等表单操作走全局 toast）
  const [msg, setMsg] = React.useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  // 通知来源表
  const [apps, setApps] = React.useState<WechatBarkApp[]>([]);
  const [appsError, setAppsError] = React.useState<string | null>(null);
  const [appsLoading, setAppsLoading] = React.useState(false);
  const [appsTried, setAppsTried] = React.useState(false);

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm(f => (f ? { ...f, [key]: value } : f));

  const loadConfig = React.useCallback(async () => {
    setConfigError(null);
    try {
      const r = await api.getWechatBarkConfig();
      baseCfgRef.current = r.config;
      setForm(configToForm(r.config));
    } catch (e) {
      setConfigError(errText(e));
    }
  }, []);

  // 进页拉 config + status + schedule；status 3 秒轮询兜底（WS 为主）、schedule 60 秒刷新，
  // 定时器随切页卸载清掉，不在别的页面白跑
  React.useEffect(() => {
    void loadConfig();
    void refreshStatus();
    void refreshSchedule();
    const statusTimer = window.setInterval(() => { void refreshStatus(); }, 3_000);
    const scheduleTimer = window.setInterval(() => { void refreshSchedule(); }, 60_000);
    return () => {
      window.clearInterval(statusTimer);
      window.clearInterval(scheduleTimer);
    };
  }, [loadConfig, refreshStatus, refreshSchedule]);

  // 日志自动滚底：有新行就把滚动条推到最下面
  const logBoxRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const el = logBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  // ---------------------------------------------------------------- 状态区操作
  const doStart = async () => {
    setBusy(true);
    try {
      const r = await api.startWechatBark();
      setMsg(r.success
        ? { type: 'ok', text: r.message || '监听已启动' }
        : { type: 'err', text: r.error || '启动失败' });
      await refreshStatus();
    } catch (e) { setMsg({ type: 'err', text: errText(e) }); }
    finally { setBusy(false); }
  };

  const doStop = async () => {
    setBusy(true);
    try {
      const r = await api.stopWechatBark();
      setMsg(r.success
        ? { type: 'ok', text: r.message || '正在停止监听' }
        : { type: 'err', text: r.error || '停止失败' });
      await refreshStatus();
    } catch (e) { setMsg({ type: 'err', text: errText(e) }); }
    finally { setBusy(false); }
  };

  const doTest = async () => {
    setBusy(true);
    try {
      const r = await api.testWechatBark();
      setMsg(r.success
        ? { type: 'ok', text: r.message || 'Bark 测试通知已发送' }
        : { type: 'err', text: r.error || '测试失败' });
    } catch (e) { setMsg({ type: 'err', text: errText(e) }); }
    finally { setBusy(false); }
  };

  const doCheckSchedule = async () => {
    setBusy(true);
    try {
      await refreshSchedule();
      const { schedule: s, scheduleError: err } = useWechatBarkStore.getState();
      if (s && !err) {
        setMsg({
          type: s.allowed ? 'ok' : 'err',
          text: `当前${s.allowed ? '允许' : '阻止'}转发 — ${s.reason}（北京时间 ${fmtIso(s.now)}）`,
        });
      } else {
        setMsg({ type: 'err', text: err || '时段判定不可用' });
      }
    } finally { setBusy(false); }
  };

  // ---------------------------------------------------------------- 表单操作
  const save = async () => {
    if (!form) return;
    setBusy(true);
    try {
      const r = await api.saveWechatBarkConfig(formToConfig(form, baseCfgRef.current));
      if (r.success && r.config) {
        baseCfgRef.current = r.config;
        setForm(configToForm(r.config)); // 用后端清洗后的结果回填（补零/去空行等）
        toast('ok', '配置已保存；正在运行的监听会在下次启动时使用新配置');
        // 把「登录后自动启动」同步到系统登录项（桥内部有平台守卫，非 macOS 打包版是 no-op）
        void window.AAS_WECHAT_BARK?.syncLoginItem(r.config.desktop.launch_at_login).catch(() => { /* ignore */ });
        void refreshStatus();
        void refreshSchedule(); // 时段规则可能刚改过，立刻更新顶部判定
      } else {
        toast('err', r.error || '保存失败');
      }
    } catch (e) { toast('err', errText(e)); }
    finally { setBusy(false); }
  };

  const reload = async () => {
    setBusy(true);
    try {
      await loadConfig();
      toast('ok', '已重新载入配置文件');
    } finally { setBusy(false); }
  };

  const listApps = async () => {
    setAppsLoading(true);
    setAppsError(null);
    try {
      const r = await api.getWechatBarkApps();
      if (r.success && r.apps) setApps(r.apps);
      else { setApps([]); setAppsError(r.error || '获取通知来源失败'); }
    } catch (e) {
      setApps([]);
      setAppsError(errText(e));
    } finally {
      setAppsLoading(false);
      setAppsTried(true);
    }
  };

  // 点击来源行：用该 Bundle ID 替换（不是追加）输入框内容——与原独立应用交互一致
  const pickApp = (identifier: string) => {
    setField('wechat_bundle_ids', identifier);
    toast('ok', `已把 ${identifier} 填入微信 Bundle ID（替换原内容，记得保存）`);
  };

  // ---------------------------------------------------------------- 系统级操作（Electron 桥）
  const bridge = window.AAS_WECHAT_BARK;

  const openPrivacy = async () => {
    const r = await bridge?.openPrivacySettings();
    if (!r?.ok) toast('err', r?.reason || '当前平台无法打开该设置页');
  };

  const showConfigFile = async () => {
    const r = await bridge?.showConfig();
    if (r && !r.ok) toast('err', r.reason || '无法定位配置文件');
  };

  // ---------------------------------------------------------------- 渲染
  // 监听进程三态：停止中（已请求停止、线程还没退）优先展示
  const statePill = stopping
    ? { cls: 'pill-warning', label: '停止中' }
    : running
      ? { cls: 'pill-success', label: '运行中' }
      : { cls: 'pill-neutral', label: '已停止' };

  return (
    <div className="col gap-6">
      {/* Windows 等非 macOS 平台的说明横幅（拉到状态前不展示，避免闪一下误报） */}
      {hasStatus && !platformSupported && (
        <div
          style={{
            background: 'var(--accent-bg)',
            border: '1px solid var(--accent-border)',
            borderLeft: '3px solid var(--accent)',
            borderRadius: 'var(--radius)',
            padding: '10px 14px',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            color: 'var(--accent-fg)',
            fontSize: 12.5,
          }}
        >
          <Icon.Info size={14} style={{ flexShrink: 0 }} />
          <span>
            微信通知监听仅在 macOS 上生效（需读取系统通知中心数据库）；
            当前平台可先完成配置、测试 Bark 推送和查看时段判定。
          </span>
        </div>
      )}

      {/* 运行状态 */}
      <div className="card">
        <div className="card-header">
          <div className="col" style={{ gap: 2 }}>
            <div className="card-title">运行状态</div>
            <div className="card-sub">macOS 微信通知 → iPhone Bark · 按时段与中国节假日规则转发</div>
          </div>
          <span className={`pill ${statePill.cls}`}><span className="dot" />{statePill.label}</span>
        </div>
        <div className="card-body">
          <div className="row gap-6" style={{ flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <div className="col" style={{ gap: 6 }}>
              <div className="kicker">监听进程</div>
              <span className={`pill ${statePill.cls}`}><span className="dot" />{statePill.label}</span>
            </div>
            <div className="col" style={{ gap: 6, minWidth: 0, maxWidth: 420 }}>
              <div className="kicker">转发窗口</div>
              {schedule ? (
                <div className="row gap-2" style={{ alignItems: 'center' }}>
                  <span className={`pill ${schedule.allowed ? 'pill-success' : 'pill-warning'}`}>
                    <span className="dot" />{schedule.allowed ? '允许' : '阻止'}
                  </span>
                  <span
                    className="muted"
                    style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={schedule.reason}
                  >
                    {schedule.reason}
                  </span>
                </div>
              ) : (
                <span className="muted" style={{ fontSize: 11 }}>{scheduleError || '—'}</span>
              )}
            </div>
            <div className="col" style={{ gap: 6 }}>
              <div className="kicker">当前北京时间</div>
              <div className="mono" style={{ fontSize: 13 }}>{schedule ? fmtIso(schedule.now) : '—'}</div>
            </div>
            <div className="col" style={{ gap: 6 }}>
              <div className="kicker">转发时段</div>
              <div className="mono" style={{ fontSize: 13 }}>
                {schedule ? `${schedule.start_time} – ${schedule.end_time}` : '—'}
              </div>
            </div>
          </div>

          <div className="divider" />

          <div className="row gap-2" style={{ flexWrap: 'wrap' }}>
            <button
              className="btn btn-primary"
              disabled={busy || running || stopping || !platformSupported}
              title={!platformSupported ? '监听仅支持 macOS' : undefined}
              onClick={doStart}
            >
              <Icon.Play size={12} />启动监听
            </button>
            <button className="btn" disabled={busy || !running || stopping} onClick={doStop}>
              <Icon.Power size={12} />停止监听
            </button>
            <button className="btn" disabled={busy} onClick={doTest}>
              <Icon.Bell size={12} />测试 Bark
            </button>
            <button className="btn" disabled={busy} onClick={doCheckSchedule}>
              <Icon.Clock size={12} />检查时间
            </button>
          </div>

          {/* 操作结果消息条 */}
          {msg && (
            <div
              role="status"
              style={{
                marginTop: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '9px 12px',
                fontSize: 12,
                borderRadius: 'var(--radius)',
                background: `var(--${msg.type === 'ok' ? 'success' : 'danger'}-bg)`,
                border: `1px solid var(--${msg.type === 'ok' ? 'success' : 'danger'}-border)`,
                borderLeft: `3px solid var(--${msg.type === 'ok' ? 'success' : 'danger'})`,
                color: `var(--${msg.type === 'ok' ? 'success' : 'danger'})`,
              }}
            >
              {msg.type === 'ok' ? <Icon.Check size={13} /> : <Icon.AlertTriangle size={13} />}
              <span style={{ color: 'var(--text-primary)' }}>{msg.text}</span>
            </div>
          )}
        </div>
      </div>

      {form === null ? (
        <div className="card">
          <div className="card-body">
            {configError ? (
              <div className="row gap-2" style={{ alignItems: 'center' }}>
                <span style={{ color: 'var(--danger)', fontSize: 12 }}>配置载入失败：{configError}</span>
                <button className="btn btn-sm" onClick={() => void loadConfig()}>重试</button>
              </div>
            ) : (
              <div className="empty-state">正在载入配置…</div>
            )}
          </div>
        </div>
      ) : (
        <>
          {/* 应用行为 */}
          <div className="card">
            <div className="card-header">
              <div className="col" style={{ gap: 2 }}>
                <div className="card-title">应用行为</div>
                <div className="card-sub">开机与打开应用时的默认动作 · 改动需点下方「保存配置」生效</div>
              </div>
            </div>
            <div className="card-body">
              <ToggleRow
                title="打开应用后自动监听"
                desc="后端启动时自动开始监听（仅 macOS 会真正启动）"
                on={form.desktop_auto_start}
                onToggle={v => setField('desktop_auto_start', v)}
              />
              <ToggleRow
                title="登录后自动启动"
                desc="保存后同步到系统登录项（仅 macOS 打包版生效）"
                on={form.desktop_launch_login}
                onToggle={v => setField('desktop_launch_login', v)}
              />
              <div className="divider" />
              <div className="row gap-2" style={{ flexWrap: 'wrap', minWidth: 0 }}>
                <button
                  className="btn btn-sm"
                  disabled={!bridge || !platformSupported}
                  title={!platformSupported ? '仅 macOS 有此设置页' : undefined}
                  onClick={openPrivacy}
                >
                  <Icon.Lock size={12} />完全磁盘访问
                </button>
                <button className="btn btn-sm" disabled={!bridge} onClick={showConfigFile}>
                  <Icon.Logs size={12} />配置文件位置
                </button>
                <span
                  className="kicker mono"
                  style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  title={configPath || undefined}
                >
                  {configPath || '—'}
                </span>
              </div>
            </div>
          </div>

          {/* Bark 与微信配置 */}
          <div className="card">
            <div className="card-header">
              <div className="col" style={{ gap: 2 }}>
                <div className="card-title">Bark 与微信配置</div>
                <div className="card-sub">推送目标、消息内容与过滤规则</div>
              </div>
            </div>
            <div className="card-body">
              <div className="field-row">
                <Field label="Bark 服务地址">
                  <input
                    className="input mono"
                    value={form.bark_server}
                    placeholder="https://api.day.app"
                    onChange={e => setField('bark_server', e.target.value)}
                  />
                </Field>
                <Field label="Device Key" hint="Bark App 首页显示的设备密钥">
                  <input
                    className="input mono"
                    type="password"
                    value={form.bark_device_key}
                    placeholder="未填写无法推送"
                    onChange={e => setField('bark_device_key', e.target.value)}
                  />
                </Field>
              </div>
              <div className="field-row">
                <Field label="分组" hint="Bark 通知中心里的分组名">
                  <input
                    className="input"
                    value={form.bark_group}
                    onChange={e => setField('bark_group', e.target.value)}
                  />
                </Field>
                <Field label="标题前缀" hint="推送标题显示为「前缀 · 发送人」">
                  <input
                    className="input"
                    value={form.wechat_title_prefix}
                    onChange={e => setField('wechat_title_prefix', e.target.value)}
                  />
                </Field>
              </div>
              <div className="field-row">
                <Field label="提示音" hint="留空用 Bark 默认铃声">
                  <input
                    className="input mono"
                    value={form.bark_sound}
                    onChange={e => setField('bark_sound', e.target.value)}
                  />
                </Field>
                <Field label="推送级别">
                  <select
                    className="input"
                    value={form.bark_level}
                    onChange={e => setField('bark_level', e.target.value)}
                  >
                    <option value="active">active（默认，正常提醒）</option>
                    <option value="timeSensitive">timeSensitive（时效性，可穿透专注模式）</option>
                    <option value="passive">passive（静默，不亮屏）</option>
                    <option value="critical">critical（重要警告，可响铃）</option>
                  </select>
                </Field>
              </div>
              <div className="field-row">
                <Field label="点击跳转 URL" hint="留空则点通知不跳转">
                  <input
                    className="input mono"
                    value={form.bark_url}
                    onChange={e => setField('bark_url', e.target.value)}
                  />
                </Field>
                <Field label="图标 URL" hint="留空用 Bark 默认图标">
                  <input
                    className="input mono"
                    value={form.bark_icon}
                    onChange={e => setField('bark_icon', e.target.value)}
                  />
                </Field>
              </div>

              <Field label="微信 Bundle ID（一行一条）" hint="要转发哪些应用的通知；可点下方「通知来源」表格的行直接填入">
                <textarea
                  className="input mono"
                  style={{ minHeight: 64, resize: 'vertical' }}
                  value={form.wechat_bundle_ids}
                  placeholder="com.tencent.xinwechat"
                  onChange={e => setField('wechat_bundle_ids', e.target.value)}
                />
              </Field>
              <div className="field-row">
                <Field label="过滤发送人/标题正则（一行一条）" hint="通知标题（一般是发送人/群名）匹配任一条就不转发">
                  <textarea
                    className="input mono"
                    style={{ minHeight: 64, resize: 'vertical' }}
                    value={form.wechat_ignore_title}
                    onChange={e => setField('wechat_ignore_title', e.target.value)}
                  />
                </Field>
                <Field label="过滤消息内容正则（一行一条）" hint="消息正文匹配任一条就不转发">
                  <textarea
                    className="input mono"
                    style={{ minHeight: 64, resize: 'vertical' }}
                    value={form.wechat_ignore_body}
                    onChange={e => setField('wechat_ignore_body', e.target.value)}
                  />
                </Field>
              </div>
              <Field label="发送人标签" hint="开启下方「正文里重复显示发送人」时，正文前缀用的文字">
                <input
                  className="input"
                  value={form.wechat_sender_label}
                  onChange={e => setField('wechat_sender_label', e.target.value)}
                />
              </Field>

              <ToggleRow
                title="以 POST 方式调用 Bark"
                desc="长消息更稳；服务端不支持时会自动回退 GET"
                on={form.bark_use_post}
                onToggle={v => setField('bark_use_post', v)}
              />
              <ToggleRow
                title="正文里重复显示发送人"
                desc="在推送正文开头加「发送人标签: 」前缀（标题本就是发送人，通常不用开）"
                on={form.wechat_show_sender}
                onToggle={v => setField('wechat_show_sender', v)}
              />
              <ToggleRow
                title="首次启动时转发历史通知"
                desc="监听启动时把通知中心里已存在的微信通知补发一遍（可能一次涌出很多条）"
                on={form.listener_send_existing}
                onToggle={v => setField('listener_send_existing', v)}
              />

              <div className="divider" />
              <div className="kicker" style={{ marginBottom: 10 }}>监听参数</div>
              <div className="field-row">
                <Field label="轮询间隔（秒）" hint="多久查一次通知中心数据库，最小 0.5">
                  <input
                    className="input mono"
                    type="number"
                    min={0.5}
                    step={0.5}
                    value={form.listener_poll}
                    onChange={e => setField('listener_poll', e.target.value)}
                  />
                </Field>
                <Field label="正文最大字数" hint="超长消息截断后再推送">
                  <input
                    className="input mono"
                    type="number"
                    min={1}
                    step={50}
                    value={form.listener_max_body}
                    onChange={e => setField('listener_max_body', e.target.value)}
                  />
                </Field>
              </div>
              <div className="field-row">
                <Field label="状态文件" hint="记录已转发到哪条通知，避免重启后重复推送">
                  <input
                    className="input mono"
                    value={form.listener_state_file}
                    onChange={e => setField('listener_state_file', e.target.value)}
                  />
                </Field>
                <Field label="通知库路径" hint="留空自动探测 macOS 通知中心数据库位置">
                  <input
                    className="input mono"
                    value={form.listener_db_path}
                    onChange={e => setField('listener_db_path', e.target.value)}
                  />
                </Field>
              </div>
            </div>
          </div>

          {/* 转发时间 */}
          <div className="card">
            <div className="card-header">
              <div className="col" style={{ gap: 2 }}>
                <div className="card-title">转发时间</div>
                <div className="card-sub">只在指定时段、非节假日转发 · 节假日数据来自 holiday-cn</div>
              </div>
            </div>
            <div className="card-body">
              <ToggleRow
                title="开启限定时段监听"
                desc="关闭后任何时间都转发，下面的时段与节假日规则全部不生效"
                on={form.schedule_enabled}
                onToggle={v => setField('schedule_enabled', v)}
              />
              <ToggleRow
                title="周末按节假日处理"
                desc="周六周日视同节假日不转发（节假日数据里的调休补班日仍按工作日转发）"
                on={form.schedule_weekends}
                onToggle={v => setField('schedule_weekends', v)}
              />
              <ToggleRow
                title="节假日数据不可用时仍允许转发"
                desc="拉取节假日数据失败时放行转发；关闭则失败时一律阻止（默认关闭）"
                on={form.schedule_allow_on_error}
                onToggle={v => setField('schedule_allow_on_error', v)}
              />

              <div className="divider" />

              <div className="field-row">
                <Field label="开始时间">
                  <input
                    className="input mono"
                    type="time"
                    value={form.schedule_start}
                    onChange={e => setField('schedule_start', e.target.value)}
                  />
                </Field>
                <Field label="结束时间" hint="必须晚于开始时间">
                  <input
                    className="input mono"
                    type="time"
                    value={form.schedule_end}
                    onChange={e => setField('schedule_end', e.target.value)}
                  />
                </Field>
              </div>
              <div className="field-row">
                <Field label="时区" hint="IANA 时区名，节假日判定按它换算日期">
                  <input
                    className="input mono"
                    value={form.schedule_timezone}
                    placeholder="Asia/Shanghai"
                    onChange={e => setField('schedule_timezone', e.target.value)}
                  />
                </Field>
                <Field label="缓存有效期（小时）" hint="节假日数据本地缓存多久后重新下载">
                  <input
                    className="input mono"
                    type="number"
                    min={1}
                    value={form.schedule_cache_ttl}
                    onChange={e => setField('schedule_cache_ttl', e.target.value)}
                  />
                </Field>
              </div>
              <Field label="节假日数据源（一行一条 URL）" hint="{year} 会替换成年份；多条按顺序尝试">
                <textarea
                  className="input mono"
                  style={{ minHeight: 64, resize: 'vertical' }}
                  value={form.schedule_holiday_urls}
                  onChange={e => setField('schedule_holiday_urls', e.target.value)}
                />
              </Field>
              <Field label="缓存目录">
                <input
                  className="input mono"
                  value={form.schedule_cache_dir}
                  onChange={e => setField('schedule_cache_dir', e.target.value)}
                />
              </Field>

              <div className="divider" />
              <div className="row gap-2" style={{ flexWrap: 'wrap' }}>
                <button className="btn btn-primary" disabled={busy} onClick={save}>
                  <Icon.Check size={12} />保存配置
                </button>
                <button className="btn" disabled={busy} onClick={reload}>
                  <Icon.Refresh size={12} />重新载入
                </button>
                <button className="btn" disabled={appsLoading} onClick={listApps}>
                  <Icon.Search size={12} />{appsLoading ? '加载中…' : '列出通知来源'}
                </button>
              </div>
            </div>
          </div>

          {/* 通知来源 */}
          <div className="card">
            <div className="card-header">
              <div className="col" style={{ gap: 2 }}>
                <div className="card-title">通知来源{apps.length > 0 ? `（${apps.length}）` : ''}</div>
                <div className="card-sub">通知中心里出现过的应用 · 点击行把 Bundle ID 填入上方输入框（替换）</div>
              </div>
            </div>
            {appsError ? (
              <div className="card-body">
                <div
                  style={{
                    padding: '9px 12px',
                    fontSize: 12,
                    borderRadius: 'var(--radius)',
                    background: 'var(--danger-bg)',
                    border: '1px solid var(--danger-border)',
                    color: 'var(--danger)',
                  }}
                >
                  {appsError}
                </div>
              </div>
            ) : (
              <table className="table">
                <thead>
                  <tr><th>Bundle ID</th><th style={{ width: 100 }}>通知数</th></tr>
                </thead>
                <tbody>
                  {apps.length === 0 ? (
                    <tr>
                      <td colSpan={2} className="empty-state">
                        {appsTried
                          ? '通知中心里没有找到应用来源'
                          : '尚未加载 — 点上方「列出通知来源」（仅 macOS 且已授予完全磁盘访问时可用）'}
                      </td>
                    </tr>
                  ) : (
                    apps.map(a => (
                      <tr key={a.identifier} style={{ cursor: 'pointer' }} onClick={() => pickApp(a.identifier)}>
                        <td className="mono">{a.identifier}</td>
                        <td className="mono">{a.count}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {/* 监听运行日志 */}
      <div className="card">
        <div className="card-header">
          <div className="col" style={{ gap: 2 }}>
            <div className="card-title">监听运行日志</div>
            <div className="card-sub">最近 600 行 · WS 实时追加，自动滚到最新</div>
          </div>
          <span className="kicker mono">{logs.length} 行</span>
        </div>
        <div
          ref={logBoxRef}
          className="scroll-area"
          style={{ maxHeight: 320, overflowY: 'auto', background: 'var(--bg-inset)', padding: '6px 0' }}
        >
          {logs.length === 0 ? (
            <div className="empty-state">暂无日志 — 在 macOS 上启动监听后这里会实时滚动</div>
          ) : (
            logs.map((line, i) => (
              <div
                key={i}
                className="mono"
                style={{
                  fontSize: 11,
                  lineHeight: 1.7,
                  padding: '1px 14px',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  color: 'var(--text-secondary)',
                }}
              >
                {line}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
