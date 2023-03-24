import pandas as pd
import numpy as np
from datetime import datetime
from random import sample
from scipy import stats
from scipy.stats import mode
from flaml import AutoML
automl = AutoML()
from joblib import Parallel, delayed

def do_all(df, value=None,feature_names=None, split_method = 'random',time_budget=60,metric= 'r2',
                  estimator_list=["lgbm", "rf","xgboost","extra_tree","xgb_limitdepth"],task='regression',
                  seed=7654321, variables_sample=None, n_samples=300,fraction=0.75):
    df=prepare_data(df, value=value, split_method = split_method,fraction=fraction)
    automl=train_model(df,variables=feature_names,
                time_budget= time_budget,  metric= metric, task= task, seed= seed);
    df=normalise(automl, df,
                           feature_names = feature_names,
                          variables= variables_sample,
                          n_samples=n_samples)
    return df

def prepare_data(df, value='value', na_rm=False,split_method = 'random' ,replace=False, fraction=0.75):

    # Check
    if value not in df.columns:
        raise ValueError("`value` is not within input data frame.")

    df = (df.rename(columns={value: "value"})
        .pipe(check_data, prepared=False)
        .pipe(impute_values, na_rm=na_rm)
        .pipe(add_date_variables, replace=replace)
        .pipe(split_into_sets, split_method = split_method,fraction=fraction)
        .reset_index(drop=True))

    return df

def add_date_variables(df, replace):

    if replace:
        # Will replace if variables exist
        df['date_unix'] = df['date'].astype(np.int64) // 10**9
        df['day_julian'] = pd.DatetimeIndex(df['date']).dayofyear
        df['weekday'] = pd.DatetimeIndex(df['date']).weekday + 1
        df['hour'] = pd.DatetimeIndex(df['date']).hour

    else:
         # Add variables if they do not exist
         # Add date variables
        if 'date_unix' not in df.columns:
            df['date_unix'] = df['date'].apply(lambda x: x.timestamp())
        if 'day_julian' not in df.columns:
            df['day_julian'] = df['date'].apply(lambda x: x.timetuple().tm_yday)

        # An internal package's function
        if 'weekday' not in df.columns:
            df['weekday'] = df['date'].apply(lambda x: x.weekday() + 1)

        if 'hour' not in df.columns:
            df['hour'] = df['date'].apply(lambda x: x.hour)

    return df

def impute_values(df, na_rm):
    # Remove missing values
    if na_rm:
        df = df.dropna(subset=['value'])
    # Numeric variables
    for col in df.select_dtypes(include=[np.number]).columns:
        df[col].fillna(df[col].median(), inplace=True)
    # Character and categorical variables
    for col in df.select_dtypes(include=['object', 'category']).columns:
        df[col].fillna(mode(df[col])[0][0], inplace=True)

    return df

def split_into_sets(df, split_method, fraction):
    # Add row number
    df = df.reset_index().rename(columns={'index': 'rowid'})
    if (split_method == 'random'):
        # Sample to get training set
        df_training = df.sample(frac=fraction, random_state=42).reset_index(drop=True).assign(set="training")
        # Remove training set from input to get testing set
        df_testing = df[~df['rowid'].isin(df_training['rowid'])].assign(set="testing")
    if (split_method == 'time_series'):
        df_training = df.iloc[:int(fraction*df.shape[0]),:].reset_index(drop=True).assign(set="training")
        df_testing = df[~df['rowid'].isin(df_training['rowid'])].assign(set="testing")

    # Bind again
    df_split = pd.concat([df_training, df_testing], axis=0, ignore_index=True)
    #df_split = df_split[['date', 'value',  'date_unix', 'day_julian', 'weekday', 'hour','set']]
    df_split = df_split.sort_values(by='date').reset_index(drop=True)

    return df_split

