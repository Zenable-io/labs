<!-- Copyright (c) 2026 Zenable, Inc. Original documentation prose only; upstream notices retain their authors. -->

# Protocol source notices

The protocol schemas derive from [Envoy's API definitions](https://github.com/envoyproxy/envoy/tree/main/api/envoy). The Status message derives from [Google RPC Status](https://github.com/googleapis/googleapis/blob/master/google/rpc/status.proto). The schema comments and generated bindings retain those upstream copyrights. Zenable's adaptations are listed below; this documentation does not claim ownership of upstream or generated code.

The upstream Apache license is distributed verbatim in [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt).

## Envoy NOTICE

```text
Envoy
Copyright The Envoy Project Authors

Licensed under Apache License 2.0.  See LICENSE for terms.
```

## Google RPC Status source notice

```text
// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
```

## Lab adaptations

- `proto/ext_proc.proto`: Modified for the Zenable lab: shared messages use shared_envoy.proto; validation and documentation annotations are omitted.
- `proto/shared_envoy.proto`: Modified for the Zenable lab: consolidated Envoy shared messages and google.rpc.Status into the envoy.service.common.v3 package.
- `jev_router/proto/ext_proc_pb2.py`: Zenable lab modification: package-qualified shared_envoy_pb2 import.
- `jev_router/proto/ext_proc_pb2_grpc.py`: Zenable lab modification: package-qualified ext_proc_pb2 import.

The other generated bindings retain their input schemas' provenance without a separate Zenable copyright claim.
