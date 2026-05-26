from ddgs import DDGS
from .logger import log_message


def search_web(query: str) -> str | None:
    """Search the web via DuckDuckGo, return the best text snippet."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if results:
                for r in results:
                    body = r.get("body", "")
                    if body:
                        return body
    except Exception as e:
        log_message(f"Ошибка поиска: {e}", "search.py")

    return None
