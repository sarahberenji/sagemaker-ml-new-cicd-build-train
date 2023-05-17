#!/bin/bash
#
################################################################################
# Help                                                                         #
################################################################################
Help()
{
   # Display Help
   echo "Helper script to fetch latest objects from sagemaker training and inference pipelines."
   echo "Built for naming patterns defined by the cirrus sample ml application. If you change the structure you need to adapt this script accordingly"
   echo "Syntax: fetch-latest-run-objects.sh [-s|p|t|i]"
   echo "options:"
   echo "-s --sagemaker-project-name      Required: Sagemaker project name"
   echo "-t --training-pipeline-name      Required: Name of training pipeline"
   echo "-i --inference-pipeline-name     Required: Name of inference pipeline."
   echo "-m --model-package-group-name    Required: Model package group name in sagemaker model registry."
   echo "-p --temp-path                   Optional: Temporary path to store the objects. [Default=temp/latest-executiondata]"
   echo "-c --clear-path                  Optional: Clear the temporary path [Default=false]"
   echo "-d --dry-run                     Optional: Only list s3 objects, dont copy them [Default=false]"

   echo "Example call from root of project: "
   echo "scripts/fetch-latest-run-objects.sh \ "
   echo "  --sagemaker-project-name ml-build-bronze-peter \ "
   echo "  --training-pipeline-name ml-build-bronze-peter-training-pipeline \ "
   echo "  --inference-pipeline-name ml-build-bronze-peter-inference-pipeline \ "
   echo "  --temp-path temp/latest-executiondata \ "
   echo "  --model-package-group-name ml-build-bronze-peter-p-xroyuamhttkm \ "
   echo "  --clear-path"
}
#MODEL_PACKAGE_GROUP_NAME=${7:-"ml-build-bronze-peter-p-xroyuamhttkm"}
# Set arguments
TEMP=$(getopt -o 's:p:t:i:m:chd' --long 'sagemaker-project-name:,training-pipeline-name:,inference-pipeline-name:,model-package-group-name:,help,temp-path:,clear-path,dry-run' -- "$@")

if [ $? -ne 0 ]; then
	echo 'Terminating...' >&2
	exit 1
fi

# Note the quotes around "$TEMP": they are essential!
eval set -- "$TEMP"
unset TEMP
PACKAGE_GROUP_NAME=
while true; do
	case "$1" in
		'-s'|'--sagemaker-project-name')
		  PROJECT_NAME="$2"
			echo "Using Sagemaker Project name:${PROJECT_NAME}"
			shift 2
			continue
		;;
		'-h'|'--help')
			Help
			exit 0
			shift
			continue
		;;
		'-t'|'--training-pipeline-name')
		  TRAINING_PIPELINE_NAME="${2}"
			echo "training-pipeline-name set to ${TRAINING_PIPELINE_NAME}"
			shift 2
			continue
		;;
		'-i'|'--inference-pipeline-name')
		  INFERENCE_PIPELINE_NAME="${2}"
			echo "inference-pipeline-name set to ${INFERENCE_PIPELINE_NAME}"
			shift 2
			continue
		;;
		'-m'|'--model-package-group-name')
		  PACKAGE_GROUP_NAME="${2}"
			echo "model-package-group-name set to ${PACKAGE_GROUP_NAME}"
			shift 2
			continue
		;;
		'-p'|'--temp-path')
		  RELATIVE_PATH="${2}"
			echo "Option temp-path set to ${RELATIVE_PATH}"
			shift 2
			continue
		;;
		'-c'|'--clear-path')
			# c has an optional argument. As we are in quoted mode,
			# an empty parameter will be generated if its optional
			# argument is not found.
      CLEAR_PATH=true
			shift
			continue
		;;
		'-d'|'--dry-run')
			# c has an optional argument. As we are in quoted mode,
			# an empty parameter will be generated if its optional
			# argument is not found.
      DRY_RUN=true
			shift
			continue
		;;

		'--')
			shift
			break
		;;
		*)
			echo 'Internal error!' >&2
			exit 1
		;;
	esac
