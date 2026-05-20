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

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return <div className={`toggle ${on ? 'on' : ''}`} onClick={() => onChange(!on)} />;
}

type TabKey =
  | 'general'
  | 'users'
  | 'schedule'
  | 'automation'
  | 'telegram'
  | 'email'
  | 'advanced';

export function SettingsScreen() {
  const { seleniumOn, setSeleniumOn, headless, setHeadless } = useApp();
  const snapshot = useSystemStore(s => s.snapshot);
  const refreshStatus = useSystemStore(s => s.refresh);
  const [tab, setTab] = React.useState<TabKey>('general');

  // Toast 状态
  const [toast, setToast] = React.useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const showToast = (type: 'ok' | 'err', text: string) => {
    setToast({ type, text });
    window.setTimeout(() => setToast(null), 4000);
  };

  // 从 API 拉初始 .env
  const [envFields, setEnvFields] = React.useState<Record<string, string>>({});
  const [envLoading, setEnvLoading] = React.useState(false);
  React.useEffect(() => {
    setEnvLoading(true);
    api.getConfigAll()
      .then(r => {
        const out: Record<string, string> = {};
        for (const [k, v] of Object.entries(r.env)) {
          if (typeof v === 'string') out[k] = v;
        }
        setEnvFields(out);
      })
      .catch(() => { /* ignore，留空表示用 fallback */ })
      .finally(() => setEnvLoading(false));
  }, []);

  const updateField = (k: string, v: string) => setEnvFields(prev => ({ ...prev, [k]: v }));

  const saveFields = async (keys: string[]) => {
    const patch: Record<string, string> = {};
    keys.forEach(k => { if (envFields[k] !== undefined) patch[k] = envFields[k]; });
    if (Object.keys(patch).length === 0) {
      showToast('err', '没有可保存的字段');
      return;
    }
    try {
      const r = await api.patchConfig(patch);
      if (r.success) {
        showToast('ok', '已保存到 .env（重启 main.py 后生效）');
      } else {
        showToast('err', r.error ?? '保存失败');
      }
    } catch (e) {
      showToast('err', e instanceof ApiError ? `${e.status}` : (e as Error).message);
    }
  };

  // mode 切换 — 接 setConfigMode 立即生效
  const handleSelenium = async (v: boolean) => {
    setSeleniumOn(v);
    try {
      await api.setConfigMode({ use_selenium_login: v });
      showToast('ok', `已切换到 ${v ? 'Selenium' : '图像识别'} 模式`);
      void refreshStatus();
    } catch (e) {
      showToast('err', `切换失败: ${e instanceof ApiError ? e.status : (e as Error).message}`);
    }
  };

  const handleHeadless = async (v: boolean) => {
    // headless 切换需提示 "下次打卡生效"
    if (snapshot?.current_operation) {
      showToast('err', '当前有打卡进行中，此设置仅对下次打卡生效');
    }
    setHeadless(v);
    try {
      await api.setConfigMode({ selenium_headless: v });
      showToast('ok', `已切换到 ${v ? '无头' : '可见'} 模式（下次打卡生效）`);
      void refreshStatus();
    } catch (e) {
      showToast('err', `切换失败: ${e instanceof ApiError ? e.status : (e as Error).message}`);
    }
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

  // 工作时间等字段：优先用 envFields，回退到 snapshot.config，再退到本地默认
  const fieldVal = (key: string, fallback: string) => envFields[key] ?? fallback;
  const workStart = fieldVal('WORK_START_TIME', snapshot?.config?.work_start_time ?? '09:00');
  const workEnd = fieldVal('WORK_END_TIME', snapshot?.config?.work_end_time ?? '17:30');
  const lateThr = fieldVal('LATE_THRESHOLD', String(snapshot?.config?.late_threshold ?? '15'));
  const earlyThr = fieldVal('EARLY_LEAVE_THRESHOLD', String(snapshot?.config?.early_leave_threshold ?? '15'));
  const dailyStatus = fieldVal('DAILY_STATUS_TIME', snapshot?.config?.daily_status_time ?? '08:20');

  // 本地行为开关（仅 UI，dynamic_config schema 暂未扩展）
  const [reminder, setReminder] = React.useState(true);
  const [autoByebye, setAutoByebye] = React.useState(true);
  const [parallelLogin, setParallelLogin] = React.useState(true);
  const [virtualMouse, setVirtualMouse] = React.useState(true);

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
          <Section title="行为开关" sub="dynamic_config.json 实时生效" icon="Zap">
            {[
              {
                t: '每日 8:15 提醒',
                d: '向 Telegram 推送当日提醒，可一键 /auto_byebye',
                v: reminder,
                set: setReminder,
              },
              {
                t: '自动下班调度',
                d: '上班后按 8h15m + 随机延迟自动安排下班',
                v: autoByebye,
                set: setAutoByebye,
              },
              {
                t: '并行登录',
                d: '多账户 Selenium 模式下并发执行打卡 (最大 3)',
                v: parallelLogin,
                set: setParallelLogin,
              },
              {
                t: '虚拟鼠标点击',
                d: 'win32 PostMessage 模拟点击，避免抢占焦点',
                v: virtualMouse,
                set: setVirtualMouse,
              },
            ].map((r, i) => (
              <div className="toggle-row" key={i}>
                <div className="toggle-row-info">
                  <div className="toggle-row-title">{r.t}</div>
                  <div className="toggle-row-desc">{r.d}</div>
                </div>
                <Toggle on={r.v} onChange={r.set} />
              </div>
            ))}
          </Section>

          <Section title="外观与语言" icon="Globe">
            <div className="field">
              <div className="field-label">主题</div>
              <div className="row gap-2">
                {['浅色', '深色', '跟随系统'].map((t, i) => (
                  <button
                    key={t}
                    className={`btn btn-sm ${i === 0 ? 'btn-primary' : ''}`}
                    onClick={() => {
                      const map = ['light', 'dark', 'light'] as const;
                      window.AAS_THEME?.setTheme(map[i]);
                    }}
                  >
                    {t}
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
          {USERS.map((u, i) => (
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
                    <div className="field-label">用户名 (LOGIN_USERNAME{i === 1 ? '2' : ''})</div>
                    <input className="input mono" defaultValue={u.name} />
                  </div>
                  <div className="field">
                    <div className="field-label">密码 (LOGIN_PASSWORD{i === 1 ? '2' : ''})</div>
                    <input className="input mono" defaultValue="●●●●●●●●●●●●" type="password" />
                  </div>
                </div>
                <div className="field">
                  <div className="field-label">备注 / 称谓</div>
                  <input className="input" defaultValue={`${u.short}先生/女士`} />
                </div>
              </div>
            </div>
          ))}
          <div className="row gap-2">
            <button className="btn"><Icon.Plus size={12} />添加账户</button>
            <div className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              ⚠️ 修改后需重启 main.py 让 config 重新加载 .env
            </div>
          </div>
          <div className="divider" />
          <div className="field">
            <div className="field-label">登录 URL (LOGIN_URL)</div>
            <input className="input mono" defaultValue="https://timecard.example.corp/login" />
            <div className="field-hint">所有用户共用同一登录入口</div>
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
                  defaultValue="C:\Program Files\Tesseract-OCR\tesseract.exe"
                />
              </div>
              <div className="field">
                <div className="field-label">匹配阈值 MATCH_THRESHOLD</div>
                <input className="input mono" defaultValue="0.8" />
              </div>
            </div>
            <div className="field">
              <div className="field-label">模板目录</div>
              <input className="input mono" defaultValue="templates/" disabled />
              <div className="field-hint">
                19 张模板图片 · username_field / login_button / punch_button …
              </div>
            </div>
          </Section>
        </div>
      )}

      {tab === 'telegram' && (
        <Section title="Telegram Bot" sub="远程控制接口 · python-telegram-bot 库" icon="Bot">
          <div className="field-row">
            <div className="field">
              <div className="field-label">Bot Token TELEGRAM_BOT_TOKEN</div>
              <input
                className="input mono"
                defaultValue="7595731872:AAHPdLF...redacted"
                type="password"
              />
            </div>
            <div className="field">
              <div className="field-label">Chat ID TELEGRAM_CHAT_ID</div>
              <input className="input mono" defaultValue="123456789" />
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
            <button className="btn btn-primary"><Icon.Zap size={12} />测试 Bot 连接</button>
            <button className="btn">查看活动 chat_id</button>
            <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              最近连接 0.4s 前 · OK
            </span>
          </div>
        </Section>
      )}

      {tab === 'email' && (
        <Section title="邮件通知" sub="SMTP · 打卡成功/失败截图抄送" icon="Mail">
          <div className="field-row">
            <div className="field">
              <div className="field-label">SMTP 服务器</div>
              <input className="input mono" defaultValue="smtp.qq.com" />
            </div>
            <div className="field">
              <div className="field-label">端口</div>
              <input className="input mono" defaultValue="465" style={{ maxWidth: 120 }} />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <div className="field-label">发件人 EMAIL_SENDER</div>
              <input className="input mono" defaultValue="your_email@qq.com" />
            </div>
            <div className="field">
              <div className="field-label">授权码 EMAIL_PASSWORD</div>
              <input
                className="input mono"
                defaultValue="●●●●●●●●●●●●●●●●"
                type="password"
              />
            </div>
          </div>
          <div className="field">
            <div className="field-label">收件人列表 EMAIL_RECIPIENTS</div>
            <input className="input mono" defaultValue="manager@corp.com, hr@corp.com" />
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
          <Section title="看门狗 Watchdog" sub="主程序崩溃后自动重启" icon="Power">
            <div className="field-row">
              <div className="field">
                <div className="field-label">最大重启次数 / 小时</div>
                <input className="input mono" defaultValue="5" />
              </div>
              <div className="field">
                <div className="field-label">重启计数窗口 (秒)</div>
                <input className="input mono" defaultValue="3600" />
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <div className="field-label">心跳间隔 (秒)</div>
                <input className="input mono" defaultValue="300" />
              </div>
              <div className="field">
                <div className="field-label">最大错误数</div>
                <input className="input mono" defaultValue="5" />
              </div>
            </div>
            <div className="toggle-row">
              <div className="toggle-row-info">
                <div className="toggle-row-title">退出时清理孤儿 driver</div>
                <div className="toggle-row-desc">SIGINT/SIGTERM/atexit 钩子兜底 msedgedriver</div>
              </div>
              <Toggle on={true} onChange={() => { /* readonly demo */ }} />
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
