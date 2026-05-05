#!/bin/sh

: "${DATASET_NAME:=hf}"
: "${DATASET_PATH:=edinburghcstr/ami}"
: "${HF_SUBSET:=ihm}"
: "${HF_SPLIT:=test}"
: "${BACKEND:=openai-audio}"
: "${ENDPOINT:=/v1/audio/transcriptions}"
: "${RESULT_DIR:=./results}"
: "${CONCURRENCY:=1,16,32,64,128,256,512}"

python3 benchmark/autotest_simple.py \
  --service-dir /workspace/nctu6/ascend/service_test \
  --dataset-name "$DATASET_NAME" \
  --dataset-path "$DATASET_PATH" \
  --hf-subset "$HF_SUBSET" \
  --hf-split "$HF_SPLIT" \
  --backend "$BACKEND" \
  --endpoint "$ENDPOINT" \
  --concurrency "$CONCURRENCY" \
  --trust-remote-code \
  --result-dir "$RESULT_DIR"
#  --with-container \
#  --port 8976 \
#  --service-name test \
#  --tokenizer /models/openai/whisper-large-v3-turbo \
#  --debug-break
