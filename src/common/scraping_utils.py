"""スクレイピング関連のユーティリティ"""
import os
import re
import urllib
from collections import namedtuple

import requests
from bs4 import BeautifulSoup

Site = namedtuple("Site", ("url", "title", "heading", "content"))


def is_allow_scraping(url: str):
    """スクレイピングできるかどうかの判定"""

    blacklist_domain: list[str] = [
        "twitter.com",
        "speakerdeck.com",
        "www.youtube.com",
    ]
    black_list_ext: list[str] = [
        ".pdf",
        ".jpg",
        ".png",
        ".gif",
        ".jpeg",
        ".zip",
    ]
    url_obj: urllib.parse.ParseResult = urllib.parse.urlparse(url)

    if url_obj.netloc == b"" or url_obj.netloc == "":
        return False
    elif url_obj.netloc in blacklist_domain:
        return False
    elif os.path.splitext(url_obj.path)[1] in black_list_ext:
        return False
    else:
        return True


def scraping(url: str) -> Site:
    """スクレイピングの実施"""
    res = requests.get(url, timeout=(3.0, 8.0))
    if res.status_code != 200:
        raise ValueError(f"status code is not 200. status code:{res.status_code}")

    soup = BeautifulSoup(res.content, "html.parser")
    title = url
    if soup.title is not None and soup.title.string is not None:
        title = re.sub(r"\n", " ", soup.title.string.strip())

    for script in soup(
        [
            "script",
            "style",
            "header",
            "footer",
            "nav",
            "iframe",
            "form",
            "button",
            # "link" 閉じ忘れが多いため除外
        ]
    ):
        script.decompose()

    for cr_tag in soup(
        [
            "br",
            "div",
            "table",
            "p",
            "li",
            "tr",
            "td",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        ]
    ):
        cr_tag.insert_after("\n")

    heading: list[str] = []
    for cr_tag in soup(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        ]
    ):
        heading.append(cr_tag.get_text().strip())

    content: str = re.sub(r"[\n\s]+", "\n", soup.get_text())

    return Site(url, title, heading, content)
