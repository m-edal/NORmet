import warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
from toolz import reduce, partial
from scipy.optimize import fmin_slsqp
from joblib import Parallel, delayed


def SCM_parallel(data: pd.DataFrame, pollutant, intervention_date, treatment_target, control_targets = None, n_core = -1):
    control_pool = data["Code"].unique()

    synthetic_all = pd.concat(Parallel(n_jobs=n_core)(delayed(SCM)(
        data=data, pollutant=pollutant,intervention_date=intervention_date,treatment_target=Code,
        control_targets=control_targets) for Code in control_pool))
    return synthetic_all


def SCM(data: pd.DataFrame, pollutant, intervention_date,treatment_target, control_targets = None) -> np.array:
    if control_targets is None:
        control_targets=list(data['Code'].unique())
        control_targets.remove(treatment_target)

    inverted = (data.query(f"date<{intervention_date}")
                .pivot(index='Code', columns="date")[pollutant]
                .T)

    y = inverted[treatment_target].values # treated
    X = inverted[control_targets].values # donor pool

    weights = get_w(X, y)
    synthetic = (data.query(f"(Code=={control_targets})")
                 .pivot(index='date', columns="Code")[pollutant]
                 .values.dot(weights))
    data = (data
            .query(f"Code=={treatment_target}")[["Code", "date", pollutant]]
            .assign(Synthetic=synthetic))
    data['Effects']=data[pollutant]-data['Synthetic']

    return data

def pre_treatment_error(df,intervention_date):
    pre_treat_error = (df.query(f"date<{intervention_date}")["Effects"]) ** 2
    return pre_treat_error.mean()

def loss_w(W, X, y) -> float:
    return np.sqrt(np.mean((y - X.dot(W))**2))

def get_w(X, y):

    w_start = [1/X.shape[1]]*X.shape[1]

    weights = fmin_slsqp(partial(loss_w, X=X, y=y),
                         np.array(w_start),
                         f_eqcons=lambda x: np.sum(x) - 1,
                         bounds=[(0.0, 1.0)]*len(w_start),
                         disp=False)
    return weights

def fit_time_weights(df, poll_col,date_col, Code_col, intervention_date,treatment_target,control_targets = None):
        if control_targets is None:
            control_targets=list(df[Code_col].unique())
            control_targets.remove(treatment_target)

        control = df[df[Code_col].isin(control_targets)]

        # pivot the data to the (T_pre, N_co) matrix representation
        y_pre = (control
                 .query(f"{date_col}<{intervention_date}")
                 .pivot(date_col, Code_col, poll_col))

        # group post-treatment time period by units to have a (1, N_co) vector.
        y_post_mean = (control
                       .query(f"{date_col}>={intervention_date}")
                       .groupby(Code_col)
                       [poll_col]
                       .mean()
                       .values)

        # add a (1, N_co) vector of 1 to the top of the matrix, to serve as the intercept.
        X = np.concatenate([np.ones((1, y_pre.shape[1])), y_pre.values], axis=0)

        # estimate time weights
        w = cp.Variable(X.shape[0])
        objective = cp.Minimize(cp.sum_squares(w@X - y_post_mean))
        constraints = [cp.sum(w[1:]) == 1, w[1:] >= 0]
        problem = cp.Problem(objective, constraints)
        problem.solve(verbose=False)

        # print("Intercept: ", w.value[0])
        return pd.Series(w.value[1:], # remove intercept
                         name="time_weights",
                         index=y_pre.index)


def calculate_regularization(df, poll_col, date_col,Code_col, intervention_date,treatment_target,control_targets = None):
    if control_targets is None:
        control_targets=list(df[Code_col].unique())
        control_targets.remove(treatment_target)

    n_treated_post = df[(df[date_col]>=intervention_date)&(df[Code_col]==treatment_target)].shape[0]

    first_diff_std = (df
                      .query(f"{date_col}<{intervention_date}")
                      .query(f"{Code_col}=={control_targets}")
                      .sort_values(date_col)
                      .groupby(Code_col)
                      [poll_col]
                      .diff()
                      .std())

    return n_treated_post**(1/4) * first_diff_std


