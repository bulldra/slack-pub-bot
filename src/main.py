import json
import logging
import os
import re
from typing import List

import flask
import functions_framework
import google.cloud.logging
import google.cloud.pubsub_v1
import slack_bolt
import slack_sdk.web

import module.slack_assistant as slack_assistant
import module.slack_gcf_handler as slack_gcf_handler
import module.slack_link_utils as slack_link_utils

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
assistant: slack_bolt.Assistant = slack_bolt.Assistant()
app.use(assistant)


@app.event({"type": "message", "subtype": "message_changed"})
@app.event({"type": "message", "subtype": "message_deleted"})
def bot_message_change() -> None:
    pass


@app.message()
def handle_message(context, event, message) -> None:
    if message.get("thread_ts") is not None:
        handle_thread(context.bot_user_id, event["user"], message)
    elif context.channel_id == str(SECRETS["SHARE_CHANNEL_ID"]):
        handle_share(event.get("user"), message)


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
            user_id=event.get("user"),
            chat_history=[{"role": "user", "content": text}],
        )


@app.command("/gpt")
@app.command("/summazise")
@app.command("/idea")
def handle_command(ack, command, say, event) -> None:
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
        user_id=event.get("user"),
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
        user_id=body.get("user", {}).get("id"),
        chat_history=[
            {"role": "assistant", "content": message_text},
            {"role": "user", "content": action},
        ],
    )


@assistant.thread_started
def handle_assistant_start(say, set_suggested_prompts):
    greeting, prompts = slack_assistant.get_assistant_greeting_and_prompts()
    say(greeting)
    set_suggested_prompts(prompts=prompts)


@assistant.user_message
def handle_assistant_message(message, context, set_status):
    set_status("is typing...")
    handle_thread(context.bot_user_id, message.get("user"), message)


def handle_thread(bot_user_id, user_id, message) -> None:
    channel: str = message.get("channel")
    thread_ts: str = message.get("thread_ts")
    replies: slack_sdk.web.SlackResponse = app.client.conversations_replies(
        channel=channel,
        ts=thread_ts,
    )
    if replies is not None:
        reply_messages: List[dict] = replies["messages"]
        reply_users = reply_messages[0].get("reply_users")
        if reply_users is not None and bot_user_id in reply_users:
            chat_history: list[dict[str, str]] = []
            for reply in sorted(reply_messages, key=lambda x: x["ts"]):
                role: str = "user"
                if reply.get("user") == bot_user_id or reply.get("bot_id"):
                    role = "assistant"
                content: str = reply["text"]
                user_id = reply.get("user")
                if user_id:
                    chat_history.append({"role": role, "content": content})
                else:
                    chat_history.append({"role": role, "content": content})
            pub_command(
                channel=channel,
                thread_ts=thread_ts,
                user_id=user_id,
                chat_history=chat_history,
            )


def handle_share(user_id, message) -> None:
    text: str = message.get("text")
    if slack_link_utils.is_contains_url(text):
        url: str = slack_link_utils.extract_url(text)
        pub_command(
            channel=message.get("channel"),
            thread_ts=message.get("ts"),
            user_id=user_id,
            chat_history=[{"role": "user", "content": url}],
        )


def handle_mail(event) -> None:
    if "files" in event:
        mail = event.get("files")[0]
        text = json.dumps(mail)

        pub_command(
            channel=event.get("channel"),
            thread_ts=event.get("ts"),
            user_id=event.get("user"),
            command="/mail",
            chat_history=[{"role": "user", "content": text}],
        )


def pub_command(
    command: str | None = None,
    channel: str | None = None,
    thread_ts: str | None = None,
    user_id: str | None = None,
    chat_history: List[dict[str, str]] | None = None,
) -> None:
    secrets_raw: str = str(os.getenv("SECRETS"))
    if not secrets_raw:
        raise RuntimeError("SECRETS 環境変数が設定されていません")
    secrets: dict[str, any] = json.loads(secrets_raw)
    gcp_project_id: str = str(secrets.get("GCP_PROJECT_ID"))
    if gcp_project_id is None:
        raise ValueError("GCP_PROJECT_ID environment variable must be set.")

    logger.debug(
        "command: %s, channel: %s, thread_ts: %s, user_id: %s, \nchat_history: %s",
        command,
        channel,
        thread_ts,
        user_id,
        chat_history,
    )
    if channel is None:
        raise ValueError("channel must be set.")
    if chat_history is None or len(chat_history) == 0:
        raise ValueError("chat_history must be set.")

    prosessing_message: str = "思考中."
    blocks: List = [
        {"type": "section", "text": {"type": "mrkdwn", "text": prosessing_message}}
    ]
    if thread_ts is None:
        res: slack_sdk.web.SlackResponse = app.client.chat_postMessage(
            channel=channel,
            blocks=blocks,
        )
    else:
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
                    "user_id": user_id,
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
