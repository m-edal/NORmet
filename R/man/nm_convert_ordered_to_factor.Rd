% Generated by roxygen2: do not edit by hand
% Please edit documentation in R/nm_prepare_data.r
\name{nm_convert_ordered_to_factor}
\alias{nm_convert_ordered_to_factor}
\title{Convert Ordered Factors to Factors}
\usage{
nm_convert_ordered_to_factor(df)
}
\arguments{
\item{df}{Input data frame.}
}
\value{
Data frame with converted factors.
}
\description{
\code{nm_convert_ordered_to_factor} converts ordered factors in the data frame to regular factors.
}
\examples{
\dontrun{
library(dplyr)
df <- data.frame(
  ordered_factor = ordered(rep(c("low", "medium", "high"), length.out = 100)),
  other_variable = rnorm(100),
  date = Sys.time() + seq(1, 100, by = 1)
)
converted_df <- nm_convert_ordered_to_factor(df)
}

}
