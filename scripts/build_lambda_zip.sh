#!/usr/bin/env bash
# Gera dist/caderno-lambda.zip (código + ask-sdk-core) para subir em uma função AWS Lambda
# (Python 3.12, handler: lambda_function.lambda_handler). Não precisa para skills Alexa-hosted.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf dist/build && mkdir -p dist/build
pip install -q -r lambda/requirements.txt -t dist/build
cp lambda/lambda_function.py lambda/storage.py dist/build/
(cd dist/build && python3 -m zipfile -c ../caderno-lambda.zip . >/dev/null)
rm -rf dist/build
echo "Pronto: dist/caderno-lambda.zip ($(du -h dist/caderno-lambda.zip | cut -f1))"
