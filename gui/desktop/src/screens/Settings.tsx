// 系统设置 — 接真实 API。
// - automation tab: setConfigMode (热生效)
// - email tab: testEmail
// - schedule/users/telegram/email/advanced: patchConfig (.env 写入)
// - general tab 主题切换走 window.AAS_THEME
import * as React from 'react';
import { useApp } from '../App';
import { Icon, type IconName } from '../lib/icons';
import { USERS } from '../lib/data';
import { api, ApiError } from '../lib/api';
import { useSystemStore } from '../store/system';

interface SectionProps {
  title: string;
  sub?: string;
  icon?: IconName;
  children: React.ReactNode;
}

function Section({ title, sub, icon, children }: SectionProps) {
  const Ico = icon ? Icon[icon] : null;
  return (
    <div className="card">
      <div className="card-header">
        <div className="row gap-2">
          {Ico && (
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 6,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'var(--accent-bg)',
                color: 'var(--accent-fg)',
              }}
            >
              <Ico size={14} />
            </div>
          )}
          <div>
            <div className="card-title">{title}</div>
            {sub && <div className="card-sub">{sub}</div>}
          </div>
        </div>
      </div>
      <div className="card-body">{children}</div>
    </div>
  );
}

function Toggle({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <div
      className={`toggle ${on ? 'on' : ''}${disabled ? ' disabled' : ''}`}
      style={disabled ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}
      onClick={() => { if (!disabled) onChange(!on); }}
    />
  );
}

type TabKey =
  | 'general'
  | 'users'
  | 'schedule'
  | 'automation'
  | 'weather'
  | 'telegram'
  | 'email'
  | 'advanced';

