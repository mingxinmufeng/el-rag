import chromadb
from api import EmbeddingAPI

# 创建 ChromaDB 客户端
chromadb_client = chromadb.Client()
api_client = EmbeddingAPI()

# 获取或创建一个集合
collection = chromadb_client.get_or_create_collection(name="my_collection")

# 添加数据到集合
text1 = "报销需要正规发票，由部门负责人签字后提交财务处。"
text2 = "因公外出产生的杂费，整理好票据逐级审批上报。"
text3 = "超出报销标准的费用部分，不予统一核算报销。"
text4 = "员工个人消费不在公司统一报销范畴之内。"
text5 = "每日班前做好设备巡检，排查线路与机械运行隐患。"
text6 = "新入职员工完成岗前培训，方可正式上岗开展工作。"
text7 = "办公区域做到人走断电，自觉落实节能降耗要求。"
documents = [text1, text2, text3, text4, text5, text6, text7]
embeddings = api_client.get_embeddings(documents)

collection.add(
    ids=["1", "2", "3", "4", "5", "6", "7"],
    documents=documents,
    embeddings=embeddings
)

# 查询集合中的数据
query_embeddings = api_client.get_embeddings(["申请人报销由部门负责人签字后提交财务处。"])
results = collection.query(
    query_embeddings=query_embeddings,
    n_results=5
)

# 打印查询结果
print(results)
print(collection.count())
# for result in results["ids"]:
#     print(f"ID: {result}")
