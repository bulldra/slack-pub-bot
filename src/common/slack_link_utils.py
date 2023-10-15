"""
Slackのリンクを扱うためのユーティリティ
"""
import collections
import html
import re
import urllib

import requests

_URL_PATTERN: str = r"https?://[a-zA-Z0-9_/:%#\$&;\?\(\)~\.=\+\-]+[^\s\|\>]+"


def build_link(url: str, title: str) -> str:
    """Slackのリンクを生成する"""
    if url is None or url == "":
        return ""
    escaped_url: str = html.escape(url)

    if title is None or title == "":
        return f"<{escaped_url}>"
    else:
        title = re.sub(r"\n", " ", title).strip()
        return f"<{escaped_url}|{title}>"


def extract_and_remove_tracking_url(text: str) -> str:
    """リンクを抽出してトラッキングURLを除去する"""
    if text is None or not is_contains_url(text):
        raise ValueError("URLが見つかりませんでした。")

    url: str = extract_url(text)
    url = redirect_url(url)
    url = canonicalize_url(url)
    return remove_tracking_query(url)


def is_contains_url(text: str) -> bool:
    """URLが含まれているかどうかの判定"""
    links: list[str] = re.findall(_URL_PATTERN, text or "")
    return len(links) > 0


def is_only_url(text: str) -> bool:
    """
    URLのみかどうかの判定
    Slackの記法に従うため<>で囲まれている場合は除去する
    """
    if is_contains_url(text):
        text = re.sub(r"<([^|>]+).*>$", "\\1", text)
        return parse_url(text) == extract_url(text)
    else:
        return False


def parse_url(url: str) -> str:
    """URLをパースする"""
    url_obj: urllib.parse.ParseResult = urllib.parse.urlparse(url)
    path: str = urllib.parse.quote(url_obj.path, safe="=&%/")
    if url_obj.query is not None and url_obj.query != "":
        query: str = urllib.parse.unquote(url_obj.query)
        path += f"?{query}"
    if url_obj.fragment is not None and url_obj.fragment != "":
        path += f"#{url_obj.fragment}"
    print(f"{url_obj.scheme}://{url_obj.netloc}{path}")
    return f"{url_obj.scheme}://{url_obj.netloc}{path}"


def extract_url(text: str) -> str:
    """URLを抽出する"""
    links: list[str] = re.findall(_URL_PATTERN, text or "")
    if len(links) == 0:
        raise ValueError("URLが見つかりませんでした。")
    return parse_url(links[0])


def redirect_url(url: str) -> str:
    """URLをリダイレクトする"""

    if url is None or url == "":
        raise ValueError("URLが見つかりませんでした。")

    Redirect = collections.namedtuple("Redirect", ("url", "param"))
    redirect_urls: list[Redirect] = [
        Redirect(url="https://www.google.com/url", param="url"),
    ]

    url_obj: urllib.parse.ParseResult = urllib.parse.urlparse(url)
    path = f"{url_obj.scheme}://{url_obj.netloc}{url_obj.path}"
    canonical_url: str = url

    for redirect in redirect_urls:
        if path == redirect.url:
            query_dict: dict = urllib.parse.parse_qs(url_obj.query)
            if redirect.param in query_dict:
                canonical_url = query_dict[redirect.param][0]
                break
    return canonical_url


def canonicalize_url(url: str) -> str:
    """URLを正規化する"""

    if url is None or url == "":
        raise ValueError("URLが見つかりませんでした。")
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
    """トラッキングクエリを除去する"""
    if url is None:
        raise ValueError("URLが見つかりませんでした。")
    tracking_param: list[str] = [
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
        raise ValueError("URL形式が不正です")
    query_dict: dict = urllib.parse.parse_qs(url_obj.query)
    new_query: dict = {k: v for k, v in query_dict.items() if k not in tracking_param}
    url_obj = url_obj._replace(
        query=urllib.parse.urlencode(new_query, doseq=True),
        fragment="",
    )
    return urllib.parse.urlunparse(url_obj)
