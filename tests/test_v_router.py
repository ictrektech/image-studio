from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.v_router import fetch_v_router_generation_models, v_router_api_candidates, v_router_connection_status, v_router_model_info


class VRouterModelsTest(unittest.IsolatedAsyncioTestCase):
    def test_model_requires_supported_generation_endpoint(self):
        self.assertIsNone(v_router_model_info({"id": "vendor/chat", "endpoints": ["chat/completions"]}))
        model = v_router_model_info({"qualified": "vendor/image", "endpoints": ["/v1/images/generations"]})
        self.assertIsNotNone(model)
        self.assertEqual(model["key"], "v-router/vendor/image")
        self.assertEqual(model["capabilities"], ["txt2img"])

    def test_image_studio_models_are_not_routed_back(self):
        self.assertIsNone(v_router_model_info({"qualified": "image-studio/sdxl", "endpoints": ["images/generations"]}))

    async def test_connection_status_exposes_eligible_count(self):
        with patch(
            "app.services.v_router._fetch_v_router_generation_models",
            AsyncMock(return_value=([{"key": "one"}, {"key": "two"}], "http://v-router:8080")),
        ):
            status = await v_router_connection_status("token")
        self.assertTrue(status["reachable"])
        self.assertEqual(status["eligible_models"], 2)
        self.assertEqual(status["error"], "")

    async def test_connection_status_exposes_failure(self):
        with patch(
            "app.services.v_router._fetch_v_router_generation_models",
            AsyncMock(side_effect=RuntimeError("upstream unavailable")),
        ):
            status = await v_router_connection_status("token")
        self.assertFalse(status["reachable"])
        self.assertIn("upstream unavailable", status["error"])

    def test_candidates_try_vos_aliases_before_host_port(self):
        with patch("app.services.v_router.settings.v_router_api_url", "http://v-router:8080"), patch(
            "app.services.v_router.settings.v_router_host_api_url", "http://host.docker.internal:22888"
        ):
            self.assertEqual(
                v_router_api_candidates(),
                ["http://v-router:8080", "http://v-router-backend:8080", "http://host.docker.internal:22888"],
            )

    async def test_model_lookup_falls_back_to_host_port(self):
        failed = type("Response", (), {"raise_for_status": lambda self: (_ for _ in ()).throw(RuntimeError("missing"))})()
        ready = type(
            "Response",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"models": [{"qualified": "vendor/image", "endpoints": ["images/generations"]}]},
            },
        )()
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[failed, failed, ready])
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        with patch("app.services.v_router.httpx.AsyncClient", return_value=client), patch(
            "app.services.v_router.settings.v_router_api_url", "http://v-router:8080"
        ), patch("app.services.v_router.settings.v_router_host_api_url", "http://host.docker.internal:22888"):
            models = await fetch_v_router_generation_models("token")
        self.assertEqual(models[0]["resolved_path"], "http://host.docker.internal:22888")


if __name__ == "__main__":
    unittest.main()