done
# Set default values
RELATIVE_PATH=${RELATIVE_PATH:="temp/latest-executiondata"}
CLEAR_PATH=${CLEAR_PATH:=false}
DRY_RUN=${DRY_RUN:=false}
# Check if parameters are properly set and give feedback to user in case its not. Use EXIT_FLAG to wait with exit until all parameters
# have been checked
EXIT_FLAG=0
function check_param() {
  if [[ -z "${3}" ]];
    then
      echo -e ">>\e[31m ${1}  variable undefined, please define this variable by setting flag: --${2} \e[0m"
      EXIT_FLAG=1
    else
      echo -e ">>\e[32m ${1}  variable defined as ${3} \e[0m"
  fi
}

check_param PROJECT_NAME  "sagemaker-project-name your-project-name" ${PROJECT_NAME}
check_param TRAINING_PIPELINE_NAME  "training-pipeline-name your-pipeline-name" ${TRAINING_PIPELINE_NAME}
check_param INFERENCE_PIPELINE_NAME  "inference-pipeline-name your-pipeline-name" ${INFERENCE_PIPELINE_NAME}
check_param PACKAGE_GROUP_NAME "model-package-group-name your-model-package-group-name" ${PACKAGE_GROUP_NAME}
# exit if non-optional parameters are unset
if [ $EXIT_FLAG = 1 ]; then
  echo -e "\n>>\e[31m INCORRECT PARAMETERS, PRINTING HELP \e[0m"
  Help
  exit 0
fi

set -euo pipefail

TRAINING_OFFSET="0"
INFERENCE_OFFSET="0"
ENV_TYPE=$(aws ssm get-parameter --name EnvType --query 'Parameter.Value' --output text --region "${AWS_REGION}")
DATA_BUCKET=$(aws ssm get-parameter --name "mlops-${ENV_TYPE}-data-bucket-name" --query 'Parameter.Value' --output text --region "${AWS_REGION}")
DATA_BUCKET="s3://${DATA_BUCKET}"
MODEL_BUCKET=$(aws ssm get-parameter --name "mlops-${ENV_TYPE}-model-bucket-name" --query 'Parameter.Value' --output text --region "${AWS_REGION}")
MODEL_BUCKET="s3://${MODEL_BUCKET}"
ACCOUNT_ID=$(aws sts get-caller-identity --query "[Account]" --output text)


PIPELINE_PACKAGE_GROUP_NAME="$INFERENCE_PIPELINE_NAME"
LATEST_PIPELINE_MODEL_ARN=$(aws sagemaker list-model-packages --model-package-group ${PIPELINE_PACKAGE_GROUP_NAME} --query "ModelPackageSummaryList[*].ModelPackageArn | [0]" --output text)
echo -e "\n>>\e[35m Information on latest inference pipeline $LATEST_PIPELINE_MODEL_ARN . Using ModelFromSMExecution for training pipeline artifacts \e[0m"
aws sagemaker describe-model-package --model-package-name ${LATEST_PIPELINE_MODEL_ARN}  --query "{ModelPackageGroupName:ModelPackageGroupName, CreationTime:CreationTime, PipelineVersion:ModelPackageVersion, ModelGitRevision:CustomerMetadataProperties.model_1_revision, GitRevision:CustomerMetadataProperties.git_revision, ModelFromSMExecution:CustomerMetadataProperties.model_1_pipeline_id}" --output table
MODEL_GIT_REVISION=$(aws sagemaker describe-model-package --model-package-name ${LATEST_PIPELINE_MODEL_ARN}  --query "[CustomerMetadataProperties.model_1_revision]" --output text)
PIPELINE_GIT_REVISION=$(aws sagemaker describe-model-package --model-package-name ${LATEST_PIPELINE_MODEL_ARN}  --query "[CustomerMetadataProperties.git_revision]" --output text)

TRAINING_SM_ID=$(aws sagemaker describe-model-package --model-package-name ${LATEST_PIPELINE_MODEL_ARN} --query "[CustomerMetadataProperties.model_1_pipeline_id]" --output text)
TRAINING_SM_ARN="arn:aws:sagemaker:${AWS_REGION}:${ACCOUNT_ID}:pipeline/${TRAINING_PIPELINE_NAME}/execution/${TRAINING_SM_ID}"
#$(aws sagemaker list-model-packages --model-package-group ${PACKAGE_GROUP_NAME} --query "ModelPackageSummaryList[?ModelApprovalStatus==\`${APPROVAL_STATUS}\`].ModelPackageArn | [0]" --output text)

