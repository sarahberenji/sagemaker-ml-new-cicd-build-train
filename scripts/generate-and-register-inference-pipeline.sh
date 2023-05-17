#!/bin/bash
set -euox pipefail
PACKAGE_GROUP_NAME=$1 #MODEL_PACKAGE_GROUP_NAME
APPROVAL_STATUS=$2 #PendingManualApproval/Approved

PIPELINE_ARGS=$( jq -n \
                  --arg region "${AWS_REGION}" \
                  --arg project_name "${SAGEMAKER_PROJECT_NAME}" \
                  --arg pipeline_name "${PIPELINE_NAME}" \
                  --arg model_package_group_name "${SAGEMAKER_PROJECT_NAME_ID}" \
                  --arg base_job_prefix "${PIPELINE_NAME}" \
                  --arg revision "${SOURCE_HEADHASH}" \
                  --arg source_scripts_path "${SOURCE_SCRIPTS_PATH}" \
                  --arg model_arn "${model_arn}" \
                  '{
                  region: $region,
                  project_name: $project_name,
                  pipeline_name: $pipeline_name ,
                  model_package_group_name: $model_package_group_name ,
                  base_job_prefix:$base_job_prefix ,
                  revision: $revision ,
                  source_scripts_path: $source_scripts_path ,
                  model_arn: $model_arn
                  }' )
echo "Pipeline Arguments"
echo $PIPELINE_ARGS

get-pipeline-definition \
  --module-name ml_pipelines.inference.standard_model.batch.pipeline \
  --file-name temp/pipeline.json \
  --kwargs "${PIPELINE_ARGS}"

aws s3 cp temp/pipeline.json "s3://${MODEL_BUCKET}/${PIPELINE_PATH}"

echo ">> Register inference pipeline as model package"
IMAGE=662702820516.dkr.ecr.eu-north-1.amazonaws.com/sagemaker-xgboost:1.0-1-cpu-py3
INFERENCE_SPEC="{\"Containers\":[{\"Image\":\"${IMAGE}\",\"ModelDataUrl\":\"s3://${MODEL_BUCKET}/${PIPELINE_PATH}\"}],\"SupportedContentTypes\":[\"text/csv\"],\"SupportedResponseMIMETypes\":[\"text/csv\"]}"
aws sagemaker create-model-package \
  --model-package-group-name "${PACKAGE_GROUP_NAME}" \
  --model-package-description "Inference Pipeline rev. ${SOURCE_HEADHASH}" \
  --inference-specification $INFERENCE_SPEC \
  --model-approval-status "$APPROVAL_STATUS" \
  --customer-metadata-properties git_revision="${SOURCE_HEADHASH}",model_1_revision="${MODEL_GIT_REVISION}",model_1_arn="${model_arn}",model_1_pipeline_id="${MODEL_PIPELINE_ID}" \
  --region $AWS_REGION