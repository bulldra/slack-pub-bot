import json
import logging
import os
import re

import flask
import functions_framework
import google.cloud.logging
import slack_bolt
from google.cloud import pubsub_v1
from slack_bolt.adapter.google_cloud_functions import SlackRequestHandler

import url_utils

SECRETS: dict = json.loads(os.getenv("SECRETS"))
GCP_PROJECT_ID = SECRETS.get("GCP_PROJECT_ID")


logging_client: google.cloud.logging.Client = google.cloud.logging.Client()
logging_client.setup_logging()
logger: logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

app: slack_bolt.App = slack_bolt.App(
    token=SECRETS.get("SLACK_BOT_TOKEN"),
    signing_secret=SECRETS.get("SLACK_SIGNING_SECRET"),
    request_verification_enabled=True,
)


def pub_command(command: str, messages: [dict], arguments: dict):
    if GCP_PROJECT_ID is None:
        raise ValueError("GCP_PROJECT_ID environment variable must be set.")
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(GCP_PROJECT_ID, "slack-ai-chat")
    publisher.publish(
        topic_path,
        data=json.dumps(
            {
                "command": command,
                "messages": messages,
                "arguments": arguments,
            }
        ).encode("utf-8"),
    )


@app.event("app_mention")
def mention(event):
    logger.debug(f"event: {event}")
    messages: [dict] = [{"role": "user", "content": event["text"]}]
    arguments: dict = {
        "channel_id": event["channel"],
        "thread_ts": event["ts"],
    }
    pub_command("/gpt", messages, arguments)


def handle_thread(context, message):
    logger.debug(f"event: {message}")
    thread_ts: str = message["thread_ts"]
    replies: dict = app.client.conversations_replies(
        channel=context.channel_id, ts=thread_ts
    )
    if replies is None:
        return

    reply_messages = replies["messages"]
    if context.bot_user_id not in reply_messages[0]["reply_users"]:
        return

    messages: [dict] = []
    for r in sorted(reply_messages, key=lambda x: x["ts"]):
        role: str = "user"
        if context.bot_user_id == r["user"]:
            role = "assistant"
        messages.append({"role": role, "content": r["text"].strip()})
    arguments = {
        "channel_id": context.channel_id,
        "thread_ts": thread_ts,
    }
    pub_command("/gpt", messages, arguments)


def handle_url_message(context, message):
    logger.debug(f"event: {message}")
    if context.channel_id == SECRETS.get("SHARE_CHANNEL_ID"):
        logger.debug(f"channel_id: {context.channel_id}, message: {message}")
        text: str = message["text"]
        ts: str = message["ts"]
        link: str = url_utils.extract_url(text)
        if link is not None:
            messages = [{"role": "user", "content": link}]
            arguments = {
                "channel_id": context.channel_id,
                "thread_ts": ts,
            }
            pub_command("/summarize", messages, arguments)


@app.message()
def handle_main(context, message):
    if message.get("thread_ts") is not None:
        return handle_thread(context, message)
    elif re.match(r".*https?://.*", message.get("text")):
        return handle_url_message(context, message)
    else:
        return None


@app.event({"type": "message", "subtype": "bot_message"})
@app.event({"type": "message", "subtype": "message_changed"})
@app.event({"type": "message", "subtype": "message_deleted"})
def bot_message_change(event):
    pass


@functions_framework.http
def main(request: flask.Request):
    if request.method != "POST":
        return ("Only POST requests are accepted", 405)
    if request.headers.get("x-slack-retry-num"):
        return ("No need to resend", 200)

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
