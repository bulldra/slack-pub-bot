"""スクレイピング関連おユーティリティ"""
import os
import re
import urllib
from collections import namedtuple

import requests
from bs4 import BeautifulSoup

Site = namedtuple("Site", ("url", "title", "description", "keywords", "content"))


def is_allow_scraping(url: str):
    """スクレイピングできるかどうかの判定"""

    blacklist_domain: [str] = [
        "twitter.com",
        "speakerdeck.com",
        "www.youtube.com",
    ]
    black_list_ext: [str] = [
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


def scraping(url: str) -> (str, str):
    """スクレイピングの実施"""

    res = requests.get(url, timeout=(3.0, 8.0))
    soup = BeautifulSoup(res.content, "html.parser")
    title = url
    if soup.title is not None and soup.title.string is not None:
        title = re.sub(r"\n", " ", soup.title.string.strip())

    description = ""
    meta_discription = soup.find("meta", attrs={"name": "description"})
    if meta_discription and meta_discription.get("content"):
        description = meta_discription.get("content")

    keywords = []
    meta_keywords = soup.find("meta", attrs={"name": "keywords"})
    if meta_keywords and meta_keywords.get("content"):
        keywords = meta_keywords.get("content").split(",")

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

    content: str = "".join([line for line in soup.stripped_strings])
    return Site(url, title, description, keywords, content)
