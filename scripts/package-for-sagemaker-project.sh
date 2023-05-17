#!/bin/bash

#
################################################################################
# Help                                                                         #
################################################################################
Help()
{
   # Display Help
    echo "Helper script to package code to create your own seed code for new sagemaker projects"
    echo "End result is a compressed archive in a s3 bucket that you or your teammates can point to in order to get"
    echo "your own custom seed code"
    echo "Comes with a few options, such as using different branches as well as getting the compressed file versioned"
    echo "To run this from your workstation you are required to:"
    echo "1. be able to execute bash scripts on your local workstation (e.g. by using WSL) "
    echo "2. setup  aws cli in your local workstation and either:"
    echo "2.a set the default profile to the dev account"
    echo "2.b Using aws-vault to set env. variables by running aws-vault exec YOUR-AWS-PROFILE."
    echo "syntax: fetch-latest-run-objects.sh"
    echo "-n --product-name       Required: Product name to use for the packaged zip"
    echo "-r --repository-name    Required: Name of codecommit repositroy to clone and package"
    echo "-b --branch-name        Optional: Define branch to use for packaging [Default=main]"
    echo "-l --publish-as-latest  Optional: Flag to use latest as suffix instead of revision.[Default=false]"
    echo "-p --temp-path          Optional: Set temporary path used for cloning the repo to local.[Default=/tmp/package-for-sagemaker-project/]"
    echo "-l  --region            Optional: Set aws region [Default=eu-north-1]."
    echo "-h --help               Optional: Prints this help"
    echo "Example call from root of project:"
    echo -e "\n>>\e[35m scripts/package-for-sagemaker-project.sh --product-name ml-build-peter --repository-name sagemaker-ml-build-bronze-build-train --branch-name peter --publish-as-latest \e[0m"
}

# Set arguments
TEMP=$(getopt -o 'n:r:p:b:hl' --long 'product-name:,repository-name:,region:,temp-path:,branch-name:,publish-as-latest,help' -- "$@")

if [ $? -ne 0 ]; then
	echo 'Terminating...' >&2
	exit 1
fi

# Note the quotes around "$TEMP": they are essential!
eval set -- "$TEMP"
unset TEMP

while true; do
	case "$1" in
		'-n'|'--product-name')
		  PRODUCT_NAME="$2"
			echo "Using name:${PRODUCT_NAME}"
			shift 2
			continue
		;;
		'-r'|'--repository-name')
		  REPO_NAME="$2"
			echo "Using repository name:${REPO_NAME}"
			shift 2
			continue
		;;
		'--region')
		  REGION="$2"
			echo "Using region :${REGION}"
			shift 2
			continue
		;;
		'-p'|'--temp-path')
		  TEMP_CLONE_FOLDER="$2"
			echo "Using temp path:${TEMP_CLONE_FOLDER}"
			shift 2
			continue
		;;
		'-b'|'--branch-name')
		  BRANCH_NAME="$2"
			echo "Using branch name:${BRANCH_NAME}"
			shift 2
			continue
		;;
		'-h'|'--help')
			Help
			exit 0
			shift
			continue
		;;
		'-l'|'--publish-as-latest')
      PUBLISH_AS_LATEST=true
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
REGION=${REGION:="eu-north-1"}
TEMP_CLONE_FOLDER=${TEMP_CLONE_FOLDER:="/tmp/package-for-sagemaker-project/"}
BRANCH_NAME=${BRANCH_NAME:="main"}
PUBLISH_AS_LATEST=${PUBLISH_AS_LATEST:=false}
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

check_param PRODUCT_NAME  "product-name your-project-name" ${PRODUCT_NAME}
check_param REPO_NAME  "repository-name your-codecommit-repo-name" ${REPO_NAME}

REPO_HTTPS="https://git-codecommit.${REGION}.amazonaws.com/v1/repos/${REPO_NAME}"

# exit if non-optional parameters are unset
if [ $EXIT_FLAG = 1 ]; then
  echo -e "\n>>\e[31m INCORRECT PARAMETERS, PRINTING HELP \e[0m"
  Help
  exit 0
fi

set -euo pipefail

#mlops-dev-seed-code-s3bucket-name
ENV_NAME=$(aws ssm get-parameter --name EnvName --query 'Parameter.Value' --output text --region "${AWS_REGION}")
ENV_TYPE=$(aws ssm get-parameter --name EnvType --query 'Parameter.Value' --output text --region "${AWS_REGION}")
ARTIFACT_BUCKET=$(aws ssm get-parameter --name "${ENV_NAME}-${ENV_TYPE}-seed-code-s3bucket-name" --query 'Parameter.Value' --output text --region "${AWS_REGION}")



#SEED_CODE_OUTPUT_DIR="/tmp/package-for-sagemaker-project/"
rm -fr ${TEMP_CLONE_FOLDER} || "folder doesnt exist"
mkdir -p ${TEMP_CLONE_FOLDER}
pushd $TEMP_CLONE_FOLDER

# Pull from ML Dev account to temporary folder
git clone \
    --config 'credential.helper=!aws codecommit --region '$REGION' credential-helper $@' \
    --config 'credential.UseHttpPath=true' \
    "${REPO_HTTPS}" \
    ${TEMP_CLONE_FOLDER}

git checkout ${BRANCH_NAME}

HEADHASH=$(git rev-parse --short HEAD)

echo "CODECOMMIT_REPO_HTTPS=${REPO_HTTPS}" >> seed-code-package.info
echo "CODECOMMIT_REPO_NAME=${REPO_NAME}" >> seed-code-package.info
echo "BRANCH_NAME=${BRANCH_NAME}" >> seed-code-package.info
echo "GIT_HEADHASH=${HEADHASH}" >> seed-code-package.info

#rm -rf .git

zip -r "./packaged-seed-code.zip" . -x ".coveragerc" -x ".pydocstylerc" -x "/venv/*" -x "/wslenv/*" -x "/.pytest_cache/*" -x "/.idea/*" -x "/untracked/*" -x "/.git/*" -x ".gitignore"


#NAME_OF_REPO_ZIPPED="${REPO_NAME}-${BRANCH_NAME}-rev-${HEADHASH}.zip"


if [ ${PUBLISH_AS_LATEST} = true ]; then
    NAME_OF_REPO_ZIPPED="${BRANCH_NAME}-revision-latest.zip"
  else
    NAME_OF_REPO_ZIPPED="${BRANCH_NAME}-revision-${HEADHASH}.zip"
fi
OBJECT_PATH="sagemaker-mlops/seed-code/${PRODUCT_NAME}/${NAME_OF_REPO_ZIPPED}"
S3_PACKAGE_PATH="s3://${ARTIFACT_BUCKET}/${OBJECT_PATH}"
aws s3 cp ./packaged-seed-code.zip ${S3_PACKAGE_PATH}

echo -e "\n>>\e[35m Your Seed code package is now published for use in your teams account. \e[0m"
echo -e "\n>>\e[35m Share this path with the users that should use your seed code for new projects:\e[36m${OBJECT_PATH} \e[0m"

popd