"""スクレイピング関連のユーティリティ"""
import os
import re
import urllib
from collections import namedtuple

import requests
from bs4 import BeautifulSoup

Site = namedtuple(
    "Site", ("url", "title", "description", "keywords", "heading", "content")
)


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


def scraping(url: str) -> Site:
    """スクレイピングの実施"""
    res = None
    try:
        res = requests.get(url, timeout=(3.0, 8.0))
    except requests.exceptions.TooManyRedirects:
        return None
    except requests.exceptions.RequestException:
        return None

    soup = BeautifulSoup(res.content, "html.parser")
    title = url
    if soup.title is not None and soup.title.string is not None:
        title = re.sub(r"\n", " ", soup.title.string.strip())

    description: str = None
    meta_discription = soup.find("meta", attrs={"name": "description"})
    if meta_discription and meta_discription.get("content"):
        description = meta_discription.get("content")

    keywords: [str] = None
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

    heading: [str] = []
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

    return Site(url, title, description, keywords, heading, content)
