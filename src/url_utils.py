import re
import urllib

import requests


def extract_url(text: str) -> str:
    if text is None:
        return None
    links: [str] = re.findall(r"https?://[\w/:%#\$&\?\(\)~\.=\+\-]+", text)
    if len(links) == 0:
        return None
    else:
        canonical_url: str = links[0]
        try:
            with requests.get(canonical_url, stream=True) as res:
                if res.status_code != 200:
                    raise requests.exceptions.RequestException
                else:
                    canonical_url = res.url
        except requests.exceptions.RequestException:
            pass
        return remove_tracking_query(canonical_url)


def remove_tracking_query(url: str) -> str:
    url_obj: urllib.parse.ParseResult = urllib.parse.urlparse(url)
    query_dict: dict = urllib.parse.parse_qs(url_obj.query)

    tracking_param: [str] = [
        "utm_medium",
        "utm_source",
        "utm_campaign",
        "gclid",
        "n_cid",
        "fbclid",
        "yclid",
        "msclkid",
        "mc_eid",
        "mc_cid",
        "mc_sub",
    ]

    new_query: dict = {k: v for k, v in query_dict.items() if k not in tracking_param}
    query_str: str = urllib.parse.urlencode(new_query, doseq=True)
    urlobj = url_obj._replace(query=query_str)
    return urllib.parse.urlunparse(urlobj)
