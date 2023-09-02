source ./.env

gcloud functions deploy ${FUNCTION_NAME} \
	--gen2 \
	--region=asia-northeast1 \
	--runtime=python311 \
	--trigger-http \
	--allow-unauthenticated \
	--timeout=3s \
	--min-instances=1 \
	--max-instances=30 \
	--memory=256Mi \
	--source=src/ \
	--entry-point=main \
	--service-account ${SERVICE_ACCOUNT} \
	--set-secrets SECRETS=${SECRETS_MANAGER}
	