#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import traceback

print("=" * 60, flush=True)
print("DIAGNOSTIC TEST START", flush=True)
print("=" * 60, flush=True)

try:
    print("1. Testing basic imports...", flush=True)
    import os
    import json
    import logging
    print("   ✓ Basic imports OK", flush=True)

    print("2. Testing FastAPI...", flush=True)
    from fastapi import FastAPI
    print("   ✓ FastAPI OK", flush=True)

    print("3. Testing orchestrator...", flush=True)
    from fastapi_backend.orchestrator import ForensicOrchestrator, TaskDomain
    print("   ✓ Orchestrator OK", flush=True)

    print("4. Creating orchestrator instance...", flush=True)
    orch = ForensicOrchestrator(enable_delegations=False)
    print("   ✓ Orchestrator instance OK", flush=True)

    print("5. Creating analysis context...", flush=True)
    ctx = orch.create_analysis_context(source_filename="test.jpg")
    print(f"   ✓ Context created: {ctx.analysis_id}", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("ALL TESTS PASSED ✓", flush=True)
    print("=" * 60, flush=True)

except Exception as e:
    print("\nERROR DETECTED:", flush=True)
    print(str(e), flush=True)
    print("\nTraceback:", flush=True)
    traceback.print_exc()
    sys.exit(1)
