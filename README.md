# EL-RAG

基于 SiliconFlow Embedding API 的文本语义相似度实验项目。

## 功能

- 调用 SiliconFlow `BAAI/bge-m3` 模型将文本转为向量
- 计算两段文本的余弦相似度

## 快速开始

### 1. 创建虚拟环境

```bash
py -3.11 -m venv venv
venv\Scripts\activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

复制 `.env.example` 为 `.env`，填入你的 SiliconFlow API Key：

```
SILICONFLOW_API_KEY=your_api_key_here
```

> 获取地址：https://cloud.siliconflow.cn/account/ak

### 4. 运行

```bash
python api.py
```

**示例输出：**

```
文本1: 报销需要正规发票，由部门负责人签字后提交财务处。
文本2: 员工报销费用须附发票原件，经主管审批后交财务部门处理。
余弦相似度: 0.9113
```

## 相似度参考

| 相似度 | 含义 |
|--------|------|
| > 0.85 | 语义高度相似 |
| 0.70 ~ 0.85 | 话题相关 |
| 0.50 ~ 0.70 | 有一定关联 |
| < 0.50 | 基本不相关 |

## 技术栈

- Python 3.11
- [SiliconFlow Embeddings API](https://docs.siliconflow.cn/cn/api-reference/embeddings/create-embeddings)
- BAAI/bge-m3 模型
