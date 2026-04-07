"""
test_email_service.py
=====================
Tests for the email_service.send_reset_email function.

All SMTP connections are mocked — no real emails are sent.
Tests cover:
  - Missing credentials → returns False without attempting connection
  - Successful send → returns True
  - SMTP exception → returns False (graceful failure)
  - HTML content includes the reset code
  - Text fallback content includes the reset code
  - Subject line is correct
"""
import smtplib
import pytest
from unittest.mock import patch, MagicMock, call

from backend.email_service import send_reset_email


# ===========================================================================
# Missing credentials
# ===========================================================================

class TestMissingCredentials:
    def test_no_smtp_user_returns_false(self):
        with patch.dict("os.environ", {"SMTP_USER": "", "SMTP_PASS": "pass"}, clear=False):
            result = send_reset_email("target@example.com", "123456")
        assert result is False

    def test_no_smtp_pass_returns_false(self):
        with patch.dict("os.environ", {"SMTP_USER": "user@mail.com", "SMTP_PASS": ""}, clear=False):
            result = send_reset_email("target@example.com", "123456")
        assert result is False

    def test_both_empty_returns_false(self):
        with patch.dict("os.environ", {"SMTP_USER": "", "SMTP_PASS": ""}, clear=False):
            result = send_reset_email("target@example.com", "123456")
        assert result is False

    def test_does_not_call_smtp_when_no_credentials(self):
        with patch.dict("os.environ", {"SMTP_USER": "", "SMTP_PASS": ""}):
            with patch("smtplib.SMTP") as mock_smtp:
                send_reset_email("target@example.com", "000000")
                mock_smtp.assert_not_called()


# ===========================================================================
# Successful send (mocked SMTP)
# ===========================================================================

class TestSuccessfulSend:
    @pytest.fixture
    def smtp_env(self):
        return {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASS": "secret",
        }

    def test_returns_true_on_success(self, smtp_env):
        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                result = send_reset_email("target@example.com", "654321")
        assert result is True

    def test_smtp_connected_to_correct_host(self, smtp_env):
        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                send_reset_email("target@example.com", "654321")
                MockSMTP.assert_called_with("smtp.example.com", 587)

    def test_starttls_called(self, smtp_env):
        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                send_reset_email("target@example.com", "654321")
                mock_server.starttls.assert_called_once()

    def test_login_called_with_credentials(self, smtp_env):
        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                send_reset_email("target@example.com", "654321")
                mock_server.login.assert_called_once_with(
                    "sender@example.com", "secret"
                )

    def test_sendmail_called_with_recipient(self, smtp_env):
        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                send_reset_email("target@example.com", "654321")
                args = mock_server.sendmail.call_args
                assert "target@example.com" in args[0]


# ===========================================================================
# SMTP failure (exception)
# ===========================================================================

class TestSMTPFailure:
    @pytest.fixture
    def smtp_env(self):
        return {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASS": "secret",
        }

    def test_smtp_exception_returns_false(self, smtp_env):
        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("Connection failed")):
                result = send_reset_email("target@example.com", "123456")
        assert result is False

    def test_connection_error_returns_false(self, smtp_env):
        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
                result = send_reset_email("target@example.com", "123456")
        assert result is False

    def test_auth_error_returns_false(self, smtp_env):
        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
                result = send_reset_email("target@example.com", "123456")
        assert result is False


# ===========================================================================
# Email content
# ===========================================================================

class TestEmailContent:
    """Verify the constructed message contains the reset code."""

    @pytest.fixture
    def smtp_env(self):
        return {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASS": "secret",
        }

    def test_html_body_contains_code(self, smtp_env):
        sent_messages = []

        def capture_sendmail(from_addr, to_addr, msg_str):
            sent_messages.append(msg_str)

        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                mock_server.sendmail.side_effect = capture_sendmail
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                send_reset_email("target@example.com", "789012")

        assert len(sent_messages) == 1
        assert "789012" in sent_messages[0]

    def test_message_contains_subject(self, smtp_env):
        sent_messages = []

        def capture(from_addr, to_addr, msg_str):
            sent_messages.append(msg_str)

        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                mock_server.sendmail.side_effect = capture
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                send_reset_email("target@example.com", "111111")

        assert "BigDream" in sent_messages[0]

    def test_different_codes_produce_different_bodies(self, smtp_env):
        messages = []

        def capture(f, t, msg):
            messages.append(msg)

        with patch.dict("os.environ", smtp_env):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                mock_server.sendmail.side_effect = capture
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                send_reset_email("t@example.com", "111111")
                send_reset_email("t@example.com", "999999")

        assert messages[0] != messages[1]


# ===========================================================================
# Default SMTP configuration
# ===========================================================================

class TestDefaultConfig:
    def test_default_host_is_gmail(self):
        """When SMTP_HOST is unset, host defaults to smtp.gmail.com."""
        import os
        env = {
            "SMTP_USER": "u@gmail.com",
            "SMTP_PASS": "p",
        }
        # Remove SMTP_HOST if set
        clean_env = {k: v for k, v in os.environ.items() if k != "SMTP_HOST"}
        clean_env.update(env)
        with patch.dict("os.environ", clean_env, clear=True):
            with patch("smtplib.SMTP") as MockSMTP:
                mock_server = MagicMock()
                MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
                send_reset_email("t@example.com", "123456")
                MockSMTP.assert_called_with("smtp.gmail.com", 587)
