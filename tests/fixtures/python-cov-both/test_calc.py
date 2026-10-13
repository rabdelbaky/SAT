from calc import add, sign


def test_add():
    assert add(2, 3) == 5


def test_sign_positive():
    assert sign(5) == 1
