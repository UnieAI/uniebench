#!/bin/sh
python3 benchmark/autotest_simple.py \
  --service-dir /workspace/nctu6/ascend/service_test \
  --dataset-path neural-bridge/rag-dataset-12000 \
  --result-dir ./results \
  --concurrency 1,16,32,64,128,256,512
#  --with-container \
#  --tokenizer /models/Qwen/Qwen3-8B \
#  --port 8976 \
#  --service-name test \
#  --debug-break
