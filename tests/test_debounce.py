from src.protocol.debounce import Debouncer


def test_requires_k_of_n_to_flip_true():
    d = Debouncer(k=3, n=5)
    assert d.update("x", True) == (False, False)
    assert d.update("x", True) == (False, False)
    state, transitioned = d.update("x", True)
    assert state is True
    assert transitioned is True


def test_holds_state_when_agreement_insufficient_either_way():
    d = Debouncer(k=3, n=5)
    for _ in range(3):
        d.update("x", True)
    assert d.state("x") is True
    # A couple of False observations isn't enough to flip back (k=3 of n=5).
    state, transitioned = d.update("x", False)
    assert state is True
    assert transitioned is False


def test_flips_back_once_k_false_observed():
    d = Debouncer(k=3, n=5)
    for _ in range(3):
        d.update("x", True)
    assert d.state("x") is True
    for _ in range(2):
        d.update("x", False)
    state, transitioned = d.update("x", False)
    assert state is False
    assert transitioned is True


def test_single_noisy_frame_does_not_flip_k_of_n_gate():
    d = Debouncer(k=4, n=5)
    for _ in range(4):
        d.update("x", True)
    assert d.state("x") is True
    # One noisy False frame among a stable True run should not flip it.
    state, transitioned = d.update("x", False)
    assert state is True
    assert transitioned is False


def test_keys_are_independent():
    d = Debouncer(k=2, n=3)
    d.update("a", True)
    d.update("a", True)
    d.update("b", True)
    assert d.state("a") is True
    assert d.state("b") is False


def test_reset_clears_state():
    d = Debouncer(k=1, n=1)
    d.update("x", True)
    assert d.state("x") is True
    d.reset("x")
    assert d.state("x") is False


def test_rejects_invalid_k_n():
    import pytest

    with pytest.raises(ValueError):
        Debouncer(k=0, n=5)
    with pytest.raises(ValueError):
        Debouncer(k=6, n=5)
