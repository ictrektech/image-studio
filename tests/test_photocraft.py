import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import api
from app.services import photocraft


class PhotoCraftHandoffTests(unittest.TestCase):
    def test_ticket_is_owned_file_scoped_temporary_and_audience_independent(self):
        app = FastAPI()
        app.include_router(api.router)
        job = SimpleNamespace(status="succeeded", outputs=["output.png"])
        photocraft._tickets.clear()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            body = b"\x89PNG\r\n\x1a\ntransport-fixture"
            (root / "output.png").write_bytes(body)
            with (
                patch.object(api, "verify_vos_identity", new=AsyncMock(side_effect=lambda token: token if token in {"owner", "other"} else "")),
                patch.object(photocraft, "load_job", side_effect=lambda user, key: job if user == "owner" and key == "job" else None),
                patch.object(photocraft, "job_dir", return_value=root),
                TestClient(app) as client,
            ):
                endpoint = "/api/v1/jobs/job/photocraft"
                payload = {"filename": "output.png"}
                self.assertEqual(client.post(endpoint, json=payload).status_code, 401)
                self.assertEqual(client.post(endpoint, json=payload, headers={"Authorization": "Bearer other"}).status_code, 404)
                response = client.post(endpoint, json=payload, headers={"Authorization": "Bearer owner"})
                self.assertEqual(response.status_code, 200)
                handoff = response.json()
                self.assertNotIn("access_token", handoff["url"])
                path = handoff["url"].removeprefix("/api/com.ictrek.image-studio")
                # PhotoCraft's own audience-bound identity cannot read the
                # source user's ordinary output URL, but this ticket names
                # exactly the file that the owner approved.
                fetched = client.get(path, headers={"Authorization": "Bearer photocraft-audience"})
                self.assertEqual(fetched.status_code, 200)
                self.assertEqual(fetched.content, body)
                self.assertEqual(fetched.headers["cache-control"], "private, no-store")
                self.assertEqual(client.get(path.replace("output.png", "another.png")).status_code, 404)
                with patch.object(photocraft.time, "time", return_value=handoff["expires_at"] + 1):
                    self.assertEqual(client.get(path).status_code, 404)
                renewed = client.post(endpoint, json=payload, headers={"Authorization": "Bearer owner"}).json()
                (root / "output.png").unlink()
                self.assertEqual(client.get(renewed["url"].removeprefix("/api/com.ictrek.image-studio")).status_code, 404)
        photocraft._tickets.clear()
