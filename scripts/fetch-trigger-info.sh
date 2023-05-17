#!/bin/bash
set -euox pipefail
#CODEBUILD_INITIATOR=codepipeline/sagemaker-ml-batch-train-p-qqyeyqonk0x6-modelbuild
#CODEBUILD_BUILD_ID=sagemaker-ml-batch-train-p-qqyeyqonk0x6-modelbuild:0dc7c3fc-c262-4561-b6b5-2af792d001cc
echo $CODEBUILD_BUILD_ID
echo $CODEBUILD_INITIATOR
PIPELINE_EXECUTION_ID=$(aws codepipeline get-pipeline-state --region eu-north-1 --name ${CODEBUILD_INITIATOR#codepipeline/} --query 'stageStates[?actionStates[?latestExecution.externalExecutionId==`'${CODEBUILD_BUILD_ID}'`]].latestExecution.pipelineExecutionId' --output text)
echo $PIPELINE_EXECUTION_ID
TRIGGER_ARN=$(aws codepipeline list-pipeline-executions --pipeline-name ${CODEBUILD_INITIATOR#codepipeline/} --query 'pipelineExecutionSummaries[?pipelineExecutionId==`'b00db724-6702-40c9-8aed-fc8f2a515cd2'`].[pipelineExecutionId, trigger.triggerDetail]')
echo $TRIGGER_ARN