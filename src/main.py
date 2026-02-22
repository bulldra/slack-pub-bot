import json
import logging
import os
import re
from typing import Any

import flask
import functions_framework
import google.auth.transport.requests
import google.cloud.logging
import google.cloud.pubsub_v1
import google.oauth2.id_token
import slack_bolt
import slack_sdk.web

import module.slack_assistant as slack_assistant
import module.slack_gcf_handler as slack_gcf_handler
import module.slack_link_utils as slack_link_utils

if os.getenv("SECRETS"):
    SECRETS: dict[str, Any] = json.loads(str(os.getenv("SECRETS")))
else:
    raise ValueError("SECRETS environment variable is not set")
URL_PATTERN: str = r"https?://[a-zA-Z0-9_/:%#\$&;\?\(\)~\.=\+\-]+[^\s\|\>]+"

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


@app.event("reaction_added")
def handle_reaction_added(event: dict[str, Any]):
    logger.info(
        "reaction_added: reaction=%s, channel=%s, ts=%s, user=%s",
        event.get("reaction"),
        event.get("item", {}).get("channel"),
        event.get("item", {}).get("ts"),
        event.get("user"),
    )
    if event["reaction"] != SECRETS.get("REACTION_EMOJI"):
        logger.info(
            "reaction skipped: expected=%s, actual=%s",
            SECRETS.get("REACTION_EMOJI"),
            event["reaction"],
        )
        return

    result: slack_sdk.web.SlackResponse = app.client.conversations_history(
        channel=event["item"]["channel"],
        inclusive=True,
        latest=event["item"]["ts"],
        limit=1,
    )
    message_text: str | None = (
        result["messages"][0].get("text") if result["messages"] else None
    )
    logger.info("reaction target message: %s", message_text)
    if message_text is None:
        logger.info("reaction target message is empty")
        return
    link: str = slack_link_utils.extract_and_remove_tracking_url(message_text)
    logger.info("share_link: %s", link)
    if link is not None:
        share_channel: str = str(SECRETS.get("SHARE_CHANNEL_ID"))
        res: slack_sdk.web.SlackResponse = app.client.chat_postMessage(
            channel=share_channel,
            text=link,
            unfurl_links=True,
        )
        logger.info("reaction shared: link=%s, channel=%s", link, share_channel)
        pub_command(
            channel=share_channel,
            thread_ts=res.get("ts"),
            user_id=event.get("user"),
            chat_history=[{"role": "user", "content": link}],
        )


@app.event({"type": "message", "subtype": "message_changed"})
@app.event({"type": "message", "subtype": "message_deleted"})
def bot_message_change() -> None:
    pass


@app.message()
def handle_message(context, event, message) -> None:
    if message.get("thread_ts") is not None:
        handle_thread(context.bot_user_id, event["user"], message)
    else:
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
    assist = slack_assistant.SlackAssistant()
    greeting, prompts = assist.get_assistant_greeting_and_prompts()
    set_suggested_prompts(prompts=prompts)
    say(greeting)


@assistant.user_message
def handle_assistant_message(message, context):
    handle_thread(context.bot_user_id, message.get("user"), message)


def handle_thread(bot_user_id, user_id, message) -> None:
    channel: str = message.get("channel")
    thread_ts: str = message.get("thread_ts")
    replies: slack_sdk.web.SlackResponse = app.client.conversations_replies(
        channel=channel,
        ts=thread_ts,
    )
    if replies is not None:
        reply_messages: list[dict] = replies["messages"]
        if not reply_messages:
            return
        reply_users = reply_messages[0].get("reply_users")
        if reply_users is not None and bot_user_id in reply_users:
            chat_history: list[dict[str, str]] = []
            for reply in sorted(reply_messages, key=lambda x: x["ts"]):
                role: str = "user"
                if reply.get("user") == bot_user_id or reply.get("bot_id"):
                    role = "assistant"
                content: str = reply["text"]
                user_id = reply.get("user")
                chat_history.append({"role": role, "content": content})
            pub_command(
                channel=channel,
                thread_ts=thread_ts,
                user_id=user_id,
                chat_history=chat_history,
            )


def handle_share(user_id, message) -> None:
    text: str = message.get("text")
    links: list[str] = re.findall(URL_PATTERN, text or "")
    if len(links) > 0:
        pub_command(
            channel=message.get("channel"),
            thread_ts=message.get("ts"),
            user_id=user_id,
            chat_history=[{"role": "user", "content": text}],
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


def _publish_to_pubsub(
    command: str | None = None,
    channel: str | None = None,
    ts: str | None = None,
    user_id: str | None = None,
    thread_ts: str | None = None,
    processing_message: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> None:
    gcp_project_id: str = str(SECRETS.get("GCP_PROJECT_ID"))
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
                    "ts": ts,
                    "user_id": user_id,
                    "thread_ts": thread_ts,
                    "processing_message": processing_message,
                },
                "chat_history": chat_history,
            }
        ).encode("utf-8"),
    )


def pub_command(
    command: str | None = None,
    channel: str | None = None,
    thread_ts: str | None = None,
    user_id: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> None:
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
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": prosessing_message},
        }
    ]
    res: slack_sdk.web.SlackResponse
    if thread_ts is None:
        res = app.client.chat_postMessage(
            channel=channel,
            blocks=blocks,
        )
    else:
        res = app.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            blocks=blocks,
        )
    if res.get("ok") is not True:
        raise ValueError("Failed to post message.")

    _publish_to_pubsub(
        command=command,
        channel=channel,
        ts=res.get("ts"),
        user_id=user_id,
        thread_ts=thread_ts,
        processing_message=prosessing_message,
        chat_history=chat_history,
    )


def _verify_scheduler_token(request: flask.Request) -> bool:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    token = auth_header.split("Bearer ")[1]
    try:
        google.oauth2.id_token.verify_oauth2_token(
            token,
            google.auth.transport.requests.Request(),
        )
        return True
    except Exception:
        return False


def handle_feed_digest(request: flask.Request) -> tuple[str, int]:
    if not _verify_scheduler_token(request):
        logger.warning("Unauthorized feed_digest request")
        return ("Unauthorized", 403)

    logger.info("feed_digest scheduled command received")
    feed_channel: str = str(SECRETS.get("FEED_DIGEST_CHANNEL_ID"))
    processing_message: str = "フィードダイジェストを生成中."
    res: slack_sdk.web.SlackResponse = app.client.chat_postMessage(
        channel=feed_channel,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": processing_message},
            }
        ],
    )
    if res.get("ok") is not True:
        logger.error("Failed to post feed_digest processing message")
        return ("Failed to post message", 500)

    _publish_to_pubsub(
        command="/feed_digest",
        channel=feed_channel,
        ts=res.get("ts"),
        processing_message=processing_message,
        chat_history=[{"role": "user", "content": "/feed_digest"}],
    )
    return ("OK", 200)


@functions_framework.http
def main(request: flask.Request):
    if request.path == "/feed_digest" and request.method == "POST":
        return handle_feed_digest(request)
    return slack_gcf_handler.handle(request, app)
