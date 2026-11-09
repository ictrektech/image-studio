"""OpenAPI metadata only: preserve existing handlers and response serialization."""
from __future__ import annotations

from copy import deepcopy
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic import TypeAdapter

from app.models import JobRecord, ModelInfo

S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": deepcopy(properties), "required": list(properties) if required is None else required, "additionalProperties": True}


def array(items: dict) -> dict:
    return {"type": "array", "items": items}


def reference(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def build_openapi(app) -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    spec = get_openapi(title=app.title, version=app.version, routes=app.routes, servers=[{"url": "."}])
    components = spec.setdefault("components", {}).setdefault("schemas", {})
    for model in (JobRecord, ModelInfo):
        schema = TypeAdapter(model).json_schema(ref_template="#/components/schemas/{model}")
        components.update(schema.pop("$defs", {}))
        components[model.__name__] = schema
    template = obj({"id": S, "name": S, "description": S, "payload": {"type": "object", "description": "Generation template parameters, limited to the template whitelist."}})
    input_file = obj({"input_id": S, "filename": S, "size": I, "created_at": S, "url": S})
    output = obj({"job_id": S, "filename": S, "url": S, "size": I, "created_at": {"type": "string", "format": "date-time"}, "prompt": S})
    progress = obj({"percent": {"type": "number", "minimum": 0, "maximum": 1}}, [])
    execution = obj({"status": S, "stopped": B, "progress": progress, "result": {"type": "object", "description": "Native execution result, including output references or a retryable failure."}}, ["status", "stopped"])
    binding = obj({"protocol_version": I, "configured": B, "binding_revision": I, "approved_model_count": I}, ["protocol_version", "configured"])
    registration_model = obj({"id": S, "endpoints": array(S), "capabilities": array(S), "model_kind": S})
    schemas = {
        "TemplateRecord": template,
        "InputFile": input_file,
        "GeneratedOutput": output,
        "ExecutionStatus": execution,
        "SchedulerBindingStatus": binding,
        "DownloadSourceSubmission": obj({"status": S, "model_id": S, "detail": S, "task": {"type": "object", "properties": {"task_id": S}, "description": "Original weight-management task submission; poll the returned task through V-Scheduler."}}, ["status", "model_id"]),
    }
    components.update(schemas)
    template["properties"]["payload"] = obj({key: deepcopy(components["GenerateRequest"]["properties"][key]) for key in ("model_key", "model_variant", "width", "height", "steps", "cfg_scale", "sampler", "vae_tiling", "vae_tile_size", "negative_prompt")}, [])
    responses = {
        "about": obj({"app_id": S, "app_version": S, "profile": S, "data_dir": S, "modelhub_root": S, "model_hub_api_url": S, "sd_cpp_bin": S, "max_concurrency": I}),
        "templates_list": obj({"templates": array(reference("TemplateRecord")), "default_template": {"type": ["string", "null"]}}),
        "templates_create": reference("TemplateRecord"), "templates_rename": reference("TemplateRecord"), "templates_delete": obj({"ok": B}),
        "me": obj({"user_key": S, "authenticated": {"type": "boolean", "description": "Indicates token presence, not proof that the token was verified."}}),
        "settings": obj({"language": {"type": "string", "enum": ["auto", "zh-CN", "zh-TW", "en"]}}),
        "update_settings": obj({"language": {"type": "string", "enum": ["auto", "zh-CN", "zh-TW", "en"]}}),
        "generate": reference("JobRecord"), "jobs": array(reference("JobRecord")), "job": reference("JobRecord"),
        "upload_job_to_immich": reference("JobRecord"), "retry_job_immich_upload": reference("JobRecord"),
        "delete_generation_job": obj({"deleted": B, "job_id": S}), "outputs": array(reference("GeneratedOutput")),
        "photocraft_handoff": obj({"url": S, "expires_at": {"type": "number", "description": "Unix seconds; fractional seconds are retained. The ticket expires after 300 seconds."}}),
        "upload_input": reference("InputFile"), "inputs": array(reference("InputFile")), "remove_input": obj({"deleted": B, "input_id": S}),
        "models": array(reference("ModelInfo")), "model": reference("ModelInfo"),
        "v_router_registration": obj({"service_id": S, "name": S, "visibility": S, "protocol": S, "base_url": S, "model_kind": S, "models": array(registration_model), "ttl_seconds": I, "scheduler": obj({"protocol_version": I, "lifecycle_protocol_version": I, "preemption_modes": array(S), "app_id": S, "binding_endpoint": S, "executor_base_url": S, "upstream_url": S, "async_models": array(obj({"id": S, "task_type": S})), "execution_settings": {"type": "object"}, "binding": reference("SchedulerBindingStatus")})}),
        "v_router_status": obj({"configured": B, "reachable": B, "api_url": S, "eligible_models": I, "error": S}),
        "pull": obj({"status": S, "model_id": S, "variant": S, "sources": array(reference("DownloadSourceSubmission"))}),
        "stop": obj({"status": S, "model_id": S, "variant": S, "tasks": array({"description": "Original weight-management cancellation result for each active download."})}, ["status", "model_id", "variant"]),
        "sync": obj({"synced": I, "hf_added": I, "ms_added": I, "ollama_added": I, "message": S}),
        "binding_status": reference("SchedulerBindingStatus"), "bind": obj({"configured": B, "binding_revision": I}),
        "execute": reference("ExecutionStatus"), "inspect": reference("ExecutionStatus"), "cancel": reference("ExecutionStatus"),
        "health": obj({"status": S, "app": S, "version": S}),
    }
    request_fields = {
        "templates_create": obj({"name": S, "payload": {"type": "object", "minProperties": 1, "description": "Allowed keys: model_key, model_variant, width, height, steps, cfg_scale, sampler, vae_tiling, vae_tile_size, negative_prompt."}}, ["payload"]),
        "templates_rename": obj({"name": S}, []),
        "update_settings": obj({"language": {"type": "string", "enum": ["auto", "zh-CN", "zh-TW", "en"]}}, []),
        "photocraft_handoff": obj({"filename": S}, ["filename"]),
        "execute": obj({"fence": I, "parameters": obj({"user_key": S, "job_id": S}), "lease_seconds": I, "preempted": B}, ["fence", "parameters"]),
        "inspect": obj({"fence": I}, ["fence"]),
        "cancel": obj({"fence": I, "parameters": obj({"user_key": S, "job_id": S}), "preempted": B}, ["fence", "parameters"]),
    }
    from app.services.scheduler import RUNTIME_PARAMETER_FIELDS
    from app.services.scheduler_binding import URL, UPSTREAM, APP_ID
    parameter_properties = {name: deepcopy(components["JobRecord"]["properties"][name]) for name in RUNTIME_PARAMETER_FIELDS}
    parameter_properties["has_reference"] = B
    model_limit = obj({name: {"type": "integer", "minimum": 0} for name in ("width", "height", "steps", "batch_count", "video_frames", "prompt_characters", "negative_prompt_characters")})
    request_fields["bind"] = obj({
        "protocol_version": {"type": "integer", "const": 1},
        "binding_revision": {"type": "integer", "minimum": 1},
        "app_id": {"type": "string", "const": APP_ID},
        "url": {"type": "string", "const": URL, "description": "Application binding snapshot; this legacy alias is not a caller-selected provider address."},
        "upstream_url": {"type": "string", "const": UPSTREAM},
        "token": {"type": "string", "minLength": 32, "maxLength": 4096, "writeOnly": True, "description": "Provisioned Scheduler service identity, never an upstream vendor key."},
        "executor_token": {"type": "string", "minLength": 32, "maxLength": 4096, "writeOnly": True},
        "models": {"type": "object", "additionalProperties": S, "minProperties": 1, "maxProperties": 512},
        "gateway_executors": {"type": "object", "additionalProperties": S, "maxProperties": 512},
        "model_limits": {"type": "object", "additionalProperties": model_limit},
        "model_parameters": {"type": "object", "additionalProperties": obj(parameter_properties)},
        "execution_settings": obj({"profile": S, "runtime": S, "logical_cpu_count": {"type": ["integer", "null"]}, "max_concurrency": I, "sd_cpp_extra_args_sha256": S}),
    }, ["protocol_version", "binding_revision", "app_id", "url", "upstream_url", "token", "executor_token", "models", "model_limits", "model_parameters", "execution_settings"])
    spec["components"]["securitySchemes"] = {
        "VOSBearer": {"type": "http", "scheme": "bearer", "description": "VOS user token for stable user attribution. Trusted-network legacy fallbacks are not a public authentication boundary."},
        "SchedulerApplication": {"type": "http", "scheme": "bearer", "description": "Verified V-Scheduler application identity only; ordinary users, model keys and vendor keys are insufficient."},
        "ExecutorBearer": {"type": "http", "scheme": "bearer", "description": "Separately provisioned executor_token from the accepted binding."},
    }
    files = {"output_file", "input_file", "photocraft_output"}
    from app.routers.api import router as application_router
    from app.services.scheduler import router as execution_router
    from app.services.scheduler_binding import router as binding_router
    routes = [route for router in (application_router, execution_router, binding_router, app) for route in router.routes]
    documented = set()
    for route in routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        name = route.endpoint.__name__
        for method in route.methods:
            if (method, route.path) in documented:
                continue
            documented.add((method, route.path))
            operation = spec["paths"][route.path][method.lower()]
            code = str(route.status_code or 200)
            if name in responses:
                operation["responses"][code] = {"description": "Successful application JSON response; not wrapped in a Scheduler envelope.", "content": {"application/json": {"schema": responses[name]}}}
            elif name in files:
                operation["responses"][code] = {"description": "Binary file. Inspect Content-Type; errors remain JSON. PhotoCraft handoffs require the expiring ticket in the URL.", "content": {"*/*": {"schema": {"type": "string", "format": "binary"}}}}
            if name in request_fields:
                operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": request_fields[name]}}}
            if name == "bind":
                operation["security"] = [{"SchedulerApplication": []}]
            elif name in {"execute", "inspect", "cancel"}:
                operation["security"] = [{"ExecutorBearer": []}]
                operation["parameters"] = [parameter for parameter in operation.get("parameters", []) if parameter.get("name", "").lower() != "authorization"]
            elif name in {"me", "settings", "update_settings", "generate", "jobs", "job", "delete_generation_job", "outputs", "output_file", "photocraft_handoff", "upload_input", "inputs", "input_file", "remove_input", "upload_job_to_immich", "retry_job_immich_upload"}:
                operation["security"] = [{"VOSBearer": []}, {}]
            else:
                operation["security"] = []
            operation["responses"].setdefault("default", {
                "description": "Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.",
                "content": {"application/json": {"schema": obj({"detail": {"description": "FastAPI error message or structured validation details."}})}, "text/plain": {"schema": S}},
            })
            operation["x-contract-source"] = f"{route.endpoint.__module__}.{name}"
    spec["paths"]["/api/v1/immich"]["get"]["description"] = "Immich connection status; no credentials are returned. See the five states in ImmichStatusResponse."
    spec["paths"]["/api/v1/inputs"]["post"]["description"] = "Upload an img2img/edit reference (png/jpg/jpeg/webp, at most 20 MiB); returns an input_id for generation."
    components["ImmichStatusResponse"]["description"] = "Immich connectivity state without credentials."
    spec["info"]["description"] = (
        "Image Studio application API; successful JSON is not wrapped in a Scheduler envelope. "
        "Business routes attribute data to the current user; legacy trusted-network header/token/IP fallbacks remain supported. "
        "Use a verified VOS Bearer token for stable same-account ownership. V-Scheduler inference keys are not Image Studio management credentials. "
        "Scheduler binding accepts only the verified V-Scheduler application identity; execution callbacks require its separately provisioned executor token. "
        "Do not expose trusted-network fallback routes as an independent public account-authentication boundary."
    )
    app.openapi_schema = spec
    return spec
