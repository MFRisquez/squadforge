from app.services.fpl_sync import availability_flag


def test_availability_colors():
    assert availability_flag("a", None) == "ok"
    assert availability_flag("a", 100) == "ok"
    assert availability_flag("d", 75) == "doubt"
    assert availability_flag("a", 50) == "doubt"
    assert availability_flag("i", None) == "out"
    assert availability_flag("s", 100) == "out"
    assert availability_flag("u", None) == "out"
    assert availability_flag("a", 0) == "out"
