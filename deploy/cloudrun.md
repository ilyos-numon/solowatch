# 공개 데모 배포 런북 (Supabase 호스팅 + Cloud Run)

데모 서버(가상 집 + 분할 화면 데모 페이지 + 가족 앱)를 컨테이너 하나로 Cloud Run 에 올리고,
데이터·인증·웹 푸시는 Supabase 무료 프로젝트가 맡는다. 한 번 구성하면 `main` 에 push 할 때마다
`.github/workflows/deploy-cloudrun.yml` 이 이미지를 다시 빌드해 배포한다.

- `<…>` 는 자리표시다. 실제 값으로 바꿔 실행한다. 키·비밀번호를 파일이나 커밋에 남기지 않는다.
- 명령은 저장소 루트에서 실행한다. 필요한 CLI: `supabase`, `psql`, `gcloud`, `docker`, `gh`, `node`(npx).

## 0. 이름과 값

| 항목 | 값 |
|---|---|
| GCP 프로젝트 | `<gcp-project-id>` (예: `solowatch-demo`) |
| 리전 | `asia-northeast3` |
| Cloud Run 서비스 | `solowatch-demo` |
| Artifact Registry 저장소 | `cloud-run-source-deploy` |
| 배포 SA (GitHub Actions) | `gh-deploy@<gcp-project-id>.iam.gserviceaccount.com` |
| 런타임 SA (Cloud Run) | `solowatch-run@<gcp-project-id>.iam.gserviceaccount.com` |
| Secret Manager | `supabase-service-role` |
| Supabase 프로젝트 | `<ref>` (리전 ap-northeast-2, 무료 등급) |
| GitHub 저장소 | `<owner>/<repo>` |

먼저 셸에 자리표시 값을 넣어 둔다 (값은 화면에 출력하지 않는다).

```bash
export GCP_PROJECT_ID='<gcp-project-id>'
export GCP_REGION='asia-northeast3'
export GH_REPO='<owner>/<repo>'
export SUPABASE_REF='<ref>'
```

## 1. Supabase 호스팅

### 1.1 프로젝트 만들기·연결

