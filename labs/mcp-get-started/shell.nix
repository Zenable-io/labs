{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = [
    pkgs.uv
    pkgs.jq
    pkgs.docker
    pkgs.docker-compose
  ];

  shellHook = ''
    if ! docker info > /dev/null 2>&1; then
      echo "Docker daemon not running. Attempting to start..."
      if command -v systemctl > /dev/null 2>&1 && systemctl cat docker.service > /dev/null 2>&1; then
        sudo systemctl start docker
      else
        sudo dockerd > /tmp/dockerd.log 2>&1 &
        echo "dockerd started (logs: /tmp/dockerd.log)"
        TRIES=0
        until [ -S /var/run/docker.sock ]; do
          sleep 1
          TRIES=$((TRIES + 1))
          if [ $TRIES -ge 15 ]; then
            echo "Timed out waiting for Docker socket. Check /tmp/dockerd.log"
            break
          fi
        done
        if [ -S /var/run/docker.sock ]; then
          sudo chmod 666 /var/run/docker.sock
          echo "Docker daemon ready."
        fi
      fi
    fi
  '';
}
