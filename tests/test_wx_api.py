import json
import unittest
from unittest.mock import MagicMock, patch


class WxApiTests(unittest.TestCase):
    @patch("core.wx_api.certifi.where", return_value="/tmp/fake-ca.pem")
    @patch("core.wx_api.ssl.create_default_context")
    @patch("core.wx_api.urllib.request.urlopen")
    def test_wx_get_uses_certifi_ssl_context(
        self,
        mock_urlopen,
        mock_create_default_context,
        _mock_certifi_where,
    ):
        from core.wx_api import wx_get

        mock_ctx = object()
        mock_create_default_context.return_value = mock_ctx

        response = MagicMock()
        response.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        mock_urlopen.return_value = response

        result = wx_get("/cgi-bin/test", "cookie=1", "token", "fp")

        self.assertEqual(result, {"ok": True})
        mock_create_default_context.assert_called_once_with(cafile="/tmp/fake-ca.pem")
        _request = mock_urlopen.call_args.args[0]
        self.assertEqual(mock_urlopen.call_args.kwargs["context"], mock_ctx)
        self.assertEqual(_request.full_url, "https://mp.weixin.qq.com/cgi-bin/test")


if __name__ == "__main__":
    unittest.main()
