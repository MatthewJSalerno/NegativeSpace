# TODO

## Durability claims: stated vs enforced

Two separate audits have caught the same failure mode — a guarantee written down more strongly than the code actually enforces. This table exists so every durability claim resolves to either **enforced and tested** or **a documented limitation**, and never sits quietly in between.

The rule: if a claim cannot be enforced, weaken the claim. Do not leave prose asserting something the code only usually does.

| # | Claim | Stated in | Status |
| :--- | :--- | :--- | :--- |
| 1 | A source is deleted only after its copy's **bytes** are fsynced | `project-spec.md` §4.2, §7 | **Enforced**, tested (`durability barriers precede source deletion`) |
| 2 | …and after the copy's **own directory entry** is fsynced | `project-spec.md` §4.2 | **Enforced**, tested |
| 3 | …and after **every ancestor entry from `--dest` down**, retried until it succeeds | `project-spec.md` §4.2 | **Enforced**, tested (`a failed ancestor sync is retried not forgotten`) |
| 4 | The chain walk never touches anything **above** `--dest` | this file | **Enforced**, tested (`the durability chain never reaches above the destination`) |
| 5 | The source is unchanged since it was verified | `project-spec.md` §4.2 | **Enforced**, tested (`a source edited after verification is kept`) |
| 6 | The copy is a different file from the source | `project-spec.md` §4.2 | **Enforced**, tested (`a source is never deleted as its own copy`) |
| 7 | `mtime` is preserved by a copy | `phase3-spec.md` §3.1 | **Verified** empirically during the run01 fixes |

### Outstanding

- [ ] **Filesystems without directory fsync are silently weaker.** `EINVAL`/`ENOTSUP` are tolerated by design — the operation is absent rather than failed — and `project-spec.md` §4.2 says the power-loss guarantee is correspondingly weaker there. But nothing says so *at runtime*: a user on exFAT or an odd network mount gets the weaker guarantee without ever being told. Log it once per run when a directory sync reports one of those errnos, naming the path, so the weaker guarantee is visible rather than inferred from the spec.

- [ ] **The audit log is less durable than the act it records.** The catalog runs WAL with `synchronous=NORMAL`, which survives process death but not power loss (see `get_db_connection`'s docstring). So a power cut can lose the `operations` row recording a deletion *even though the deletion itself is durable* — the file is gone and the record saying why is not. Decide between `synchronous=FULL` for the audit writes (slower, measure it), accepting the window, or fsyncing the WAL at run end. Whichever is chosen, state it where the durability claims are made.

- [ ] **Power-loss behaviour has never been tested, only reasoned about.** Every durability test asserts *which* fsyncs happen and in what order, not that a real power cut preserves the tree. That is a meaningful gap between "the barriers are in the right places" and "the guarantee holds". Options: `dm-log-writes` or device-mapper `flakey` in a VM to replay a crash at an arbitrary point, or a documented statement that it is untested here and why.

- [ ] **A destination on an NFS share exported `async` can acknowledge an fsync before data reaches the server's disk.** Nothing currently says this anywhere. It does not affect the current deployment — `--dest` is local NVMe — but the engine makes no check and the guarantee quietly weakens for anyone who points `--dest` at such a share. Document it beside the existing NFS caveat in the README, and consider whether it is worth detecting.

- [ ] **Re-audit these claims whenever the write path changes.** Both defects found so far were introduced *by a fix to this very path*: the ancestor chain was added, then forgotten after the first failure. A change to `copy_verify_delete`, `_mkdir_durable`, `_finalize_partial` or `_remove_verified_source` should end with this table re-checked rather than assumed.

## Other

Deferred performance and robustness work — a stalled worker having no deadline, the unchanged-file check loading every settled row, batch barriers at submission tails — lives in `project-spec.md` §8 with the condition that should bring each one back. This file tracks claims that need enforcing; §8 tracks work deliberately postponed.
