import torch
import json

print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0))

data = {
    "input": ["空降啊魂师对决哈卡建好的"],
    "model": "BAAI/bge-m3"
}

data1 = json.dumps(data)
print(data1)