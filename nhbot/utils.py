import functools
from functools import partial, wraps
from itertools import chain

import cv2
import numba as nb
import numpy as np
import toolz

from .strategy import Strategy


@nb.njit(cache=True)
def bfs(y, x, *, walkable, walkable_diagonally, can_squeeze):
    dis = np.zeros(walkable.shape, dtype=np.int32)
    dis[:] = -1
    dis[y, x] = 0

    buf = np.zeros((walkable.shape[0] * walkable.shape[1], 2), dtype=np.uint32)
    index = 0
    buf[index] = (y, x)
    size = 1
    while index < size:
        y, x = buf[index]
        index += 1

        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                py, px = y + dy, x + dx
                if 0 <= py < walkable.shape[0] and 0 <= px < walkable.shape[1] and (dy != 0 or dx != 0):
                    if (walkable[py, px] and
                            (abs(dy) + abs(dx) <= 1 or
                             (walkable_diagonally[py, px] and walkable_diagonally[y, x] and
                              (can_squeeze or walkable[py, x] or walkable[y, px])))):
                        if dis[py, px] == -1:
                            dis[py, px] = dis[y, x] + 1
                            buf[size] = (py, px)
                            size += 1

    return dis


def translate(array, y_offset, x_offset, out=None):
    if out is None:
        out = np.zeros_like(array)
    else:
        out.fill(0)

    if y_offset > 0:
        array = array[:-y_offset]
    elif y_offset < 0:
        array = array[-y_offset:]
    if x_offset > 0:
        array = array[:, :-x_offset]
    elif x_offset < 0:
        array = array[:, -x_offset:]

    sy, sx = max(y_offset, 0), max(x_offset, 0)
    out[sy: sy + array.shape[0], sx: sx + array.shape[1]] = array
    return out


@nb.njit('b1[:,:](i2[:,:],i2,i2,b1[:])', cache=True)
def _isin_kernel(array, mi, ma, mask):
    ret = np.zeros(array.shape, dtype=nb.b1)
    for y in range(array.shape[0]):
        for x in range(array.shape[1]):
            if array[y, x] < mi or array[y, x] > ma:
                continue
            ret[y, x] = mask[array[y, x] - mi]
    return ret


@functools.lru_cache(1024)
def _isin_mask(elems):
    elems = np.array(list(chain(*elems)), np.int16)
    return _isin_mask_kernel(elems)


@nb.njit('Tuple((i2,i2,b1[:]))(i2[:])', cache=True)
def _isin_mask_kernel(elems):
    mi: i2 = 32767
    ma: i2 = -32768
    for i in range(elems.shape[0]):
        if mi > elems[i]:
            mi = elems[i]
        if ma < elems[i]:
            ma = elems[i]
    ret = np.zeros(ma - mi + 1, dtype=nb.b1)
    for i in range(elems.shape[0]):
        ret[elems[i] - mi] = True
    return mi, ma, ret


def isin(array, *elems):
    assert array.dtype == np.int16

    # PERF: the usual arguments (frozensets / tuples) are their own memoization key -- the normalization below
    # leaves them unchanged, so the cached mask is the same one; anything unhashable takes the old path
    try:
        mi, ma, mask = _isin_mask(elems)
    except TypeError:
        pass
    else:
        return _isin_kernel(array, mi, ma, mask)

    # for memoization
    elems = tuple((
        e if isinstance(e, tuple) else
        e if isinstance(e, frozenset) else
        tuple(e) if isinstance(e, list) else
        frozenset(e) if isinstance(e, set) else
        e
        for e in elems))

    mi, ma, mask = _isin_mask(elems)
    return _isin_kernel(array, mi, ma, mask)


def neighbor_count8(mask):
    """For each square, how many of its 8 neighbours are set in the 2-D boolean `mask` (outside the map counts as
    unset), as int32 -- the same numbers as summing translate(mask, dy, dx) over the 8 offsets (dy, dx) != (0, 0)."""
    h, w = mask.shape
    p = np.zeros((h + 2, w + 2), np.int32)
    p[1:-1, 1:-1] = mask
    return (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] + p[1:-1, :-2] + p[1:-1, 2:] +
            p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:])


def neighbor_count4(mask):
    """As neighbor_count8, over the 4 orthogonal neighbours only."""
    h, w = mask.shape
    p = np.zeros((h + 2, w + 2), np.int32)
    p[1:-1, 1:-1] = mask
    return p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]


