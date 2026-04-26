"""Email delivery using Gmail OAuth2 — based on GmailPOC (C:/coding/GmailPOC)."""

import base64
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from analyzer import ResearchReport
from config import EmailDeliveryConfig
from delivery.base import BaseDelivery

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _get_gmail_service():
    credentials_file = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
    token_file = os.getenv("GMAIL_TOKEN_FILE", "token.json")

    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(credentials_file).exists():
                print(f"ERROR: credentials file not found at '{credentials_file}'.")
                print("Set GMAIL_CREDENTIALS_FILE in .env or copy credentials.json from GmailPOC.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


class EmailDelivery(BaseDelivery):
    def __init__(self, config: EmailDeliveryConfig):
        self.config = config
        self.sender = os.getenv("SENDER_EMAIL")
        if not self.sender:
            raise ValueError("SENDER_EMAIL not set in .env")

    def deliver(self, report: ResearchReport) -> None:
        service = _get_gmail_service()
        subject = self.config.subject or f"Research Report: {report.project_name}"

        if report.match_table_html:
            msg = self._build_html_email(report, subject)
        else:
            msg = MIMEText(report.to_markdown(), "plain")
            msg["to"] = self.config.to
            msg["from"] = self.sender
            msg["subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
            print(f"Report emailed to {self.config.to}. Message ID: {result['id']}")
        except HttpError as e:
            print(f"ERROR sending email: {e}")

    def _build_html_email(self, report: ResearchReport, subject: str) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["to"] = self.config.to
        msg["from"] = self.sender
        msg["subject"] = subject

        # Plain-text fallback
        msg.attach(MIMEText(report.to_markdown(), "plain", "utf-8"))

        # HTML body — the match table is already a complete, styled page
        msg.attach(MIMEText(report.match_table_html, "html", "utf-8"))

        return msg
