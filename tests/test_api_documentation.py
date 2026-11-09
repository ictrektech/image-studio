import unittest

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app


class ApiDocumentationTests(unittest.TestCase):
    def test_every_application_operation_has_a_response_contract(self):
        spec = app.openapi()
        for path, methods in spec["paths"].items():
            for method, operation in methods.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                for status, response in operation["responses"].items():
                    if str(status).startswith("2"):
                        content = response.get("content", {})
                        self.assertTrue(content, (method, path, status))
                        self.assertTrue(all(value.get("schema") for value in content.values()), (method, path, status))
        def check_references(value):
            if isinstance(value, dict):
                if value.get("$ref", "").startswith("#/"):
                    target = spec
                    for part in value["$ref"][2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                for child in value.values():
                    check_references(child)
            elif isinstance(value, list):
                for child in value:
                    check_references(child)
        check_references(spec)
        self.assertEqual(spec["paths"]["/api/v1/generate"]["post"]["responses"]["200"]["content"]["application/json"]["schema"], {"$ref": "#/components/schemas/JobRecord"})
        self.assertEqual(spec["paths"]["/api/v1/jobs/{job_id}/immich-upload"]["post"]["responses"]["202"]["content"]["application/json"]["schema"], {"$ref": "#/components/schemas/JobRecord"})
        for schema in spec["components"]["schemas"].values():
            self.assertIsInstance(schema, dict)
        self.assertEqual(spec["paths"]["/api/v1/scheduler/binding"]["post"]["security"], [{"SchedulerApplication": []}])
        self.assertEqual(spec["paths"]["/api/v1/scheduler/executions/{attempt}/inspect"]["post"]["security"], [{"ExecutorBearer": []}])

    def test_documentation_does_not_add_runtime_response_filtering(self):
        from app.routers.api import router
        from app.services.scheduler_binding import router as bindings
        checked = set()
        for route in [*router.routes, *bindings.routes]:
            if isinstance(route, APIRoute) and route.endpoint.__name__ in {"generate", "job", "jobs", "models", "bind"}:
                checked.add(route.endpoint.__name__)
                self.assertIsNone(route.response_field, route.path)
        self.assertEqual(checked, {"generate", "job", "jobs", "models", "bind"})

    def test_swagger_and_spec_work_under_a_reverse_proxy_prefix(self):
        client = TestClient(app, root_path="/api/com.ictrek.image-studio")
        page = client.get("/docs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("url: 'openapi.json'", page.text)
        self.assertNotIn("url: '/openapi.json'", page.text)
        self.assertIn({"url": "."}, client.get("/openapi.json").json()["servers"])


if __name__ == "__main__":
    unittest.main()
