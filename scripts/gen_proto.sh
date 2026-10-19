#!/usr/bin/env bash
# Regenerate Python bindings for backend/proto/*.proto.
# Requires grpcio-tools (pip install -r backend/requirements-dev.txt).
set -euo pipefail
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc \
  -I . \
  --python_out=. \
  --pyi_out=. \
  backend/proto/test_result.proto
echo "generated backend/proto/test_result_pb2.py"
