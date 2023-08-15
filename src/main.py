"""
Slackからのイベント処理を行うためのサーバレス関数
"""
import json
import logging
import os

import flask
import functions_framework
import google.cloud.logging
import slack_bolt
from google.cloud import pubsub_v1
from slack_bolt.adapter.google_cloud_functions import SlackRequestHandler

import slack_link_utils

SECRETS: dict = json.loads(os.getenv("SECRETS"))
GCP_PROJECT_ID = SECRETS.get("GCP_PROJECT_ID")
SHARE_CHANNEL_ID = SECRETS.get("SHARE_CHANNEL_ID")

logging_client: google.cloud.logging.Client = google.cloud.logging.Client()
logging_client.setup_logging()
logger: logging.Logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

app: slack_bolt.App = slack_bolt.App(
    token=SECRETS.get("SLACK_BOT_TOKEN"),
    signing_secret=SECRETS.get("SLACK_SIGNING_SECRET"),
    request_verification_enabled=True,
)


@app.event({"type": "message", "subtype": "message_changed"})
@app.event({"type": "message", "subtype": "message_deleted"})
def bot_message_change():
    """
    メッセージイベントがあった場合の処理
    """


@app.message()
def handle_message(context, message):
    """
    メッセージが送信された場合の処理
    起動条件のみを判定して、コマンドの選択は後続に移譲する
    """
    bot_user_id: str = context.bot_user_id
    if message.get("thread_ts") is not None:
        handle_thread(bot_user_id, message)
    elif context.channel_id == SHARE_CHANNEL_ID:
        handle_share(message)


@app.event("app_mention")
def mention(context, event):
    """
    BOTに対してメンションがされた場合の処理
    コマンドの選択は後続に移譲する
    """
    channel: str = event.get("channel")
    timestamp: str = event.get("ts")
    text: str = event.get("text")
    text = text.replace(f"<@{context.bot_user_id}>", "").strip()
    messages: [dict] = [{"role": "user", "content": text}]
    handle_placeholder(channel, timestamp, messages)


@app.command("/gpt")
@app.command("/summazise")
def handle_command(ack, command, say):
    """
    Slackのコマンドが実行された場合の処理
    最初にコマンド自体をSlackに送信しておき、そのメッセージに対するスレッド処理とする
    """
    ack()
    command_name: str = command.get("command")
    text: str = command.get("text")
    res = say(f"{command_name} {text}")
    messages: [dict] = [{"role": "user", "content": text}]
    channel: str = res.get("channel")
    timestamp: str = res.get("ts")
    handle_placeholder(channel, timestamp, messages, command=command_name)


def handle_thread(bot_user_id, message):
    """
    スレッドリプライされている場合の処理
    BOTがスレッド内にいればBOTが返信する
    """
    channel: str = message.get("channel")
    thread_ts: str = message.get("thread_ts")
    replies: dict = app.client.conversations_replies(
        channel=channel,
        ts=thread_ts,
    )
    if replies is None:
        return

    reply_messages = replies.get("messages")
    logger.debug(reply_messages)
    if (
        reply_messages is not None
        and len(reply_messages) > 0
        and reply_messages[0].get("reply_users") is not None
        and bot_user_id not in reply_messages[0].get("reply_users")
    ):
        return

    messages: [dict] = []
    for reply in sorted(reply_messages, key=lambda x: x["ts"]):
        role: str = "user"
        user_id = reply.get("user") or reply.get("bot_id")
        if user_id == bot_user_id or reply.get("bot_id"):
            role = "assistant"
        text: str = reply.get("text")
        messages.append({"role": role, "content": text})
    handle_placeholder(channel, thread_ts, messages)


def handle_share(message):
    """
    シェアチャンネルにリンクがシェアされた場合の処理
    """
    channel: str = message.get("channel")
    timestamp: str = message.get("ts")
    text: str = message.get("text")
    if slack_link_utils.is_contains_url(text):
        url: str = slack_link_utils.extract_and_remove_tracking_url(text)
        if url is None or not slack_link_utils.is_allow_scraping(url):
            return
        else:
            messages: [dict] = [{"role": "user", "content": url}]
            handle_placeholder(channel, timestamp, messages, command="/summazise")


def handle_placeholder(
    channel: str, thread_ts: str, messages: str, command: str = None
):
    """
    最初にスレッドにメッセージを返信しておき、そのメッセージを後続で処理対象とする
    """

    if messages is None or len(messages) == 0:
        return
    res = app.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="処理中.",
    )
    if res.get("ok") is not True:
        raise ValueError("Failed to post message.")
    timestamp: str = res.get("ts")
    arguments: dict = {"channel": channel, "ts": timestamp}
    pub_command(command, arguments, messages)


def pub_command(command: str, arguments: dict, messages: [dict]):
    """
    コマンドの種類や引数を後続処理に Pub/Sub で通知する
    """
    if GCP_PROJECT_ID is None:
        raise ValueError("GCP_PROJECT_ID environment variable must be set.")
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(GCP_PROJECT_ID, "slack-ai-chat")
    publisher.publish(
        topic_path,
        data=json.dumps(
            {
                "command": command,
                "arguments": arguments,
                "messages": messages,
            }
        ).encode("utf-8"),
    )


@functions_framework.http
def main(request: flask.Request):
    """
    Functionsのエントリーポイント
    """
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
