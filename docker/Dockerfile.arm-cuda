ARG NVIDIA_PYTORCH_BASE_IMAGE=swr.cn-southwest-2.myhuaweicloud.com/ictrek/nvidia-pytorch:arm_25.08-py3

FROM ${NVIDIA_PYTORCH_BASE_IMAGE} AS sd-cpp-builder
ARG GITHUB_ACCELERATOR=https://gh-proxy.com/
ARG SD_CPP_REF=97d2990807fe6d558e395f8764198d7c7e7b411c
ARG GGML_REF=8e800cef2948046cc47f9db6090491c6128ca42c
ARG SD_CPP_CMAKE_ARGS="-DSD_CUDA=ON -DSD_WEBP=OFF -DSD_WEBM=ON"
WORKDIR /tmp
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl build-essential cmake tar && rm -rf /var/lib/apt/lists/*
COPY docker/install_sd_cpp.sh /usr/local/bin/install_sd_cpp.sh
RUN chmod +x /usr/local/bin/install_sd_cpp.sh && SD_CPP_INSTALL_DIR=/opt/sd-cpp SD_CPP_SKIP_VERIFY=true /usr/local/bin/install_sd_cpp.sh

FROM ${NVIDIA_PYTORCH_BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IMAGE_STUDIO_MOCK_WHEN_RUNTIME_MISSING=false
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=sd-cpp-builder /opt/sd-cpp/bin/sd-cli /usr/local/bin/sd-cli
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 5000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
