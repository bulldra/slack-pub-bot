"""
Slackのリンクを扱うためのユーティリティ
"""
import collections
import html
import re
import urllib

import requests


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
    url: str = extract_url(text)
    url = redirect_url(url)
    url = canonicalize_url(url)
    return remove_tracking_query(url)


def is_contains_url(text: str) -> bool:
    """URLが含まれているかどうかの判定"""
    return extract_url(text) is not None


def is_only_url(text: str) -> bool:
    """
    URLのみかどうかの判定
    Slackの記法に従うため<>で囲まれている場合は除去する
    """
    if text is None:
        return False
    text = re.sub(r"<([^|>]+).*>$", "\\1", text)
    return html.unescape(text) == extract_url(text)


def extract_url(text: str) -> str:
    """URLを抽出する"""
    links: [str] = re.findall(
        r"https?://[a-zA-Z0-9_/:%#\$&;\?\(\)~\.=\+\-]+", text or ""
    )
    if len(links) == 0:
        return None
    else:
        result: str = html.unescape(links[0])
        return result


def redirect_url(url: str) -> str:
    """URLをリダイレクトする"""

    if url is None or url == "":
        return None

    Redirect = collections.namedtuple("Redirect", ("url", "param"))
    redirect_urls: [Redirect] = [
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
    """トラッキングクエリを除去する"""
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


def convert_mrkdwn(markdown_text: str) -> str:
    """convert markdown to mrkdwn"""

    # コードブロックエスケープ
    replacement = "!!!CODE_BLOCK!!!"
    code_blocks = re.findall(
        r"[^`]```([^`].+?[^`])```[^`]",
        markdown_text,
        flags=re.DOTALL,
    )
    markdown_text = re.sub(
        r"([^`])```[^`].+?[^`]```([^`])",
        rf"\1{replacement}\2",
        markdown_text,
        flags=re.DOTALL,
    )

    # リスト・数字リストも・に変換
    markdown_text = re.sub(
        r"^\s*[\*\+-]\s+(.*)\n",
        r"• \1\n",
        markdown_text,
        flags=re.MULTILINE,
    )

    # イタリック
    markdown_text = re.sub(
        r"([^\*])\*([^\*].+?[^\*])\*([^\*])",
        r"\1_\2_\3",
        markdown_text,
    )

    # 太字
    markdown_text = re.sub(
        r"\*\*(.+?)\*\*",
        r"*\1*",
        markdown_text,
    )

    # 見出し
    markdown_text = re.sub(
        r"^#{1,6}\s*(.+?)\n",
        r"*\1*\n",
        markdown_text,
        flags=re.MULTILINE,
    )

    # リンク
    markdown_text = re.sub(r"!?\[\]\((.+?)\)", r"<\1>", markdown_text)
    markdown_text = re.sub(r"!?\[(.+?)\]\((.+?)\)", r"<\2|\1>", markdown_text)

    for code in code_blocks:
        markdown_text = re.sub(replacement, f"```{code}```\n", markdown_text, count=1)
    return markdown_text
