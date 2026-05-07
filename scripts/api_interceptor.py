"""API 拦截器：监听网络请求，捕获圈子相关的 API 响应。"""

import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, Callable


# 圈子相关的 API 路径模式（基于实际抓包发现的 URL）
API_PATTERNS = {
    "feed_list": re.compile(r"get_feeds_list|feedList|feed_list", re.IGNORECASE),
    "feed_detail": re.compile(r"get_feeds_detail|feedDetail|feed_detail", re.IGNORECASE),
    "comment_list": re.compile(r"get_comment|commentList|comment_list", re.IGNORECASE),
    "like_list": re.compile(r"get_like|likeList|like_list", re.IGNORECASE),
    "play_url": re.compile(r"getPlayUrl|play_url|xe\.material-center\.play", re.IGNORECASE),
    "circle_info": re.compile(r"community_user/info|communityInfo|my_community", re.IGNORECASE),
    "circle_list": re.compile(r"communityList|community_list", re.IGNORECASE),
    "user_info": re.compile(r"community_user/info|userInfo", re.IGNORECASE),
    # 课程相关 API
    "course_list": re.compile(r"get_list_by_condition|courseList|course_list|big_column|xe\.course", re.IGNORECASE),
    "course_detail": re.compile(r"get_course_detail|courseDetail|course_detail|get_material", re.IGNORECASE),
    "course_outline": re.compile(r"get_outline|outlineList|outline_list|chapter_list", re.IGNORECASE),
    "video_play": re.compile(r"get_video_play_url|video_play|player_url|live/detail", re.IGNORECASE),
}


@dataclass
class CapturedResponse:
    """捕获的 API 响应。"""
    url: str
    api_type: str
    status: int
    body: dict | list | None = None
    timestamp: float = field(default_factory=time.time)