LATEST_MODEL_ARN=$(aws sagemaker list-model-packages --model-package-group ${PACKAGE_GROUP_NAME} --query "ModelPackageSummaryList[*].ModelPackageArn | [0]" --output text)
LATEST_APPROVED_MODEL_ARN=$(aws sagemaker list-model-packages --model-package-group ${PACKAGE_GROUP_NAME} --query "ModelPackageSummaryList[?ModelApprovalStatus=='Approved'].ModelPackageArn | [0]" --output text)
#aws sagemaker describe-model-package --model-package-name ${LATEST_MODEL_ARN}  --output table #--query 'CustomerMetadataProperties.git_revision' --output text)
echo -e "\n>>\e[35m Information on LATEST_APPROVED_MODEL_ARN:$LATEST_APPROVED_MODEL_ARN \e[0m"
aws sagemaker describe-model-package --model-package-name ${LATEST_APPROVED_MODEL_ARN}  --query "{ModelPackageGroupName:ModelPackageGroupName, CreationTime:CreationTime, ModelVersion:ModelPackageVersion, GitRevision:CustomerMetadataProperties.git_revision, CreatedBySMPipelineExecution:CustomerMetadataProperties.pipeline_execution_id}" --output table

echo -e "\n>>\e[35m Information on LATEST_MODEL_ARN:$LATEST_MODEL_ARN \e[0m NOTE: If this is not the same as LATEST_APPROVED_MODEL_ARN then consider going to the model registry and approving the latest model version"
aws sagemaker describe-model-package --model-package-name ${LATEST_MODEL_ARN}  --query "{ModelPackageGroupName:ModelPackageGroupName, CreationTime:CreationTime, ModelVersion:ModelPackageVersion, GitRevision:CustomerMetadataProperties.git_revision, CreatedBySMPipelineExecution:CustomerMetadataProperties.pipeline_execution_id}" --output table


echo -e "\n>>\e[35m 10 most recent Pipeline Executions for ${TRAINING_PIPELINE_NAME} \e[0m"
aws sagemaker list-pipeline-executions --pipeline-name ${TRAINING_PIPELINE_NAME}  --query "PipelineExecutionSummaries[0:10:1].{StartTime:StartTime,ExecutionName:PipelineExecutionDisplayName,PipelineExectionARN:PipelineExecutionArn,PipelineExecutionStatus:PipelineExecutionStatus}" --output table
echo -e "\n>>\e[35m 10 most recent Pipeline Executions for ${INFERENCE_PIPELINE_NAME} \e[0m"
aws sagemaker list-pipeline-executions --pipeline-name ${INFERENCE_PIPELINE_NAME}  --query "PipelineExecutionSummaries[0:10:1].{StartTime:StartTime,ExecutionName:PipelineExecutionDisplayName,PipelineExectionARN:PipelineExecutionArn,PipelineExecutionStatus:PipelineExecutionStatus}" --output table
echo -e "\n>>\e[35m Selecting Training pipeline that created model used in latest inference pipeline model package \e[0m"
aws sagemaker list-pipeline-executions --pipeline-name ${TRAINING_PIPELINE_NAME}   --query "PipelineExecutionSummaries[?PipelineExecutionArn==\`${TRAINING_SM_ARN}\`].{StartTime:StartTime,ExecutionName:PipelineExecutionDisplayName,PipelineExectionARN:PipelineExecutionArn,PipelineExecutionStatus:PipelineExecutionStatus}" --output table
echo -e "\n>>\e[35m Selecting LATEST execution for ${INFERENCE_PIPELINE_NAME} \e[0m"
aws sagemaker list-pipeline-executions --pipeline-name ${INFERENCE_PIPELINE_NAME}   --query "PipelineExecutionSummaries[${INFERENCE_OFFSET}].{StartTime:StartTime,ExecutionName:PipelineExecutionDisplayName,PipelineExectionARN:PipelineExecutionArn,PipelineExecutionStatus:PipelineExecutionStatus}" --output table

