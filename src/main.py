"""Slackからのイベント処理を行うためのサーバレス関数"""
import collections
import json
import logging
import os

import flask
import functions_framework
import google.cloud.logging
import slack_bolt
from google.cloud import pubsub_v1

import common.scraping_utils as scraping_utils
import common.slack_gcf_handler as slack_gcf_handler
import common.slack_link_utils as slack_link_utils

Chat = collections.namedtuple("Chat", ("role", "content"))
Chat.__new__.__defaults__ = ("user", None)


SECRETS: dict = json.loads(os.getenv("SECRETS"))

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
def bot_message_change() -> None:
    """メッセージイベントがあっても何もしない"""


@app.message()
def handle_message(context, message) -> None:
    """メッセージが送信された場合の処理。起動条件のみを判定して、コマンドの選択は後続に委譲"""
    share_cannel_id: str = SECRETS.get("SHARE_CHANNEL_ID")
    if message.get("thread_ts") is not None:
        handle_thread(context.bot_user_id, message)
    elif context.channel_id == share_cannel_id:
        handle_share(message)


@app.event("app_mention")
def mention(context, event) -> None:
    """BOTに対してメンションがされた場合の処理。コマンドの選択は後続に委譲"""
    text: str = event.get("text")
    if text is not None:
        text = text.replace(f"<@{context.bot_user_id}>", "").strip()
        pub_command(
            channel=event.get("channel"),
            thread_ts=event.get("ts"),
            chat_history=[Chat(content=text)],
        )


@app.command("/gpt")
@app.command("/summazise")
def handle_command(ack, command, say) -> None:
    """
    Slackのコマンドが実行された場合の処理
    コマンドをメッセージとしてSlackにPOSTし、そのメッセージに対するスレッド処理とする
    """
    ack()
    command_name: str = command.get("command")
    text: str = command.get("text")
    message = command_name
    if text is not None:
        message += f" {text}"
    res = say(message)
    pub_command(
        command=command_name,
        channel=res.get("channel"),
        thread_ts=res.get("ts"),
        chat_history=[Chat(content=text)],
    )


def handle_thread(bot_user_id, message) -> None:
    """スレッドリプライされている場合の処理。BOTがスレッド内にいればBOTが返信する"""
    channel: str = message.get("channel")
    thread_ts: str = message.get("thread_ts")
    replies: dict = app.client.conversations_replies(
        channel=channel,
        ts=thread_ts,
    )

    if replies is not None:
        reply_messages = replies.get("messages")
        reply_users = reply_messages[0].get("reply_users")
        if reply_users is not None and bot_user_id in reply_users:
            chat_history: [Chat] = [
                Chat(
                    role="assistant"
                    if reply.get("user") == bot_user_id or reply.get("bot_id")
                    else "user",
                    content=reply.get("text"),
                )
                for reply in sorted(reply_messages, key=lambda x: x["ts"])
            ]
            pub_command(
                channel=channel,
                thread_ts=thread_ts,
                chat_history=chat_history,
            )


def handle_share(message) -> None:
    """シェアチャンネルにスクレイピング可能なURLの投稿があった場合には処理対象とする"""
    text: str = message.get("text")
    if slack_link_utils.is_contains_url(text):
        url: str = slack_link_utils.extract_and_remove_tracking_url(text)
        if scraping_utils.is_allow_scraping(url):
            pub_command(
                channel=message.get("channel"),
                thread_ts=message.get("ts"),
                chat_history=[Chat(content=url)],
            )


def pub_command(
    command: str = None,
    channel: str = None,
    thread_ts: str = None,
    chat_history: [Chat] = None,
) -> None:
    """該当メッセージにスレッドリプライを行い、そのリプライを後続で処理対象とする"""
    gcp_project_id: str = SECRETS.get("GCP_PROJECT_ID")
    if gcp_project_id is None:
        raise ValueError("GCP_PROJECT_ID environment variable must be set.")

    logger.debug(
        "command: %s, channel: %s, thread_ts: %s\nchat_history: %s",
        command,
        channel,
        thread_ts,
        chat_history,
    )
    if thread_ts is None or channel is None:
        raise ValueError("thread_ts and channel must be set.")
    if chat_history is None or len(chat_history) == 0:
        raise ValueError("chat_history must be set.")

    prosessing_message: str = "Processing."
    res = app.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=prosessing_message,
    )
    if res.get("ok") is not True:
        raise ValueError("Failed to post message.")

    publisher: pubsub_v1.PublisherClient = pubsub_v1.PublisherClient()
    publisher.publish(
        publisher.topic_path(gcp_project_id, "slack-ai-chat"),
        data=json.dumps(
            {
                "context": {
                    "command": command,
                    "channel": channel,
                    "ts": res.get("ts"),
                    "thread_ts": thread_ts,
                    "processing_message": prosessing_message,
                },
                "chat_history": [chat._asdict() for chat in chat_history],
            }
        ).encode("utf-8"),
    )


@functions_framework.http
def main(request: flask.Request):
    """Functionsのエントリーポイント"""
    return slack_gcf_handler.handle(request, app)
