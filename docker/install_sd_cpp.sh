#!/bin/sh
set -eu

SD_CPP_REF="${SD_CPP_REF:-97d2990807fe6d558e395f8764198d7c7e7b411c}"
GGML_REF="${GGML_REF:-8e800cef2948046cc47f9db6090491c6128ca42c}"
LIBWEBM_REF="${LIBWEBM_REF:-5bf12267eea773a32fcf4949de52b0add158a8d5}"
GITHUB_ACCELERATOR="${GITHUB_ACCELERATOR:-https://gh-proxy.com/}"
SD_CPP_INSTALL_DIR="${SD_CPP_INSTALL_DIR:-/opt/sd-cpp}"
SD_CPP_CMAKE_ARGS="${SD_CPP_CMAKE_ARGS:--DSD_WEBP=OFF -DSD_WEBM=OFF}"
SD_CPP_BUILD_JOBS="${SD_CPP_BUILD_JOBS:-$(nproc)}"
SD_CPP_SKIP_VERIFY="${SD_CPP_SKIP_VERIFY:-false}"

work_dir="/tmp/sd-cpp-build"

download() {
  url="$1"
  output="$2"
  if [ -n "$GITHUB_ACCELERATOR" ]; then
    case "$GITHUB_ACCELERATOR" in
      */) full_url="${GITHUB_ACCELERATOR}${url}" ;;
      *) full_url="${GITHUB_ACCELERATOR}/${url}" ;;
    esac
  else
    full_url="$url"
  fi
  curl -L --fail --retry 3 --connect-timeout 20 --max-time 300 -o "$output" "$full_url"
}

rm -rf "$work_dir"
mkdir -p "$work_dir/src" "$SD_CPP_INSTALL_DIR/bin"

download "https://github.com/leejet/stable-diffusion.cpp/archive/${SD_CPP_REF}.tar.gz" "$work_dir/sd.tar.gz"
tar -xzf "$work_dir/sd.tar.gz" -C "$work_dir/src" --strip-components=1

rm -rf "$work_dir/src/ggml"
mkdir -p "$work_dir/src/ggml"
download "https://github.com/leejet/ggml/archive/${GGML_REF}.tar.gz" "$work_dir/ggml.tar.gz"
tar -xzf "$work_dir/ggml.tar.gz" -C "$work_dir/src/ggml" --strip-components=1

rm -rf "$work_dir/src/thirdparty/libwebm"
mkdir -p "$work_dir/src/thirdparty/libwebm"
download "https://github.com/webmproject/libwebm/archive/${LIBWEBM_REF}.tar.gz" "$work_dir/libwebm.tar.gz"
tar -xzf "$work_dir/libwebm.tar.gz" -C "$work_dir/src/thirdparty/libwebm" --strip-components=1

# shellcheck disable=SC2086
cmake -S "$work_dir/src" -B "$work_dir/build" -DCMAKE_BUILD_TYPE=Release $SD_CPP_CMAKE_ARGS
cmake --build "$work_dir/build" --config Release -j"$SD_CPP_BUILD_JOBS"
install -m 0755 "$work_dir/build/bin/sd-cli" "$SD_CPP_INSTALL_DIR/bin/sd-cli"
if [ "$SD_CPP_SKIP_VERIFY" != "true" ]; then
  "$SD_CPP_INSTALL_DIR/bin/sd-cli" --help >/dev/null
fi
