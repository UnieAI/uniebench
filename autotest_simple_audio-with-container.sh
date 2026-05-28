#!/bin/sh
python3 benchmark/autotest_simple.py \
  --benchmark-task audio \
  --dataset-path adi-gov-tw/Taiwan-Tongues-ASR-CE-dataset-hokkien \
  --hf-split train \
  --with-container \
  --base-url http://localhost:8986 \
  --tokenizer /models/openai/whisper-large-v3-turbo \
  --service-name test \
  --result-dir ./results \
  --concurrency 1,16,32,64,128,256,512
