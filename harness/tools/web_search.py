import os

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from harness.tools.registry import ToolDefinition


async def _tavily(args: dict) -> str:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "[web_search] 未配置 TAVILY_API_KEY，请在 .env 中设置"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": args["query"],
                "max_results": args.get("max_results", 5),
                "include_answer": True,
            },
        )
    if not response.is_success:
        return f"[web_search] 请求失败: HTTP {response.status_code}"
    data = response.json()
    lines = [f"## AI 摘要\n{data['answer']}\n"] if data.get("answer") else []
    for result in data.get("results", []):
        lines.extend(
            [f"### {result['title']}", result["url"], result.get("content") or result.get("snippet") or "", ""]
        )
    return "\n".join(lines) or "没有找到相关结果"


async def _serper(args: dict) -> str:
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return "[web_search] 未配置 SERPER_API_KEY，请在 .env 中设置"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key},
            json={"q": args["query"], "num": args.get("max_results", 5)},
        )
    if not response.is_success:
        return f"[web_search] 请求失败: HTTP {response.status_code}"
    data = response.json()
    lines: list[str] = []
    if data.get("knowledgeGraph"):
        graph = data["knowledgeGraph"]
        lines.extend([f"## {graph['title']}", graph.get("description", ""), ""])
    for result in data.get("organic", [])[: args.get("max_results", 5)]:
        lines.extend([f"### {result['title']}", result["link"], result.get("snippet", ""), ""])
    return "\n".join(lines) or "没有找到相关结果"


async def _fetch(args: dict) -> str:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(
                args["url"],
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; AgentHarness/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
        if not response.is_success:
            return f"抓取失败: HTTP {response.status_code}"
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup.select("script,style,nav,footer,header,iframe"):
            element.decompose()
        return markdownify(str(soup), heading_style="ATX")
    except Exception as error:
        return f"抓取失败: {error}"


SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索关键词"},
        "max_results": {"type": "number", "description": "返回结果数量，默认 5"},
    },
    "required": ["query"],
}
tavily_search_tool = ToolDefinition(
    "web_search", "搜索互联网获取最新信息。返回相关网页的标题、链接和内容摘要", SEARCH_SCHEMA, _tavily, True, True, 3000
)
serper_search_tool = ToolDefinition(
    "web_search",
    "搜索互联网获取最新信息。返回 Google 搜索结果的标题、链接和摘要",
    SEARCH_SCHEMA,
    _serper,
    True,
    True,
    3000,
)
web_fetch_tool = ToolDefinition(
    "web_fetch",
    "抓取指定 URL 的网页内容，转换为 Markdown 格式。搭配 web_search 使用——先搜索拿到链接，再用这个工具读取详细内容",
    {"type": "object", "properties": {"url": {"type": "string", "description": "完整 URL"}}, "required": ["url"]},
    _fetch,
    True,
    True,
    3000,
)


def pick_search_tool() -> ToolDefinition:
    return serper_search_tool if not os.getenv("TAVILY_API_KEY") and os.getenv("SERPER_API_KEY") else tavily_search_tool
