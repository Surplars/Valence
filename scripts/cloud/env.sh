# Source from bash: source scripts/cloud/env.sh
_VALENCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export VALENCE_CLOUD_ENV="${_VALENCE_ROOT}/simulator/build/cloud-env"
export PATH="${VALENCE_CLOUD_ENV}/bin:${VALENCE_CLOUD_ENV}/sysroot/usr/bin:${VALENCE_CLOUD_ENV}/sysroot/usr/lib/llvm-19/bin:${PATH}"
export HOME="${VALENCE_CLOUD_ENV}/home"
export XDG_CACHE_HOME="${VALENCE_CLOUD_ENV}/cache"
export COURSIER_CACHE="${VALENCE_CLOUD_ENV}/cache/coursier"
export COURSIER_REPOSITORIES="https://repo.maven.apache.org/maven2"
export JAVA_TOOL_OPTIONS="-Duser.home=${HOME} -Xmx4g -XX:ActiveProcessorCount=2"
export BISON_PKGDATADIR="${VALENCE_CLOUD_ENV}/sysroot/usr/share/bison"
export GSIM_CXX="${VALENCE_CLOUD_ENV}/sysroot/usr/bin/clang++-19"
export GSIM_BUILD_JOBS=2
unset _VALENCE_ROOT
# Java does not inherit HTTPS_PROXY automatically. Reuse the executor's proxy;
# do not alter trust, OS networking, or access rules.
if [[ -n "${HTTPS_PROXY:-}" ]]; then
    _VALENCE_JAVA_PROXY="$(python3 - <<'PY'
import os, urllib.parse
u = urllib.parse.urlsplit(os.environ['HTTPS_PROXY'])
if u.scheme != 'http' or u.username or u.password:
    raise SystemExit('Expected the executor-provided unauthenticated HTTP proxy')
print(f'-Dhttps.proxyHost={u.hostname} -Dhttps.proxyPort={u.port} -Dhttp.proxyHost={u.hostname} -Dhttp.proxyPort={u.port} -Dhttp.nonProxyHosts=localhost|127.*')
PY
)"
    export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS} ${_VALENCE_JAVA_PROXY}"
    unset _VALENCE_JAVA_PROXY
fi

export M4="${VALENCE_CLOUD_ENV}/sysroot/usr/bin/m4"

export CPATH="${VALENCE_CLOUD_ENV}/sysroot/usr/include${CPATH:+:${CPATH}}"
# Mill's downloaded JDK must use the executor's existing CA trust bundle.
# This reuses system trust without adding a certificate or weakening TLS checks.
if [[ -r /etc/ssl/certs/java/cacerts ]]; then
    export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS} -Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts"
fi
