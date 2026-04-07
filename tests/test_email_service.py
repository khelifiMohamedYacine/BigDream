"""
Tests for email_service.send_reset_email — SMTP is always mocked.
"""
import pytest
from unittest.mock import patch, MagicMock

from backend.email_service import send_reset_email


class TestSendResetEmail:
    @patch("backend.email_service.smtplib.SMTP")
    def test_returns_true_on_success(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        with patch.dict("os.environ", {
            "SMTP_USER": "user@gmail.com",
            "SMTP_PASS": "password",
        }):
            result = send_reset_email("to@test.com", "123456")
        assert result is True

    @patch("backend.email_service.smtplib.SMTP")
    def test_calls_sendmail(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        with patch.dict("os.environ", {
            "SMTP_USER": "user@gmail.com",
            "SMTP_PASS": "password",
        }):
            send_reset_email("to@test.com", "123456")
        mock_server.sendmail.assert_called_once()

    def test_returns_false_when_credentials_missing(self):
        with patch.dict("os.environ", {"SMTP_USER": "", "SMTP_PASS": ""}):
            result = send_reset_email("to@test.com", "123456")
        assert result is False

    def test_returns_false_when_smtp_user_empty(self):
        with patch.dict("os.environ", {"SMTP_USER": "", "SMTP_PASS": "somepass"}):
            result = send_reset_email("to@test.com", "654321")
        assert result is False

    def test_returns_false_when_smtp_pass_empty(self):
        with patch.dict("os.environ", {"SMTP_USER": "user@gmail.com", "SMTP_PASS": ""}):
            result = send_reset_email("to@test.com", "654321")
        assert result is False

    @patch("backend.email_service.smtplib.SMTP", side_effect=Exception("Connection refused"))
    def test_returns_false_on_smtp_error(self, mock_smtp):
        with patch.dict("os.environ", {
            "SMTP_USER": "user@gmail.com",
            "SMTP_PASS": "password",
        }):
            result = send_reset_email("to@test.com", "123456")
        assert result is False

    @patch("backend.email_service.smtplib.SMTP")
    def test_email_contains_reset_code(self, mock_smtp):
        captured_messages = []

        def capture_sendmail(frm, to, msg):
            captured_messages.append(msg)

        mock_server = MagicMock()
        mock_server.sendmail.side_effect = capture_sendmail
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {
            "SMTP_USER": "user@gmail.com",
            "SMTP_PASS": "password",
        }):
            send_reset_email("to@test.com", "999888")

        assert len(captured_messages) == 1
        assert "999888" in captured_messages[0]

    @patch("backend.email_service.smtplib.SMTP")
    def test_uses_tls(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        with patch.dict("os.environ", {
            "SMTP_USER": "user@gmail.com",
            "SMTP_PASS": "password",
        }):
            send_reset_email("to@test.com", "111222")
        mock_server.starttls.assert_called_once()

    @patch("backend.email_service.smtplib.SMTP")
    def test_uses_correct_smtp_host(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        with patch.dict("os.environ", {
            "SMTP_HOST": "smtp.custom.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "u@custom.com",
            "SMTP_PASS": "p",
        }):
            send_reset_email("to@test.com", "000111")
        mock_smtp.assert_called_with("smtp.custom.com", 587)
