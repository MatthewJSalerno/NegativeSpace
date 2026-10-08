"""Persistent instance address policy, using generated application data only."""
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from webui import access
from webui.app import create_app
from webui_api_test import ApiCase


class InstanceAccess(ApiCase):
    def put(self, hosts, revision=0, **extra):
        return self.client.put("/api/v1/access", json=dict(hosts=hosts, revision=revision, **extra))

    def test_access_exists_before_catalog_and_survives_catalog_replacement_and_restart(self):
        self.assertEqual(self.client.get("/api/v1/access").json()["revision"], 0)
        self.assertFalse(self.cfg.db_path.exists())
        result = self.put(["Review.Example", "192.0.2.5", "2001:db8::1"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["hosts"], ["review.example", "192.0.2.5", "2001:db8::1"])
        path = self.cfg.base / "access.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.stat().st_uid, os.getuid())
        self.create_catalog()
        self.cfg.db_path.unlink()
        self.create_catalog()
        with TestClient(create_app(self.cfg), base_url="http://review.example") as restarted:
            self.assertEqual(restarted.get("/api/v1/access").json()["revision"], 1)
            self.assertEqual(restarted.get("/api/v1/status").status_code, 200)

    def test_invalid_inputs_do_not_write_or_expand_trust(self):
        for hosts in (["*"], ["*.example"], ["https://review.example"], ["review.example:8092"],
                      ["review.example/a"], ["a,b"], ["a@b"], [""], [123], "example", ["x"] * 129):
            with self.subTest(hosts=hosts):
                self.assertEqual(self.put(hosts).status_code, 400)
        for body in ({"hosts": [], "revision": True}, {"hosts": [], "revision": 0, "unexpected": 1},
                     {"hosts": [], "revision": 0, "confirm_current_host": "yes"}):
            self.assertEqual(self.client.put("/api/v1/access", json=body).status_code, 400)
        self.assertFalse((self.cfg.base / "access.json").exists())

    def test_revision_conflict_and_two_simultaneous_writers(self):
        def save(host):
            try:
                return access.save(self.cfg, {"hosts": [host], "revision": 0}, "testserver")["revision"]
            except access.AccessError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ("one.example", "two.example")))
        self.assertCountEqual(results, [1, "access_changed"])
        self.assertEqual(self.put(["third.example"]).status_code, 409)
        self.assertNotIn("third.example", access.effective(self.cfg))

    def test_removing_current_host_requires_confirmation_and_revokes_socket(self):
        self.assertEqual(self.put(["review.example", "next.example"]).status_code, 200)
        with TestClient(create_app(self.cfg), base_url="http://review.example") as other:
            with other.websocket_connect("ws://review.example/api/v1/ws/jobs") as ws:
                self.assertIn("active", ws.receive_json())
                body = {"hosts": ["next.example"], "revision": 1}
                refused = other.put("/api/v1/access", json=body)
                self.assertEqual(refused.json()["error"], "current_address_removed")
                self.assertEqual(other.get("/api/v1/status").status_code, 200)
                accepted = other.put("/api/v1/access", json=dict(body, confirm_current_host=True))
                self.assertEqual(accepted.status_code, 200)
                self.assertTrue(accepted.json()["current_removed"])
                self.assertEqual(other.get("/api/v1/status").status_code, 400)
                with self.assertRaises(WebSocketDisconnect) as disconnected:
                    ws.receive_json()
                self.assertEqual(disconnected.exception.code, 1008)
        self.assertEqual(self.client.get("/api/v1/status", headers={"Host": "next.example"}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/status", headers={"Host": "localhost"}).status_code, 200)

    def test_environment_addresses_remain_protected(self):
        result = self.put(["testserver", "localhost", "extra.example"])
        self.assertEqual(result.json()["hosts"], ["extra.example"])
        self.assertIn("testserver", result.json()["protected_hosts"])
        self.assertEqual(self.put([], 1).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/status").status_code, 200)

    def test_foreign_origin_cannot_change_addresses(self):
        response = self.client.put("/api/v1/access", json={"hosts": ["attacker.example"], "revision": 0},
                                   headers={"Origin": "http://attacker.example"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("attacker.example", access.effective(self.cfg))

    def test_symlink_and_corrupt_configuration_fail_closed_with_bootstrap_recovery(self):
        path = self.cfg.base / "access.json"
        outside = self.root / "outside.json"
        outside.write_text(json.dumps({"hosts": ["outside.example"], "revision": 4}))
        original = outside.read_bytes()
        path.symlink_to(outside)
        self.assertEqual(self.client.get("/api/v1/access").status_code, 503)
        self.assertEqual(self.put(["extra.example"]).status_code, 503)
        self.assertEqual(outside.read_bytes(), original)
        self.assertEqual(self.client.get("/api/v1/status", headers={"Host": "outside.example"}).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/status").status_code, 200)
        path.unlink()
        path.write_text('{broken')
        self.assertEqual(self.client.get("/api/v1/access").status_code, 503)
        self.assertEqual(self.put(["extra.example"]).status_code, 503)
        self.assertEqual(path.read_text(), '{broken')

    def test_failed_atomic_publish_preserves_policy_and_cleans_owned_temporary(self):
        self.assertEqual(self.put(["one.example"]).status_code, 200)
        before = (self.cfg.base / "access.json").read_bytes()
        with patch("webui.access.os.replace", side_effect=OSError("generated write failure")):
            self.assertEqual(self.put(["two.example"], 1).status_code, 503)
        self.assertEqual((self.cfg.base / "access.json").read_bytes(), before)
        self.assertFalse(list(self.cfg.base.glob(".access-*.tmp")))
        self.assertNotIn("two.example", access.effective(self.cfg))
