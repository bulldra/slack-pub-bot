import os

import pytest

from module import slack_assistant


def test_handle_assistant_start_with_conf(pytestconfig: pytest.Config):
    os.chdir(pytestconfig.getini("pythonpath")[0])
    greeting, prompts = slack_assistant.get_assistant_greeting_and_prompts()
    print(f"greeting: {greeting}, prompts: {prompts}")
