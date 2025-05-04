import json
import random
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo


def get_assistant_greeting_and_prompts() -> tuple[str, List[str]]:
    greeting: str = "はいはい〜。"
    try:
        with open("./conf/assistant.json", "r", encoding="utf-8") as f:
            conf = json.load(f)
    except FileNotFoundError:
        conf = {}

    greetings = conf.get("greetings", {})

    tz = ZoneInfo("Asia/Tokyo")
    now = datetime.now(tz) if tz else datetime.now()
    weekday = now.strftime("%A")
    hour = now.hour
    hour_range = f"{(hour // 3) * 3}-{((hour // 3) + 1) * 3}"
    day_greetings = greetings.get(weekday, {})
    greeting_list = day_greetings.get(hour_range, [])

    if greeting_list:
        greeting = random.choice(greeting_list)

    prompts: List[str] = conf.get("suggested_prompts", [])
    print(prompts)
    if prompts:
        prompts = random.sample(prompts, 4)
    return greeting, prompts
