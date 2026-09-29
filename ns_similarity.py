"""Exact, incremental 64-bit pHash comparisons; no photo reads or file changes."""
from collections import defaultdict
import re

MAX_DISTANCE = 6
MIN_SCORE = 90
VALID_HASH = re.compile(r'^[0-9a-fA-F]{16}$')


def usable(value):
    return isinstance(value, str) and bool(VALID_HASH.fullmatch(value))


class HashIndex:
    """Four 16-bit blocks. At distance <=6, one block differs in at most one bit.

    Probe that block and its 16 one-bit neighbors, then verify the whole hash.
    This candidate reduction is exact over the entire supported slider range.
    Identical hashes share a bucket; callers insert each distinct hash once.
    """
    def __init__(self):
        self.tables = [defaultdict(list) for _ in range(4)]

    def add(self, value):
        for i, table in enumerate(self.tables):
            table[(value >> (16 * i)) & 65535].append(value)

    def near(self, value):
        candidates = set()
        for i, table in enumerate(self.tables):
            block = (value >> (16 * i)) & 65535
            candidates.update(table.get(block, ()))
            for bit in range(16):
                candidates.update(table.get(block ^ (1 << bit), ()))
        for other in candidates:
            distance = (value ^ other).bit_count()
            if distance <= MAX_DISTANCE:
                yield other, distance


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
