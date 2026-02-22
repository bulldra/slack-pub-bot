import os

import pytest

from module import slack_assistant


def test_handle_assistant_start_with_conf(pytestconfig: pytest.Config):
    os.chdir(pytestconfig.getini("pythonpath")[0])
    assist = slack_assistant.SlackAssistant()
    greeting, prompts = assist.get_assistant_greeting_and_prompts()
    print(f"greeting: {greeting}, prompts: {prompts}")
