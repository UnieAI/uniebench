#!/bin/sh
python3 benchmark/autotest_simple.py \
  --benchmark-task vlm \
  --service-dir /workspace/nctu6/ascend/service_test \
  --dataset-path lmms-lab/VQAv2 \
  --hf-split validation \
  --result-dir ./results \
  --concurrency 1,16,32,64,128,256,512
