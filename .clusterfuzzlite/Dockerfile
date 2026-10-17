# ClusterFuzzLite build image for the fuzz targets in tests/fuzz (see docs/fuzzing.md).
#
# The OSS-Fuzz base image ships Python 3.11 and an atheris built for it. The project needs
# Python 3.14 (its sources use PEP 758 syntax that older interpreters cannot parse), so this image
# installs its own 3.14 with uv in /opt/fuzz-venv and leaves the base image's python3 alone: the
# base `compile` script still runs it to find atheris' sanitizer libraries.
#
# Everything installed here is pinned: the base image and uv by digest, Python by its exact
# version, the project's runtime packages by uv.lock (hash-checked), the fuzzing tools by hash in
# .clusterfuzzlite/requirements.txt. The image runs as root, as the OSS-Fuzz builders do.
FROM gcr.io/oss-fuzz-base/base-builder-python:v1@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9

COPY --from=ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/opt/fuzz-venv \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

# The project's runtime packages exactly as locked, without the project itself (its source is
# put on the path by build.sh).
COPY pyproject.toml uv.lock /tmp/lock/
RUN cd /tmp/lock \
    && uv python install 3.14.7 --no-bin \
    && uv sync --frozen --no-dev --no-install-project --python 3.14.7 \
    && rm -rf /tmp/lock

# The fuzzing tools: the atheris wheel for CPython 3.14 and PyInstaller.
COPY .clusterfuzzlite/requirements.txt /tmp/fuzz-requirements.txt
RUN uv pip install --python /opt/fuzz-venv/bin/python --require-hashes --no-deps \
        -r /tmp/fuzz-requirements.txt \
    && rm /tmp/fuzz-requirements.txt

# The source of the commit under test, and the build script the base `compile` runs.
ENV PROJECT_DIR=$SRC/sankey-studio
COPY . $PROJECT_DIR
WORKDIR $PROJECT_DIR
COPY .clusterfuzzlite/build.sh $SRC/
