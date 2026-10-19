"""SMTP transport for verification and durable operator notifications."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def send_email(to: str, subject: str, text: str = "", sealed_text: str = "") -> None:
    if sealed_text:
        from controlplane.vault import open_seal
        text = open_seal(sealed_text)
    host = os.environ["SMTP_HOST"]
    sender = os.environ["SMTP_FROM"]
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, to, subject
    message.set_content(text)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if os.getenv("SMTP_USERNAME"):
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)
