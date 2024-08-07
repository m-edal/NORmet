% Generated by roxygen2: do not edit by hand
% Please edit documentation in R/nm_modStats.r
\name{nm_modStats}
\alias{nm_modStats}
\title{Calculate Model Statistics}
\usage{
nm_modStats(df, model, obs = "value", set = NULL, statistic = NULL)
}
\arguments{
\item{df}{Data frame containing the input data.}

\item{model}{The trained model object.}

\item{obs}{The name of the observed values column. Default is "value".}

\item{set}{The name of the set for which to calculate statistics. If NULL, statistics for all sets will be calculated. Default is NULL.}

\item{statistic}{A vector of statistics to calculate. Default is c("n", "FAC2", "MB", "MGE", "NMB", "NMGE", "RMSE", "r", "COE", "IOA", "R2").}
}
\value{
A data frame containing the calculated statistics.
}
\description{
\code{nm_modStats} calculates various statistical measures for a given model and dataset.
}
\examples{
\dontrun{
library(dplyr)
df <- data.frame(
  set = rep(c("train", "test"), each = 50),
  value = rnorm(100)
)
model <- lm(value ~ set, data = df)
stats <- nm_modStats(df, model, obs = "value")
}
}
