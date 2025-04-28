import json
import logging
import os
import re

import flask
import functions_framework
import google.cloud.logging
import google.cloud.pubsub_v1
import slack_bolt
import slack_sdk.web

import common.slack_gcf_handler as slack_gcf_handler
import common.slack_link_utils as slack_link_utils

SECRETS: dict = json.loads(str(os.getenv("SECRETS")))

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
    pass


@app.message()
def handle_message(context, message) -> None:
    if message.get("thread_ts") is not None:
        handle_thread(context.bot_user_id, message)
    elif context.channel_id == str(SECRETS["SHARE_CHANNEL_ID"]):
        handle_share(message)


@app.event("message")
def handle_file_share(context, event) -> None:
    if event.get("subtype") == "file_share":
        if context.channel_id == str(SECRETS["MAIL_CHANNEL_ID"]):
            handle_mail(event)


@app.event("app_mention")
def mention(context, event) -> None:
    text: str = event.get("text")
    if text is not None:
        text = text.replace(f"<@{context.bot_user_id}>", "").strip()
        pub_command(
            channel=event.get("channel"),
            thread_ts=event.get("ts"),
            chat_history=[{"role": "user", "content": text}],
        )


@app.command("/gpt")
@app.command("/summazise")
@app.command("/idea")
def handle_command(ack, command, say) -> None:
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
        chat_history=[{"role": "user", "content": text}],
    )


@app.action(re.compile(r"^button-.+$"))
def handle_button_action(ack, body) -> None:
    ack()
    logger.debug("button action: %s", str(body))
    message_text: str = body["message"]["text"]
    action: str = body["actions"][0].get("value")
    pub_command(
        channel=body["channel"]["id"],
        thread_ts=body["message"]["ts"],
        chat_history=[
            {"role": "assistant", "content": message_text},
            {"role": "user", "content": action},
        ],
    )


def handle_thread(bot_user_id, message) -> None:
    channel: str = message.get("channel")
    thread_ts: str = message.get("thread_ts")
    replies: slack_sdk.web.SlackResponse = app.client.conversations_replies(
        channel=channel,
        ts=thread_ts,
    )
    if replies is not None:
        reply_messages: list[dict] = replies["messages"]
        reply_users = reply_messages[0].get("reply_users")
        if reply_users is not None and bot_user_id in reply_users:
            chat_history: list[dict[str, str]] = []
            for reply in sorted(reply_messages, key=lambda x: x["ts"]):
                role: str = "user"
                if reply.get("user") == bot_user_id or reply.get("bot_id"):
                    role = "assistant"
                content: str = reply["text"]
                chat_history.append({"role": role, "content": content})
            pub_command(channel=channel, thread_ts=thread_ts, chat_history=chat_history)


def handle_share(message) -> None:
    text: str = message.get("text")
    if slack_link_utils.is_contains_url(text):
        url: str = slack_link_utils.extract_url(text)
        pub_command(
            channel=message.get("channel"),
            thread_ts=message.get("ts"),
            chat_history=[{"role": "user", "content": url}],
        )


def handle_mail(event) -> None:
    if "files" in event:
        mail = event.get("files")[0]
        text = json.dumps(mail)

        pub_command(
            channel=event.get("channel"),
            thread_ts=event.get("ts"),
            command="/mail",
            chat_history=[{"role": "user", "content": text}],
        )


def pub_command(
    command: str | None = None,
    channel: str | None = None,
    thread_ts: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> None:
    gcp_project_id: str = str(SECRETS.get("GCP_PROJECT_ID"))
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

    prosessing_message: str = "思考中."
    blocks: list = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": prosessing_message,
            },
        }
    ]
    res: slack_sdk.web.SlackResponse = app.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        blocks=blocks,
    )
    if res.get("ok") is not True:
        raise ValueError("Failed to post message.")

    publisher: google.cloud.pubsub_v1.PublisherClient = (
        google.cloud.pubsub_v1.PublisherClient()
    )
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
                "chat_history": chat_history,
            }
        ).encode("utf-8"),
    )


@functions_framework.http
def main(request: flask.Request):
    return slack_gcf_handler.handle(request, app)
