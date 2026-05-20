import os
import base64
import requests
from dotenv import load_dotenv


# 加载.env文件
load_dotenv()

# 从.env中读取API
API_KEY = os.getenv("SILICONFLOW_API_KEY")

# POST的请求地址
url = "https://api.siliconflow.cn/v1/chat/completions"

# 请求头
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 默认VL模型
DEFAULT_VL_MODEL = "Qwen/Qwen3-VL-32B-Instruct"

# 系统提示词
SYSTEM_PROMPT = """
你是专业的工程建设规范文档整理专家，熟悉国家及行业标准规范体系。
1. 自动删除所有<|LOC_xxx|>类占位乱码、无效符号及其他OCR噪声字符
2. 修正OCR识别错别字，保持原文语义不变
3. 表格内容严格按照原表格式对齐，保留行列结构
4. 专业术语严格遵照所属规范领域的国家标准用语输出
5. 只输出规整后的规范条文原文，不添加任何解释或额外内容
"""

def encoding_image(image_path: str) -> str:
    """将本地图片编码为base64字符串"""
    with open(image_path, "rb") as f:
        image_data = f.read()
    return base64.b64encode(image_data).decode("utf-8")


def vl_chat(prompt: str, image_path: str, model: str = DEFAULT_VL_MODEL, max_tokens: int = 1024) -> str:
    """调用VL模型对本地图片进行理解问答"""
    base64_image = encoding_image(image_path)
    ext = os.path.splitext(image_path)[-1].lower().lstrip(".")
    mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
    mime_type = mime_map.get(ext, "jpeg")
    image_url = f"data:image/{mime_type};base64,{base64_image}"

    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": max_tokens,
    }
    response = requests.post(url, headers=headers, json=data, timeout=120)
    result = response.json()
    usage = result.get("usage", {})
    return result["choices"][0]["message"]["content"], usage


if __name__ == "__main__":
    import time
    test_image = "ceshi.jpg"
    test_prompt = "请识别并提取图片中的所有文字内容，保持原有格式和结构输出。并提供图片链接"

    print(f"模型: {DEFAULT_VL_MODEL}")
    print(f"提问: {test_prompt}")
    print("-" * 40)
    t0 = time.time()
    answer, usage = vl_chat(test_prompt, test_image)
    elapsed = time.time() - t0
    print(f"回答: {answer}")
    print(f"\n耗时: {elapsed:.2f}s")
    print(f"Token用量 - 输入: {usage.get('prompt_tokens', 'N/A')}, 输出: {usage.get('completion_tokens', 'N/A')}, 合计: {usage.get('total_tokens', 'N/A')}")
