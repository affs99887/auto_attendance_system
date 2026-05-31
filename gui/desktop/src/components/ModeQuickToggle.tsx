// 主界面快捷切换：Selenium ⇄ 图像识别 + 无头/可见。
// 状态来自后端真实配置（经 App context 从 snapshot.config 派生），点击即调 setMode 持久化。
import * as React from 'react';
import { useApp } from '../App';

export function ModeQuickToggle() {
  const { seleniumOn, setSeleniumOn, headless, setHeadless } = useApp();
  return (
    <div className="row gap-2">
      <button
        className="btn btn-sm"
        title="点击切换：Selenium WebDriver / 图像识别 (PyAutoGUI)"
        onClick={() => setSeleniumOn(!seleniumOn)}
      >
        <span
          className="dot"
          style={{ background: seleniumOn ? 'var(--success)' : 'var(--text-muted)' }}
        />
        {seleniumOn ? 'Selenium' : '图像识别'}
      </button>
      {seleniumOn && (
        <button
          className="btn btn-sm"
          title="点击切换无头 / 可见（下次打卡生效）"
          onClick={() => setHeadless(!headless)}
        >
          <span
            className="dot"
            style={{ background: headless ? '#3B82F6' : 'var(--text-muted)' }}
          />
          {headless ? '无头' : '可见'}
        </button>
      )}
    </div>
  );
}
