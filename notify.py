#!/usr/bin/env python3
"""
Send the digest. Configure via environment variables or config.json.

Email (Gmail example - use an App Password, not your account password):
    SMTP_HOST=smtp.gmail.com  SMTP_PORT=465
    SMTP_USER=you@gmail.com   SMTP_PASS=your-app-password
    ALERT_TO=you@gmail.com

Chat, either or both:
    SLACK_WEBHOOK=https://hooks.slack.com/services/...
    DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import requests


def load_config() -> dict:
    """config.json values, overridden by environment variables."""
    cfg = {}
    p = Path("config.json")
    if p.exists():
        cfg = json.loads(p.read_text())
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "ALERT_TO",
              "SLACK_WEBHOOK", "DISCORD_WEBHOOK"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def send_email(subject: str, html: str, text: str, cfg: dict) -> bool:
    need = ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "ALERT_TO")
    if not all(cfg.get(k) for k in need):
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["SMTP_USER"]
    msg["To"] = cfg["ALERT_TO"]
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    port = int(cfg.get("SMTP_PORT", 465))
    try:
        ctx = ssl.create_default_context()
        if port == 587:
            with smtplib.SMTP(cfg["SMTP_HOST"], port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg["SMTP_HOST"], port, context=ctx, timeout=30) as s:
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
                s.send_message(msg)
        print(f"Emailed {cfg['ALERT_TO']}")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


def send_webhook(text: str, cfg: dict) -> bool:
    sent = False
    for key, payload in (("SLACK_WEBHOOK", lambda t: {"text": t}),
                         ("DISCORD_WEBHOOK", lambda t: {"content": t[:1900]})):
        url = cfg.get(key)
        if not url:
            continue
        try:
            r = requests.post(url, json=payload(text), timeout=20)
            r.raise_for_status()
            print(f"Posted to {key.split('_')[0].title()}")
            sent = True
        except Exception as e:
            print(f"{key} failed: {e}")
    return sent
