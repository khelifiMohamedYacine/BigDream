"""
Email service for BigDream — sends password reset codes via SMTP.
Configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS in .env
"""
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_reset_email(to_email: str, code: str) -> bool:
    """Send a password reset code email. Returns True on success."""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASS", "")

    if not user or not password:
        return False

    subject = "Your BigDream Password Reset Code"

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #0a0a12; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 480px; margin: 40px auto; background: #12121e; border: 1px solid rgba(0,255,255,0.15); border-radius: 12px; overflow: hidden; }}
    .header {{ background: #0d0d1a; padding: 28px 32px; border-bottom: 1px solid rgba(0,255,255,0.1); }}
    .brand {{ font-size: 22px; font-weight: 900; color: #00ffff; letter-spacing: 0.06em; }}
    .body {{ padding: 32px; }}
    .body p {{ color: rgba(255,255,255,0.75); font-size: 15px; line-height: 1.6; margin: 0 0 16px; }}
    .code-box {{ background: #0a0a12; border: 1px solid rgba(0,255,255,0.3); border-radius: 8px; padding: 20px; text-align: center; margin: 24px 0; }}
    .code {{ font-size: 36px; font-weight: 900; color: #00ffff; letter-spacing: 0.18em; font-family: 'Courier New', monospace; }}
    .expiry {{ font-size: 13px; color: rgba(255,255,255,0.4); margin-top: 8px; }}
    .footer {{ padding: 20px 32px; border-top: 1px solid rgba(255,255,255,0.05); font-size: 12px; color: rgba(255,255,255,0.3); }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <div class="brand">BigDream</div>
    </div>
    <div class="body">
      <p>You requested a password reset. Use the code below to set a new password.</p>
      <div class="code-box">
        <div class="code">{code}</div>
        <div class="expiry">Expires in 15 minutes</div>
      </div>
      <p>If you did not request this, you can safely ignore this email. Your password will not change.</p>
    </div>
    <div class="footer">BigDream — AI-Powered Goal Management Platform</div>
  </div>
</body>
</html>
"""

    text_body = f"Your BigDream password reset code is: {code}\n\nThis code expires in 15 minutes.\n\nIf you did not request this, ignore this email."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, to_email, msg.as_string())
        return True
    except Exception:
        return False
