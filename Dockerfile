FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制代码
COPY rag_engine.py app.py ./

# 创建数据目录
RUN mkdir -p chroma_db

EXPOSE 8000

# 设置HuggingFace镜像
ENV HF_ENDPOINT=https://hf-mirror.com

CMD ["python", "app.py"]
