"""输出格式化：Staging 格式 Markdown 生成、文件下载、状态文件管理。"""

import json
import re
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import requests

from content_parser import PostData


# Staging 格式 frontmatter 模板（与 Source Normalizer 统一 schema 对齐）
STAGING_TEMPLATE = """---
title: "{title}"
created: "{created}"
origin: xiaoetong
source_path: "{source_path}"
tags: [{tags}]
url: "{url}"
author: "{author}"
{optional_fields}
---

{content}
"""

# 请求 Session（用于下载图片/音频）
_session = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": "https://quanzi.xiaoe-tech.com/",
        })
    return _session


class OutputManager:
    """管理输出文件：Markdown 生成、资源下载、增量状态。"""

    def __init__(
        self,
        staging_path: str,
        vault_root: str,
        attachments_subdir: str = "attachments/",
        video_dir: str = "videos/",
        state_file: str = ".xiaoetong-state.json",
    ):
        self.vault_root = Path(vault_root)
        self.staging_path = self.vault_root / staging_path
        self.attachments_dir = self.staging_path / attachments_subdir
        self.video_dir = self.staging_path / video_dir
        self.state_file = self.vault_root / state_file
        self.new_articles_file = self.staging_path / ".new-articles.json"

        # 确保目录存在
        self.staging_path.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.video_dir.mkdir(parents=True, exist_ok=True)

        # 加载增量状态
        self.state = self._load_state()

    # ---- 增量状态管理 ----

    def _load_state(self) -> dict:
        """加载增量状态文件。"""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_state(self):
        """保存增量状态文件。"""
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def is_post_processed(self, feeds_id: str) -> bool:
        """检查帖子是否已处理过。"""
        return feeds_id in self.state

    def mark_post_processed(self, feeds_id: str, post_data: dict):
        """标记帖子为已处理。"""
        self.state[feeds_id] = {
            "processed_at": datetime.now().isoformat(),
            **post_data,
        }
        self._save_state()

    # ---- Markdown 输出 ----

    def write_post(self, post: PostData, circle_name: str = "") -> str:
        """将帖子输出为 Staging 格式 Markdown 文件。

        Returns:
            输出文件路径
        """
        # 生成文件名
        filename = self._sanitize_filename(f"xiaoetong-{post.feeds_id}")
        filepath = self.staging_path / f"{filename}.md"

        # 构建 frontmatter
        source_path = f"xiaoetong/{post.community_id}/{post.feeds_id}"
        tags = ", ".join(f"小鹅通, {circle_name}" .split(", ") if circle_name else ["小鹅通"])

        # 可选字段
        optional_parts = []
        if post.images:
            optional_parts.append(f'images:')
            for img in post.images:
                img_name = self._get_image_filename(img, post.feeds_id)
                optional_parts.append(f'  - "{img_name}"')
        if post.video_url or post.video_m3u8:
            video_filename = f"{post.feeds_id}.mp4"
            optional_parts.append(f'video: "{video_filename}"')
        if post.audio_url:
            optional_parts.append(f'audio: "已下载"')
        if post.likes_count:
            optional_parts.append(f'likes: {post.likes_count}')
        if post.comments_count:
            optional_parts.append(f'comments_count: {post.comments_count}')
        if post.is_featured:
            optional_parts.append(f'featured: true')
        if post.is_pinned:
            optional_parts.append(f'pinned: true')

        optional_fields = "\n".join(optional_parts)

        # 构建正文
        content_parts = []

        # 帖子类型标签
        if post.post_type:
            content_parts.append(f"*类型: {post.post_type}*\n")

        # 正文
        if post.content_markdown:
            content_parts.append(post.content_markdown)

        # 图片（Markdown 引用）— 去重：跳过已在正文中内联引用的图片
        if post.images:
            # 检查 content_markdown 中已有哪些图片 URL
            inline_img_urls = set()
            if post.content_markdown:
                import re as _re
                for m in _re.finditer(r'!\[.*?\]\(([^)]+)\)', post.content_markdown):
                    inline_img_urls.add(m.group(1))

            extra_images = [img for img in post.images if img not in inline_img_urls]
            if extra_images:
                content_parts.append("\n## 图片\n")
                for img_url in extra_images:
                    img_name = self._get_image_filename(img_url, post.feeds_id)
                    content_parts.append(f"![图片](attachments/{img_name})")

        # 视频
        if post.video_url or post.video_m3u8:
            content_parts.append("\n## 视频\n")
            video_filename = f"{post.feeds_id}.mp4"
            content_parts.append(f"📹 视频: videos/{video_filename}")

        # 音频
        if post.audio_url:
            content_parts.append("\n## 音频\n")
            content_parts.append("🎵 音频已下载")

        # 评论
        if post.comments:
            content_parts.append("\n## 评论\n")
            for comment in post.comments:
                author = comment.get("author", "匿名")
                content = comment.get("content", "")
                created = comment.get("created_at", "")
                if created:
                    # 只显示日期时间部分
                    created = created[:19].replace("T", " ")
                content_parts.append(f"> **{author}** ({created}): {content}")

        content = "\n\n".join(content_parts)

        # 组装完整 Markdown
        md = STAGING_TEMPLATE.format(
            title=post.title or "无标题",
            created=post.created_at or "",
            source_path=source_path,
            tags=tags,
            url=post.url or "",
            author=post.author or "",
            optional_fields=optional_fields,
            content=content,
        )

        # 写入文件
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md)

        # 标记为已处理
        self.mark_post_processed(post.feeds_id, {
            "title": post.title,
            "community_id": post.community_id,
            "circle_name": circle_name,
        })

        return str(filepath)

    # ---- 资源下载 ----

    def download_images(self, post: PostData) -> list[str]:
        """下载帖子图片到本地。

        Returns:
            下载成功的文件路径列表
        """
        if not post.images:
            return []

        downloaded = []
        session = _get_session()

        for img_url in post.images:
            try:
                img_name = self._get_image_filename(img_url, post.feeds_id)
                img_path = self.attachments_dir / img_name

                if img_path.exists():
                    downloaded.append(str(img_path))
                    continue

                resp = session.get(img_url, timeout=30)
                resp.raise_for_status()

                img_path.write_bytes(resp.content)
                downloaded.append(str(img_path))

            except Exception as e:
                print(f"      图片下载失败 {img_url[:60]}: {e}")

        return downloaded

    def download_audio(self, post: PostData) -> str | None:
        """下载音频文件。"""
        if not post.audio_url:
            return None

        try:
            audio_name = f"{post.feeds_id}.mp3"
            audio_path = self.attachments_dir / audio_name

            if audio_path.exists():
                return str(audio_path)

            session = _get_session()
            resp = session.get(post.audio_url, timeout=60)
            resp.raise_for_status()

            audio_path.write_bytes(resp.content)
            return str(audio_path)

        except Exception as e:
            print(f"      音频下载失败: {e}")
            return None

    # ---- 新文章清单 ----

    def write_new_articles_list(self, new_files: list[str]):
        """输出 .new-articles.json 供下游 Source Normalizer / Wiki 使用。"""
        # 使用相对路径（相对于 staging_path）
        relative_paths = []
        for f in new_files:
            try:
                rel = str(Path(f).relative_to(self.staging_path)).replace("\\", "/")
                relative_paths.append(rel)
            except ValueError:
                relative_paths.append(f)

        with open(self.new_articles_file, "w", encoding="utf-8") as f:
            json.dump(relative_paths, f, ensure_ascii=False, indent=2)

        print(f"  新文章清单已保存: {self.new_articles_file} ({len(relative_paths)} 篇)")

    # ---- 工具方法 ----

    def _sanitize_filename(self, name: str) -> str:
        """清理文件名中的非法字符。"""
        name = re.sub(r'[<>:"/\\|?*]', '_', name)
        name = re.sub(r'\s+', '_', name)
        name = name.strip('._')
        # 限制长度
        if len(name) > 100:
            name = name[:100]
        return name

    def _get_image_filename(self, url: str, feeds_id: str) -> str:
        """根据图片 URL 生成文件名。"""
        # 尝试从 URL 提取扩展名
        ext = ".jpg"
        url_path = url.split("?")[0]  # 去掉查询参数
        if "." in url_path.split("/")[-1]:
            ext = "." + url_path.split("/")[-1].rsplit(".", 1)[-1].lower()
            if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]:
                ext = ".jpg"

        # 用 URL hash 生成唯一文件名
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        return f"{feeds_id}_{url_hash}{ext}"
