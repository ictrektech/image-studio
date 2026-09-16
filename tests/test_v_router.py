from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.v_router import v_router_connection_status, v_router_model_info


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
            "app.services.v_router.fetch_v_router_generation_models",
            AsyncMock(return_value=[{"key": "one"}, {"key": "two"}]),
        ):
            status = await v_router_connection_status("token")
        self.assertTrue(status["reachable"])
        self.assertEqual(status["eligible_models"], 2)
        self.assertEqual(status["error"], "")

    async def test_connection_status_exposes_failure(self):
        with patch(
            "app.services.v_router.fetch_v_router_generation_models",
            AsyncMock(side_effect=RuntimeError("upstream unavailable")),
        ):
            status = await v_router_connection_status("token")
        self.assertFalse(status["reachable"])
        self.assertIn("upstream unavailable", status["error"])


if __name__ == "__main__":
    unittest.main()
