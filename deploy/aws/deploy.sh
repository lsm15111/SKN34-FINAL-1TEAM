#!/usr/bin/env bash
# EC2 SSM에서만 실행한다. 이미지 버전을 고정하고 실패하면 이전 버전으로 되돌린다.
set -Eeuo pipefail
umask 077

ROOT=/opt/mitjip
REGION=ap-northeast-2
STACK=mitjip-staging
HOST=mitjip.13-209-178-19.sslip.io
REPO=SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM
mkdir -p "$ROOT"
cd "$ROOT"
exec 9>/var/lock/mitjip-deploy.lock
flock -w 60 9 || { echo "Another deployment is running"; exit 1; }

compose() {
  docker compose --env-file "$ROOT/.env.release" -f "$ROOT/compose.deploy.yaml" "$@"
}

smoke() {
  local attempt
  for attempt in $(seq 1 40); do
    if curl --fail --silent --max-time 6 "https://$HOST/api/health/ready" > /dev/null \
      && curl --fail --silent --max-time 6 "https://$HOST/login" > /dev/null; then
      echo "HTTPS, web and API readiness OK"
      return 0
    fi
    if (( attempt % 10 == 0 )); then echo "HTTPS readiness retry $attempt"; fi
    sleep 4
  done
  return 1
}

restore_previous() {
  if [[ ! -s .env.previous-release ]]; then
    echo "No previous release exists; preserving diagnostic containers"
    return 1
  fi
  cp .env.previous-release .env.release
  if [[ -s compose.previous.yaml ]]; then cp compose.previous.yaml compose.deploy.yaml; fi
  if [[ -s Caddyfile.previous ]]; then cp Caddyfile.previous Caddyfile; fi
  compose up -d --wait --wait-timeout 180 redis api worker web caddy
  smoke
  echo "Restored previous container images (DB schema migrations are not reversed)"
}

if [[ "${1:-}" == "--rollback" ]]; then
  restore_previous
  exit 0
fi

SHA="${1:?Commit SHA required}"
if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then echo "Invalid commit SHA"; exit 1; fi

# 외부 EC2 접근 정보나 비밀번호를 GitHub Secrets로 복사하지 않는다.
cfout() {
  aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text
}
DB_HOST="$(cfout DatabaseEndpoint)"
DB_SECRET="$(cfout DatabaseSecretArn)"
S3_BUCKET="$(cfout FileBucketName)"
API_REPO="$(cfout ApiRepositoryUri)"
WEB_REPO="$(cfout WebRepositoryUri)"
[[ -n "$DB_HOST" && -n "$DB_SECRET" && -n "$S3_BUCKET" && -n "$API_REPO" && -n "$WEB_REPO" ]]

aws secretsmanager get-secret-value --secret-id "$DB_SECRET" --region "$REGION" \
  --query SecretString --output text | \
  MITJIP_DB_HOST="$DB_HOST" MITJIP_S3_BUCKET="$S3_BUCKET" MITJIP_HOST="$HOST" python3 -c '
import json, os, sys
from urllib.parse import quote
s = json.load(sys.stdin)
u = quote(s["username"], safe="")
p = quote(s["password"], safe="")
h = os.environ["MITJIP_DB_HOST"]
print("APP_ENV=staging")
print("API_ROOT_PATH=/api")
print("DATABASE_URL=postgresql+asyncpg://" + u + ":" + p + "@" + h + ":5432/mitjip")
print("REDIS_URL=redis://redis:6379/0")
print("FILES_S3_BUCKET=" + os.environ["MITJIP_S3_BUCKET"])
print("AWS_DEFAULT_REGION=ap-northeast-2")
print("ALLOWED_ORIGINS=https://" + os.environ["MITJIP_HOST"])
print("LLM_LIVE=false")
# 시연 업체 자동 응답(worker). 시연 계정(app/demo.py)에만 하고, 끄려면 false로 바꾼다
print("DEMO_AUTO=true")
' > .env.runtime.new
chmod 600 .env.runtime.new

# 공식 main에서 CI가 통과한 커밋의 배포 파일만 가져온다.
for f in compose.deploy.yaml Caddyfile; do
  curl -fLsS --retry 3 "https://raw.githubusercontent.com/$REPO/$SHA/deploy/aws/$f" -o "$f.new"
done

aws ecr get-login-password --region "$REGION" | docker login \
  --username AWS --password-stdin "${API_REPO%%/*}"

if [[ -s .env.release ]]; then
  cp .env.release .env.previous-release
  cp compose.deploy.yaml compose.previous.yaml
  cp Caddyfile Caddyfile.previous
fi
mv .env.runtime.new .env.runtime
mv compose.deploy.yaml.new compose.deploy.yaml
mv Caddyfile.new Caddyfile
printf 'API_IMAGE=%s\nWEB_IMAGE=%s\nDEPLOY_HOSTNAME=%s\n' \
  "$API_REPO:$SHA" "$WEB_REPO:$SHA" "$HOST" > .env.release

on_error() {
  local status=$?
  trap - ERR
  echo "Deployment failed with status $status"
  if [[ -s .env.previous-release ]]; then
    if ! restore_previous; then echo "Automatic image rollback also failed"; fi
  fi
  exit "$status"
}
trap on_error ERR

compose config --quiet
compose pull api worker web redis caddy
# 변경을 적용하기 전에 DB 스키마부터 올린다. 실패하면 기존 앱은 유지한다.
compose run --rm migrate
compose up -d --wait --wait-timeout 180 redis api worker web caddy
smoke
printf '%s\n' "$SHA" > current-sha
echo "Deployment succeeded at commit $SHA"
