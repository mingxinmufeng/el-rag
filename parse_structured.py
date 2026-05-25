"""
基于清洗后的 Markdown 文件解析规范文档结构。

输出（每本规范产生 3 个文件，全部位于 structured_chunks/）：
  1. {doc_id}_articles.json      —— 正文条文（用于 embedding 入库）
  2. {doc_id}_explanations.json  —— 条文说明，按 article_id 索引（召回后由 LLM 拼接，不入向量库）
  3. {doc_id}_hierarchy.json     —— 章/节/条层级（用于调试与展示）

支持要点：
  - 主条文编号：x.x.x
  - 附录章：`# 附录 A xxx`
  - 附录条文：`#### A.0.1 xxx`
  - 自动检测 `# 条文说明` 分界线，之后的条文进入 explanations
  - 引用抽取：在 content 中识别附录与条文 ID（含跨规范召回时由检索层做引用展开）
  - 批量处理 cleaned_md/ 下所有 *_cleaned.md
"""

import json
import os
import re
from pathlib import Path

# ---------------- 路径 ----------------
CLEANED_MD_DIR = "cleaned_md"
OUTPUT_DIR = "structured_chunks"


# ---------------- 工具函数 ----------------
def extract_doc_id(md_path: str) -> str:
    """从文件名提取规范编号，例如 GB50058-2014_cleaned.md -> GB50058-2014"""
    filename = Path(md_path).stem
    match = re.search(r'[GT]?B/?T?\s*\d{4,6}\s*[-—]\s*\d{4}', filename)
    if match:
        code = re.sub(r'\s+', '', match.group(0)).replace('—', '-')
        return code
    # 退化：去掉常见后缀
    return re.sub(r'(_cleaned|_full|^full_)', '', filename) or 'doc'


# ---------------- 标题识别 ----------------
# 主章：## 1 xxx
RE_CH_MAIN = re.compile(r'^##\s+(\d+)\s+(.+)$')
# 附录章（兼容 # / ## / 无 # 前缀的容错形式）：
#   # 附录A xxx / # 附录 A xxx / ## 附录 A xxx / 附录 A xxx
RE_CH_APPX = re.compile(r'^(?:#{1,2}\s+)?附录\s*([A-Z])\s+(\S.*)$')
# 主节：### 3.1 xxx
RE_SEC_MAIN = re.compile(r'^###\s+(\d+\.\d+)\s+(.+)$')
# 附录节（少见）：### A.0 xxx
RE_SEC_APPX = re.compile(r'^###\s+([A-Z]\.\d+)\s+(.+)$')
# 主条：#### 3.1.1 xxx
RE_ART_MAIN = re.compile(r'^####\s+(\d+\.\d+\.\d+)\s*(.*)$')
# 附录条：#### A.0.1 xxx
RE_ART_APPX = re.compile(r'^####\s+([A-Z]\.\d+\.\d+)\s*(.*)$')
# 条文说明分界线：# 条文说明 / ## 条文说明 / 单行 "条文说明"
RE_EXPL_BOUNDARY = re.compile(r'^#{0,3}\s*条文\s*说明\s*$')
# TOC 行特征：含中文省略号 …… 或行尾带页码 (xx) / （xx）
RE_TOC_LINE = re.compile(r'…{2,}|[\(（]\s*\d+\s*[\)）]\s*$')


def _is_toc_line(line: str) -> bool:
    return bool(RE_TOC_LINE.search(line))


# ---------------- 引用抽取 ----------------
RE_REF_APPENDIX = re.compile(r'附录\s*([A-Z])\b')
RE_REF_APPX_ART = re.compile(r'\b([A-Z]\.\d+\.\d+)\b')
RE_REF_MAIN_ART = re.compile(r'(?<!\d)(\d+\.\d+\.\d+)(?!\d)')


def extract_references(content: str, self_id: str = "") -> dict:
    """从条文内容中抽取交叉引用。

    返回:
      {"appendices": ["A", ...], "articles": ["A.0.1", "5.2.3", ...]}
    引用不包括自身 ID。
    """
    appendices = sorted(set(RE_REF_APPENDIX.findall(content)))
    articles = set(RE_REF_APPX_ART.findall(content)) | set(RE_REF_MAIN_ART.findall(content))
    articles.discard(self_id)
    return {
        "appendices": appendices,
        "articles": sorted(articles, key=_article_id_sort_key),
    }


