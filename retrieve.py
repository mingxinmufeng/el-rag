"""
召回后处理工具：
  1. 按 article_id 拼接对应的 "条文说明"（来自 {doc_id}_explanations.json）
  2. 展开条文中的引用（references.appendices / references.articles），
     拉取被引用的原条文一起送给 LLM，缓解"按附录 A 计算"这类纯引用句召回不到的问题

设计原则：
  - 不耦合具体的向量库（chroma / 其它）。本模块只负责"给我一个 article_id
    或一组命中结果 → 我给你拼好上下文"。
  - 所有规范的结构化文件统一放在 structured_chunks/ 下，按 doc_id 命名。
  - 多规范共存：通过 doc_id 区分。

典型用法：
    store = ArticleStore("structured_chunks")
    ctx = store.build_context("GB50058-2014", "1.0.2", expand_refs=True)
    # ctx["article"]      : 命中的正文条文
    # ctx["explanation"]  : 对应的条文说明（可能为 None）
    # ctx["referenced"]   : 被引用的其它条文 [{...}, ...]
    # ctx["prompt_text"]  : 已拼成可直接放进 LLM prompt 的文本
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Optional


class ArticleStore:
    """加载 structured_chunks/ 下所有规范，提供按 (doc_id, article_id) 检索。"""

    def __init__(self, root: str = "structured_chunks"):
        self.root = root

    # ---------------- 加载（带缓存） ----------------
    @lru_cache(maxsize=None)
    def _load_articles(self, doc_id: str) -> dict:
        """返回 {article_id: article_dict}。"""
        path = os.path.join(self.root, f"{doc_id}_articles.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            arts = json.load(f)
        return {a["article_id"]: a for a in arts}

    @lru_cache(maxsize=None)
    def _load_explanations(self, doc_id: str) -> dict:
        """返回 {article_id: explanation_dict}。"""
        path = os.path.join(self.root, f"{doc_id}_explanations.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ---------------- 单条查询 ----------------
    def get_article(self, doc_id: str, article_id: str) -> Optional[dict]:
        return self._load_articles(doc_id).get(article_id)

    def get_explanation(self, doc_id: str, article_id: str) -> Optional[dict]:
        return self._load_explanations(doc_id).get(article_id)

    # ---------------- 引用展开 ----------------
    def expand_references(self, doc_id: str, article: dict) -> list[dict]:
        """根据 article['references'] 拉取被引用的其它条文（同规范内）。

        - appendices: ["A", "D"] → 拉取附录章下所有条文
        - articles: ["A.0.1", "5.2.3"] → 直接按 article_id 取
        返回顺序：先具体条文，再附录整章；同一条文不重复。
        """
        refs = article.get("references") or {}
        articles_map = self._load_articles(doc_id)
        seen: set = {article["article_id"]}
        result: list[dict] = []

        # 1) 具体条文（含附录条 A.0.1）
        for aid in refs.get("articles", []):
            if aid in seen:
                continue
            art = articles_map.get(aid)
            if art:
                result.append(art)
                seen.add(aid)

        # 2) 整个附录章
        for appx_letter in refs.get("appendices", []):
            for aid, art in articles_map.items():
                if art.get("kind") == "appendix" and art.get("chapter_id") == appx_letter and aid not in seen:
                    result.append(art)
                    seen.add(aid)

        return result

    # ---------------- 组装 LLM 上下文 ----------------
    def build_context(
        self,
        doc_id: str,
        article_id: str,
        *,
        expand_refs: bool = True,
        include_explanation: bool = True,
    ) -> dict:
        """给定一个命中条文，组装可直接喂给 LLM 的上下文。"""
        article = self.get_article(doc_id, article_id)
        if article is None:
            return {
                "article": None,
                "explanation": None,
                "referenced": [],
                "prompt_text": "",
            }

        explanation = self.get_explanation(doc_id, article_id) if include_explanation else None
        referenced = self.expand_references(doc_id, article) if expand_refs else []

        prompt_text = _format_for_prompt(doc_id, article, explanation, referenced)
        return {
            "article": article,
            "explanation": explanation,
            "referenced": referenced,
            "prompt_text": prompt_text,
        }

    def build_context_for_hits(
        self,
        hits: list[dict],
        *,
        expand_refs: bool = True,
        include_explanation: bool = True,
    ) -> list[dict]:
        """批量处理：hits 形如 [{"doc_id":..., "article_id":..., "score":...}, ...]。"""
        return [
            self.build_context(
                h["doc_id"], h["article_id"],
                expand_refs=expand_refs,
                include_explanation=include_explanation,
            )
            for h in hits
        ]


# ---------------- 文本拼接 ----------------
def _format_for_prompt(
    doc_id: str,
    article: dict,
    explanation: Optional[dict],
    referenced: list[dict],
) -> str:
    """把一条命中结果（含说明 + 引用展开）拼成 LLM 上下文片段。"""
    lines: list[str] = []
    head = f"【{doc_id} 第 {article['article_id']} 条】"
    if article.get("chapter_title"):
        head += f"（{article['chapter_title']}"
        if article.get("section_title"):
            head += f" / {article['section_title']}"
            head += "）"
        else:
            head += "）"
    lines.append(head)
    if article.get("title"):
        lines.append(article["title"])
    if article.get("content"):
        lines.append(article["content"])

    if explanation and explanation.get("content"):
        lines.append("")
        lines.append(f"[条文说明 {article['article_id']}]")
        lines.append(explanation["content"])

    for ref_art in referenced:
        lines.append("")
        lines.append(
            f"[关联条文 {doc_id} 第 {ref_art['article_id']} 条 - {ref_art.get('chapter_title', '')}]"
        )
        if ref_art.get("title"):
            lines.append(ref_art["title"])
        if ref_art.get("content"):
            lines.append(ref_art["content"])

    return "\n".join(lines).strip()


# ---------------- CLI 自检 ----------------
def _demo():
    store = ArticleStore()
    # 示例 1：1.0.2 有条文说明
    ctx = store.build_context("GB50058-2014", "1.0.2")
    print("=" * 60)
    print("示例 1：1.0.2（有条文说明）")
    print("=" * 60)
    print(ctx["prompt_text"])
    print()
    print(f"[explanation 是否存在: {ctx['explanation'] is not None}]")
    print(f"[引用展开数: {len(ctx['referenced'])}]")

    # 示例 2：3.3.2 引用附录 A
    print()
    print("=" * 60)
    print("示例 2：3.3.2（引用附录 A，自动展开）")
    print("=" * 60)
    ctx = store.build_context("GB50058-2014", "3.3.2")
    print(ctx["prompt_text"][:1200])
    print("...")
    print()
    print(f"[引用展开数: {len(ctx['referenced'])}]  -> {[r['article_id'] for r in ctx['referenced']]}")


if __name__ == "__main__":
    _demo()