def fit_unit_weights(df, poll_col, date_col, Code_col, intervention_date,treatment_target,control_targets = None):
    if control_targets is None:
        control_targets=list(df[Code_col].unique())
        control_targets.remove(treatment_target)

    zeta = calculate_regularization(df, poll_col, date_col, Code_col, intervention_date,treatment_target,control_targets)
    pre_data = df.query(f"{date_col}<{intervention_date}")

    # pivot the data to the (T_pre, N_co) matrix representation
    y_pre_control = (pre_data
                     .query(f"{Code_col}=={control_targets}")
                     .pivot(date_col, Code_col, poll_col))

    # group treated units by time periods to have a (T_pre, 1) vector.
    y_pre_treat_mean = (pre_data[pre_data[Code_col]==treatment_target]
                        .groupby(date_col)
                        [poll_col]
                        .mean())

    # add a (T_pre, 1) column to the begining of the (T_pre, N_co) matrix to serve as intercept
    T_pre = y_pre_control.shape[0]
    X = np.concatenate([np.ones((T_pre, 1)), y_pre_control.values], axis=1)

    # estimate unit weights. Notice the L2 penalty using zeta
    w = cp.Variable(X.shape[1])
    objective = cp.Minimize(cp.sum_squares(X@w - y_pre_treat_mean.values) + T_pre*zeta**2 * cp.sum_squares(w[1:]))
    constraints = [cp.sum(w[1:]) == 1, w[1:] >= 0]

    problem = cp.Problem(objective, constraints)
    problem.solve(verbose=False)

    # print("Intercept:", w.value[0])
    return pd.Series(w.value[1:], # remove intercept
                     name="unit_weights",
                     index=y_pre_control.columns)


def join_weights(df, unit_w, time_w, date_col, Code_col, intervention_date,treatment_target,control_targets = None):
    df['treated']=df[Code_col]==treatment_target
    df['after_treatment']=df[date_col]>=intervention_date

    return (
        df
        .set_index([date_col, Code_col])
        .join(time_w)
        .join(unit_w)
        .reset_index()
        .fillna({time_w.name: df['after_treatment'].mean(),
                 unit_w.name: df['treated'].mean()})
        .assign(**{"weights": lambda d: (d[time_w.name]*d[unit_w.name]).round(10)})
        .astype({'treated':int, 'after_treatment':int}))



def SDID(df, poll_col, date_col, Code_col, intervention_date,treatment_target,control_targets = None):
    if control_targets is None:
        control_targets=list(df[Code_col].unique())
        control_targets.remove(treatment_target)

    # find the unit weights
    unit_weights = fit_unit_weights(df=df,
                                    poll_col=poll_col,
                                    date_col=date_col,
                                    Code_col=Code_col,
                                    intervention_date=intervention_date,
                                    treatment_target=treatment_target,
                                    control_targets=control_targets)

    # find the time weights
    time_weights = fit_time_weights(df=df,
                                    poll_col=poll_col,
                                    date_col=date_col,
                                    Code_col=Code_col,
                                    intervention_date=intervention_date,
                                    treatment_target=treatment_target,
                                    control_targets=control_targets)

    # join weights into DiD Data
    did_data = join_weights(df, unit_weights, time_weights,
                            date_col=date_col,
                            Code_col=Code_col,
                            intervention_date=intervention_date,
                            treatment_target=treatment_target,
                            control_targets=control_targets)

    df['treated']=df[Code_col]==treatment_target
    df['after_treatment']=df[date_col]>=intervention_date

    # run DiD
    formula = f"{poll_col} ~ after_treatment * treated "
    did_model = smf.wls(formula, data=did_data, weights=did_data["weights"]+1e-10).fit()

    return did_model.params[f"after_treatment:treated"]


def SDID_effects(df, poll_col, date_col, Code_col, intervention_date,treatment_target,control_targets = None):
    effects = {year: synthetic_diff_in_diff(df[(df['date']<intervention_date)|(df['date']==year)],
                                        poll_col=poll_col,
                                        date_col=date_col,
                                        Code_col=Code_col,
                                        intervention_date=intervention_date,
                                        treatment_target=treatment_target)
           for year in list(df[df[date_col]>=intervention_date][date_col].unique())}
    return pd.Series(effects)