export function SettingsScreen() {
  const { seleniumOn, setSeleniumOn, headless, setHeadless } = useApp();
  const snapshot = useSystemStore(s => s.snapshot);
  const [tab, setTab] = React.useState<TabKey>('general');

  // Toast 状态
  const [toast, setToast] = React.useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const showToast = (type: 'ok' | 'err', text: string) => {
    setToast({ type, text });
    window.setTimeout(() => setToast(null), 4000);
  };

  // 敏感字段：后端 getConfigAll 返回掩码（••••），前端置空，留空=不修改，避免保存时覆盖真实值
  const SENSITIVE = React.useMemo(
    () => new Set([
      'LOGIN_PASSWORD', 'LOGIN_PASSWORD2', 'TELEGRAM_BOT_TOKEN', 'EMAIL_PASSWORD',
      'CAIYUN_WEATHER_APP_KEY', 'CAIYUN_WEATHER_APP_SECRET', 'CAIYUN_WEATHER_TOKEN',
    ]),
    [],
  );

  // 从 API 拉初始 .env
  const [envFields, setEnvFields] = React.useState<Record<string, string>>({});
  const [hasSecret, setHasSecret] = React.useState<Record<string, boolean>>({});
  const [envLoading, setEnvLoading] = React.useState(false);
  React.useEffect(() => {
    setEnvLoading(true);
    api.getConfigAll()
      .then(r => {
        const out: Record<string, string> = {};
        const secrets: Record<string, boolean> = {};
        for (const [k, v] of Object.entries(r.env)) {
          // 后端用 `${key}__has` 布尔标志表示敏感字段当前是否已设置
          if (k.endsWith('__has')) { secrets[k.slice(0, -5)] = Boolean(v); continue; }
          if (typeof v === 'string') {
            out[k] = SENSITIVE.has(k) ? '' : v; // 敏感字段不回填掩码
          }
        }
        setEnvFields(out);
        setHasSecret(secrets);
      })
      .catch(() => { /* ignore，留空表示用 fallback */ })
      .finally(() => setEnvLoading(false));
  }, [SENSITIVE]);

  const updateField = (k: string, v: string) => setEnvFields(prev => ({ ...prev, [k]: v }));

  // 敏感字段占位提示：已设置则提示"留空不修改"
  const secretPlaceholder = (k: string) => (hasSecret[k] ? '已设置 · 留空表示不修改' : '未设置');

  const saveFields = async (keys: string[]) => {
    const patch: Record<string, string> = {};
    keys.forEach(k => {
      const v = envFields[k];
      if (v === undefined) return;
      // 敏感字段留空 = 不修改，跳过以免覆盖真实值
      if (SENSITIVE.has(k) && v === '') return;
      patch[k] = v;
    });
    if (Object.keys(patch).length === 0) {
      showToast('err', '没有需要保存的字段（敏感字段留空表示不修改）');
      return;
    }
    try {
      const r = await api.patchConfig(patch);
      if (r.success) {
        // 已保存的敏感字段从内存清空（避免明文滞留），并标记为"已设置"，恢复占位语义
        const savedSecrets = Object.keys(patch).filter(k => SENSITIVE.has(k));
        if (savedSecrets.length) {
          setEnvFields(prev => {
            const next = { ...prev };
            savedSecrets.forEach(k => { next[k] = ''; });
            return next;
          });
          setHasSecret(prev => {
            const next = { ...prev };
            savedSecrets.forEach(k => { next[k] = true; });
            return next;
          });
        }
        showToast('ok', '已保存到 .env（重启 main.py 后生效）');
      } else {
        showToast('err', r.error ?? '保存失败');
      }
    } catch (e) {
      showToast('err', e instanceof ApiError ? `${e.status}` : (e as Error).message);
    }
  };

  // mode 切换 — setSeleniumOn/setHeadless 已走 store.setMode（乐观更新 + PUT /config/mode + refresh + 全局 toast/回滚）
  const handleSelenium = (v: boolean) => { setSeleniumOn(v); };

  const handleHeadless = (v: boolean) => {
    if (snapshot?.current_operation) {
      showToast('err', '当前有打卡进行中，此设置仅对下次打卡生效');
    }
    setHeadless(v);
  };

  // 邮件测试
  const handleEmailTest = async () => {
    showToast('ok', '正在测试 SMTP 连接...');
    try {
      const r = await api.testEmail();
      showToast(r.success ? 'ok' : 'err', r.message ?? r.error ?? '');
    } catch (e) {
      showToast('err', e instanceof ApiError ? `${e.status}` : (e as Error).message);
    }
  };

  // 测试每日提醒任务设置 (/test_reminder)
  const handleTestReminder = async () => {
    showToast('ok', '正在验证每日提醒任务设置...');
    try {
      const r = await api.testReminder();
      showToast(r.success ? 'ok' : 'err', r.message ?? r.error ?? (r.success ? '每日提醒任务已就绪' : '验证失败'));
    } catch (e) {
      showToast('err', e instanceof ApiError ? `${e.status}` : (e as Error).message);
    }
  };

  // 工作时间等字段：优先用 envFields，回退到 snapshot.config，再退到本地默认
  const fieldVal = (key: string, fallback: string) => envFields[key] ?? fallback;
  const workStart = fieldVal('WORK_START_TIME', snapshot?.config?.work_start_time ?? '09:00');
  const workEnd = fieldVal('WORK_END_TIME', snapshot?.config?.work_end_time ?? '17:30');
  const lateThr = fieldVal('LATE_THRESHOLD', String(snapshot?.config?.late_threshold ?? '15'));
  const earlyThr = fieldVal('EARLY_LEAVE_THRESHOLD', String(snapshot?.config?.early_leave_threshold ?? '15'));
  const dailyStatus = fieldVal('DAILY_STATUS_TIME', snapshot?.config?.daily_status_time ?? '08:20');

  // 本地行为开关（仅 UI 展示，dynamic_config schema 暂未扩展 → 不接后端，禁用控件避免误导）
  const [reminder] = React.useState(true);
  const [autoByebye] = React.useState(true);
  const [parallelLogin] = React.useState(true);
  const [virtualMouse] = React.useState(true);

  // 当前主题（从 AAS_THEME 取真实值，使高亮态与实际主题一致；AAS_THEME 接口仅支持 light/dark）
  const [theme, setThemeLocal] = React.useState<'light' | 'dark'>(
    () => window.AAS_THEME?.get().theme ?? 'light',
  );
  const handleTheme = (t: 'light' | 'dark') => {
    window.AAS_THEME?.setTheme(t);
    setThemeLocal(t);
  };

  return (
    <div className="col gap-4">
      {toast && (
        <div
          style={{
            position: 'fixed', top: 80, right: 24, zIndex: 200,
            background: 'var(--bg-card)',
            border: `1px solid var(--${toast.type === 'ok' ? 'success' : 'danger'}-border)`,
            borderLeft: `3px solid var(--${toast.type === 'ok' ? 'success' : 'danger'})`,
            borderRadius: 'var(--radius)',
            padding: '10px 16px',
            boxShadow: 'var(--shadow-lg)',
            fontSize: 13,
            maxWidth: 360,
          }}
        >
          {toast.text}
        </div>
      )}
      <div className="row gap-2">
        <div className="tab-bar">
          {([
            { id: 'general', l: '通用' },
            { id: 'users', l: '账户与登录' },
            { id: 'schedule', l: '打卡时间' },
            { id: 'automation', l: '自动化模式' },
            { id: 'weather', l: '天气' },
            { id: 'telegram', l: 'Telegram' },
            { id: 'email', l: '邮件' },
            { id: 'advanced', l: '高级' },
          ] as { id: TabKey; l: string }[]).map(t => (
            <button
              key={t.id}
              className={`tab-btn ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.l}
            </button>
          ))}
        </div>
      </div>

      {tab === 'general' && (
        <div className="grid grid-2">
          <Section title="行为开关" sub="暂未生效（展示用）· 行为由 .env / 代码常量控制" icon="Zap">
            {[
              {
                t: '每日 8:15 提醒',
                d: '向 Telegram 推送当日提醒，可一键 /auto_byebye',
                v: reminder,
              },
              {
                t: '自动下班调度',
                d: '上班后按 8h15m + 随机延迟自动安排下班',
                v: autoByebye,
              },
              {
                t: '并行登录',
                d: '多账户 Selenium 模式下并发执行打卡 (最大 3)',
                v: parallelLogin,
              },
              {
                t: '虚拟鼠标点击',
                d: 'win32 PostMessage 模拟点击，避免抢占焦点',
                v: virtualMouse,
              },
            ].map((r, i) => (
              <div className="toggle-row" key={i}>
                <div className="toggle-row-info">
                  <div className="toggle-row-title">{r.t}</div>
                  <div className="toggle-row-desc">{r.d}</div>
                </div>
                {/* dynamic_config schema 暂未扩展，禁用以免误导用户以为已关闭自动下班等真实行为 */}
                <Toggle on={r.v} onChange={() => { /* 展示用，未接后端 */ }} disabled />
              </div>
            ))}
            <div className="divider" />
            <div className="row gap-2" style={{ justifyContent: 'flex-end' }}>
              <button className="btn" onClick={handleTestReminder}>
                <Icon.Zap size={12} />测试每日提醒推送
              </button>
            </div>
          </Section>

          <Section title="外观与语言" icon="Globe">
            <div className="field">
              <div className="field-label">主题</div>
              <div className="row gap-2">
                {([
                  { l: '浅色', v: 'light' },
                  { l: '深色', v: 'dark' },
                ] as { l: string; v: 'light' | 'dark' }[]).map(t => (
                  <button
                    key={t.v}
                    className={`btn btn-sm ${theme === t.v ? 'btn-primary' : ''}`}
                    onClick={() => handleTheme(t.v)}
                  >
                    {t.l}
                  </button>
                ))}
              </div>
            </div>
            <div className="field">
              <div className="field-label">界面语言</div>
              <select className="input">
                <option>简体中文</option>
                <option>English</option>
              </select>
            </div>
            <div className="field">
              <div className="field-label">日历起始日</div>
              <div className="tab-bar">
                <button className="tab-btn active">星期一</button>
                <button className="tab-btn">星期日</button>
              </div>
            </div>
          </Section>
        </div>
      )}

      {tab === 'users' && (
        <Section
          title="多账户配置"
          sub=".env 中 LOGIN_USERNAME / LOGIN_USERNAME2 · 支持并行"
          icon="Users"
        >
          {USERS.map((u, i) => {
            const uKey = `LOGIN_USERNAME${i === 1 ? '2' : ''}`;
            const pKey = `LOGIN_PASSWORD${i === 1 ? '2' : ''}`;
            return (
            <div key={u.id} className="card" style={{ marginBottom: 12, border: '1px solid var(--border)' }}>
              <div className="card-header" style={{ background: 'var(--bg-inset)' }}>
                <div className="row gap-2">
                  <div
                    className="user-avatar"
                    style={{ background: u.color, width: 24, height: 24, fontSize: 11 }}
                  >
                    {u.short}
                  </div>
                  <div className="card-title">{u.name}</div>
                  <span className="pill pill-neutral mono" style={{ fontSize: 10 }}>{u.env}</span>
                </div>
                <span className="pill pill-success"><span className="dot" />已启用</span>
              </div>
              <div className="card-body">
                <div className="field-row">
                  <div className="field">
                    <div className="field-label">用户名 ({uKey})</div>
                    <input
                      className="input mono"
                      value={envFields[uKey] ?? ''}
                      onChange={e => updateField(uKey, e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <div className="field-label">密码 ({pKey})</div>
                    <input
                      className="input mono"
                      type="password"
                      value={envFields[pKey] ?? ''}
                      placeholder={secretPlaceholder(pKey)}
                      onChange={e => updateField(pKey, e.target.value)}
                    />
                  </div>
                </div>
                <div className="field">
                  <div className="field-label">备注 / 称谓</div>
                  <input className="input" defaultValue={`${u.short}先生/女士`} />
                </div>
              </div>
            </div>
            );
          })}
          <div className="row gap-2">
            <button className="btn"><Icon.Plus size={12} />添加账户</button>
            <div className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              ⚠️ 修改后需重启 main.py 让 config 重新加载 .env
            </div>
          </div>
          <div className="divider" />
          <div className="field">
            <div className="field-label">登录 URL (LOGIN_URL)</div>
            <input
              className="input mono"
              value={envFields['LOGIN_URL'] ?? ''}
              onChange={e => updateField('LOGIN_URL', e.target.value)}
            />
            <div className="field-hint">所有用户共用同一登录入口</div>
          </div>
          <div className="row gap-2" style={{ marginTop: 12, justifyContent: 'flex-end' }}>
            <button
              className="btn btn-primary"
              disabled={envLoading}
              onClick={() => saveFields(['LOGIN_USERNAME', 'LOGIN_PASSWORD', 'LOGIN_URL'])}
            >
              <Icon.Check size={12} />保存到 .env（需重启）
            </button>
          </div>
        </Section>
      )}

      {tab === 'schedule' && (
        <Section
          title="打卡时间"
          sub="WORK_START_TIME / WORK_END_TIME / *_THRESHOLD"
          icon="Clock"
        >
          <div className="field-row">
            <div className="field">
              <div className="field-label">正常上班时间 WORK_START_TIME</div>
              <input
                className="input mono"
                value={workStart}
                onChange={e => updateField('WORK_START_TIME', e.target.value)}
              />
            </div>
            <div className="field">
              <div className="field-label">正常下班时间 WORK_END_TIME</div>
              <input
                className="input mono"
                value={workEnd}
                onChange={e => updateField('WORK_END_TIME', e.target.value)}
              />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <div className="field-label">迟到阈值 LATE_THRESHOLD（分钟）</div>
              <input
                className="input mono"
                value={lateThr}
                onChange={e => updateField('LATE_THRESHOLD', e.target.value)}
              />
              <div className="field-hint">
                {workStart} 后 {lateThr} 分钟仍未打卡视为迟到
              </div>
            </div>
            <div className="field">
              <div className="field-label">早退阈值 EARLY_LEAVE_THRESHOLD（分钟）</div>
              <input
                className="input mono"
                value={earlyThr}
                onChange={e => updateField('EARLY_LEAVE_THRESHOLD', e.target.value)}
              />
            </div>
          </div>
          <div className="field">
            <div className="field-label">每日状态推送时间 DAILY_STATUS_TIME</div>
            <input
              className="input mono"
              value={dailyStatus}
              onChange={e => updateField('DAILY_STATUS_TIME', e.target.value)}
              style={{ maxWidth: 180 }}
            />
            <div className="field-hint">每日该时间自动向 Telegram 推送当日状态</div>
          </div>
          <div className="divider" />
          <div className="row spread">
            <div>
              <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>工作日识别</div>
              <div className="muted" style={{ fontSize: 11 }}>
                使用 chinese_calendar 包，自动识别中国节假日与调休
              </div>
            </div>
            <span className="pill pill-success"><span className="dot" />已启用</span>
          </div>
          <div className="row gap-2" style={{ marginTop: 12, justifyContent: 'flex-end' }}>
            <button
              className="btn btn-primary"
              disabled={envLoading}
              onClick={() => saveFields(['WORK_START_TIME', 'WORK_END_TIME', 'LATE_THRESHOLD', 'EARLY_LEAVE_THRESHOLD', 'DAILY_STATUS_TIME'])}
            >
              <Icon.Check size={12} />保存到 .env（需重启）
            </button>
          </div>
        </Section>
      )}

      {tab === 'automation' && (
        <div className="col gap-4">
          <Section
            title="自动化模式"
            sub="dynamic_config.json · 切换后立即生效，无需重启"
            icon="Activity"
          >
            <div className="toggle-row">
              <div className="toggle-row-info">
                <div className="toggle-row-title">USE_SELENIUM_LOGIN</div>
                <div className="toggle-row-desc">
                  使用 Selenium WebDriver（推荐 · 更稳定 · 支持并行）— 实时生效
                </div>
              </div>
              <Toggle on={seleniumOn} onChange={handleSelenium} />
            </div>
            <div className="toggle-row">
              <div className="toggle-row-info">
                <div className="toggle-row-title">SELENIUM_HEADLESS</div>
                <div className="toggle-row-desc">无头模式 · 不弹出浏览器窗口 — 下次打卡生效</div>
              </div>
              <Toggle on={headless} onChange={handleHeadless} />
            </div>
            <div
              style={{
                padding: 12,
                background: 'var(--bg-inset)',
                borderRadius: 6,
                fontSize: 11,
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              当前:{' '}
              {seleniumOn
                ? headless
                  ? 'Selenium · headless · 并行 (max 3)'
                  : 'Selenium · visible · 并行 (max 3)'
                : 'PyAutoGUI · 图像识别 · 串行'}
            </div>
          </Section>

          <Section
            title="备用 · 图像识别配置"
            sub="USE_SELENIUM_LOGIN=false 时启用"
            icon="Eye"
          >
            <div className="field-row">
              <div className="field">
                <div className="field-label">Tesseract 路径 TESSERACT_PATH</div>
                <input
                  className="input mono"
                  value={envFields['TESSERACT_PATH'] ?? ''}
                  onChange={e => updateField('TESSERACT_PATH', e.target.value)}
                />
              </div>
              <div className="field">
                <div className="field-label">匹配阈值 MATCH_THRESHOLD</div>
                <input className="input mono" defaultValue="0.8" disabled />
                <div className="field-hint">代码常量，暂不支持在此修改</div>
              </div>
            </div>
            <div className="field">
              <div className="field-label">模板目录</div>
              <input className="input mono" defaultValue="templates/" disabled />
              <div className="field-hint">
                19 张模板图片 · username_field / login_button / punch_button …
              </div>
            </div>
            <div className="row gap-2" style={{ marginTop: 12, justifyContent: 'flex-end' }}>
              <button
                className="btn btn-primary"
                disabled={envLoading}
                onClick={() => saveFields(['TESSERACT_PATH'])}
              >
                <Icon.Check size={12} />保存到 .env（需重启）
              </button>
            </div>
          </Section>
        </div>
      )}

      {tab === 'weather' && (
        <Section
          title="彩云天气"
          sub="固定地点：上海市长宁区华山路1076号 · 彩云 v2.6 综合天气"
          icon="Cloud"
        >
          <div className="field-row">
            <div className="field">
              <div className="field-label">App Key CAIYUN_WEATHER_APP_KEY</div>
              <input
                className="input mono"
                type="password"
                value={envFields['CAIYUN_WEATHER_APP_KEY'] ?? ''}
                placeholder={secretPlaceholder('CAIYUN_WEATHER_APP_KEY')}
                onChange={e => updateField('CAIYUN_WEATHER_APP_KEY', e.target.value)}
              />
            </div>
            <div className="field">
              <div className="field-label">App Secret CAIYUN_WEATHER_APP_SECRET</div>
              <input
                className="input mono"
                type="password"
                value={envFields['CAIYUN_WEATHER_APP_SECRET'] ?? ''}
                placeholder={secretPlaceholder('CAIYUN_WEATHER_APP_SECRET')}
                onChange={e => updateField('CAIYUN_WEATHER_APP_SECRET', e.target.value)}
              />
            </div>
          </div>
          <div className="field">
            <div className="field-label">兼容 Token CAIYUN_WEATHER_TOKEN</div>
            <input
              className="input mono"
              type="password"
              value={envFields['CAIYUN_WEATHER_TOKEN'] ?? ''}
              placeholder={secretPlaceholder('CAIYUN_WEATHER_TOKEN')}
              onChange={e => updateField('CAIYUN_WEATHER_TOKEN', e.target.value)}
            />
            <div className="field-hint">
              优先使用更安全的 App Key + App Secret；只有旧版凭据时再填写 Token。
            </div>
          </div>
          <div
            style={{
              padding: 12,
              background: 'var(--bg-inset)',
              border: '1px solid var(--border-soft)',
              borderRadius: 6,
              fontSize: 11,
              lineHeight: 1.7,
              color: 'var(--text-secondary)',
            }}
          >
            天气地点已固定为上海市长宁区华山路1076号，不读取 Windows 定位，也不调用
            逆地理编码。认证凭据只由本机 Python 后端读取并用于调用彩云天气。
          </div>
          <div className="divider" />
          <div className="row gap-2" style={{ justifyContent: 'flex-end' }}>
            <button
              className="btn btn-primary"
              disabled={envLoading}
              onClick={() => saveFields([
                'CAIYUN_WEATHER_APP_KEY',
                'CAIYUN_WEATHER_APP_SECRET',
                'CAIYUN_WEATHER_TOKEN',
              ])}
            >
              <Icon.Check size={12} />保存到 .env（需重启）
            </button>
          </div>
        </Section>
      )}

      {tab === 'telegram' && (
        <Section title="Telegram Bot" sub="远程控制接口 · python-telegram-bot 库" icon="Bot">
          <div className="field-row">
            <div className="field">
              <div className="field-label">Bot Token TELEGRAM_BOT_TOKEN</div>
              <input
                className="input mono"
                type="password"
                value={envFields['TELEGRAM_BOT_TOKEN'] ?? ''}
                placeholder={secretPlaceholder('TELEGRAM_BOT_TOKEN')}
                onChange={e => updateField('TELEGRAM_BOT_TOKEN', e.target.value)}
              />
            </div>
            <div className="field">
              <div className="field-label">Chat ID TELEGRAM_CHAT_ID</div>
              <input
                className="input mono"
                value={envFields['TELEGRAM_CHAT_ID'] ?? ''}
                onChange={e => updateField('TELEGRAM_CHAT_ID', e.target.value)}
              />
            </div>
          </div>
          <div className="grid grid-3" style={{ marginTop: 8 }}>
            {[
              { k: 'Connection pool', v: '20' },
              { k: 'Read timeout', v: '20s' },
              { k: 'Update timeout', v: '600s' },
            ].map(x => (
              <div key={x.k} style={{ padding: 10, background: 'var(--bg-inset)', borderRadius: 6 }}>
                <div className="kicker">{x.k}</div>
                <div className="mono" style={{ fontSize: 14, marginTop: 2 }}>{x.v}</div>
              </div>
            ))}
          </div>
          <div className="divider" />
          <div className="row gap-2">
            <button
              className="btn btn-primary"
              disabled={envLoading}
              onClick={() => saveFields(['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'])}
            >
              <Icon.Check size={12} />保存到 .env（需重启）
            </button>
            <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              修改后需重启 main.py 生效
            </span>
          </div>
        </Section>
      )}

      {tab === 'email' && (
        <Section title="邮件通知" sub="SMTP · 打卡成功/失败截图抄送" icon="Mail">
          <div className="field-row">
            <div className="field">
              <div className="field-label">SMTP 服务器 EMAIL_SMTP_SERVER</div>
              <input
                className="input mono"
                value={envFields['EMAIL_SMTP_SERVER'] ?? ''}
                onChange={e => updateField('EMAIL_SMTP_SERVER', e.target.value)}
              />
            </div>
            <div className="field">
              <div className="field-label">端口 EMAIL_SMTP_PORT</div>
              <input
                className="input mono"
                value={envFields['EMAIL_SMTP_PORT'] ?? ''}
                onChange={e => updateField('EMAIL_SMTP_PORT', e.target.value)}
                style={{ maxWidth: 120 }}
              />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <div className="field-label">发件人 EMAIL_SENDER</div>
              <input
                className="input mono"
                value={envFields['EMAIL_SENDER'] ?? ''}
                onChange={e => updateField('EMAIL_SENDER', e.target.value)}
              />
            </div>
            <div className="field">
              <div className="field-label">授权码 EMAIL_PASSWORD</div>
              <input
                className="input mono"
                type="password"
                value={envFields['EMAIL_PASSWORD'] ?? ''}
                placeholder={secretPlaceholder('EMAIL_PASSWORD')}
                onChange={e => updateField('EMAIL_PASSWORD', e.target.value)}
              />
            </div>
          </div>
          <div className="field">
            <div className="field-label">收件人列表 EMAIL_RECIPIENTS</div>
            <input
              className="input mono"
              value={envFields['EMAIL_RECIPIENTS'] ?? ''}
              onChange={e => updateField('EMAIL_RECIPIENTS', e.target.value)}
            />
            <div className="field-hint">英文逗号分隔，可多个</div>
          </div>
          <div className="row gap-2">
            <button className="btn btn-primary" onClick={handleEmailTest}>
              <Icon.Mail size={12} />测试 SMTP 连接
            </button>
            <button
              className="btn"
              onClick={() => saveFields(['EMAIL_SENDER', 'EMAIL_PASSWORD', 'EMAIL_SMTP_SERVER', 'EMAIL_SMTP_PORT', 'EMAIL_RECIPIENTS'])}
            >
              <Icon.Check size={12} />保存到 .env
            </button>
            <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              修改后需重启 main.py 生效
            </span>
          </div>
        </Section>
      )}

      {tab === 'advanced' && (
        <div className="grid grid-2">
          {/* 看门狗参数为 watchdog.py 内代码常量，dynamic_config schema 暂未扩展 → 禁用控件并标注，免得用户误以为可在此调参 */}
          <Section title="看门狗 Watchdog" sub="暂未生效（展示用）· 参数由 watchdog.py 代码常量控制" icon="Power">
            <div className="field-row">
              <div className="field">
                <div className="field-label">最大重启次数 / 小时</div>
                <input className="input mono" defaultValue="5" disabled />
              </div>
              <div className="field">
                <div className="field-label">重启计数窗口 (秒)</div>
                <input className="input mono" defaultValue="3600" disabled />
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <div className="field-label">心跳间隔 (秒)</div>
                <input className="input mono" defaultValue="300" disabled />
              </div>
              <div className="field">
                <div className="field-label">最大错误数</div>
                <input className="input mono" defaultValue="5" disabled />
              </div>
            </div>
            <div className="toggle-row">
              <div className="toggle-row-info">
                <div className="toggle-row-title">退出时清理孤儿 driver</div>
                <div className="toggle-row-desc">SIGINT/SIGTERM/atexit 钩子兜底 msedgedriver</div>
              </div>
              {/* 展示用，未接后端，禁用以保持与通用 tab 一致 */}
              <Toggle on={true} onChange={() => { /* 展示用，未接后端 */ }} disabled />
            </div>
          </Section>

          <Section title="路径与目录" icon="Records">
            {[
              { k: 'PUNCH_RECORDS_DIR', v: 'punch_records/' },
              { k: 'SCREENSHOTS_DIR', v: 'screenshots/' },
              { k: 'LOGS_DIR', v: 'logs/' },
              { k: 'TEMPLATES_DIR', v: 'templates/' },
              { k: 'DYNAMIC_CONFIG', v: 'dynamic_config.json' },
            ].map(p => (
              <div
                key={p.k}
                className="row spread"
                style={{ padding: '8px 0', borderBottom: '1px solid var(--border-soft)' }}
              >
                <span className="mono" style={{ fontSize: 12 }}>{p.k}</span>
                <span className="mono muted" style={{ fontSize: 11 }}>{p.v}</span>
              </div>
            ))}
          </Section>
        </div>
      )}
    </div>
  );
}
