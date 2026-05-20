import json
import requests
import os
from dotenv import load_dotenv
from urllib3.poolmanager import key_fn_by_scheme
import math


# 加载.env文件
load_dotenv()

# 从.env中读取API
API_KEY = os.getenv("SILICONFLOW_API_KEY")

# POST的请求地址
url = "https://api.siliconflow.cn/v1/embeddings"

# 请求头
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 请求数据
def get_embeddings(texts: list[str]) -> list[list[float]]:
    data = {
        "input": texts,  
        "model":"BAAI/bge-m3",
        "encoding_format":"float"
    }
    # 发送POST请求
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    result["data"].sort(key=lambda x: x["index"])
    return [item["embedding"] for item in result["data"]]

text1 = "报销需要正规发票，由部门负责人签字后提交财务处。"
text2 = "今天天气不错，适合报名去做销售，然后报销。"
embeddings = get_embeddings([text1, text2])

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)

similarity = cosine_similarity(embeddings[0], embeddings[1])



print(f"文本1: {text1}")
print(f"文本2: {text2}")
print(f"余弦相似度: {similarity:.4f}")