class APIInterceptor:
    """监听浏览器网络请求，捕获圈子 API 的结构化数据。"""

    def __init__(self, discover_mode: bool = False):
        self.discover_mode = discover_mode
        self.captured: dict[str, list[CapturedResponse]] = defaultdict(list)
        self.all_requests: list[dict] = []  # 发现模式下记录所有请求
        self._handlers: list[Callable] = []

    def attach(self, page):
        """将拦截器挂载到 Playwright Page 上。"""
        page.on("response", self._on_response)
        print("  API 拦截器已挂载")

    def detach(self, page):
        """从 Page 上卸载拦截器。"""
        # Playwright 不支持直接移除 listener，但不再有副作用
        print("  API 拦截器已卸载")

    def _on_response(self, response):
        """处理网络响应。"""
        url = response.url
        status = response.status

        # 发现模式：记录所有请求
        if self.discover_mode:
            self.all_requests.append({
                "url": url,
                "status": status,
                "method": response.request.method,
                "timestamp": time.time(),
            })

        # 只处理 JSON 响应
        content_type = response.headers.get("content-type", "")
        is_json = "json" in content_type.lower()
        # 也检查 URL 是否是小鹅通 API（有些响应没有 content-type 但确实是 JSON）
        is_xiaoe_api = "xiaoe" in url.lower() or "xiaoeknow" in url.lower()

        if not is_json and not is_xiaoe_api:
            return

        # 匹配 API 模式
        api_type = self._match_api(url)
        if api_type is None:
            return

        # 尝试解析 JSON
        try:
            body = response.json()
        except Exception:
            body = None

        captured = CapturedResponse(
            url=url,
            api_type=api_type,
            status=status,
            body=body,
        )
        self.captured[api_type].append(captured)

    def _match_api(self, url: str) -> Optional[str]:
        """匹配 URL 到 API 类型。"""
        for api_type, pattern in API_PATTERNS.items():
            if pattern.search(url):
                return api_type
        return None

    # ---- 数据提取方法 ----

    def get_feed_list_data(self) -> list[dict]:
        """获取所有捕获的动态列表数据。"""
        results = []
        for resp in self.captured.get("feed_list", []):
            if resp.body and isinstance(resp.body, dict):
                data = resp.body.get("data", resp.body)
                # 尝试提取列表
                items = self._extract_list(data)
                results.extend(items)
        return results

    def get_feed_detail_data(self) -> list[dict]:
        """获取所有捕获的动态详情数据。"""
        results = []
        for resp in self.captured.get("feed_detail", []):
            if resp.body and isinstance(resp.body, dict):
                data = resp.body.get("data", resp.body)
                results.append(data)
        return results

    def get_comment_data(self) -> list[dict]:
        """获取所有捕获的评论数据。"""
        results = []
        for resp in self.captured.get("comment_list", []):
            if resp.body and isinstance(resp.body, dict):
                data = resp.body.get("data", resp.body)
                items = self._extract_list(data)
                results.extend(items)
        return results

    def get_play_url_data(self) -> list[dict]:
        """获取所有捕获的视频播放地址。"""
        results = []
        for resp in self.captured.get("play_url", []):
            if resp.body and isinstance(resp.body, dict):
                data = resp.body.get("data", resp.body)
                results.append(data)
        return results

    def get_circle_info(self) -> Optional[dict]:
        """获取圈子信息。"""
        for resp in self.captured.get("circle_info", []):
            if resp.body and isinstance(resp.body, dict):
                return resp.body.get("data", resp.body)
        return None

    def _extract_list(self, data: dict) -> list:
        """从 API 响应中提取列表数据。

        尝试常见的字段名：list, items, feeds, data, records
        """
        list_keys = ["list", "items", "feeds", "data", "records", "feed_list"]
        for key in list_keys:
            if key in data and isinstance(data[key], list):
                return data[key]
        return []

    # ---- 发现模式 ----

    def get_discovery_report(self) -> str:
        """生成 API 发现报告（发现模式专用）。"""
        if not self.all_requests:
            return "未捕获到任何网络请求"

        lines = ["=" * 60, "小鹅通圈子 API 发现报告", "=" * 60, ""]

        # 按域名分组
        by_domain = defaultdict(list)
        for req in self.all_requests:
            # 提取域名+路径
            url = req["url"]
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc
                path = parsed.path
            except Exception:
                domain = "unknown"
                path = url
            by_domain[domain].append({
                **req,
                "path": path,
            })

        for domain, reqs in sorted(by_domain.items()):
            # 过滤掉静态资源
            if any(ext in domain for ext in [".css", ".js", ".png", ".jpg", ".woff", ".ico"]):
                continue
            if domain in ["cdn.jsdelivr.net", "unpkg.com", "fonts.googleapis.com"]:
                continue

            lines.append(f"\n## {domain}")

            # 去重路径
            seen_paths = set()
            for req in sorted(reqs, key=lambda x: x["path"]):
                path = req["path"]
                if path in seen_paths:
                    continue
                seen_paths.add(path)

                # 过滤静态资源路径
                if any(ext in path for ext in [".js", ".css", ".png", ".jpg", ".svg", ".woff", ".ico", ".ttf"]):
                    continue

                method = req.get("method", "?")
                status = req.get("status", "?")
                api_type = self._match_api(req["url"])
                marker = f" ← {api_type}" if api_type else ""
                lines.append(f"  [{method}] {status} {path}{marker}")

        # 已识别的 API 摘要
        lines.append("\n" + "=" * 60)
        lines.append("已识别的 API 类型摘要")
        lines.append("=" * 60)
        for api_type, responses in self.captured.items():
            lines.append(f"\n### {api_type} ({len(responses)} 个响应)")
            if responses:
                resp = responses[0]
                lines.append(f"  URL: {resp.url}")
                if resp.body:
                    lines.append(f"  数据结构: {self._summarize_structure(resp.body)}")

        return "\n".join(lines)

    def _summarize_structure(self, data, depth=0, max_depth=2) -> str:
        """递归生成数据结构摘要。"""
        if depth > max_depth:
            return "..."
        if isinstance(data, dict):
            keys = list(data.keys())[:10]
            items = ", ".join(f"{k}: {type(data[k]).__name__}" for k in keys)
            return "{" + items + ("..." if len(data) > 10 else "") + "}"
        elif isinstance(data, list):
            if not data:
                return "[]"
            return f"[{self._summarize_structure(data[0], depth+1)}, ...({len(data)} items)]"
        else:
            return type(data).__name__

    def save_discovery_report(self, path: str):
        """保存发现报告到文件。"""
        report = self.get_discovery_report()
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"  API 发现报告已保存到 {path}")

    def clear(self):
        """清空捕获的数据。"""
        self.captured.clear()
        self.all_requests.clear()
