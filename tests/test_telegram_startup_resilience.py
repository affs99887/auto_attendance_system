import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import main as app_main
from modules.attendance_system import AttendanceSystem
from modules.telegram_bot import TelegramBot


class NetworkError(Exception):
    pass


class TelegramStartupResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_activation_failure_marks_degraded_without_raising(self):
        app = SimpleNamespace(
            start=AsyncMock(),
            stop=AsyncMock(),
            shutdown=AsyncMock(),
        )
        bot = SimpleNamespace(
            app=app,
            _ensure_app_initialized=AsyncMock(),
            start_polling=AsyncMock(side_effect=NetworkError('polling failed')),
            is_polling=False,
            _is_initialized=True,
            _reconnect_lock=asyncio.Lock(),
        )
        system = SimpleNamespace(bot=bot, bot_available=False, bot_error='正在初始化')

        result = await app_main._activate_initialized_bot(system)

        self.assertFalse(result)
        self.assertFalse(system.bot_available)
        self.assertIn('polling failed', system.bot_error)
        self.assertIsNone(bot.app)
        app.stop.assert_awaited_once()
        app.shutdown.assert_awaited_once()

    async def test_activation_success_is_the_only_path_marking_bot_available(self):
        app = SimpleNamespace(
            start=AsyncMock(),
            stop=AsyncMock(),
            shutdown=AsyncMock(),
        )
        bot = SimpleNamespace(
            app=app,
            _ensure_app_initialized=AsyncMock(),
            start_polling=AsyncMock(),
            is_polling=True,
            _is_initialized=True,
            _reconnect_lock=asyncio.Lock(),
        )
        system = SimpleNamespace(bot=bot, bot_available=False, bot_error='正在初始化')

        result = await app_main._activate_initialized_bot(system)

        self.assertTrue(result)
        self.assertTrue(system.bot_available)
        self.assertIsNone(system.bot_error)

    async def test_activation_and_manual_reconnect_share_lifecycle_lock(self):
        activation_entered = asyncio.Event()
        release_activation = asyncio.Event()
        order = []

        async def ensure_initialized():
            order.append('activate_enter')
            activation_entered.set()
            await release_activation.wait()

        app = SimpleNamespace(
            start=AsyncMock(side_effect=lambda: order.append('activate_start')),
            stop=AsyncMock(),
            shutdown=AsyncMock(),
        )
        lock = asyncio.Lock()
        bot = SimpleNamespace(
            app=app,
            _ensure_app_initialized=ensure_initialized,
            start_polling=AsyncMock(side_effect=lambda: order.append('activate_polling')),
            is_polling=True,
            _is_initialized=True,
            _reconnect_lock=lock,
        )
        system = SimpleNamespace(bot=bot, bot_available=False, bot_error='正在初始化')

        async def manual_reconnect():
            async with lock:
                order.append('manual_reconnect')

        activation_task = asyncio.create_task(
            app_main._activate_initialized_bot(system))
        await activation_entered.wait()
        reconnect_task = asyncio.create_task(manual_reconnect())
        await asyncio.sleep(0)
        self.assertFalse(reconnect_task.done())

        release_activation.set()
        await asyncio.gather(activation_task, reconnect_task)

        self.assertEqual(order, [
            'activate_enter', 'activate_start', 'activate_polling', 'manual_reconnect',
        ])

    async def test_monitor_recovers_even_when_app_is_missing(self):
        system = SimpleNamespace(bot_available=False, bot_error='offline')
        bot = TelegramBot.__new__(TelegramBot)
        bot.attendance_system = system
        bot.app = None
        bot.is_polling = False
        bot.last_update_time = None
        bot.connection_error_count = 3
        bot.reconnect = AsyncMock(return_value=(True, 'ok'))

        with patch('modules.telegram_bot.asyncio.sleep', new=AsyncMock(
                side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await bot.monitor_connection()

        bot.reconnect.assert_awaited_once_with(force=False)
        self.assertTrue(system.bot_available)
        self.assertIsNone(system.bot_error)
        self.assertEqual(bot.connection_error_count, 0)

    async def test_network_error_threshold_never_restarts_whole_program(self):
        attendance_system = SimpleNamespace(
            bot_available=True,
            bot_error=None,
            restart_program=AsyncMock(),
        )
        bot = TelegramBot.__new__(TelegramBot)
        bot.max_retries = 1
        bot.retry_delay = 0
        bot.connection_error_count = 9
        bot.max_connection_errors = 10
        bot.last_connection_error = None
        bot.attendance_system = attendance_system
        bot.chat_id = 'chat'
        bot._is_initialized = True
        bot._ensure_app_initialized = AsyncMock()
        bot.app = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock(
                side_effect=NetworkError('network down')))
        )

        result = await bot.send_message('title', 'content')
        second_result = await bot.send_message('title', 'content')

        self.assertFalse(result)
        self.assertFalse(second_result)
        attendance_system.restart_program.assert_not_awaited()
        self.assertFalse(attendance_system.bot_available)
        self.assertIn('等待后台重连', attendance_system.bot_error)
        self.assertTrue(bot._is_initialized)
        bot._ensure_app_initialized.assert_awaited_once()

    async def test_polling_bootstrap_failure_is_not_retried_forever(self):
        updater = SimpleNamespace(start_polling=AsyncMock())
        bot = TelegramBot.__new__(TelegramBot)
        bot.app = SimpleNamespace(updater=updater)
        bot.is_polling = False
        bot.connection_timeout = 20
        bot.read_timeout = 20
        bot.write_timeout = 20
        bot.connect_timeout = 20
        bot.pool_timeout = 20

        await bot.start_polling()

        self.assertEqual(updater.start_polling.await_args.kwargs['bootstrap_retries'], 0)

    async def test_stop_polling_cleans_running_updater_even_if_flag_is_false(self):
        updater = SimpleNamespace(running=True, stop=AsyncMock())
        bot = TelegramBot.__new__(TelegramBot)
        bot.app = SimpleNamespace(updater=updater)
        bot.is_polling = False
        bot.cleanup_connections = AsyncMock()

        await bot.stop_polling()

        updater.stop.assert_awaited_once()
        bot.cleanup_connections.assert_awaited_once()

    async def test_degraded_notification_still_reaches_gui_without_bot_retry(self):
        event_bus = SimpleNamespace(publish=AsyncMock())
        bot = SimpleNamespace(
            _ensure_app_initialized=AsyncMock(),
            send_message=AsyncMock(),
            app=None,
        )
        system = AttendanceSystem.__new__(AttendanceSystem)
        system.update_progress = Mock(return_value='progress')
        system._event_bus = event_bus
        system.bot = bot
        system.bot_available = False
        system.message_id = None

        await AttendanceSystem.send_notification(system, '打卡流程', '处理中')

        event_bus.publish.assert_awaited_once()
        bot._ensure_app_initialized.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    async def test_constructor_tolerates_initial_proxy_probe_error(self):
        with patch('modules.telegram_bot.config.get_telegram_proxy',
                   side_effect=RuntimeError('probe failed')):
            bot = TelegramBot('chat')

        self.assertIsNone(bot.proxy_url)


if __name__ == '__main__':
    unittest.main()