대시보드(https://supabase.com/dashboard)에서 새 프로젝트를 만든다: 리전 `ap-northeast-2`, 무료 등급.
DB 비밀번호는 비밀번호 관리자에 둔다.

```bash
supabase login
supabase link --project-ref "$SUPABASE_REF"
supabase db push
```

### 1.2 시드와 호스팅용 Vault 값

`Project Settings → Database → Connection string (URI)` 를 `SUPABASE_DB_URL` 로 둔다.

```bash
export SUPABASE_DB_URL='<postgresql://postgres.<ref>:<db-password>@<pooler-host>:5432/postgres>'
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f supabase/seed.sql
```

`seed.sql` 의 Vault 3 줄은 로컬 값이다. 호스팅 값으로 덮어쓴다.
`push_alert_bearer` 는 호스팅 anon key (`Project Settings → API → anon public`),
`push_alert_secret` 은 새로 만든 임의 문자열이고 1.4 의 `PUSH_ALERT_SECRET` 과 같아야 한다.

```bash
export PUSH_ALERT_SECRET="$(openssl rand -hex 24)"
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 \
  -v url="https://$SUPABASE_REF.supabase.co/functions/v1/push-alert" \
  -v bearer='<hosted-anon-key>' \
  -v secret="$PUSH_ALERT_SECRET" <<'SQL'
select vault.update_secret((select id from vault.secrets where name = 'push_alert_url'), :'url');
select vault.update_secret((select id from vault.secrets where name = 'push_alert_bearer'), :'bearer');
select vault.update_secret((select id from vault.secrets where name = 'push_alert_secret'), :'secret');
SQL
```

시드의 데모 계정: 가족 `family@example.com`, 가정 기기 `device@example.com`, 비밀번호 `solowatch-demo-1234`.
가족 계정은 번들에 들어가 공개된다 (RLS 로 데모 가구만 접근). 기기 계정 비밀번호는 바꾸는 편이 낫다:
`Authentication → Users → device@example.com → Reset password` 후 새 값을 2.6 의 `SOLOWATCH_DEVICE_PASSWORD` 로 쓴다.

### 1.3 Edge Function 배포

```bash
supabase functions deploy push-alert --no-verify-jwt
```

### 1.4 Edge Function 시크릿

VAPID 키를 만든다 (계정 불필요). 공개 키는 GitHub 변수 `VITE_VAPID_PUBLIC_KEY` 에도 쓴다.

```bash
npx -y web-push generate-vapid-keys --json > /tmp/vapid.json   # 저장소 밖에 둔다
supabase secrets set \
  VAPID_SUBJECT='mailto:<contact@example.com>' \
  VAPID_PUBLIC_KEY='<vapid-public-key>' \
  VAPID_PRIVATE_KEY='<vapid-private-key>' \
  PUSH_ALERT_SECRET="$PUSH_ALERT_SECRET"
rm /tmp/vapid.json
```

`SUPABASE_URL`·`SUPABASE_SERVICE_ROLE_KEY` 는 호스팅 Edge Function 에 자동으로 들어가므로 넣지 않는다.

## 2. GCP

### 2.1 프로젝트·결제·API

```bash
gcloud projects create "$GCP_PROJECT_ID"
gcloud billing accounts list
gcloud billing projects link "$GCP_PROJECT_ID" --billing-account '<billing-account-id>'
gcloud config set project "$GCP_PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  iamcredentials.googleapis.com secretmanager.googleapis.com
```

예산 알림(선택): `gcloud billing budgets create --billing-account '<billing-account-id>' --display-name solowatch-demo --budget-amount 5USD --threshold-rule percent=0.5 --threshold-rule percent=1.0`

### 2.2 Artifact Registry

```bash
gcloud artifacts repositories create cloud-run-source-deploy \
  --repository-format docker --location "$GCP_REGION"
# 오래된 이미지는 최근 3개만 남긴다
cat > /tmp/ar-cleanup.json <<'JSON'
[{"name":"keep-3","action":{"type":"Keep"},"mostRecentVersions":{"keepCount":3}},
 {"name":"delete-old","action":{"type":"Delete"},"condition":{"tagState":"any","olderThan":"1d"}}]
JSON
gcloud artifacts repositories set-cleanup-policies cloud-run-source-deploy \
  --location "$GCP_REGION" --policy /tmp/ar-cleanup.json --no-dry-run
```

### 2.3 서비스 계정·Secret Manager

```bash
PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format 'value(projectNumber)')
DEPLOY_SA="gh-deploy@$GCP_PROJECT_ID.iam.gserviceaccount.com"
RUN_SA="solowatch-run@$GCP_PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create gh-deploy --display-name 'GitHub deploy'
gcloud iam service-accounts create solowatch-run --display-name 'solowatch-demo runtime'

for role in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member "serviceAccount:$DEPLOY_SA" --role "$role" --condition None
done
gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" \
  --member "serviceAccount:$DEPLOY_SA" --role roles/iam.serviceAccountUser

# 서비스 롤 키: Supabase Project Settings → API → service_role. 표준 입력으로만 넘긴다.
printf '%s' '<hosted-service-role-key>' | \
  gcloud secrets create supabase-service-role --replication-policy automatic --data-file=-
gcloud secrets add-iam-policy-binding supabase-service-role \
  --member "serviceAccount:$RUN_SA" --role roles/secretmanager.secretAccessor
```

### 2.4 Workload Identity Federation (`main` 브랜치만)

```bash
gcloud iam workload-identity-pools create github --location global --display-name GitHub
gcloud iam workload-identity-pools providers create-oidc github-oidc \
  --location global --workload-identity-pool github \
  --issuer-uri 'https://token.actions.githubusercontent.com' \
  --attribute-mapping 'google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref' \
  --attribute-condition "assertion.repository == '$GH_REPO' && assertion.ref == 'refs/heads/main'"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GH_REPO"

WIF_PROVIDER="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github-oidc"
```

### 2.5 이미지 빌드 값 (공개 값만)

빌드 ARG 5 개는 브라우저 번들에 그대로 들어가는 공개 값이다. 서비스 롤 키·기기 비밀번호를 여기에 넣지 않는다.

```bash
export VITE_SUPABASE_URL="https://$SUPABASE_REF.supabase.co"
export VITE_SUPABASE_ANON_KEY='<hosted-anon-key>'
export VITE_DEMO_EMAIL='family@example.com'
export VITE_DEMO_PASSWORD='solowatch-demo-1234'
export VITE_VAPID_PUBLIC_KEY='<vapid-public-key>'
```

### 2.6 첫 배포 (env·시크릿을 서비스에 심는다)

워크플로는 env 를 건드리지 않고 이미지만 바꾸므로, 첫 배포는 손으로 env 와 시크릿을 넣는다.
Cloud Run 은 `linux/amd64` 이미지가 필요하다 (Apple Silicon 에서는 `--platform` 필수).

```bash
IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/cloud-run-source-deploy/solowatch-demo:first"
gcloud auth configure-docker "$GCP_REGION-docker.pkg.dev" --quiet
docker buildx build --platform linux/amd64 -t "$IMAGE" --push \
  --build-arg VITE_SUPABASE_URL --build-arg VITE_SUPABASE_ANON_KEY \
  --build-arg VITE_DEMO_EMAIL --build-arg VITE_DEMO_PASSWORD --build-arg VITE_VAPID_PUBLIC_KEY .

gcloud run deploy solowatch-demo \
  --image "$IMAGE" --region "$GCP_REGION" --service-account "$RUN_SA" \
  --allow-unauthenticated --port 8080 \
  --cpu 1 --memory 1Gi --min-instances 0 --max-instances 1 \
  --concurrency 20 --timeout 300 --cpu-boost \
  --set-env-vars "SUPABASE_URL=https://$SUPABASE_REF.supabase.co,SUPABASE_ANON_KEY=<hosted-anon-key>,SOLOWATCH_DEVICE_EMAIL=device@example.com,SOLOWATCH_DEVICE_PASSWORD=<device-password>" \
  --set-secrets "SUPABASE_SERVICE_ROLE_KEY=supabase-service-role:latest"

DEMO_URL=$(gcloud run services describe solowatch-demo --region "$GCP_REGION" --format 'value(status.url)')
curl -s "$DEMO_URL/api/demo/state" | jq .ready   # true (콜드스타트 직후 30 초쯤은 false). /healthz 는 Cloud Run 이 막는 경로라 404
curl -s -o /dev/null -w '%{http_code}\n' "$DEMO_URL/demo"   # 200
```

### 2.7 GitHub 변수 10 개

모두 공개되어도 되는 값이라 Secrets 가 아니라 Variables 에 둔다.

```bash
gh variable set GCP_PROJECT_ID        -R "$GH_REPO" --body "$GCP_PROJECT_ID"
gh variable set GCP_REGION            -R "$GH_REPO" --body "$GCP_REGION"
gh variable set GCP_WIF_PROVIDER      -R "$GH_REPO" --body "$WIF_PROVIDER"
gh variable set GCP_DEPLOY_SA         -R "$GH_REPO" --body "$DEPLOY_SA"
gh variable set VITE_SUPABASE_URL     -R "$GH_REPO" --body "$VITE_SUPABASE_URL"
gh variable set VITE_SUPABASE_ANON_KEY -R "$GH_REPO" --body "$VITE_SUPABASE_ANON_KEY"
gh variable set VITE_DEMO_EMAIL       -R "$GH_REPO" --body "$VITE_DEMO_EMAIL"
gh variable set VITE_DEMO_PASSWORD    -R "$GH_REPO" --body "$VITE_DEMO_PASSWORD"
gh variable set VITE_VAPID_PUBLIC_KEY -R "$GH_REPO" --body "$VITE_VAPID_PUBLIC_KEY"
gh variable set DEMO_URL              -R "$GH_REPO" --body "$DEMO_URL"
```

확인:

```bash
gh workflow run deploy-cloudrun -R "$GH_REPO" --ref main
gh workflow run keepalive -R "$GH_REPO" --ref main
gh run list -R "$GH_REPO" --limit 2
```

`GCP_PROJECT_ID` 나 `GCP_WIF_PROVIDER` 가 비어 있으면 배포 워크플로는 notice 만 남기고 건너뛴다.
`DEMO_URL` 이 비어 있으면 keepalive 도 건너뛴다.

## 3. 비용·일시정지·초기화

- **Cloud Run**: `min-instances 0` 이라 방문이 없으면 0 원. 요청이 오면 콜드스타트(가상 28 일 시뮬레이션 포함, 수 초)
  동안 데모 페이지가 "준비 중" 을 보여준다. `max-instances 1` 이라 폭주해도 인스턴스 1 개 비용이 상한이다.
- **Artifact Registry**: 이미지 1 개 약 0.7 GB, 정리 정책으로 3 개만 유지 → 월 수십 원 수준.
- **Secret Manager**: 활성 버전 6 개까지 무료 범위.
- **Supabase 무료 등급**: 7 일 동안 요청이 없으면 일시정지된다. `keepalive.yml` 이 3 일마다
  `GET $DEMO_URL/api/demo/state` 로 데모 서버를 깨우고, 데모 서버가 Supabase 를 호출한다.
  그래도 정지되면 대시보드에서 `Restore project` 를 누른다 (가족 앱에는 잠듦 배너가 뜬다).
- **초기화**: 방문자는 데모 페이지의 `초기화` 버튼으로 가상 가구를 처음 상태로 되돌린다. 가상 14 일이 지나면 자동 초기화되고,
  Cloud Run 인스턴스가 새로 뜰 때도 초기화된다.
- **일시 중지(비용 0 유지)**: 공개를 잠깐 막으려면
  `gcloud run services remove-iam-policy-binding solowatch-demo --region "$GCP_REGION" --member allUsers --role roles/run.invoker`,
  다시 열 때는 `add-iam-policy-binding` 같은 인자로.

## 4. 회수 (전부 지우기)

```bash
gh variable delete DEMO_URL -R "$GH_REPO"   # keepalive 먼저 멈춤
for v in GCP_PROJECT_ID GCP_REGION GCP_WIF_PROVIDER GCP_DEPLOY_SA VITE_SUPABASE_URL \
         VITE_SUPABASE_ANON_KEY VITE_DEMO_EMAIL VITE_DEMO_PASSWORD VITE_VAPID_PUBLIC_KEY; do
  gh variable delete "$v" -R "$GH_REPO"
done

gcloud run services delete solowatch-demo --region "$GCP_REGION" --quiet
gcloud artifacts repositories delete cloud-run-source-deploy --location "$GCP_REGION" --quiet
gcloud secrets delete supabase-service-role --quiet
gcloud iam workload-identity-pools delete github --location global --quiet
gcloud iam service-accounts delete "$DEPLOY_SA" --quiet
gcloud iam service-accounts delete "$RUN_SA" --quiet
# 프로젝트째 지우면 위 항목도 함께 사라진다 (30 일 뒤 영구 삭제)
gcloud projects delete "$GCP_PROJECT_ID" --quiet
```

Supabase: 대시보드 `Project Settings → General → Delete project`. 로컬 연결 정보는 `supabase unlink`.
README 의 공개 URL 줄도 함께 지운다.
