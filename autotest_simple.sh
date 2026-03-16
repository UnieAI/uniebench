#!/bin/sh
python3 benchmark/autotest_simple.py \
  --service-dir /workspace/nctu6/ascend/service_test \
  --dataset-path ./data/ShareGPT_V3_unfiltered_cleaned_split.json \
  --result-dir ./results \
  --concurrency 1,2 \
  --debug-break

