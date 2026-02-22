import json
import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo


class SlackAssistant:
    def __init__(self, config_path="./conf/assistant.json"):
        self._logger = logging.getLogger(__name__)
        self._logger.info(
            "SlackAssistant initialized with config path: %s", config_path
        )
        self._conf = {"greetings": {}, "suggested_prompts": []}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._conf = json.load(f)
        except FileNotFoundError:
            self._logger.warning(
                "Configuration file not found at %s, using default", config_path
            )
        except json.JSONDecodeError:
            self._logger.error("Invalid JSON in configuration file")

    def get_assistant_greeting_and_prompts(self) -> tuple[str, list[str]]:
        now: datetime = datetime.now(ZoneInfo("Asia/Tokyo"))
        weekday: str = now.strftime("%A")
        hour_range = f"{(now.hour // 3) * 3}-{((now.hour // 3) + 1) * 3}"
        greetings: dict[str, dict] = self._conf.get("greetings", {})
        day_greetings: dict[str, list[str]] = greetings.get(weekday, {})
        target_greeting_list: list[str] = day_greetings.get(hour_range, [])

        greeting: str = "はいはい〜。"
        if target_greeting_list:
            greeting = random.choice(target_greeting_list)

        prompts: list[str] = self._conf.get("suggested_prompts", [])
        if prompts:
            prompts = random.sample(prompts, min(4, len(prompts)))
        else:
            self._logger.debug("No suggested prompts available")

        return (greeting, prompts)
