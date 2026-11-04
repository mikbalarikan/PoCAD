"""pocad paketi checkout'tan, kurulmadan içe aktarılır."""
import pocad


def test_paket_surumu_var():
    assert pocad.__version__ == "0.1.0"
