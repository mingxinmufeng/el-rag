import os
import re
import shutil

# 路径配置
RAW_PDF_DIR = "raw_pdf"
PARSE_RESULT_DIR = "parse_result"
CLEANED_MD_DIR = "cleaned_md"

# 动态获取parse_result下的子文件夹（对应各个PDF）
def get_parse_result_dirs():
    """获取parse_result下所有子文件夹（对应各个PDF的解析结果）"""
    if not os.path.exists(PARSE_RESULT_DIR):
        return []
    
    dirs = []
    for item in os.listdir(PARSE_RESULT_DIR):
        item_path = os.path.join(PARSE_RESULT_DIR, item)
        # 是文件夹且包含full.md
        if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "full.md")):
            dirs.append(item)
    return sorted(dirs)


def get_doc_code_from_dirname(dir_name: str, text: str = "") -> str:
    """从文件夹名或内容提取规范编号"""
    # 先尝试从文件夹名提取 GB 编号
    match = re.search(r'[GT]?B\d{4,6}[-—]?\d{4}', dir_name)
    if match:
        code = match.group(0)
        code = re.sub(r'[—]', '-', code)
        return code
    
    # 尝试从内容提取
    if text:
        return extract_doc_code(text)
    
    # 默认使用文件夹名
    return dir_name


def extract_doc_code(text: str) -> str:
    """从文本中提取规范编号（如 GB50058-2014）"""
    # 匹配 GB/T 或 GB 编号格式
    patterns = [
        r'[GT]?B\s*/?T?\s*\d{4,6}\s*[-—]\s*\d{4}',  # GB 50058-2014, GB/T 50058-2014
        r'[GT]?B\d{4,6}[-—]\d{4}',  # GB50058-2014
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            # 清理空格，统一格式
            code = match.group(0)
            code = re.sub(r'\s+', '', code)  # 去掉所有空格
            code = re.sub(r'[—]', '-', code)  # 统一连接符
            return code
    
    # 如果没找到，返回默认值
    return "doc"


def clean_markdown(text: str) -> str:
    # 1. 删除 [Non-Text] 占位行（含前后空行合并）
    text = re.sub(r"\[Non-Text\]\n?", "", text)

    # 2. 删除 <|LOC_xxx|> 类乱码占位符
    text = re.sub(r"<\|LOC_[^|]*\|>", "", text)

    # 3. 删除其他常见OCR乱码符号（孤立的 ☆ 等装饰符号独占一行，以及1~2个汉字的孤立残留字符行）
    text = re.sub(r"^\s*☆\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\u4e00-\u9fff]{1,2}$", "", text, flags=re.MULTILINE)

    # 4a. 修复中文硬截断续行：行末为汉字（非标点），下一行紧接汉字
    # 但不合并 # 标题行（防止标题与正文粘连）
    text = re.sub(r"(^(?!#).*[\u4e00-\u9fff])\n\n([\u4e00-\u9fff])", r"\1\2", text, flags=re.MULTILINE)

    # 4b. 修复英文硬截断续行：行末为英文字母/数字，下一行为小写字母开头（中间可有空行）
    text = re.sub(r"([A-Za-z0-9,])\n{1,2}([a-z])", r"\1 \2", text)

    # 5. 列表项 1) 2) 3) 统一加两个空格缩进，与上级条文编号区分；并确保 ) 后有空格
    text = re.sub(r"^(\d+\))", r"  \1", text, flags=re.MULTILINE)
    text = re.sub(r"^(  \d+\))(\S)", r"\1 \2", text, flags=re.MULTILINE)

    # 8a. 预处理：去除 "# 数字 区号" 误标题（如 "# 3 22区："），还原为裸文本供5a处理
    text = re.sub(r"^# (\d+\s+(?:2[012]|[012])区)", r"\1", text, flags=re.MULTILINE)

    # 8. 修复标题层级（MinerU 解析后全为 # 一级，或完全没有 #）
    # #### 四级：带 # 的条文编号 x.x.x
    text = re.sub(
        r"^# (\d+\.\d+\.\d+.+)$",
        r"#### \1",
        text, flags=re.MULTILINE
    )
    # #### 四级：裸文本条文编号 x.x.x（无 # 前缀），内容可以数字或汉字开头
    text = re.sub(
        r"^(\d+\.\d+\.\d+\s+[\u4e00-\u9fff0-9].+)$",
        r"#### \1",
        text, flags=re.MULTILINE
    )
    # #### 四级：附录条文编号 A.0.1 / B.0.1 / D.0.2 等（裸文本或带#前缀）
    text = re.sub(
        r"^#?\s*([A-Z]\.\d+\.\d+\s+.+)$",
        r"#### \1",
        text, flags=re.MULTILINE
    )
    # ### 三级：带 # 的节编号 x.x（如 3.1 一般规定）
    text = re.sub(
        r"^# (\d+\.\d+ .+)$",
        r"### \1",
        text, flags=re.MULTILINE
    )
    # ## 二级：章编号 单数字开头（如 1 总则、2 术语、3 爆炸性气体环境）
    text = re.sub(
        r"^# (\d+ [\u4e00-\u9fff].+)$",
        r"## \1",
        text, flags=re.MULTILINE
    )

    # 5a. 上下文感知修复区号粘连（必须在####生成后执行）
    # 合法区号：0区/1区/2区/20区/21区/22区（含粘连/内部多余空格形式）
    # 匹配：序号数字 + 可选空格 + 区号数字(含20/21/22) + 可选空格 + 区
    ZONE_PAT = re.compile(r"^([1-9])\s*(2[012]|[012])\s*区")
    src_lines = text.splitlines()
    fixed_lines = []
    for idx, ln in enumerate(src_lines):
        m = ZONE_PAT.match(ln)
        if m:
            seq = int(m.group(1))
            prev = next((src_lines[j] for j in range(idx - 1, -1, -1) if src_lines[j].strip()), "")
            nxt  = next((src_lines[j] for j in range(idx + 1, len(src_lines)) if src_lines[j].strip()), "")
            prev_m = ZONE_PAT.match(prev)
            next_m = ZONE_PAT.match(nxt)
            is_seq = (
                (prev_m and int(prev_m.group(1)) == seq - 1) or
                (next_m and int(next_m.group(1)) == seq + 1)
            )
            if seq == 1:
                is_seq = is_seq and bool(re.match(r"^####", prev))
            if is_seq:
                # 重建：序号 + 空格 + 区号数字+区 + 剩余内容（去掉原行中序号+空格+区号部分）
                suffix = ln[m.end():]   # "区"之后的内容
                ln = m.group(1) + " " + m.group(2) + "区" + suffix
        fixed_lines.append(ln)
    text = "\n".join(fixed_lines)

    # 5b. 修复 "1 20 区" / "1 21 区" / "1 22 区" 行首序号1+两位区号含空格
    text = re.sub(r"^(1)\s+(2[012])\s+区", r"\1 \2区", text, flags=re.MULTILINE)

    # 6. 合并连续3个以上空行为2个空行
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 7. 去除行尾多余空格
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)

    return text.strip() + "\n"


