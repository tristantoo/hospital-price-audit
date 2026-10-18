import numpy as np

from sim import PS, k_cms


def test_cms_rank_mapping():
    # Hand-derived ranks for n = 1..3 under "ceil of type-7 position (n-1)p + 1".
    expected = {1: (1, 1, 1), 2: (2, 2, 2), 3: (2, 2, 3)}
    x = np.random.default_rng(0).lognormal(size=1000)
    for n in range(1, 1001):
        ks = [k_cms(n, P) for P in PS]
        if n in expected:
            assert tuple(ks) == expected[n]
        s = np.sort(x[:n])
        # equals numpy method="higher" on continuous data ...
        assert np.array_equal(s[np.array(ks) - 1], np.quantile(s, [P / 100 for P in PS], method="higher"))
        # ... median is the upper median floor(n/2)+1, which is NOT Hyndman-Fan type 1 (ceil(n/2)) for even n
        assert ks[1] == n // 2 + 1
        assert (ks[1] == -(-n // 2)) == (n % 2 == 1)
