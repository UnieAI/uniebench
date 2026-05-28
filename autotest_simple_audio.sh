#!/bin/sh
python3 benchmark/autotest_simple.py \
  --benchmark-task audio \
  --service-dir /workspace/nctu6/ascend/service_test \
  --dataset-path adi-gov-tw/Taiwan-Tongues-ASR-CE-dataset-hokkien \
  --hf-split train \
  --result-dir ./results \
  --concurrency 1,16,32,64,128,256,512
