"""scoring script"""
import logging
import pathlib
import pickle
import tarfile
import pandas as pd
import xgboost
import random
import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

def createDatetime():
    
    from datetime import datetime
    
    datestring = ""
    y = str(datetime.now().year)
    m = str(datetime.now().month)
    d = str(datetime.now().day)
    h = str(datetime.now().hour)
    minute = str(datetime.now().minute)
    sec = str(datetime.now().second)
    datestring +=y
    datestring +=m
    datestring +=d
    datestring +=h
    datestring +=minute
    datestring +=sec
    return datestring

if __name__ == "__main__":
    logger.info("Starting evaluation.")
    model_path = "/opt/ml/processing/model/model.tar.gz"
    with tarfile.open(model_path) as tar:
        tar.extractall(path=".")

    logger.info("Loading xgboost model.")
    model = pickle.load(open("xgboost-model", "rb"))

    logger.info("Reading  data.")
    data_path = "/opt/ml/processing/inference/inference-data.csv"
    df = pd.read_csv(data_path, header=None)

    logger.info("Reading  data.")
    X = xgboost.DMatrix(df.values)

    logger.info("Performing predictions against test data.")
    predictions = model.predict(X)
    predictions_df = pd.DataFrame(predictions, columns = ['score'])

    # create df with both features and label to be used to evaluate data drift
    # cast as int since this is used by data drift.
    df.insert(0,'label', predictions.astype(int))
    #use this if you want to test alarm for data_type
    #df.insert(0,'label', predictions)

    creation_date = datetime.datetime.now().replace(second=0, microsecond=0)
    #adding intentional fail check
    #df["faulty_additional_col"] = creation_date



    predictions_df["creation_date"] = creation_date
    predictions_df["mock_id"] = [random.randint(10000000, 90000000) for x in range(len(predictions_df))]
    predictions_df = predictions_df[["mock_id", "creation_date", "score" ]]
    output_dir = "/opt/ml/processing/inference-output"
    dataquality_input_dir = "/opt/ml/processing/inference-with-features"
    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)
    logger.info("Save to csv locally.")
    timestamp=createDatetime()
    predictions_df.to_csv(f"{output_dir}/inference-{timestamp}.csv", header=False, index=False)
    df.to_csv(f"{dataquality_input_dir}/inference-with-features.csv", header=False, index=False)
    logger.info("Model inference completed.")