def any_in(array, *elems):
    # TODO: optimize
    return isin(array, *elems).any()


@toolz.curry
def debug_log(txt, fun, color=(255, 255, 255)):
    @wraps(fun)
    def wrapper(self, *args, **kwargs):
        # TODO: make it cleaner
        if type(self).__name__ != 'Agent':
            env = self.agent.env
        else:
            env = self.env

        with env.debug_log(txt=txt, color=color):
            ret = fun(self, *args, **kwargs)
            if isinstance(ret, Strategy):
                def f(strategy=ret.strategy, *a, **k):
                    it = strategy(*a, **k)
                    yield next(it)
                    with env.debug_log(txt=txt, color=color):
                        try:
                            next(it)
                            assert 0
                        except StopIteration as e:
                            return e.value

                ret.strategy = partial(f, ret.strategy)
            return ret

    return wrapper


def edit_distance(s1, s2):
    """Levenshtein distance, the same number as nltk.metrics.distance.edit_distance(s1, s2) with its defaults
    (substitution cost 1, no transpositions) -- PERF: importing nltk pulled in scipy.stats, ~1 s per game process."""
    longest = max(len(s1), len(s2))
    if longest > 2000:   # nltk's MAX_DISTANCE_INPUT_LEN guard
        raise ValueError(f"edit_distance: input length {longest} exceeds MAX_DISTANCE_INPUT_LEN (2000)")
    len1, len2 = len(s1), len(s2)
    prev = list(range(len2 + 1))
    for i in range(1, len1 + 1):
        cur = [i] + [0] * len2
        c1 = s1[i - 1]
        for j in range(1, len2 + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (1 if c1 != s2[j - 1] else 0))
        prev = cur
    return prev[len2]


def box3_sum_symm(a):
    """Sum over each 3x3 neighbourhood with mirrored edges: the same integers as
    scipy.signal.convolve2d(a, np.ones((3, 3)), boundary='symm', mode='same') for an integer 2-D array -- PERF:
    scipy.signal pulled in scipy.stats at import (~1 s per game process)."""
    p = np.pad(a, 1, mode='symmetric')
    h, w = a.shape
    out = np.zeros((h, w), dtype=np.result_type(a.dtype, np.int64) if a.dtype.kind in 'biu' else a.dtype)
    for dy in range(3):
        for dx in range(3):
            out += p[dy:dy + h, dx:dx + w]
    return out


def adjacent(p1, p2):
    return max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1])) == 1


def calc_dps(to_hit, damage):
    return damage * min(20, max(0, (to_hit - 1))) / 20


@Strategy.wrap
def assert_strategy(error=None):
    yield True
    assert 0, error


def copy_result(func):
    @wraps(func)
    def f(*args, **kwargs):
        ret = func(*args, **kwargs)
        if isinstance(ret, list):
            return ret.copy()
        if isinstance(ret, tuple):
            return tuple((x.copy() if isinstance(x, list) else x for x in ret))
        return ret.copy()

    return f


def dilate(mask, radius=1, with_diagonal=True):
    d = radius * 2 + 1
    if with_diagonal:
        kernel = np.ones((d, d), dtype=np.uint8)
    else:
        kernel = np.zeros((d, d), dtype=np.uint8)
        kernel[radius: radius + 1, :] = 1
        kernel[:, radius: radius + 1] = 1
    return cv2.dilate(mask.astype(np.uint8), kernel).astype(bool)


def slice_with_padding(array, a1, a2, b1, b2, pad_value=0):
    ret = np.zeros_like(array, shape=(a2 - a1, b2 - b1)) + pad_value
    off_a1 = -a1 if a1 < 0 else 0
    off_b1 = -b1 if b1 < 0 else 0
    off_a2 = array.shape[0] - a2 if a2 > array.shape[0] else ret.shape[0]
    off_b2 = array.shape[1] - b2 if b2 > array.shape[1] else ret.shape[1]
    ret[off_a1: off_a2, off_b1: off_b2] = array[max(0, a1): a2, max(0, b1): b2]
    return ret


def slice_square_with_padding(array, center_y, center_x, radius, pad_value=0):
    return slice_with_padding(array, center_y - radius, center_y + radius + 1,
                              center_x - radius, center_x + radius + 1, pad_value=pad_value)

