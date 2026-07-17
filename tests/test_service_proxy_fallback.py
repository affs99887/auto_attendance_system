import unittest
from unittest.mock import Mock, patch

from modules import proxy_manager


class ServiceProxyFallbackTests(unittest.TestCase):
    def setUp(self):
        proxy_manager.reset_proxy_request_circuits()
        self.local_proxy = {
            'http': 'http://127.0.0.1:7899',
            'https': 'http://127.0.0.1:7899',
        }

    def tearDown(self):
        proxy_manager.reset_proxy_request_circuits()

    def test_uses_default_network_when_local_proxy_is_unavailable(self):
        response = Mock()
        with patch.object(proxy_manager.config, 'get_local_proxy', return_value=None), \
                patch.object(proxy_manager.requests, 'get', return_value=response) as request_get:
            result = proxy_manager.request_get_with_local_proxy_fallback(
                'demo_service', 'https://example.test/data', timeout=10)

        self.assertIs(result, response)
        request_get.assert_called_once_with('https://example.test/data', timeout=10)

    def test_connection_error_falls_back_and_opens_only_that_service_circuit(self):
        fallback_response = Mock()
        other_response = Mock()
        with patch.object(proxy_manager.config, 'get_local_proxy', return_value=self.local_proxy), \
                patch.object(
                    proxy_manager.requests,
                    'get',
                    side_effect=[
                        proxy_manager.requests.exceptions.ProxyError('proxy failed'),
                        fallback_response,
                        fallback_response,
                        other_response,
                    ],
                ) as request_get:
            first = proxy_manager.request_get_with_local_proxy_fallback(
                'demo_service', 'https://example.test/first')
            second = proxy_manager.request_get_with_local_proxy_fallback(
                'demo_service', 'https://example.test/second')
            other = proxy_manager.request_get_with_local_proxy_fallback(
                'exchange_rate', 'https://example.test/rate')

        self.assertIs(first, fallback_response)
        self.assertIs(second, fallback_response)
        self.assertIs(other, other_response)
        self.assertEqual(request_get.call_count, 4)
        self.assertEqual(request_get.call_args_list[0].kwargs['proxies'], self.local_proxy)
        self.assertNotIn('proxies', request_get.call_args_list[1].kwargs)
        self.assertNotIn('proxies', request_get.call_args_list[2].kwargs)
        self.assertEqual(request_get.call_args_list[3].kwargs['proxies'], self.local_proxy)

    def test_http_error_response_does_not_trigger_direct_retry(self):
        response = Mock(status_code=503)
        with patch.object(proxy_manager.config, 'get_local_proxy', return_value=self.local_proxy), \
                patch.object(proxy_manager.requests, 'get', return_value=response) as request_get:
            result = proxy_manager.request_get_with_local_proxy_fallback(
                'weather', 'https://example.test/weather')

        self.assertIs(result, response)
        request_get.assert_called_once_with(
            'https://example.test/weather', proxies=self.local_proxy)

    def test_reset_allows_proxy_retry_immediately(self):
        direct_response = Mock()
        recovered_response = Mock()
        with patch.object(proxy_manager.config, 'get_local_proxy', return_value=self.local_proxy), \
                patch.object(
                    proxy_manager.requests,
                    'get',
                    side_effect=[
                        proxy_manager.requests.exceptions.Timeout('timeout'),
                        direct_response,
                        recovered_response,
                    ],
                ) as request_get:
            proxy_manager.request_get_with_local_proxy_fallback(
                'demo_service_b', 'https://example.test/usage')
            proxy_manager.reset_proxy_request_circuits()
            result = proxy_manager.request_get_with_local_proxy_fallback(
                'demo_service_b', 'https://example.test/usage')

        self.assertIs(result, recovered_response)
        self.assertNotIn('proxies', request_get.call_args_list[1].kwargs)
        self.assertEqual(request_get.call_args_list[2].kwargs['proxies'], self.local_proxy)

    def test_inflight_old_failure_cannot_reopen_circuit_after_reset(self):
        direct_response = Mock()
        recovered_response = Mock()
        call_count = 0

        def request_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                self.assertIn('proxies', kwargs)
                proxy_manager.reset_proxy_request_circuits()
                raise proxy_manager.requests.exceptions.ProxyError('old node failed')
            if call_count == 2:
                self.assertNotIn('proxies', kwargs)
                return direct_response
            return recovered_response

        with patch.object(proxy_manager.config, 'get_local_proxy', return_value=self.local_proxy), \
                patch.object(proxy_manager.requests, 'get', side_effect=request_side_effect) as request_get:
            proxy_manager.request_get_with_local_proxy_fallback(
                'weather', 'https://example.test/weather')
            result = proxy_manager.request_get_with_local_proxy_fallback(
                'weather', 'https://example.test/weather')

        self.assertIs(result, recovered_response)
        self.assertEqual(request_get.call_args_list[2].kwargs['proxies'], self.local_proxy)

    def test_half_open_allows_only_one_proxy_probe(self):
        _, _, generation = proxy_manager._claim_local_proxy_attempt('demo_service', 0)
        proxy_manager._open_proxy_request_circuit('demo_service', generation)
        with proxy_manager._proxy_request_circuit_lock:
            proxy_manager._proxy_request_circuits['demo_service']['open_until'] = 0

        first = proxy_manager._claim_local_proxy_attempt('demo_service', 1)
        second = proxy_manager._claim_local_proxy_attempt('demo_service', 1)

        self.assertEqual(first[:2], (True, True))
        self.assertEqual(second[:2], (False, False))


if __name__ == '__main__':
    unittest.main()
