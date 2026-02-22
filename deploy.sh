source ./.env

uv pip compile pyproject.toml -o src/requirements.txt
gcloud -q components update
gcloud secrets versions add PUB_SLACK_SECRETS --data-file=secrets.json --project=radiant-voyage-325608
DEPLOY_OUTPUT=$(gcloud functions deploy ${FUNCTION_NAME} \
	--gen2 \
	--region=asia-northeast1 \
	--runtime=python312 \
	--trigger-http \
	--allow-unauthenticated \
	--timeout=3s \
	--min-instances=0 \
	--max-instances=30 \
	--memory=256Mi \
	--source=src/ \
	--entry-point=main \
	--service-account ${SERVICE_ACCOUNT} \
	--set-secrets SECRETS=${SECRETS_MANAGER} 2>&1)

if [ $? -eq 0 ]; then
	osascript -e "display notification \"Deployment succeeded.\" with title \"Visual Studio Code\" subtitle \"✅ Cloud Function ${FUNCTION_NAME} deployment.\" sound name \"Bell\""

	SCHEDULER_JOB_NAME="feed-digest-6hourly"
	SCHEDULER_ENDPOINT="https://asia-northeast1-radiant-voyage-325608.cloudfunctions.net/${FUNCTION_NAME}/feed_digest"

	if gcloud scheduler jobs describe ${SCHEDULER_JOB_NAME} --location=asia-northeast1 > /dev/null 2>&1; then
		gcloud scheduler jobs update http ${SCHEDULER_JOB_NAME} \
			--location=asia-northeast1 \
			--schedule="0 */6 * * *" \
			--time-zone="Asia/Tokyo" \
			--uri="${SCHEDULER_ENDPOINT}" \
			--http-method=POST \
			--oidc-service-account-email=${SERVICE_ACCOUNT} \
			--oidc-token-audience="${SCHEDULER_ENDPOINT}"
	else
		gcloud scheduler jobs create http ${SCHEDULER_JOB_NAME} \
			--location=asia-northeast1 \
			--schedule="0 */6 * * *" \
			--time-zone="Asia/Tokyo" \
			--uri="${SCHEDULER_ENDPOINT}" \
			--http-method=POST \
			--oidc-service-account-email=${SERVICE_ACCOUNT} \
			--oidc-token-audience="${SCHEDULER_ENDPOINT}"
	fi
else
	ERROR_MESSAGE=$(echo "$DEPLOY_OUTPUT" | head -n 1 )
	osascript -e "display notification \"Deployment failed: ${ERROR_MESSAGE}\" with title \"Visual Studio Code\" subtitle \"❌ Cloud Function ${FUNCTION_NAME} deployment.\" sound name \"Basso\""
	echo "Deployment failed for ${FUNCTION_NAME}."
	echo "Error: ${ERROR_MESSAGE}"
fi
date
