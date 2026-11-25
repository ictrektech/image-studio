import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import compute


class ComputeTests(unittest.TestCase):
    def test_deployment_uses_authorized_fixed_profile_and_packaged_image(self):
        app = FastAPI()
        app.include_router(compute.router)
        image = "registry.example.test/team/backend:orin"
        catalog = {"jetson-orin": {"image": image, "profile": "l4t"}}
        env = {"IMAGE_STUDIO_BACKEND_IMAGES": json.dumps(catalog)}
        target = {"kind": "ssh", "id": "node-orin", "profile": "jetson-orin"}
        received = []
        new_client = httpx.AsyncClient

        def scheduler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer fixture-application")
            if request.url.path.endswith("/managed-nodes"):
                data = {"items": [{"id": "node-orin", "profile": "jetson-orin", "name": "Orin"}]}
            elif request.url.path.endswith(f"/backend-deployment-access/{compute.APP_ID}"):
                data = {"targets": [target], "repositories": [image.rsplit(":", 1)[0]]}
            else:
                received.append(json.loads(request.content))
                data = {"id": "a" * 32, "state": "pending"}
            return httpx.Response(200, json={"code": "OK", "data": data})

        response = {"code": 0, "data": {"id": "operator", "enable": 1, "delete": 0, "role_code": "normal_user"}}
        identity = AsyncMock(return_value=httpx.Response(200, json=response))
        with (
            patch.dict(os.environ, env),
            patch.object(settings, "scheduler_url", "http://scheduler.test/api/v1"),
            patch.object(settings, "scheduler_token", "fixture-application"),
            patch("app.routers.compute.deployment_client", side_effect=lambda: new_client(
                base_url=settings.scheduler_url + "/", headers={"Authorization": "Bearer " + settings.scheduler_token},
                transport=httpx.MockTransport(scheduler),
            )),
            patch.object(httpx.AsyncClient, "get", identity),
            TestClient(app) as api,
        ):
            request = {"kind": "ssh", "node_id": "node-orin", "request_key": "first-deploy"}
            route = "/api/v1/compute/deployments"
            self.assertEqual(api.post(route, json=request).status_code, 401)
            headers = {"Authorization": "Bearer fixture-vos"}
            self.assertEqual(api.post(route, json=request, headers=headers).status_code, 403)
            self.assertEqual(received, [])
            response["data"]["role_code"] = "system_admin"
            identity.return_value = httpx.Response(200, json=response)
            self.assertEqual(api.post(route, json={**request, "node_id": "ungranted"}, headers=headers).status_code, 403)
            reply = api.post(route, json=request, headers=headers)
            self.assertEqual(reply.status_code, 200, reply.text)
            self.assertEqual(received, [{
                "request_key": "first-deploy", "target": target, "image": image, "container_port": 5000,
                "config": {"mode": "image-studio-worker-v1", "profile": "l4t"},
            }])
