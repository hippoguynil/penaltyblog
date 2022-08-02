import pandas as pd
import pytest

import penaltyblog as pb


def test_understat_wrong_league():
    with pytest.raises(ValueError):
        under = pb.scrapers.Understat("FRA Premier League", "2020-2021")


def test_understat_get_fixtures():
    under = pb.scrapers.Understat("ENG Premier League", "2020-2021")
    df = under.get_fixtures()
    assert type(df) == pd.DataFrame


def test_understat_id():
    under = pb.scrapers.Understat("ENG Premier League", "2021-2022")
    df = under.get_fixtures()
    assert "1628812800---brentford---arsenal" in df.index


def test_understat_list_competitions():
    df = pb.scrapers.Understat.list_competitions()
    assert type(df) == list


def test_understat_team_mappings():
    team_mappings = pb.scrapers.get_example_team_name_mappings()
    fb = pb.scrapers.FootballData("ENG Premier League", "2021-2022", team_mappings)
    df = fb.get_fixtures()
    assert "Leeds United" in df["team_home"].unique()


def test_understat_shots():
    under = pb.scrapers.Understat("ENG Premier League", "2020-2021")
    df = under.get_shots("14090")
    assert type(df) == pd.DataFrame


def test_understat_fixture_info():
    under = pb.scrapers.Understat("ENG Premier League", "2020-2021")
    df = under.get_shots("14090")
    assert type(df) == pd.DataFrame