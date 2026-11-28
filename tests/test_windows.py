from carbon.common.windows import best_windows, job_dollars, window_averages


def test_picks_the_lowest_average_window():
    values = [10, 10, 1, 1, 10, 10]
    best = best_windows(values, duration=2, max_delay=4, top=1)[0]
    assert best["start_offset_h"] == 2
    assert best["avg"] == 1


def test_savings_are_dollars_per_mwh_below_starting_now():
    best = best_windows([10, 10, 5, 5], duration=2, max_delay=2, top=1)[0]
    assert best["savings"] == 5.0


def test_negative_prices_win_and_savings_stay_defined():
    best = best_windows([-5, -5, -20, -20], duration=2, max_delay=2, top=1)[0]
    assert best["avg"] == -20 and best["savings"] == 15.0


def test_job_dollars():
    assert job_dollars(40, kw=8, duration=4) == 1.28  # the 8 kW cabinet for 4 hours at 40 $/MWh


def test_windows_do_not_overlap():
    values = [9, 1, 1, 1, 9, 9, 2, 2, 9]
    windows = best_windows(values, duration=2, max_delay=7, top=3)
    starts = sorted(w["start_offset_h"] for w in windows)
    assert all(b - a >= 2 for a, b in zip(starts, starts[1:]))


def test_max_delay_is_respected():
    values = [10, 10, 10, 1, 1, 1]
    best = best_windows(values, duration=2, max_delay=1, top=1)[0]
    assert best["start_offset_h"] <= 1


def test_duration_longer_than_forecast_returns_nothing():
    assert best_windows([1, 2, 3], duration=5, max_delay=0) == []
    assert window_averages([1, 2, 3], duration=0, max_delay=1) == []
