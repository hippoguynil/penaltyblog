import os

import numpy as np
import pandas as pd
import pymc3 as pm
import theano.tensor as tt
from scipy.stats import poisson

from .football_probability_grid import FootballProbabilityGrid


class BayesianHierarchicalGoalModel:
    """Bayesian Hierarchical model for predicting outcomes of football
    (soccer) matches. Based on the paper by Baio and Blangiardo from
    https://discovery.ucl.ac.uk/id/eprint/16040/1/16040.pdf

    Methods
    -------
    fit()
        fits a Bayesian Hierarchical model to the data to calculate the team strengths.
        Must be called before the model can be used to predict game outcomes

    predict(home_team, away_team, max_goals=15)
        predict the outcome of a football (soccer) game between the home_team and away_team

    get_params()
        Returns the fitted parameters from the model
    """

    def __init__(
        self,
        goals_home,
        goals_away,
        teams_home,
        teams_away,
        weights=1,
        n_jobs=None,
        draws=2500,
    ):
        """
        Parameters
        ----------
        goals_home : list
            A list or pd.Series of goals scored by the home_team
        goals_away : list
            A list or pd.Series of goals scored by the away_team
        teams_home : list
            A list or pd.Series of team_names for the home_team
        teams_away : list
            A list or pd.Series of team_names for the away_team
        weights : list
            A list or pd.Series of weights for the data,
            the lower the weight the less the match has on the output.
            A scalar value of 1 indicates equal weighting for each observation
        n_jobs : int or None
            Number of chains to run in parallel
        draws : int
            Number of samples to draw from the model
        """
        self.fixtures = pd.DataFrame([goals_home, goals_away, teams_home, teams_away]).T
        self.fixtures.columns = ["goals_home", "goals_away", "team_home", "team_away"]
        self.fixtures["goals_home"] = self.fixtures["goals_home"].astype(int)
        self.fixtures["goals_away"] = self.fixtures["goals_away"].astype(int)
        self.fixtures["weights"] = weights
        self.fixtures = self.fixtures.reset_index(drop=True)
        self.fixtures["weights"] = weights

        self.n_teams = len(self.fixtures["team_home"].unique())

        self.teams = (
            self.fixtures[["team_home"]]
            .drop_duplicates()
            .sort_values("team_home")
            .reset_index(drop=True)
            .assign(team_index=np.arange(self.n_teams))
            .rename(columns={"team_home": "team"})
        )

        self.fixtures = (
            self.fixtures.merge(
                self.teams,
                left_on="team_home",
                right_on="team",
                how="left",
            )
            .rename(columns={"team_index": "home_index"})
            .drop(["team"], axis=1)
            .merge(
                self.teams,
                left_on="team_away",
                right_on="team",
                how="left",
            )
            .rename(columns={"team_index": "away_index"})
            .drop(["team"], axis=1)
        )

        self.trace = None
        self.draws = draws
        self.params = dict()

        if n_jobs == -1 or n_jobs is None:
            self.n_jobs = os.cpu_count()
        elif n_jobs == 0:
            self.n_jobs = 1
        else:
            self.n_jobs = n_jobs

        self.fitted = False

    def fit(self):
        """
        Fits the model to the data and calculates the team strengths,
        home advantage and intercept. Should be called before `predict` can be used
        """
        goals_home_obs = self.fixtures["goals_home"].values
        goals_away_obs = self.fixtures["goals_away"].values

        home_team = self.fixtures["home_index"].values
        away_team = self.fixtures["away_index"].values

        weights = self.fixtures["weights"].values

        with pm.Model():
            # flat parameters
            home = pm.Flat("home")
            intercept = pm.Flat("intercept")

            # attack parameters
            tau_att = pm.Gamma("tau_att", 0.1, 0.1)
            atts_star = pm.Normal("atts_star", mu=0, tau=tau_att, shape=self.n_teams)

            # defence parameters
            tau_def = pm.Gamma("tau_def", 0.1, 0.1)
            def_star = pm.Normal("def_star", mu=0, tau=tau_def, shape=self.n_teams)

            # apply sum zero constraints
            atts = pm.Deterministic("atts", atts_star - tt.mean(atts_star))
            defs = pm.Deterministic("defs", def_star - tt.mean(def_star))

            # calulate theta
            home_theta = tt.exp(intercept + home + atts[home_team] + defs[away_team])
            away_theta = tt.exp(intercept + atts[away_team] + defs[home_team])

            # goal expectation
            pm.Potential(
                "home_goals",
                weights * pm.Poisson.dist(mu=home_theta).logp(goals_home_obs),
            )
            pm.Potential(
                "away_goals",
                weights * pm.Poisson.dist(mu=away_theta).logp(goals_away_obs),
            )

            self.trace = pm.sample(
                self.draws, tune=1500, cores=self.n_jobs, return_inferencedata=False
            )

        self.params["home"] = np.mean(self.trace["home"])
        self.params["intercept"] = np.mean(self.trace["intercept"])
        for idx, row in self.teams.iterrows():
            self.params["attack_" + row["team"]] = np.mean(
                [x[idx] for x in self.trace["atts"]]
            )
            self.params["defence_" + row["team"]] = np.mean(
                [x[idx] for x in self.trace["defs"]]
            )

        self.fitted = True

    def predict(self, home_team, away_team, max_goals=15) -> FootballProbabilityGrid:
        """
        Predicts the probabilities of the different possible match outcomes

        Parameters
        ----------
        home_team : str
            The name of the home_team, must have been in the data the model was fitted on

        away_team : str
            The name of the away_team, must have been in the data the model was fitted on

        max_goals : int
            The maximum number of goals to calculate the probabilities over.
            Reducing this will improve performance slightly at the expensive of acuuracy

        Returns
        -------
        FootballProbabilityGrid
            A class providing access to a range of probabilites,
            such as 1x2, asian handicaps, over unders etc
        """
        if not self.fitted:
            raise ValueError(
                (
                    "Model's parameters have not been fit yet, please call the `fit()` "
                    "function before making any predictions"
                )
            )

        # check we have parameters for teams
        if home_team not in self.teams["team"].tolist():
            raise ValueError(
                (
                    "No parameters for home team - "
                    "please ensure the team was included in the training data"
                )
            )

        if away_team not in self.teams["team"].tolist():
            raise ValueError(
                (
                    "No parameters for away team - "
                    "please ensure the team was included in the training data"
                )
            )

        # get the parameters
        home = self.params["home"]
        intercept = self.params["intercept"]
        atts_home = self.params["attack_" + home_team]
        atts_away = self.params["attack_" + away_team]
        defs_home = self.params["defence_" + home_team]
        defs_away = self.params["defence_" + away_team]

        # calculate the goal vectors
        home_goals = np.exp(intercept + home + atts_home + defs_away)
        away_goals = np.exp(intercept + atts_away + defs_home)
        home_goals_vector = poisson(home_goals).pmf(np.arange(0, max_goals))
        away_goals_vector = poisson(away_goals).pmf(np.arange(0, max_goals))

        # get the probabilities for each possible score
        m = np.outer(home_goals_vector, away_goals_vector)

        probability_grid = FootballProbabilityGrid(m, home_goals, away_goals)
        return probability_grid

    def get_params(self) -> dict:
        """
        Provides access to the model's fitted parameters

        Returns
        -------
        dict
            A dict containing the model's parameters
        """
        if not self.fitted:
            raise ValueError(
                "Model's parameters have not been fit yet, please call the `fit()` function first"
            )

        return self.params
