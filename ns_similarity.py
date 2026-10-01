"""Exact, incremental 64-bit pHash comparisons; no photo reads or file changes."""
import re

import numpy as np

MAX_DISTANCE = 16
MIN_SCORE = 75
VALID_HASH = re.compile(r'^[0-9a-fA-F]{16}$')


def usable(value):
    return isinstance(value, str) and bool(VALID_HASH.fullmatch(value))


class HashIndex:
    """Exact vectorized Hamming comparisons over compact uint64 hashes.

    A wider radius defeats the old four-block candidate shortcut. Compare bounded
    chunks in NumPy instead of constructing a quadratic distance matrix or Python
    candidate sets. Initial work is O(n²); each new hash scans the known hashes.
    Equal hashes share a bucket; refresh inserts each distinct hash once.
    """
    def __init__(self):
        self.values = np.empty(1024, dtype=np.uint64)
        self.size = 0

    def add(self, value):
        if self.size == len(self.values):
            grown = np.empty(2 * len(self.values), dtype=np.uint64)
            grown[:self.size] = self.values
            self.values = grown
        self.values[self.size] = value
        self.size += 1

    def near(self, value):
        for start in range(0, self.size, 65536):
            values = self.values[start:min(start + 65536, self.size)]
            distances = np.bitwise_count(values ^ np.uint64(value))
            for i in np.flatnonzero(distances <= MAX_DISTANCE):
                yield int(values[i]), int(distances[i])


def refresh(conn, *, cancelled=lambda: False, progress=lambda done, total: None):
    """Publish batches of complete hash comparisons. Interrupted work resumes on Index.

    Hash-keyed relationships remain valid when content membership changes; readers
    join current content hashes, so an old hash can never supply a changed photo's
    matches. Equal hashes have implicit zero distance, avoiding quadratic storage.
    A completion marker and all pairs for its hash commit atomically.
    """
    wanted = {h.lower() for (h,) in conn.execute("SELECT DISTINCT phash FROM contents WHERE phash_state='ok'") if usable(h)}
    known = {h for (h,) in conn.execute('SELECT phash FROM similarity_hashes')}
    missing = sorted(wanted - known)
    index = HashIndex()
    for value in known:
        index.add(int(value, 16))
    progress(0, len(missing))
    done = 0
    try:
        for value in missing:
            if cancelled():
                conn.rollback()
                return False
            number = int(value, 16)
            for other, distance in index.near(number):
                if cancelled():
                    conn.rollback()
                    return False
                a, b = sorted((value, f'{other:016x}'))
                conn.execute('INSERT OR IGNORE INTO content_similarity(low_hash,high_hash,distance) VALUES(?,?,?)', (a,b,distance))
            conn.execute('INSERT INTO similarity_hashes(phash) VALUES(?)', (value,))
            index.add(number)
            done += 1
            if done % 256 == 0:
                conn.commit()
                progress(done, len(missing))
        conn.commit()
        progress(done, len(missing))
        return True
    except BaseException:
        conn.rollback()
        raise
