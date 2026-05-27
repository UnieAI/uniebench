#!/bin/sh
python3 benchmark/autotest_simple.py \
  --benchmark-task embedding \
  --service-dir /workspace/nctu6/ascend/service_test \
  --dataset-path BeIR/scifact \
  --hf-subset corpus \
  --hf-split corpus \
  --result-dir ./results \
  --concurrency 1,16,32,64,128,256,512