# ---------------- 排序键 ----------------
def _article_id_sort_key(article_id: str):
    """支持数字编号(3.1.1)与字母附录编号(A.0.1)统一排序。"""
    parts = article_id.split('.')
    head = parts[0]
    if head.isdigit():
        return (0,) + tuple(int(p) for p in parts)
    # 字母开头：放在数字之后，按字母序
    rest = tuple(int(p) for p in parts[1:]) if len(parts) > 1 else tuple()
    return (1, ord(head[0])) + rest


# ---------------- 内容清洗 ----------------
def _clean_content(lines: list) -> str:
    """去除条文内容前后空行，保留段内换行。"""
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


# ---------------- 主解析 ----------------
def parse_markdown(md_path: str) -> dict:
    doc_id = extract_doc_id(md_path)
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    chapters: list = []
    articles_flat: list = []
    explanations: dict = {}

    current_ch = None
    current_sec = None
    current_art = None
    current_expl = None
    in_explanation = False
    seen_main_chapter = False  # 用于过滤前置 TOC 区中的"附录 X"伪标题

    def flush_article():
        nonlocal current_art
        if current_art is not None:
            current_art['content'] = _clean_content(current_art.pop('_lines'))
            # 标题行常自带规则正文（如 "3.3.2 ... 应符合附录 A ..."），
            # 因此引用抽取需覆盖 title + content。
            ref_text = (current_art['title'] or '') + '\n' + current_art['content']
            current_art['references'] = extract_references(
                ref_text, self_id=current_art['article_id']
            )
            articles_flat.append(current_art)
        current_art = None

    def flush_expl():
        nonlocal current_expl
        if current_expl is not None:
            current_expl['content'] = _clean_content(current_expl.pop('_lines'))
            explanations[current_expl['article_id']] = {
                'article_id': current_expl['article_id'],
                'title': current_expl['title'],
                'content': current_expl['content'],
                'start_line': current_expl['start_line'],
            }
        current_expl = None

    for idx, raw_line in enumerate(lines):
        line = raw_line.rstrip('\n')
        stripped = line.strip()
        line_no = idx + 1

        if RE_EXPL_BOUNDARY.match(stripped):
            flush_article()
            flush_expl()
            in_explanation = True
            current_ch = None
            current_sec = None
            continue

        m_ch_main = RE_CH_MAIN.match(stripped)
        m_ch_appx = RE_CH_APPX.match(stripped)
        # 过滤目录页：附录章无 # 前缀时，需要：
        #   (a) 已见过至少一个 ## 主章（说明已越过前置 TOC 区）
        #   (b) 不带 …… 或行尾页码（去除目录残留）
        if m_ch_appx and not stripped.startswith('#'):
            if (not seen_main_chapter) or _is_toc_line(stripped):
                m_ch_appx = None
        if m_ch_main or m_ch_appx:
            flush_article()
            flush_expl()
            if in_explanation:
                current_ch = None
                current_sec = None
                continue
            if m_ch_main:
                ch_id, ch_name = m_ch_main.group(1), m_ch_main.group(2).strip()
                kind = 'main'
                title = f"{ch_id} {ch_name}"
                seen_main_chapter = True
            else:
                ch_id = m_ch_appx.group(1)
                ch_name = m_ch_appx.group(2).strip()
                kind = 'appendix'
                title = f"附录 {ch_id} {ch_name}".strip()
            current_ch = {
                'kind': kind,
                'chapter_id': ch_id,
                'title': title,
                'start_line': line_no,
                'sections': [],
                'article_ids': [],
            }
            chapters.append(current_ch)
            current_sec = None
            continue

        m_sec_main = RE_SEC_MAIN.match(stripped)
        m_sec_appx = RE_SEC_APPX.match(stripped)
        if m_sec_main or m_sec_appx:
            flush_article()
            flush_expl()
            if in_explanation:
                current_sec = None
                continue
            if m_sec_main:
                sec_id, sec_name = m_sec_main.group(1), m_sec_main.group(2).strip()
            else:
                sec_id, sec_name = m_sec_appx.group(1), m_sec_appx.group(2).strip()
            current_sec = {
                'section_id': sec_id,
                'title': f"{sec_id} {sec_name}",
                'start_line': line_no,
                'article_ids': [],
            }
            if current_ch is not None:
                current_ch['sections'].append(current_sec)
            continue

        m_art_main = RE_ART_MAIN.match(stripped)
        m_art_appx = RE_ART_APPX.match(stripped)
        if m_art_main or m_art_appx:
            flush_article()
            flush_expl()
            if m_art_main:
                art_id, art_rest = m_art_main.group(1), m_art_main.group(2).strip()
                kind = 'main'
            else:
                art_id, art_rest = m_art_appx.group(1), m_art_appx.group(2).strip()
                kind = 'appendix'

            if in_explanation:
                current_expl = {
                    'article_id': art_id,
                    'title': art_rest,
                    'start_line': line_no,
                    '_lines': [],
                }
            else:
                current_art = {
                    'id': f"{doc_id}_{art_id}",
                    'doc_id': doc_id,
                    'article_id': art_id,
                    'kind': kind,
                    'title': art_rest,
                    'chapter_id': current_ch['chapter_id'] if current_ch else '',
                    'chapter_title': current_ch['title'] if current_ch else '',
                    'section_id': current_sec['section_id'] if current_sec else '',
                    'section_title': current_sec['title'] if current_sec else '',
                    'start_line': line_no,
                    '_lines': [],
                }
                if current_sec is not None:
                    current_sec['article_ids'].append(art_id)
                elif current_ch is not None:
                    current_ch['article_ids'].append(art_id)
            continue

        if stripped.startswith('#'):
            # 其它级别的标题（如纯 # 标题），结束当前条文收集
            flush_article()
            flush_expl()
            continue

        if current_art is not None:
            current_art['_lines'].append(line)
        elif current_expl is not None:
            current_expl['_lines'].append(line)

    flush_article()
    flush_expl()

    articles_flat.sort(key=lambda a: _article_id_sort_key(a['article_id']))

    return {
        'doc_id': doc_id,
        'source_file': md_path,
        'chapters': chapters,
        'articles': articles_flat,
        'explanations': explanations,
    }


