from carbon.common.windows import best_windows, window_averages


def test_picks_the_lowest_average_window():
    values = [10, 10, 1, 1, 10, 10]
    best = best_windows(values, duration=2, max_delay=4, top=1)[0]
    assert best["start_offset_h"] == 2
    assert best["avg"] == 1


def test_savings_are_relative_to_starting_now():
    best = best_windows([10, 10, 5, 5], duration=2, max_delay=2, top=1)[0]
    assert best["savings_pct"] == 50.0


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
