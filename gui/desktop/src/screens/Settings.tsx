// 系统设置 — 接真实 API。
// - weather tab: patchConfig (.env 写入彩云天气密钥)
// - general tab: 主题切换走 window.AAS_THEME
// - advanced tab: 看门狗参数与路径（展示用）
import * as React from 'react';
import { Icon, type IconName } from '../lib/icons';
import { api, ApiError } from '../lib/api';

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

type TabKey =
  | 'general'
  | 'weather'
  | 'advanced';

export function SettingsScreen() {
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
            { id: 'weather', l: '天气' },
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

      {tab === 'weather' && (
        <Section
          title="彩云天气"
          sub="多地点天气 · 彩云 v2.6 综合天气"
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
            默认地点为上海市长宁区华山路1076号。收藏地点与当前地点请在“天气预报”页面
            管理和切换；城市搜索使用本地行政区划数据。认证凭据只由本机 Python 后端读取。
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
          </Section>

          <Section title="路径与目录" icon="Records">
            {[
              { k: 'LOGS_DIR', v: 'logs/' },
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
