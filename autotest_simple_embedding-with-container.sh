#!/bin/sh
python3 benchmark/autotest_simple.py \
  --benchmark-task embedding \
  --dataset-path BeIR/scifact \
  --hf-subset corpus \
  --hf-split corpus \
  --with-container \
  --base-url http://localhost:8986 \
  --tokenizer /models/Qwen/Qwen3-Embedding-8B \
  --service-name test \
  --result-dir ./results \
  --concurrency 1,16,32,64,128,256,512
