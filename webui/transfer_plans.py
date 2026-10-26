"""Short-lived, per-server destination plans. Confirmation always rechecks live state."""
from collections import OrderedDict
import threading
import time

from engine import index_history, ns_db, transfer_preview

MAX_PLANS = 4
LIFETIME_SECONDS = 300


class PlanCache:
    def __init__(self):
        self._plans = OrderedDict()
        self._lock = threading.Lock()

    def preview(self, conn, *, source, destination, mode, photo_ids=None, source_subdir=None,
                token=None, page=1, folder=None, file_page=1):
        key = (str(source), str(destination), mode, token)
        if token is not None:
            with self._lock:
                cached = self._plans.get(key)
                if cached is not None and time.monotonic() - cached[0] >= LIFETIME_SECONDS:
                    del self._plans[key]; cached = None
                if cached is not None: self._plans.move_to_end(key)
            if cached is None:
                raise ns_db.RevisionConflict('The destination preview expired. Refresh the preview and confirm again.')
            plan = cached[1]
            # The browser sends only a token for paging. Retain validation for API
            # callers that also supply scope; they cannot retarget a cached plan.
            ids = plan['file_ids'] if photo_ids is None and source_subdir is None else photo_ids
            try:
                transfer_preview.check(conn,token,source=source,destination=destination,
                    photo_ids=ids,source_subdir=source_subdir)
            except ValueError as exc:
                raise ns_db.RevisionConflict(str(exc)) from exc
        else:
            plan = transfer_preview.preview(conn,source=source,destination=destination,mode=mode,
                photo_ids=photo_ids,source_subdir=source_subdir,materialize=True)
            key = (str(source),str(destination),mode,plan['token'])
            with self._lock:
                self._plans[key] = (time.monotonic(),plan)
                self._plans.move_to_end(key)
                while len(self._plans) > MAX_PLANS: self._plans.popitem(last=False)
        result = transfer_preview.page_result(plan,page=page,folder=folder,file_page=file_page)
        if token is None:
            result['index_basis'] = index_history.for_scope(conn,source,source_subdir)
        return result