def check_data(df, prepared):

    if 'date' not in df.columns:
        raise ValueError("Input must contain a `date` variable.")
    if not np.issubdtype(df["date"].dtype, np.datetime64):
        raise ValueError("`date` variable needs to be a parsed date (datetime64).")
    if df['date'].isnull().any():
        raise ValueError("`date` must not contain missing (NA) values.")

    if prepared:
        if 'set' not in df.columns:
            raise ValueError("Input must contain a `set` variable.")
        if not set(df['set'].unique()).issubset(set(['training', 'testing'])):
            raise ValueError("`set` can only take the values `training` and `testing`.")
        if "value" not in df.columns:
            raise ValueError("Input must contain a `value` variable.")
        if "date_unix" not in df.columns:
            raise ValueError("Input must contain a `date_unix` variable.")
    return df


def train_model(df, variables,
    time_budget= 60,  # total running time in seconds
    metric= 'r2',  # primary metrics for regression can be chosen from: ['mae','mse','r2','rmse','mape']
    estimator_list= ["lgbm", "rf","xgboost","extra_tree","xgb_limitdepth"],  # list of ML learners; we tune lightgbm in this example
    task= 'regression',  # task type
    seed= 7654321,    # random seed
):
    # Check arguments
    if len(set(variables)) != len(variables):
        raise ValueError("`variables` contains duplicate elements.")

    if not all([var in df.columns for var in variables]):
        raise ValueError("`variables` given are not within input data frame.")

    # Check input dataset
    df = check_data(df, prepared=True)

    # Filter and select input for modelling
    df = df.loc[df['set'] == 'training', ['value'] + variables]

    automl_settings = {
        "time_budget": time_budget,  # total running time in seconds
        "metric": metric,  # primary metrics for regression can be chosen from: ['mae','mse','r2','rmse','mape']
        "estimator_list": estimator_list,  # list of ML learners; we tune lightgbm in this example
        "task": task,  # task type
        "seed": seed,    # random seed
    }

    automl.fit(X_train=df[variables], y_train=df['value'],**automl_settings)

    return automl

def normalise_worker(index, automl, df, variables, replace, n_samples,n_cores, verbose):
    # Only every fifth prediction message
    if verbose and index % 5 == 0:
        # Calculate percent
        message_percent = round((index / n_samples) * 100, 2)
        # Always have 2 dp
        message_percent = "{:.1f} %".format(message_percent)
        # Print
        print(pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
              ": Predicting", index, "of", n_samples, "times (", message_precent, ")...")
    # Randomly sample observations
    n_rows = df.shape[0]
    index_rows = np.random.choice(range(n_rows), size=n_rows, replace=replace)

    # Transform data frame to include sampled variables
    if variables is None:
        variables = list(set(df.columns) - {'date_unix'})
    # Transform data frame to include sampled variables
    df[variables] = df[variables].iloc[index_rows].reset_index(drop=True)

    # Use model to predict
    value_predict = model_predict(automl, df)

    # Build data frame of predictions
    predictions = pd.DataFrame({'date': df['date'], 'Observed':df['value'],'Deweathered': value_predict})

    return predictions

def normalise(automl, df, feature_names,variables=None, n_samples=300, replace=True,
                  aggregate=True, n_cores=None, verbose=False):

    df = check_data(df, prepared=True)
    # Default logic for cpu cores
    n_cores = n_cores if n_cores is not None else -1

    # Use all variables except the trend term
    if variables is None:
        #variables = automl.model.estimator.feature_name_
        variables = feature_names
        variables.remove('date_unix')

    # Sample the time series
    if verbose:
        print(pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'), ": Sampling and predicting",
              n_samples, "times...")

    # If no samples are passed
    if n_samples == 0:
        df = pd.DataFrame()
    else:
        df = pd.concat(Parallel(n_jobs=n_cores)(delayed(normalise_worker)(
            index=i,automl=automl,df=df,
            variables=variables,replace=replace,n_cores=n_cores,
            n_samples=n_samples,
            verbose=verbose) for i in range(n_samples)), axis=0).pivot_table(index='date',aggfunc='mean')
    df=df[['Observed','Deweathered']]
    return df

