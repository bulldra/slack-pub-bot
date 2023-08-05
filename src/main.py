import json
import logging
import os
import re

import functions_framework
import google.cloud.logging
import slack_bolt
from flask import Request
from google.cloud import pubsub_v1
from slack_bolt.adapter.google_cloud_functions import SlackRequestHandler

import url_utils

SECRETS: dict = json.loads(os.getenv("SECRETS"))


logging_client: google.cloud.logging.Client = google.cloud.logging.Client()
logging_client.setup_logging()
logger: logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

app: slack_bolt.App = slack_bolt.App(
    token=SECRETS.get("SLACK_BOT_TOKEN"),
    signing_secret=SECRETS.get("SLACK_SIGNING_SECRET"),
    process_before_response=True,
    request_verification_enabled=True,
)


def pub_command(command, text, channel_id=None, ts=None, response_url=None):
    message = {
        "command": command,
        "text": text,
        "channel_id": channel_id,
        "ts": ts,
        "response_url": response_url,
    }
    publisher = pubsub_v1.PublisherClient()
    GCP_PROJECT_ID = SECRETS.get("GCP_PROJECT_ID")
    if GCP_PROJECT_ID is None:
        raise ValueError("GCP_PROJECT_ID environment variable must be set.")
    topic_path = publisher.topic_path(GCP_PROJECT_ID, "slack-ai-chat")
    publisher.publish(
        topic_path,
        data=json.dumps(message).encode("utf-8"),
    )


@app.command("/summarize")
@app.command("/wikipedia")
@app.command("/gpt")
def command_preprocessing(ack, body, say, message):
    ack()
    command = body["command"]
    text = body["text"]
    logger.debug(f"command: {command} text: {text}")
    response_url = body["response_url"]
    text = re.sub("<@[a-zA-Z0-9]{11}>", "", text)
    say(f"{command} {text}")
    pub_command(command, text, response_url=response_url)


@app.message(re.compile(".*https?://.+"))
def handle_message(context, message):
    channel_id: str = context.channel_id
    if channel_id == SECRETS.get("SHARE_CHANNEL_ID"):
        logger.debug(f"channel_id: {channel_id}, message: {message}")
        text: str = message["text"]
        ts: str = message["ts"]
        link: str = url_utils.extract_link(text)
        if link is not None:
            pub_command("/summarize", link, channel_id=channel_id, ts=ts)


@app.event({"type": "message", "subtype": "message_changed"})
def log_message_change(logger, event):
    logger.info(f"message changed {event}")


@app.event({"type": "message", "subtype": "message_deleted"})
def log_message_deleted(logger, event):
    logger.info(f"message deleted {event}")


@functions_framework.http
def main(request: Request):
    if request.method != "POST":
        return "Only POST requests are accepted", 405

    if request.headers.get("x-slack-retry-num"):
        return "No need to resend", 200

    content_type: str = request.headers.get("Content-Type")
    if content_type == "application/json":
        body: dict = request.get_json()
        if body.get("type") == "url_verification":
            headers: dict = {"Content-Type": "application/json"}
            res: str = json.dumps({"challenge": body.get("challenge")})
            return (res, 200, headers)
        else:
            return SlackRequestHandler(app).handle(request)
    elif content_type == "application/x-www-form-urlencoded":
        return SlackRequestHandler(app).handle(request)
    else:
        return ("Bad Request", 400)
