#!/bin/bash
set -euox pipefail
echo "Get ARN for latest package in model group"
#
PACKAGE_GROUP_NAME=$1 #MODEL_PACKAGE_GROUP_NAME
APPROVAL_STATUS=$2 #PendingManualApproval
echo PACKAGE_GROUP_NAME: $PACKAGE_GROUP_NAME , APPROVAL: $APPROVAL_STATUS
#model_arn=$(aws-vault exec cirrus-ml-dev -- aws sagemaker list-model-packages --model-package-group ml-batch-train-dev-p-fduveu18mmpw --query "ModelPackageSummaryList[?ModelApprovalStatus==\`PendingManualApproval\`].ModelPackageArn | [0]" --output text)
model_arn=$(aws sagemaker list-model-packages --model-package-group ${PACKAGE_GROUP_NAME} --query "ModelPackageSummaryList[?ModelApprovalStatus==\`${APPROVAL_STATUS}\`].ModelPackageArn | [0]" --output text)
echo "Get s3 URI to inference pipeline"
# aws-vault exec cirrus-ml-dev -- aws sagemaker describe-model-package --model-package-name ${model_arn} --query 'InferenceSpecification.Containers[0].ModelDataUrl' --output text
MODEL_GIT_REVISION=$(aws sagemaker describe-model-package --model-package-name ${model_arn} --query 'CustomerMetadataProperties.git_revision' --output text)
SOURCE_SCRIPTS_PATH_MODEL=$(aws sagemaker describe-model-package --model-package-name ${model_arn} --query 'CustomerMetadataProperties.source_scripts_path' --output text)
MODEL_PIPELINE_ID=$(aws sagemaker describe-model-package --model-package-name ${model_arn} --query 'CustomerMetadataProperties.pipeline_execution_id' --output text)

PREPROCESS_PATH=$(aws sagemaker describe-model-package --model-package-name ${model_arn} --query 'CustomerMetadataProperties.preprocess' --output text)
POSTPROCESS_PATH=$(aws sagemaker describe-model-package --model-package-name ${model_arn} --query 'CustomerMetadataProperties.postprocess' --output text)
PIPELINE_S3_URI_MODEL_MREG=$(aws sagemaker describe-model-package --model-package-name ${model_arn} --query 'InferenceSpecification.Containers[0].ModelDataUrl' --output text)
MODEL_BUCKET_MREG=$(awk '{ sub(/.*s3:\/\//, ""); sub(/\/.*/, ""); print}' <<< $PIPELINE_S3_URI_MODEL_MREG)
PIPELINE_PATH_MREG=${PIPELINE_S3_URI_MODEL_MREG#"s3://$MODEL_BUCKET_MREG/"}
printf "PIPELINE_S3_URI_MODEL_MREG= $PIPELINE_S3_URI_MODEL_MREG \n MODEL_BUCKET_MREG= $MODEL_BUCKET_MREG \n PIPELINE_PATH_MREG= $PIPELINE_PATH_MREG \n"
