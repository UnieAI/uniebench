# 基礎映像
FROM openmmlab/lmdeploy:latest-cu12.8

# 確保系統套件是最新的，並安裝 git 和 python3-venv (以防基礎映像缺少 venv 模組)
# 如果基礎映像非 root 使用者，可能需要先切換 USER root，但通常這類映像預設為 root
RUN apt-get update && apt-get install -y \
    git \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 1. Git clone 並切換分支
# 使用 --depth 1 可以減少映像檔大小，但若需完整歷史可移除該參數
RUN git clone https://github.com/nctu6/vllm.git \
    && cd vllm \
    && git checkout turbomind

# 切換到 vllm 目錄
WORKDIR /app/vllm

# 2. 建立 Python 虛擬環境
RUN python3 -m venv .venv

# 3. 啟用虛擬環境
# 在 Docker 中，我們通過設定環境變數來達到 "source activate" 的效果
# 這確保後續的 RUN 指令和容器啟動後的 CMD 都在此 venv 中執行
ENV VIRTUAL_ENV=/app/vllm/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 4. 安裝 PyTorch
RUN pip install --no-cache-dir torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128

# 5. 安裝建置依賴 (修正點：加入 ninja 和 cmake)
# vLLM 編譯高度依賴 ninja，且 --no-build-isolation 模式下必須手動安裝
RUN pip install --no-cache-dir -U pip packaging setuptools wheel setuptools-scm ninja cmake>=3.26

# 5.1 (選用) 避免 OOM：限制編譯時的並行作業數
# vLLM 編譯非常消耗記憶體，若不限制可能會導致 docker build 被 kill
ENV MAX_JOBS=4
ENV NVCC_THREADS=4

# 6. 安裝 vllm
# 建議加入 -v 以便在再次失敗時能看到具體的錯誤日誌
# 如果您的 vllm fork 包含 'use_existing_torch.py' 或類似腳本，建議先執行它以放寬版本檢查
RUN pip install --no-build-isolation -v -e .

# 設定預設指令
CMD ["bash"]
