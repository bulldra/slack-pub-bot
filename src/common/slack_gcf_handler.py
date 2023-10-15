"""
Google Cloud Functions 向け Slack Event Handler
"""
import json

import flask
import slack_bolt
from slack_bolt.adapter.google_cloud_functions import SlackRequestHandler


def handle(request: flask.Request, app: slack_bolt.App):
    """
    main処理
    """
    if request.method != "POST":
        return ("Only POST requests are accepted", 405)
    if request.headers.get("x-slack-retry-num"):
        return ("No need to resend", 200)

    content_type: str = str(request.headers.get("Content-Type"))
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
