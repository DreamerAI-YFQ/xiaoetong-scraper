"""内容解析器：从 API 响应和 DOM 中提取帖子数据，富文本转 Markdown。"""

import re
from dataclasses import dataclass, field
from typing import Optional
from html.parser import HTMLParser


@dataclass
class PostData:
    """帖子结构化数据。"""
    feeds_id: str = ""
    title: str = ""
    author: str = ""
    author_avatar: str = ""
    created_at: str = ""
    content_html: str = ""
    content_text: str = ""
    content_markdown: str = ""
    images: list[str] = field(default_factory=list)
    video_url: str = ""
    video_m3u8: str = ""
    audio_url: str = ""
    comments: list[dict] = field(default_factory=list)
    likes_count: int = 0
    comments_count: int = 0
    post_type: str = ""       # 图文/视频/音频/问答/打卡等
    community_id: str = ""
    url: str = ""
    is_pinned: bool = False
    is_featured: bool = False


class ContentParser:
    """解析圈子帖子内容。"""

    # 圈子帖子类型映射
    POST_TYPE_MAP = {
        0: "图文",
        1: "视频",
        2: "音频",
        3: "问答",
        4: "直播",
        5: "文件",
        6: "打卡",
        7: "长文章",
        8: "课程",
    }

    def parse_feed_from_api(self, feed_data: dict, community_id: str = "") -> PostData:
        """从 API 响应解析帖子数据。

        由于 API 字段名可能有多种形式，这里做宽松匹配。
        """
        post = PostData(community_id=community_id)

        # 提取 ID
        post.feeds_id = str(feed_data.get("feeds_id") or feed_data.get("feed_id") or feed_data.get("id") or "")

        # 提取标题
        post.title = feed_data.get("title") or feed_data.get("feed_title") or ""

        # 提取作者
        author_data = feed_data.get("user_info") or feed_data.get("author_info") or feed_data.get("user") or {}
        if isinstance(author_data, dict):
            post.author = author_data.get("nick_name") or author_data.get("nickname") or author_data.get("name") or ""
            post.author_avatar = author_data.get("wx_avatar") or author_data.get("avatar") or author_data.get("avatar_url") or ""
        elif isinstance(author_data, str):
            post.author = author_data

        # 提取时间
        post.created_at = self._normalize_time(
            feed_data.get("created_at") or feed_data.get("create_time") or feed_data.get("publish_time") or ""
        )

        # 提取正文
        raw_content = feed_data.get("content") or feed_data.get("text") or feed_data.get("body") or ""
        # content 可能是 dict（如 {"text": "...", "html": "..."}）或 string
        if isinstance(raw_content, dict):
            # 尝试多种字段组合
            html_content = raw_content.get("html", "")
            text_content = raw_content.get("text", "")
            # 如果 html 字段有内容，优先用 html（含图片标签）
            if html_content and isinstance(html_content, str) and len(html_content) > len(text_content):
                post.content_html = html_content
            elif text_content and isinstance(text_content, str):
                post.content_html = text_content
            else:
                # 递归搜索 dict 中最长的字符串字段
                import json
                post.content_html = json.dumps(raw_content, ensure_ascii=False)
        else:
            post.content_html = str(raw_content) if raw_content else ""
        post.content_text = self._html_to_text(post.content_html)
        post.content_markdown = self._html_to_markdown(post.content_html)

        # 提取图片
        post.images = self._extract_images(feed_data)

        # 提取视频
        video_data = feed_data.get("video_info") or feed_data.get("video") or {}
        if isinstance(video_data, dict):
            post.video_url = video_data.get("play_url") or video_data.get("url") or video_data.get("video_url") or ""
        elif isinstance(video_data, str):
            post.video_url = video_data

        # 提取音频
        audio_data = feed_data.get("audio_info") or feed_data.get("audio") or {}
        if isinstance(audio_data, dict):
            post.audio_url = audio_data.get("play_url") or audio_data.get("url") or audio_data.get("audio_url") or ""
        elif isinstance(audio_data, str):
            post.audio_url = audio_data

        # 提取帖子类型
        post_type_val = feed_data.get("type") or feed_data.get("feed_type") or 0
        post.post_type = self.POST_TYPE_MAP.get(post_type_val, f"类型{post_type_val}")

        # 统计
        post.likes_count = int(feed_data.get("like_count") or feed_data.get("likes") or 0)
        post.comments_count = int(feed_data.get("comment_count") or feed_data.get("comments") or 0)

        # 标记
        post.is_pinned = bool(feed_data.get("is_pinned") or feed_data.get("is_top") or False)
        post.is_featured = bool(feed_data.get("is_featured") or feed_data.get("is_essence") or False)

        # 构造 URL
        if community_id and post.feeds_id:
            post.url = f"https://quanzi.xiaoe-tech.com/{community_id}/feed_detail/{post.feeds_id}"

        return post

    def parse_feed_from_dom(self, page, community_id: str = "") -> PostData:
        """从 DOM 解析帖子数据（兜底方案）。"""
        post = PostData(community_id=community_id)

        try:
            # 尝试提取帖子主体内容
            post.title = page.title() or ""

            # 尝试提取正文
            content_el = page.query_selector(".feed-content, .post-content, .content-text, article")
            if content_el:
                post.content_html = content_el.inner_html()
                post.content_text = content_el.inner_text()
                post.content_markdown = self._html_to_markdown(post.content_html)

            # 尝试提取图片
            img_elements = page.query_selector_all(".feed-content img, .post-content img, article img")
            for img in img_elements:
                src = img.get_attribute("src") or ""
                if src and not src.startswith("data:"):
                    post.images.append(src)

            # 尝试提取作者
            author_el = page.query_selector(".author-name, .user-name, .nick-name")
            if author_el:
                post.author = author_el.inner_text().strip()

        except Exception as e:
            print(f"    DOM 解析异常: {e}")

        return post

    def parse_comments(self, comment_data: dict | list) -> list[dict]:
        """解析评论数据。"""
        comments = []

        if isinstance(comment_data, list):
            items = comment_data
        elif isinstance(comment_data, dict):
            items = self._extract_list_from_dict(comment_data)
        else:
            return comments

        for item in items:
            if not isinstance(item, dict):
                continue
            comment = {
                "type": "comment",
                "author": "",
                "content": "",
                "created_at": "",
            }

            # 作者
            user_info = item.get("user_info") or item.get("user") or {}
            if isinstance(user_info, dict):
                comment["author"] = user_info.get("nick_name") or user_info.get("nickname") or ""
            elif isinstance(user_info, str):
                comment["author"] = user_info

            # 内容
            content = item.get("content") or item.get("text") or item.get("body") or ""
            comment["content"] = self._html_to_text(str(content))

            # 时间
            comment["created_at"] = self._normalize_time(
                item.get("created_at") or item.get("create_time") or ""
            )

            comments.append(comment)

        return comments

    # ---- 工具方法 ----

    def _normalize_time(self, raw_time) -> str:
        """标准化时间格式。"""
        if not raw_time:
            return ""

        raw_time = str(raw_time)

        # 时间戳（秒或毫秒）
        if raw_time.isdigit():
            ts = int(raw_time)
            if ts > 1e12:  # 毫秒
                ts = ts // 1000
            from datetime import datetime
            try:
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                return raw_time

        # 已有格式的时间字符串
        return raw_time

    def _html_to_text(self, html: str) -> str:
        """HTML 转纯文本。"""
        if not html:
            return ""
        if not isinstance(html, str):
            html = str(html)
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"<p\s*>", "\n", text)
        text = re.sub(r"</p>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _html_to_markdown(self, html: str) -> str:
        """HTML 转 Markdown。"""
        if not html:
            return ""
        if not isinstance(html, str):
            html = str(html)

        md = html

        # 标题
        for i in range(6, 0, -1):
            md = re.sub(f"<h{i}[^>]*>(.*?)</h{i}>", "#" * i + r" \1", md, flags=re.DOTALL)

        # 加粗
        md = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", md, flags=re.DOTALL)
        md = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", md, flags=re.DOTALL)

        # 斜体
        md = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", md, flags=re.DOTALL)
        md = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", md, flags=re.DOTALL)

        # 链接
        md = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", md, flags=re.DOTALL)

        # 图片 → Markdown 图片引用（支持 src 和 data-src 懒加载）
        # 先处理 data-src（懒加载优先），再处理 src
        def _img_to_md(match):
            full_tag = match.group(0)
            # 优先取 data-src，其次取 data-original，最后取 src
            for attr in ["data-src", "data-original", "src"]:
                attr_match = re.search(rf'{attr}="([^"]*)"', full_tag)
                if attr_match and attr_match.group(1) and not attr_match.group(1).startswith("data:"):
                    return f"![]({attr_match.group(1)})"
            return ""  # 没有有效图片 URL，移除标签

        md = re.sub(r'<img[^>]*>', _img_to_md, md)

        # 换行
        md = re.sub(r"<br\s*/?>", "\n", md)
        md = re.sub(r"<p[^>]*>", "\n", md)
        md = re.sub(r"</p>", "\n", md)

        # 列表
        md = re.sub(r"<li[^>]*>", "- ", md)
        md = re.sub(r"</li>", "\n", md)

        # 引用
        md = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>", lambda m: "> " + m.group(1).strip().replace("\n", "\n> "), md, flags=re.DOTALL)

        # 清除剩余标签
        md = re.sub(r"<[^>]+>", "", md)

        # 清理多余空白
        md = re.sub(r"\n{3,}", "\n\n", md)

        return md.strip()

    def _extract_images(self, feed_data: dict) -> list[str]:
        """从帖子数据提取图片 URL 列表。"""
        images = []

        # 方式1：顶层图片列表字段（覆盖常见命名）
        img_list_keys = [
            "images", "image_list", "img_list", "imgs",
            "image_url_list", "img_url_list", "pic_list",
            "media_list", "resource_list", "attachments",
        ]
        for key in img_list_keys:
            img_list = feed_data.get(key)
            if img_list and isinstance(img_list, list):
                for item in img_list:
                    if isinstance(item, str):
                        images.append(item)
                    elif isinstance(item, dict):
                        # 尝试多种子字段
                        for sub_key in ["url", "img_url", "src", "image_url", "link",
                                        "file_url", "original_url", "thumb_url", "full_url"]:
                            url = item.get(sub_key, "")
                            if url:
                                images.append(url)
                                break

        # 方式2：单个图片字段
        single_img_keys = [
            "image_url", "cover_url", "cover_image", "img_url",
            "pic_url", "thumbnail", "thumb_url",
        ]
        for key in single_img_keys:
            url = feed_data.get(key, "")
            if url and isinstance(url, str):
                images.append(url)

        # 方式3：从 HTML 内容提取（同时匹配 src 和 data-src 懒加载）
        content = feed_data.get("content") or feed_data.get("text") or ""
        if isinstance(content, dict):
            # content 是 dict 时，提取 html 和 text 子字段
            for sub in ["html", "text", "content"]:
                sub_content = content.get(sub, "")
                if sub_content and isinstance(sub_content, str):
                    images.extend(self._extract_img_urls_from_html(sub_content))
        elif isinstance(content, str):
            images.extend(self._extract_img_urls_from_html(content))

        # 方式4：深度搜索 — 遍历所有字段，找看起来像图片 URL 的值
        images.extend(self._deep_find_image_urls(feed_data))

        # 去重
        seen = set()
        unique = []
        for url in images:
            if url not in seen and not url.startswith("data:"):
                seen.add(url)
                unique.append(url)

        return unique

    def _extract_img_urls_from_html(self, html: str) -> list[str]:
        """从 HTML 中提取图片 URL（支持 src 和 data-src 懒加载）。"""
        urls = []

        # 匹配 src="..."
        for m in re.finditer(r'<img[^>]*\bsrc="([^"]*)"', html):
            urls.append(m.group(1))

        # 匹配 data-src="..."（懒加载）
        for m in re.finditer(r'<img[^>]*data-src="([^"]*)"', html):
            urls.append(m.group(1))

        # 匹配 data-original="..."（另一种懒加载）
        for m in re.finditer(r'<img[^>]*data-original="([^"]*)"', html):
            urls.append(m.group(1))

        # 匹配 background-image: url(...)
        for m in re.finditer(r'background-image\s*:\s*url\(["\']?([^"\'()]+)["\']?\)', html):
            urls.append(m.group(1))

        return urls

    def _deep_find_image_urls(self, data, depth=0, max_depth=3) -> list[str]:
        """深度搜索数据结构中所有看起来像图片 URL 的值。"""
        if depth > max_depth:
            return []

        urls = []
        image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
        image_domains = (
            "img.xiaoe-tech.com",
            "cdn.xiaoe-tech.com",
            "xiaoe-tech.com",
            "img.xiaoe-tech",
            "xiaoetong",
        )

        if isinstance(data, dict):
            # 跳过已知的非图片字段，避免误匹配
            skip_keys = {"feeds_id", "feed_id", "id", "community_id", "user_id",
                         "app_id", "token", "session", "cookie"}
            for key, value in data.items():
                if key in skip_keys:
                    continue
                if isinstance(value, str) and self._looks_like_image_url(value, image_extensions, image_domains):
                    urls.append(value)
                else:
                    urls.extend(self._deep_find_image_urls(value, depth + 1, max_depth))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str) and self._looks_like_image_url(item, image_extensions, image_domains):
                    urls.append(item)
                else:
                    urls.extend(self._deep_find_image_urls(item, depth + 1, max_depth))

        return urls

    @staticmethod
    def _looks_like_image_url(url: str, extensions: tuple, domains: tuple) -> bool:
        """判断 URL 是否看起来像图片链接。"""
        if not url or not isinstance(url, str) or url.startswith("data:"):
            return False
        url_lower = url.lower().split("?")[0]
        # 扩展名匹配
        if url_lower.endswith(extensions):
            return True
        # 域名匹配
        for domain in domains:
            if domain in url_lower:
                return True
        return False

    def _extract_list_from_dict(self, data: dict) -> list:
        """从字典中提取列表。"""
        list_keys = ["list", "items", "data", "comments", "records"]
        for key in list_keys:
            if key in data and isinstance(data[key], list):
                return data[key]
        return []
