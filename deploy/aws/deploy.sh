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
  if [[ ! -s .env.previous-release || ! -s .env.previous-runtime ]]; then
    echo "No complete previous release configuration exists; preserving diagnostic containers"
    return 1
  fi
  install -m 600 .env.previous-runtime .env.runtime
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

# 공식 main에서 CI가 통과한 커밋의 배포 파일만 가져온다.
for f in compose.deploy.yaml Caddyfile runtime_env.py; do
  curl -fLsS --retry 3 "https://raw.githubusercontent.com/$REPO/$SHA/deploy/aws/$f" -o "$f.new"
done

python3 runtime_env.py.new \
  --region "$REGION" --stack "$STACK" --db-secret-id "$DB_SECRET" \
  --db-host "$DB_HOST" --bucket "$S3_BUCKET" --host "$HOST" \
  --output "$ROOT/.env.runtime.new"

aws ecr get-login-password --region "$REGION" | docker login \
  --username AWS --password-stdin "${API_REPO%%/*}"

if [[ -s .env.release ]]; then
  [[ -s .env.runtime ]] || { echo "Missing active runtime configuration"; exit 1; }
  cp .env.release .env.previous-release
  cp compose.deploy.yaml compose.previous.yaml
  cp Caddyfile Caddyfile.previous
  install -m 600 .env.runtime .env.previous-runtime
fi

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

mv .env.runtime.new .env.runtime
mv compose.deploy.yaml.new compose.deploy.yaml
mv Caddyfile.new Caddyfile
printf 'API_IMAGE=%s\nWEB_IMAGE=%s\nDEPLOY_HOSTNAME=%s\n' \
  "$API_REPO:$SHA" "$WEB_REPO:$SHA" "$HOST" > .env.release

compose config --quiet
compose pull api worker web redis caddy
# 변경을 적용하기 전에 DB 스키마부터 올린다. 실패하면 기존 앱은 유지한다.
compose run --rm migrate
compose up -d --wait --wait-timeout 180 redis api worker web caddy
smoke
printf '%s\n' "$SHA" > current-sha
echo "Deployment succeeded at commit $SHA"
