#!/bin/sh
python3 benchmark/autotest_simple.py \
  --benchmark-task text \
  --dataset-path neural-bridge/rag-dataset-12000 \
  --with-container \
  --base-url http://localhost:8986 \
  --tokenizer /models/Qwen/Qwen3-8B \
  --service-name test \
  --result-dir ./results \
  --concurrency 1,16,32,64,128,256,512