INFERENCE_SM_ARN=$(aws sagemaker list-pipeline-executions --pipeline-name ${INFERENCE_PIPELINE_NAME}   --query "PipelineExecutionSummaries[${INFERENCE_OFFSET}].[PipelineExecutionArn]" --output text)
INFERENCE_SM_ID=${INFERENCE_SM_ARN##*/}

echo -e "\n>>\e[35m Training Code Artifacts from model bucket for SM Pipeline ${TRAINING_SM_ID} \e[0m"
TRAINING_PATH="${MODEL_BUCKET}/lifecycle/max/${PROJECT_NAME}/${TRAINING_PIPELINE_NAME}/${MODEL_GIT_REVISION}"
aws s3 --recursive ls $TRAINING_PATH




echo -e "\n>>\e[35m Training artifacts from model bucket for SM Pipeline ${TRAINING_SM_ID} \e[0m"
aws s3 --recursive ls "${MODEL_BUCKET}/lifecycle/60d/${PROJECT_NAME}/${TRAINING_PIPELINE_NAME}/${TRAINING_SM_ID}/"

echo -e "\n>>\e[35m Training artifacts from data bucket for SM Pipeline ${TRAINING_SM_ID} \e[0m"
aws s3 --recursive ls "${DATA_BUCKET}/lifecycle/60d/${PROJECT_NAME}/${TRAINING_PIPELINE_NAME}/${TRAINING_SM_ID}"


echo -e "\n>>\e[35m Inference Code Artifacts from model bucket for SM Pipeline $INFERENCE_PIPELINE_NAME ${PIPELINE_GIT_REVISION} \e[0m"
INFERENCE_PATH="${MODEL_BUCKET}/lifecycle/max/${PROJECT_NAME}/${INFERENCE_PIPELINE_NAME}/${MODEL_GIT_REVISION}/${PIPELINE_GIT_REVISION}"
aws s3 --recursive ls $INFERENCE_PATH

echo -e "\n>>\e[35m Inference artifacts from data bucket using model created by SM Pipeline ${TRAINING_SM_ID} in inference execution ${INFERENCE_SM_ID} \e[0m"
aws s3 --recursive ls "${DATA_BUCKET}/lifecycle/60d/${PROJECT_NAME}/${INFERENCE_PIPELINE_NAME}/${TRAINING_SM_ID}/${INFERENCE_SM_ID}"

# Copy files to local
if [ $DRY_RUN = false ]; then
  if [ $CLEAR_PATH = true ]; then
    rm -fr ${RELATIVE_PATH} || "folder doesnt exist"
  fi
  echo "create folder ${RELATIVE_PATH}"
  mkdir -p ${RELATIVE_PATH}
  echo -e "\n>>\e[35m Create files locally showing what execution ids are currently used \e[0m"
  echo "INFERENCE_SAGEMAKER_ID=${INFERENCE_SM_ID}" > $RELATIVE_PATH/info.sh
  echo "TRAINING_SAGEMAKER_ID=${TRAINING_SM_ID}" >> $RELATIVE_PATH/info.sh
  echo -e "\n>>\e[35m Copying to local \e[0m"
  aws s3 --recursive cp "$TRAINING_PATH" "${RELATIVE_PATH}/model-bucket/code/training/"
  aws s3 --recursive cp "${MODEL_BUCKET}/lifecycle/60d/${PROJECT_NAME}/${TRAINING_PIPELINE_NAME}/${TRAINING_SM_ID}/" "${RELATIVE_PATH}/model-bucket/"
  aws s3 --recursive cp "${DATA_BUCKET}/lifecycle/60d/${PROJECT_NAME}/${TRAINING_PIPELINE_NAME}/${TRAINING_SM_ID}" "${RELATIVE_PATH}/data-bucket/training-pipeline"
  aws s3 --recursive cp $INFERENCE_PATH "${RELATIVE_PATH}/model-bucket/code/inference/"
  aws s3 --recursive cp "${DATA_BUCKET}/lifecycle/60d/${PROJECT_NAME}/${INFERENCE_PIPELINE_NAME}/${TRAINING_SM_ID}/${INFERENCE_SM_ID}" "${RELATIVE_PATH}/data-bucket/inference-pipeline"
fi

