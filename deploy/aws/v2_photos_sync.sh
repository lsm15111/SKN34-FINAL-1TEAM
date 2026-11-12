#!/usr/bin/env bash
# v2 상담 화면 사진(frontend/public/v2/img, 579장)을 S3에 올린다. 저장소 루트에서 실행한다.
#   deploy/aws/v2_photos_sync.sh <버킷> [경로, 기본 v2/img]
# 버킷은 infra/aws/v2-photos.yaml 스택(mitjip-v2-photos)이 만든다. 올린 뒤 화면 서버(web)의 V2_IMG_BASE를 스택 출력 ImageBaseUrl로 둔다.
# '우리 집에 칠해 보기' 그림은 사진을 canvas로 읽으므로 버킷(또는 CDN)이 화면 주소에서 오는 GET을 CORS로 허락해야 한다.
set -euo pipefail
BUCKET="${1:?버킷 이름을 넣어 주세요}"
PREFIX="${2:-v2/img}"
case "$PREFIX" in -*) echo "두 번째 값은 경로예요(옵션을 받지 않아요): $PREFIX" >&2; exit 2 ;; esac
aws s3 sync frontend/public/v2/img "s3://${BUCKET}/${PREFIX}" \
  --exclude "*" --include "*.jpg" \
  --content-type image/jpeg \
  --cache-control "public, max-age=31536000, immutable"
