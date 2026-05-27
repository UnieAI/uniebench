#!/bin/sh
python3 benchmark/autotest_simple.py \
  --benchmark-task vlm \
  --dataset-path lmms-lab/VQAv2 \
  --hf-split validation \
  --with-container \
  --base-url http://localhost:8986 \
  --tokenizer /models/Qwen/Qwen3.5-9B \
  --service-name test \
  --result-dir ./results \
  --concurrency 1,16,32,64,128,256,512