# ---------------- 输出 ----------------
def save_outputs(parsed: dict, output_dir: str = OUTPUT_DIR) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    doc_id = parsed['doc_id']

    hierarchy_file = os.path.join(output_dir, f"{doc_id}_hierarchy.json")
    articles_file = os.path.join(output_dir, f"{doc_id}_articles.json")
    explanations_file = os.path.join(output_dir, f"{doc_id}_explanations.json")

    hierarchy = {
        'doc_id': doc_id,
        'source_file': parsed['source_file'],
        'chapters': parsed['chapters'],
    }
    with open(hierarchy_file, 'w', encoding='utf-8') as f:
        json.dump(hierarchy, f, ensure_ascii=False, indent=2)

    with open(articles_file, 'w', encoding='utf-8') as f:
        json.dump(parsed['articles'], f, ensure_ascii=False, indent=2)

    with open(explanations_file, 'w', encoding='utf-8') as f:
        json.dump(parsed['explanations'], f, ensure_ascii=False, indent=2)

    return {
        'hierarchy': hierarchy_file,
        'articles': articles_file,
        'explanations': explanations_file,
    }


# ---------------- 批处理 ----------------
def process_one(md_path: str) -> dict:
    parsed = parse_markdown(md_path)
    paths = save_outputs(parsed)

    arts = parsed['articles']
    appx = sum(1 for a in arts if a['kind'] == 'appendix')
    with_content = sum(1 for a in arts if a['content'].strip())
    with_refs = sum(1 for a in arts if a['references']['appendices'] or a['references']['articles'])

    print(f"[{parsed['doc_id']}] 解析完成")
    print(f"  - 章: {len(parsed['chapters'])}  条: {len(arts)} (附录条 {appx}, 含内容 {with_content}, 含引用 {with_refs})")
    print(f"  - 条文说明: {len(parsed['explanations'])} 条")
    for k, v in paths.items():
        print(f"  - {k}: {v}")
    return parsed


def main():
    if not os.path.isdir(CLEANED_MD_DIR):
        print(f"目录不存在: {CLEANED_MD_DIR}")
        return

    md_files = sorted(
        os.path.join(CLEANED_MD_DIR, f)
        for f in os.listdir(CLEANED_MD_DIR)
        if f.endswith('_cleaned.md')
    )
    if not md_files:
        print(f"未在 {CLEANED_MD_DIR}/ 下找到 *_cleaned.md")
        return

    print(f"发现 {len(md_files)} 个待处理文档\n")
    for md in md_files:
        process_one(md)
        print()
    print("=" * 50)
    print("全部完成")


if __name__ == '__main__':
    main()
