from email.message import EmailMessage
import smtplib

from app.core.config import settings


def send_email(to_email: str, subject: str, body: str) -> None:
    if not settings.email_host or not settings.email_host_user:
        print(f"[email disabled] To: {to_email} | Subject: {subject}\n{body}")
        return

    message = EmailMessage()
    message["From"] = settings.default_from_email or settings.email_host_user
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.email_host, settings.email_port, timeout=20) as smtp:
        if settings.email_use_tls:
            smtp.starttls()
        smtp.login(settings.email_host_user, settings.email_host_password)
        smtp.send_message(message)
