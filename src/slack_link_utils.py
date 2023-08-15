"""
Slackのリンクを扱うためのユーティリティ
"""
import os
import re
import urllib

import requests
from bs4 import BeautifulSoup


def extract_and_remove_tracking_url(text: str) -> str:
    """
    リンクを抽出してトラッキングURLを除去する
    """
    url: str = extract_url(text)
    url: str = canonicalize_url(url)
    return remove_tracking_query(url)


def is_contains_url(text: str) -> bool:
    """
    URLが含まれているかどうかの判定
    """
    return extract_url(text) is not None


def is_only_url(text: str) -> bool:
    """
    URLのみかどうかの判定
    Slackの記法に従うため<>で囲まれている場合は除去する
    """
    text = re.sub("<(.+?)>", "\\1", text).strip()
    return text == extract_url(text)


def extract_url(text: str) -> str:
    """
    URLを抽出する
    """
    links: [str] = re.findall(
        r"https?://[a-zA-Z0-9_/:%#\$&\?\(\)~\.=\+\-]+", text or ""
    )
    if len(links) == 0:
        return None
    else:
        return links[0]


def canonicalize_url(url: str) -> str:
    """
    URLを正規化する
    """
    if url is None or url == "":
        return None
    canonical_url: str = url
    try:
        with requests.get(canonical_url, stream=True, timeout=(1.0, 2.0)) as res:
            if res.status_code == 200:
                canonical_url = res.url
            else:
                raise requests.exceptions.RequestException
    except requests.exceptions.RequestException:
        pass
    return canonical_url


def remove_tracking_query(url: str) -> str:
    """
    トラッキングクエリを除去する
    """
    if url is None:
        return None
    tracking_param: [str] = [
        "utm_medium",
        "utm_source",
        "utm_campaign",
        "n_cid",
        "gclid",
        "fbclid",
        "yclid",
        "msclkid",
    ]
    url_obj: urllib.parse.ParseResult = urllib.parse.urlparse(url)
    if url_obj.netloc == b"" or url_obj.netloc == "":
        return None
    query_dict: dict = urllib.parse.parse_qs(url_obj.query)
    new_query: dict = {k: v for k, v in query_dict.items() if k not in tracking_param}
    url_obj = url_obj._replace(
        query=urllib.parse.urlencode(new_query, doseq=True),
        fragment="",
    )
    return urllib.parse.urlunparse(url_obj)


def is_allow_scraping(url: str):
    """
    スクレイピングできるかどうかの判定
    """

    blacklist_domain: [str] = [
        "twitter.com",
        "speakerdeck.com",
        "youtube.com",
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
    """
    スクレイピングの実施
    """

    try:
        res = requests.get(url, timeout=(1.0, 2.0))
    except requests.exceptions.RequestException:
        return None, None

    soup = BeautifulSoup(res.content, "html.parser")
    title = url

    if soup.title is not None and soup.title.string is not None:
        title = re.sub(r"\n", " ", soup.title.string.strip())

    for script in soup(
        [
            "script",
            "style",
            "link",
            "header",
            "footer",
            "nav",
            "iframe",
            "aside",
            "form",
            "button",
        ]
    ):
        script.decompose()
    text: str = "\n".join([line for line in soup.stripped_strings])
    return (title, text)