def collect_referenced_images(text: str) -> list[str]:
    """提取MD中所有引用的图片文件名"""
    return re.findall(r"!\[.*?\]\(images/([^)]+)\)", text)


def process_single_doc(parse_subdir: str):
    """处理单个文档"""
    input_md = os.path.join(PARSE_RESULT_DIR, parse_subdir, "full.md")
    input_images_dir = os.path.join(PARSE_RESULT_DIR, parse_subdir, "images")
    
    if not os.path.exists(input_md):
        print(f"跳过: {parse_subdir} (无full.md)")
        return
    
    # 读取原始MD
    with open(input_md, "r", encoding="utf-8") as f:
        raw = f.read()
    
    # 从文件夹名或内容提取规范编号
    doc_code = get_doc_code_from_dirname(parse_subdir, raw)
    output_md = os.path.join(CLEANED_MD_DIR, f"{doc_code}_cleaned.md")
    output_images_dir = os.path.join(CLEANED_MD_DIR, f"{doc_code}_images")
    
    # 跳过已存在的
    if os.path.exists(output_md):
        print(f"跳过: {doc_code} (已存在)")
        return
    
    # 清洗
    cleaned = clean_markdown(raw)
    
    # 收集引用图片并复制
    os.makedirs(output_images_dir, exist_ok=True)
    referenced = collect_referenced_images(cleaned)
    copied, missing = 0, 0
    for fname in referenced:
        src = os.path.join(input_images_dir, fname)
        dst = os.path.join(output_images_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            copied += 1
        else:
            print(f"  [WARN] 图片不存在: {fname}")
            missing += 1
    
    # 写出清洗后MD
    with open(output_md, "w", encoding="utf-8") as f:
        f.write(cleaned)
    
    print(f"[{doc_code}] 清洗完成: {output_md}")
    print(f"  图片: {copied}/{len(referenced)} 张")
    
    # 质量报告
    issues = []
    lines = cleaned.splitlines()
    for i, line in enumerate(lines, 1):
        if re.match(r"^\d+ \d+ 区", line):
            issues.append((i, "区号空格异常", line))
    
    if issues:
        print(f"  发现 {len(issues)} 处疑似问题")


def main():
    os.makedirs(CLEANED_MD_DIR, exist_ok=True)
    
    # 获取所有待处理的子文件夹
    doc_dirs = get_parse_result_dirs()
    
    if not doc_dirs:
        print(f"未在 {PARSE_RESULT_DIR} 下找到包含 full.md 的子文件夹")
        print("请确保每个PDF的解析结果放在单独的子文件夹中，如:")
        print(f"  {PARSE_RESULT_DIR}/GB50058-2014/full.md")
        return
    
    print(f"发现 {len(doc_dirs)} 个文档待处理: {', '.join(doc_dirs)}")
    print()
    
    # 批量处理
    for doc_dir in doc_dirs:
        process_single_doc(doc_dir)
        print()
    
    print("=" * 50)
    print("全部处理完成")


if __name__ == "__main__":
    main()
