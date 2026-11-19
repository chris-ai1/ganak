set -euo pipefail
opts=()
while read -r name url rev; do
  dir="$RUNNER_TEMP/deps/$name"
  git init -q "$dir"
  git -C "$dir" fetch -q --depth 1 "$url" "$rev"
  git -C "$dir" checkout -q --detach FETCH_HEAD
  git -C "$dir" submodule update --init --recursive --depth 1
  opts+=("-DFETCHCONTENT_SOURCE_DIR_${name^^}=$dir")
done < pilot/deps.txt
cmake -S solver -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF "${opts[@]}"
cmake --build build --parallel 4 --target ganak-bin
mkdir pkg
cp build/ganak pkg/
ldd build/ganak | tee libraries.txt
while read -r name path; do cp -L "$path" "pkg/$name"; done < <(awk '$2=="=>" && $3 ~ /^\// && $1 !~ /^(libc\.so|libm\.so|libpthread\.so|libdl\.so|librt\.so)/ {print $1,$3}' libraries.txt)
tar -C pkg -czf solver.tgz .