def model_predict(automl, df=None):
    x = automl.predict(df)
    return x

#def modStats(df,value=None,split_method = 'random',set='testing',fraction=0.75):
def modStats(df,set=set,statistic=["n", "FAC2", "MB", "MGE", "NMB", "NMGE", "RMSE", "r", "COE", "IOA"]):
    df=df[df['set']==set]
    df['value_predict']=automl.predict(df)
    df=Stats(df, mod="value_predict", obs="value",statistic=statistic)
    return df

def Stats(df, mod="mod", obs="obs",
             statistic = None):
    res = {}
    if "n" in statistic:
        res["n"] = n(df, mod, obs)
    if "FAC2" in statistic:
        res["FAC2"] = FAC2(df, mod, obs)
    if "MB" in statistic:
        res["MB"] = MB(df, mod, obs)
    if "MGE" in statistic:
        res["MGE"] = MGE(df, mod, obs)
    if "NMB" in statistic:
        res["NMB"] = NMB(df, mod, obs)
    if "NMGE" in statistic:
        res["NMGE"] = NMGE(df, mod, obs)
    if "RMSE" in statistic:
        res["RMSE"] = RMSE(df, mod, obs)
    if "r" in statistic:
        res["r"] = r(df, mod, obs)[0]
        res["p_Value"] = r(df, mod, obs)[1]
    if "COE" in statistic:
        res["COE"] = COE(df, mod, obs)
    if "IOA" in statistic:
        res["IOA"] = IOA(df, mod, obs)

    results = {'n':res['n'], 'FAC2':res['FAC2'], 'MB':res['MB'], 'MGE':res['MGE'], 'NMB':res['NMB'],
               'NMGE':res['NMGE'],
               'RMSE':res['RMSE'], 'r':res['r'],'p_Value':res['p_Value'], 'COE':res['COE'], 'IOA':res['IOA']}

    results = pd.DataFrame([results])

    return results

## number of valid readings
def n(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    res = x.shape[0]
    return res

## fraction within a factor of two
def FAC2(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    ratio = x[mod] / x[obs]
    ratio = ratio.dropna()
    len = ratio.shape[0]
    if len > 0:
        res = ratio[(ratio >= 0.5) & (ratio <= 2)].shape[0] / len
    else:
        res = np.nan
    return res

## mean bias
def MB(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    res = np.mean(x[mod] - x[obs])
    return res

## mean gross error
def MGE(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    res = np.mean(np.abs(x[mod] - x[obs]))
    return res

## normalised mean bias
def NMB(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    res = np.sum(x[mod] - x[obs]) / np.sum(x[obs])
    return res

## normalised mean gross error
def NMGE(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    res = np.sum(np.abs(x[mod] - x[obs])) / np.sum(x[obs])
    return res

## root mean square error
def RMSE(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    res = np.sqrt(np.mean((x[mod] - x[obs]) ** 2))
    return res

## correlation coefficient
# when SD=0; will return(NA)
def r(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    res = stats.pearsonr(x[mod], x[obs])
    #return pd.DataFrame({"r": [res[0]], "P": [res[1]]})
    return res

## Coefficient of Efficiency
def COE(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    res = 1 - np.sum(np.abs(x[mod] - x[obs])) / np.sum(np.abs(x[obs] - np.mean(x[obs])))
    return res

## Index of Agreement
def IOA(x, mod="mod", obs="obs"):
    x = x[[mod, obs]].dropna()
    LHS = np.sum(np.abs(x[mod] - x[obs]))
    RHS = 2 * np.sum(np.abs(x[obs] - np.mean(x[obs])))
    if LHS <= RHS:
        res = 1 - LHS / RHS
    else:
        res = RHS / LHS - 1
    return res
